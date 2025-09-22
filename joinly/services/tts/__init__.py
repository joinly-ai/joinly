# from .kokoro import KokoroTTS
# from .elevenlabs import ElevenlabsTTS
# from .deepgram import DeepgramTTS
# from .resemble import ResembleTTS

# PROVIDERS = {
#     "kokoro": KokoroTTS,
#     "elevenlabs": ElevenlabsTTS,
#     "deepgram": DeepgramTTS,
#     "resemble": ResembleTTS,
# }

# def get_tts_provider(name: str, **args) -> TTS:
#     if name not in PROVIDERS:
#         raise ValueError(f"Unknown TTS provider: {name}")
#     return PROVIDERS[name].from_args(args)