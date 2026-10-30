import os

# Only secrets live here (they come from Render environment variables).
# Every other setting is changed inside the bot via /settings.
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
MONGO_URI = os.environ.get("MONGO_URI", "")
DB_NAME = os.environ.get("DB_NAME", "filestore")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
DB_CHANNEL = int(os.environ.get("DB_CHANNEL", "0"))  # default, can be changed with /setdb
PORT = int(os.environ.get("PORT", "8080"))
LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL", "0"))  # default, can be changed with /setlog
# Public URL for streaming (Render provides RENDER_EXTERNAL_URL automatically)
BASE_URL = (os.environ.get("BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL", "")).rstrip("/")

BOT_VERSION = "v18"  # shown in the About panel
