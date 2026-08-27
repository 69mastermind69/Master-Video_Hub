import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]

# Render persistent disk will be mounted here.
DOWNLOAD_DIR = Path(
    os.getenv(
        "DOWNLOAD_DIR",
        "/var/data/downloads"
    )
)

DOWNLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True
)

MAX_CONCURRENT_DOWNLOADS = int(
    os.getenv(
        "MAX_CONCURRENT_DOWNLOADS",
        "1"
    )
)

MAX_DISK_USAGE_PERCENT = int(
    os.getenv(
        "MAX_DISK_USAGE_PERCENT",
        "90"
    )
)