import os
import math
from typing import Dict, Tuple

from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)

from yt_dlp import YoutubeDL

from config import Config

# Simple in-memory store: message -> url
URL_STORE: Dict[str, str] = {}


# ---------- Helper: Force Subscribe ----------

async def check_force_sub(client: Client, message: Message) -> bool:
    """
    Returns True if user is allowed to use bot.
    Returns False if user must join channel.
    """
    if not Config.CHANNEL:
        return True  # force sub disabled

    try:
        member = await client.get_chat_member(int(Config.CHANNEL), message.from_user.id)
        if member.status in ("banned", "kicked"):
            await message.reply_text("🚫 Aap channel se banned ho.")
            return False
        return True
    except Exception:
        # Not a member / chat not found / etc
        try:
            chat = await client.get_chat(int(Config.CHANNEL))
            invite_link = chat.invite_link
            if not invite_link:
                invite_link = await client.export_chat_invite_link(int(Config.CHANNEL))
        except Exception:
            invite_link = None

        buttons = []
        if invite_link:
            buttons.append(
                [InlineKeyboardButton("📢 Channel Join Karo", url=invite_link)]
            )
        buttons.append(
            [InlineKeyboardButton("✅ Joined Done", callback_data="joined_refresh")]
        )

        await message.reply_text(
            "⚠️ Pehle hamare channel ko join karo, "
            "phir bot use kar sakte ho.",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return False


# ---------- Helper: Format Size ----------

def human_size(size: int) -> str:
    if not size or size <= 0:
        return "unknown"
    # bytes -> MB
    return f"{round(size / (1024 * 1024), 2)} MB"


# ---------- Helper: Get formats using yt-dlp ----------

def get_video_info(url: str) -> Tuple[dict, list]:
    """
    Returns (info_dict, list_of_merged_formats)
    Only formats jisme video + audio dono ho.
    """
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "nocheckcertificate": True,
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        formats = info.get("formats", [])

    merged_formats = []
    for f in formats:
        vcodec = f.get("vcodec")
        acodec = f.get("acodec")
        # Need both audio + video
        if vcodec != "none" and acodec != "none":
            merged_formats.append(f)

    return info, merged_formats


# ---------- /start command ----------

@Client.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    if not await check_force_sub(client, message):
        return

    await message.reply_text(
        "👋 Namaste!\n\n"
        "Mujhe koi bhi YouTube link bhejo,\n"
        "main tumhe available qualities dikhata hoon,\n"
        "aur tum jo chaho wo download kar sakte ho.\n\n"
        "✅ Audio + Video hamesha sath me (no mute video)."
    )


# ---------- URL Handler ----------

@Client.on_message(filters.private & filters.text)
async def url_handler(client: Client, message: Message):
    text = message.text.strip()

    # Simple YouTube URL check (baad me tiktok/insta add kar sakte hain)
    if "youtube.com" not in text and "youtu.be" not in text:
        return await message.reply_text(
            "❌ Sirf YouTube link support hai abhi.\n"
            "Baad me TikTok / Insta bhi add kar denge. 🙂"
        )

    if not await check_force_sub(client, message):
        return

    msg = await message.reply_text("🔍 Info la raha hoon, please wait...")

    try:
        info, formats = get_video_info(text)
    except Exception as e:
        await msg.edit_text(f"❌ Info fetch nahi ho payi:\n`{e}`")
        return

    if not formats:
        return await msg.edit_text("❌ Koi valid audio+video format nahi mila.")

    title = info.get("title", "Unknown Title")

    # Thode selected formats (360p, 480p, 720p) choose karte hain
    qualities = {}
    for f in formats:
        height = f.get("height")
        if not height:
            continue
        if height in (360, 480, 720):
            # Agar same height ka best size choose karna ho:
            old = qualities.get(height)
            if not old or (f.get("filesize", 0) or 0) > (old.get("filesize", 0) or 0):
                qualities[height] = f

    if not qualities:
        # Agar specific 360/480/720 nahi mile to sab me se kuch first teen
        for f in formats[:3]:
            h = f.get("height") or 0
            qualities[h] = f

    buttons = []
    for height, f in sorted(qualities.items(), key=lambda x: x[0]):
        fmt_id = f.get("format_id")
        size = human_size(f.get("filesize") or f.get("filesize_approx") or 0)
        btn_text = f"{height}p - {size}"
        # callback_data me format id rakhte hain
        buttons.append(
            [
                InlineKeyboardButton(
                    btn_text, callback_data=f"ytfmt|{fmt_id}"
                )
            ]
        )

    # Store URL against reply message
    key = f"{msg.chat.id}:{msg.id}"
    URL_STORE[key] = text

    await msg.edit_text(
        f"🎬 *{title}*\n\nQuality choose karo:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ---------- Callback: Joined Refresh ----------

@Client.on_callback_query(filters.regex("^joined_refresh$"))
async def joined_refresh(client: Client, callback_query: CallbackQuery):
    try:
        await callback_query.answer("Checking membership...", show_alert=False)
        dummy_message = callback_query.message
        dummy_message.from_user = callback_query.from_user  # hack
        if await check_force_sub(client, dummy_message):
            await callback_query.edit_message_text(
                "✅ Dhanyavaad! Ab aap bot use kar sakte ho.\n"
                "Mujhe koi YouTube link bhejo."
            )
    except Exception:
        pass


# ---------- Callback: Format Select ----------

@Client.on_callback_query(filters.regex(r"^ytfmt\|"))
async def format_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer("Download start ho raha hai...")

    data = callback_query.data
    _, fmt_id = data.split("|", 1)

    msg = callback_query.message
    key = f"{msg.chat.id}:{msg.id}"
    url = URL_STORE.get(key)

    if not url:
        return await msg.edit_text("❌ URL expire ho gaya. Dobara link bhejo.")

    await msg.edit_text("⬇️ Download ho raha hai, please wait...")

    # Download with audio+video merge
    ydl_opts = {
        "format": fmt_id,  # ye format_id audio+video wala hi hai
        "outtmpl": os.path.join(Config.DOWNLOAD_DIR, "%(title)s.%(ext)s"),
        "merge_output_format": "mp4",
        "nocheckcertificate": True,
        "quiet": True,
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
    except Exception as e:
        return await msg.edit_text(f"❌ Download error:\n`{e}`")

    # Send file to user
    try:
        await msg.edit_text("📤 Telegram par bhej raha hoon...")
        title = info.get("title", "Video")
        await msg.reply_video(
            video=file_path,
            caption=f"✅ Download complete!\n\n🎬 {title}",
        )
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"❌ Send error:\n`{e}`")

    # Cleanup
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception:
        pass
