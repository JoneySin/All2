"""Admin-only Recycle Bin for deleted media files.

Deleted file documents are moved to a separate ``RecycleBin`` collection, so
the normal search paths (bot PM/group, the web catalogue and the mini app)
cannot return them. Only an authenticated admin can list, restore or purge
these records here.
"""
from aiohttp import web

from database.ia_filterdb import (
    list_recycle_files,
    purge_recycle_file,
    recycle_file_count,
    restore_recycle_file,
)
from utils import get_size
from web.web_assets import build_page, fast_json, get_auth

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
.rb-toolbar{display:flex;gap:8px;background:var(--card);border:1px solid var(--border);border-radius:12px;padding:10px;margin-bottom:12px}
.rb-search{flex:1;min-width:0;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font:inherit;font-size:13px;padding:11px 13px;outline:none}
.rb-search:focus{border-color:var(--accent)}
.rb-btn{border:1px solid var(--border);border-radius:8px;background:var(--bg3);color:var(--text);font:inherit;font-size:12px;font-weight:800;padding:10px 14px;cursor:pointer;transition:.15s}
.rb-btn:hover{border-color:var(--accent);color:var(--accent)}
.rb-btn.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.rb-btn.primary:hover{background:var(--accent-hover);border-color:var(--accent-hover);color:#fff}
.rb-status{min-height:20px;font-size:12px;line-height:1.5;color:var(--muted);margin:4px 2px 12px}
.rb-status.error{color:#e75a64}
.rb-grid{display:grid;grid-template-columns:1fr;gap:10px}
@media(min-width:720px){.rb-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(min-width:1120px){.rb-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
.rb-card{display:flex;gap:12px;min-width:0;background:var(--card);border:1px solid var(--border);border-radius:11px;padding:11px;transition:border-color .15s}
.rb-card:hover{border-color:var(--muted)}
.rb-thumb{flex:none;width:92px;height:72px;border-radius:8px;overflow:hidden;background:var(--bg3);border:1px solid var(--border);display:grid;place-items:center;color:var(--muted);font-size:22px}
.rb-thumb img{width:100%;height:100%;object-fit:cover;display:block}
.rb-body{min-width:0;flex:1;display:flex;flex-direction:column;gap:5px}
.rb-name{font-size:13px;font-weight:800;line-height:1.35;overflow-wrap:anywhere;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.rb-meta{display:flex;flex-wrap:wrap;gap:5px;align-items:center;font-size:10px;font-weight:700;color:var(--muted)}
.rb-chip{background:var(--bg3);border:1px solid var(--border);border-radius:5px;padding:2px 6px;white-space:nowrap}
.rb-chip.primary{color:#4ade80;border-color:rgba(34,197,94,.5)}
.rb-chip.cloud{color:#93c5fd;border-color:rgba(96,165,250,.5)}
.rb-chip.archive{color:#fdba74;border-color:rgba(251,146,60,.5)}
.rb-date{font-size:10px;color:var(--muted);line-height:1.4}
.rb-actions{display:flex;gap:6px;margin-top:auto;padding-top:5px;flex-wrap:wrap}
.rb-actions .rb-btn{flex:1;padding:8px 9px;font-size:11px;min-width:82px}
.rb-btn.restore{color:#22c55e;border-color:rgba(34,197,94,.45);background:rgba(34,197,94,.08)}
.rb-btn.restore:hover{background:rgba(34,197,94,.16);border-color:#22c55e;color:#22c55e}
.rb-btn.purge{color:#ff8b93;border-color:rgba(229,9,20,.45);background:rgba(229,9,20,.08)}
.rb-btn.purge:hover{background:rgba(229,9,20,.18);border-color:var(--accent);color:#fff}
.rb-empty{grid-column:1/-1;text-align:center;padding:64px 20px;color:var(--muted);border:1px dashed var(--border);border-radius:12px;background:var(--card)}
.rb-empty b{display:block;color:var(--text);font-size:15px;margin-bottom:6px}
.rb-pager{display:flex;align-items:center;justify-content:center;gap:12px;margin-top:20px}
.rb-pageinfo{font-size:12px;font-weight:800;color:var(--muted);min-width:90px;text-align:center}
.rb-pager .rb-btn:disabled{opacity:.4;cursor:not-allowed}
@media(max-width:560px){.rb-page{padding:25px 16px 55px}.rb-head{align-items:flex-start;flex-direction:column}.rb-headside{justify-content:flex-start}.rb-toolbar{flex-wrap:wrap}.rb-search{flex:1 1 100%}.rb-toolbar .rb-btn{flex:1}.rb-thumb{width:78px;height:64px}}
@media(prefers-reduced-motion:reduce){.rb-page *{transition:none!important}}
</style>"""

_JS = """<script>
(function(){
  var offset=0,limit=24,total=0,query='',busy=false;
  var grid=document.getElementById('rbGrid'),status=document.getElementById('rbStatus');
  var count=document.getElementById('rbCount'),page=document.getElementById('rbPage');
  var prev=document.getElementById('rbPrev'),next=document.getElementById('rbNext');
  var search=document.getElementById('rbSearch');
  function esc(v){return String(v==null?'':v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
  function setStatus(text,error){status.textContent=text||'';status.classList.toggle('error',!!error);}
  function dateText(ts){if(!ts)return 'Unknown date';try{return new Date(Number(ts)*1000).toLocaleString();}catch(e){return 'Unknown date';}}
  function thumb(item){
    var u=String(item.thumb||'');
    if(/^(https?:\\/\\/|\/)/i.test(u))return '<div class="rb-thumb"><img src="'+esc(u)+'" alt="" loading="lazy" onerror="this.parentNode.textContent=\\'🎬\\'"></div>';
    return '<div class="rb-thumb" aria-hidden="true">🎬</div>';
  }
  function card(item){
    var col=String(item.collection||'primary').toLowerCase(),original=String(item.group_id||'');
    return '<article class="rb-card">'+thumb(item)+'<div class="rb-body">'+
      '<div class="rb-name">'+esc(item.file_name||'Deleted file')+'</div>'+
      '<div class="rb-meta"><span class="rb-chip '+esc(col)+'">'+esc(col.toUpperCase())+'</span>'+
      (item.file_size?'<span class="rb-chip">'+esc(item.file_size)+'</span>':'')+
      (original?'<span class="rb-chip">GROUP #'+esc(original)+'</span>':'')+'</div>'+
      '<div class="rb-date">Deleted '+esc(dateText(item.deleted_at))+(item.deleted_by?' · by #'+esc(item.deleted_by):'')+'</div>'+
      '<div class="rb-actions"><button type="button" class="rb-btn restore" data-action="restore" data-id="'+esc(item.id)+'">♻️ Restore</button>'+
      '<button type="button" class="rb-btn purge" data-action="purge" data-id="'+esc(item.id)+'">🗑 Delete forever</button></div>'+
      '</div></article>';
  }
  async function load(){
    if(busy)return;
    busy=true;setStatus('Loading Recycle Bin…');prev.disabled=true;next.disabled=true;
    try{
      var r=await fetch('/api/recycle/list?offset='+offset+'&limit='+limit+'&q='+encodeURIComponent(query),{cache:'no-store'});
      var d=await r.json();
      if(!r.ok)throw new Error(d.error||'Could not load the Recycle Bin.');
      total=Number(d.total)||0;
      count.textContent=total+(total===1?' item':' items');
      page.textContent='Page '+(Math.floor(offset/limit)+1);
      grid.innerHTML=(d.items&&d.items.length)?d.items.map(card).join(''):'<div class="rb-empty"><b>Recycle Bin is empty</b>Deleted files will appear here for admin restore.</div>';
      prev.disabled=offset<=0;next.disabled=offset+limit>=total;
      setStatus('');
    }catch(e){setStatus(e.message||'Could not load the Recycle Bin.',true);grid.innerHTML='';}
    finally{busy=false;}
  }
  async function post(path,payload){
    var r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    var d=await r.json().catch(function(){return {};});
    if(!r.ok||!d.success)throw new Error(d.error||'The operation failed.');
    return d;
  }
  grid.addEventListener('click',async function(event){
    var button=event.target.closest('button[data-action]');if(!button||busy)return;
    var action=button.dataset.action,id=button.dataset.id;
    var question=action==='restore'?'Restore this file to the library?':'Permanently delete this file from the Recycle Bin? This cannot be undone.';
    if(!confirm(question))return;
    button.disabled=true;setStatus(action==='restore'?'Restoring file…':'Deleting file permanently…');
    try{
      var d=await post(action==='restore'?'/api/recycle/restore':'/api/recycle/purge',{id:id});
      setStatus(action==='restore'?(d.already?'This file is already active in '+String(d.collection||'').toUpperCase()+'.':'File restored successfully.'):'File permanently deleted.',false);
      await load();
    }catch(e){setStatus(e.message||'The operation failed.',true);button.disabled=false;}
  });
  function searchNow(){query=(search.value||'').trim();offset=0;load();}
  document.getElementById('rbSearchBtn').addEventListener('click',searchNow);
  document.getElementById('rbClear').addEventListener('click',function(){search.value='';query='';offset=0;load();});
  search.addEventListener('keydown',function(e){if(e.key==='Enter'){e.preventDefault();searchNow();}});
  prev.addEventListener('click',function(){if(offset>0&&!busy){offset=Math.max(0,offset-limit);load();}});
  next.addEventListener('click',function(){if(!busy&&offset+limit<total){offset+=limit;load();}});
  load();
})();
</script>"""


def _page_body():
    return (
        _CSS
        + '<main class="rb-page">'
        '<header class="rb-head"><div><div class="rb-eyebrow">Admin workspace</div>'
        '<h1 class="rb-title">Recycle Bin</h1>'
        '<p class="rb-sub">Deleted media records are kept here for admin restore. '
        'They are hidden from bot searches, the web catalogue and the mini app.</p></div>'
        '<div class="rb-headside"><span class="rb-count" id="rbCount">Loading…</span>'
        '<a class="rb-back" href="/dashboard">← Back to library</a></div></header>'
        '<div class="rb-toolbar"><input class="rb-search" id="rbSearch" type="search" '
        'placeholder="Search deleted file names…" autocomplete="off">'
        '<button type="button" class="rb-btn primary" id="rbSearchBtn">Search</button>'
        '<button type="button" class="rb-btn" id="rbClear">Clear</button></div>'
        '<div class="rb-status" id="rbStatus" role="status" aria-live="polite"></div>'
        '<div class="rb-grid" id="rbGrid"></div>'
        '<div class="rb-pager"><button type="button" class="rb-btn" id="rbPrev" disabled>Previous</button>'
        '<span class="rb-pageinfo" id="rbPage">Page 1</span>'
        '<button type="button" class="rb-btn" id="rbNext" disabled>Next</button></div>'
        '</main>'
        + _JS
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
    total, docs = await list_recycle_files(q, offset, limit)
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
        })
    return web.json_response({'total': total, 'offset': offset, 'limit': limit,
                              'items': items}, dumps=fast_json,
                             headers={'Cache-Control': 'no-store'})


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
