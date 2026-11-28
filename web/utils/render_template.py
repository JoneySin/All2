import urllib.parse, html, json, logging
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
<style>
:root{{
--bg:#0a0a0c;--bg2:#111116;--bg3:#1d1d26;--card:#14141f;--border:#262636;--text:#ffffff;--muted:#a0a0b0;--accent:#e50914;--red:#e50914;
--nav1:rgba(10,10,12,.95);--nav2:rgba(10,10,12,.4);
}}
html.light{{
--bg:#f4f5f7;--bg2:#ffffff;--bg3:#eef0f4;--card:#ffffff;--border:#d2d5df;--text:#0a0a0c;--muted:#62627a;--accent:#e50914;--red:#e50914;
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
.inline-player-card,.watch-card{{width:100%;background:var(--card);border:1px solid var(--border);border-radius:18px;overflow:hidden;box-shadow:0 24px 80px rgba(0,0,0,.62);}}
html.light .inline-player-card,html.light .watch-card{{box-shadow:0 24px 70px rgba(15,23,42,.22);}}
.inline-player-head,.watch-head{{display:flex;align-items:center;gap:12px;padding:14px 17px;background:linear-gradient(125deg,rgba(229,9,20,.1),transparent 55%),var(--card);border-bottom:1px solid var(--border);}}
.inline-player-mark{{display:grid;place-items:center;width:38px;height:38px;flex:none;color:#fff;background:linear-gradient(135deg,var(--accent),#b20710);border-radius:10px;font-size:16px;box-shadow:0 4px 12px rgba(229,9,20,.32);}}
.inline-player-titlebox{{flex:1;min-width:0;}}
.inline-player-kicker{{color:var(--accent);font-size:10px;letter-spacing:1.1px;text-transform:uppercase;font-weight:900;}}
.inline-player-title{{color:var(--text);font-size:14px;font-weight:800;line-height:1.35;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:2px;}}
.inline-player-screen{{background:#000;aspect-ratio:16/9;display:flex;align-items:center;justify-content:center;position:relative;}}
.inline-player-screen video{{width:100%;height:100%;max-height:56vh;object-fit:contain;background:#000;display:block;}}
.inline-player-status{{padding:9px 17px;color:var(--muted);font-size:12px;font-weight:600;line-height:1.45;background:var(--bg2);border-top:1px solid var(--border);}}
.inline-player-status:empty{{display:none;}}
.inline-player-status.error{{color:#ffb4a9;background:rgba(229,9,20,.12);}}
html.light .inline-player-status.error{{color:#b91c1c;background:rgba(229,9,20,.08);}}
.inline-player-switcher{{padding:15px 17px 14px;background:var(--card);border-top:1px solid var(--border);display:flex;flex-direction:column;gap:12px;}}
.inline-player-switcher[hidden]{{display:none;}}
.inline-player-switch-banner{{display:flex;align-items:center;gap:11px;}}
.inline-player-switch-ico{{display:grid;place-items:center;width:38px;height:38px;flex:none;border-radius:11px;background:rgba(229,9,20,.14);color:#ff6b74;}}
html.light .inline-player-switch-ico{{background:rgba(229,9,20,.1);color:var(--accent);}}
.inline-player-switch-copy{{min-width:0;flex:1;}}
.inline-player-switch-title{{color:var(--text);font-size:15px;font-weight:900;line-height:1.25;}}
.inline-player-switch-sub{{color:var(--muted);font-size:12px;font-weight:500;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}}
.inline-player-switch-group{{display:flex;flex-direction:column;gap:8px;}}
.inline-player-switch-head{{display:flex;align-items:center;justify-content:space-between;gap:10px;color:var(--muted);font-size:10px;letter-spacing:1.1px;text-transform:uppercase;font-weight:900;}}
.inline-player-switch-head span:last-child{{letter-spacing:0;text-transform:none;font-weight:600;font-size:11px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}}
.inline-player-switch-row{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;max-height:240px;overflow-y:auto;padding:2px 1px;scrollbar-width:thin;}}
.inline-player-switch-row.episodes-row{{grid-template-columns:repeat(auto-fill,minmax(94px,1fr));max-height:152px;}}
.inline-player-chip{{display:flex;flex-direction:column;align-items:flex-start;justify-content:center;gap:4px;min-width:0;border:1.5px solid var(--border);background:var(--bg3);color:var(--text);padding:11px 12px;border-radius:12px;font-size:13.5px;font-weight:800;cursor:pointer;font-family:inherit;line-height:1.25;text-align:left;transition:border-color .16s,background .16s,box-shadow .16s;}}
.inline-player-chip:hover:not([aria-current="true"]){{border-color:var(--accent);background:var(--bg2);}}
.inline-player-chip:focus-visible{{outline:2px solid var(--accent);outline-offset:2px;}}
.inline-player-chip-top{{display:flex;align-items:center;justify-content:space-between;gap:8px;width:100%;}}
.inline-player-chip-lbl{{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:14px;font-weight:900;color:var(--text);}}
.inline-player-chip-state{{display:none;font-size:9.5px;font-weight:900;letter-spacing:.5px;text-transform:uppercase;color:#ff6b74;flex-shrink:0;}}
html.light .inline-player-chip-state{{color:#b91c1c;}}
.inline-player-chip[aria-current="true"]{{background:linear-gradient(135deg,rgba(229,9,20,.26),rgba(229,9,20,.1));border-color:var(--accent);box-shadow:inset 3px 0 0 var(--accent);cursor:default;}}
html.light .inline-player-chip[aria-current="true"]{{background:linear-gradient(135deg,rgba(229,9,20,.14),rgba(229,9,20,.04));box-shadow:inset 3px 0 0 var(--accent);}}
.inline-player-chip[aria-current="true"] .inline-player-chip-state{{display:inline-block;}}
.inline-player-chip-name{{width:100%;font-size:11.5px;font-weight:500;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}}
.inline-player-chip-meta{{display:flex;align-items:center;gap:4px;font-size:11px;font-weight:600;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%;}}
.inline-player-switch-note{{color:var(--muted);font-size:10px;}}
.inline-player-actions{{display:flex;flex-direction:column;gap:9px;padding:12px 17px 14px;background:var(--card);border-top:1px solid var(--border);}}
.inline-player-btn-row,.controls-row{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;width:100%;}}
.inline-player-action-btn{{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-width:0;color:var(--text);text-decoration:none;border:1px solid var(--border);background:var(--bg3);padding:10px 8px;border-radius:10px;font:inherit;font-size:12.5px;font-weight:800;cursor:pointer;white-space:nowrap;transition:border-color .16s,color .16s,background .16s;}}
.inline-player-action-btn:hover{{border-color:var(--accent);color:var(--accent);background:var(--bg2);}}
.inline-player-action-btn:focus-visible{{outline:2px solid var(--accent);outline-offset:2px;}}
.inline-player-note{{color:var(--muted);font-size:11px;line-height:1.4;text-align:center;}}
#toast{{visibility:hidden;min-width:200px;background:var(--accent);color:#fff;text-align:center;border-radius:10px;padding:12px 18px;position:fixed;right:20px;bottom:20px;z-index:9999;font-size:13px;font-weight:800;box-shadow:0 10px 30px rgba(0,0,0,.45);}}
#toast.show{{visibility:visible;animation:fi .35s,fo .35s 2.4s;}}
@keyframes fi{{from{{opacity:0;transform:translateY(12px);}}to{{opacity:1;transform:translateY(0);}}}}
@keyframes fo{{from{{opacity:1;transform:translateY(0);}}to{{opacity:0;transform:translateY(12px);}}}}
@media(max-width:768px){{.logo{{font-size:20px;}}}}
@media(max-width:500px){{.hero-container{{padding:76px 10px 30px;}} .inline-player-card,.watch-card{{border-radius:14px;}} .inline-player-head,.watch-head{{padding:12px 13px;}} .inline-player-switcher{{padding:13px 13px 12px;}} .inline-player-actions{{padding:11px 13px 13px;}} .inline-player-screen video{{max-height:50vh;}}}}
@media(max-width:340px){{.inline-player-switch-row,.inline-player-btn-row,.controls-row{{grid-template-columns:1fr;}}}}
__BRAND_CSS__
</style>
</head>
<body>
<div class="navbar">
    <a href="/" class="logo watch-brand" aria-label="FastFinder home">__BRAND_MARKUP__</a>
    <button class="theme-btn" id="theme-btn">Theme</button>
</div>
<div class="hero-container">
<div class="inline-player-card watch-card">
<div class="inline-player-head watch-head"><span class="inline-player-mark" aria-hidden="true">&#9654;</span><div class="inline-player-titlebox"><div class="inline-player-kicker">Now playing</div><div id="watchTitle" class="inline-player-title">{file_name}</div></div></div>
<div class="inline-player-screen"><video id="player" controls playsinline preload="metadata"><source src="{src}" type="{mime_type}"></video></div>
<div id="watchStatus" class="inline-player-status" role="status" aria-live="polite"></div>
<div id="watchSwitcher" class="inline-player-switcher" aria-label="Other versions in this group" hidden></div>
<div class="inline-player-actions"><div class="inline-player-btn-row controls-row">
<a id="dlBtn" href="{src}" class="inline-player-action-btn">&#8595; Download</a>
<button type="button" id="copyBtn" onclick="copyLink()" class="inline-player-action-btn">&#128279; Copy link</button>
<a href="/dashboard" class="inline-player-action-btn">&#8592; Home</a>
</div><span class="inline-player-note">Playback depends on your browser's supported formats.</span></div>
</div></div>
<div id="toast">Link Copied!</div>

<script>
const docEl=document.documentElement, themeBtn=document.getElementById('theme-btn');
if(localStorage.getItem('theme')==='light') docEl.classList.add('light');
themeBtn.addEventListener('click',()=>{{
    let isLight = docEl.classList.toggle('light');
    localStorage.setItem('theme', isLight ? 'light' : 'dark');
}});

var WATCH_STATE = __SWITCH_PAYLOAD__;
var watchCurrentFileId = WATCH_STATE.fileId || '';
var watchSwitchData = WATCH_STATE.switches || null;
var watchEpisode = watchSwitchData ? String(watchSwitchData.current_episode || '') : '';
var watchCopyUrl = new URL(__WATCH_COPY_SRC__, window.location.origin).href;
var watchSwitchReq = 0, watchSwitchAbort = null, watchCopyTimer = null;

function watchStatus(msg, isError){{
    var el = document.getElementById('watchStatus');
    if(!el) return;
    el.textContent = msg || '';
    el.className = isError ? 'inline-player-status error' : 'inline-player-status';
}}

function watchBanner(subtitle){{
    var wrap = document.createElement('div'); wrap.className = 'inline-player-switch-banner';
    var ico = document.createElement('span'); ico.className = 'inline-player-switch-ico'; ico.setAttribute('aria-hidden', 'true');
    ico.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><line x1="7" y1="9" x2="17" y2="9"/><line x1="7" y1="13" x2="17" y2="13"/><line x1="7" y1="17" x2="13" y2="17"/></svg>';
    var copy = document.createElement('div'); copy.className = 'inline-player-switch-copy';
    var title = document.createElement('div'); title.className = 'inline-player-switch-title'; title.textContent = 'Episodes & qualities';
    var sub = document.createElement('div'); sub.className = 'inline-player-switch-sub'; sub.textContent = subtitle || 'Choose a version to play';
    copy.appendChild(title); copy.appendChild(sub); wrap.appendChild(ico); wrap.appendChild(copy); return wrap;
}}

function watchHead(label, detail){{
    var head = document.createElement('div'); head.className = 'inline-player-switch-head';
    var left = document.createElement('span'); left.textContent = label;
    var right = document.createElement('span'); right.textContent = detail || '';
    head.appendChild(left); head.appendChild(right); return head;
}}

function watchRow(label, extraClass){{
    var row = document.createElement('div');
    row.className = 'inline-player-switch-row' + (extraClass ? ' ' + extraClass : '');
    row.setAttribute('role', 'group'); row.setAttribute('aria-label', label); return row;
}}

function watchItemMeta(item){{
    var parts = []; if(item.duration) parts.push(item.duration); if(item.size) parts.push(item.size); return parts.join(' · ');
}}

function watchChip(row, label, meta, current, title, onClick, showName){{
    var chip = document.createElement('button'); chip.type = 'button'; chip.className = 'inline-player-chip';
    var top = document.createElement('div'); top.className = 'inline-player-chip-top';
    var text = document.createElement('span'); text.className = 'inline-player-chip-lbl'; text.textContent = label || 'Version';
    var state = document.createElement('span'); state.className = 'inline-player-chip-state'; state.textContent = 'SELECTED';
    top.appendChild(text); top.appendChild(state); chip.appendChild(top);
    if(showName && title){{ var sub = document.createElement('div'); sub.className = 'inline-player-chip-name'; sub.textContent = title; chip.appendChild(sub); }}
    if(meta){{ var small = document.createElement('div'); small.className = 'inline-player-chip-meta'; small.textContent = '⏱ ' + meta; chip.appendChild(small); }}
    chip.title = title || '';
    if(current){{ chip.setAttribute('aria-current', 'true'); chip.title = 'Currently playing'; }}
    else if(onClick) chip.addEventListener('click', onClick);
    row.appendChild(chip); return chip;
}}

function watchQualityItem(episode, preferredLabel){{
    var items = (episode && episode.items) || [];
    if(!items.length) return null;
    if(preferredLabel){{ for(var i = 0; i < items.length; i++){{ if(items[i].label === preferredLabel) return items[i]; }} }}
    return items[items.length - 1];
}}

function watchQualityLabelForFile(fileId, data){{
    var episodes = (data && data.episodes) || [];
    for(var i = 0; i < episodes.length; i++){{
        var items = episodes[i].items || [];
        for(var j = 0; j < items.length; j++){{ if(items[j].file_id === fileId) return items[j].label || ''; }}
    }}
    return '';
}}

function watchPaintSwitches(){{
    var box = document.getElementById('watchSwitcher');
    if(!box) return;
    box.textContent = '';
    var data = watchSwitchData;
    if(!data || !data.group){{ box.hidden = true; return; }}
    var group = data.group;
    if(group.type === 'series' && data.episodes && data.episodes.length){{
        var episodes = data.episodes, current = null, i;
        if(!watchEpisode) watchEpisode = data.current_episode || episodes[0].key;
        for(i = 0; i < episodes.length; i++){{ if(episodes[i].key === watchEpisode){{ current = episodes[i]; break; }} }}
        if(!current){{ current = episodes[0]; watchEpisode = current.key; }}
        box.appendChild(watchBanner(group.name ? 'Choose a version · ' + group.name : 'Choose a version to play'));
        var epSec = document.createElement('div'); epSec.className = 'inline-player-switch-group';
        epSec.appendChild(watchHead('Episodes', episodes.length + (group.truncated ? ' of ' + group.episode_count : '') + ' episodes'));
        var episodeRow = watchRow('Episodes', 'episodes-row');
        for(i = 0; i < episodes.length; i++){{
            (function(ep){{
                watchChip(episodeRow, ep.label, '', ep.key === watchEpisode, ep.label, function(){{ watchPickEpisode(ep.key); }}, false);
            }})(episodes[i]);
        }}
        epSec.appendChild(episodeRow); box.appendChild(epSec);
        var qSec = document.createElement('div'); qSec.className = 'inline-player-switch-group';
        qSec.appendChild(watchHead('Quality', current.label || ''));
        var qualityRow = watchRow('Quality versions of this episode'), items = current.items || [];
        for(i = 0; i < items.length; i++){{
            (function(item){{
                watchChip(qualityRow, item.label, watchItemMeta(item), item.file_id === watchCurrentFileId, item.name, function(){{ switchWatchFile(item.file_id, item.name, false); }}, true);
            }})(items[i]);
        }}
        qSec.appendChild(qualityRow); box.appendChild(qSec);
        if(group.truncated){{
            var note = document.createElement('div'); note.className = 'inline-player-switch-note';
            note.textContent = 'Only the first ' + episodes.length + ' episodes are listed here.';
            box.appendChild(note);
        }}
    }}else{{
        var items = data.items || [];
        if(items.length < 2){{ box.hidden = true; return; }}
        box.appendChild(watchBanner(group.name ? 'Choose a version · ' + group.name : 'Choose a version to play'));
        var qOnly = document.createElement('div'); qOnly.className = 'inline-player-switch-group';
        var row = watchRow('Quality versions');
        for(var j = 0; j < items.length; j++){{
            (function(item){{
                watchChip(row, item.label, watchItemMeta(item), item.file_id === watchCurrentFileId, item.name, function(){{ switchWatchFile(item.file_id, item.name, false); }}, true);
            }})(items[j]);
        }}
        qOnly.appendChild(row); box.appendChild(qOnly);
        if(group.truncated){{
            var note2 = document.createElement('div'); note2.className = 'inline-player-switch-note';
            note2.textContent = 'Only the first ' + items.length + ' files are listed here.';
            box.appendChild(note2);
        }}
    }}
    box.hidden = false;
}}

async function watchPickEpisode(key){{
    var data = watchSwitchData, episodes = (data && data.episodes) || [], target = null, previous = watchEpisode;
    for(var i = 0; i < episodes.length; i++){{ if(episodes[i].key === key){{ target = episodes[i]; break; }} }}
    if(!target || key === previous) return;
    var item = watchQualityItem(target, watchQualityLabelForFile(watchCurrentFileId, data));
    if(!item) return;
    watchEpisode = key; watchPaintSwitches();
    var switched = await switchWatchFile(item.file_id, item.name, true);
    if(!switched && watchEpisode === key){{ watchEpisode = previous; watchPaintSwitches(); }}
}}

async function switchWatchFile(fileId, title, resetPosition){{
    var video = document.getElementById('player'), titleEl = document.getElementById('watchTitle');
    if(!fileId || !video) return false;
    if(fileId === watchCurrentFileId) return true;
    var resume = resetPosition ? 0 : (isFinite(video.currentTime) ? video.currentTime : 0);
    var req = ++watchSwitchReq;
    if(watchSwitchAbort) watchSwitchAbort.abort();
    watchSwitchAbort = new AbortController();
    watchStatus(resetPosition ? 'Loading selected episode...' : 'Switching version...', false);
    try{{
        var res = await fetch('/api/watch/switch', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{mid: WATCH_STATE.mid, e: WATCH_STATE.e, s: WATCH_STATE.s, file_id: fileId}}),
            signal: watchSwitchAbort.signal
        }});
        var data = await res.json().catch(function(){{ return {{}}; }});
        if(!res.ok || data.error) throw new Error(data.error || 'Unable to switch version.');
        if(req !== watchSwitchReq) return false;
        var parsed = new URL(data.url, window.location.origin);
        var dl = new URL(parsed); dl.searchParams.delete('inline');
        var srcUrl = parsed.pathname + parsed.search;
        var dlUrl = dl.pathname + dl.search;
        watchCurrentFileId = fileId;
        if(titleEl && title) titleEl.textContent = title;
        var dlBtn = document.getElementById('dlBtn');
        if(dlBtn) dlBtn.href = dlUrl;
        watchCopyUrl = dl.href;
        var copyBtn = document.getElementById('copyBtn');
        if(copyBtn) copyBtn.textContent = '🔗 Copy link';
        video.pause();
        video.innerHTML = '';
        video.src = srcUrl;
        if(resume > 0.5){{
            video.addEventListener('loadedmetadata', function(){{
                if(isFinite(video.duration) && video.duration > 0) video.currentTime = Math.min(resume, Math.max(0, video.duration - 1));
            }}, {{once: true}});
        }}
        video.load();
        var play = video.play();
        if(play && play.catch) play.catch(function(){{}});
        watchStatus('', false);
        watchPaintSwitches();
        return true;
    }}catch(err){{
        if(err && err.name === 'AbortError') return false;
        if(req === watchSwitchReq) watchStatus((err && err.message) || 'Could not switch version.', true);
        return false;
    }}
}}

watchPaintSwitches();

function copyLink(){{
    var btn = document.getElementById('copyBtn');
    function done(){{
        if(btn) btn.textContent = '✓ Copied!';
        var t = document.getElementById('toast');
        if(t){{ t.classList.add('show'); setTimeout(function(){{ t.classList.remove('show'); }}, 2800); }}
        clearTimeout(watchCopyTimer);
        watchCopyTimer = setTimeout(function(){{ if(btn && btn.isConnected) btn.textContent = '🔗 Copy link'; }}, 1800);
    }}
    if(navigator.clipboard && navigator.clipboard.writeText){{
        navigator.clipboard.writeText(watchCopyUrl).then(done).catch(fallbackCopy);
    }}else{{ fallbackCopy(); }}
    function fallbackCopy(){{
        var ta = document.createElement('textarea'); ta.value = watchCopyUrl; ta.style.position = 'fixed'; ta.style.opacity = '0';
        document.body.appendChild(ta); ta.select();
        try{{ document.execCommand('copy'); done(); }}catch(_){{}}
        document.body.removeChild(ta);
    }}
}}
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
            qs = urllib.parse.parse_qs(query or "")
            raw_name = info.file_name or "Fast Finder Movie"
            switch_payload = {
                "mid": int(message_id),
                "e": (qs.get("e") or [""])[0],
                "s": (qs.get("s") or [""])[0],
                "fileId": "",
                "switches": None,
            }
            raw_fid = getattr(info, "file_id", None)
            if raw_fid:
                try:
                    from database.ia_filterdb import unpack_new_file_id, get_files_by_ids
                    from web.search_api import _switches_for
                    origin_fid = unpack_new_file_id(raw_fid)
                    if origin_fid:
                        switch_payload["fileId"] = origin_fid
                        switches = await _switches_for(origin_fid)
                        if switches and switches.get("group"):
                            switch_payload["switches"] = switches
                        docs = await get_files_by_ids([origin_fid])
                        if docs and docs[0].get("file_name"):
                            raw_name = docs[0]["file_name"]
                except Exception:
                    logger.debug("watch switches lookup skipped", exc_info=True)

            fn = html.escape(raw_name)   # None => crash fix
            payload_json = json.dumps(switch_payload).replace("<", "\\u003c")
            src_json = json.dumps(src).replace("<", "\\u003c")
            return (watch_tmplt.format(heading=f"Watch {fn}", file_name=fn, src=src, mime_type=html.escape(mime))
                    .replace("__BRAND_CSS__", BRAND_CSS)
                    .replace("__BRAND_MARKUP__", BRAND_MARKUP)
                    .replace("__SWITCH_PAYLOAD__", payload_json)
                    .replace("__WATCH_COPY_SRC__", src_json))
        
        return f'<body style="background:#000;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;font-family:\'DM Sans\',sans-serif;"><div style="text-align:center;background:#141414;padding:40px;border-radius:12px;border:1px solid rgba(255,255,255,.08);"><h2>⚠️ Unsupported File</h2><br><a href="{src}" style="background:#e50914;color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:bold;">Download Direct</a></div></body>'

    except Exception as e:
        logger.error(f"Watch Error: {e}")
        return "<h2 style='color:red;text-align:center;'>Server Error</h2>"
