from typing import Protocol

from pydantic import BaseModel, Field


class BrowserAgentTaskResponse(BaseModel):
    """A response model for browser agent tasks."""

    success: bool = Field(description="Indicates if the task was successful")
    message: str | None = Field(
        default=None,
        description="An optional message providing additional information about the "
        "task result",
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

    async def run(self, task: str) -> BrowserAgentTaskResponse:
        """Run a task in the browser.

        Args:
            task (str): The task to run in the browser.

        Returns:
            BrowserAgentTaskResponse: A response indicating the success or failure of
                the task.
        """
        ...
