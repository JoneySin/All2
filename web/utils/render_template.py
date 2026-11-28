import asyncio, urllib.parse, html, json, logging
from info import URL
from web.utils.custom_dl import TGCustomYield
from web.utils.media_info import get_media_info
from web.brand import BRAND_MARKUP, BRAND_CSS
from web.player_assets import PLAYER_CSS, PLAYER_JS, build_player_card_html

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 🎬 FAST FINDER OPTIMIZED STREAM TEMPLATE
# ─────────────────────────────────────────────
watch_tmplt = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>{heading}</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700;900&display=swap" rel="stylesheet">
<style>
:root{{
--bg:#0a0a0c;--bg2:#111116;--bg3:#1d1d26;--card:#14141f;--border:#262636;--text:#ffffff;--muted:#a0a0b0;--accent:#e50914;
--nav1:rgba(10,10,12,.95);--nav2:rgba(10,10,12,.4);
}}
html.light{{
--bg:#f4f5f7;--bg2:#ffffff;--bg3:#eef0f4;--card:#ffffff;--border:#d2d5df;--text:#0a0a0c;--muted:#62627a;--accent:#e50914;
--nav1:rgba(255,255,255,.95);--nav2:rgba(255,255,255,.4);
}}
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:var(--bg);font-family:'DM Sans',sans-serif;color:var(--text);min-height:100vh;transition:background .2s,color .2s;}}
.navbar{{width:100%;padding:16px 4%;display:flex;align-items:center;justify-content:space-between;position:fixed;top:0;z-index:999;background:linear-gradient(to bottom,var(--nav1),var(--nav2),transparent);backdrop-filter:blur(6px);transition:background .3s;}}
.logo{{font-size:24px;font-weight:900;letter-spacing:1px;color:var(--accent);display:flex;align-items:center;gap:8px;text-decoration:none;transition:.3s;}}
.logo:hover{{transform:scale(1.02);}}
.theme-btn{{background:var(--card);border:1px solid var(--border);color:var(--text);padding:8px 16px;border-radius:10px;font-family:'DM Sans',sans-serif;font-weight:800;font-size:13px;cursor:pointer;transition:.2s;}}
.theme-btn:hover{{border-color:var(--accent);color:var(--accent);}}
.hero-container{{width:100%;max-width:722px;margin:auto;padding:86px 16px 40px;}}
#toast{{visibility:hidden;min-width:200px;background:var(--accent);color:#fff;text-align:center;border-radius:10px;padding:12px 18px;position:fixed;right:20px;bottom:20px;z-index:9999;font-size:13px;font-weight:800;box-shadow:0 10px 30px rgba(0,0,0,.45);}}
#toast.show{{visibility:visible;animation:fi .35s,fo .35s 2.4s;}}
@keyframes fi{{from{{opacity:0;transform:translateY(12px);}}to{{opacity:1;transform:translateY(0);}}}}
@keyframes fo{{from{{opacity:1;transform:translateY(0);}}to{{opacity:0;transform:translateY(12px);}}}}
@media(max-width:768px){{.logo{{font-size:20px;}}}}
@media(max-width:500px){{.hero-container{{padding:76px 10px 30px;}}}}
__BRAND_CSS__
__PLAYER_CSS__
</style>
</head>
<body>
<div class="navbar">
    <a href="/" class="logo watch-brand" aria-label="FastFinder home">__BRAND_MARKUP__</a>
    <button class="theme-btn" id="theme-btn">Theme</button>
</div>
<div class="hero-container">
__PLAYER_CARD__
</div>
<div id="toast">Link Copied!</div>

<script>
const docEl=document.documentElement, themeBtn=document.getElementById('theme-btn');
if(localStorage.getItem('theme')==='light') docEl.classList.add('light');
themeBtn.addEventListener('click',()=>{{
    let isLight = docEl.classList.toggle('light');
    localStorage.setItem('theme', isLight ? 'light' : 'dark');
}});
function showToast(msg){{
    var t=document.getElementById('toast');
    if(!t)return;
    t.textContent=msg||'Link Copied!';
    t.classList.add('show');
    setTimeout(function(){{t.classList.remove('show');}},2800);
}}
__PLAYER_JS__
if(window.Telegram&&window.Telegram.WebApp&&typeof window.Telegram.WebApp.initData==='string'&&window.Telegram.WebApp.initData.length>0){{
    try{{window.Telegram.WebApp.ready();window.Telegram.WebApp.expand();}}catch(_){{}}
}}
inlinePlayerInitWatch(__WATCH_CONFIG__);
</script>
</body></html>"""


# ─────────────────────────────────────────────
# 🎬 MEDIA WATCH FUNCTION
# ─────────────────────────────────────────────
async def media_watch(message_id, query=""):
    try:
        info = await get_media_info(message_id)      # cache — Telegram call har baar nahi

        if not info:
            return "<h2 style='color:#fff;text-align:center;padding:50px;'>❌ File Not Found</h2>"

        TGCustomYield.warm_media_session(getattr(info, "file_id_obj", None))

        src = urllib.parse.urljoin(URL, f'download/{message_id}')
        if query:
            src += f'?{query}'      # signed token download request me bhi jaata hai
        mime = info.mime_type or 'video/mp4'   # None => crash fix

        if mime.split('/')[0].strip() == 'video':
            qs = urllib.parse.parse_qs(query or "")
            raw_name = info.file_name or "Fast Finder Movie"
            watch_config = {
                "mid": int(message_id),
                "e": (qs.get("e") or [""])[0],
                "s": (qs.get("s") or [""])[0],
                "fileId": "",
                "downloadUrl": src,
                "switches": None,
            }
            raw_fid = getattr(info, "file_id", None)
            if raw_fid:
                try:
                    from database.ia_filterdb import unpack_new_file_id, get_files_by_ids
                    from web.search_api import _switches_for
                    origin_fid = unpack_new_file_id(raw_fid)
                    if origin_fid:
                        watch_config["fileId"] = origin_fid
                        switches, docs = await asyncio.gather(
                            _switches_for(origin_fid),
                            get_files_by_ids([origin_fid]),
                        )
                        if switches and switches.get("group"):
                            watch_config["switches"] = switches
                        if docs and docs[0].get("file_name"):
                            raw_name = docs[0]["file_name"]
                except Exception:
                    logger.debug("watch switches lookup skipped", exc_info=True)

            fn = html.escape(raw_name)   # None => crash fix
            card_html = build_player_card_html(mode="watch", title=fn, src=html.escape(src, quote=True), mime_type=html.escape(mime, quote=True))
            config_json = json.dumps(watch_config).replace("<", "\\u003c")
            return (watch_tmplt.format(heading=f"Watch {fn}")
                    .replace("__BRAND_CSS__", BRAND_CSS)
                    .replace("__BRAND_MARKUP__", BRAND_MARKUP)
                    .replace("__PLAYER_CSS__", PLAYER_CSS)
                    .replace("__PLAYER_CARD__", card_html)
                    .replace("__PLAYER_JS__", PLAYER_JS)
                    .replace("__WATCH_CONFIG__", config_json))
        
        return f'<body style="background:#000;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;font-family:\'DM Sans\',sans-serif;"><div style="text-align:center;background:#141414;padding:40px;border-radius:12px;border:1px solid rgba(255,255,255,.08);"><h2>⚠️ Unsupported File</h2><br><a href="{src}" style="background:#e50914;color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:bold;">Download Direct</a></div></body>'

    except Exception as e:
        logger.error(f"Watch Error: {e}")
        return "<h2 style='color:red;text-align:center;'>Server Error</h2>"
