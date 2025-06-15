from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field

TOutputModel = TypeVar("TOutputModel", bound=BaseModel)


class BrowserAgentTaskResponse(BaseModel, Generic[TOutputModel]):
    """A response model for browser agent tasks."""

    success: bool = Field(description="Indicates if the task was successful")
    output: TOutputModel | None = Field(description="The structured output of the task")
    message: str | None = Field(
        default=None,
        description="An optional message providing additional information about the "
        "task result",
    )

    model_config = ConfigDict(
        title="BrowserAgentTaskResponse",
        json_schema_extra={"name": "BrowserAgentTaskResponse"},
    )


class BrowserAgent(Protocol):
    """A protocol for browser agents."""

    async def connect(self, cdp_url: str) -> None:
        """Connect to the browser using the provided CDP URL.

        Args:
            cdp_url (str): The CDP URL to connect to.
        """
        ...

    async def close(self) -> None:
        """Close the browser connection."""
        ...

    async def run(
        self, task: str, output_type: type[TOutputModel]
    ) -> BrowserAgentTaskResponse[TOutputModel]:
        """Run a task in the browser.

        Args:
            task (str): The task to run in the browser.
            output_type (BaseModel): An output model to validate the
                task result against.

        Returns:
            BrowserAgentTaskResponse: A response indicating the success or failure of
                the task and potential output.
        """
        ...
