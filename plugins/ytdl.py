import os
from typing import Dict, Tuple, List

from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)

from yt_dlp import YoutubeDL
from config import Config

# In-memory store: "chat_id:msg_id" -> url
URL_STORE: Dict[str, str] = {}

# Make sure download folder exists
os.makedirs(getattr(Config, "DOWNLOAD_DIR", "downloads"), exist_ok=True)


# ------------- Helper: Force Subscribe -------------

async def check_force_sub(client: Client, message: Message) -> bool:
    """
    Returns True if user is allowed to use bot.
    Returns False if user must join channel.
    """

    # Force-sub disabled
    if not getattr(Config, "CHANNEL", None):
        return True

    try:
        chat_id = int(Config.CHANNEL)
    except Exception:
        # Agar galat id ho to bhi force-sub disable treat kar dete hain
        return True

    try:
        member = await client.get_chat_member(chat_id, message.from_user.id)
        if member.status in ("banned", "kicked"):
            await message.reply_text(
                "🥲 Aap channel se banned ho.",
                parse_mode=None
            )
            return False
        return True
    except Exception:
        # Not a member / chat not found etc → send join button
        try:
            chat = await client.get_chat(chat_id)
            invite_link = chat.invite_link
            if not invite_link:
                invite_link = await client.export_chat_invite_link(chat_id)
        except Exception:
            invite_link = None

        buttons: List[List[InlineKeyboardButton]] = []

        if invite_link:
            buttons.append(
                [InlineKeyboardButton("📢 Channel Join Karo", url=invite_link)]
            )

        buttons.append(
            [InlineKeyboardButton("✅ Joined Done", callback_data="joined_refresh")]
        )

        await message.reply_text(
            "📌 Pehle hamare channel ko join karo,\n"
            "phir bot use kar sakte ho.",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=None,
        )
        return False


# ------------- Helper: Human readable size -------------

def human_size(size: int) -> str:
    if not size or size <= 0:
        return "unknown"
    # bytes → MB (2 decimal places)
    return f"{round(size / (1024 * 1024), 2)} MB"


# ------------- Helper: Get formats using yt-dlp -------------

def get_video_info(url: str) -> Tuple[dict, List[dict]]:
    """
    Returns (info_dict, list_of_formats_with_audio+video)
    Only formats jisme video + audio dono ho.
    """
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "nocheckcertificate": True,
        "noplaylist": True,
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        formats = info.get("formats", [])

    merged_formats: List[dict] = []

    for f in formats:
        vcodec = f.get("vcodec")
        acodec = f.get("acodec")

        # Need both audio + video in same stream
        if vcodec and vcodec != "none" and acodec and acodec != "none":
            merged_formats.append(f)

    return info, merged_formats


# ------------- /start command -------------

@Client.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    if not await check_force_sub(client, message):
        return

    await message.reply_text(
        "👋 Namaste!\n\n"
        "Mujhe koi bhi YouTube link bhejo,\n"
        "main tumhe available qualities dikhata hoon,\n"
        "aur tum jo chaho wo download kar sakte ho.\n\n"
        "✅ Audio + Video hamesha sath me (no mute video).",
        parse_mode=None,
    )


# ------------- URL Handler (YouTube link) -------------

@Client.on_message(filters.private & filters.text)
async def url_handler(client: Client, message: Message):
    text = message.text.strip()

    # simple YouTube URL check
    if "youtube.com" not in text and "youtu.be" not in text:
        return  # ignore non-YouTube text

    if not await check_force_sub(client, message):
        return

    msg = await message.reply_text(
        "🔍 Info la raha hoon, please wait...",
        parse_mode=None,
    )

    try:
        info, formats = get_video_info(text)
    except Exception as e:
        await msg.edit_text(
            f"❌ Info fetch nahi ho payi.\n`{e}`",
            parse_mode=None,
        )
        return

    if not formats:
        await msg.edit_text(
            "❌ Koi valid audio+video format nahi mila.",
            parse_mode=None,
        )
        return

    title = info.get("title", "Unknown Title")

    # specific heights (360 / 480 / 720) ko prefer karo
    qualities: Dict[int, dict] = {}
    for f in formats:
        height = f.get("height")
        if not height:
            continue

        if height in (360, 480, 720):
            old = qualities.get(height)
            if (
                not old
                or (f.get("filesize", 0) or 0)
                > (old.get("filesize", 0) or 0)
            ):
                qualities[height] = f

    # agar 360/480/720 me se kuch nahi mila to first 3 best formats
    if not qualities:
        for f in formats[:3]:
            h = f.get("height") or 0
            qualities[h] = f

    buttons: List[List[InlineKeyboardButton]] = []

    for height, f in sorted(qualities.items(), key=lambda x: x[0]):
        fmt_id = f.get("format_id")
        size = human_size(f.get("filesize") or f.get("filesize_approx") or 0)
        btn_text = f"{height}p • {size}"
        # callback_data me sirf format_id bhej rahe hain
        buttons.append(
            [
                InlineKeyboardButton(
                    btn_text,
                    callback_data=f"ytfmt|{fmt_id}",
                )
            ]
        )

    # URL ko store karte hain message key ke saath
    key = f"{msg.chat.id}:{msg.id}"
    URL_STORE[key] = text

    await msg.edit_text(
        f"📺 *{title}*\n\nQuality choose karo:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=None,
    )


# ------------- Callback: Joined Refresh -------------

@Client.on_callback_query(filters.regex("^joined_refresh$"))
async def joined_refresh(client: Client, callback_query: CallbackQuery):
    try:
        await callback_query.answer("Checking membership...", show_alert=False)
        dummy_message = callback_query.message
        # force-sub dobara check
        if await check_force_sub(client, dummy_message):
            await callback_query.edit_message_text(
                "✅ Dhanyawaad! Ab aap bot use kar sakte ho.\n"
                "Mujhe koi YouTube link bhejo.",
                parse_mode=None,
            )
    except Exception:
        # ignore errors
        pass


# ------------- Callback: Format Select -------------

@Client.on_callback_query(filters.regex("^ytfmt\\|"))
async def format_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer("Download start ho raha hai...")

    data = callback_query.data
    fmt_id = data.split("|", 1)[1]

    msg = callback_query.message
    key = f"{msg.chat.id}:{msg.id}"
    url = URL_STORE.get(key)

    if not url:
        await msg.edit_text(
            "❌ URL expire ho gaya. Dobara link bhejo.",
            parse_mode=None,
        )
        return

    await msg.edit_text(
        "⬇️ Download ho raha hai, please wait...",
        parse_mode=None,
    )

    # Download with yt-dlp (audio+video in one file)
    download_dir = getattr(Config, "DOWNLOAD_DIR", "downloads")

    ydl_opts = {
        "format": fmt_id,  # progressive stream (video+audio)
        "outtmpl": os.path.join(download_dir, "%(title)s.%(ext)s"),
        "noplaylist": True,
        "nocheckcertificate": True,
        "quiet": True,
    }

    file_path = None
    info = None

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
    except Exception as e:
        await msg.edit_text(
            f"❌ Download error:\n`{e}`",
            parse_mode=None,
        )
        return

    if not file_path or not os.path.exists(file_path):
        await msg.edit_text(
            "❌ Download file nahi mili.",
            parse_mode=None,
        )
        return

    # Send file to user
    try:
        await msg.edit_text(
            "📤 Telegram par bhej raha hoon...",
            parse_mode=None,
        )

        title = info.get("title", "Video")

        await msg.reply_video(
            video=file_path,
            caption=f"✅ Download complete!\n\n🎬 {title}",
        )

        await msg.delete()
    except Exception as e:
        await msg.edit_text(
            f"❌ Send error:\n`{e}`",
            parse_mode=None,
        )

    # Cleanup
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception:
        pass
