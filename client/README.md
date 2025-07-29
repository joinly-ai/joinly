
# joinly-client: Client for a conversational meeting agent used with joinly

## Command line usage

Connect to a running joinly server and join a meeting:
```bash
uvx joinly-client --joinly-url http://localhost:8000/mcp/ <MeetingUrl>
```

Add other MCP servers using a [configuration file](https://gofastmcp.com/clients/client#configuration-based-clients):
```json
{
    "mcpServers": {
        "localServer": {
            "command": "npx",
            "args": ["-y", "package@0.1.0"]
        },
        "remoteServer": {
            "url": "http://mcp.example.com",
            "auth": "oauth"
        }
    }
}
```

```bash
uvx joinly-client --mcp-config config.json <MeetingUrl>
```

## Code usage

Direct use of run function:
```python
import joinly_client.run

async def main():
    await joinly_client.run(
        joinly_url="http://localhost:8000/mcp/",
        meeting_url="<MeetingUrl>",
        llm_provider="openai",
        llm_model="gpt-4o-mini",
        prompt="You are joinly, a...",
        name="joinly",
        name_trigger=False,
        mcp_config=None,  # MCP servers configuration (dict)
        settings=None,  # settings propagated to joinly server (dict)
    )
```

Or with only the client and a custom agent:
```python
import asyncio
from joinly_client import JoinlyClient
from joinly_client.types import TranscriptSegment


async def main():
    client = JoinlyClient(
        joinly_url="http://localhost:8000/mcp/",
        name="joinly",
        name_trigger=False,
        settings=None,
    )
    # optionally, load all tools from the server
    tool_list = await client.client.list_tools()

    async def on_utterance(segments: list[TranscriptSegment]) -> None:
        for segment in segments:
            print(f"Received utterance: {segment.text}")
            if "marco" in segment.text.lower():
                await client.client.call_tool("speak_text", {"text": "Polo!"})
    client.add_utterance_callback(on_utterance)

    async with client:
        await client.join_meeting("<MeetingUrl>")
        await asyncio.Event().wait()  # wait until cancelled
```
