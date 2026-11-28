import io, time, html, re, uuid
from urllib.parse import urlencode, urlsplit
from aiohttp import web
from bson.objectid import ObjectId
from utils import temp
from info import MAX_WEB_RESULTS, MEDIA_STORAGE_CHANNEL
from database.ia_filterdb import actors, delete_actor_profile, delete_gallery_image_by_index
# ✅ DRY: fast_json + DIRECTORY_CSS अब web_assets से आते हैं (पहले दोनों यहाँ copy थे)
from web.web_assets import build_page, get_auth, require_active_plan, fast_json, DIRECTORY_CSS, DIRECTORY_FILTER_CSS, DEFAULT_CATALOG_MODE, DEFAULT_MEDIA_MODE, render_category_picker
from web.search_api import actor_search_page, _invalidate_search_caches, _GroupCursorLimitError, _GroupCursorStorageError
from web.dashboard_routes import SEARCH_PANEL_CSS, GROUP_CARD_CSS, GROUP_ENGINE_JS
from web.catalog_cards import render_catalog_card
from web.catalog_search import CATALOG_PAGE_SIZE, catalog_page

actor_routes = web.RouteTableDef()

ACTOR_MEDIA_SCRIPT = r'''<script>
var actorMediaFiles={};
function actorPlayFile(card){var f=actorMediaFiles[card.dataset.fid];if(f)openInlinePlayer(f.file_id,f.name);}
function actorEditFile(card){var f=actorMediaFiles[card.dataset.fid];if(f)editFile(f.file_id,f.raw_collection||'primary',encodeURIComponent(f.name||'').replace(/'/g,'%27'),encodeURIComponent(f.caption||'').replace(/'/g,'%27'));}
function actorDeleteFile(card){var f=actorMediaFiles[card.dataset.fid];if(f)deleteFile(f.file_id,f.raw_collection||'primary');}
function renderActorMediaCard(f,mode,isAdmin){
    actorMediaFiles[f.file_id]=f;
    var actions=isAdmin?`<button class="btn-edit" onclick="event.stopPropagation();actorEditFile(this.closest('.file-card'))">&#9999; Edit</button><button class="btn-del" onclick="event.stopPropagation();actorDeleteFile(this.closest('.file-card'))">&#128465; Delete</button>`:'';
    return renderMediaFile(f,mode,{admin:isAdmin,actions:actions,play:"actorPlayFile(this.closest('.file-card'))"});
}
</script><style>.poster-top{flex-wrap:wrap;align-content:flex-start}</style>'''

# ─────────────────────────────────────────────────────────
# 🌐 MAIN HOMEPAGE: UNIVERSAL DIRECTORY WITH SEARCH & FILTERS
# ─────────────────────────────────────────────────────────
@actor_routes.get('/actors')
async def actors_directory_page(req):
    role, tg_id = await get_auth(req)
    if not role: return web.HTTPFound('/login')
    if not await require_active_plan(role, tg_id): return web.HTTPFound('/premium_expired')
    
    all_actors, has_next_init = await catalog_page(actors, {})
    
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
                <span id="dir_cat_lbl">All</span> <span class="cdd-arrow" aria-hidden="true">▼</span>
                <div class="cdd-menu" id="dir_cat_menu">
                    <div class="cdd-item" onclick="pickDirCat('all', 'All', event)">All</div>
                    <div class="cdd-item" onclick="pickDirCat('actor', '🎭 Actor', event)">🎭 Actor</div>
                    <div class="cdd-item" onclick="pickDirCat('app', '📱 App', event)">📱 App</div>
                    <div class="cdd-item" onclick="pickDirCat('website', '🌐 Website', event)">🌐 Website</div>
                </div>
            </div>
            <div class="cdd-wrap" onclick="toggleDirCDD('mode', event)">
                <span id="dir_mode_lbl">{'📄 Text' if DEFAULT_CATALOG_MODE == 'text' else '🖼️ Poster'}</span> <span class="cdd-arrow" aria-hidden="true">▼</span>
                <div class="cdd-menu" id="dir_mode_menu">
                    <div class="cdd-item" onclick="pickDirMode('poster', '🖼️ Poster', event)">🖼️ Poster</div>
                    <div class="cdd-item" onclick="pickDirMode('text', '📄 Text', event)">📄 Text</div>
                </div>
            </div>
            {admin_btn}
        </div>
    </div>
    '''

    act_items = ''.join(render_catalog_card(a, 'actor', DEFAULT_CATALOG_MODE) for a in all_actors)

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
    var dirOffset = 0; var dirLimit = {CATALOG_PAGE_SIZE}; var dirPage = 1;
    var hasNext = {has_nxt_str};
    var currentCat = 'all'; var currentMode = MediaView.get('{DEFAULT_CATALOG_MODE}');
    var lastQ = "", lastCat = "all", lastMode = "{DEFAULT_CATALOG_MODE}", lastOffset = 0;
    var dirReqId = 0;
    
    document.addEventListener("DOMContentLoaded", () => {{ 
        if(sessionStorage.getItem('ff_dir_state')) {{
            document.getElementById('dir_q').value = sessionStorage.getItem('ff_dir_q') || "";
            currentCat = sessionStorage.getItem('ff_dir_cat') || "all";
            currentMode = MediaView.get('{DEFAULT_CATALOG_MODE}');
            dirOffset = parseInt(sessionStorage.getItem('ff_dir_off') || "0");
            dirPage = parseInt(sessionStorage.getItem('ff_dir_page') || "1");
            
            const catMap = {{'all':'All', 'actor':'🎭 Actor', 'app':'📱 App', 'website':'🌐 Website'}};
            const modeMap = {{'poster':'🖼️ Poster', 'text':'📄 Text'}};
            document.getElementById('dir_cat_lbl').innerText = catMap[currentCat] || 'All';
            document.getElementById('dir_mode_lbl').innerText = modeMap[currentMode] || modeMap['{DEFAULT_CATALOG_MODE}'];
            
            searchDirectory(true);
        }} else {{
            document.getElementById('dir_mode_lbl').innerText = currentMode === 'text' ? '📄 Text' : '🖼️ Poster';
            if(currentMode !== '{DEFAULT_CATALOG_MODE}') {{ searchDirectory(true); return; }}
            updatePgUI();
            staggerCards(document.getElementById('dir_grid_container'));
        }}
    }});

    MediaView.subscribe(function(value) {{
        if(value===currentMode)return;
        currentMode=value;document.getElementById('dir_mode_lbl').innerText=value==='text'?'📄 Text':'🖼️ Poster';
        resetDir();searchDirectory(true);
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
    function pickDirMode(val, lbl, e) {{ e.stopPropagation(); currentMode = MediaView.set(val); document.getElementById('dir_mode_lbl').innerText = lbl; closeAllDirCDD(); resetDir(); searchDirectory(); }}

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
            if (myReq !== dirReqId) {{ clearTimeout(loadTimer); return; }}
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
        }} catch(e) {{ clearTimeout(loadTimer); if (myReq !== dirReqId) return; if (row) row.classList.remove('loading'); lastQ = null; grid.innerHTML = '<div style="grid-column:1/-1; text-align:center; color:var(--accent); font-weight:bold;">Search Error! Please retry.</div>'; }}
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
    role, tg_id = await get_auth(req)
    if not role or not await require_active_plan(role, tg_id):
        return web.json_response({"error": "Access denied."}, status=403, dumps=fast_json)

    q = req.query.get("q", "").strip()
    cat = req.query.get("cat", "all")
    mode = req.query.get("mode", DEFAULT_CATALOG_MODE)
    offset = req.query.get("offset", 0)
    
    query = {}
    if cat != "all": query["category"] = cat
    if q: 
        safe_q = re.escape(q)
        query["name"] = {"$regex": safe_q, "$options": "i"}
        
    try:
        docs, has_next = await catalog_page(actors, query, offset)
    except Exception:
        return web.json_response({"error": "Profile search temporarily unavailable."}, status=503, dumps=fast_json)
    
    if not docs:
        return web.json_response({"html": '<div style="grid-column:1/-1; color:var(--muted); text-align:center; padding:60px 20px;">📇 No profiles matching your filters found.</div>', "has_next": False}, dumps=fast_json)
        
    html_out = ''.join(render_catalog_card(a, 'actor', mode) for a in docs)

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
.profile-cancel{color:var(--text);text-decoration:none;border:1px solid var(--border);background:var(--bg3);border-radius:9px;padding:10px 14px;font-size:13px;font-weight:700;white-space:nowrap;cursor:pointer}
.profile-studio-kicker,.profile-section-kicker{font-size:10px;letter-spacing:1.3px;text-transform:uppercase;color:var(--accent);font-weight:900}
.profile-studio-head h1{font-size:26px;line-height:1.2;margin:5px 0}.profile-studio-head p,.profile-help{font-size:12px;line-height:1.55;color:var(--muted)}
.profile-section{background:var(--bg2);border:1px solid var(--border);border-radius:14px;padding:20px;margin-bottom:14px}
.profile-section-head{margin-bottom:16px}.profile-section-head h2{font-size:16px;margin:5px 0}.profile-section-head p{font-size:12px;line-height:1.5;color:var(--muted)}
.profile-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.profile-field{display:flex;flex-direction:column;gap:7px;min-width:0;color:var(--text);font-size:12px;font-weight:800}
.profile-field.full{grid-column:1/-1}.profile-field .em-input{margin:0;padding:12px;background:var(--bg);border-radius:9px;font-family:inherit;font-weight:500;line-height:1.4}
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
    link_rows = ''.join(
        '<div class="profile-link-row"><label class="profile-field">Name <span>(optional)</span>'
        f'<input class="em-input" name="link_label" maxlength="200" value="{esc(link.get("label"))}" placeholder="Website, Instagram, shop…"></label>'
        '<label class="profile-field">URL'
        f'<input class="em-input" name="link_url" inputmode="url" value="{esc(link.get("url"))}" placeholder="https://example.com"></label>'
        '<button class="profile-link-remove" type="button" data-link-remove>Remove</button></div>'
        for link in links
    )
    category_field = render_category_picker(
        [("actor", "🎭 Actor"), ("app", "📱 App"), ("website", "🌐 Website")],
        category or "actor",
        field_class="profile-field",
    )
    return (
        '<section class="profile-section"><div class="profile-section-head"><div class="profile-section-kicker">01 · Identity</div><h2>Profile details</h2><p>Tell visitors who or what this profile represents.</p></div>'
        '<div class="profile-fields">'
        f'<label class="profile-field">Display name<input type="text" name="name" value="{esc(name)}" placeholder="Name of actor, app or website" class="em-input" required></label>'
        + category_field +
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
      <header class="profile-studio-head"><a class="profile-back back-pill-btn" href="/actors" onclick="return openBackNav(this,event)" onpointerenter="prefetchCatalogUrl('/actors')" ontouchstart="prefetchCatalogUrl('/actors')">← Back</a><div><div class="profile-studio-kicker">Profile studio</div><h1>Create a profile</h1><p>Make a home for an actor, app or website.</p></div></header>
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
            msg = await temp.BOT.send_photo(chat_id=MEDIA_STORAGE_CHANNEL, photo=img_buffer)
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
.actor-page{max-width:1200px;margin:0 auto;padding:24px 20px 68px}
.actor-top-bar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:16px}
.actor-back{margin-bottom:0}
.actor-top-actions{display:flex;gap:8px;flex-wrap:wrap;margin-left:auto}
.actor-btn{position:relative;overflow:hidden;display:inline-flex;align-items:center;justify-content:center;gap:6px;background:var(--accent);color:#fff;border:0;border-radius:9px;padding:10px 18px;font-family:inherit;font-weight:800;font-size:13px;cursor:pointer;transition:transform .16s,background .16s,box-shadow .16s}
.actor-btn:hover{background:var(--accent-hover);transform:translateY(-2px);box-shadow:0 8px 22px rgba(229,9,20,.35)}
.actor-btn:active{transform:scale(.96)}
.actor-btn.ghost{background:var(--bg3);border:1px solid var(--border);color:var(--text)}
.actor-btn.ghost:hover{background:var(--bg2);border-color:var(--accent);box-shadow:none}
.actor-btn i.actor-rip{position:absolute;border-radius:50%;background:rgba(255,255,255,.42);transform:scale(0);animation:actorRipple .5s ease-out forwards;pointer-events:none}
@keyframes actorRipple{to{transform:scale(2.8);opacity:0}}
.actor-tab-bar{display:flex;align-items:stretch;gap:2px;flex-wrap:nowrap;border-bottom:2px solid var(--border);margin:20px 0 20px;position:relative;overflow-x:auto;scrollbar-width:none}
.actor-tab-bar::-webkit-scrollbar{display:none}
.actor-tab{position:relative;display:inline-flex;flex-direction:row;align-items:center;justify-content:center;gap:6px;background:none;border:0;color:var(--muted);padding:12px 16px;font-size:13px;font-weight:800;cursor:pointer;font-family:inherit;white-space:nowrap;transition:color .18s,transform .18s}
.actor-tab:hover:not(.active){color:var(--text);transform:translateY(-2px)}
.actor-tab:focus-visible{outline:2px solid var(--accent);outline-offset:-3px;border-radius:6px}
.actor-tab.active{color:var(--accent)!important;background:none!important}
.actor-tab::after{content:'';position:absolute;left:12px;right:12px;bottom:-2px;height:2px;background:var(--accent);transform:scaleX(0);transition:transform .28s cubic-bezier(.34,1.4,.64,1)}
.actor-tab.active::after{transform:scaleX(1)}
.actor-tab-ico{font-size:14px;line-height:1;flex-shrink:0}
.actor-tab-label{display:inline-flex;align-items:center;gap:6px;min-width:0}
.actor-tab-badge{display:inline-block;min-width:19px;padding:1px 6px;border-radius:20px;background:var(--bg3);border:1px solid var(--border);font-size:10px;font-weight:800;color:var(--muted);line-height:1.4;text-align:center;transition:background .2s,color .2s,border-color .2s}
.actor-tab.active .actor-tab-badge{background:var(--accent);border-color:var(--accent);color:#fff}
.actor-panel{display:none;animation:actorPanelIn .42s cubic-bezier(.25,.8,.25,1) both}
.actor-panel.active{display:block!important}
@keyframes actorPanelIn{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:none}}
@keyframes actorFade{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:translateY(0)}}
.actor-header-wrap{display:flex;gap:26px;flex-wrap:wrap;background:var(--card);border:1px solid var(--border);border-radius:16px;padding:24px;margin-bottom:18px;width:100%;box-sizing:border-box;animation:actorFade .5s ease both}
.avatar-box-master{position:relative;flex:0 0 240px;width:240px;max-width:100%;aspect-ratio:3/4;background:var(--bg3);border-radius:12px;overflow:hidden;border:1px solid var(--border);cursor:zoom-in}
.avatar-box-master img{display:block;width:100%;height:100%;object-fit:cover;transition:transform .3s ease}
.avatar-box-master:hover img{transform:scale(1.03)}
.avatar-zoom-pill{position:absolute;right:10px;bottom:10px;display:inline-flex;align-items:center;gap:4px;background:rgba(0,0,0,.8);color:#fff;border:1px solid rgba(255,255,255,.4);border-radius:8px;padding:6px 9px;font-size:12px;font-weight:800;pointer-events:none}
.actor-identity{flex:1;min-width:0}
.actor-identity h1{font-size:28px;font-weight:900;line-height:1.15;letter-spacing:-1px;margin-bottom:10px;overflow-wrap:anywhere}
.actor-chips{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px;max-width:100%}
.actor-category,.actor-tag{display:inline-flex;align-items:center;gap:4px;border-radius:20px;padding:4px 10px;font-size:11px;font-weight:800;line-height:1.3;overflow-wrap:anywhere}
.actor-category{background:var(--accent);border:1px solid var(--accent);color:#fff}
.actor-tag{background:var(--bg3);border:1px solid var(--border);color:var(--muted);cursor:pointer;font-family:inherit;transition:border-color .15s,color .15s}
.actor-tag:hover{border-color:var(--accent);color:var(--text)}
.actor-bio-copy{font-size:14px;line-height:1.7;color:var(--text);white-space:pre-wrap;overflow-wrap:anywhere;margin-bottom:18px}
.actor-links{display:flex;gap:9px;flex-wrap:wrap;max-width:100%}
.actor-link{display:inline-flex;align-items:center;gap:5px;background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:9px 14px;font-size:12px;font-weight:800;color:var(--text);text-decoration:none;overflow-wrap:anywhere;transition:transform .16s,border-color .16s,color .16s}
.actor-link::before{content:'🔗 '}
.actor-link:hover{transform:translateY(-2px);border-color:var(--accent);color:var(--accent)}
.actor-links-empty{color:var(--muted);font-size:12px;font-weight:700}
.actor-tagline{display:flex;gap:6px;flex-wrap:wrap;margin:2px 0 14px}
.actor-tagpill{background:var(--bg3);border:1px solid var(--border);border-radius:20px;padding:4px 10px;font-size:10.5px;font-weight:800;color:var(--muted);cursor:pointer;font-family:inherit;transition:border-color .15s,color .15s}
.actor-tagpill:hover{border-color:var(--accent);color:var(--text)}
.actor-tagpill b{color:var(--accent)}
.actor-gallery-upload{display:flex;gap:12px;align-items:center;flex-wrap:wrap;background:var(--card);border:1px dashed var(--border);border-radius:12px;padding:14px 16px;margin-bottom:16px}
.actor-gallery-upload-copy{flex:1 1 200px;font-size:11px;font-weight:600;color:var(--muted)}
.actor-gallery-choose{display:inline-flex;align-items:center;gap:6px;position:relative;overflow:hidden;padding:9px 14px;background:var(--bg3);border:1px dashed var(--border);color:var(--text);border-radius:8px;font-size:11.5px;font-weight:800;cursor:pointer;white-space:nowrap;transition:border-color .16s}
.actor-gallery-choose:hover{border-color:var(--accent)}
.actor-gallery-choose input{position:absolute;inset:0;width:100%;height:100%;opacity:0;cursor:pointer}
.actor-gallery-choose:focus-within{outline:2px solid var(--accent);outline-offset:3px}
.actor-gallery-empty{background:var(--card);border:1px dashed var(--border);border-radius:12px;padding:34px 18px;text-align:center;color:var(--muted);font-size:13px;font-weight:700}
.gallery-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px}
@media(min-width:700px){.gallery-grid{grid-template-columns:repeat(auto-fill,minmax(190px,1fr))}}
.gallery-item-wrap{position:relative;border-radius:11px;overflow:hidden;border:1px solid var(--border);aspect-ratio:1;cursor:pointer;background:var(--bg3)}
.gallery-item-wrap:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.gallery-item{width:100%;height:100%;object-fit:cover;opacity:0;transition:opacity .35s,transform .3s ease}
.gallery-item.on{opacity:1}
.gallery-item-wrap:hover .gallery-item{transform:scale(1.06)}
.actor-gal-enter{opacity:0}
.actor-gal-enter.in{animation:actorGalIn .55s cubic-bezier(.34,1.2,.64,1) forwards}
@keyframes actorGalIn{0%{opacity:0;transform:translateY(26px) scale(.94)}60%{opacity:1;transform:translateY(-4px) scale(1.01)}100%{opacity:1;transform:none}}
.gallery-del-btn{position:absolute;top:7px;right:7px;background:rgba(160,8,8,.92);border:0;color:#fff;padding:4px 8px;border-radius:6px;font-size:10px;font-weight:800;cursor:pointer;z-index:5;opacity:0;transition:opacity .2s}
.gallery-item-wrap:hover .gallery-del-btn,.gallery-item-wrap:focus-within .gallery-del-btn{opacity:1}
@media(hover:none){.gallery-del-btn{opacity:1;min-width:34px;min-height:34px}}
.lightbox{position:fixed;inset:0;background:rgba(0,0,0,.92);backdrop-filter:blur(14px);z-index:99999;display:none;align-items:center;justify-content:center;opacity:0;transition:opacity .22s ease;padding:20px}.lightbox.open{display:flex;opacity:1}.lightbox-img{max-width:94%;max-height:86vh;object-fit:contain;border-radius:10px;box-shadow:0 16px 50px rgba(0,0,0,.85);transform:scale(.94);transition:transform .25s cubic-bezier(.34,1.3,.64,1)}.lightbox.open .lightbox-img{transform:scale(1)}.lightbox-close{position:absolute;top:16px;right:16px;width:44px;height:44px;display:grid;place-items:center;background:rgba(0,0,0,.75);border:1px solid rgba(255,255,255,.5);border-radius:50%;color:#fff;font-size:26px;line-height:1;cursor:pointer}.lightbox-close:hover{border-color:var(--accent)}
.lightbox-nav{position:absolute;top:50%;transform:translateY(-50%);width:44px;height:44px;display:grid;place-items:center;border-radius:50%;background:rgba(0,0,0,.65);border:1px solid rgba(255,255,255,.3);color:#fff;font-size:24px;cursor:pointer;transition:background .15s,border-color .15s}.lightbox-nav:hover{background:rgba(229,9,20,.85);border-color:var(--accent)}.lightbox-prev{left:16px}.lightbox-next{right:16px}.lightbox-counter{position:absolute;bottom:18px;left:50%;transform:translateX(-50%);padding:5px 12px;border-radius:999px;background:rgba(0,0,0,.7);border:1px solid rgba(255,255,255,.2);color:#fff;font-size:12px;font-weight:800}
.profile-modal-card{border-radius:18px!important;box-shadow:0 24px 70px rgba(0,0,0,.5)}.profile-modal-card .profile-section{border-radius:12px}.profile-field .em-input:focus{box-shadow:0 0 0 3px rgba(229,9,20,.12)}.profile-link-add:hover,.profile-cancel:hover{border-color:var(--accent)}
@media(max-width:767px){.actor-header-wrap{flex-direction:column;align-items:stretch;gap:18px;padding:16px;margin-bottom:20px;border-radius:16px}.avatar-box-master{flex:0 1 100%;width:100%;max-width:100%;height:auto;aspect-ratio:3/4;border-radius:12px}.actor-identity{flex-basis:100%}}
@media(max-width:600px){.actor-page{padding:16px 12px 50px}.actor-identity h1{font-size:24px;letter-spacing:-.5px}.actor-tab-bar{justify-content:space-around;margin:16px 0 18px}.actor-tab{flex:1;min-width:0;padding:12px 6px;font-size:12.5px;gap:4px}.actor-tab::after{left:8px;right:8px}.lightbox-nav{width:38px;height:38px;font-size:20px}.lightbox-prev{left:10px}.lightbox-next{right:10px}}
@media(prefers-reduced-motion:reduce){.actor-header-wrap,.actor-panel,.actor-tab,.actor-tab::after,.gallery-item,.actor-gal-enter,.actor-gal-enter.in,.lightbox,.lightbox-img{animation:none!important;transition:none!important;opacity:1!important;transform:none!important}}
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
    cat_badge = f'<span class="actor-category">{cat_emoji} {html.escape(str(category).title())}</span>'
    t_html = "".join(
        f'<button type="button" class="actor-tag" onclick="searchActorTag({html.escape(fast_json(t), quote=True)})" title="Filter media by #{html.escape(t, quote=True)}">#{html.escape(t)}</button>'
        for t in tags_list
    )
    tags_chips_html = f'<div class="actor-chips">{cat_badge}{t_html}</div>'
    s_html = "".join(
        f'<a class="actor-link" href="{html.escape(link["url"], quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(link["label"])}</a>'
        for link in links
    )
    social_html = f'<div class="actor-links" aria-label="Profile links">{s_html}</div>' if s_html else '<div class="actor-links"><span class="actor-links-empty">🔗 No external links.</span></div>'

    gallery_grid_html = f'''<div class="actor-gallery-upload"><form action="/api/actor/gallery_upload" method="post" enctype="multipart/form-data"><input type="hidden" name="actor_id" value="{actor_id}"><label class="actor-gallery-choose">📂 Add photos to gallery<input type="file" name="gallery_img" accept="image/*" multiple onchange="this.form.submit()"></label></form><span class="actor-gallery-upload-copy">Select several photos at once — they are saved to Telegram one at a time</span></div>''' if role == 'admin' else ""
    gallery_urls = []
    if not gallery_list:
        gallery_grid_html += '<div class="actor-gallery-empty">🖼️ The gallery is empty.</div>'
    else:
        # ✅ CACHE FIX: /api/actor/photo 1-साल immutable cache भेजता है — बिना version
        # param के delete/upload के बाद browser पुरानी image (पुराने gallery_idx URL से)
        # दिखाता रहता था, जिससे लगता था कि photo delete ही नहीं हुई। अब &v={gallery_v}
        # हर बदलाव पर URL बदल देता है।
        gallery_v = actor.get("gallery_revision") or int(actor.get("gallery_updated_at") or actor.get("photo_updated_at") or actor.get("created_at") or 0)
        gallery_urls = [f"/api/actor/photo?id={actor_id}&gallery_idx={i}&v={gallery_v}" for i in range(len(gallery_list))]
        g_items = "".join([f'<div class="gallery-item-wrap actor-gal-enter" role="button" tabindex="0" aria-label="Enlarge image" data-src="{gallery_urls[i]}" data-idx="{i}" onclick="openLightbox(\'{gallery_urls[i]}\',{i})"><img src="{gallery_urls[i]}" class="gallery-item" loading="lazy" onload="this.classList.add(\'on\')" onerror="this.classList.add(\'on\')">' + (f'<button class="gallery-del-btn" title="Remove" onclick="deleteGalleryImage(\'{actor_id}\', {i}, event)">✕</button>' if role=='admin' else "") + '</div>' for i in range(len(gallery_list))])
        gallery_grid_html += f'<div class="gallery-grid">{g_items}</div>'

    admin_top_btns = (
        f'<div class="actor-top-actions">'
        f'<button type="button" class="actor-btn" onclick="openActorEditModal()">✏️ Edit Profile</button>'
        f'<button type="button" class="actor-btn ghost" onclick="deleteActorProfile(\'{actor_id}\')">🗑 Delete</button>'
        f'</div>'
        if role == 'admin' else ""
    )

    video_tag_pills = "".join(
        f'<button type="button" class="actor-tagpill" onclick="searchActorTag({html.escape(fast_json(t), quote=True)})">🏷️ <b>#{html.escape(t)}</b></button>'
        for t in tags_list[:12]
    ) or f'<span class="actor-tagpill">🏷️ No search tags — searching by <b>{html.escape(actor_name)}</b></span>'

    tags_json_payload = html.escape(fast_json(tags_list))
    gallery_json_payload = fast_json(gallery_urls)
    safe_bio = html.escape(actor.get("bio", ""))
    bio_html = safe_bio if safe_bio else '<span style="color:var(--muted)">No description available.</span>'
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
    
    # 🎛️ Default media mode (centralized via DEFAULT_MEDIA_MODE in web_assets.py, synced with main page)
    ap_mode_tg_lbl = "🖼️ Poster"
    ap_mode_none_lbl = "📄 Text"
    ap_mode_lbl = ap_mode_none_lbl if DEFAULT_MEDIA_MODE == "none" else ap_mode_tg_lbl
    ap_sel_tg = " selected" if DEFAULT_MEDIA_MODE == "tg" else ""
    ap_sel_none = " selected" if DEFAULT_MEDIA_MODE == "none" else ""

    gallery_badge = f'<span class="actor-tab-badge">{len(gallery_list)}</span>'
    actor_page_markup = f'''{ACTOR_PROFILE_CSS}<main class="actor-page"><div class="actor-top-bar"><a class="actor-back back-pill-btn" href="/actors" onclick="return openBackNav(this,event)" onpointerenter="prefetchCatalogUrl('/actors')" ontouchstart="prefetchCatalogUrl('/actors')">← Back</a>{admin_top_btns}</div><div class="actor-tab-bar" role="tablist"><button type="button" id="actorInfoTabBtn" class="actor-tab active" aria-pressed="true" role="tab" aria-selected="true" aria-controls="tab-info" tabindex="0" data-tab="overview" onclick="switchActorTab(event,'tab-info')"><span class="actor-tab-ico" aria-hidden="true">ℹ️</span><span class="actor-tab-label">Overview</span></button><button type="button" id="actorMediaTabBtn" class="actor-tab" aria-pressed="false" role="tab" aria-selected="false" aria-controls="tab-video" tabindex="-1" data-tab="videos" onclick="switchActorTab(event,'tab-video')"><span class="actor-tab-ico" aria-hidden="true">🎬</span><span class="actor-tab-label">Videos</span></button><button type="button" id="actorGalleryTabBtn" class="actor-tab" aria-pressed="false" role="tab" aria-selected="false" aria-controls="tab-gallery" tabindex="-1" data-tab="gallery" onclick="switchActorTab(event,'tab-gallery')"><span class="actor-tab-ico" aria-hidden="true">🖼️</span><span class="actor-tab-label">Gallery{gallery_badge}</span></button></div><div id="tab-info" class="actor-panel active" role="tabpanel" aria-labelledby="actorInfoTabBtn"><div class="actor-header-wrap"><div class="avatar-box-master" onclick="openLightbox('/api/actor/photo?id={actor_id}&v={photo_v}',-1)"><img id="actorMasterAvatarImage" src="/api/actor/photo?id={actor_id}&v={photo_v}" alt="{html.escape(actor_name, quote=True)} profile photo"><span class="avatar-zoom-pill" aria-hidden="true">🔍 Enlarge</span></div><div class="actor-identity"><h1>{html.escape(actor_name)}</h1>{tags_chips_html}<div class="actor-bio-copy">{bio_html}</div>{social_html}</div></div></div><div id="tab-video" class="actor-panel" role="tabpanel" aria-labelledby="actorMediaTabBtn"><div class="actor-tagline">{video_tag_pills}</div><div class="search-box actor-search-panel"><div class="search-row1"><div class="search-wrap" id="actMovieWrap"><input type="text" id="actor_movie_q" value="" placeholder="Search inside this profile..." class="search-input"><button type="button" class="search-clear" id="actMovieClear" aria-label="Clear search" hidden>&times;</button><span class="search-spinner" id="actMovieSpinner"></span></div><div class="cdd-wrap gf-wrap" id="cddGfWrapActor" onclick="toggleActorCdd('gf',event)"><button type="button" class="cdd-btn" id="cddGfBtnActor" aria-label="Group filter: All" aria-expanded="false" aria-controls="cddGfMenuActor"><span class="cdd-kicker">Group:</span><span id="cddGfLabelActor">All</span></button><span class="cdd-arrow" aria-hidden="true">&#9660;</span><div class="cdd-menu" id="cddGfMenuActor" style="display:none"><button type="button" class="cdd-item selected" data-val="all" onclick="pickActorGF('all','All',this,event)">All</button><button type="button" class="cdd-item" data-val="group" onclick="pickActorGF('group','Group',this,event)">Group</button><button type="button" class="cdd-item" data-val="single" onclick="pickActorGF('single','UnGroup',this,event)">UnGroup</button></div></div></div><div class="search-row2"><div class="cdd-wrap" id="cddColWrapActor" onclick="toggleActorCdd('col',event)"><button type="button" class="cdd-btn" id="cddColBtnActor" aria-label="Collection filter: All" aria-expanded="false" aria-controls="cddColMenuActor"><span class="cdd-kicker">Source:</span><span id="cddColLabelActor">All</span></button><span class="cdd-arrow" aria-hidden="true">&#9660;</span><div class="cdd-menu" id="cddColMenuActor" style="display:none"><button type="button" class="cdd-item selected" data-val="all" onclick="pickActorCol('all','All',this,event)">All</button><button type="button" class="cdd-item" data-val="primary" onclick="pickActorCol('primary','🟢 Primary',this,event)">🟢 Primary</button><button type="button" class="cdd-item" data-val="cloud" onclick="pickActorCol('cloud','🔵 Cloud',this,event)">🔵 Cloud</button><button type="button" class="cdd-item" data-val="archive" onclick="pickActorCol('archive','🟠 Archive',this,event)">🟠 Archive</button></div></div><div class="cdd-wrap" id="cddModeWrapActor" onclick="toggleActorCdd('mode',event)"><button type="button" class="cdd-btn" id="cddModeBtnActor" aria-label="View mode filter" aria-expanded="false" aria-controls="cddModeMenuActor"><span class="cdd-kicker">View:</span><span id="cddModeLabelActor">{ap_mode_lbl}</span></button><span class="cdd-arrow" aria-hidden="true">&#9660;</span><div class="cdd-menu" id="cddModeMenuActor" style="display:none"><button type="button" class="cdd-item{ap_sel_tg}" data-val="tg" onclick="pickActorMode('tg','🖼️ Poster',this,event)">🖼️ Poster</button><button type="button" class="cdd-item{ap_sel_none}" data-val="none" onclick="pickActorMode('none','📄 Text',this,event)">📄 Text</button></div></div></div></div><div class="results-info" id="actorResInfo" style="padding:0 2px 10px;display:none"><span class="results-count" id="actorResCount"></span></div><div id="actor_video_results" class="res-grid"></div><div class="pagination" id="actor_page_box" style="display:none"><button class="pg-btn" id="actor_pBtn" onclick="actorPagePrev()" disabled>Previous</button><span class="pg-info" id="actor_pgInfo">Page 1</span><button class="pg-btn" id="actor_nBtn" onclick="actorPageNext()">Next</button></div></div><div id="tab-gallery" class="actor-panel" role="tabpanel" aria-labelledby="actorGalleryTabBtn">{gallery_grid_html}</div></main><div id="actorLightboxModal" class="lightbox" onclick="closeLightbox()"><button type="button" class="lightbox-close" aria-label="Close lightbox" onclick="closeLightbox()">&times;</button><button type="button" class="lightbox-nav lightbox-prev" id="lbPrevBtn" aria-label="Previous photo" onclick="stepLightbox(-1,event)">&#8249;</button><img id="lightboxTargetImg" class="lightbox-img" src="" onclick="event.stopPropagation()"><button type="button" class="lightbox-nav lightbox-next" id="lbNextBtn" aria-label="Next photo" onclick="stepLightbox(1,event)">&#8250;</button><div class="lightbox-counter" id="lbCounter" hidden></div></div><input type="hidden" id="actor_master_tags_payload" value="{tags_json_payload}">{profile_edit_modal}'''

    actor_page_js = f'''
var hideSelFab=true;
var actorGalleryUrls={gallery_json_payload},actorLightboxIdx=-1;
var actCurPage=1,actOffset=0,actNextOffset="",actOffHist=[],actPageGroups={{}},actLimit={MAX_WEB_RESULTS},actCol="all",actGF="all",actMovieReqId=0,actVideosLoaded=false;
var actMode=MediaView.media("{DEFAULT_MEDIA_MODE}");
var pMode=actMode;
document.addEventListener('DOMContentLoaded',function(){{isAdminView=(document.getElementById('editCombinedModal')!==null);}});
document.getElementById('cddModeLabelActor').textContent=actMode==='none'?'📄 Text':'🖼️ Poster';
document.getElementById('cddModeBtnActor').setAttribute('aria-label','View mode filter: '+(actMode==='none'?'Text':'Poster'));
document.querySelectorAll('#cddModeMenuActor .cdd-item').forEach(function(i){{i.classList.toggle('selected',i.dataset.val===actMode);}});
MediaView.subscribe(function(value){{
    var mode=value==='text'?'none':'tg';if(mode===actMode)return;
    actMode=mode;pMode=mode;
    document.getElementById('cddModeLabelActor').textContent=mode==='none'?'📄 Text':'🖼️ Poster';
    document.getElementById('cddModeBtnActor').setAttribute('aria-label','View mode filter: '+(mode==='none'?'Text':'Poster'));
    document.querySelectorAll('#cddModeMenuActor .cdd-item').forEach(function(i){{i.classList.toggle('selected',i.dataset.val===mode);}});
    if(actVideosLoaded)triggerActorSearchAjax();
}});
var ACTOR_CDDS={{gf:['cddGfMenuActor','cddGfBtnActor'],col:['cddColMenuActor','cddColBtnActor'],mode:['cddModeMenuActor','cddModeBtnActor']}};
function closeActorCdds(){{
    Object.keys(ACTOR_CDDS).forEach(function(k){{
        var m=document.getElementById(ACTOR_CDDS[k][0]),b=document.getElementById(ACTOR_CDDS[k][1]);
        if(m)m.style.display='none';if(b){{b.classList.remove('open');b.setAttribute('aria-expanded','false');}}
    }});
}}
function toggleActorCdd(w,e){{
    if(e)e.stopPropagation();
    var pair=ACTOR_CDDS[w];if(!pair)return;
    var m=document.getElementById(pair[0]),b=document.getElementById(pair[1]);
    var isOpen=m.style.display!=='none';
    closeActorCdds();
    if(!isOpen){{m.style.display='block';b.classList.add('open');b.setAttribute('aria-expanded','true');}}
}}
function pickActorGF(v,l,el,e){{
    if(e)e.stopPropagation();
    actGF=v;
    document.getElementById('cddGfLabelActor').textContent=l;
    document.getElementById('cddGfBtnActor').setAttribute('aria-label','Group filter: '+l);
    var wrap=document.getElementById('cddGfWrapActor');if(wrap)wrap.classList.toggle('filter-active',v!=='all');
    document.querySelectorAll('#cddGfMenuActor .cdd-item').forEach(function(i){{i.classList.remove('selected');}});
    el.classList.add('selected');
    closeActorCdds();
    if(e&&e.detail===0)document.getElementById('cddGfBtnActor').focus();
    resetActorSearchPage();
    triggerActorSearchAjax();
}}
function pickActorCol(v,l,el,e){{
    if(e)e.stopPropagation();
    actCol=v;
    document.getElementById('cddColLabelActor').textContent=l;
    document.getElementById('cddColBtnActor').setAttribute('aria-label','Collection filter: '+l);
    var wrap=document.getElementById('cddColWrapActor');if(wrap)wrap.classList.toggle('filter-active',v!=='all');
    document.querySelectorAll('#cddColMenuActor .cdd-item').forEach(function(i){{i.classList.remove('selected');}});
    el.classList.add('selected');
    closeActorCdds();
    if(e&&e.detail===0)document.getElementById('cddColBtnActor').focus();
    resetActorSearchPage();
    triggerActorSearchAjax();
}}
function pickActorMode(v,l,el,e){{
    if(e)e.stopPropagation();
    actMode=v;pMode=v;MediaView.set(v);
    document.getElementById('cddModeLabelActor').textContent=l;
    document.getElementById('cddModeBtnActor').setAttribute('aria-label','View mode filter: '+l);
    document.querySelectorAll('#cddModeMenuActor .cdd-item').forEach(function(i){{i.classList.remove('selected');}});
    el.classList.add('selected');
    closeActorCdds();
    if(e&&e.detail===0)document.getElementById('cddModeBtnActor').focus();
    triggerActorSearchAjax();
}}
document.addEventListener('click',function(e){{if(!e.target.closest('.actor-search-panel .cdd-wrap'))closeActorCdds();}});
document.addEventListener('keydown',function(e){{
    var lb=document.getElementById('actorLightboxModal');
    if(lb&&lb.classList.contains('open')){{
        if(e.key==='Escape'){{e.preventDefault();closeLightbox();return;}}
        if(e.key==='ArrowLeft'){{e.preventDefault();stepLightbox(-1);return;}}
        if(e.key==='ArrowRight'){{e.preventDefault();stepLightbox(1);return;}}
    }}
    var focused=document.activeElement;
    if((e.key==='Enter'||e.key===' ')&&focused&&focused.classList&&focused.classList.contains('gallery-item-wrap')){{
        e.preventDefault();openLightbox(focused.dataset.src,Number(focused.dataset.idx));return;
    }}
    if(focused&&focused.classList&&focused.classList.contains('actor-tab')&&['ArrowLeft','ArrowRight','Home','End'].indexOf(e.key)>=0){{
        e.preventDefault();
        var tabs=Array.prototype.slice.call(document.querySelectorAll('.actor-tab'));
        var idx=tabs.indexOf(focused);
        if(e.key==='Home')idx=0;
        else if(e.key==='End')idx=tabs.length-1;
        else idx=(idx+(e.key==='ArrowRight'?1:tabs.length-1))%tabs.length;
        var target=tabs[idx];
        if(target){{activateActorTab(target.dataset.tab);target.focus();}}
        return;
    }}
    if(e.key==='Escape'){{var open=document.querySelector('.actor-search-panel .cdd-btn[aria-expanded="true"]');if(open){{closeActorCdds();open.focus();}}}}
}});
document.addEventListener('pointerdown',function(e){{
    var b=e.target.closest&&e.target.closest('.actor-btn');
    if(!b)return;
    if(window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches)return;
    var r=b.getBoundingClientRect(),i=document.createElement('i'),d=Math.max(r.width,r.height);
    i.className='actor-rip';
    i.style.cssText='width:'+d+'px;height:'+d+'px;left:'+(e.clientX-r.left-d/2)+'px;top:'+(e.clientY-r.top-d/2)+'px';
    b.appendChild(i);setTimeout(function(){{i.remove();}},520);
}});
document.querySelectorAll('.actor-search-panel .cdd-menu').forEach(function(m){{m.addEventListener('click',function(e){{e.stopPropagation();}});}});
var actorLightReturnFocus=null;
function syncLightboxNav(){{
    var prev=document.getElementById('lbPrevBtn'),next=document.getElementById('lbNextBtn'),cnt=document.getElementById('lbCounter');
    var showNav=actorLightboxIdx>=0&&actorGalleryUrls.length>1;
    if(prev)prev.style.display=showNav?'grid':'none';
    if(next)next.style.display=showNav?'grid':'none';
    if(cnt){{
        if(showNav){{cnt.textContent=(actorLightboxIdx+1)+' / '+actorGalleryUrls.length;cnt.hidden=false;}}
        else cnt.hidden=true;
    }}
}}
function openLightbox(s,idx){{
    actorLightReturnFocus=document.activeElement;
    actorLightboxIdx=typeof idx==='number'?idx:-1;
    document.getElementById('lightboxTargetImg').src=s;
    syncLightboxNav();
    var lb=document.getElementById('actorLightboxModal');lb.style.display='flex';setTimeout(()=>lb.classList.add('open'),10);
}}
function stepLightbox(delta,ev){{
    if(ev)ev.stopPropagation();
    if(actorLightboxIdx<0||actorGalleryUrls.length<2)return;
    actorLightboxIdx=(actorLightboxIdx+delta+actorGalleryUrls.length)%actorGalleryUrls.length;
    document.getElementById('lightboxTargetImg').src=actorGalleryUrls[actorLightboxIdx];
    syncLightboxNav();
}}
function closeLightbox(){{
    var lb=document.getElementById('actorLightboxModal');
    lb.classList.remove('open');
    setTimeout(()=>lb.style.display='none',200);
    if(actorLightReturnFocus&&actorLightReturnFocus.focus)actorLightReturnFocus.focus();
}}
function staggerActorGallery(){{
    var items=document.querySelectorAll('#tab-gallery .gallery-item-wrap');
    var noMotion=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    items.forEach(function(el,i){{
        var img=el.querySelector('img.gallery-item');
        if(img&&img.complete&&img.naturalWidth)img.classList.add('on');
        if(noMotion){{el.classList.remove('actor-gal-enter','in');el.style.animationDelay='';return;}}
        el.classList.remove('in');
        el.classList.add('actor-gal-enter');
        var delay=Math.round(Math.min(i,8)*0.06*1000)/1000;
        el.style.animationDelay=delay+'s';
        void el.offsetWidth;
        el.classList.add('in');
        setTimeout(function(){{el.classList.remove('actor-gal-enter','in');el.style.animationDelay='';}},(0.55+delay)*1000);
    }});
}}
var ACTOR_TAB_MAP={{'overview':'tab-info','info':'tab-info','tab-info':'tab-info','videos':'tab-video','video':'tab-video','tab-video':'tab-video','gallery':'tab-gallery','tab-gallery':'tab-gallery'}};
function activateActorTab(name,init){{
    var tId=ACTOR_TAB_MAP[String(name||'').toLowerCase()]||'tab-info';
    if(tId!=='tab-video'&&selMode)toggleSelMode(false);
    document.querySelectorAll('.actor-panel').forEach(function(p){{p.classList.toggle('active',p.id===tId);}});
    var activeTabName='overview';
    document.querySelectorAll('.actor-tab').forEach(function(t){{
        var panelId=ACTOR_TAB_MAP[t.dataset.tab]||'tab-info';
        var on=panelId===tId;
        t.classList.toggle('active',on);
        t.setAttribute('aria-pressed',String(on));
        t.setAttribute('aria-selected',String(on));
        t.tabIndex=on?0:-1;
        if(on&&t.dataset.tab)activeTabName=t.dataset.tab;
    }});
    if(tId==='tab-video'){{
        if(!actVideosLoaded)triggerActorSearchAjax();
        else staggerCards(document.getElementById('actor_video_results'));
    }}
    if(tId==='tab-gallery')staggerActorGallery();
    if(!init&&window.history&&window.history.replaceState){{
        try{{var u=new URL(location.href);u.searchParams.set('tab',activeTabName);history.replaceState(null,'',u.pathname+u.search);}}catch(_){{}}
    }}
}}
function searchActorTag(tag){{
    var aq=document.getElementById('actor_movie_q'),ac=document.getElementById('actMovieClear');
    if(aq){{aq.value=String(tag||'');if(ac)ac.hidden=!aq.value.length;}}
    resetActorSearchPage();
    activateActorTab('videos');
    triggerActorSearchAjax();
    scrollActorVideoTop();
}}
function switchActorTab(ev,tId){{
    var name=(ev&&ev.currentTarget&&ev.currentTarget.dataset&&ev.currentTarget.dataset.tab)||tId;
    activateActorTab(name);
}}
function openActorEditModal(){{document.getElementById('actorEditModal').classList.add('open');}}
function closeActorEditModal(){{var m=document.getElementById('actorEditModal'),f=m&&m.querySelector('form[data-profile-form]');if(f&&f.dataset.saving==='true'){{showToast('Please wait for the save to finish.');return;}}if(m)m.classList.remove('open');}}
function resetActorSearchPage(){{actCurPage=1;actOffset=0;actOffHist=[];actPageGroups={{}};}}
async function triggerActorSearchAjax(fresh){{
    if(fresh&&typeof actOffset==='string'&&/^g[12]_/.test(actOffset)){{actOffset=0;actCurPage=1;actOffHist=[];actPageGroups={{}};}}
    var q=document.getElementById('actor_movie_q').value.trim(),grid=document.getElementById('actor_video_results');
    var resInfo=document.getElementById('actorResInfo'),resCount=document.getElementById('actorResCount');
    var wrap=document.getElementById('actMovieWrap');var myReq=++actMovieReqId;
    if(!actVideosLoaded&&grid&&!grid.children.length)grid.innerHTML='<div class="empty"><p>Loading linked media…</p></div>';
    var loadTimer=setTimeout(function(){{if(myReq!==actMovieReqId)return;if(wrap)wrap.classList.add('loading');}},150);
    try{{
        var url='/api/actor/search?q='+encodeURIComponent(q)+'&offset='+encodeURIComponent(actOffset)+'&col='+actCol+'&mode='+actMode+'&group=1&gf='+actGF+'&id={actor_id}'+(fresh?'&fresh=1':'');
        var r=await fetch(url,{{cache:'no-store'}});
        if(myReq!==actMovieReqId){{clearTimeout(loadTimer);return;}}
        clearTimeout(loadTimer);if(wrap)wrap.classList.remove('loading');
        var d=null;try{{d=await r.json();}}catch(_){{d=null;}}
        if(myReq!==actMovieReqId)return;
        if(!r.ok||(d&&d.error))throw new Error((d&&d.error)||('HTTP '+r.status));
        actVideosLoaded=true;
        if(typeof d.is_admin==='boolean')isAdminView=d.is_admin;
        pMode=actMode;
        grid.className='res-grid mode-'+actMode+(selMode?' sel-mode':'');
        if(!d.results||!d.results.length){{
            actNextOffset=d.next_offset||'';actPageGroups[actOffset]=[];
            if(resInfo)resInfo.style.display='none';
            grid.innerHTML='<div class="empty"><p>No video assets matching filters found.</p>'+(actNextOffset?'<p>More results may be on the next page.</p>':'')+'</div>';
            document.getElementById('actor_page_box').style.display=(actNextOffset||actCurPage>1)?'flex':'none';
            document.getElementById('actor_pBtn').disabled=(actCurPage<=1);
            document.getElementById('actor_nBtn').disabled=!actNextOffset;
            document.getElementById('actor_pgInfo').textContent='Page '+actCurPage;
            renderSelBar();return;
        }}
        var earlier={{}};
        actOffHist.forEach(function(oo){{(actPageGroups[oo]||[]).forEach(function(k){{earlier[k]=1;}});}});
        var rows=d.results.filter(function(f){{return !(f.group&&earlier[f.key]);}});
        actPageGroups[actOffset]=rows.filter(function(f){{return f.group;}}).map(function(f){{return f.key;}});
        if(resInfo&&resCount){{
            var gCount=rows.filter(function(f){{return f.group;}}).length,fCount=rows.length-gCount;
            var parts=[];if(gCount)parts.push(gCount+(gCount===1?' group':' groups'));if(fCount)parts.push(fCount+(fCount===1?' file':' files'));
            resCount.textContent=parts.length?(parts.join(' · ')+(q?' for "'+q+'"':'')):'';
            resInfo.style.display=parts.length?'flex':'none';
        }}
        var h='';rows.forEach(function(f){{h+=f.group?groupHtml(f):cardHtml(f,false);}});
        grid.innerHTML=h;renderSelBar();staggerCards(grid);
        actNextOffset=d.next_offset||'';
        document.getElementById('actor_page_box').style.display='flex';
        document.getElementById('actor_pBtn').disabled=(actCurPage<=1);
        document.getElementById('actor_nBtn').disabled=!actNextOffset;
        document.getElementById('actor_pgInfo').textContent='Page '+actCurPage;
    }}catch(e){{
        clearTimeout(loadTimer);if(myReq!==actMovieReqId)return;if(wrap)wrap.classList.remove('loading');
        if(resInfo)resInfo.style.display='none';
        grid.innerHTML='<div class="empty"><p>Could not load linked videos. Please retry.</p></div>';
    }}
}}
var actorAvatarInProgress=false;async function updateActorAvatar(aid,input){{var field=input,f=field&&field.files[0];if(!f)return;if(actorAvatarInProgress){{field.value='';showToast('Please wait for the current photo upload.');return;}}actorAvatarInProgress=true;var save=document.querySelector('#actorEditModal button[type=submit]'),oldLabel=save&&save.textContent;if(save){{save.disabled=true;save.textContent='Uploading photo…';}}var fd=new FormData();fd.append('actor_id',aid);fd.append('photo',f);field.disabled=true;try{{var r=await fetch('/api/actor/update_avatar',{{method:'POST',body:fd}}),d=await r.json();if(!r.ok||!d.success)throw new Error(d.error||'Upload failed');var src='/api/actor/photo?id='+encodeURIComponent(aid)+'&v='+encodeURIComponent(d.photo_revision||Date.now());document.getElementById('actorMasterAvatarImage').src=src;var preview=document.getElementById('actorEditPreview');if(preview)preview.src=src;showToast('Profile photo updated.');}}catch(e){{showToast(e.message||'Network update error','error');}}finally{{field.value='';field.disabled=false;actorAvatarInProgress=false;if(save){{save.disabled=false;save.textContent=oldLabel;}}}}}}
async function deleteGalleryImage(aid,idx,e){{if(e)e.stopPropagation();if(!confirm("Delete this photo from gallery permanently?"))return;try{{var r=await fetch('/api/actor/gallery_delete',{{method:'POST',body:JSON.stringify({{actor_id:aid,index:idx}}),headers:{{'Content-Type':'application/json'}}}}),d=await r.json();if(d.success){{alert("Image removed from gallery!");window.location.reload();}}else alert(d.error||"Delete failed!");}}catch(e){{alert("Network deletion error!");}}}}
async function deleteActorProfile(id){{if(!confirm("Are you sure you want to permanently delete this profile?"))return;try{{var r=await fetch('/api/actor/delete?id='+id,{{method:'POST'}}),d=await r.json();if(d.success){{alert("Profile deleted successfully!");window.location.href='/actors';}}else alert(d.error||"Deletion failed!");}}catch(e){{alert("Network communication error!");}}}}
function scrollActorVideoTop(){{var bar=document.querySelector('.actor-tab-bar')||document.getElementById('tab-video');if(bar&&bar.scrollIntoView)bar.scrollIntoView({{behavior:'smooth',block:'start'}});}}
function actorPageNext(){{if(actNextOffset){{actOffHist.push(actOffset);actCurPage++;actOffset=actNextOffset;triggerActorSearchAjax();scrollActorVideoTop();}}}}
function actorPagePrev(){{if(actCurPage>1){{actCurPage--;actOffset=actOffHist.length?actOffHist.pop():0;triggerActorSearchAjax();scrollActorVideoTop();}}}}
(function(){{
    var aq=document.getElementById('actor_movie_q'),ac=document.getElementById('actMovieClear');
    function syncActClear(){{if(ac&&aq)ac.hidden=!aq.value.length;}}
    if(ac&&aq){{
        ac.addEventListener('click',function(){{
            clearTimeout(actMovieLiveTimer);
            aq.value='';syncActClear();aq.focus();
            resetActorSearchPage();triggerActorSearchAjax();
        }});
    }}
    if(aq){{
        aq.addEventListener('keydown',function(e){{if(e.key==='Enter'){{clearTimeout(actMovieLiveTimer);resetActorSearchPage();triggerActorSearchAjax();}}}});
        aq.addEventListener('input',function(){{syncActClear();clearTimeout(actMovieLiveTimer);actMovieLiveTimer=setTimeout(function(){{resetActorSearchPage();triggerActorSearchAjax();}},350);}});
    }}
    syncActClear();
    document.querySelectorAll('#tab-gallery img.gallery-item').forEach(function(im){{if(im.complete&&im.naturalWidth)im.classList.add('on');}});
    var initTab=new URLSearchParams(location.search).get('tab');
    if(initTab)activateActorTab(initTab,true);
}})();
var actMovieLiveTimer;'''

    css_js_minified = actor_page_markup + f"<script>{GROUP_ENGINE_JS}{actor_page_js}</script>"

    return build_page(
        f"{actor_name} - Directory Profile",
        DIRECTORY_FILTER_CSS + SEARCH_PANEL_CSS + GROUP_CARD_CSS + ACTOR_FORM_CSS + css_js_minified + PROFILE_FORM_JS,
        "",
        "actors",
        role,
    )

# ─────────────────────────────────────────────────────────
# ⚙️ PROFILE PAGE: INTERNAL FILE SEARCH API
# ─────────────────────────────────────────────────────────
@actor_routes.get('/api/actor/search')
async def api_actor_search_handler(req):
    role, tg_id = await get_auth(req)
    if not role or not await require_active_plan(role, tg_id):
        return web.json_response({"error": "Unauthorized"}, status=403, dumps=fast_json)
    if role == "admin" and req.query.get("fresh") == "1":
        _invalidate_search_caches()

    actor_id, q_custom = req.query.get("id"), req.query.get("q", "").strip()
    off = req.query.get("offset", "0")
    col = req.query.get("col", "all").lower()
    mode = req.query.get("mode", DEFAULT_MEDIA_MODE).lower()
    want_group = req.query.get("group", "1") == "1"
    gf = req.query.get("gf", "all").lower()

    if not actor_id:
        return web.json_response({"results": [], "next_offset": "", "is_admin": role == "admin"}, dumps=fast_json)
    if not ObjectId.is_valid(actor_id):
        return web.json_response({"error": "Invalid profile ID"}, status=400, dumps=fast_json)
    actor = await actors.find_one({"_id": ObjectId(actor_id)})
    if not actor:
        return web.json_response({"results": [], "next_offset": "", "is_admin": role == "admin"}, dumps=fast_json)

    tags_list = actor.get("tags", [])
    search_query, final_tags = (q_custom, []) if q_custom else (tags_list[0] if tags_list else "", tags_list)
    if not search_query:
        return web.json_response({"results": [], "next_offset": "", "is_admin": role == "admin"}, dumps=fast_json)

    try:
        results_list, next_offset = await actor_search_page(
            actor_id, search_query, final_tags, col, off, MAX_WEB_RESULTS, mode, gf, want_group
        )
    except ValueError:
        return web.json_response({"error": "Invalid or expired pagination cursor. Start the search again."}, status=400, dumps=fast_json)
    except _GroupCursorLimitError:
        return web.json_response({"error": "Too many results to continue. Please narrow your search."}, status=400, dumps=fast_json)
    except _GroupCursorStorageError:
        return web.json_response({"error": "Pagination is temporarily unavailable. Please try again."}, status=503, dumps=fast_json)
    except Exception:
        return web.json_response({"error": "Search is temporarily unavailable."}, status=503, dumps=fast_json)

    return web.json_response({"results": results_list, "next_offset": next_offset, "is_admin": role == "admin"}, dumps=fast_json)

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
            msg = await temp.BOT.send_photo(chat_id=MEDIA_STORAGE_CHANNEL, photo=img_buffer)
            
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
                msg = await temp.BOT.send_photo(chat_id=MEDIA_STORAGE_CHANNEL, photo=img_buffer)

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
