import asyncio

import click

from meeting_agent import MeetingSession


@click.command()
@click.option(
    "-n",
    "--participant-name",
    type=str,
    help="The meeting participant name.",
    envvar="PARTICIPANT_NAME",
    default="Kevin",
)
@click.argument("meeting-url", type=str, envvar="MEETING_URL")
def cli(meeting_url: str, participant_name: str) -> None:
    """Start the meeting session."""
    asyncio.run(run_meeting_session(meeting_url, participant_name))


async def run_meeting_session(meeting_url: str, participant_name: str) -> None:
    """Run the meeting session."""
    session = MeetingSession(meeting_url=meeting_url, participant_name=participant_name)
    await session.run()
