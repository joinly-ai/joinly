import argparse
import logging
import os
import pathlib
import subprocess
import sys
import urllib.request

from faster_whisper import WhisperModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def download_playwright() -> None:
    """Download Playwright browser."""
    logger.info("Downloading Playwright browser")
    playwright_cmd = ["playwright", "install", "--no-shell", "chromium"]
    subprocess.run(playwright_cmd, check=True)  # noqa: S603
    logger.info("Playwright browser downloaded successfully")


def download_whisper() -> None:
    """Download Whisper model."""
    logger.info("Downloading Whisper model")
    _ = WhisperModel(
        "tiny.en",
        device="cpu",
        compute_type="int8",
    )
    logger.info("Whisper model downloaded successfully")


def download_kokoro() -> None:
    """Download Kokoro model and voices."""
    logger.info("Downloading Kokoro model and voices")
    file_urls = [
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
        "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
    ]
    cache_dir = (
        pathlib.Path(os.getenv("XDG_CACHE_HOME", "~/.cache")).expanduser() / "kokoro"
    )
    cache_dir.mkdir(parents=True, exist_ok=True)

    bar_len = 40  # width of the textual bar

    for url in file_urls:
        fn = url.split("/")[-1]
        dst = cache_dir / fn
        if dst.exists():
            logger.info("[cached] %s", fn)
            continue

        # progress callback used by urlretrieve
        def _reporthook(block_num: int, block_size: int, total_size: int) -> None:
            if total_size <= 0 or not sys.stdout.isatty():
                return
            downloaded = block_num * block_size
            ratio = min(downloaded / total_size, 1.0)
            filled = int(bar_len * ratio)
            bar = "=" * filled + "-" * (bar_len - filled)
            sys.stdout.write(f"\r{fn} [{bar}] {ratio * 100:6.2f}%")  # noqa: B023
            sys.stdout.flush()
            if downloaded >= total_size:  # ensure newline when done
                sys.stdout.write("\n")

        urllib.request.urlretrieve(url, dst, _reporthook)  # noqa: S310

    logger.info("Kokoro model and voices downloaded successfully")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Download assets for the project.")
    parser.add_argument(
        "--assets",
        nargs="*",
        choices=["playwright", "whisper", "kokoro", "all"],
        default=["all"],
        help="Specify which assets to download (default: all)",
    )
    return parser.parse_args()


def main() -> None:
    """Download assets for the project."""
    args = parse_args()

    assets = args.assets

    # If "all" is specified, download all assets
    if "all" in assets:
        download_playwright()
        download_whisper()
        download_kokoro()
    else:
        # Download only the specified assets
        if "playwright" in assets:
            download_playwright()
        if "whisper" in assets:
            download_whisper()
        if "kokoro" in assets:
            download_kokoro()


if __name__ == "__main__":
    main()
