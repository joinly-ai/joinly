from typing import Protocol


class BrowserAgent(Protocol):
    """A protocol for browser agents."""

    async def connect(self, cdp_url: str) -> None:
        """Connect to the browser using the provided CDP URL."""
        ...

    async def close(self) -> None:
        """Close the browser connection."""
        ...

    async def run(self, task: str) -> None:
        """Run a task in the browser."""
        ...
