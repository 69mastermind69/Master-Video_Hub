import os
import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

from aiohttp import web

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.constants import ChatAction

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
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
    get_video_info,
    format_bytes,
    format_duration,
)


# =========================================================
# RENDER CONFIG
# =========================================================

PORT = int(
    os.getenv("PORT", "10000")
)

RENDER_EXTERNAL_URL = os.getenv(
    "RENDER_EXTERNAL_URL",
    ""
).rstrip("/")

WEBHOOK_PATH = (
    f"/telegram/{BOT_TOKEN}"
)


# =========================================================
# TELEGRAM APPLICATION
# =========================================================

application = (
    Application.builder()
    .token(BOT_TOKEN)
    .build()
)


# =========================================================
# QUEUE
# =========================================================

@dataclass(order=True)
class DownloadJob:

    priority: int

    created_at: float = field(
        compare=True
    )

    job_id: int = field(
        compare=False
    )

    user_id: int = field(
        compare=False
    )

    chat_id: int = field(
        compare=False
    )

    url: str = field(
        compare=False
    )

    message_id: int = field(
        compare=False
    )

    state: DownloadState = field(
        compare=False
    )

    status_message_id: Optional[int] = field(
        default=None,
        compare=False
    )

    cancelled: bool = field(
        default=False,
        compare=False
    )


job_counter = 0

queue = asyncio.PriorityQueue()

active_jobs = {}

all_jobs = {}


# =========================================================
# PRIORITY
# =========================================================

PRIORITY_HIGH = 0
PRIORITY_NORMAL = 10

DEVELOPER_USERNAME = "Do_x_Die"


def get_priority(update: Update):

    user = update.effective_user

    if not user:
        return PRIORITY_NORMAL

    username = user.username or ""

    if (
        username.lower()
        == DEVELOPER_USERNAME.lower()
    ):
        return PRIORITY_HIGH

    return PRIORITY_NORMAL


# =========================================================
# BUTTONS
# =========================================================

def developer_button():

    keyboard = [
        [
            InlineKeyboardButton(
                "👨‍💻 Developer",
                callback_data="developer"
            )
        ]
    ]

    return InlineKeyboardMarkup(
        keyboard
    )


def developer_menu():

    keyboard = [
        [
            InlineKeyboardButton(
                "👨‍💻 @Do_x_Die",
                url="https://t.me/Do_x_Die"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 Back",
                callback_data="back"
            )
        ]
    ]

    return InlineKeyboardMarkup(
        keyboard
    )


def cancel_button(job_id):

    keyboard = [
        [
            InlineKeyboardButton(
                "🛑 Cancel Download",
                callback_data=f"cancel:{job_id}"
            )
        ]
    ]

    return InlineKeyboardMarkup(
        keyboard
    )


# =========================================================
# START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    text = (
        "🎬 <b>VIDEO DOWNLOADER</b>\n\n"

        "Send me a public video URL.\n\n"

        "✨ <b>Features</b>\n"
        "• 🎬 Full video title\n"
        "• 🖼️ Thumbnail information\n"
        "• ⏱️ Duration\n"
        "• 📦 File size\n"
        "• 📊 Live progress\n"
        "• ⚡ Download speed\n"
        "• ⏳ ETA\n"
        "• 🔄 Retry support\n"
        "• 📥 Queue system\n"
        "• ⭐ Priority system\n"
        "• 🛑 Cancel download\n"
        "• 🎞️ FFmpeg support\n\n"

        "👨‍💻 <b>Developer:</b> MASTERMIND"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=developer_button()
    )


# =========================================================
# DEVELOPER
# =========================================================

async def developer_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    text = (
        "👨‍💻 <b>Developer</b>\n\n"
        "Name: <b>MASTERMIND</b>\n"
        "Username: <b>@Do_x_Die</b>"
    )

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=developer_menu()
    )


# =========================================================
# BACK
# =========================================================

async def back_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    text = (
        "🎬 <b>VIDEO DOWNLOADER</b>\n\n"
        "Send me a public video URL."
    )

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=developer_button()
    )


# =========================================================
# PROGRESS TEXT
# =========================================================

def progress_text(job):

    state = job.state

    info = state.info or {}

    title = info.get(
        "title",
        "Video"
    )

    duration = format_duration(
        info.get("duration")
    )

    downloaded = format_bytes(
        state.downloaded
    )

    total = format_bytes(
        state.total
    )

    if state.total:

        percentage = (
            state.downloaded
            / state.total
        ) * 100

        percentage = min(
            percentage,
            100
        )

        progress = (
            f"{percentage:.1f}%"
        )

    else:

        progress = (
            "Calculating..."
        )

    speed = format_bytes(
        state.speed
    )

    if state.speed:
        speed += "/s"
    else:
        speed = "Calculating..."

    if state.eta:

        eta = format_duration(
            state.eta
        )

    else:

        eta = "Calculating..."

    return (
        f"🎬 <b>{title}</b>\n\n"

        f"⏱ Duration: "
        f"<code>{duration}</code>\n"

        f"📦 Size: "
        f"<code>{downloaded} / {total}</code>\n"

        f"📊 Progress: "
        f"<code>{progress}</code>\n"

        f"⚡ Speed: "
        f"<code>{speed}</code>\n"

        f"⏳ ETA: "
        f"<code>{eta}</code>"
    )


# =========================================================
# QUEUE POSITION
# =========================================================

async def get_queue_position(
    job_id
):

    items = list(
        queue._queue
    )

    items.sort()

    for position, job in enumerate(
        items,
        start=1
    ):

        if job.job_id == job_id:

            return position

    return 0


# =========================================================
# CREATE JOB
# =========================================================

async def create_job(
    update: Update,
    url: str,
    info
):

    global job_counter

    job_counter += 1

    job_id = job_counter

    state = DownloadState()

    state.info = info

    priority = get_priority(
        update
    )

    job = DownloadJob(
        priority=priority,
        created_at=time.monotonic(),
        job_id=job_id,
        user_id=update.effective_user.id,
        chat_id=update.effective_chat.id,
        url=url,
        message_id=update.message.message_id,
        state=state,
    )

    all_jobs[job_id] = job

    await queue.put(job)

    return job


# =========================================================
# URL HANDLER
# =========================================================

async def handle_url(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    url = update.message.text.strip()

    if not url.startswith(
        ("http://", "https://")
    ):

        await update.message.reply_text(
            "❌ Please send a valid video URL."
        )

        return

    analyzing = await update.message.reply_text(
        "🔎 <b>Analyzing video...</b>",
        parse_mode="HTML"
    )

    try:

        info = await get_video_info(
            url
        )

    except Exception as exc:

        error = str(exc)

        if len(error) > 1000:
            error = (
                error[:1000]
                + "..."
            )

        await analyzing.edit_text(
            "❌ <b>Could not read this video.</b>\n\n"
            f"<code>{error}</code>",
            parse_mode="HTML"
        )

        return

    title = info.get(
        "title",
        "Unknown"
    )

    duration = format_duration(
        info.get("duration")
    )

    filesize = (
        info.get("filesize")
        or info.get("filesize_approx")
        or 0
    )

    size_text = (
        format_bytes(filesize)
        if filesize
        else "Unknown"
    )

    job = await create_job(
        update,
        url,
        info
    )

    position = await get_queue_position(
        job.job_id
    )

    if (
        job.priority
        == PRIORITY_HIGH
    ):

        priority_text = (
            "🔴 High"
        )

    else:

        priority_text = (
            "🟡 Normal"
        )

    text = (
        f"🎬 <b>{title}</b>\n\n"

        f"⏱ Duration: "
        f"<code>{duration}</code>\n"

        f"📦 Size: "
        f"<code>{size_text}</code>\n"

        f"⭐ Priority: "
        f"<code>{priority_text}</code>\n"

        f"📥 Queue Position: "
        f"<code>#{position}</code>\n\n"

        "⏳ <b>Added to download queue.</b>"
    )

    await analyzing.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=cancel_button(
            job.job_id
        )
    )


# =========================================================
# CANCEL
# =========================================================

async def cancel_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    try:

        job_id = int(
            query.data.split(":")[1]
        )

    except Exception:

        await query.answer(
            "Invalid job.",
            show_alert=True
        )

        return

    job = all_jobs.get(
        job_id
    )

    if not job:

        await query.answer(
            "Job not found.",
            show_alert=True
        )

        return

    if (
        job.user_id
        != query.from_user.id
    ):

        await query.answer(
            "This is not your download.",
            show_alert=True
        )

        return

    if job.cancelled:

        await query.answer(
            "Already cancelled.",
            show_alert=True
        )

        return

    job.cancelled = True

    job.state.cancelled = True

    # Stop running yt-dlp process.
    if job.state.process:

        try:

            job.state.process.terminate()

        except ProcessLookupError:

            pass

    await query.edit_message_text(
        "🛑 <b>Download cancelled.</b>",
        parse_mode="HTML"
    )


# =========================================================
# PROCESS JOB
# =========================================================

async def process_job(job):

    if job.cancelled:
        return

    active_jobs[
        job.job_id
    ] = job

    filepath = None

    try:

        status = (
            await application.bot.send_message(
                chat_id=job.chat_id,
                text=(
                    "🚀 <b>Download started!</b>\n\n"
                    "Preparing..."
                ),
                parse_mode="HTML",
                reply_markup=cancel_button(
                    job.job_id
                )
            )
        )

        job.status_message_id = (
            status.message_id
        )

        last_update = 0

        async def progress_loop():

            nonlocal last_update

            while (
                job.state.status
                not in (
                    "finished",
                    "error",
                    "cancelled"
                )
                and not job.cancelled
            ):

                now = time.monotonic()

                if (
                    now - last_update
                    >= 3
                ):

                    try:

                        await application.bot.edit_message_text(
                            chat_id=job.chat_id,
                            message_id=job.status_message_id,
                            text=progress_text(job),
                            parse_mode="HTML",
                            reply_markup=cancel_button(
                                job.job_id
                            )
                        )

                        last_update = now

                    except Exception:
                        pass

                await asyncio.sleep(1)

        progress_task = asyncio.create_task(
            progress_loop()
        )

        try:

            filepath = await download_video(
                job.url,
                job.state
            )

        finally:

            progress_task.cancel()

        # Cancelled.
        if (
            job.cancelled
            or job.state.cancelled
        ):

            if (
                filepath
                and os.path.exists(filepath)
            ):

                try:
                    os.remove(filepath)
                except OSError:
                    pass

            try:

                await application.bot.edit_message_text(
                    chat_id=job.chat_id,
                    message_id=job.status_message_id,
                    text=(
                        "🛑 <b>Download cancelled.</b>"
                    ),
                    parse_mode="HTML"
                )

            except Exception:
                pass

            return

        if (
            not filepath
            or not os.path.exists(filepath)
        ):

            raise RuntimeError(
                "Downloaded file was not found."
            )

        file_size = os.path.getsize(
            filepath
        )

        await application.bot.edit_message_text(
            chat_id=job.chat_id,
            message_id=job.status_message_id,
            text=(
                progress_text(job)
                + "\n\n"
                "✅ <b>Download completed!</b>\n"
                f"📦 {format_bytes(file_size)}"
            ),
            parse_mode="HTML"
        )

        await application.bot.send_chat_action(
            chat_id=job.chat_id,
            action=ChatAction.UPLOAD_DOCUMENT
        )

        with open(
            filepath,
            "rb"
        ) as video_file:

            await application.bot.send_document(
                chat_id=job.chat_id,
                document=video_file,
                filename=os.path.basename(
                    filepath
                ),
                caption=(
                    f"🎬 {job.state.info.get('title', 'Video')}\n"
                    f"⏱ {format_duration(job.state.info.get('duration'))}"
                ),
                read_timeout=1800,
                write_timeout=1800,
                connect_timeout=60,
                pool_timeout=60,
            )

    except Exception as exc:

        if (
            job.cancelled
            or job.state.cancelled
        ):
            return

        error = str(exc)

        if len(error) > 1200:

            error = (
                error[:1200]
                + "..."
            )

        try:

            await application.bot.send_message(
                chat_id=job.chat_id,
                text=(
                    "❌ <b>Download failed.</b>\n\n"
                    f"<code>{error}</code>"
                ),
                parse_mode="HTML"
            )

        except Exception:
            pass

    finally:

        active_jobs.pop(
            job.job_id,
            None
        )

        if (
            filepath
            and os.path.exists(filepath)
        ):

            try:
                os.remove(filepath)
            except OSError:
                pass

        all_jobs.pop(
            job.job_id,
            None
        )


# =========================================================
# QUEUE WORKER
# =========================================================

async def queue_worker():

    while True:

        job = await queue.get()

        try:

            if not job.cancelled:

                await process_job(
                    job
                )

        except Exception as exc:

            print(
                "Queue worker error:",
                exc
            )

        finally:

            queue.task_done()


# =========================================================
# WEBHOOK
# =========================================================

async def telegram_webhook(
    request: web.Request
):

    try:

        data = await request.json()

        update = Update.de_json(
            data,
            application.bot
        )

        await application.process_update(
            update
        )

        return web.Response(
            text="OK"
        )

    except Exception as exc:

        print(
            "Webhook error:",
            exc
        )

        return web.Response(
            text="ERROR",
            status=500
        )


# =========================================================
# HEALTH CHECK
# =========================================================

async def health_check(
    request: web.Request
):

    return web.Response(
        text=(
            "Video Downloader Bot is running."
        )
    )


# =========================================================
# RUN SERVER
# =========================================================

async def run():

    if not RENDER_EXTERNAL_URL:

        raise RuntimeError(
            "RENDER_EXTERNAL_URL "
            "environment variable is missing."
        )

    await application.initialize()

    await application.start()

    await application.bot.set_webhook(
        url=(
            RENDER_EXTERNAL_URL
            + WEBHOOK_PATH
        ),
        drop_pending_updates=True
    )

    asyncio.create_task(
        queue_worker()
    )

    server = web.Application()

    server.router.add_get(
        "/",
        health_check
    )

    server.router.add_post(
        WEBHOOK_PATH,
        telegram_webhook
    )

    runner = web.AppRunner(
        server
    )

    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PORT
    )

    await site.start()

    print(
        f"HTTP server listening on port {PORT}"
    )

    print(
        "Telegram webhook is active."
    )

    try:

        await asyncio.Event().wait()

    finally:

        await application.stop()

        await application.shutdown()

        await runner.cleanup()


# =========================================================
# HANDLERS
# =========================================================

application.add_handler(
    CommandHandler(
        "start",
        start
    )
)

application.add_handler(
    CallbackQueryHandler(
        developer_callback,
        pattern="^developer$"
    )
)

application.add_handler(
    CallbackQueryHandler(
        back_callback,
        pattern="^back$"
    )
)

application.add_handler(
    CallbackQueryHandler(
        cancel_callback,
        pattern=r"^cancel:\d+$"
    )
)

application.add_handler(
    MessageHandler(
        filters.TEXT
        & ~filters.COMMAND,
        handle_url
    )
)


# =========================================================
# START
# =========================================================

if __name__ == "__main__":

    asyncio.run(
        run()
    )
