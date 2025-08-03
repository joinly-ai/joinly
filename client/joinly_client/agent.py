import asyncio
import contextlib
import logging
from typing import Self

from pydantic_ai.direct import model_request
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelRequestPart,
    ModelResponse,
    SystemPromptPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import ToolDefinition

from joinly_client.types import ToolExecutor, TranscriptSegment, Usage
from joinly_client.utils import get_prompt

logger = logging.getLogger(__name__)


class ConversationalToolAgent:
    """A conversational agent implementation to interact with joinly."""

    def __init__(
        self,
        llm: Model,
        tools: list[ToolDefinition],
        tool_executor: ToolExecutor,
        *,
        prompt: str | None = None,
    ) -> None:
        """Initialize the conversational agent with a model.

        Args:
            llm (Model): The language model to use for the agent.
            tools (list[ToolDefinition] | None): List of tools for the agent. Defaults
                to None.
            tool_executor (ToolExecutor | None): A function to execute a tool. Defaults
                to None.
            prompt (str | None): An optional prompt to initialize the agent with.
        """
        if not tools:
            msg = "At least one tool must be provided to the agent."
            raise ValueError(msg)

        self._llm = llm
        self._prompt = prompt or get_prompt()
        self._tools = tools
        self._tool_executor = tool_executor
        self._messages: list[ModelMessage] = []
        self._usage = Usage()
        self._run_task: asyncio.Task | None = None

    @property
    def usage(self) -> Usage:
        """Get the usage statistics for the agent."""
        return self._usage

    async def __aenter__(self) -> Self:
        """Enter the agent context."""
        self._messages = []
        self._usage = Usage()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Exit the agent context and clean up resources."""
        if self._run_task and not self._run_task.done():
            self._run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._run_task
        self._run_task = None

    async def on_utterance(self, segments: list[TranscriptSegment]) -> None:
        """Handle an utterance event.

        Args:
            segments (list[TranscriptSegment]): The segments of the transcript to
                process.
        """
        if self._run_task and not self._run_task.done():
            self._run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._run_task
        self._run_task = asyncio.create_task(self._run_loop(segments))

    async def _run_loop(self, segments: list[TranscriptSegment]) -> None:
        """Run the agent loop with the provided segments.

        Args:
            segments (list[TranscriptSegment]): The segments of the transcript to
                process.
        """
        for segment in segments:
            prompt = f"{segment.speaker or 'Participant'}: {segment.text}"
            self._messages.append(ModelRequest.user_text_prompt(prompt))

        while True:
            response = await self._call_llm(self._messages)
            request = await self._call_tools(response)
            self._messages.append(response)
            if request:
                self._messages.append(request)
            if self._check_finished(response, request):
                break

    async def _call_llm(self, messages: list[ModelMessage]) -> ModelResponse:
        """Call the LLM with the current messages.

        Args:
            messages (list[ModelMessage]): The messages to send to the LLM.

        Returns:
            ModelResponse: The response from the LLM.
        """
        response = await model_request(
            self._llm,
            [ModelRequest(parts=[SystemPromptPart(self._prompt)]), *messages],
            model_settings=ModelSettings(
                temperature=0.2,
                parallel_tool_calls=True,
            ),
            model_request_parameters=ModelRequestParameters(
                function_tools=[
                    ToolDefinition(
                        name="finish",
                        description=(
                            "Finish the current response. "
                            "Use this directly if no response is needed."
                        ),
                        parameters_json_schema={"properties": {}, "type": "object"},
                    ),
                    *self._tools,
                ],
                allow_text_output=False,
            ),
        )
        self._usage.add(
            "llm",
            usage={
                "input_tokens": response.usage.request_tokens or 0,
                "output_tokens": response.usage.response_tokens or 0,
            },
            meta={"model": self._llm.model_name},
        )
        return response

    async def _call_tools(self, response: ModelResponse) -> ModelRequest | None:
        """Handle the response from the LLM and call tools.

        Args:
            response (ModelResponse): The response from the LLM containing tool calls.

        Returns:
            ModelRequest | None: A ModelRequest containing the results of the tool
                calls, or None if there are no tool calls.
        """
        tool_calls = [p for p in response.parts if isinstance(p, ToolCallPart)]
        if not tool_calls:
            return None

        results: list[ModelRequestPart] = await asyncio.gather(
            *[self._call_tool(t) for t in tool_calls]
        )
        return ModelRequest(parts=results)

    async def _call_tool(self, tool_call: ToolCallPart) -> ToolReturnPart:
        """Call a tool with the given name and arguments.

        Args:
            tool_call (ToolCallPart): The tool call part containing the tool name and
                arguments.

        Returns:
            ToolReturnPart: The result of the tool call.
        """
        if tool_call.tool_name == "finish":
            return ToolReturnPart(
                tool_name="finish",
                content="",
                tool_call_id=tool_call.tool_call_id,
            )

        try:
            logger.info(
                "%s: %s",
                tool_call.tool_name,
                ", ".join(
                    f'{k}="{v}"' if isinstance(v, str) else f"{k}={v}"
                    for k, v in tool_call.args_as_dict().items()
                ),
            )
            content = await self._tool_executor(
                tool_call.tool_name, tool_call.args_as_dict()
            )
        except Exception:
            logger.exception("Error calling tool %s", tool_call.tool_name)
            content = f"Error calling tool {tool_call.tool_name}"

        logger.info("%s: %s", tool_call.tool_name, content)
        return ToolReturnPart(
            tool_name=tool_call.tool_name,
            content=content,
            tool_call_id=tool_call.tool_call_id,
        )

    def _check_finished(
        self, response: ModelResponse, request: ModelRequest | None
    ) -> bool:
        """Check if the response indicates that the agent has finished.

        Returns True if the agent called the 'finish' tool, if there are no tool
        calls, or if tool response includes speech interruption.

        Args:
            response (ModelResponse): The response from the LLM.
            request (ModelRequest): The request sent to the LLM.

        Returns:
            bool: True if the agent has finished, False otherwise.
        """
        tool_calls = [p for p in response.parts if isinstance(p, ToolCallPart)]
        tool_responses = (
            [p for p in request.parts if isinstance(p, ToolReturnPart)]
            if request
            else []
        )

        return (
            not tool_calls
            or any(p.tool_name == "finish" for p in tool_calls)
            or any(
                p
                for p in tool_responses
                if "Interrupted by detected speech" in str(p.content)
            )
        )
