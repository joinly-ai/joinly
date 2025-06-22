class Clock:
    """A simple clock class that tracks time in nanoseconds."""

    __slots__ = ("_time_ns",)

    def __init__(self) -> None:
        """Initialize the clock with a starting time of 0 nanoseconds."""
        self._time_ns = 0

    def update(self, ns: int) -> None:
        """Update the clock with a new time in nanoseconds.

        Args:
            ns (int): The new time in nanoseconds to set the clock to.

        Raises:
            ValueError: If the new time is not greater than or equal to the current time
        """
        if ns >= self._time_ns:
            self._time_ns = ns
        else:
            msg = (
                f"Cannot update clock with {ns} ns, current time is {self._time_ns} ns"
                f" ({ns} < {self._time_ns})"
            )
            raise ValueError(msg)

    @property
    def now_ns(self) -> int:
        """Get the current time in nanoseconds."""
        return self._time_ns

    @property
    def now_s(self) -> float:
        """Get the current time in seconds."""
        return self._time_ns / 1_000_000_000
