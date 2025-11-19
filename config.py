import os

class Config:
    # Telegram API
    API_ID = int(os.environ.get("API_ID", 0))
    API_HASH = os.environ.get("API_HASH", "")

    # Bot token from @BotFather
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

    # Force subscribe channel ID (example: -1001234567890)
    # Agar force sub nahi chahiye to CHANNEL = None kar sakte ho
    CHANNEL = os.environ.get("CHANNEL", None)

    # Downloads folder
    DOWNLOAD_DIR = "downloads"