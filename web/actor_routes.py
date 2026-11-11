import io, time, html, re, uuid
from urllib.parse import urlencode, urlsplit
from aiohttp import web
from bson.objectid import ObjectId
from utils import temp
from info import MAX_WEB_RESULTS, ACTOR_STORAGE_CHANNEL
from database.ia_filterdb import actors, get_actor_search_results, delete_actor_profile, delete_gallery_image_by_index
# ✅ DRY: fast_json + DIRECTORY_CSS अब web_assets से आते हैं (पहले दोनों यहाँ copy थे)
from web.web_assets import build_page, get_auth, require_active_plan, fast_json, DIRECTORY_CSS, DEFAULT_CATALOG_MODE, DEFAULT_MEDIA_MODE
from web.search_api import _build_results_list, _annotate_raw_groups

actor_routes = web.RouteTableDef()

ACTOR_MEDIA_SCRIPT = r'''<script>
var actorMediaFiles={};
function actorEsc(value){return String(value==null?'':value).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
function actorPlayFile(card){var f=actorMediaFiles[card.dataset.fid];if(f)openInlinePlayer(f.stream_id||f.file_id,f.name);}
function actorEditFile(card){var f=actorMediaFiles[card.dataset.fid];if(f)editFile(f.file_id,f.raw_collection||'primary',encodeURIComponent(f.name||'').replace(/'/g,'%27'),encodeURIComponent(f.caption||'').replace(/'/g,'%27'));}
function actorDeleteFile(card){var f=actorMediaFiles[card.dataset.fid];if(f)deleteFile(f.file_id,f.raw_collection||'primary');}
function renderActorMediaCard(f,mode,isAdmin){
    actorMediaFiles[f.file_id]=f;
    var sc=String(f.raw_collection||'primary').toLowerCase();if(!['primary','cloud','archive'].includes(sc))sc='primary';
    var fid=actorEsc(f.file_id),name=actorEsc(f.name),source='<span class="source-pill '+sc+'"><span class="source-dot"></span>'+sc.toUpperCase()+'</span>';
    var id=f.group_num||f.gid,idChip=id?'<span class="actor-group-id">GROUP #'+actorEsc(id)+'</span>':'';
    var duration=f.duration?'<span class="'+(mode==='none'?'tc-dur':'dur-chip')+'">'+actorEsc(f.duration)+'</span>':'';
    var res=f.res?'<span class="'+(mode==='none'?'tc-res':'res-chip')+'">'+actorEsc(f.res)+'</span>':'';
    var posterTrigger=isAdmin?'<button type="button" class="file-poster-trigger" aria-label="Show file editing options" aria-expanded="false" onclick="toggleAdminBtns(this.closest(\'.file-card\'),event)"></button>':'';
    var actions=isAdmin?'<button class="btn-edit" onclick="event.stopPropagation();actorEditFile(this.closest(\'.file-card\'))">&#9999; Edit</button><button class="btn-del" onclick="event.stopPropagation();actorDeleteFile(this.closest(\'.file-card\'))">&#128465; Delete</button>':'';
    var badges=idChip+'<span class="'+(mode==='none'?'tc-size':'size-chip')+'">'+actorEsc(f.size||'')+'</span>'+duration+res+source;
    var visual=mode==='none'?'<div class="fc-text-info">'+badges+'</div>'+(isAdmin?'<div class="text-admin-row">'+actions+'</div>':''):
        '<div class="poster-box" id="poster-box-'+fid+'"><img src="'+actorEsc(f.tg_thumb||'')+'" id="img-poster-'+fid+'" class="fc-poster" onload="this.classList.add(\'loaded\')" onerror="handleThumbError(this.closest(\'.file-card\').dataset.fid)" loading="lazy"><div class="poster-top">'+badges+'</div>'+posterTrigger+(isAdmin?'<div class="poster-admin">'+actions+'</div>':'')+'</div>';
    var textControl=isAdmin&&mode==='none'?' role="button" tabindex="0" aria-label="Show file editing options" aria-expanded="false" onclick="textFileClick(this,event)" onkeydown="textFileKey(this,event)"':'';
    return '<div class="file-card card-enter'+(textControl?' text-file-trigger':'')+'" data-fid="'+fid+'"'+textControl+'>'+visual+'<div class="fc-body"><button type="button" class="fc-name" id="name-title-'+fid+'" onclick="actorPlayFile(this.closest(\'.file-card\'))">'+name+'</button></div></div>';
}
</script><style>.actor-group-id{display:inline-flex;background:#39230b;color:#ffd58a;border:1px solid #d99b3b;border-radius:6px;padding:3px 7px;font-size:10px;font-weight:800;white-space:nowrap}.poster-top{flex-wrap:wrap;align-content:flex-start}</style>'''

# ─────────────────────────────────────────────────────────
# 🌐 MAIN HOMEPAGE: UNIVERSAL DIRECTORY WITH SEARCH & FILTERS
# ─────────────────────────────────────────────────────────
@actor_routes.get('/actors')
async def actors_directory_page(req):
    role, tg_id = await get_auth(req)
    if not role: return web.HTTPFound('/login')
    if not await require_active_plan(role, tg_id): return web.HTTPFound('/premium_expired')
    
    all_actors = await actors.find({}).sort("created_at", -1).limit(21).to_list(length=21)
    has_next_init = len(all_actors) > 20
    all_actors = all_actors[:20]
    
    admin_btn = '''<button onclick="window.location.href='/admin/create_actor'" style="background:var(--accent); color:#fff; border:none; padding:10px 15px; border-radius:8px; font-weight:800; cursor:pointer; font-size:13px; flex:1; min-width:130px; box-shadow:0 4px 15px rgba(229,9,20,0.3); transition:0.2s;">➕ Create Profile</button>''' if role == 'admin' else ""
    
    search_ui = f'''
    {DIRECTORY_CSS}

    <div class="search-box">
        <div class="s-row-1" id="dirSearchRow">
            <input type="text" id="dir_q" class="s-input" placeholder="Search...">
            <span class="s-spinner" id="dirSpinner"></span>
        </div>
        <div class="s-row-2">
            <div class="cdd-wrap" onclick="toggleDirCDD('cat', event)">
                <span id="dir_cat_lbl">📂 All</span> <span style="font-size:10px; color:var(--muted);">▼</span>
                <div class="cdd-menu" id="dir_cat_menu">
                    <div class="cdd-item" onclick="pickDirCat('all', '📂 All', event)">📂 All</div>
                    <div class="cdd-item" onclick="pickDirCat('actor', '🎭 Actor', event)">🎭 Actor</div>
                    <div class="cdd-item" onclick="pickDirCat('app', '📱 App', event)">📱 App</div>
                    <div class="cdd-item" onclick="pickDirCat('website', '🌐 Website', event)">🌐 Website</div>
                </div>
            </div>
            <div class="cdd-wrap" onclick="toggleDirCDD('mode', event)">
                <span id="dir_mode_lbl">{'📄 Text' if DEFAULT_CATALOG_MODE == 'text' else '🖼️ Poster'}</span> <span style="font-size:10px; color:var(--muted);">▼</span>
                <div class="cdd-menu" id="dir_mode_menu">
                    <div class="cdd-item" onclick="pickDirMode('poster', '🖼️ Poster', event)">🖼️ Poster</div>
                    <div class="cdd-item" onclick="pickDirMode('text', '📄 Text', event)">📄 Text</div>
                </div>
            </div>
            {admin_btn}
        </div>
    </div>
    '''

    act_items = ""
    for a in all_actors:
        cat = a.get("category", "actor")
        i = "🎭" if cat == "actor" else "📱" if cat == "app" else "🌐"
        v = a.get("photo_revision") or int(a.get("photo_updated_at") or a.get("created_at") or 0)
        # ✅ Centralized default: text mode ⇒ initial server render भी text cards देता है (API text branch जैसा ही markup)
        if DEFAULT_CATALOG_MODE == "text":
            act_items += f'''<div class="act-text-card" style="background:var(--card); border:1px solid var(--border); padding:15px; border-radius:8px; display:flex; justify-content:space-between; align-items:center; cursor:pointer; transition:0.2s;" onclick="window.location.href=\'/actor/{str(a["_id"])}\'" onmouseover="this.style.borderColor='var(--accent)'" onmouseout="this.style.borderColor='var(--border)'"><div style="font-weight:800; color:var(--text); font-size:14px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:65%;">{html.escape(a.get("name",""))}</div><div style="background:var(--bg3); padding:4px 10px; border-radius:6px; font-size:11px; font-weight:800; color:var(--muted); white-space:nowrap; border:1px solid var(--border);">{i} {cat.capitalize()}</div></div>'''
            continue
        act_items += f'<div class="act-card card-enter" onclick="window.location.href=\'/actor/{str(a["_id"])}\'">\n            <div class="poster-wrap" style="position:relative; padding-top:135%; background:var(--bg3); overflow:hidden;">\n                <img src="/api/actor/photo?id={str(a["_id"])}&v={v}" class="act-poster" loading="lazy">\n                <div style="position:absolute; top:8px; left:8px; background:rgba(229,9,20,0.9); color:#fff; font-size:10px; padding:4px 8px; border-radius:4px; font-weight:800; backdrop-filter:blur(4px); z-index:2; text-transform:uppercase; box-shadow:0 2px 10px rgba(0,0,0,0.5);">{i} {cat.capitalize()}</div>\n                <div style="position:absolute; bottom:0; left:0; right:0; background:linear-gradient(to top, rgba(0,0,0,0.95) 0%, rgba(0,0,0,0.7) 40%, transparent 100%); padding:30px 12px 12px 12px; z-index:2; text-align:center;">\n                    <div style="font-size:14.5px; font-weight:900; color:#fff; text-overflow:ellipsis; overflow:hidden; white-space:nowrap; text-shadow:0 2px 6px rgba(0,0,0,0.9); letter-spacing:0.5px;">{html.escape(a.get("name", ""))}</div>\n                </div>\n            </div>\n            <div class="card-body">\n                <div style="font-size:14px; font-weight:800; color:var(--text); text-overflow:ellipsis; overflow:hidden; white-space:nowrap;">{html.escape(a.get("name", ""))}</div>\n                <div style="font-size:11px; color:var(--muted); font-weight:700; margin-top:4px;">{html.escape(cat.capitalize())}</div>\n            </div>\n        </div>'
    
    dir_grid_style = ' style="display:flex; flex-direction:column; gap:10px;"' if DEFAULT_CATALOG_MODE == "text" else ""
    initial_grid = f'<div id="dir_grid_container" class="dir-grid"{dir_grid_style}>{act_items}</div>' if all_actors else '<div id="dir_grid_container" style="color:var(--muted); text-align:center; padding:60px 20px;">📇 No profiles found.</div>'
    
    has_nxt_str = "true" if has_next_init else "false"

    js_logic = f'''
    <div class="pg-bar" id="dir_pg_box" style="display:none;">
        <button class="pg-btn" id="dir_pBtn" onclick="prevDir()" disabled>Previous</button>
        <span class="pg-info" id="dir_pgInfo">Page 1</span>
        <button class="pg-btn" id="dir_nBtn" onclick="nextDir()">Next</button>
    </div>

    <script>
    var dirOffset = 0; var dirLimit = 20; var dirPage = 1;
    var hasNext = {has_nxt_str};
    var currentCat = 'all'; var currentMode = '{DEFAULT_CATALOG_MODE}';
    var lastQ = "", lastCat = "all", lastMode = "{DEFAULT_CATALOG_MODE}", lastOffset = 0;
    var dirReqId = 0;
    
    document.addEventListener("DOMContentLoaded", () => {{ 
        if(sessionStorage.getItem('ff_dir_state')) {{
            document.getElementById('dir_q').value = sessionStorage.getItem('ff_dir_q') || "";
            currentCat = sessionStorage.getItem('ff_dir_cat') || "all";
            currentMode = sessionStorage.getItem('ff_dir_mode') || "{DEFAULT_CATALOG_MODE}";
            dirOffset = parseInt(sessionStorage.getItem('ff_dir_off') || "0");
            dirPage = parseInt(sessionStorage.getItem('ff_dir_page') || "1");
            
            const catMap = {{'all':'📂 All', 'actor':'🎭 Actor', 'app':'📱 App', 'website':'🌐 Website'}};
            const modeMap = {{'poster':'🖼️ Poster', 'text':'📄 Text'}};
            document.getElementById('dir_cat_lbl').innerText = catMap[currentCat] || '📂 All';
            document.getElementById('dir_mode_lbl').innerText = modeMap[currentMode] || modeMap['{DEFAULT_CATALOG_MODE}'];
            
            searchDirectory(true);
        }} else {{
            updatePgUI();
            staggerCards(document.getElementById('dir_grid_container'));
        }}
    }});

    function closeAllDirCDD() {{ document.getElementById('dir_cat_menu').style.display='none'; document.getElementById('dir_mode_menu').style.display='none'; }}
    document.addEventListener('click', closeAllDirCDD);

    function toggleDirCDD(type, e) {{
        e.stopPropagation();
        var menu = document.getElementById('dir_' + type + '_menu');
        var isVis = menu.style.display === 'block';
        closeAllDirCDD();
        if (!isVis) menu.style.display = 'block';
    }}

    function pickDirCat(val, lbl, e) {{ e.stopPropagation(); currentCat = val; document.getElementById('dir_cat_lbl').innerText = lbl; closeAllDirCDD(); resetDir(); searchDirectory(); }}
    function pickDirMode(val, lbl, e) {{ e.stopPropagation(); currentMode = val; document.getElementById('dir_mode_lbl').innerText = lbl; closeAllDirCDD(); resetDir(); searchDirectory(); }}

    async function searchDirectory(forceRestore = false) {{
        var q = document.getElementById('dir_q').value.trim();
        
        if (!forceRestore && q === lastQ && currentCat === lastCat && currentMode === lastMode && dirOffset === lastOffset) {{ return; }}
        
        lastQ = q; lastCat = currentCat; lastMode = currentMode; lastOffset = dirOffset;
        
        sessionStorage.setItem('ff_dir_state', '1');
        sessionStorage.setItem('ff_dir_q', q);
        sessionStorage.setItem('ff_dir_cat', currentCat);
        sessionStorage.setItem('ff_dir_mode', currentMode);
        sessionStorage.setItem('ff_dir_off', dirOffset);
        sessionStorage.setItem('ff_dir_page', dirPage);

        var myReq = ++dirReqId;
        var grid = document.getElementById('dir_grid_container');
        var row = document.getElementById('dirSearchRow');
        var loadTimer = setTimeout(function() {{
            if (myReq !== dirReqId) return;
            if (row) row.classList.add('loading');
        }}, 150);
        
        try {{
            var res = await fetch('/api/directory/search?q=' + encodeURIComponent(q) + '&cat=' + currentCat + '&mode=' + currentMode + '&offset=' + dirOffset);
            if (myReq !== dirReqId) {{ clearTimeout(loadTimer); if (row) row.classList.remove('loading'); return; }}
            clearTimeout(loadTimer);
            if (row) row.classList.remove('loading');
            if (!res.ok) throw new Error("HTTP " + res.status);
            var data = await res.json();
            if (myReq !== dirReqId) return;
            grid.innerHTML = data.html;
            // Stagger entrance animation
            staggerCards(grid);
            hasNext = data.has_next;
            
            if(currentMode === 'text') {{
                grid.style.display = 'flex'; grid.style.flexDirection = 'column'; grid.style.gap = '10px';
            }} else {{
                grid.style.display = 'grid'; grid.style.gap = '';
            }}
            updatePgUI();
        }} catch(e) {{ clearTimeout(loadTimer); if (row) row.classList.remove('loading'); grid.innerHTML = '<div style="grid-column:1/-1; text-align:center; color:var(--accent); font-weight:bold;">Search Error!</div>'; }}
    }}
    
    function updatePgUI() {{
        var box = document.getElementById('dir_pg_box');
        if (dirOffset === 0 && !hasNext) {{ box.style.display = 'none'; }} else {{ box.style.display = 'flex'; }}
        document.getElementById('dir_pBtn').disabled = (dirOffset === 0);
        document.getElementById('dir_nBtn').disabled = !hasNext;
        document.getElementById('dir_pgInfo').innerText = 'Page ' + dirPage;
    }}
    
    function resetDir() {{ dirOffset = 0; dirPage = 1; }}
    function nextDir() {{ if(hasNext) {{ dirOffset += dirLimit; dirPage++; searchDirectory(); window.scrollTo(0, 50); }} }}
    function prevDir() {{ if(dirOffset > 0) {{ dirOffset = Math.max(0, dirOffset - dirLimit); dirPage--; searchDirectory(); window.scrollTo(0, 50); }} }}
    document.getElementById('dir_q').addEventListener('keydown', function(e) {{ if(e.key === 'Enter') {{ clearTimeout(dirLiveTimer); resetDir(); searchDirectory(); }} }});
    var dirLiveTimer;
    document.getElementById('dir_q').addEventListener('input', function() {{
        clearTimeout(dirLiveTimer);
        dirLiveTimer = setTimeout(function() {{ resetDir(); searchDirectory(); }}, 350);
    }});
    </script>
    '''

    page_body = f'''<div class="main" style="padding-top:20px; max-width:1100px; margin:0 auto; padding-left:20px; padding-right:20px;">{search_ui}{initial_grid}{js_logic}</div>'''
    return build_page("Directory Catalog - Fast Finder", page_body, "", "actors", role)

# ─────────────────────────────────────────────────────────
# 🔍 API: DIRECTORY UNIVERSAL SEARCH (WITH PAGINATION)
# ─────────────────────────────────────────────────────────
@actor_routes.get('/api/directory/search')
async def api_directory_search(req):
    role, _ = await get_auth(req)
    if not role: return web.json_response({"html": ""}, dumps=fast_json)
    
    q = req.query.get("q", "").strip()
    cat = req.query.get("cat", "all")
    mode = req.query.get("mode", DEFAULT_CATALOG_MODE)
    try: offset = int(req.query.get("offset", 0))
    except: offset = 0
    lim = 20
    
    query = {}
    if cat != "all": query["category"] = cat
    if q: 
        safe_q = re.escape(q)
        query["name"] = {"$regex": safe_q, "$options": "i"}
        
    try:
        docs = await actors.find(query).sort("created_at", -1).skip(offset).limit(lim + 1).to_list(length=lim + 1)
    except Exception:
        docs = []
    
    has_next = len(docs) > lim
    docs = docs[:lim]
    
    if not docs:
        return web.json_response({"html": '<div style="grid-column:1/-1; color:var(--muted); text-align:center; padding:60px 20px;">📇 No profiles matching your filters found.</div>', "has_next": False}, dumps=fast_json)
        
    html_out = ""
    if mode == "text":
        for a in docs:
            c = a.get("category", "actor")
            i = "🎭" if c == "actor" else "📱" if c == "app" else "🌐"
            html_out += f'''<div class="act-text-card" style="background:var(--card); border:1px solid var(--border); padding:15px; border-radius:8px; display:flex; justify-content:space-between; align-items:center; cursor:pointer; transition:0.2s;" onclick="window.location.href=\'/actor/{str(a["_id"])}\'" onmouseover="this.style.borderColor='var(--accent)'" onmouseout="this.style.borderColor='var(--border)'"><div style="font-weight:800; color:var(--text); font-size:14px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:65%;">{html.escape(a.get("name",""))}</div><div style="background:var(--bg3); padding:4px 10px; border-radius:6px; font-size:11px; font-weight:800; color:var(--muted); white-space:nowrap; border:1px solid var(--border);">{i} {c.capitalize()}</div></div>'''
    else:
        for a in docs:
            c = a.get("category", "actor")
            i = "🎭" if c == "actor" else "📱" if c == "app" else "🌐"
            v = a.get("photo_revision") or int(a.get("photo_updated_at") or a.get("created_at") or 0)
            html_out += f'''<div class="act-card card-enter" onclick="window.location.href=\'/actor/{str(a["_id"])}\'">\n            <div class="poster-wrap" style="position:relative; padding-top:135%; background:var(--bg3); overflow:hidden;">\n                <img src="/api/actor/photo?id={str(a["_id"])}&v={v}" class="act-poster" loading="lazy">\n                <div style="position:absolute; top:8px; left:8px; background:rgba(229,9,20,0.9); color:#fff; font-size:10px; padding:4px 8px; border-radius:4px; font-weight:800; backdrop-filter:blur(4px); z-index:2; text-transform:uppercase; box-shadow:0 2px 10px rgba(0,0,0,0.5);">{i} {c.capitalize()}</div>\n                <div style="position:absolute; bottom:0; left:0; right:0; background:linear-gradient(to top, rgba(0,0,0,0.95) 0%, rgba(0,0,0,0.7) 40%, transparent 100%); padding:30px 12px 12px 12px; z-index:2; text-align:center;">\n                    <div style="font-size:14.5px; font-weight:900; color:#fff; text-overflow:ellipsis; overflow:hidden; white-space:nowrap; text-shadow:0 2px 6px rgba(0,0,0,0.9); letter-spacing:0.5px;">{html.escape(a.get("name", ""))}</div>\n                </div>\n            </div>\n            <div class="card-body">\n                <div style="font-size:14px; font-weight:800; color:var(--text); text-overflow:ellipsis; overflow:hidden; white-space:nowrap;">{html.escape(a.get("name", ""))}</div>\n                <div style="font-size:11px; color:var(--muted); font-weight:700; margin-top:4px;">{html.escape(c.capitalize())}</div>\n            </div>\n        </div>'''
            
    return web.json_response({"html": html_out, "has_next": has_next}, dumps=fast_json)


# ─────────────────────────────────────────────────────────
# 🧩 SHARED PROFILE FORM (Create + Edit दोनों इसी से बनते हैं)
#    नया फ़ील्ड जोड़ना हो तो सिर्फ यहाँ जोड़ें — दोनों फॉर्म में अपने-आप आ जाएगा।
# ─────────────────────────────────────────────────────────
def _clean_link(v):
    """Accept web links only, including scheme-less domains; never truncate URLs."""
    if not isinstance(v, str):
        return ""
    v = v.strip()
    if not v or len(v) > 8192 or "\\" in v or re.search(r"[\s\x00-\x1f\x7f]", v):
        return ""
    if not re.match(r"^https?://", v, re.I):
        # Permit example.com:8080 but reject javascript:, data:, ftp:, etc.
        if re.match(r"^[a-z][a-z0-9+.\-]*:", v, re.I) and not re.match(r"^[^/:]+:\d+(?:[/?#]|$)", v):
            return ""
        v = "https://" + v
    try:
        parsed = urlsplit(v)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            return ""
        _ = parsed.port  # Reject malformed ports.
    except ValueError:
        return ""
    return v


_LEGACY_LINK_LABELS = {"instagram": "Instagram", "youtube": "YouTube", "twitter": "Twitter / X"}


def _profile_links(actor):
    """Read the new ordered links, or legacy social links without discarding them."""
    saved = actor.get("profile_links")
    if isinstance(saved, list):
        candidates = saved
    else:
        legacy = actor.get("social_links") or {}
        candidates = [{"label": _LEGACY_LINK_LABELS.get(str(k).lower(), str(k)), "url": v}
                      for k, v in legacy.items()] if isinstance(legacy, dict) else []
    result = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        url = _clean_link(item.get("url"))
        if url:
            label = str(item.get("label") or "").strip() or urlsplit(url).hostname
            result.append({"label": label, "url": url})
    return result


def _parse_profile_links(labels, urls):
    """Validate all rows before writing; preserve ordering and duplicate URLs."""
    if len(labels) != len(urls):
        raise ValueError("Each link must have a matching name and URL.")
    links = []
    for label, raw in zip(labels, urls):
        if not isinstance(label, str) or not isinstance(raw, str):
            raise ValueError("Invalid link fields.")
        label, raw = label.strip(), raw.strip()
        if not label and not raw:
            continue
        if len(label) > 200:
            raise ValueError("Link names must be at most 200 characters.")
        url = _clean_link(raw)
        if not url:
            raise ValueError("Enter a valid http or https URL for each link.")
        links.append({"label": label or urlsplit(url).hostname, "url": url})
    return links


ACTOR_FORM_CSS = '''<style>
.profile-studio{max-width:880px;margin:0 auto;padding:30px 20px 60px}
.profile-studio-head{display:flex;align-items:flex-start;gap:16px;margin-bottom:22px}
.profile-back,.profile-cancel{color:var(--text);text-decoration:none;border:1px solid var(--border);background:var(--bg3);border-radius:9px;padding:10px 14px;font-size:13px;font-weight:700;white-space:nowrap;cursor:pointer}
.profile-studio-kicker,.profile-section-kicker{font-size:10px;letter-spacing:1.3px;text-transform:uppercase;color:var(--accent);font-weight:900}
.profile-studio-head h1{font-size:26px;line-height:1.2;margin:5px 0}.profile-studio-head p,.profile-help{font-size:12px;line-height:1.55;color:var(--muted)}
.profile-section{background:var(--bg2);border:1px solid var(--border);border-radius:14px;padding:20px;margin-bottom:14px}
.profile-section-head{margin-bottom:16px}.profile-section-head h2{font-size:16px;margin:5px 0}.profile-section-head p{font-size:12px;line-height:1.5;color:var(--muted)}
.profile-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.profile-field{display:flex;flex-direction:column;gap:7px;min-width:0;color:var(--text);font-size:12px;font-weight:800}
.profile-field.full{grid-column:1/-1}.profile-field .em-input{margin:0;padding:12px;background:var(--bg);font-family:inherit;font-weight:500;line-height:1.4}
.profile-field textarea{min-height:110px;resize:vertical}.profile-field small{font-weight:500;color:var(--muted);line-height:1.4}
.profile-links{display:flex;flex-direction:column;gap:10px}.profile-link-row{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,2fr) auto;gap:10px;align-items:end;padding:12px;background:var(--bg);border:1px solid var(--border);border-radius:10px}
.profile-link-row .em-input{background:var(--bg2)}.profile-link-remove,.profile-link-add{border:1px solid var(--border);border-radius:8px;background:var(--bg3);color:var(--text);padding:11px 13px;font-family:inherit;font-size:12px;font-weight:700;cursor:pointer}.profile-link-add{margin-top:12px}.profile-link-remove:hover,.profile-link-add:hover{border-color:var(--accent)}
.profile-media{display:flex;gap:18px;align-items:center}.profile-photo{width:100px;aspect-ratio:3/4;flex:none;border:1px solid var(--border);border-radius:10px;background:var(--bg3);display:grid;place-items:center;overflow:hidden;color:var(--muted);font-size:27px}
.profile-photo img{width:100%;height:100%;object-fit:cover}.profile-photo img[hidden]{display:none}.profile-photo img:not([hidden])+span{display:none}
.profile-media-copy{flex:1;min-width:0}.profile-file{display:block;max-width:100%;margin:10px 0;color:var(--muted);font:inherit;font-size:12px}.profile-file::file-selector-button{border:1px solid var(--border);background:var(--bg3);color:var(--text);padding:9px 12px;border-radius:8px;font:inherit;font-weight:700;cursor:pointer;margin-right:10px}
.profile-form-actions{display:flex;gap:10px;align-items:center;justify-content:flex-end;margin-top:18px}.profile-form-actions .em-save-btn{width:auto;min-width:170px}
.profile-modal-card{max-width:720px!important;max-height:calc(100dvh - 30px);overflow:auto;padding:22px!important}.profile-modal-card .profile-section{background:var(--card);padding:16px}.profile-modal-card .profile-section:last-of-type{margin-bottom:0}
.profile-modal-card .em-title{padding-right:35px;margin-bottom:5px}.profile-modal-card .profile-help{margin-bottom:16px}
@media(max-width:600px){.profile-studio{padding:20px 14px 50px}.profile-studio-head{gap:10px}.profile-studio-head h1{font-size:22px}.profile-section{padding:16px}.profile-fields{grid-template-columns:1fr}.profile-field.full{grid-column:auto}.profile-photo{width:78px}.profile-modal-card{padding:16px!important}.profile-form-actions .em-save-btn{flex:1;min-width:0}}
@media(max-width:600px){.profile-link-row{grid-template-columns:1fr}.profile-link-remove{justify-self:start}}
@media(hover:none){.gallery-del-btn{opacity:1!important}}
</style>'''

PROFILE_FORM_JS = r'''<script>
(function(){
    document.querySelectorAll('form[data-profile-form]').forEach(function(form){
        var button=form.querySelector('button[type=submit]'),notice=form.querySelector('.profile-form-error'),label=button.textContent;
        var modal=form.closest('#actorEditModal'),avatar=modal&&modal.querySelector('.profile-file');
        var list=form.querySelector('[data-profile-links]'),add=form.querySelector('[data-link-add]');
        if(list&&add){
            add.addEventListener('click',function(){
                var row=document.createElement('div');row.className='profile-link-row';
                row.innerHTML='<label class="profile-field">Name <span>(optional)</span><input class="em-input" name="link_label" maxlength="200" placeholder="Website, Instagram, shop…"></label><label class="profile-field">URL<input class="em-input" name="link_url" inputmode="url" placeholder="https://example.com"></label><button class="profile-link-remove" type="button" data-link-remove>Remove</button>';
                list.appendChild(row);row.querySelector('[name=link_url]').focus();
            });
            list.addEventListener('click',function(event){var remove=event.target.closest('[data-link-remove]');if(remove)remove.closest('.profile-link-row').remove();});
        }
        form.addEventListener('submit',async function(event){
            event.preventDefault();if(button.disabled)return;form.dataset.saving='true';button.disabled=true;button.textContent='Saving…';notice.hidden=true;if(avatar)avatar.disabled=true;
            try{
                var response=await fetch(form.action,{method:'POST',body:new FormData(form),headers:{'Accept':'application/json'}});
                var data=await response.json().catch(function(){return {};});
                if(!response.ok||!data.success)throw new Error(data.error||'Could not confirm the save. Please retry.');
                if(typeof data.redirect!=='string'||data.redirect[0]!=='/'||data.redirect[1]==='/')throw new Error('Saved, but could not open the result.');
                window.location.assign(data.redirect);return;
            }catch(error){form.dataset.saving='false';notice.textContent=error.message||'Could not confirm the save. Check your connection before retrying.';notice.hidden=false;notice.scrollIntoView({block:'nearest'});button.disabled=false;button.textContent=label;if(avatar)avatar.disabled=false;}
        });
        window.addEventListener('pageshow',function(){form.dataset.saving='false';button.disabled=false;button.textContent=label;if(avatar)avatar.disabled=false;});
    });
})();
</script>'''


def _actor_result(req, destination, error=None, status=400):
    if 'application/json' in req.headers.get('Accept', ''):
        return web.json_response({'error': error} if error else {'success': True, 'redirect': destination},
                                 status=status if error else 200, dumps=fast_json)
    if error:
        return web.HTTPFound(destination + ('&' if '?' in destination else '?') + urlencode({'err': error}))
    return web.HTTPFound(destination)


def actor_form_fields(name="", category="actor", bio="", tags="", links=None):
    """Shared, escaped fields keep create and edit forms in sync."""
    links = links or []
    esc = lambda value: html.escape(str(value or ""), quote=True)

    def opt(val, label):
        return f'<option value="{val}"{" selected" if category == val else ""}>{label}</option>'

    link_rows = ''.join(
        '<div class="profile-link-row"><label class="profile-field">Name <span>(optional)</span>'
        f'<input class="em-input" name="link_label" maxlength="200" value="{esc(link.get("label"))}" placeholder="Website, Instagram, shop…"></label>'
        '<label class="profile-field">URL'
        f'<input class="em-input" name="link_url" inputmode="url" value="{esc(link.get("url"))}" placeholder="https://example.com"></label>'
        '<button class="profile-link-remove" type="button" data-link-remove>Remove</button></div>'
        for link in links
    )
    legacy_category = f'<option value="{esc(category)}" selected>{esc(category)}</option>' if category and category not in ('actor', 'app', 'website') else ''
    return (
        '<section class="profile-section"><div class="profile-section-head"><div class="profile-section-kicker">01 · Identity</div><h2>Profile details</h2><p>Tell visitors who or what this profile represents.</p></div>'
        '<div class="profile-fields">'
        f'<label class="profile-field">Display name<input type="text" name="name" value="{esc(name)}" placeholder="Name of actor, app or website" class="em-input" required></label>'
        '<label class="profile-field">Category<select name="category" class="em-input" required>'
        + legacy_category + opt("actor", "🎭 Actor") + opt("app", "📱 App") + opt("website", "🌐 Website") + '</select></label>'
        f'<label class="profile-field full">Biography<textarea name="bio" placeholder="Add a short introduction..." class="em-input" required>{esc(bio)}</textarea></label>'
        f'<label class="profile-field full">Search tags<input type="text" name="tags" value="{esc(tags)}" placeholder="e.g. Actor name, Alias, Genre" class="em-input"><small>Separate tags with commas to help match linked videos.</small></label>'
        '</div></section>'
        '<section class="profile-section"><div class="profile-section-head"><div class="profile-section-kicker">02 · Optional</div><h2>Links</h2><p>Add any websites or social profiles. Add as many as you need.</p></div>'
        '<input type="hidden" name="links_present" value="1">'
        f'<div class="profile-links" data-profile-links>{link_rows}</div>'
        '<button class="profile-link-add" type="button" data-link-add>+ Add link</button></section>'
    )


# ─────────────────────────────────────────────────────────
# 🛠️ ADMIN ROUTE: CREATE PROFILE PAGE
# ─────────────────────────────────────────────────────────
@actor_routes.get('/admin/create_actor')
async def create_actor_page(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.HTTPFound('/dashboard')
    err, msg = html.escape(req.query.get('err', '')), html.escape(req.query.get('msg', ''))
    notices = (f'<div class="err-box">{err}</div>' if err else '') + (f'<div class="success-box">{msg}</div>' if msg else '')
    content = ACTOR_FORM_CSS + f'''
    <main class="profile-studio">
      <header class="profile-studio-head"><a class="profile-back" href="/actors">← Profiles</a><div><div class="profile-studio-kicker">Profile studio</div><h1>Create a profile</h1><p>Make a home for an actor, app or website.</p></div></header>
      {notices}
      <form action="/api/create_actor" method="post" enctype="multipart/form-data" data-profile-form>
        <div class="err-box profile-form-error" role="alert" hidden></div>
        <section class="profile-section"><div class="profile-section-head"><div class="profile-section-kicker">Profile image</div><h2>Choose a portrait or icon</h2><p>This image appears in the directory and at the top of the profile.</p></div>
          <div class="profile-media"><div class="profile-photo"><img id="newProfilePreview" alt="Selected profile image" hidden><span aria-hidden="true">♙</span></div>
          <div class="profile-media-copy"><label class="profile-field">Profile photo <input id="newProfilePhoto" class="profile-file" type="file" name="photo" accept="image/*" required></label><div class="profile-help">Select an image from your device. A portrait works best.</div></div></div>
        </section>
        {actor_form_fields()}
        <div class="profile-form-actions"><a class="profile-cancel" href="/actors">Cancel</a><button class="em-save-btn" type="submit">Create profile</button></div>
      </form>
    </main>
    <script>document.getElementById('newProfilePhoto').addEventListener('change',function(){{var img=document.getElementById('newProfilePreview');if(img.dataset.objectUrl)URL.revokeObjectURL(img.dataset.objectUrl);if(this.files&&this.files[0]){{img.dataset.objectUrl=URL.createObjectURL(this.files[0]);img.src=img.dataset.objectUrl;img.hidden=false;}}else{{img.hidden=true;img.removeAttribute('src');}}}});</script>'''
    return build_page("Create New Profile", content + PROFILE_FORM_JS, "", "actors", role)

@actor_routes.post('/api/create_actor')
async def api_create_actor(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.json_response({"error": "Unauthorized"}, status=403, dumps=fast_json)
    try:
        reader = await req.multipart()
        name, bio, tags_raw, image_bytes, category = None, None, "", None, "actor"
        insta, yt, twitter = "", "", ""
        links_present, labels, urls = False, [], []
        while True:
            part = await reader.next()
            if part is None: break
            if part.name == 'name': name = (await part.read()).decode().strip()
            elif part.name == 'bio': bio = (await part.read()).decode().strip()
            elif part.name == 'tags': tags_raw = (await part.read()).decode().strip()
            elif part.name == 'category': category = (await part.read()).decode().strip()
            elif part.name == 'insta': insta = _clean_link((await part.read()).decode())
            elif part.name == 'yt': yt = _clean_link((await part.read()).decode())
            elif part.name == 'twitter': twitter = _clean_link((await part.read()).decode())
            elif part.name == 'links_present': links_present = True
            elif part.name == 'link_label': labels.append((await part.read()).decode())
            elif part.name == 'link_url': urls.append((await part.read()).decode())
            elif part.name == 'photo': image_bytes = await part.read()
            
        if not name or not bio or not image_bytes:
            return _actor_result(req, '/admin/create_actor', 'Name, biography and profile photo are required.')
        try:
            links = _parse_profile_links(labels, urls) if links_present else None
        except ValueError as exc:
            return _actor_result(req, '/admin/create_actor', str(exc))

        with io.BytesIO(image_bytes) as img_buffer:
            img_buffer.name = f"{name.replace(' ', '_')}.jpg"
            msg = await temp.BOT.send_photo(chat_id=ACTOR_STORAGE_CHANNEL, photo=img_buffer)
        if not msg or not msg.photo:
            return _actor_result(req, '/admin/create_actor', 'Profile photo upload failed. Please retry.', 500)
        
        tg_photo_id = msg.photo.sizes[-1].file_id if hasattr(msg.photo, "sizes") and msg.photo.sizes else msg.photo.file_id
        now_ts = int(time.time())
        profile = {"name": name, "bio": bio, "category": category, "tags": [t.strip() for t in tags_raw.split(",") if t.strip()], "photo_url": f"TG_ID:{tg_photo_id}", "is_actor_permanent": True, "photo_updated_at": now_ts, "photo_revision": uuid.uuid4().hex, "social_links": {"instagram": insta, "youtube": yt, "twitter": twitter}, "gallery": [], "is_gallery_permanent": True, "created_at": now_ts}
        if links is not None:
            profile["profile_links"] = links
        await actors.insert_one(profile)
        return _actor_result(req, '/actors?msg=Profile+created+successfully!')
    except Exception as e:
        return _actor_result(req, '/admin/create_actor', str(e) or 'Could not create the profile.', 500)


# ─────────────────────────────────────────────────────────
# 🖼️ PHOTO ENGINE (With Cache Control)
# ─────────────────────────────────────────────────────────
@actor_routes.get('/api/actor/photo')
async def get_actor_photo(req):
    actor_id, img_index = req.query.get("id"), req.query.get("gallery_idx")
    if not actor_id: return web.Response(status=400)
    try:
        doc = await actors.find_one({"_id": ObjectId(actor_id)})
        if not doc: return web.Response(status=404)
        if img_index is not None:
            raw_url = doc.get("gallery", [])[int(img_index)]
            headers = {"Cache-Control": "public, max-age=31536000, immutable", "Content-Disposition": 'inline; filename="photo.jpg"'}
        else:
            raw_url = doc.get("photo_url")
            headers = {"Cache-Control": "public, max-age=31536000, immutable", "Content-Disposition": 'inline; filename="avatar.jpg"'}
            
        if not raw_url or not raw_url.startswith("TG_ID:"): return web.Response(status=404)
        file_data = await temp.BOT.download_media(raw_url.replace("TG_ID:", ""), in_memory=True)
        if not file_data: return web.Response(status=404)
        
        body_bytes = file_data.getvalue()
        file_data.close()
        del file_data
        return web.Response(body=body_bytes, content_type="image/jpeg", headers=headers)
    except Exception: return web.Response(status=500)


ACTOR_PROFILE_CSS = '''<style>
.actor-page{max-width:1100px;margin:0 auto;padding:26px 20px 64px}.actor-back{display:inline-flex;align-items:center;gap:8px;color:var(--muted);text-decoration:none;font-size:12px;font-weight:700;margin-bottom:18px}.actor-back:hover{color:var(--text)}
.actor-header-wrap{position:relative;overflow:hidden;display:flex;flex-direction:row;align-items:stretch;gap:28px;padding:26px;border-radius:18px;margin-bottom:28px;background:linear-gradient(125deg,rgba(229,9,20,.12),transparent 45%),var(--card)}
.avatar-box-master{width:260px;max-width:none;height:auto;aspect-ratio:3/4;border-radius:12px;box-shadow:0 12px 30px rgba(0,0,0,.24)}.avatar-box-master img{display:block;width:100%;height:100%;object-fit:cover}
.actor-identity{flex:1;min-width:0;display:flex;flex-direction:column;justify-content:center;align-items:flex-start}.actor-eyebrow{font-size:10px;font-weight:900;letter-spacing:1.5px;text-transform:uppercase;color:var(--accent);margin-bottom:8px}.actor-identity h1{font-size:clamp(25px,3vw,38px);line-height:1.12;letter-spacing:-.7px;overflow-wrap:anywhere}.actor-chips,.actor-links,.actor-actions{display:flex;flex-wrap:wrap;gap:7px;max-width:100%}.actor-chips{margin-top:14px}.actor-category,.actor-tag{padding:6px 10px;border-radius:7px;font-size:10px;font-weight:800;line-height:1.2;overflow-wrap:anywhere}.actor-category{background:var(--accent);color:#fff;letter-spacing:.4px}.actor-tag{border:1px solid var(--border);background:var(--bg3);color:var(--muted)}
.actor-links{margin-top:17px}.actor-link{color:var(--text);background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:8px 11px;text-decoration:none;font-size:12px;font-weight:700;overflow-wrap:anywhere}.actor-link:hover,.actor-action-edit:hover{border-color:var(--accent)}.actor-actions{margin-top:20px}.actor-actions button{font-family:inherit;font-size:12px;font-weight:700;border-radius:8px;padding:10px 13px;cursor:pointer}.actor-action-edit{background:var(--bg4);color:var(--text);border:1px solid var(--border)}.actor-action-delete{background:transparent;color:var(--muted);border:1px solid var(--border)}.actor-action-delete:hover{color:var(--accent);border-color:var(--accent)}
.actor-page .actor-tab-bar{gap:4px;margin-bottom:20px;border-bottom:1px solid var(--border);overflow-x:auto}.actor-page .actor-tab{padding:13px 18px;white-space:nowrap;font-size:13px}.actor-page .actor-tab.active::after{bottom:-1px}
.actor-bio{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:24px 26px}.actor-panel-kicker{color:var(--accent);font-size:10px;font-weight:900;letter-spacing:1.3px;text-transform:uppercase}.actor-bio h2{font-size:18px;margin:8px 0 12px}.actor-bio-copy{line-height:1.8;color:var(--text);font-size:14px;white-space:pre-line;overflow-wrap:anywhere}
.actor-gallery-upload{display:flex;align-items:center;justify-content:space-between;gap:16px;background:var(--card);border:1px solid var(--border);border-radius:14px;padding:18px 20px;margin-bottom:16px}.actor-gallery-upload strong{font-size:14px}.actor-gallery-upload p,.actor-gallery-empty p{font-size:12px;color:var(--muted);margin-top:5px}.actor-gallery-choose{display:inline-block;position:relative;overflow:hidden;padding:10px 15px;background:var(--accent);color:#fff;border-radius:8px;font-size:12px;font-weight:700;cursor:pointer;white-space:nowrap}.actor-gallery-choose input{position:absolute;inset:0;width:100%;height:100%;opacity:0;cursor:pointer}.actor-gallery-choose:focus-within{outline:2px solid var(--accent);outline-offset:3px}.actor-gallery-empty{text-align:center;background:var(--card);border:1px dashed var(--border);border-radius:14px;padding:38px 20px}.actor-gallery-empty strong{font-size:14px}
.profile-modal-card{border-radius:18px!important;box-shadow:0 24px 70px rgba(0,0,0,.5)}.profile-modal-card .profile-section{border-radius:12px}.profile-field .em-input:focus{box-shadow:0 0 0 3px rgba(229,9,20,.12)}.profile-link-add:hover,.profile-cancel:hover{border-color:var(--accent)}
@media(max-width:600px){.actor-page{padding:20px 14px 50px}.actor-header-wrap{flex-direction:column;align-items:stretch;gap:18px;padding:17px;margin-bottom:20px}.avatar-box-master{width:100%;max-width:260px;align-self:center;aspect-ratio:3/4;border-radius:10px}.actor-identity{justify-content:flex-start}.actor-eyebrow{font-size:9px}.actor-identity h1{font-size:23px;letter-spacing:-.3px}.actor-chips{margin-top:10px}.actor-links{margin-top:12px}.actor-actions{margin-top:14px}.actor-page .actor-tab{padding:12px 13px;font-size:12px}.actor-bio{padding:20px}.actor-gallery-upload{align-items:flex-start;flex-direction:column}.actor-gallery-upload form,.actor-gallery-choose{width:100%;text-align:center}}
</style>'''


# ─────────────────────────────────────────────────────────
# 🌐 PROFILE VIEW: INDIVIDUAL DISPLAY & MEDIA
# ─────────────────────────────────────────────────────────
@actor_routes.get('/actor/{id}')
async def actor_profile_display(req):
    role, tg_id = await get_auth(req)
    if not role: return web.HTTPFound('/login')
    if not await require_active_plan(role, tg_id): return web.HTTPFound('/premium_expired')
    try:
        actor_id = req.match_info['id']
        actor = await actors.find_one({"_id": ObjectId(actor_id)})
        if not actor: return web.Response(text="Profile Not Found", status=404)
    except: return web.Response(text="Invalid ID", status=400)
        
    actor_name, tags_list, category = actor["name"], actor.get("tags", []), actor.get("category", "actor")
    links, gallery_list = _profile_links(actor), actor.get("gallery", [])
    
    cat_emoji = "🎭" if category == "actor" else "📱" if category == "app" else "🌐"
    cat_badge = f'<span class="actor-category">{cat_emoji} {html.escape(str(category).upper())}</span>'
    t_html = "".join(f'<span class="actor-tag">#{html.escape(t)}</span>' for t in tags_list)
    tags_chips_html = f'<div class="actor-chips">{cat_badge}{t_html}</div>'
    s_html = "".join(
        f'<a class="actor-link" href="{html.escape(link["url"], quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(link["label"])}</a>'
        for link in links
    )
    social_html = f'<div class="actor-links" aria-label="Profile links">{s_html}</div>' if s_html else ''

    gallery_grid_html = f'''<div class="actor-gallery-upload"><div><strong>Add to the gallery</strong><p>Choose one or more photos from your device.</p></div><form action="/api/actor/gallery_upload" method="post" enctype="multipart/form-data"><input type="hidden" name="actor_id" value="{actor_id}"><label class="actor-gallery-choose">Add images<input type="file" name="gallery_img" accept="image/*" multiple onchange="this.form.submit()"></label></form></div>''' if role == 'admin' else ""
    if not gallery_list:
        gallery_grid_html += '<div class="actor-gallery-empty"><strong>No photos yet</strong><p>Gallery images will appear here.</p></div>'
    else:
        # ✅ CACHE FIX: /api/actor/photo 1-साल immutable cache भेजता है — बिना version
        # param के delete/upload के बाद browser पुरानी image (पुराने gallery_idx URL से)
        # दिखाता रहता था, जिससे लगता था कि photo delete ही नहीं हुई। अब &v={gallery_v}
        # हर बदलाव पर URL बदल देता है।
        gallery_v = actor.get("gallery_revision") or int(actor.get("gallery_updated_at") or actor.get("photo_updated_at") or actor.get("created_at") or 0)
        g_items = "".join([f'<div class="gallery-item-wrap" onclick="openLightbox(\'/api/actor/photo?id={actor_id}&gallery_idx={i}&v={gallery_v}\')"><img src="/api/actor/photo?id={actor_id}&gallery_idx={i}&v={gallery_v}" class="gallery-item" loading="lazy">' + (f'<button class="gallery-del-btn" onclick="deleteGalleryImage(\'{actor_id}\', {i}, event)">🗑️ Delete</button>' if role=='admin' else "") + '</div>' for i in range(len(gallery_list))])
        gallery_grid_html += f'<div class="gallery-grid">{g_items}</div>'

    admin_actions_html = f'''<div class="actor-actions"><button type="button" class="actor-action-edit" onclick="openActorEditModal()">✏️ Edit Profile</button><button type="button" class="actor-action-delete" onclick="deleteActorProfile('{actor_id}')">Delete Profile</button></div>''' if role == 'admin' else ""

    tags_json_payload = html.escape(fast_json(tags_list))
    safe_bio = html.escape(actor.get("bio", ""))
    photo_v = actor.get("photo_revision") or int(actor.get("photo_updated_at") or actor.get("created_at") or 0)
    profile_edit_modal = f'''
    <div class="edit-modal" id="actorEditModal" role="dialog" aria-modal="true" aria-labelledby="actorEditTitle" onclick="if(event.target===this)closeActorEditModal()">
      <div class="em-card profile-modal-card"><button class="em-close" type="button" aria-label="Close" onclick="closeActorEditModal()">&#10005;</button>
        <div class="profile-studio-kicker">Profile studio</div><h2 class="em-title" id="actorEditTitle">Edit profile</h2><p class="profile-help">Update the details below. Your photo can be changed here too.</p>
        <div class="profile-section"><div class="profile-media"><div class="profile-photo"><img id="actorEditPreview" src="/api/actor/photo?id={actor_id}&amp;v={html.escape(str(photo_v), quote=True)}" alt="Current profile photo"></div>
          <div class="profile-media-copy"><label class="profile-field">Profile photo<input class="profile-file" type="file" accept="image/*" onchange="updateActorAvatar('{actor_id}',this)"></label><div class="profile-help">The photo is updated immediately when selected.</div></div></div></div>
        <form action="/api/actor/update_profile" method="post" data-profile-form><input type="hidden" name="actor_id" value="{actor_id}">
          <div class="err-box profile-form-error" role="alert" hidden></div>
          {actor_form_fields(actor_name, category, actor.get("bio", ""), ", ".join(tags_list), links)}
          <div class="profile-form-actions"><button class="profile-cancel" type="button" onclick="closeActorEditModal()">Cancel</button><button class="em-save-btn" type="submit">Save changes</button></div>
        </form>
      </div>
    </div>''' if role == 'admin' else ""
    
    # 🎛️ Default media mode (centralized via DEFAULT_MEDIA_MODE in web_assets.py)
    ap_mode_tg_lbl = "🖼️ Original TG Thumb"
    ap_mode_none_lbl = "⚡ Text Only (Fastest)"
    ap_mode_lbl = ap_mode_none_lbl if DEFAULT_MEDIA_MODE == "none" else ap_mode_tg_lbl
    ap_sel_tg = " selected" if DEFAULT_MEDIA_MODE == "tg" else ""
    ap_sel_none = " selected" if DEFAULT_MEDIA_MODE == "none" else ""


    # ✅ CSS MINIFIED (DUPLICATES REMOVED)
    css_js_minified = f'''<style>.actor-tab-bar{{display:flex;gap:10px;border-bottom:2px solid var(--border);margin-bottom:25px}}.actor-tab{{background:0 0;border:none;color:var(--muted);padding:12px 20px;font-size:15px;font-weight:700;cursor:pointer;transition:.2s;position:relative;font-family:inherit}}.actor-tab.active{{color:var(--text)!important}}.actor-tab.active::after{{content:'';position:absolute;bottom:-2px;left:0;right:0;height:2px;background:var(--accent)}}.actor-panel{{display:none}}.actor-panel.active{{display:block!important}}.gallery-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:14px}}@media(min-width:600px){{.gallery-grid{{grid-template-columns:repeat(auto-fill,minmax(180px,1fr))}}}}.gallery-item-wrap{{position:relative;border-radius:8px;overflow:hidden;border:1px solid var(--border);aspect-ratio:1;cursor:pointer}}.gallery-item{{width:100%;height:100%;object-fit:cover;transition:transform .2s}}.gallery-item-wrap:hover .gallery-item{{transform:scale(1.04)}}.gallery-del-btn{{position:absolute;bottom:8px;left:50%;transform:translateX(-50%);background:rgba(160,8,8,.85);border:1px solid var(--accent);color:#fff;padding:4px 10px;border-radius:4px;font-size:10px;font-weight:700;cursor:pointer;z-index:5;opacity:0;transition:opacity .15s}}.gallery-item-wrap:hover .gallery-del-btn{{opacity:1}}.lightbox{{position:fixed;inset:0;background:rgba(0,0,0,.92);backdrop-filter:blur(15px);z-index:99999;display:none;align-items:center;justify-content:center;opacity:0;transition:opacity .2s ease}}.lightbox.open{{display:flex;opacity:1}}.lightbox-img{{max-width:92%;max-height:88vh;object-fit:contain;border-radius:6px;box-shadow:0 10px 40px rgba(0,0,0,.8);transform:scale(.95);transition:transform .2s cubic-bezier(.4,0,.2,1)}}.lightbox.open .lightbox-img{{transform:scale(1)}}.lightbox-close{{position:absolute;top:20px;right:25px;background:none;border:none;color:#fff;font-size:32px;cursor:pointer;opacity:.7}}.lightbox-close:hover{{opacity:1}}.search-zone-actor{{padding:16px 0 0}}.search-row1-actor{{display:flex;align-items:center;gap:10px;margin-bottom:10px}}.search-row2-actor{{display:flex;align-items:center;justify-content:flex-start;gap:10px;margin-bottom:16px}}@media(min-width:768px){{.search-zone-actor{{display:flex;align-items:center;gap:10px;flex-wrap:nowrap;padding-bottom:16px}}.search-row1-actor{{flex:1;margin-bottom:0}}.search-row2-actor{{margin-bottom:0;flex-shrink:0}}}}.search-wrap-actor{{flex:1;min-width:0;display:flex;align-items:center;background:var(--bg3);border:1.5px solid var(--border);border-radius:12px;padding:0 6px 0 18px;gap:8px;overflow:hidden;min-height:38px}}.search-spinner-actor{{display:none;width:15px;height:15px;flex-shrink:0;border:2px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:searchSpinActor .6s linear infinite}}.search-wrap-actor.loading .search-spinner-actor{{display:inline-block}}@keyframes searchSpinActor{{to{{transform:rotate(360deg)}}}}.search-input-actor{{flex:1;min-width:0;width:100%;background:0 0;border:none;outline:none;color:var(--text);font-size:14px;font-weight:600;padding:6px 0;font-family:inherit}}.search-input-actor::placeholder{{color:var(--muted);font-weight:400}}.search-btn-actor{{flex-shrink:0;background:var(--accent);color:#fff;border:none;border-radius:12px;padding:0 20px;height:38px;font-size:14px;font-weight:700;cursor:pointer;white-space:nowrap;transition:transform .15s,background .15s}}.search-btn-actor:hover{{background:var(--accent-hover);transform:scale(1.03)}}.cdd-wrap-actor{{flex:0 1 auto;min-width:0;position:relative;user-select:none}}.cdd-btn-actor{{width:auto;background:var(--bg3);color:var(--text);border:1.5px solid var(--border);border-radius:999px;padding:8px 28px 8px 14px;font-size:11px;font-weight:700;cursor:pointer;font-family:inherit;box-sizing:border-box;display:inline-flex;align-items:center;gap:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:border-color .15s}}.cdd-btn-actor.open,.cdd-btn-actor:hover{{border-color:var(--accent)}}.cdd-arrow-actor{{position:absolute;right:12px;top:50%;transform:translateY(-50%);pointer-events:none;font-size:9px;color:var(--muted);transition:transform .2s}}.cdd-btn-actor.open+.cdd-arrow-actor{{transform:translateY(-50%) rotate(180deg)}}.cdd-menu-actor{{position:absolute;top:calc(100% + 7px);left:50%;transform:translateX(-50%);min-width:max-content;background:var(--bg2);border:1.5px solid var(--border);border-radius:16px;overflow:hidden;z-index:9999;box-shadow:0 8px 32px rgba(0,0,0,.45);display:none}}.cdd-item-actor{{display:flex;align-items:center;gap:10px;padding:11px 14px;font-size:12px;font-weight:700;color:var(--text);cursor:pointer;transition:background .12s;border-bottom:1px solid var(--border)}}.cdd-item-actor:last-child{{border-bottom:none}}.cdd-item-actor:hover{{background:var(--bg3)}}.cdd-item-actor.selected{{color:var(--accent)}}.cdd-radio-actor{{width:16px;height:16px;border-radius:50%;border:2px solid var(--border);margin-left:auto;flex-shrink:0;display:flex;align-items:center;justify-content:center}}.cdd-item-actor.selected .cdd-radio-actor{{border-color:var(--accent)}}.cdd-radio-dot-actor{{width:6px;height:6px;border-radius:50%;background:var(--accent);display:none}}.cdd-item-actor.selected .cdd-radio-dot-actor{{display:block}}.actor-header-wrap{{display:flex;gap:25px;background:var(--card);border:1px solid var(--border);padding:25px;border-radius:12px;margin-bottom:35px;flex-direction:column;align-items:center;width:100%;box-sizing:border-box}}.avatar-box-master{{width:100%;max-width:340px;height:auto;aspect-ratio:3/4;background:var(--bg3);border-radius:8px;overflow:hidden;border:1px solid var(--border);flex-shrink:0}}@media(min-width:768px){{.actor-header-wrap{{flex-direction:row;align-items:stretch}}.avatar-box-master{{width:260px;height:350px;max-width:none;aspect-ratio:auto}}}}</style>{ACTOR_PROFILE_CSS}<main class="actor-page"><a class="actor-back" href="/actors">← Back to profiles</a><div class="actor-header-wrap"><div class="avatar-box-master"><img id="actorMasterAvatarImage" src="/api/actor/photo?id={actor_id}&v={photo_v}" alt="{html.escape(actor_name, quote=True)} profile photo"></div><div class="actor-identity"><div class="actor-eyebrow">Profile</div><h1>{html.escape(actor_name)}</h1>{tags_chips_html}{social_html}{admin_actions_html}</div></div><div class="actor-tab-bar"><button class="actor-tab active" onclick="switchActorTab(event,'tab-info')">ℹ️ Info</button><button class="actor-tab" onclick="switchActorTab(event,'tab-video')">🎬 Linked Media</button><button class="actor-tab" onclick="switchActorTab(event,'tab-gallery')">🖼️ Gallery</button></div><div id="tab-info" class="actor-panel active"><section class="actor-bio"><div class="actor-panel-kicker">The story</div><h2>About</h2><div class="actor-bio-copy">{safe_bio}</div></section></div><div id="tab-video" class="actor-panel"><div class="search-zone-actor"><div class="search-row1-actor"><div class="search-wrap-actor" id="actMovieWrap"><input type="text" id="actor_movie_q" value="" placeholder="Search inside this profile..." class="search-input-actor"><span class="search-spinner-actor" id="actMovieSpinner"></span></div></div><div class="search-row2-actor"><div class="cdd-wrap-actor"><div class="cdd-btn-actor" id="cddColBtnActor" onclick="toggleActorCdd('col',event)"><span id="cddColLabelActor">📂 All Collections</span></div><span class="cdd-arrow-actor">&#9660;</span><div class="cdd-menu-actor" id="cddColMenuActor"><div class="cdd-item-actor selected" data-val="all" onclick="pickActorCol('all','📂 All Collections',this,event)">📂 All Collections<span class="cdd-radio-actor"><span class="cdd-radio-dot-actor"></span></span></div><div class="cdd-item-actor" data-val="primary" onclick="pickActorCol('primary','🟢 Primary',this,event)">🟢 Primary<span class="cdd-radio-actor"><span class="cdd-radio-dot-actor"></span></span></div><div class="cdd-item-actor" data-val="cloud" onclick="pickActorCol('cloud','🔵 Cloud',this,event)">🔵 Cloud<span class="cdd-radio-actor"><span class="cdd-radio-dot-actor"></span></span></div><div class="cdd-item-actor" data-val="archive" onclick="pickActorCol('archive','🟠 Archive',this,event)">🟠 Archive<span class="cdd-radio-actor"><span class="cdd-radio-dot-actor"></span></span></div></div></div><div class="cdd-wrap-actor"><div class="cdd-btn-actor" id="cddModeBtnActor" onclick="toggleActorCdd('mode',event)"><span id="cddModeLabelActor">{ap_mode_lbl}</span></div><span class="cdd-arrow-actor">&#9660;</span><div class="cdd-menu-actor" id="cddModeMenuActor"><div class="cdd-item-actor{ap_sel_tg}" data-val="tg" onclick="pickActorMode('tg','🖼️ Original TG Thumb',this,event)">🖼️ Original TG Thumb<span class="cdd-radio-actor"><span class="cdd-radio-dot-actor"></span></span></div><div class="cdd-item-actor{ap_sel_none}" data-val="none" onclick="pickActorMode('none','⚡ Text Only (Fastest)',this,event)">⚡ Text Only (Fastest)<span class="cdd-radio-actor"><span class="cdd-radio-dot-actor"></span></span></div></div></div></div></div><div id="actor_video_results" class="res-grid"></div><div class="pagination" id="actor_page_box" style="display:none"><button class="pg-btn" id="actor_pBtn" onclick="actorPagePrev()" disabled>Previous</button><span class="pg-info" id="actor_pgInfo">Page 1</span><button class="pg-btn" id="actor_nBtn" onclick="actorPageNext()">Next</button></div></div><div id="tab-gallery" class="actor-panel">{gallery_grid_html}</div></main><div id="actorLightboxModal" class="lightbox" onclick="closeLightbox()"><button class="lightbox-close" onclick="closeLightbox()">&times;</button><img id="lightboxTargetImg" class="lightbox-img" src="" onclick="event.stopPropagation()"></div><input type="hidden" id="actor_master_tags_payload" value="{tags_json_payload}">{profile_edit_modal}<script>var actCurPage=1,actOffset=0,actNextOffset="",actLimit={MAX_WEB_RESULTS},actCol="all",actMode="{DEFAULT_MEDIA_MODE}",actMovieReqId=0;function closeActorCdds(){{document.getElementById('cddColMenuActor').style.display='none';document.getElementById('cddColBtnActor').classList.remove('open');document.getElementById('cddModeMenuActor').style.display='none';document.getElementById('cddModeBtnActor').classList.remove('open');}}function toggleActorCdd(w,e){{if(e)e.stopPropagation();var mid=w==='col'?'cddColMenuActor':'cddModeMenuActor',bid=w==='col'?'cddColBtnActor':'cddModeBtnActor',oid=w==='col'?'cddModeMenuActor':'cddColMenuActor',obid=w==='col'?'cddModeBtnActor':'cddColBtnActor';document.getElementById(oid).style.display='none';document.getElementById(obid).classList.remove('open');var m=document.getElementById(mid),b=document.getElementById(bid);if(m.style.display==='block'){{m.style.display='none';b.classList.remove('open');}}else{{m.style.display='block';b.classList.add('open');}}}}function pickActorCol(v,l,el,e){{if(e)e.stopPropagation();actCol=v;document.getElementById('cddColLabelActor').textContent=l;document.querySelectorAll('#cddColMenuActor .cdd-item-actor').forEach(i=>i.classList.remove('selected'));el.classList.add('selected');closeActorCdds();resetActorSearchPage();triggerActorSearchAjax();}}function pickActorMode(v,l,el,e){{if(e)e.stopPropagation();actMode=v;document.getElementById('cddModeLabelActor').textContent=l;document.querySelectorAll('#cddModeMenuActor .cdd-item-actor').forEach(i=>i.classList.remove('selected'));el.classList.add('selected');closeActorCdds();resetActorSearchPage();triggerActorSearchAjax();}}document.addEventListener('click',closeActorCdds);function openLightbox(s){{document.getElementById('lightboxTargetImg').src=s;var lb=document.getElementById('actorLightboxModal');lb.style.display='flex';setTimeout(()=>lb.classList.add('open'),10);}}function closeLightbox(){{var lb=document.getElementById('actorLightboxModal');lb.classList.remove('open');setTimeout(()=>lb.style.display='none',200);}}function switchActorTab(ev,tId){{document.querySelectorAll('.actor-panel').forEach(p=>p.classList.remove('active'));document.querySelectorAll('.actor-tab').forEach(t=>t.classList.remove('active'));document.getElementById(tId).classList.add('active');ev.currentTarget.classList.add('active');if(tId==='tab-video'&&!document.getElementById('actor_video_results').innerHTML)triggerActorSearchAjax();}}function openActorEditModal(){{document.getElementById('actorEditModal').classList.add('open');}}function closeActorEditModal(){{var m=document.getElementById('actorEditModal'),f=m&&m.querySelector('form[data-profile-form]');if(f&&f.dataset.saving==='true'){{showToast('Please wait for the save to finish.');return;}}if(m)m.classList.remove('open');}}function resetActorSearchPage(){{actCurPage=1;actOffset=0;}}async function triggerActorSearchAjax(){{var q=document.getElementById('actor_movie_q').value.trim(),grid=document.getElementById('actor_video_results');var wrap=document.getElementById('actMovieWrap');var myReq=++actMovieReqId;var loadTimer=setTimeout(function(){{if(myReq!==actMovieReqId)return;if(wrap)wrap.classList.add('loading');}},150);try{{var r=await fetch('/api/actor/search?q='+encodeURIComponent(q)+'&offset='+actOffset+'&col='+actCol+'&mode='+actMode+'&id={actor_id}');if(myReq!==actMovieReqId){{clearTimeout(loadTimer);if(wrap)wrap.classList.remove('loading');return;}}clearTimeout(loadTimer);if(wrap)wrap.classList.remove('loading');var d=await r.json();if(myReq!==actMovieReqId)return;grid.className='res-grid mode-'+actMode;if(!d.results||!d.results.length){{grid.innerHTML='<div class="empty"><p>No video assets matching filters found.</p></div>';document.getElementById('actor_page_box').style.display='none';return;}}var h='';d.results.forEach(f=>{{h+=renderActorMediaCard(f,actMode,document.getElementById('editCombinedModal')!==null);}});grid.innerHTML=h;staggerCards(grid);actNextOffset=d.next_offset;document.getElementById('actor_page_box').style.display='flex';document.getElementById('actor_pBtn').disabled=(actOffset===0);document.getElementById('actor_nBtn').disabled=!actNextOffset;document.getElementById('actor_pgInfo').textContent='Page '+actCurPage;}}catch(e){{clearTimeout(loadTimer);if(myReq!==actMovieReqId)return;if(wrap)wrap.classList.remove('loading');grid.innerHTML='<div class="empty"><p>Could not load linked videos. Please retry.</p></div>';}}}}var actorAvatarInProgress=false;async function updateActorAvatar(aid,input){{var field=input,f=field&&field.files[0];if(!f)return;if(actorAvatarInProgress){{field.value='';showToast('Please wait for the current photo upload.');return;}}actorAvatarInProgress=true;var save=document.querySelector('#actorEditModal button[type=submit]'),oldLabel=save&&save.textContent;if(save){{save.disabled=true;save.textContent='Uploading photo…';}}var fd=new FormData();fd.append('actor_id',aid);fd.append('photo',f);field.disabled=true;try{{var r=await fetch('/api/actor/update_avatar',{{method:'POST',body:fd}}),d=await r.json();if(!r.ok||!d.success)throw new Error(d.error||'Upload failed');var src='/api/actor/photo?id='+encodeURIComponent(aid)+'&v='+encodeURIComponent(d.photo_revision||Date.now());document.getElementById('actorMasterAvatarImage').src=src;var preview=document.getElementById('actorEditPreview');if(preview)preview.src=src;showToast('Profile photo updated.');}}catch(e){{showToast(e.message||'Network update error','error');}}finally{{field.value='';field.disabled=false;actorAvatarInProgress=false;if(save){{save.disabled=false;save.textContent=oldLabel;}}}}}}async function deleteGalleryImage(aid,idx,e){{if(e)e.stopPropagation();if(!confirm("Delete this photo from gallery permanently?"))return;try{{var r=await fetch('/api/actor/gallery_delete',{{method:'POST',body:JSON.stringify({{actor_id:aid,index:idx}}),headers:{{'Content-Type':'application/json'}}}}),d=await r.json();if(d.success){{alert("Image removed from gallery!");window.location.reload();}}else alert(d.error||"Delete failed!");}}catch(e){{alert("Network deletion error!");}}}}async function deleteActorProfile(id){{if(!confirm("Are you sure you want to permanently delete this profile?"))return;try{{var r=await fetch('/api/actor/delete?id='+id,{{method:'POST'}}),d=await r.json();if(d.success){{alert("Profile deleted successfully!");window.location.href='/actors';}}else alert(d.error||"Deletion failed!");}}catch(e){{alert("Network communication error!");}}}}function actorPageNext(){{if(actNextOffset){{actCurPage++;actOffset=actNextOffset;triggerActorSearchAjax();window.scrollTo(0,350);}}}}function actorPagePrev(){{if(actCurPage>1){{actCurPage--;actOffset=Math.max(0,actOffset-actLimit);triggerActorSearchAjax();window.scrollTo(0,350);}}}}document.getElementById('actor_movie_q').addEventListener('keydown',function(e){{if(e.key==='Enter'){{clearTimeout(actMovieLiveTimer);resetActorSearchPage();triggerActorSearchAjax();}}}});var actMovieLiveTimer;document.getElementById('actor_movie_q').addEventListener('input',function(){{clearTimeout(actMovieLiveTimer);actMovieLiveTimer=setTimeout(function(){{resetActorSearchPage();triggerActorSearchAjax();}},350);}});</script>'''
    
    return build_page(f"{actor_name} - Directory Profile", ACTOR_FORM_CSS + css_js_minified + ACTOR_MEDIA_SCRIPT + PROFILE_FORM_JS, "", "actors", role)

# ─────────────────────────────────────────────────────────
# ⚙️ PROFILE PAGE: INTERNAL FILE SEARCH API
# ─────────────────────────────────────────────────────────
@actor_routes.get('/api/actor/search')
async def api_actor_search_handler(req):
    role, _ = await get_auth(req)
    if not role: return web.json_response({"error": "Unauthorized"}, status=403, dumps=fast_json)
    actor_id, q_custom = req.query.get("id"), req.query.get("q", "").strip()
    # नोट: `mode` query-param अब पढ़ा नहीं जाता — इस handler में thumbnail हमेशा
    # tg_thumb के तौर पर भेजा जाता है, इसलिए variable bind करना dead code था।
    off, col = req.query.get("offset", "0"), req.query.get("col", "all").lower()
    
    if not actor_id: return web.json_response({"results": []}, dumps=fast_json)
    try: off = max(0, int(off))
    except: off = 0
        
    actor = await actors.find_one({"_id": ObjectId(actor_id)})
    if not actor: return web.json_response({"results": []}, dumps=fast_json)
    
    tags_list = actor.get("tags", [])
    search_query, final_tags = (q_custom, []) if q_custom else (tags_list[0] if tags_list else "", tags_list)
    if not search_query: return web.json_response({"results": [], "next_offset": ""}, dumps=fast_json)
        
    lim = MAX_WEB_RESULTS
    all_m, next_offset = await get_actor_search_results(search_query, final_tags, max_results=lim, offset=off, collection_type=col)
    
    # Use the same thumbnail revision and file-reference logic as the dashboard.
    results_list = await _annotate_raw_groups(_build_results_list(all_m, "tg"))
        
    return web.json_response({"results": results_list, "next_offset": next_offset}, dumps=fast_json)

# ─────────────────────────────────────────────────────────
# ⚙️ PROFILE: UPDATE PROFILE DATA
# ─────────────────────────────────────────────────────────
@actor_routes.post('/api/actor/update_profile')
async def api_actor_update_profile(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.json_response({"error": "Unauthorized"}, status=403, dumps=fast_json)
    try:
        d = await req.post()
        actor_id, name, bio = d.get('actor_id'), d.get('name', '').strip(), d.get('bio', '').strip()
        category = d.get('category', 'actor').strip()
        if not actor_id or not name or not bio:
            return _actor_result(req, '/actors', 'Name and biography are required.')
        oid = ObjectId(actor_id)
        existing = await actors.find_one({"_id": oid})
        if not existing:
            return _actor_result(req, '/actors', 'Profile not found.', 404)
        updates = {"name": name, "bio": bio, "category": category,
                   "tags": [t.strip() for t in d.get('tags', '').strip().split(",") if t.strip()]}
        if 'links_present' in d:
            try:
                updates['profile_links'] = _parse_profile_links(d.getall('link_label', []), d.getall('link_url', []))
            except ValueError as exc:
                return _actor_result(req, f'/actor/{actor_id}', str(exc))
        else:
            # Old clients can still update the three original fields. Requests
            # that omit them must not erase any existing or new links.
            fields = {'insta': 'instagram', 'yt': 'youtube', 'twitter': 'twitter'}
            supplied = {key: d[field] for field, key in fields.items() if field in d}
            if supplied:
                legacy = dict(existing.get('social_links') or {})
                for key, value in supplied.items():
                    legacy[key] = _clean_link(value)
                updates['social_links'] = legacy
                if isinstance(existing.get('profile_links'), list):
                    links = _profile_links(existing)
                    for key, value in supplied.items():
                        label = _LEGACY_LINK_LABELS[key]
                        links = [link for link in links if link['label'].casefold() != label.casefold()]
                        if _clean_link(value):
                            links.append({'label': label, 'url': _clean_link(value)})
                    updates['profile_links'] = links
        result = await actors.update_one({"_id": oid}, {"$set": updates})
        if not result.matched_count:
            return _actor_result(req, '/actors', 'Profile not found.', 404)
        return _actor_result(req, f'/actor/{actor_id}?msg=Profile+updated+successfully!')
    except Exception as e:
        return _actor_result(req, '/actors', str(e) or 'Could not update the profile.', 500)

# ─────────────────────────────────────────────────────────
# ⚙️ PROFILE: UPDATE AVATAR
# ─────────────────────────────────────────────────────────
@actor_routes.post('/api/actor/update_avatar')
async def api_actor_update_avatar(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.json_response({"error": "Unauthorized"}, status=403, dumps=fast_json)
    try:
        data = await req.post()
        if not data.get("actor_id") or not data.get("photo"): return web.json_response({"success": False, "error": "Invalid assets data"}, dumps=fast_json)
            
        with io.BytesIO(data.get("photo").file.read()) as img_buffer:
            img_buffer.name = f"avatar_{data.get('actor_id')}_{int(time.time())}.jpg"
            # ✅ UPGRADE: पुराने मिक्स्ड 'BIN_CHANNEL' के बजाय पृथक 'ACTOR_STORAGE_CHANNEL' का उपयोग
            msg = await temp.BOT.send_photo(chat_id=ACTOR_STORAGE_CHANNEL, photo=img_buffer)
            
        if not msg or not msg.photo: return web.json_response({"success": False, "error": "Telegram upload failed"}, dumps=fast_json)
        tg_photo_id = msg.photo.sizes[-1].file_id if hasattr(msg.photo, "sizes") and msg.photo.sizes else msg.photo.file_id
        
        revision, updated_at = uuid.uuid4().hex, int(time.time())
        result = await actors.update_one({"_id": ObjectId(data.get("actor_id"))}, {"$set": {
            "photo_url": f"TG_ID:{tg_photo_id}", "is_actor_permanent": True,
            "photo_updated_at": updated_at, "photo_revision": revision}})
        if not result.matched_count:
            return web.json_response({"success": False, "error": "Profile not found"}, status=404, dumps=fast_json)
        return web.json_response({"success": True, "photo_updated_at": updated_at, "photo_revision": revision}, dumps=fast_json)
    except Exception as e: return web.json_response({"success": False, "error": str(e)}, dumps=fast_json)

# ─────────────────────────────────────────────────────────
# ⚙️ PROFILE: GALLERY UPLOAD
# ─────────────────────────────────────────────────────────
@actor_routes.post('/api/actor/gallery_upload')
async def api_actor_gallery_upload(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.json_response({"error": "Unauthorized"}, status=403, dumps=fast_json)
    try:
        reader = await req.multipart()
        actor_id, image_bytes_list = None, []
        while True:
            part = await reader.next()
            if part is None: break
            if part.name == 'actor_id':
                actor_id = (await part.read()).decode().strip()
            elif part.name == 'gallery_img':
                image_bytes = await part.read()
                if image_bytes:
                    # With the `multiple` input attribute the browser sends one
                    # multipart part per selected image, all with the same name.
                    image_bytes_list.append(image_bytes)
            
        if not actor_id or not image_bytes_list:
            return web.HTTPFound('/actors?err=Assets reading packet failure')

        # Upload each selected image and keep the resulting Telegram IDs in the
        # same order in which the user selected them.
        tg_photo_ids = []
        for image_number, image_bytes in enumerate(image_bytes_list, start=1):
            with io.BytesIO(image_bytes) as img_buffer:
                img_buffer.name = f"gallery_{actor_id}_{int(time.time())}_{image_number}.jpg"
                # ✅ UPGRADE: पुराने मिक्स्ड 'BIN_CHANNEL' के बजाय पृथक 'ACTOR_STORAGE_CHANNEL' का उपयोग
                msg = await temp.BOT.send_photo(chat_id=ACTOR_STORAGE_CHANNEL, photo=img_buffer)

            if not msg or not msg.photo:
                return web.HTTPFound(f'/actor/{actor_id}?err=Telegram Node Gallery Upload Failed ({image_number}/{len(image_bytes_list)})')
            tg_photo_id = msg.photo.sizes[-1].file_id if hasattr(msg.photo, "sizes") and msg.photo.sizes else msg.photo.file_id
            tg_photo_ids.append(f"TG_ID:{tg_photo_id}")
        
        # Add all uploaded images atomically so one multi-photo submission is
        # stored as one ordered batch instead of overwriting earlier images.
        await actors.update_one(
            {"_id": ObjectId(actor_id)},
            {"$push": {"gallery": {"$each": tg_photo_ids}}, "$set": {"is_gallery_permanent": True, "gallery_updated_at": int(time.time()), "gallery_revision": uuid.uuid4().hex}}
        )
        return web.HTTPFound(f'/actor/{actor_id}?msg={len(tg_photo_ids)} portrait(s) uploaded successfully to star gallery!')
    except Exception as e: return web.HTTPFound(f'/actors?err=System core crash: {str(e)}')

# ─────────────────────────────────────────────────────────
# ⚙️ PROFILE: GALLERY DELETE
# ─────────────────────────────────────────────────────────
@actor_routes.post('/api/actor/gallery_delete')
async def api_actor_gallery_delete(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.json_response({"error": "Unauthorized"}, status=403, dumps=fast_json)
    try:
        body = await req.json()
        actor_id, index = body.get("actor_id"), body.get("index")
        if not actor_id or index is None:
            return web.json_response({"success": False, "error": "Missing actor_id/index"}, dumps=fast_json)
        # The DB helper deletes one index using an atomic compare-and-set.
        ok = await delete_gallery_image_by_index(actor_id, int(index))
        if not ok:
            return web.json_response({"success": False, "error": "Profile or gallery changed. Refresh and try again."}, dumps=fast_json)
        return web.json_response({"success": True}, dumps=fast_json)
    except Exception as e: return web.json_response({"success": False, "error": str(e)}, dumps=fast_json)

# ─────────────────────────────────────────────────────────
# ⚙️ PROFILE: DELETE WHOLE PROFILE
# ─────────────────────────────────────────────────────────
@actor_routes.post('/api/actor/delete')
async def api_actor_delete(req):
    role, _ = await get_auth(req)
    if role != 'admin': return web.json_response({"error": "Unauthorized"}, status=403, dumps=fast_json)
    if not req.query.get("id"): return web.json_response({"error": "Missing ID"}, status=400, dumps=fast_json)
    try:
        # ✅ DUPLICATION FIX: database/ia_filterdb.py का delete_actor_profile()
        # पहले से मौजूद था, यहाँ दोबारा actors.delete_one() लिखने की जरूरत नहीं।
        ok = await delete_actor_profile(req.query.get("id"))
        if not ok: return web.json_response({"error": "Actor not found"}, status=404, dumps=fast_json)
        return web.json_response({"success": True}, dumps=fast_json)
    except Exception as e: return web.json_response({"error": str(e)}, status=500, dumps=fast_json)
