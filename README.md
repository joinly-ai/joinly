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
- **Choose-your-preferred-TTS/STT**: Modular design supports multiple services - Whisper/Deepgram for STT and Kokoro/ElevenLabs/Deepgram for TTS (and more to come...)
- **100% open-source, self-hosted and privacy-first** :rocket:

# :video_camera: Demos
### GitHub
[![GitHub Demo](https://raw.githubusercontent.com/joinly-ai/assets/main/images/others/github-demo.png)](https://youtu.be/XWolVuxw8I8)
> In this demo video, joinly answers the question 'What is Joinly?' by accessing the latest news from the web. It then creates an issue in a GitHub demo repository.
### Notion
[![Notion Demo](https://raw.githubusercontent.com/joinly-ai/assets/main/images/others/notion-demo.png)](https://www.youtube.com/watch?v=pvYqZi2KeI0)
> In this demo video, we connect joinly to our notion via MCP and let it edit the content of a page content live in the meeting. 

Any ideas what we should build next? [Write us!](https://discord.com/invite/AN5NEBkS4d) :rocket:

# :zap: Quickstart
Run joinly via Docker with a basic conversational agent client.

> [!IMPORTANT]
> **Prerequisites**: [Docker installation](https://docs.docker.com/engine/install/)

Create a new folder `joinly` or clone this repository (not mandatory for the following steps). In this directory, create a new `.env` file with a valid API key for the LLM provider you want to use, e.g. OpenAI:

> [!TIP]
> You can find the OpenAI API key [here](https://platform.openai.com/api-keys)

```Dotenv
# .env
# for OpenAI LLM
# change key and model to your desired one
JOINLY_LLM_MODEL=gpt-4o
JOINLY_LLM_PROVIDER=openai
OPENAI_API_KEY=your-openai-api-key
```

> [!NOTE]
> See [.env.example](.env.example) for complete configuration options including Anthropic (Claude) and Ollama setups. Replace the placeholder values with your actual API keys and adjust the model name as needed. Delete the placeholder values of the providers you don't use.


Pull the Docker image (~2.3GB since it packages browser and models):
```bash
docker pull ghcr.io/joinly-ai/joinly:latest
```

Launch your meeting in [Zoom](https://www.zoom.com), [Google Meet](https://meet.google.com) or Teams and let joinly join the meeting using the meeting link as `<MeetingURL>`. Then, run the following command from the folder where you created the `.env` file:
```bash  
docker run --env-file .env ghcr.io/joinly-ai/joinly:latest --client <MeetingURL>
```
> :red_circle: Having trouble getting started? Let's figure it out together on our [discord](https://discord.com/invite/AN5NEBkS4d)! 

# :technologist: Run an external client
In Quickstart, we ran the Docker Container directly as a client using `--client`. But we can also run it as a server and connect to it from outside the container, which allows us to connect other MCP servers. Here, we run an external client using the [joinly-client package](https://pypi.org/project/joinly-client/) and connect it to the joinly MCP server.

> [!IMPORTANT]
> **Prerequisites**: do the [Quickstart](#zap-quickstart) (except the last command), [install uv](https://github.com/astral-sh/uv), and open two terminals

Start the joinly server in the first terminal (note, we are not using `--client` here and forward port `8000`):
```bash  
docker run -p 8000:8000 ghcr.io/joinly-ai/joinly:latest
```

While the server is running, start the example client implementation in the second terminal window to connect to it and join a meeting:
```bash  
uvx joinly-client --env-file .env <MeetingUrl>
```

## Add MCP servers to the client
Add the tools of any MCP server to the agent by providing a JSON configuration. The configuration file can contain multiple entries under `"mcpServers"` which will all be available as tools in the meeting (see [fastmcp client docs](https://gofastmcp.com/clients/client) for config syntax):

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

Add for example a [Tavily config](examples/config_tavily.json) for web searching, then run the client using the config file, here named `config.json`:

```bash
uvx joinly-client --env-file .env --mcp-config config.json <MeetingUrl>
```

# :wrench: Configurations

Configurations can be given via env variables and/or command line args. Here is a list of common configuration options, which can be used when starting the docker container:
```bash
docker run --env-file .env -p 8000:8000 ghcr.io/joinly-ai/joinly:latest <MyOptionArgs>
```

Alternatively, you can pass `--name`, `--lang`, and [provider settings](#providers) as command line arguments using `joinly-client`, which will override settings of the server:
```bash
uvx joinly-client <MyOptionArgs> <MeetingUrl>
```

## Basic Settings

In general, the docker image provides an MCP server which is started by default. But to quickly get started, we also include a client implementation that can be used via `--client`. Note, in this case no server is started and no other client can connect to it.

```bash
# Start directly as client; default is as server, to which an external client can connect
--client <MeetingUrl>

# Change participant name (default: joinly)
--name "AI Assistant"

# Change language of TTS/STT (default: en)
# Note, availability depends on the TTS/STT provider
--lang de

# Change host & port of the joinly MCP server
--host 0.0.0.0 --port 8000
```

## Providers

### Text-to-Speech
```bash
# Kokoro (local) TTS (default)
--tts kokoro
--tts-arg voice=<VoiceName>  # optionally, set different voice

# ElevenLabs TTS, include ELEVENLABS_API_KEY in .env
--tts elevenlabs
--tts-arg voice_id=<VoiceID>  # optionally, set different voice

# Deepgram TTS, include DEEPGRAM_API_KEY in .env
--tts deepgram
--tts-arg model_name=<ModelName>  # optionally, set different model (voice)
```

### Transcription
```bash
# Whisper (local) STT (default)
--stt whisper
--stt-arg model_name=<ModelName>  # optionally, set different model (default: base), for GPU support see below

# Deepgram STT, include DEEPGRAM_API_KEY in .env
--stt deepgram
--stt-arg model_name=<ModelName>  # optionally, set different model
```

## Debugging
```bash
# Start browser with a VNC server for debugging;
# forward the port and connect to it using a VNC client
--vnc-server --vnc-server-port 5900

# Logging
-v  # or -vv, -vvv

# Help
--help
```

## GPU Support

We provide a Docker image with CUDA GPU support for running the transcription and TTS models on a GPU. To use it, you need to have the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) installed and `CUDA >= 12.6`. Then pull the CUDA-enabled image:
```bash
docker pull ghcr.io/joinly-ai/joinly:latest-cuda
```

Run as client or server with the same commands as above, but use the `joinly:{version}-cuda` image and set `--gpus all`:
```bash
# Run as server
docker run --gpus all --env-file .env -p 8000:8000 ghcr.io/joinly-ai/joinly:latest-cuda -v
# Run as client
docker run --gpus all --env-file .env ghcr.io/joinly-ai/joinly:latest-cuda -v --client <MeetingURL>
```

By default, the `joinly` image uses the Whisper model `base` for transcription, since it still runs reasonably fast on CPU. For `cuda`, it automatically defaults to `distil-large-v3` for significantly better transcription quality. You can change the model by setting `--stt-arg model_name=<model_name>` (e.g., `--stt-arg model_name=large-v3`). However, only the respective default models are packaged in the docker image, so it will start to download the model weights on container start.

# :test_tube: Create your own agent

You can also write your own agent and connect it to our joinly MCP server. See the [code examples](https://github.com/joinly-ai/joinly/client/README.md#code-usage) for the joinly-client package or the [client_example.py](examples/client_example.py) if you want a starting point that doesn't depend on our framework.

The joinly MCP server provides following tools and resources:

### Tools

- **`join_meeting`** - Join meeting with URL, participant name, and optional passcode
- **`leave_meeting`** - Leave the current meeting
- **`speak_text`** - Speak text using TTS (requires `text` parameter)
- **`send_chat_message`** - Send chat message (requires `message` parameter)
- **`mute_yourself`** - Mute microphone
- **`unmute_yourself`** - Unmute microphone
- **`get_chat_history`** - Get current meeting chat history in JSON format
- **`get_participants`** - Get current meeting participants in JSON format
- **`get_transcript`** - Get current meeting transcript in JSON format, optionally filtered by minutes
- **`get_video_snapshot`** - Get an image from the current meeting, e.g., view a current screenshare

### Resources

- **`transcript://live`** - Live meeting transcript in JSON format, including timestamps and speaker information. Subscribable for real-time updates when new utterances are added.

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
- [x] Meeting chat access
- [ ] Camera in video call with status updates
- [ ] Enable screen share during video conferences
- [ ] Participant metadata and joining/leaving
- [ ] Improve browser agent capabilities

**Conversation**
- [x] Speaker attribute for transcription
- [ ] Improve client memory: reduce token usage, allow persistence across meetings
events
- [ ] Improve End-of-Utterance/turn-taking detection
- [ ] Human approval mechanism from inside the meeting

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
