import asyncio
import json
import re
from pathlib import Path

from config import DOWNLOAD_DIR


# =========================================================
# HELPERS
# =========================================================

def format_bytes(value):
    if not value:
        return "0 B"

    try:
        value = float(value)
    except (TypeError, ValueError):
        return "0 B"

    units = ["B", "KB", "MB", "GB", "TB"]

    for unit in units:
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024

    return f"{value:.1f} PB"


def format_duration(seconds):
    if seconds is None:
        return "Unknown"

    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return "Unknown"

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60

    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    return f"{minutes:02d}:{seconds:02d}"


def safe_filename(name):
    """
    Used only when a human-readable filename is needed.
    Downloaded files themselves use video ID to avoid
    'File name too long' errors.
    """

    if not name:
        return "video"

    name = re.sub(
        r'[\\/*?:"<>|]',
        "_",
        str(name)
    )

    name = re.sub(
        r"\s+",
        " ",
        name
    ).strip()

    return name[:100] or "video"


# =========================================================
# ERROR TYPES
# =========================================================

class DownloaderError(Exception):
    pass


class YouTubeVerificationError(
    DownloaderError
):
    pass


class PrivateVideoError(
    DownloaderError
):
    pass


class UnsupportedVideoError(
    DownloaderError
):
    pass


class DownloadCancelledError(
    DownloaderError
):
    pass


# =========================================================
# DOWNLOAD STATE
# =========================================================

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


# =========================================================
# ERROR PARSER
# =========================================================

def parse_ytdlp_error(error_text):

    if not error_text:
        return DownloaderError(
            "Unknown downloader error."
        )

    text = error_text.lower()

    # -----------------------------------------------------
    # YouTube verification
    # -----------------------------------------------------

    youtube_patterns = [
        "sign in to confirm you're not a bot",
        "sign in to confirm you’re not a bot",
        "confirm you're not a bot",
        "confirm you’re not a bot",
        "use --cookies-from-browser",
        "use --cookies for the authentication",
    ]

    if any(
        pattern in text
        for pattern in youtube_patterns
    ):

        return YouTubeVerificationError(
            "YouTube is requiring additional "
            "verification for this request."
        )

    # -----------------------------------------------------
    # Private / unavailable
    # -----------------------------------------------------

    private_patterns = [
        "this video is private",
        "private video",
        "video unavailable",
        "this video isn't available",
        "this video is not available",
        "has been removed",
    ]

    if any(
        pattern in text
        for pattern in private_patterns
    ):

        return PrivateVideoError(
            "This video is private or unavailable."
        )

    # -----------------------------------------------------
    # Unsupported URL
    # -----------------------------------------------------

    unsupported_patterns = [
        "unsupported url",
        "no suitable extractor",
        "is not a valid url",
    ]

    if any(
        pattern in text
        for pattern in unsupported_patterns
    ):

        return UnsupportedVideoError(
            "This URL is not supported."
        )

    # -----------------------------------------------------
    # Generic error
    # -----------------------------------------------------

    return DownloaderError(
        error_text.strip()
        or "Download failed."
    )


# =========================================================
# GET VIDEO INFO
# =========================================================

async def get_video_info(url):

    command = [
        "yt-dlp",

        "--dump-single-json",

        "--no-playlist",

        "--no-warnings",

        "--quiet",

        # Network reliability
        "--socket-timeout",
        "60",

        "--retries",
        "5",

        # Prefer IPv4
        "--force-ipv4",

        url,
    ]

    process = await asyncio.create_subprocess_exec(
        *command,

        stdout=asyncio.subprocess.PIPE,

        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await process.communicate()

    if process.returncode != 0:

        error_text = stderr.decode(
            "utf-8",
            errors="replace"
        )

        raise parse_ytdlp_error(
            error_text
        )

    try:

        return json.loads(
            stdout.decode(
                "utf-8",
                errors="replace"
            )
        )

    except json.JSONDecodeError:

        raise DownloaderError(
            "Could not read video information."
        )


# =========================================================
# PROGRESS PARSER
# =========================================================

def parse_progress(line, state):

    line = line.strip()

    # -----------------------------------------------------
    # Percentage
    # -----------------------------------------------------

    percentage_match = re.search(
        r"(\d+(?:\.\d+)?)%",
        line
    )

    if percentage_match:

        try:

            percentage = float(
                percentage_match.group(1)
            )

            if state.total:

                state.downloaded = (
                    state.total
                    * percentage
                    / 100
                )

        except (
            TypeError,
            ValueError
        ):

            pass

    # -----------------------------------------------------
    # Total size
    # -----------------------------------------------------

    size_match = re.search(
        r"of\s+([0-9.]+\s*[KMGTP]?i?B)",
        line,
        re.IGNORECASE
    )

    if size_match:

        size_text = size_match.group(1)

        match = re.match(
            r"([0-9.]+)\s*([KMGTP]?i?)B",
            size_text,
            re.IGNORECASE
        )

        if match:

            try:

                number = float(
                    match.group(1)
                )

                unit = (
                    match.group(2)
                    .upper()
                )

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

                state.total = (
                    number
                    * multipliers.get(
                        unit,
                        1
                    )
                )

            except (
                TypeError,
                ValueError
            ):

                pass

    # -----------------------------------------------------
    # Downloaded amount
    # -----------------------------------------------------

    downloaded_match = re.search(
        r"\[download\]\s+([0-9.]+)([KMGTP]?i?)B",
        line,
        re.IGNORECASE
    )

    if downloaded_match:

        try:

            number = float(
                downloaded_match.group(1)
            )

            unit = (
                downloaded_match.group(2)
                .upper()
            )

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

            state.downloaded = (
                number
                * multipliers.get(
                    unit,
                    1
                )
            )

        except (
            TypeError,
            ValueError
        ):

            pass

    # -----------------------------------------------------
    # Speed
    # -----------------------------------------------------

    speed_match = re.search(
        r"at\s+([0-9.]+\s*[KMGTP]?i?B/s)",
        line,
        re.IGNORECASE
    )

    if speed_match:

        speed_text = speed_match.group(1)

        match = re.match(
            r"([0-9.]+)\s*([KMGTP]?i?)B/s",
            speed_text,
            re.IGNORECASE
        )

        if match:

            try:

                number = float(
                    match.group(1)
                )

                unit = (
                    match.group(2)
                    .upper()
                )

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

            except (
                TypeError,
                ValueError
            ):

                pass

    # -----------------------------------------------------
    # ETA
    # -----------------------------------------------------

    eta_match = re.search(
        r"ETA\s+(\d+:\d+)",
        line,
        re.IGNORECASE
    )

    if eta_match:

        try:

            minutes, seconds = map(
                int,
                eta_match.group(1).split(":")
            )

            state.eta = (
                minutes * 60
                + seconds
            )

        except (
            ValueError,
            TypeError
        ):

            pass


# =========================================================
# FIND DOWNLOADED FILE
# =========================================================

def find_downloaded_file(
    before_files,
    output_directory
):

    output_directory = Path(
        output_directory
    )

    files = [
        p
        for p in output_directory.iterdir()
        if p.is_file()
    ]

    new_files = [
        p
        for p in files
        if p not in before_files
    ]

    if new_files:
        files = new_files

    if not files:
        return None

    files.sort(
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    return files[0]


# =========================================================
# DOWNLOAD VIDEO
# =========================================================

async def download_video(
    url,
    state
):

    output_directory = Path(
        DOWNLOAD_DIR
    )

    output_directory.mkdir(
        parents=True,
        exist_ok=True
    )

    state.status = "downloading"

    before_files = set(
        output_directory.iterdir()
    )

    # =====================================================
    # IMPORTANT
    # =====================================================
    #
    # Do NOT use %(title)s here.
    #
    # Some Facebook/other titles can be extremely long
    # and cause:
    #
    # [Errno 36] File name too long
    #
    # Video ID is short and safe.
    # =====================================================

    output_template = str(
        output_directory
        / "%(id)s.%(ext)s"
    )

    command = [
        "yt-dlp",

        # Progress output
        "--newline",

        # Never download playlist
        "--no-playlist",

        # Network reliability
        "--socket-timeout",
        "60",

        # Retry network failures
        "--retries",
        "10",

        "--fragment-retries",
        "10",

        "--retry-sleep",
        "3",

        # Prefer IPv4
        "--force-ipv4",

        # Continue partial downloads
        "--continue",

        # Don't overwrite existing file
        "--no-overwrites",

        # Best available video + audio.
        # Falls back to a single format if necessary.
        "-f",
        "bv*+ba/b",

        # Merge separate streams to MP4
        "--merge-output-format",
        "mp4",

        # Safe filename
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

                output_lines.append(
                    text
                )

                if len(output_lines) > 100:

                    output_lines.pop(0)

                parse_progress(
                    text,
                    state
                )

            # -------------------------------------------------
            # Cancellation
            # -------------------------------------------------

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

                raise DownloadCancelledError(
                    "Download cancelled."
                )

        return_code = await process.wait()

        # -----------------------------------------------------
        # Cancelled
        # -----------------------------------------------------

        if state.cancelled:

            state.status = "cancelled"

            raise DownloadCancelledError(
                "Download cancelled."
            )

        # -----------------------------------------------------
        # Failed
        # -----------------------------------------------------

        if return_code != 0:

            error_text = "\n".join(
                output_lines[-30:]
            )

            parsed_error = parse_ytdlp_error(
                error_text
            )

            state.error = str(
                parsed_error
            )

            state.status = "error"

            raise parsed_error

        # -----------------------------------------------------
        # Find output
        # -----------------------------------------------------

        filepath = find_downloaded_file(
            before_files,
            output_directory
        )

        if not filepath:

            state.status = "error"

            raise DownloaderError(
                "Download completed but "
                "the output file could not be found."
            )

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


# =========================================================
# USER-FRIENDLY ERROR
# =========================================================

def user_friendly_error(error):

    if isinstance(
        error,
        YouTubeVerificationError
    ):

        return (
            "❌ <b>YouTube verification required.</b>\n\n"
            "YouTube is currently requiring additional "
            "verification for this server request.\n\n"
            "Please try another supported public video URL."
        )

    if isinstance(
        error,
        PrivateVideoError
    ):

        return (
            "❌ <b>Video unavailable.</b>\n\n"
            "The video may be private, removed, "
            "or otherwise unavailable."
        )

    if isinstance(
        error,
        UnsupportedVideoError
    ):

        return (
            "❌ <b>Unsupported URL.</b>\n\n"
            "Please send a valid public video URL "
            "from a supported site."
        )

    if isinstance(
        error,
        DownloadCancelledError
    ):

        return (
            "🛑 <b>Download cancelled.</b>"
        )

    message = str(
        error
    ).strip()

    if not message:

        message = (
            "The video could not be downloaded."
        )

    # Prevent huge raw errors in Telegram.
    if len(message) > 800:

        message = (
            message[:800]
            + "..."
        )

    # Escape HTML-sensitive characters
    message = (
        message
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

    return (
        "❌ <b>Download failed.</b>\n\n"
        f"<code>{message}</code>"
    )
