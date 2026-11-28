import urllib.parse, html, logging
from info import URL
from web.utils.media_info import get_media_info
from web.brand import BRAND_MARKUP, BRAND_CSS

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# 🎬 FAST FINDER OPTIMIZED STREAM TEMPLATE
# ─────────────────────────────────────────────
watch_tmplt = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>{heading}</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/plyr@3.8.5/dist/plyr.css"/>
<style>
:root{{
--red:#e50914; --bg1:#0b0b0d; --bg2:#141414; --card:#181818; --bg3:#262629; --txt:#fff; 
--nav1:rgba(0,0,0,.95); --nav2:rgba(0,0,0,.4); 
--box:#000; --box-bd:rgba(255,255,255,.12); 
--btn-c:rgba(255,255,255,.08); --btn-bd:rgba(255,255,255,.12); --txt-muted:#9ca3af;
}}
html.light{{
--bg1:#f4f6f9; --bg2:#e9edf3; --card:#ffffff; --bg3:#eff2f7; --txt:#111827; 
--nav1:rgba(255,255,255,.95); --nav2:rgba(255,255,255,.4); 
--box:#ffffff; --box-bd:rgba(15,23,42,.12); 
--btn-c:rgba(15,23,42,.06); --btn-bd:rgba(15,23,42,.14); --txt-muted:#64748b;
}}
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:linear-gradient(to bottom,var(--bg1),var(--bg2));font-family:'DM Sans',sans-serif;color:var(--txt);min-height:100vh;transition:background .3s,color .3s;}}
.navbar{{width:100%;padding:16px 4%;display:flex;align-items:center;justify-content:space-between;position:fixed;top:0;z-index:999;background:linear-gradient(to bottom,var(--nav1),var(--nav2),transparent);backdrop-filter:blur(6px);transition:background .3s;}}
.logo{{font-size:24px;font-weight:900;letter-spacing:1px;color:var(--red);display:flex;align-items:center;gap:8px;text-decoration:none;transition:.3s;}}
.logo:hover{{transform:scale(1.02);}}
.theme-btn{{background:var(--card);border:1px solid var(--box-bd);color:var(--txt);padding:8px 16px;border-radius:10px;font-family:'DM Sans',sans-serif;font-weight:800;font-size:13px;cursor:pointer;transition:.2s;}}
.theme-btn:hover{{border-color:var(--red);color:var(--red);}}
.hero-container{{width:100%;max-width:860px;margin:auto;padding:96px 16px 40px;}}
.watch-card{{background:var(--card);border:1px solid var(--box-bd);border-radius:18px;overflow:hidden;box-shadow:0 24px 80px rgba(0,0,0,.55);}}
html.light .watch-card{{box-shadow:0 24px 70px rgba(15,23,42,.16);}}
.watch-head{{display:flex;align-items:center;gap:12px;padding:14px 17px;background:linear-gradient(125deg,rgba(229,9,20,.1),transparent 55%),var(--card);border-bottom:1px solid var(--box-bd);}}
.watch-mark{{display:grid;place-items:center;width:38px;height:38px;flex:none;color:#fff;background:linear-gradient(135deg,var(--red),#b20710);border-radius:10px;font-size:16px;box-shadow:0 4px 12px rgba(229,9,20,.32);}}
.watch-titlebox{{flex:1;min-width:0;}}
.watch-kicker{{color:var(--red);font-size:10px;letter-spacing:1.1px;text-transform:uppercase;font-weight:900;}}
.title{{font-size:15px;font-weight:800;line-height:1.35;color:var(--txt);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:2px;}}
.player-box{{width:100%;background:#000;position:relative;overflow:hidden;}}
video{{width:100%;height:auto;max-height:66vh;display:block;}}
.skip-zone{{position:absolute;top:0;bottom:35%;width:30%;z-index:20;display:flex;align-items:center;justify-content:center;cursor:pointer;-webkit-tap-highlight-color:transparent;touch-action:manipulation;}}
.skip-zone.left{{left:0;}} .skip-zone.right{{right:0;}}
.skip-ripple{{position:absolute;inset:0;background:rgba(255,255,255,.12);opacity:0;transition:opacity .3s;display:flex;flex-direction:column;align-items:center;justify-content:center;pointer-events:none;}}
html.light .skip-ripple{{background:rgba(0,0,0,.1);}}
.skip-zone.left .skip-ripple{{border-radius:0 50% 50% 0/0 100% 100% 0;transform-origin:left center;}}
.skip-zone.right .skip-ripple{{border-radius:50% 0 0 50%/100% 0 0 100%;transform-origin:right center;}}
.skip-zone.active .skip-ripple{{opacity:1;animation:pop .3s cubic-bezier(.25,1,.5,1) forwards;}}
@keyframes pop{{0%{{transform:scaleX(.85);}} 100%{{transform:scaleX(1);}}}}
.skip-text{{color:#fff;font-weight:800;font-size:14px;margin-top:6px;text-shadow:0 2px 8px rgba(0,0,0,.6);letter-spacing:.5px;}}
.skip-arrows svg{{width:28px;height:28px;fill:#fff;filter:drop-shadow(0 2px 6px rgba(0,0,0,.5));}}
.info-section{{padding:13px 17px 15px;border-top:1px solid var(--box-bd);display:flex;flex-direction:column;gap:9px;}}
.controls-row{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;width:100%;}}
.btn{{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-width:0;padding:10px 8px;border-radius:10px;text-decoration:none;font-family:inherit;font-size:12.5px;font-weight:800;cursor:pointer;transition:border-color .16s,color .16s,background .16s;border:1px solid var(--box-bd);background:var(--bg3);color:var(--txt);white-space:nowrap;}}
.btn:hover{{border-color:var(--red);color:var(--red);background:var(--bg2);}}
.watch-note{{color:var(--txt-muted);font-size:11px;line-height:1.4;text-align:center;}}
.plyr--video{{--plyr-color-main:#e50914;--plyr-video-background:#000;}}
.plyr__control--overlaid,.plyr__control:hover{{background:rgba(229,9,20,.9)!important;}} .plyr__controls{{z-index:30!important;}}
#toast{{visibility:hidden;min-width:220px;background:var(--red);color:#fff;text-align:center;border-radius:6px;padding:15px;position:fixed;right:30px;bottom:30px;z-index:9999;font-weight:700;box-shadow:0 10px 30px rgba(0,0,0,.45);}}
#toast.show{{visibility:visible;animation:fi .4s,fo .4s 2.6s;}}
@keyframes fi{{from{{opacity:0;bottom:0;}}to{{opacity:1;bottom:30px;}}}} @keyframes fo{{from{{opacity:1;bottom:30px;}}to{{opacity:0;bottom:0;}}}}
@media(max-width:768px){{.hero-container{{padding:84px 10px 30px;}} .logo{{font-size:20px;}} .watch-head{{padding:12px 13px;}} .info-section{{padding:11px 13px 13px;}}}}
@media(max-width:340px){{.controls-row{{grid-template-columns:1fr;}}}}
__BRAND_CSS__
</style>
</head>
<body>
<div class="navbar">
    <a href="/" class="logo watch-brand" aria-label="FastFinder home">__BRAND_MARKUP__</a>
    <button class="theme-btn" id="theme-btn">Theme</button>
</div>
<div class="hero-container">
<div class="watch-card">
<div class="watch-head"><span class="watch-mark" aria-hidden="true">&#9654;</span><div class="watch-titlebox"><div class="watch-kicker">Now playing</div><div class="title">{file_name}</div></div></div>
<div class="player-box"><video id="player" playsinline controls><source src="{src}" type="{mime_type}"></video></div>
<div class="info-section"><div class="controls-row">
<a href="{src}" class="btn btn-download">&#8595; Download</a>
<button type="button" onclick="copyLink()" class="btn btn-copy">&#128279; Copy link</button>
<a href="/dashboard" class="btn">&#8592; Home</a>
</div><span class="watch-note">Playback depends on your browser's supported formats.</span></div>
</div></div>
<div id="toast">Link Copied!</div>

<script src="https://cdn.jsdelivr.net/npm/plyr@3.8.5/dist/plyr.min.js"></script>
<script>
const docEl=document.documentElement, themeBtn=document.getElementById('theme-btn');
if(localStorage.getItem('theme')==='light') docEl.classList.add('light');
themeBtn.addEventListener('click',()=>{{
    let isLight = docEl.classList.toggle('light');
    localStorage.setItem('theme', isLight ? 'light' : 'dark');
}});

const player=new Plyr('#player',{{iconUrl:'https://cdn.jsdelivr.net/npm/plyr@3.8.5/dist/plyr.svg',controls:['play-large','play','progress','current-time','mute','settings','pip','fullscreen'],settings:['quality','speed'],autoplay:!1,doubleClick:{{togglesFullscreen:!1}}}});

player.on('enterfullscreen', ()=>{{
    if(screen.orientation && screen.orientation.lock) {{
        screen.orientation.lock('landscape').catch(e => console.log(e));
    }}
}});
player.on('exitfullscreen', ()=>{{
    if(screen.orientation && screen.orientation.unlock) {{
        screen.orientation.unlock();
    }}
}});

player.on('ready',()=>{{
    const c=document.querySelector('.plyr'), l=document.createElement('div'), r=document.createElement('div');
    l.className='skip-zone left'; r.className='skip-zone right';
    const ui=d=>'<div class="skip-ripple"><div class="skip-arrows"><svg viewBox="0 0 24 24">'+d+'</svg></div><div class="skip-text">10s</div></div>';
    l.innerHTML=ui('<path d="M11 18V6l-8.5 6 8.5 6zm.5-6l8.5 6V6l-8.5 6z"/>');
    r.innerHTML=ui('<path d="M4 18l8.5-6L4 6v12zm9-12v12l8.5-6-8.5-6z"/>');
    c.append(l,r);
    
    let tc=0, tmr;
    const tap=(e,side,z)=>{{
        e.preventDefault(); e.stopPropagation();
        tc++; 
        clearTimeout(tmr);
        
        // ✅ FIX: यूट्यूब स्टाइल प्रोग्रेसिव 10s जंप और रिपल एनीमेशन सिंक किया गया
        let t = tc * 10; 
        z.querySelector('.skip-text').innerText = t + 's';
        z.classList.remove('active'); void z.offsetWidth; z.classList.add('active');
        
        tmr = setTimeout(() => {{
            player.currentTime += side === 'l' ? -t : t; 
            z.classList.remove('active'); 
            tc = 0;
        }}, 400);
    }};
    ['dblclick','click'].forEach(ev=>{{l.addEventListener(ev,e=>{{e.preventDefault();e.stopPropagation()}});r.addEventListener(ev,e=>{{e.preventDefault();e.stopPropagation()}})}});
    l.addEventListener('pointerup',e=>tap(e,'l',l)); r.addEventListener('pointerup',e=>tap(e,'r',r));
}});

function copyLink(){{navigator.clipboard.writeText("{src}"); let t=document.getElementById("toast"); t.classList.add("show"); setTimeout(()=>t.classList.remove("show"),3000);}}
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

        src = urllib.parse.urljoin(URL, f'download/{message_id}')
        if query:
            src += f'?{query}'      # signed token download request me bhi jaata hai
        mime = info.mime_type or 'video/mp4'   # None => crash fix

        if mime.split('/')[0].strip() == 'video':
            fn = html.escape(info.file_name or "Fast Finder Movie")   # None => crash fix
            return (watch_tmplt.format(heading=f"Watch {fn}", file_name=fn, src=src, mime_type=html.escape(mime))
                    .replace("__BRAND_CSS__", BRAND_CSS).replace("__BRAND_MARKUP__", BRAND_MARKUP))
        
        return f'<body style="background:#000;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;font-family:\'DM Sans\',sans-serif;"><div style="text-align:center;background:#141414;padding:40px;border-radius:12px;border:1px solid rgba(255,255,255,.08);"><h2>⚠️ Unsupported File</h2><br><a href="{src}" style="background:#e50914;color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:bold;">Download Direct</a></div></body>'

    except Exception as e:
        logger.error(f"Watch Error: {e}")
        return "<h2 style='color:red;text-align:center;'>Server Error</h2>"
