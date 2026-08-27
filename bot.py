import asyncio
import os
import shutil
import time

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config import (
    BOT_TOKEN,
    MAX_CONCURRENT_DOWNLOADS,
)

from downloader import (
    DownloadState,
    download_video,
    format_bytes,
    format_duration,
)


download_slots = asyncio.Semaphore(
    MAX_CONCURRENT_DOWNLOADS
)


def make_progress(state):

    title = state.info.get(
        "title",
        "Reading video information..."
    )

    duration = format_duration(
        state.info.get("duration")
    )

    downloaded = format_bytes(
        state.downloaded
    )

    total = format_bytes(
        state.total
    )

    if state.total:

        percent = (
            state.downloaded /
            state.total
        ) * 100

        percent = min(
            percent,
            100
        )

        progress = f"{percent:.1f}%"

    else:
        progress = "Calculating..."

    speed = (
        format_bytes(state.speed)
        + "/s"
    )

    eta = (
        format_duration(state.eta)
        if state.eta
        else "Calculating..."
    )

    return (
        f"🎬 <b>{title}</b>\n\n"
        f"⏱ Duration: <code>{duration}</code>\n"
        f"📦 Size: <code>{downloaded} / {total}</code>\n"
        f"📊 Progress: <code>{progress}</code>\n"
        f"⚡ Speed: <code>{speed}</code>\n"
        f"⏳ ETA: <code>{eta}</code>"
    )


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "👋 Send a public video URL.\n\n"
        "The bot will show:\n"
        "🎬 Title\n"
        "⏱ Duration\n"
        "📦 Size\n"
        "📊 Progress\n"
        "⚡ Speed\n"
        "⏳ ETA"
    )


async def handle_url(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    url = update.message.text.strip()

    if not url.startswith(
        ("http://", "https://")
    ):

        await update.message.reply_text(
            "❌ Please send a valid URL."
        )

        return

    status = await update.message.reply_text(
        "🔎 Reading video information..."
    )

    state = DownloadState()

    async with download_slots:

        last_update = 0

        async def progress_loop():

            nonlocal last_update

            while state.status not in (
                "finished",
                "error",
            ):

                now = time.monotonic()

                if now - last_update >= 3:

                    try:

                        await status.edit_text(
                            make_progress(state),
                            parse_mode="HTML"
                        )

                        last_update = now

                    except Exception:
                        pass

                await asyncio.sleep(1)

        progress_task = asyncio.create_task(
            progress_loop()
        )

        filepath = None

        try:

            filepath = await download_video(
                url,
                state
            )

            progress_task.cancel()

            await status.edit_text(
                make_progress(state)
                + "\n\n"
                "✅ <b>Download complete.</b>",
                parse_mode="HTML"
            )

            if not filepath or not os.path.exists(
                filepath
            ):

                raise RuntimeError(
                    "Downloaded file was not found."
                )

            file_size = os.path.getsize(
                filepath
            )

            await update.message.reply_text(
                "📤 Preparing upload...\n"
                f"📦 {format_bytes(file_size)}"
            )

            await update.message.chat.send_action(
                ChatAction.UPLOAD_DOCUMENT
            )

            with open(
                filepath,
                "rb"
            ) as video:

                await update.message.reply_document(
                    document=video,
                    filename=os.path.basename(
                        filepath
                    ),
                    caption=(
                        f"🎬 {state.info.get('title', 'Video')}\n"
                        f"⏱ {format_duration(state.info.get('duration'))}"
                    ),
                    read_timeout=1800,
                    write_timeout=1800,
                    connect_timeout=60,
                    pool_timeout=60,
                )

        except Exception as exc:

            progress_task.cancel()

            message = str(exc)

            if len(message) > 1200:
                message = (
                    message[:1200]
                    + "..."
                )

            try:

                await status.edit_text(
                    "❌ <b>Failed</b>\n\n"
                    f"<code>{message}</code>",
                    parse_mode="HTML"
                )

            except Exception:

                await update.message.reply_text(
                    "❌ Download failed."
                )

        finally:

            if filepath and os.path.exists(
                filepath
            ):

                try:
                    os.remove(filepath)

                except OSError:
                    pass


def main():

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            handle_url
        )
    )

    print(
        "Telegram downloader bot started."
    )

    app.run_polling()


if __name__ == "__main__":
    main()