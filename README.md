<p align="center">
  <a href="https://github.com/joinly-ai/assets">
    <picture>
      <source
        media="(prefers-color-scheme: dark)"
        srcset="https://raw.githubusercontent.com/joinly-ai/assets/main/animations/logo-animations/joinly_logo_black_cropped.gif"
      >
      <img
        alt="Animated joinly.ai logo"
        src="https://raw.githubusercontent.com/joinly-ai/assets/main/animations/logo-animations/joinly_logo_light_cropped.gif"
      >
    </picture>
  </a>
</p>

[![GitHub Release](https://img.shields.io/github/v/release/joinly-ai/joinly?sytle=flat&label=Release&labelColor=black&color=%237B2CBF)](https://github.com/joinly-ai/joinly/releases)
[![GitHub License](https://img.shields.io/github/license/joinly-ai/joinly?style=flat&label=License&labelColor=black&color=%237B2CBF)](LICENSE) 
[![GitHub Repo stars](https://img.shields.io/github/stars/joinly-ai/joinly?style=flat&logo=github&logoColor=white&label=Stars&labelColor=black&color=7B2CBF)](https://github.com/joinly-ai/joinly) 
[![Discord](https://img.shields.io/discord/1377431745632145500?style=flat&logo=discord&logoColor=white&label=Discord&labelColor=black&color=7B2CBF)](https://discord.com/invite/AN5NEBkS4d) 
[![GitHub Discussions](https://img.shields.io/github/discussions/joinly-ai/joinly?style=flat&labelColor=black&label=Discussions&color=%237B2CBF)](https://github.com/joinly-ai/joinly/discussions)

<h1 align="center">Make your meetings accessible to AI Agents 🤖</h1>

**joinly.ai** is a connector middleware designed to enable AI agents to join and actively participate in video calls. Through its MCP server, joinly.ai provides essential [meeting tools](#tools) and [resources](#resources) that can equip any AI agent with the skills to perform tasks and interact with you in real time during your meetings.

> Want to dive right in? Jump to the [Quickstart](#zap-quickstart)!
> Want to know more? Visit our [website](https://joinly.ai/)!


# :sparkles: Features
- **Live Interaction**: Lets your agents execute tasks and respond in real-time by voice or chat within your meetings
- **Conversational flow**: Built-in logic that ensures natural conversations by handling interruptions and multi-speaker interactions
- **Cross-platform**: Join Google Meet, Zoom, and Microsoft Teams (or any available over the browser)
- **Bring-your-own-LLM**: Works with all LLM providers (also locally with Ollama)
- **Choose-your-preferred-TTS/STT**: Modular design supports multiple services - Whisper/Deepgram for STT and Kokoro/Deepgram for TTS (and more to come...)
- **100% open-source, self-hosted and privacy-first** :rocket:

# :video_camera: Demos
### Websearch
[![Tavily Demo](https://raw.githubusercontent.com/joinly-ai/assets/main/images/others/tavily-demo.png)](https://www.youtube.com/watch?v=MbIDuf7a-_8)
> In this demo video, you can see joinly anwsering simple questions by accessing the latest news from the web.
### Notion
[![Notion Demo](https://raw.githubusercontent.com/joinly-ai/assets/main/images/others/notion-demo.png)](https://www.youtube.com/watch?v=pvYqZi2KeI0)
> In this demo video, we connect joinly to our notion via MCP and let it edit the content of a page content live in the meeting. 

Any ideas what we should build next? [Write us!](https://discord.com/invite/AN5NEBkS4d) :rocket:

# :zap: Quickstart
Run joinly via Docker with a basic conversational agent client.

> [!IMPORTANT]
> **Prerequisites**: [Docker installation](https://docs.docker.com/engine/install/)

Clone this repository:
```bash
git clone https://github.com/joinly-ai/joinly
cd joinly
```

Create a new `.env` file in the project root with your API keys. See [.env.example](.env.example) for complete configuration options including Anthropic (Claude) and Ollama setups. Replace the placeholder values with your actual API keys and adjust the model name as needed.

> [!NOTE]
> Remember not to copy the [.env.example](.env.example) exactly. Instead, delete the placeholder values of the providers you don't use.

```Dotenv
# .env
# for OpenAI LLM
# change key and model to your desired one
JOINLY_MODEL_NAME=gpt-4o
JOINLY_MODEL_PROVIDER=openai
OPENAI_API_KEY=your-openai-api-key
```
> [!TIP]
> You can find the OpenAI API key [here](https://platform.openai.com/api-keys)

Pull the Docker image (~2.3GB since it packages browser and models):
```bash
docker pull ghcr.io/joinly-ai/joinly:latest
```

Launch your meeting in [Zoom](https://www.zoom.com), [Google Meet](https://meet.google.com) or Teams and let joinly join the meeting using the meeting link as `<MeetingURL>`:
```bash  
docker run --env-file .env ghcr.io/joinly-ai/joinly:latest -v --client <MeetingURL>
```
> :red_circle: Having trouble getting started? Let's figure it out together on our [discord](https://discord.com/invite/AN5NEBkS4d)! 

# :technologist: Run an external client
In Quickstart, we ran the Docker Container directly as a client using `--client`. But we can also run it as a server and connect to it from outside the container, which allows us to control the entire logic of our agent. Here, we run an external client implementation and connect it to the joinly MCP server.

> [!IMPORTANT]
> **Prerequisites**: do the [Quickstart](#zap-quickstart) (except the last command), [install uv](https://github.com/astral-sh/uv), and open two terminals

Start the joinly server in the first terminal (note, we are not using `--client` here and forward port `8000`):
```bash  
docker run --env-file .env -p 8000:8000 ghcr.io/joinly-ai/joinly:latest -v
```

While the server is running, start the example client implementation in the second terminal window to connect to it and join a meeting:
```bash  
uv run examples/client_example.py --mcp-url http://127.0.0.1:8000/mcp/ <MeetingUrl>
```

## Add MCP servers to the client
Add the tools of any MCP server to the example client by providing a JSON configuration. In [config_tavily.json](examples/config_tavily.json), we add the Tavily MCP server for web search functionality (requires `TAVILY_API_KEY` in `.env`):

```json
{
    "mcpServers": {
        "tavily": {
            "command": "npx",
            "args": ["-y", "tavily-mcp@0.2.2"]
        }
    }
}
```

You can also add multiple entries under `"mcpServers"` which will all be available as tools in the meeting (see [fastmcp client docs](https://gofastmcp.com/clients/client) for config syntax). Then, run the client using the config file (`--config <file>`):

```bash  
uv run examples/client_example.py --mcp-url http://127.0.0.1:8000/mcp/ --config examples/config_tavily.json <MeetingUrl>
```

# :wrench: Configurations

```bash
# Start server (default), connect via own client
uv run joinly

# Start directly as client
uv run joinly --client <MeetingUrl>

# Change name (default: joinly)
uv run joinly --name "AI Assistant"

# Change TTS provider
uv run joinly --tts kokoro # default: local Kokoro
uv run joinly --tts deepgram # include DEEPGRAM_API_KEY in your .env

# Change Transcription (STT) provider
uv run joinly --stt whisper # default: local Whisper (faster-whisper)
uv run joinly --stt deepgram # include DEEPGRAM_API_KEY in your .env

# Change host & port of the joinly MCP server
uv run joinly --host 0.0.0.0 --port 8000

# Start browser with a VNC server for debugging;
# forward the port and connect to it using a VNC client
uv run joinly --vnc-server --vnc-server-port 5900

# Use browser agent as fallback/to join any meeting website (Experimental)
# Note: this requires npx (not installed in the docker but in devcontainer),
# LLM is selected using the same ENV variables as described earlier
uv run joinly --browser-agent playwright-mcp

# Logging
uv run joinly -v  # or -vv, -vvv

# Help
uv run joinly --help
```
# :test_tube: Create your own client

You can also write your own client from scratch and connect it to our joinly MCP server. See [client_example.py](examples/client_example.py) for a starting point.

The joinly MCP server provides following tools and resources:

### Tools

- **`join_meeting`** - Join meeting with URL, participant name, and optional passcode
- **`leave_meeting`** - Leave the current meeting
- **`speak_text`** - Speak text using TTS (requires `text` parameter)
- **`send_chat_message`** - Send chat message (requires `message` parameter)
- **`mute_yourself`** - Mute microphone
- **`unmute_yourself`** - Unmute microphone
- *more soon...*

### Resources

- `transcript://live` - Live meeting transcript in JSON format. Subscribable for real-time updates when new utterances are added.

# :building_construction: Developing joinly.ai

For development we recommend using the development container, which installs all necessary dependencies. To get started, install the DevContainer Extension for Visual Studio Code, open the repository and choose **Reopen in Container**.

<img src="https://raw.githubusercontent.com/joinly-ai/assets/main/images/others/reopen_in_container.png" width="500" alt="Reopen in Devcontainer">

The installation can take some time, since it downloads all packages as well as models for Whisper/Kokoro and the Chromium browser. At the end, it automatically invokes the [download_assets.py](scripts/download_assets.py) script. If you see errors like `Missing kokoro-v1.0.onnx`, run this script manually using:
```bash
uv run scripts/download_assets.py
```

We'd love to see what you are using it for or building with it. Showcase your work on our [discord](https://discord.com/invite/AN5NEBkS4d)
# :pencil2: Roadmap

**Meeting**
- [ ] Camera in video call with status updates
- [ ] Enable screen share during video conferences
- [ ] Meeting chat as resource
- [ ] Participant metadata and joining/leaving
- [ ] Improve browser agent capabilities

**Conversation**
- [ ] Improve client memory: reduce token usage, allow persistence across meetings
events
- [ ] Improve End-of-Utterance/turn-taking detection
- [ ] Human approval mechanism from inside the meeting
- [ ] Speaker diarization

**Integrations**
- [ ] Showcase how to add agents using the A2A protocol
- [ ] Add more provider integrations (STT, TTS)
- [ ] Integrate meeting platform SDKs
- [ ] Add alternative open-source meeting provider
- [ ] Add support for Speech2Speech models
  
# :busts_in_silhouette: Contributing
Contributions are always welcome! Feel free to open issues for bugs or submit a feature request. We'll do our best to review all contributions promptly and help merge your changes.

Please check our [Roadmap](#pencil2-roadmap) and don't hesitate to reach out to us!

# :memo: License
This project is licensed under the MIT License ‒ see the [LICENSE](LICENSE) file for details.

# :speech_balloon: Getting help
If you have questions or feedback, or if you would like to chat with the maintainers or other community members, please use the following links:
-  [Join our Discord](https://discord.com/invite/AN5NEBkS4d)
-  [Explore our GitHub Discussions](https://github.com/joinly-ai/joinly/discussions)

<div align="center">
Made with ❤️ in Osnabrück
 </div>
