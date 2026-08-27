import asyncio
import json
import os
import re
import subprocess
from pathlib import Path

from config import DOWNLOAD_DIR


def format_bytes(value):
    if not value:
        return "0 B"

    value = float(value)

    for unit in ("B", "KB", "MB", "GB", "TB"):
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
    seconds %= 60

    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def safe_filename(name):
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

        self.cancelled = False

        self.process = None


async def get_video_info(url):

    """
    Fetch metadata only.
    Does NOT download the video.
    """

    process = await asyncio.create_subprocess_exec(
        "yt-dlp",
        "--dump-single-json",
        "--no-playlist",
        "--no-warnings",
        "--quiet",
        url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await process.communicate()

    if process.returncode != 0:

        error = stderr.decode(
            "utf-8",
            errors="replace"
        ).strip()

        raise RuntimeError(
            error or "Could not read video information."
        )

    try:

        return json.loads(
            stdout.decode(
                "utf-8",
                errors="replace"
            )
        )

    except json.JSONDecodeError:

        raise RuntimeError(
            "Invalid metadata returned by yt-dlp."
        )


def parse_progress(line, state):

    """
    Parse yt-dlp progress output.

    Example:

    [download]  25.5% of 1.20GiB at 5.5MiB/s ETA 03:10
    """

    line = line.strip()

    percentage = re.search(
        r"(\d+(?:\.\d+)?)%",
        line
    )

    if percentage:

        try:

            percent = float(
                percentage.group(1)
            )

            if state.total:
                state.downloaded = (
                    state.total
                    * percent
                    / 100
                )

        except Exception:
            pass

    speed = re.search(
        r"at\s+([0-9.]+\s*[KMGTP]?i?B/s)",
        line,
        re.IGNORECASE
    )

    if speed:

        speed_text = speed.group(1)

        match = re.match(
            r"([0-9.]+)\s*([KMGTP]?i?)B/s",
            speed_text,
            re.IGNORECASE
        )

        if match:

            number = float(
                match.group(1)
            )

            unit = match.group(2).upper()

            multipliers = {
                "": 1,
                "K": 1024,
                "KI": 1024,
                "M": 1024 ** 2,
                "MI": 1024 ** 2,
                "G": 1024 ** 3,
                "GI": 1024 ** 3,
                "T": 1024 ** 4,
                "TI": 1024 ** 4,
            }

            state.speed = (
                number
                * multipliers.get(
                    unit,
                    1
                )
            )

    eta = re.search(
        r"ETA\s+(\d+:\d+)",
        line,
        re.IGNORECASE
    )

    if eta:

        parts = eta.group(1).split(":")

        try:

            if len(parts) == 2:

                minutes = int(parts[0])
                seconds = int(parts[1])

                state.eta = (
                    minutes * 60
                    + seconds
                )

        except Exception:
            pass


async def download_video(
    url,
    state
):

    Path(DOWNLOAD_DIR).mkdir(
        parents=True,
        exist_ok=True
    )

    state.status = "downloading"

    output_template = str(
        Path(DOWNLOAD_DIR)
        / "%(title)s.%(ext)s"
    )

    command = [
        "yt-dlp",

        "--newline",

        "--no-playlist",

        "--retries",
        "10",

        "--fragment-retries",
        "10",

        "--socket-timeout",
        "60",

        "--continue",

        "--no-overwrites",

        "-f",
        "bv*+ba/b",

        "--merge-output-format",
        "mp4",

        "-o",
        output_template,

        url,
    ]

    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    state.process = process

    output_lines = []

    try:

        while True:

            line = await process.stdout.readline()

            if not line:

                break

            text = line.decode(
                "utf-8",
                errors="replace"
            ).strip()

            if text:

                output_lines.append(text)

                if len(output_lines) > 100:
                    output_lines.pop(0)

                parse_progress(
                    text,
                    state
                )

            # User cancelled the job.
            if state.cancelled:

                try:
                    process.terminate()

                except ProcessLookupError:
                    pass

                try:

                    await asyncio.wait_for(
                        process.wait(),
                        timeout=5
                    )

                except asyncio.TimeoutError:

                    try:
                        process.kill()

                    except ProcessLookupError:
                        pass

                state.status = "cancelled"

                return None

        return_code = await process.wait()

        if state.cancelled:

            state.status = "cancelled"

            return None

        if return_code != 0:

            error = "\n".join(
                output_lines[-20:]
            )

            state.error = error

            state.status = "error"

            raise RuntimeError(
                error or "yt-dlp failed."
            )

        # Find the newest media file.
        files = [
            p for p in Path(
                DOWNLOAD_DIR
            ).iterdir()
            if p.is_file()
        ]

        if not files:

            raise FileNotFoundError(
                "Downloaded file was not found."
            )

        files.sort(
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        filepath = files[0]

        state.filename = str(
            filepath
        )

        state.status = "finished"

        return str(filepath)

    except asyncio.CancelledError:

        state.cancelled = True

        try:

            process.terminate()

        except ProcessLookupError:
            pass

        try:

            await asyncio.wait_for(
                process.wait(),
                timeout=5
            )

        except asyncio.TimeoutError:

            try:
                process.kill()

            except ProcessLookupError:
                pass

        state.status = "cancelled"

        raise

    finally:

        state.process = None
