import asyncio
import os
import re
from pathlib import Path

import yt_dlp

from config import DOWNLOAD_DIR


def safe_filename(name: str) -> str:
    name = re.sub(
        r'[\\/*?:"<>|]',
        "_",
        name
    )

    name = re.sub(
        r"\s+",
        " ",
        name
    ).strip()

    return name[:180] or "video"


def format_bytes(value):
    if not value:
        return "0 B"

    value = float(value)

    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024:
            return f"{value:.1f} {unit}"

        value /= 1024

    return f"{value:.1f} PB"


def format_duration(seconds):
    if not seconds:
        return "Unknown"

    seconds = int(seconds)

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60

    if hours:
        return (
            f"{hours:02d}:"
            f"{minutes:02d}:"
            f"{seconds:02d}"
        )

    return (
        f"{minutes:02d}:"
        f"{seconds:02d}"
    )


class DownloadState:

    def __init__(self):
        self.status = "starting"
        self.info = {}
        self.downloaded = 0
        self.total = 0
        self.speed = 0
        self.eta = None
        self.filename = None
        self.error = None


def build_options(state):

    def progress_hook(data):

        state.status = data.get(
            "status",
            "unknown"
        )

        state.downloaded = (
            data.get("downloaded_bytes")
            or 0
        )

        state.total = (
            data.get("total_bytes")
            or data.get("total_bytes_estimate")
            or 0
        )

        state.speed = (
            data.get("speed")
            or 0
        )

        state.eta = data.get("eta")

        if data.get("filename"):
            state.filename = data["filename"]

    return {

        # Best available video + audio.
        "format": "bv*+ba/b",

        # FFmpeg merge.
        "merge_output_format": "mp4",

        # Never load the complete video into RAM.
        "outtmpl": str(
            DOWNLOAD_DIR /
            "%(title)s.%(ext)s"
        ),

        # Resume incomplete downloads.
        "continuedl": True,

        # Retry temporary failures.
        "retries": 10,
        "fragment_retries": 10,

        # Long-video friendly timeout.
        "socket_timeout": 60,

        # Progress.
        "progress_hooks": [
            progress_hook
        ],

        "noplaylist": True,

        "quiet": True,
        "no_warnings": True,
    }


async def download_video(
    url: str,
    state: DownloadState
):

    def worker():

        options = build_options(state)

        with yt_dlp.YoutubeDL(
            options
        ) as ydl:

            info = ydl.extract_info(
                url,
                download=True
            )

            state.info = info

            filename = (
                info.get("_filename")
                or ydl.prepare_filename(info)
            )

            base = os.path.splitext(
                filename
            )[0]

            candidates = [
                filename,
                base + ".mp4",
                base + ".mkv",
                base + ".webm",
                base + ".mov",
            ]

            for path in candidates:

                if os.path.exists(path):
                    return path

            return filename

    try:

        state.status = "downloading"

        filepath = await asyncio.to_thread(
            worker
        )

        state.status = "finished"

        return filepath

    except Exception as exc:

        state.status = "error"
        state.error = str(exc)

        raise