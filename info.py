import re
import logging
from os import environ
from Script import script

logger = logging.getLogger(__name__)

# Compulsory environment variables — single source of truth, all seven required.
# BIN_CHANNEL, DELETE_CHANNEL, and MEDIA_STORAGE_CHANNEL are optional and fall back to LOG_CHANNEL.
REQUIRED_ENV = ("API_ID", "API_HASH", "BOT_TOKEN", "ADMINS", "LOG_CHANNEL", "DATABASE_URL", "URL")
_missing_env = [name for name in REQUIRED_ENV if not (environ.get(name) or "").strip()]
if _missing_env:
    logger.error("❌ Missing required environment variable(s): %s", ", ".join(_missing_env))
    exit(1)

# Needed for the self-service premium purchase flow, not for bot startup.
PAYMENT_ENV = ("UPI_ID", "UPI_NAME", "RECEIPT_SEND_USERNAME")

# ─────────────────────────────────────────────
# 🧠 HELPERS & BOOLEAN PARSERS (RAM Safe)
# ─────────────────────────────────────────────
def is_enabled(key, default=False):
    val = environ.get(key, str(default)).lower()
    if val in ("true", "1", "yes", "y", "enable"): return True
    if val in ("false", "0", "no", "n", "disable"): return False
    logger.error(f"❌ {key} has invalid value")
    exit(1)

def is_valid_ip(ip):
    ip_pattern = (
        r'\b(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.'
        r'(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.'
        r'(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.'
        r'(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b'
    )
    return re.match(ip_pattern, ip) is not None

def parse_reactions(raw=None, default="👍 ❤️ 🔥 😍 🤝"):
    """Parse REACTIONS from either space- or comma-separated values.

    Empty values intentionally disable reactions. Duplicates are removed so
    one accidentally repeated emoji does not skew the random choice.
    """
    source = environ.get("REACTIONS", default) if raw is None else raw
    tokens = str(source or "").replace(",", " ").split()
    return list(dict.fromkeys(token for token in tokens if token))

# ─────────────────────────────────────────────
# 🤖 BOT CREDENTIALS
# ─────────────────────────────────────────────
API_ID = int((environ.get("API_ID") or "0").strip())
API_HASH = (environ.get("API_HASH") or "").strip()
BOT_TOKEN = (environ.get("BOT_TOKEN") or "").strip()

if not API_ID or not API_HASH or not BOT_TOKEN:
    logger.error("❌ API_ID / API_HASH / BOT_TOKEN missing")
    exit(1)

# A bot token is exactly "<numeric bot id>:<secret>". Pasting a Koyeb secret
# with a trailing newline/space is a common mistake and would otherwise surface
# as a misleading Telegram authorization timeout.
if ":" not in BOT_TOKEN or not BOT_TOKEN.split(":", 1)[0].isdigit():
    logger.error("❌ BOT_TOKEN format invalid (expected 123456789:AA...)")
    exit(1)

# Optional Telegram transport settings. Keep these empty unless needed:
#   PROXY          socks5://user:pass@host:port (or an MTProxy link)
#   SESSION_STRING a previously exported Kurigram/Pyrogram session string
#   SESSION_DIR    writable directory for Auto_Filter_Bot.session (use a volume)
PROXY = (environ.get("PROXY") or "").strip()
SESSION_STRING = (environ.get("SESSION_STRING") or "").strip()
SESSION_DIR = (environ.get("SESSION_DIR") or "").strip()

# Telegram occasionally answers bot authorization with a temporary 500/timeout.
# Retry a few times instead of restarting the whole Koyeb instance immediately.
AUTH_RETRY_ATTEMPTS = int(environ.get("AUTH_RETRY_ATTEMPTS", "5"))
AUTH_RETRY_DELAY = int(environ.get("AUTH_RETRY_DELAY", "30"))

PORT = int(environ.get("PORT", 8080)) # कोएब (Koyeb) के डायनेमिक बाइंडिंग के लिए 8080 यूनिवर्सल बेस्ट पोर्ट है

# ─────────────────────────────────────────────
# 👑 ADMINS & SECURITY
# ─────────────────────────────────────────────
ADMINS = environ.get("ADMINS", "")
if not ADMINS:
    logger.error("❌ ADMINS environment variable missing")
    exit(1)
ADMINS = [int(x) for x in ADMINS.split() if x.isnumeric()]

# ─────────────────────────────────────────────
# 📢 STORAGE & MICRO-ROUTING CHANNELS SYNC
# ─────────────────────────────────────────────
LOG_CHANNEL = int((environ.get("LOG_CHANNEL") or "").strip() or "0")
if not LOG_CHANNEL:
    logger.error("❌ LOG_CHANNEL missing")
    exit(1)

def _parse_optional_channel(key, fallback):
    raw = (environ.get(key) or "").strip()
    val = int(raw) if raw else 0
    return val or fallback

# स्ट्रीमिंग/प्रोबिंग चैनल — सेट नहीं (या 0) है तो सुरक्षित रूप से LOG_CHANNEL पर जाएगा
BIN_CHANNEL = _parse_optional_channel("BIN_CHANNEL", LOG_CHANNEL)

# ⚡ [MERGED] एक्टर फोटोज़, गैलरी, पोस्ट कवर व थंबनेल के लिए एक ही मीडिया स्टोरेज चैनल
# (यदि MEDIA_STORAGE_CHANNEL सेट नहीं है — या पुराना THUMBNAIL_STORAGE_CHANNEL /
# ACTOR_STORAGE_CHANNEL भी खाली है — तो सुरक्षित रूप से BIN_CHANNEL, अन्यथा LOG_CHANNEL पर जाएगा)
def _resolve_media_storage_channel():
    for key in ("MEDIA_STORAGE_CHANNEL", "THUMBNAIL_STORAGE_CHANNEL", "ACTOR_STORAGE_CHANNEL"):
        raw = (environ.get(key) or "").strip()
        val = int(raw) if raw else 0
        if val:
            return val
    return BIN_CHANNEL or LOG_CHANNEL

MEDIA_STORAGE_CHANNEL = _resolve_media_storage_channel()

# 🗑️ [NEW FEATURE] डिलीट-बैकअप चैनल — बॉट या वेब से कोई फाइल डिलीट होने से पहले
# यहाँ फॉरवर्ड/रीसेंड की जाती है ताकि गलती से डिलीट होने पर भी फाइल रिकवर हो सके।
# (सेट नहीं है तो सुरक्षित रूप से LOG_CHANNEL पर फॉल-बैक होगा)
DELETE_CHANNEL = _parse_optional_channel("DELETE_CHANNEL", LOG_CHANNEL)

# ─────────────────────────────────────────────
# 🗄️ DATABASE CONNECTION URL
# ─────────────────────────────────────────────
DATABASE_URL = environ.get("DATABASE_URL", "")
DATABASE_NAME = environ.get("DATABASE_NAME", "Cluster0")

if not DATABASE_URL:
    logger.error("❌ DATABASE_URL missing")
    exit(1)

# ─────────────────────────────────────────────
# ⚙️ GLOBAL SETTINGS & ADAPTIVE RESULTS SYNC
# ─────────────────────────────────────────────
TIME_ZONE = environ.get("TIME_ZONE", "Asia/Kolkata")

# बोट के बटन्स (12) और वेब/मिनी ऐप (21) की स्वतंत्र रिज़ल्ट लिमिट
MAX_BOT_RESULTS = int(environ.get("MAX_BOT_RESULTS", 12)) 
MAX_WEB_RESULTS = int(environ.get("MAX_WEB_RESULTS", 21)) 

# ─────────────────────────────────────────────
# ⏳ TIMERS ENGINE (सेंट्रलाइज्ड कस्टमाइजेबल टाइमर्स)
# ─────────────────────────────────────────────
PM_FILE_DELETE_TIME = int(environ.get("PM_FILE_DELETE_TIME", 600)) 
PREMIUM_REMINDER_BUSY_GAP = int(environ.get("PREMIUM_REMINDER_BUSY_GAP", 60)) 

# ─────────────────────────────────────────────
# ⚡ SPEED, BUFFER & ANTI-SPAM THRU LMT
# ─────────────────────────────────────────────
MAX_THUMB_CACHE = int(environ.get("MAX_THUMB_CACHE", 500))

# ─────────────────────────────────────────────
# 🧩 FEATURE FLAGS
# ─────────────────────────────────────────────
USE_CAPTION_FILTER = is_enabled("USE_CAPTION_FILTER", True)
AUTO_DELETE = is_enabled("AUTO_DELETE", True)
PROTECT_CONTENT = is_enabled("PROTECT_CONTENT", False)
SPELL_CHECK = is_enabled("SPELL_CHECK", True)
IS_STREAM = is_enabled("IS_STREAM", True)
IS_PREMIUM = is_enabled("IS_PREMIUM", True)
# A full library scan is useful after bulk changes, but running it on every
# restart can keep a small worker/DB busy for minutes and make normal replies
# feel slow. Keep it opt-in; the admin dashboard can still trigger it manually.
STARTUP_GROUP_SCAN = is_enabled("STARTUP_GROUP_SCAN", False)

# ─────────────────────────────────────────────
# 📝 TEXT FILE CAPTION TEMPLATE
# ─────────────────────────────────────────────
FILE_CAPTION = environ.get("FILE_CAPTION", script.FILE_CAPTION)

# ─────────────────────────────────────────────
# 🎥 STREAM ENGINE & WEB APP DOMAIN CONVERTER
# ─────────────────────────────────────────────
URL = environ.get("URL", "").strip()
if not URL:
    logger.error("❌ Web URL environment variable missing")
    exit(1)

# WebApp-Compatible HTTPS URL Auto-Builder Engine
if URL.startswith("http://"):
    logger.warning(f"⚠️ URL is HTTP, auto-converting to HTTPS: {URL}")
    URL = "https://" + URL[len("http://"):]

if URL.startswith("https://"):
    if not URL.endswith("/"): URL += "/"
elif is_valid_ip(URL):
    URL = f"https://{URL}/"
    logger.warning("⚠️ IP-based URL detected. Telegram WebApp requires a valid HTTPS domain.")
else:
    # No http(s) scheme reached this branch, so only a dotted host is valid.
    if "." in URL:
        URL = "https://" + URL.rstrip("/") + "/"
        logger.info(f"✅ Auto-Formatted incomplete URL string to valid domain structure: {URL}")
    else:
        logger.error("❌ Invalid URL - must start with https:// for Telegram Mini App support")
        exit(1)

# ─────────────────────────────────────────────
# 💎 PREMIUM PAYMENT CONFIGURATIONS
# ─────────────────────────────────────────────
# Space- or comma-separated Telegram reaction emojis; empty disables them.
REACTIONS = parse_reactions()

PRE_DAY_AMOUNT = int(environ.get("PRE_DAY_AMOUNT", 10))
UPI_ID = environ.get("UPI_ID", "").strip()
UPI_NAME = environ.get("UPI_NAME", "").strip()

RECEIPT_SEND_USERNAME = environ.get("RECEIPT_SEND_USERNAME", "").strip()
if RECEIPT_SEND_USERNAME and not RECEIPT_SEND_USERNAME.startswith("@") and not RECEIPT_SEND_USERNAME.isnumeric():
    RECEIPT_SEND_USERNAME = "@" + RECEIPT_SEND_USERNAME

if IS_PREMIUM:
    _missing_payment = [name for name in PAYMENT_ENV if not (environ.get(name) or "").strip()]
    if _missing_payment:
        logger.warning(
            "⚠️ Premium is ON but self-service purchase is not configured "
            "(missing: %s). Buy buttons will ask users to contact an admin; "
            "/add_prm still works.", ", ".join(_missing_payment)
        )
