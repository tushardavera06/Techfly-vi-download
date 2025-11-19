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

# Message id -> URL (simple in-memory store)
URL_STORE: Dict[str, str] = {}


# ------------- Helper: Force Subscribe -------------


async def check_force_sub(client: Client, message: Message) -> bool:
    """
    Returns True agar user ko bot use karne dena hai.
    Returns False agar pehle channel join karna zaroori hai.
    """

    # Agar CHANNEL set hi nahi hai to force sub band:
    if not getattr(Config, "CHANNEL", None):
        return True

    try:
        member = await client.get_chat_member(
            int(Config.CHANNEL),
            message.from_user.id,
        )
        if member.status in ("banned", "kicked"):
            await message.reply_text(
                "🚫 Aap channel se banned ho, bot use nahi kar sakte.",
                parse_mode=None,
            )
            return False

        # Member hai, use karne do
        return True

    except Exception:
        # Member nahi mila / chat not found / etc
        try:
            chat = await client.get_chat(int(Config.CHANNEL))
            invite_link = chat.invite_link
            if not invite_link:
                invite_link = await client.export_chat_invite_link(
                    int(Config.CHANNEL)
                )
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
            "📌 Pehle hamare channel ko join karo,\n"
            "phir bot use kar sakte ho. 🙂",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=None,
        )
        return False


# ------------- Helper: Human readable size -------------


def human_size(size: int) -> str:
    if not size or size <= 0:
        return "Unknown"

    # bytes -> MB (2 decimal)
    return f"{round(size / (1024 * 1024), 2)} MiB"


# ------------- Helper: yt-dlp se formats laana -------------


def get_video_info(url: str) -> Tuple[dict, List[dict]]:
    """
    Returns:
      info_dict, list_of_formats (sirf jisme video + audio dono ho)
    """

    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "noprogress": True,
        "nocheckcertificate": True,
        "ignoreerrors": True,
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        formats = info.get("formats", []) if info else []

    merged_formats: List[dict] = []
    for f in formats:
        vcodec = f.get("vcodec")
        acodec = f.get("acodec")

        # Hume sirf woh chahiye jisme audio + video dono ho
        if vcodec and vcodec != "none" and acodec and acodec != "none":
            merged_formats.append(f)

    return info, merged_formats


# ------------- /start command -------------


@Client.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    if not await check_force_sub(client, message):
        return

    text = (
        "👋 Namaste!\n\n"
        "Mujhe koi bhi YouTube link bhejo,\n"
        "main tumhe available qualities dikhata hoon,\n"
        "aur tum jo chaho wo download kar sakte ho.\n\n"
        "✅ Audio + Video hamesha sath me (no mute video)."
    )

    await message.reply_text(text, parse_mode=None)


# ------------- URL Handler (YouTube link) -------------


@Client.on_message(filters.private & filters.text)
async def url_handler(client: Client, message: Message):
    text = message.text.strip()

    # Simple YouTube URL check
    if "youtube.com" not in text and "youtu.be" not in text:
        return await message.reply_text(
            "❌ Abhi sirf YouTube link support hai.\n"
            "Baad me TikTok / Insta bhi add kar denge. 🙂",
            parse_mode=None,
        )

    if not await check_force_sub(client, message):
        return

    msg = await message.reply_text(
        "🔍 Info la raha hoon, please wait…",
        parse_mode=None,
    )

    try:
        info, formats = get_video_info(text)
    except Exception as e:
        return await msg.edit_text(
            f"❌ Info fetch nahi ho payi:\n{e}",
            parse_mode=None,
        )

    if not formats:
        return await msg.edit_text(
            "❌ Koi valid audio+video format nahi mila.",
            parse_mode=None,
        )

    title = info.get("title", "Unknown Title")

    # 360p / 480p / 720p ko prefer karo
    qualities: Dict[int, dict] = {}
    for f in formats:
        height = f.get("height")
        if not height:
            continue

        if height in (360, 480, 720):
            old = qualities.get(height)
            if not old or (f.get("filesize") or 0) > (old.get("filesize") or 0):
                qualities[height] = f

    # Agar specific height ke formats nahi mile to first 3 le lo
    if not qualities:
        for f in formats[:3]:
            h = f.get("height") or 0
            qualities[h] = f

    buttons = []
    for height, f in sorted(qualities.items(), key=lambda x: x[0]):
        fmt_id = f.get("format_id")
        size = human_size(
            f.get("filesize") or f.get("filesize_approx") or 0
        )
        btn_text = f"{height}p • {size}"
        buttons.append(
            [InlineKeyboardButton(btn_text, callback_data=f"ytfmt|{fmt_id}")]
        )

    # Store URL against this message
    key = f"{msg.chat.id}:{msg.id}"
    URL_STORE[key] = text

    await msg.edit_text(
        f"✅ Available formats for:\n{title}",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=None,
    )


# ------------- Callback: Joined Refresh -------------


@Client.on_callback_query(filters.regex("^joined_refresh$"))
async def joined_refresh(client: Client, callback_query: CallbackQuery):
    try:
        await callback_query.answer("Checking membership…", show_alert=False)
        dummy_message = callback_query.message
        dummy_message.from_user = callback_query.from_user  # hack

        if await check_force_sub(client, dummy_message):
            await callback_query.edit_message_text(
                "✅ Dhanyavaad! Ab aap bot use kar sakte ho.\n"
                "Mujhe koi YouTube link bhejo. 🙂",
                parse_mode=None,
            )
    except Exception:
        # Agar kuch bhi error aaya to ignore kar dete hain
        pass


# ------------- Callback: Format Select -------------


@Client.on_callback_query(filters.regex("^ytfmt\\|"))
async def format_callback(client: Client, callback_query: CallbackQuery):
    await callback_query.answer("Download start ho raha hai…")

    data = callback_query.data
    fmt_id = data.split("|", 1)[1]

    msg = callback_query.message
    key = f"{msg.chat.id}:{msg.id}"
    url = URL_STORE.get(key)

    if not url:
        return await msg.edit_text(
            "❌ URL expire ho gaya. Dobara link bhejo.",
            parse_mode=None,
        )

    await msg.edit_text(
        "⬇️ Download ho raha hai, please wait…",
        parse_mode=None,
    )

    # Download with audio+video merge
    os.makedirs(Config.DOWNLOAD_DIR, exist_ok=True)
    outtmpl = os.path.join(Config.DOWNLOAD_DIR, "%(title)s.%(ext)s")

    ydl_opts = {
        "format": f"{fmt_id}+bestaudio/best",
        "outtmpl": outtmpl,
        "merge_output_format": "mp4",
        "quiet": True,
        "nocheckcertificate": True,
    }

    file_path = None
    info = None

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
    except Exception as e:
        return await msg.edit_text(
            f"❌ Download error:\n{e}",
            parse_mode=None,
        )

    # Send file to user
    try:
        title = (info or {}).get("title", "Video")
        await msg.edit_text(
            "📤 Telegram par bhej raha hoon…",
            parse_mode=None,
        )
        await msg.reply_video(
            video=file_path,
            caption=f"✅ Download complete!\n\n📽 {title}",
        )
        await msg.delete()
    except Exception as e:
        await msg.edit_text(
            f"❌ Send error:\n{e}",
            parse_mode=None,
        )

    # Cleanup
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
    except Exception:
        pass