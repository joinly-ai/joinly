import os
import pathlib
import subprocess
import urllib.request

from faster_whisper import WhisperModel


def main() -> None:
    """Download assets for the project."""
    # download playwright browser
    playwright_cmd = ["playwright", "install", "--no-shell", "chromium"]
    subprocess.run(playwright_cmd, check=True)  # noqa: S603

    # download whisper model
    _ = WhisperModel(
        "tiny.en",
        device="cpu",
        compute_type="int8",
    )

    # download kokoro model and voices
    file_urls = [
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
    ]
    cache_dir = (
        pathlib.Path(os.getenv("XDG_CACHE_HOME", "~/.cache")).expanduser() / "kokoro"
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    for url in file_urls:
        fn = url.split("/")[-1]
        dst = cache_dir / fn
        if not dst.exists():
            urllib.request.urlretrieve(url, dst)  # noqa: S310


if __name__ == "__main__":
    main()
