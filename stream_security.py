"""Signed (HMAC) stream links.

/watch/<id> aur /download/<id> ab sirf wahi link kholte hain jisme valid
`e` (expiry) aur `s` (signature) ho. Login ya premium check KHOLNE wale par
nahi hota -> premium user ka /link wala public link koi bhi khol sakta hai,
par message-id guess karke files nahi nikaal sakta.

Secret: env STREAM_SECRET (recommended). Nahi hai to BOT_TOKEN se derive hota hai.
NOTE: secret badalne par saare purane links turant band ho jaate hain.
"""
import base64
import hashlib
import hmac
import time
from os import environ

from info import BOT_TOKEN

_SECRET = hashlib.sha256(
    b"stream-link:" + (environ.get("STREAM_SECRET") or BOT_TOKEN).encode()
).digest()

# ── Link validity (seconds) ──────────────────────────────────────────
USER_LINK_TTL = 24 * 3600         # premium user ke /link ki validity (1 din)
STREAM_TTL = 6 * 3600             # search/dashboard "Stream" button ke links
MAX_ADMIN_TTL = 365 * 24 * 3600   # admin ke custom /link ki max limit


def _sig(mid: int, exp: int) -> str:
    mac = hmac.new(_SECRET, f"{int(mid)}:{int(exp)}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac[:16]).decode().rstrip("=")


def sign_params(mid: int, ttl=STREAM_TTL) -> str:
    """Query string 'e=..&s=..' banata hai. ttl=None => kabhi expire nahi (e=0)."""
    exp = 0 if ttl is None else int(time.time()) + int(ttl)
    return f"e={exp}&s={_sig(mid, exp)}"


def verify(mid: int, exp, sig) -> bool:
    try:
        exp = int(exp)
    except (TypeError, ValueError):
        return False
    if exp < 0 or (exp and exp < time.time()):
        return False
    return hmac.compare_digest(_sig(mid, exp), str(sig or ""))
