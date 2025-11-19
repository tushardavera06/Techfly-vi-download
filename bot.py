import os
from pyrogram import Client
from config import Config

# Ensure download folder exists
os.makedirs(Config.DOWNLOAD_DIR, exist_ok=True)

app = Client(
    "yt_downloader_bot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
    plugins={"root": "plugins"},  # plugins folder
)

if __name__ == "__main__":
    print("🤖 Bot starting...")
    app.run()