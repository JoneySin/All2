import math, os, secrets, mimetypes, logging, gc, ctypes, asyncio
from urllib.parse import quote
from aiohttp import web
from utils import temp
from web.utils.custom_dl import TGCustomYield, chunk_size, offset_fix
from web.utils.render_template import media_watch
from web.utils.media_info import get_media_info
from web.web_assets import get_auth
from web.brand import BRAND_MARKUP, BRAND_CSS
from stream_security import verify

routes = web.RouteTableDef()
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 🏠 ROOT ROUTE
# ─────────────────────────────────────────────
@routes.get("/", allow_head=True)
async def root_route_handler(request):
    role, _ = await get_auth(request)
    if role:                                   # लॉगिन है → लैंडिंग पेज की जगह सीधे dashboard
        raise web.HTTPFound('/dashboard')
    # ✅ BUG FIX: pehle `getattr(temp, 'U_NAME', 'AutoFilterBot')` tha, par temp.U_NAME
    # class me already `None` declared hai — isliye getattr ka default KABHI apply nahi
    # hota tha aur bot_username `None` aata tha. Uske baad `.replace(..., None)`
    # TypeError deta tha, yaani homepage `/` pura 500 crash karta tha jab tak bot client
    # start na ho jaaye. Ab `or` se sahi fallback milta hai.
    bot_username = temp.U_NAME or 'AutoFilterBot'

    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Fast Finder — Movies, Series & More</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700;900&display=swap" rel="stylesheet">
<style>
:root{--bg:#000;--text:#fff;--box:rgba(0,0,0,.7);--tag-bg:rgba(51,51,51,.8);--red:#E50914;--red-hover:#b30710}
html.light{--bg:#f3f3f3;--text:#141414;--box:#fff;--tag-bg:#e6e6e6}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;display:flex;flex-direction:column;transition:background 0.3s, color 0.3s}
.hero-bg{position:fixed;inset:0;background:linear-gradient(to top,var(--bg) 0,rgba(0,0,0,.4) 50%,rgba(0,0,0,.8) 100%),url('https://assets.nflxext.com/ffe/siteui/vlv3/f841d4c7-10e1-40af-bcae-07a3f8dc141a/f6d7434e-d6de-4185-a6d4-c77a2d08737b/IN-en-20220502-popsignuptwoweeks-perspective_alpha_website_medium.jpg') center/cover;z-index:-1;transition:all 0.3s}
html.light .hero-bg{background:linear-gradient(to top,var(--bg) 0,rgba(255,255,255,.6) 50%,rgba(255,255,255,.9) 100%),url('https://assets.nflxext.com/ffe/siteui/vlv3/f841d4c7-10e1-40af-bcae-07a3f8dc141a/f6d7434e-d6de-4185-a6d4-c77a2d08737b/IN-en-20220502-popsignuptwoweeks-perspective_alpha_website_medium.jpg') center/cover}
.navbar{display:flex;justify-content:space-between;align-items:center;padding:25px 5%;z-index:10}
.logo{font-size:28px;font-weight:900;color:var(--red);text-decoration:none;display:flex;align-items:center;gap:8px;letter-spacing:1px;text-transform:uppercase}
.header-actions{display:flex;align-items:center;gap:12px}
.theme-btn{background:transparent;border:1px solid var(--text);color:var(--text);padding:8px 16px;border-radius:4px;font-family:'DM Sans',sans-serif;font-weight:700;font-size:14px;cursor:pointer;transition:.2s}
.theme-btn:hover{background:var(--text);color:var(--bg)}
.admin-btn{background:var(--red);color:#fff;text-decoration:none;padding:8px 16px;border-radius:4px;font-weight:700;font-size:14px;transition:.2s;border:1px solid var(--red)}
.admin-btn:hover{background:var(--red-hover);border-color:var(--red-hover)}
.hero-content{flex:1;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;padding:20px;z-index:10;max-width:800px;margin:0 auto}
.hero-title{font-size:4rem;font-weight:900;margin-bottom:15px;line-height:1.1}
.hero-sub{font-size:1.5rem;font-weight:500;margin-bottom:30px}
.search-container{display:flex;width:100%;max-width:650px;flex-direction:row}
.search-input{flex:1;padding:20px 25px;font-size:1.2rem;border:1px solid #808080;border-radius:4px 0 0 4px;background:var(--box);color:var(--text);outline:none;transition:.2s}
.search-input:focus{border-color:var(--text)}
.search-btn{background:var(--red);color:#fff;border:none;padding:0 35px;font-size:1.5rem;font-weight:700;border-radius:0 4px 4px 0;cursor:pointer;display:flex;align-items:center;gap:10px;transition:.2s}
.search-btn:hover{background:var(--red-hover)}
.quick-picks{margin-top:40px;display:flex;flex-wrap:wrap;justify-content:center;gap:10px}
.qp-title{width:100%;font-size:1rem;color:var(--text);opacity:0.7;margin-bottom:10px;font-weight:500;text-transform:uppercase;letter-spacing:1px}
.tag{background:var(--tag-bg);border:1px solid var(--text);padding:8px 18px;border-radius:50px;font-size:14px;font-weight:700;cursor:pointer;transition:.2s}
.tag:hover{background:var(--text);color:var(--bg)}
@media (max-width:600px){.hero-title{font-size:2.5rem}.hero-sub{font-size:1.2rem}.search-container{flex-direction:column;gap:10px}.search-input{border-radius:4px;border:1px solid #808080;padding:15px}.search-btn{border-radius:4px;padding:15px;justify-content:center;font-size:1.2rem}.logo{font-size:20px}.theme-btn, .admin-btn{padding:6px 12px;font-size:12px;}}
__BRAND_CSS__
</style>
</head>
<body>
<div class="hero-bg"></div>
<header class="navbar">
    <a href="/" class="logo landing-brand" aria-label="FastFinder home">__BRAND_MARKUP__</a>
    <div class="header-actions">
        <button class="theme-btn" id="theme-btn">Theme</button>
        <a href="/login" class="admin-btn">Sign In</a>
    </div>
</header>
<main class="hero-content">
    <h1 class="hero-title">Unlimited movies, TV shows, and more.</h1>
    <p class="hero-sub">Search and stream instantly via Telegram.</p>
    <div class="search-container">
        <input type="text" id="searchInput" class="search-input" placeholder="Search genres, qualities, formats..." autocomplete="off">
        <button class="search-btn" onclick="startSearch()">Search ></button>
    </div>
    <div class="quick-picks">
        <div class="qp-title">Trending Searches</div>
        <span class="tag" onclick="fillAndSearch('Action')">Action</span>
        <span class="tag" onclick="fillAndSearch('Comedy')">Comedy</span>
        <span class="tag" onclick="fillAndSearch('Thriller')">Thriller</span>
        <span class="tag" onclick="fillAndSearch('Anime')">Anime</span>
        <span class="tag" onclick="fillAndSearch('4K')">4K UHD</span>
        <span class="tag" onclick="fillAndSearch('Sci-Fi')">Sci-Fi</span>
    </div>
</main>
<script>
(function(){if(localStorage.getItem('theme')==='light')document.documentElement.classList.add('light')})();
document.getElementById('theme-btn').addEventListener('click',()=>{
    let isLight = document.documentElement.classList.toggle('light');
    localStorage.setItem('theme', isLight ? 'light' : 'dark');
});
function startSearch(){
    const q=document.getElementById('searchInput').value.trim();
    const base=`https://t.me/BOT_USERNAME_PLACEHOLDER`;
    window.open(q?`${base}?start=${encodeURIComponent(q)}`:base,'_blank');
}
function fillAndSearch(q){
    document.getElementById('searchInput').value=q;
    startSearch();
}
document.getElementById('searchInput').addEventListener('keydown',e=>{
    if(e.key==='Enter') startSearch();
});
</script>
</body>
</html>""".replace("BOT_USERNAME_PLACEHOLDER", bot_username).replace("__BRAND_CSS__", BRAND_CSS).replace("__BRAND_MARKUP__", BRAND_MARKUP)

    return web.Response(text=html_content, content_type='text/html')


# ─────────────────────────────────────────────
# 📺 STREAM / WATCH ROUTE
# ─────────────────────────────────────────────
@routes.get("/watch/{message_id}")
async def watch_handler(request):
    try:
        mid = int(request.match_info['message_id'])
        e, s = request.query.get("e"), request.query.get("s")
        if not verify(mid, e, s):
            return web.Response(status=403, text="Link expired or invalid", content_type='text/plain')
        return web.Response(
            text=await media_watch(mid, f"e={int(e)}&s={s}"),
            content_type='text/html'
        )
    except ValueError:
        return web.Response(status=400, text="Invalid Message ID")
    except Exception as e:
        logger.error(f"Watch Error: {e}")
        return web.Response(status=500, text="Internal Server Error")


# ─────────────────────────────────────────────
# 📐 HTTP RANGE PARSER (extracted + hardened)
# ✅ BUG FIX: पहले यह parsing media_download() के अंदर inline थी और `r_head` try-block
# के अंदर assign होकर बाहर इस्तेमाल होता था — अगर `int()` कहीं बीच में फेंकता तो
# `r_head` unbound रह सकता था। साथ ही unsatisfiable range (start > file_size) पर
# 416 की जगह आगे बढ़कर negative Content-Length बन सकता था। अब सब एक pure function
# में है, इसलिए इसे test भी किया जा सकता है।
# return: (first_byte, last_byte, length, is_partial) या None (416 भेजना है)
# ─────────────────────────────────────────────
def parse_range(header, file_size):
    """Range header को validated (start, end, length, partial) में बदलता है।"""
    partial = bool(header)
    try:
        if header:
            spec = header.replace("bytes=", "").split(",")[0].strip()
            a, b = spec.split("-", 1)
            if a == "":                       # suffix range: bytes=-N => aakhri N bytes
                first, last = max(file_size - int(b), 0), file_size - 1
            else:
                first = int(a)
                last = int(b) if b else file_size - 1
        else:
            first, last = 0, file_size - 1
    except Exception:
        first, last, partial = 0, file_size - 1, False

    last = min(last, file_size - 1)          # upper bound clamp
    if first < 0 or last < first:            # unsatisfiable
        return None
    return first, last, last - first + 1, partial


# ─────────────────────────────────────────────
# 📥 DOWNLOAD & STREAMING CORE
# ─────────────────────────────────────────────
# Ek saath max kitne open stream connections (RAM bachane ke liye; har connection par
# PREFETCH MB tak buffer rehta hai). Ye sirf connections gino hai — asli speed-control
# custom_dl.py me STREAM_FETCH_CONCURRENCY se hota hai.
MAX_CONNS = max(1, int(os.environ.get("STREAM_MAX_CONNS", "15")))
_ACTIVE_STREAMS = 0



# ─────────────────────────────────────────────
# 🧹 RAM TRIM — स्ट्रीम बंद होने के बाद freed memory को OS को लौटाओ
# Python/glibc free की हुई मेमोरी अपने पास रोक लेता है, इसलिए Koyeb का Memory ग्राफ
# वीडियो बंद होने पर भी ऊँचा दिखता है। सब स्ट्रीम खत्म होने के कुछ सेकंड बाद gc +
# malloc_trim चलाते हैं (सिर्फ़ Linux/glibc पर; वरना चुपचाप skip)।
# ─────────────────────────────────────────────
_trim_task = None

def _trim_now():
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass

async def _trim_later(delay=8):
    try:
        await asyncio.sleep(delay)
        if _ACTIVE_STREAMS == 0:
            _trim_now()
    except asyncio.CancelledError:
        pass

def _schedule_trim():
    global _trim_task
    if _trim_task and not _trim_task.done():
        _trim_task.cancel()
    _trim_task = asyncio.ensure_future(_trim_later())

@routes.get("/download/{message_id}")
async def download_handler(request):
    try:
        mid = int(request.match_info['message_id'])
    except ValueError:
        return web.Response(status=400, text="Invalid Message ID")

    if not verify(mid, request.query.get("e"), request.query.get("s")):
        return web.Response(status=403, text="Link expired or invalid", content_type='text/plain')

    # ⚠️ yahan generic `except Exception` jaan-boojhkar nahi hai: body bhejna shuru hone ke baad
    # alag 500 response bhejna possible nahi hota. Setup ke errors media_download khud sambhalta hai.
    return await media_download(request, mid)


async def media_download(request, message_id: int):
    global _ACTIVE_STREAMS

    # ── 1) SETUP (body shuru hone se pehle) — errors par normal 4xx/5xx response ──
    try:
        info = await get_media_info(message_id)      # cache: har Range par Telegram call nahi
        if not info:
            return web.Response(status=404, text="Media Not Supported or Not Found")

        file_size = info.file_size
        file_name = info.file_name
        if not file_name:
            file_name = (
                f"video_{secrets.token_hex(3)}.mp4"
                if info.is_video
                else f"file_{secrets.token_hex(3)}.bin"
            )

        declared_type = (info.mime_type or "").split(";", 1)[0].strip().lower()
        guessed_type = mimetypes.guess_type(file_name)[0]
        # Telegram documents often report octet-stream even when they have a
        # playable extension. Preserve specific types; infer only generic ones.
        mime_type = (guessed_type or ("video/mp4" if info.is_video else "application/octet-stream")) \
            if declared_type in ("", "application/octet-stream", "binary/octet-stream") else declared_type

        # ── Range Header Parse + Clamp/Validate (देखें parse_range) ──
        parsed = parse_range(request.headers.get('Range'), file_size)
        if parsed is None:
            return web.Response(
                status=416,
                body="416: Range Not Satisfiable",
                headers={"Content-Range": f"bytes */{file_size}"}
            )
        fb, ub, req_len, is_partial = parsed

        ncs    = chunk_size(req_len)
        offset = offset_fix(fb, ncs)

        first_cut = fb - offset
        last_cut  = (ub % ncs) + 1
        parts     = math.ceil((req_len + first_cut) / ncs)

        enc_fn = quote(file_name)
        # Only media types may be served inline; other files keep download-only
        # disposition even when a signed URL contains the inline flag.
        disposition = "inline" if request.query.get("inline") == "1" and mime_type.startswith(("video/", "audio/")) else "attachment"
        headers = {
            "Content-Type":        mime_type,
            "Content-Disposition": f'{disposition}; filename="{enc_fn}"; filename*=UTF-8\'\'{enc_fn}',
            "Accept-Ranges":       "bytes",
            "X-Content-Type-Options": "nosniff",
            "Content-Length":      str(req_len),
        }
        if is_partial:
            headers["Content-Range"] = f"bytes {fb}-{ub}/{file_size}"
        status = 206 if is_partial else 200

    except Exception as e:
        logger.error(f"Stream Setup Error: {e}")
        return web.Response(status=500, text="Server Error")

    resp = web.StreamResponse(status=status, headers=headers)

    # HEAD: sirf headers, Telegram se data mangwane ki zaroorat nahi
    if request.method == "HEAD":
        await resp.prepare(request)
        await resp.write_eof()
        return resp

    if _ACTIVE_STREAMS >= MAX_CONNS:
        return web.Response(status=503, text="Server busy, please retry in a few seconds",
                            headers={"Retry-After": "5"})

    # ── 2) STREAMING (backpressure ke saath; prefetch custom_dl.yield_file me hota hai) ──
    _ACTIVE_STREAMS += 1
    agen = None
    try:
        await resp.prepare(request)
        agen = TGCustomYield().yield_file(
            info.file_id_obj, offset, first_cut, last_cut, parts, ncs
        )
        async for chunk in agen:
            await resp.write(chunk)
        await resp.write_eof()
    except ConnectionError:
        pass            # viewer ne tab band kar diya / seek kiya — normal hai
    except Exception as e:
        logger.error(f"Stream Error (mid-body): {e!r}")
        raise           # connection todo, taaki player ko adhoora data 'poora' na lage
    finally:
        _ACTIVE_STREAMS -= 1
        if agen is not None:
            try:
                await agen.aclose()      # pending prefetch tasks cancel
            except Exception:
                pass
        if _ACTIVE_STREAMS == 0:
            _schedule_trim()
    return resp
