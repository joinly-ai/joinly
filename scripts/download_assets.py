import argparse
import logging
import os
import pathlib
import subprocess
import sys
import urllib.request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def download_playwright() -> None:
    """Download Playwright browser."""
    logger.info("Downloading Playwright browser")
    playwright_cmd = ["playwright", "install", "--no-shell", "chromium"]
    subprocess.run(playwright_cmd, check=True)  # noqa: S603
    logger.info("Playwright browser downloaded successfully")


def download_whisper(model_name: str) -> None:
    """Download Whisper model."""
    from faster_whisper import WhisperModel

    logger.info("Downloading Whisper model %s", model_name)
    _ = WhisperModel(model_name)
    logger.info("Whisper model downloaded successfully")


def download_assets(
    cache_subdir: str,
    file_urls: list[str],
    description: str | None = None,
) -> pathlib.Path:
    """Download a set of assets into a cache directory.

    Args:
        cache_subdir: subdirectory under XDG_CACHE_HOME (default ~/.cache) to store
            assets.
        file_urls: list of URLs pointing to the files to download.
        description: optional description for logging (e.g., "Kokoro model and voices").

    Returns:
        Path to the cache directory containing the downloaded assets.
    """
    if description:
        logger.info("Downloading %s", description)
    cache_dir = (
        pathlib.Path(os.getenv("XDG_CACHE_HOME", "~/.cache")).expanduser()
        / cache_subdir
    )
    cache_dir.mkdir(parents=True, exist_ok=True)

    bar_len = 40  # width of the textual progress bar

    for url in file_urls:
        filename = url.rsplit("/", 1)[-1]
        dest = cache_dir / filename
        if dest.exists():
            logger.info("[cached] %s", filename)
            continue

        def _reporthook(block_num: int, block_size: int, total_size: int) -> None:
            if total_size <= 0 or not sys.stdout.isatty():
                return
            downloaded = block_num * block_size
            ratio = min(downloaded / total_size, 1.0)
            filled = int(bar_len * ratio)
            bar = "=" * filled + "-" * (bar_len - filled)
            sys.stdout.write(f"\r{filename} [{bar}] {ratio * 100:6.2f}%")  # noqa: B023
            sys.stdout.flush()
            if downloaded >= total_size:
                sys.stdout.write("\n")

        logger.info("Downloading %s", filename)
        if not url.startswith(("http:", "https:")):
            msg = f"URL must start with 'http:' or 'https:'. Got: {url}"
            raise ValueError(msg)
        urllib.request.urlretrieve(url, dest, _reporthook)  # noqa: S310
        logger.info("Saved %s to %s", filename, dest)

    if description:
        logger.info("%s downloaded successfully", description)
    return cache_dir


def download_silero_vad() -> None:
    """Download Silero VAD model."""
    file_urls = [
        "https://raw.githubusercontent.com/snakers4/silero-vad/v5.0/files/silero_vad.onnx",
        "https://raw.githubusercontent.com/snakers4/silero-vad/master/LICENSE",
    ]
    download_assets("silero", file_urls, "Silero VAD v5 ONNX model")


def download_kokoro() -> None:
    """Download Kokoro model and voices."""
    file_urls = [
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
        "https://raw.githubusercontent.com/thewh1teagle/kokoro-onnx/main/LICENSE",
        "https://www.apache.org/licenses/LICENSE-2.0.txt",
    ]
    download_assets("kokoro", file_urls, "Kokoro v1.0 ONNX model and voices")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Download assets for the project.")
    parser.add_argument(
        "--assets",
        nargs="*",
        choices=["playwright", "whisper", "kokoro", "silero", "all"],
        default=["all"],
        help="Specify which assets to download (default: all)",
    )
    parser.add_argument(
        "--whisper-model",
        type=str,
        default="base",
        help="Whisper model to download (default: base)",
    )
    return parser.parse_args()


def main() -> None:
    """Download assets for the project."""
    args = parse_args()

    assets = args.assets

    if "playwright" in assets or "all" in assets:
        download_playwright()
    if "whisper" in assets or "all" in assets:
        download_whisper(model_name=args.whisper_model)
    if "silero" in assets or "all" in assets:
        download_silero_vad()
    if "kokoro" in assets or "all" in assets:
        download_kokoro()


if __name__ == "__main__":
    main()
