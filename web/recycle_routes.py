"""Admin-only Recycle Bin for deleted media files.

Deleted file documents are moved to a separate ``RecycleBin`` collection, so
the normal search paths (bot PM/group, the web catalogue and the mini app)
cannot return them. Only an authenticated admin can list, restore or purge
these records here.
"""
from aiohttp import web

from database.ia_filterdb import (
    get_recycle_original,
    list_recycle_files,
    purge_recycle_file,
    recycle_file_count,
    restore_recycle_file,
)
from utils import get_size
from web.web_assets import (
    DIRECTORY_FILTER_CSS,
    build_page,
    fast_json,
    get_auth,
)

recycle_routes = web.RouteTableDef()

_CSS = """<style>
.rb-page{max-width:1240px;margin:0 auto;padding:34px 4% 70px;color:var(--text)}
.rb-page *{box-sizing:border-box}
.rb-head{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;margin-bottom:22px}
.rb-eyebrow{font-size:10px;font-weight:900;letter-spacing:1.5px;text-transform:uppercase;color:var(--accent);margin-bottom:7px}
.rb-title{font-size:clamp(28px,4vw,40px);line-height:1.05;letter-spacing:-1.2px;margin:0 0 7px}
.rb-sub{font-size:13px;line-height:1.55;color:var(--muted);max-width:680px;margin:0}
.rb-headside{display:flex;align-items:center;gap:9px;flex-wrap:wrap;justify-content:flex-end}
.rb-count{font-size:12px;font-weight:800;color:var(--muted);background:var(--bg3);border:1px solid var(--border);padding:8px 12px;border-radius:999px;white-space:nowrap}
.rb-back{display:inline-flex;align-items:center;gap:6px;text-decoration:none;color:var(--text);background:var(--bg3);border:1px solid var(--border);padding:9px 13px;border-radius:9px;font-size:12px;font-weight:800;transition:.15s}
.rb-back:hover{border-color:var(--accent);color:var(--accent)}
.rb-toolbar{display:flex;gap:8px;background:var(--card);border:1px solid var(--border);border-radius:12px;padding:10px;margin-bottom:10px}
.rb-search{flex:1;min-width:0;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font:inherit;font-size:13px;padding:11px 13px;outline:none}
.rb-search:focus{border-color:var(--accent)}
.rb-filters{display:flex;gap:8px;margin:0 0 12px}
.rb-filters .cdd-wrap{flex:1;min-width:0;font-size:13px}
.rb-filters .cdd-wrap.open{border-color:var(--accent)}
.rb-filters .cdd-wrap.open .cdd-menu{display:block}
.rb-filters .cdd-btn{flex:1;min-width:0;padding:0;border:0;background:none;color:inherit;font:inherit;text-align:left;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;cursor:pointer}
.rb-filters .cdd-btn:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:4px}
.rb-filters .cdd-item{display:block;width:100%;background:none;border:0;border-bottom:1px solid var(--border);color:var(--text);font:inherit;text-align:left;cursor:pointer}
.rb-filters .cdd-item:last-child{border-bottom:0}
.rb-filters .cdd-item:hover{background:var(--bg3);color:var(--accent)}
.rb-filters .cdd-item.selected{color:var(--accent)}
.rb-btn{border:1px solid var(--border);border-radius:8px;background:var(--bg3);color:var(--text);font:inherit;font-size:12px;font-weight:800;padding:10px 14px;cursor:pointer;transition:.15s}
.rb-btn:hover{border-color:var(--accent);color:var(--accent)}
.rb-btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.rb-btn.primary:hover{background:var(--accent-hover);border-color:var(--accent-hover);color:#fff}
.rb-status{min-height:20px;font-size:12px;line-height:1.5;color:var(--muted);margin:4px 2px 12px}
.rb-status.error{color:#e75a64}
.rb-grid{display:grid;grid-template-columns:1fr;gap:10px}
@media(min-width:720px){.rb-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(min-width:1120px){.rb-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
.rb-card{position:relative;display:flex;gap:12px;min-width:0;background:var(--card);border:1px solid var(--border);border-radius:11px;padding:11px;transition:border-color .15s}
.rb-card:hover{border-color:var(--muted)}
.rb-card.rb-active{z-index:40;border-color:var(--accent)}
.rb-thumb-wrap{position:relative;flex:none;width:92px;height:72px;border-radius:8px;overflow:hidden;background:var(--bg3);border:1px solid var(--border)}
.rb-thumb{width:100%;height:100%;display:grid;place-items:center;color:var(--muted);font-size:22px}
.rb-thumb img{width:100%;height:100%;object-fit:cover;display:block}
.rb-thumb-trigger{position:absolute;inset:0;z-index:4;width:100%;height:100%;border:0;padding:0;background:transparent;cursor:pointer}
.rb-thumb-trigger::after{content:'⋮';position:absolute;top:4px;right:4px;width:22px;height:22px;display:grid;place-items:center;border-radius:6px;background:rgba(0,0,0,.62);color:#fff;font-size:16px;line-height:1;opacity:0;transition:opacity .15s;pointer-events:none}
.rb-thumb-wrap:hover .rb-thumb-trigger::after,.rb-card.rb-active .rb-thumb-trigger::after{opacity:1}
.rb-thumb-trigger:focus-visible{outline:3px solid var(--accent);outline-offset:-4px}
.rb-body{position:relative;min-width:0;flex:1;display:flex;flex-direction:column;gap:5px}
.rb-name{display:-webkit-box;width:100%;padding:0;border:0;background:none;color:var(--text);font:inherit;font-size:13px;font-weight:800;line-height:1.35;text-align:left;cursor:pointer;overflow-wrap:anywhere;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.rb-name:hover{color:var(--accent);text-decoration:underline;text-underline-offset:2px}
.rb-name:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:3px}
.rb-more{display:none;position:absolute;right:0;top:0;z-index:6;width:28px;height:26px;align-items:center;justify-content:center;border:1px solid var(--border);border-radius:7px;background:var(--bg3);color:var(--text);font:inherit;font-size:17px;font-weight:900;line-height:1;cursor:pointer}
.rb-more:hover{border-color:var(--accent);color:var(--accent)}
.rb-more:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.rb-meta{display:flex;flex-wrap:wrap;gap:5px;align-items:center;font-size:10px;font-weight:700;color:var(--muted)}
.rb-chip{background:var(--bg3);border:1px solid var(--border);border-radius:5px;padding:2px 6px;white-space:nowrap}
.rb-chip.primary{color:#4ade80;border-color:rgba(34,197,94,.5)}
.rb-chip.cloud{color:#93c5fd;border-color:rgba(96,165,250,.5)}
.rb-chip.archive{color:#fdba74;border-color:rgba(251,146,60,.5)}
.rb-date{font-size:10px;color:var(--muted);line-height:1.4}
.rb-actions{display:none;position:absolute;top:8px;right:8px;z-index:45;min-width:172px;flex-direction:column;gap:5px;padding:6px;background:var(--bg2);border:1px solid var(--accent);border-radius:10px;box-shadow:0 12px 30px rgba(0,0,0,.32)}
.rb-card.rb-active .rb-actions{display:flex}
.rb-actions .rb-btn{width:100%;padding:9px 11px;font-size:11px;text-align:left}
.rb-btn.restore{color:#22c55e;border-color:rgba(34,197,94,.45);background:rgba(34,197,94,.08)}
.rb-btn.restore:hover{background:rgba(34,197,94,.16);border-color:#22c55e;color:#22c55e}
.rb-btn.purge{color:#ff8b93;border-color:rgba(229,9,20,.45);background:rgba(229,9,20,.08)}
.rb-btn.purge:hover{background:rgba(229,9,20,.18);border-color:var(--accent);color:#fff}
.rb-empty{grid-column:1/-1;text-align:center;padding:64px 20px;color:var(--muted);border:1px dashed var(--border);border-radius:12px;background:var(--card)}
.rb-empty b{display:block;color:var(--text);font-size:15px;margin-bottom:6px}
.rb-pager{display:flex;align-items:center;justify-content:center;gap:12px;margin-top:20px}
.rb-pageinfo{font-size:12px;font-weight:800;color:var(--muted);min-width:90px;text-align:center}
.rb-pager .rb-btn:disabled{opacity:.4;cursor:not-allowed}
.rb-grid.mode-text{grid-template-columns:1fr}
.rb-grid.mode-text .rb-card{padding:12px 14px}
.rb-grid.mode-text .rb-thumb-wrap{display:none}
.rb-grid.mode-text .rb-body{padding-right:34px}
.rb-grid.mode-text .rb-more{display:inline-flex}
.rb-grid.mode-text .rb-actions{top:42px}
@media(max-width:560px){.rb-page{padding:25px 16px 55px}.rb-head{align-items:flex-start;flex-direction:column}.rb-headside{justify-content:flex-start}.rb-search{font-size:13px}.rb-thumb-wrap{width:78px;height:64px}.rb-actions{left:8px;right:8px;top:auto;bottom:8px;min-width:0;flex-direction:row}.rb-actions .rb-btn{flex:1;min-width:0;width:auto}.rb-grid.mode-text .rb-actions{top:auto}}
@media(prefers-reduced-motion:reduce){.rb-page *{transition:none!important}}
</style>"""

_JS = """<script>
(function(){
  var offset=0,limit=24,total=0,query='',collection='all',busy=false,pending=false;
  var grid=document.getElementById('rbGrid'),status=document.getElementById('rbStatus');
  var count=document.getElementById('rbCount'),page=document.getElementById('rbPage');
  var prev=document.getElementById('rbPrev'),next=document.getElementById('rbNext');
  var search=document.getElementById('rbSearch');
  var colLabel=document.getElementById('rbColLabel'),colBtn=document.getElementById('rbColBtn');
  var modeLabel=document.getElementById('rbModeLabel'),modeBtn=document.getElementById('rbModeBtn');
  var mode=(typeof MediaView!=='undefined')?MediaView.get('__DEFAULT_VIEW_MODE__'):'__DEFAULT_VIEW_MODE__';
  function esc(v){return String(v==null?'':v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
  function setStatus(text,error){status.textContent=text||'';status.classList.toggle('error',!!error);}
  function dateText(ts){if(!ts)return 'Unknown date';try{return new Date(Number(ts)*1000).toLocaleString();}catch(e){return 'Unknown date';}}
  function closeFilterMenus(except){
    document.querySelectorAll('.rb-filters .cdd-wrap.open').forEach(function(w){
      if(w===except)return;
      w.classList.remove('open');
      var b=w.querySelector('.cdd-btn');if(b)b.setAttribute('aria-expanded','false');
    });
  }
  function closeMenus(except){
    document.querySelectorAll('.rb-card.rb-active').forEach(function(c){
      if(c===except)return;
      c.classList.remove('rb-active');
      c.querySelectorAll('[data-menu]').forEach(function(b){b.setAttribute('aria-expanded','false');});
    });
  }
  function setMode(value,save){
    mode=(value==='text')?'text':'poster';
    grid.className='rb-grid mode-'+mode;
    modeLabel.textContent=mode==='text'?'📄 Text':'🖼️ Poster';
    modeBtn.setAttribute('aria-label','View mode filter: '+(mode==='text'?'Text':'Poster'));
    document.querySelectorAll('#rbModeMenu .cdd-item').forEach(function(i){
      i.classList.toggle('selected',i.dataset.val===mode);
    });
    if(save&&typeof MediaView!=='undefined')MediaView.set(mode);
  }
  function selectFilter(menu,val){
    menu.querySelectorAll('.cdd-item').forEach(function(i){i.classList.toggle('selected',i.dataset.val===val);});
  }
  function thumb(item){
    var u=String(item.thumb||''),inner;
    if(/^(https?:\/\/|\/)/i.test(u))inner='<img src="'+esc(u)+'" alt="" loading="lazy" onerror="this.parentNode.textContent=&#39;🎬&#39;">';
    else inner='🎬';
    return '<div class="rb-thumb-wrap"><div class="rb-thumb">'+inner+'</div>'+
      '<button type="button" class="rb-thumb-trigger" data-menu aria-expanded="false" aria-label="Show restore and delete options for this file"></button></div>';
  }
  function card(item){
    var col=String(item.collection||'primary').toLowerCase(),gid= String(item.group_id||'');
    var playable=item.playable?'1':'0';
    return '<article class="rb-card" data-id="'+esc(item.id)+'">'+thumb(item)+
      '<div class="rb-body">'+
      '<button type="button" class="rb-name" data-play data-id="'+esc(item.id)+'" data-name="'+esc(item.file_name||'Deleted file')+'" data-playable="'+playable+'" title="'+esc(item.file_name||'Deleted file')+'" aria-label="Play '+esc(item.file_name||'this file')+'">'+esc(item.file_name||'Deleted file')+'</button>'+
      '<button type="button" class="rb-more" data-menu aria-expanded="false" aria-label="Show restore and delete options">&#8942;</button>'+
      '<div class="rb-meta"><span class="rb-chip '+esc(col)+'">'+esc(col.toUpperCase())+'</span>'+
      (item.file_size?'<span class="rb-chip">'+esc(item.file_size)+'</span>':'')+
      (gid?'<span class="rb-chip">GROUP #'+esc(gid)+'</span>':'')+'</div>'+
      '<div class="rb-date">Deleted '+esc(dateText(item.deleted_at))+(item.deleted_by?' · by #'+esc(item.deleted_by):'')+'</div>'+
      '<div class="rb-actions" role="menu" aria-label="Recycle Bin actions">'+
      '<button type="button" class="rb-btn restore" role="menuitem" data-action="restore" data-id="'+esc(item.id)+'">♻️ Restore</button>'+
      '<button type="button" class="rb-btn purge" role="menuitem" data-action="purge" data-id="'+esc(item.id)+'">🗑 Delete forever</button></div>'+
      '</div></article>';
  }
  async function load(){
    if(busy){pending=true;return;}
    busy=true;pending=false;
    setStatus('Loading Recycle Bin…');prev.disabled=true;next.disabled=true;
    try{
      var r=await fetch('/api/recycle/list?offset='+offset+'&limit='+limit+'&q='+encodeURIComponent(query)+'&col='+encodeURIComponent(collection),{cache:'no-store'});
      var d=await r.json();
      if(!r.ok)throw new Error(d.error||'Could not load the Recycle Bin.');
      total=Number(d.total)||0;
      count.textContent=total+(total===1?' item':' items');
      page.textContent='Page '+(Math.floor(offset/limit)+1);
      grid.innerHTML=(d.items&&d.items.length)?d.items.map(card).join(''):'<div class="rb-empty"><b>'+(query||collection!=='all'?'No files match these filters':'Recycle Bin is empty')+'</b>Deleted files will appear here for admin restore.</div>';
      prev.disabled=offset<=0;next.disabled=offset+limit>=total;
      setStatus('');
    }catch(e){setStatus(e.message||'Could not load the Recycle Bin.',true);grid.innerHTML='';}
    finally{busy=false;if(pending){pending=false;load();}}
  }
  async function post(path,payload){
    var r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    var d=await r.json().catch(function(){return {};});
    if(!r.ok||!d.success)throw new Error(d.error||'The operation failed.');
    return d;
  }
  function toggleMenu(card,trigger){
    if(!card)return;
    var was=card.classList.contains('rb-active');
    closeMenus(card);
    if(was){card.classList.remove('rb-active');trigger.setAttribute('aria-expanded','false');return;}
    card.classList.add('rb-active');trigger.setAttribute('aria-expanded','true');
  }
  function pickFilter(item){
    var wrap=item.closest('.cdd-wrap'),which=wrap&&wrap.dataset.filter,val=item.dataset.val||'';
    if(which==='col'){
      collection=val;colLabel.textContent=item.dataset.label||val;colBtn.setAttribute('aria-label','Collection filter: '+(item.dataset.label||val));
      selectFilter(document.getElementById('rbColMenu'),val);offset=0;closeFilterMenus();load();return;
    }
    setMode(val,true);closeFilterMenus();
  }
  grid.addEventListener('click',async function(event){
    closeFilterMenus();
    var trigger=event.target.closest('[data-menu]');
    if(trigger){event.preventDefault();event.stopPropagation();toggleMenu(trigger.closest('.rb-card'),trigger);return;}
    var name=event.target.closest('[data-play]');
    if(name){
      event.preventDefault();closeMenus();
      if(name.dataset.playable!=='1'){setStatus('This record has no Telegram media reference to play.',true);return;}
      if(typeof openInlinePlayer==='function')openInlinePlayer(name.dataset.id,name.dataset.name||name.textContent,true);
      else setStatus('The video player is not available on this page.',true);
      return;
    }
    var button=event.target.closest('button[data-action]');if(!button||busy)return;
    event.preventDefault();event.stopPropagation();
    var action=button.dataset.action,id=button.dataset.id;
    var question=action==='restore'?'Restore this file to the library?':'Permanently delete this file from the Recycle Bin? This cannot be undone.';
    if(!confirm(question))return;
    closeMenus();
    button.disabled=true;setStatus(action==='restore'?'Restoring file…':'Deleting file permanently…');
    try{
      var d=await post(action==='restore'?'/api/recycle/restore':'/api/recycle/purge',{id:id});
      var message=action==='restore'?(d.already?'This file is already active in '+String(d.collection||'').toUpperCase()+'.':'File restored successfully.'):'File permanently deleted.';
      await load();
      if(!status.classList.contains('error'))setStatus(message,false);
    }catch(e){setStatus(e.message||'The operation failed.',true);button.disabled=false;}
  });
  document.addEventListener('click',function(event){
    closeMenus();
    var item=event.target.closest('.rb-filters .cdd-item');
    if(item){event.preventDefault();pickFilter(item);return;}
    var wrap=event.target.closest('.rb-filters .cdd-wrap');
    if(wrap){
      event.preventDefault();var was=wrap.classList.contains('open');closeFilterMenus(wrap);
      if(!was){wrap.classList.add('open');var b=wrap.querySelector('.cdd-btn');if(b)b.setAttribute('aria-expanded','true');}
      return;
    }
    closeFilterMenus();
    if(!event.target.closest('.rb-card'))closeMenus();
  });
  document.addEventListener('keydown',function(event){
    if(event.key==='Escape'){closeFilterMenus();closeMenus();}
  });
  var searchTimer;
  search.addEventListener('input',function(){
    clearTimeout(searchTimer);
    searchTimer=setTimeout(function(){query=search.value.trim();offset=0;load();},300);
  });
  search.addEventListener('keydown',function(event){
    if(event.key==='Enter'){event.preventDefault();clearTimeout(searchTimer);query=search.value.trim();offset=0;load();}
  });
  prev.addEventListener('click',function(){if(offset>0&&!busy){offset=Math.max(0,offset-limit);load();}});
  next.addEventListener('click',function(){if(!busy&&offset+limit<total){offset+=limit;load();}});
  if(typeof MediaView!=='undefined'&&MediaView.subscribe){
    MediaView.subscribe(function(value){if(value==='text'||value==='poster')setMode(value,false);});
  }
  setMode(mode,false);
  load();
})();
</script>"""

def _page_body():
    # Recycle items are identified visually; start in Poster mode like the old
    # recycle cards, while still honoring a saved Text preference below.
    default_mode = "poster"
    mode_label = "🖼️ Poster"
    mode_selected = " selected"
    return (
        DIRECTORY_FILTER_CSS
        + _CSS
        + '<main class="rb-page">'
        '<header class="rb-head"><div><div class="rb-eyebrow">Admin workspace</div>'
        '<h1 class="rb-title">Recycle Bin</h1>'
        '<p class="rb-sub">Deleted media records are kept here for admin restore. '
        'They are hidden from bot searches, the web catalogue and the mini app.</p></div>'
        '<div class="rb-headside"><span class="rb-count" id="rbCount">Loading…</span>'
        '<a class="rb-back" href="/dashboard">← Back to library</a></div></header>'
        '<div class="rb-toolbar"><input class="rb-search" id="rbSearch" type="search" '
        'placeholder="Search deleted file names…" autocomplete="off" aria-label="Search deleted files"></div>'
        '<div class="rb-filters">'
        '<div class="cdd-wrap" data-filter="col" id="rbColWrap">'
        '<button type="button" class="cdd-btn" id="rbColBtn" aria-label="Collection filter: All" aria-expanded="false" aria-controls="rbColMenu">'
        '<span id="rbColLabel">All</span></button><span class="cdd-arrow" aria-hidden="true">▼</span>'
        '<div class="cdd-menu" id="rbColMenu">'
        '<button type="button" class="cdd-item selected" data-val="all" data-label="All">All</button>'
        '<button type="button" class="cdd-item" data-val="primary" data-label="🟢 Primary">🟢 Primary</button>'
        '<button type="button" class="cdd-item" data-val="cloud" data-label="🔵 Cloud">🔵 Cloud</button>'
        '<button type="button" class="cdd-item" data-val="archive" data-label="🟠 Archive">🟠 Archive</button>'
        '</div></div>'
        '<div class="cdd-wrap" data-filter="mode" id="rbModeWrap">'
        '<button type="button" class="cdd-btn" id="rbModeBtn" aria-label="View mode filter: ' + ("Text" if default_mode == "text" else "Poster") + '" aria-expanded="false" aria-controls="rbModeMenu">'
        '<span id="rbModeLabel">' + mode_label + '</span></button><span class="cdd-arrow" aria-hidden="true">▼</span>'
        '<div class="cdd-menu" id="rbModeMenu">'
        '<button type="button" class="cdd-item' + (mode_selected if default_mode == "poster" else "") + '" data-val="poster" data-label="🖼️ Poster">🖼️ Poster</button>'
        '<button type="button" class="cdd-item' + (mode_selected if default_mode == "text" else "") + '" data-val="text" data-label="📄 Text">📄 Text</button>'
        '</div></div></div>'
        '<div class="rb-status" id="rbStatus" role="status" aria-live="polite"></div>'
        '<div class="rb-grid mode-' + default_mode + '" id="rbGrid"></div>'
        '<div class="rb-pager"><button type="button" class="rb-btn" id="rbPrev" disabled>Previous</button>'
        '<span class="rb-pageinfo" id="rbPage">Page 1</span>'
        '<button type="button" class="rb-btn" id="rbNext" disabled>Next</button></div>'
        '</main>'
        + _JS.replace("__DEFAULT_VIEW_MODE__", default_mode)
    )


@recycle_routes.get('/admin/recycle')
async def recycle_page(req):
    role, _ = await get_auth(req)
    if role != 'admin':
        return web.HTTPFound('/dashboard')
    return build_page('Recycle Bin - Fast Finder', _page_body(), '', 'recycle', role)


@recycle_routes.get('/api/recycle/list')
async def api_recycle_list(req):
    role, _ = await get_auth(req)
    if role != 'admin':
        return web.json_response({'error': 'Core Admin Authorization Required!'},
                                 status=403, dumps=fast_json)
    try:
        offset = max(0, int(req.query.get('offset', 0)))
        limit = max(1, min(int(req.query.get('limit', 24)), 100))
    except (TypeError, ValueError):
        return web.json_response({'error': 'Invalid page.'}, status=400, dumps=fast_json)
    q = str(req.query.get('q', '') or '').strip()[:120]
    collection = str(req.query.get('col', 'all') or 'all').lower()
    if collection not in ('all', 'primary', 'cloud', 'archive'):
        collection = 'all'
    total, docs = await list_recycle_files(q, offset, limit, collection)
    items = []
    for doc in docs:
        original = doc.get('original') or {}
        raw_size = original.get('file_size') or 0
        try:
            size = get_size(raw_size) if raw_size else ''
        except (TypeError, ValueError):
            size = ''
        items.append({
            'id': str(doc.get('_id', '')),
            'file_id': str(doc.get('file_id', '')),
            'file_name': str(original.get('file_name') or doc.get('file_name') or 'Deleted file'),
            'file_size': size,
            'collection': str(doc.get('source_col') or ''),
            'deleted_at': int(doc.get('deleted_at') or 0),
            'deleted_by': doc.get('deleted_by'),
            'group_id': str(original.get('group_id') or ''),
            'thumb': str(original.get('thumb_url') or ''),
            'playable': bool(str(original.get('file_ref') or '').strip()),
        })
    return web.json_response({'total': total, 'offset': offset, 'limit': limit,
                              'items': items}, dumps=fast_json,
                             headers={'Cache-Control': 'no-store'})


@recycle_routes.post('/api/recycle/stream')
async def api_recycle_stream(req):
    """Prepare an inline player URL for a deleted file, admin-only.

    The original Telegram file reference is read server-side; it is never sent
    to the browser. Restoring is not required just to preview a video.
    """
    role, _ = await get_auth(req)
    if role != 'admin':
        return web.json_response({'error': 'Core Admin Authorization Required!'},
                                 status=403, dumps=fast_json)
    try:
        data = await req.json()
    except Exception:
        return web.json_response({'error': 'Invalid request.'}, status=400, dumps=fast_json)
    if not isinstance(data, dict):
        return web.json_response({'error': 'Invalid request.'}, status=400, dumps=fast_json)
    original = await get_recycle_original(str(data.get('id') or ''))
    if not isinstance(original, dict) or not original:
        return web.json_response({'error': 'This item is no longer in the Recycle Bin.'},
                                 status=404, dumps=fast_json)
    file_ref = str(original.get('file_ref') or '').strip()
    if not file_ref:
        return web.json_response({'error': 'This record has no Telegram media reference to play.'},
                                 status=400, dumps=fast_json)
    try:
        # Lazy import avoids a module cycle: admin routes are registered before
        # search routes in web/__init__.py.
        from web.search_api import _tunnel_stream
        url = await _tunnel_stream(file_ref, 'inline')
    except Exception as e:
        # Telegram may reject an old file reference or the media may be gone.
        from web.search_api import logger as search_logger
        search_logger.warning("Recycle preview failed for %s: %s", data.get('id'), e)
        return web.json_response({'error': 'Telegram could not open this media. It may have expired.'},
                                 status=502, dumps=fast_json)
    return web.json_response({'url': url}, dumps=fast_json, headers={'Cache-Control': 'no-store'})


@recycle_routes.post('/api/recycle/restore')
async def api_recycle_restore(req):
    role, _ = await get_auth(req)
    if role != 'admin':
        return web.json_response({'error': 'Core Admin Authorization Required!'},
                                 status=403, dumps=fast_json)
    try:
        data = await req.json()
    except Exception:
        return web.json_response({'error': 'Invalid request.'}, status=400, dumps=fast_json)
    if not isinstance(data, dict):
        return web.json_response({'error': 'Invalid request.'}, status=400, dumps=fast_json)
    result = await restore_recycle_file(str(data.get('id') or ''))
    if not result.get('ok'):
        return web.json_response({'error': result.get('error') or 'Could not restore.'},
                                 status=404, dumps=fast_json)
    # The active collections changed; drop catalogue/page caches immediately.
    try:
        from web.search_api import _invalidate_search_caches
        _invalidate_search_caches()
    except Exception:
        pass
    return web.json_response({'success': True, 'already': bool(result.get('already')),
                              'collection': result.get('collection') or ''},
                             dumps=fast_json)


@recycle_routes.post('/api/recycle/purge')
async def api_recycle_purge(req):
    role, _ = await get_auth(req)
    if role != 'admin':
        return web.json_response({'error': 'Core Admin Authorization Required!'},
                                 status=403, dumps=fast_json)
    try:
        data = await req.json()
    except Exception:
        return web.json_response({'error': 'Invalid request.'}, status=400, dumps=fast_json)
    if not isinstance(data, dict):
        return web.json_response({'error': 'Invalid request.'}, status=400, dumps=fast_json)
    if not await purge_recycle_file(str(data.get('id') or '')):
        return web.json_response({'error': 'This item is no longer in the Recycle Bin.'},
                                 status=404, dumps=fast_json)
    return web.json_response({'success': True}, dumps=fast_json)


@recycle_routes.get('/api/recycle/count')
async def api_recycle_count(req):
    """Small admin-only count helper for the sidebar/stats integrations."""
    role, _ = await get_auth(req)
    if role != 'admin':
        return web.json_response({'error': 'Core Admin Authorization Required!'},
                                 status=403, dumps=fast_json)
    return web.json_response({'count': await recycle_file_count()}, dumps=fast_json,
                             headers={'Cache-Control': 'no-store'})
