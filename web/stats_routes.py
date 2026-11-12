"""Admin database overview: counts, storage and cache controls."""
import asyncio
from aiohttp import web
from web.web_assets import build_page, get_auth
from database.ia_filterdb import (
    db_count_documents, get_directory_counts, get_post_category_counts,
    get_saved_group_counts,
)
from database.users_chats_db import db as user_db

stats_routes = web.RouteTableDef()

_STATS_CSS = """<style>
.stats-page{max-width:1320px;margin:0 auto;padding:36px 4% 64px;--stat-surface:var(--card);--stat-soft:var(--bg3);--stat-border:var(--border);--stat-text:var(--text);--stat-muted:var(--muted)}
.stats-page *{box-sizing:border-box}.stats-page button,.stats-page a{font-family:inherit}
.stats-head{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin-bottom:28px}
.stats-eyebrow,.section-kicker{display:flex;align-items:center;gap:8px;color:var(--accent);font-size:10px;font-weight:900;letter-spacing:1.6px;text-transform:uppercase}
.stats-eyebrow:before{content:'';width:7px;height:7px;border-radius:50%;background:var(--accent)}
.stats-head h1{font-size:clamp(27px,3.4vw,38px);letter-spacing:-1.4px;line-height:1.08;margin:10px 0 8px;color:var(--stat-text)}
.stats-head p{color:var(--stat-muted);font-size:13px;line-height:1.55}.stats-refresh{display:inline-flex;align-items:center;justify-content:center;gap:8px;border:1px solid var(--stat-border);border-radius:9px;padding:10px 14px;background:var(--stat-surface);color:var(--stat-text);text-decoration:none;font-size:12px;font-weight:800;white-space:nowrap;transition:border-color .2s,background .2s}
.stats-refresh:hover{border-color:var(--accent);background:var(--stat-soft)}.stats-refresh svg,.stat-icon svg,.section-icon svg,.cache-btn svg{width:16px;height:16px;display:block;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.stats-page a:focus-visible,.stats-page button:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
.overview-panel{position:relative;overflow:hidden;display:grid;grid-template-columns:1.1fr 1fr;gap:32px;border:1px solid var(--stat-border);border-radius:18px;background:linear-gradient(125deg,var(--stat-surface),var(--bg2));padding:29px 32px;margin-bottom:30px}
.overview-panel:before{content:'';position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--accent)}
.overview-main{min-width:0}.overview-label{color:var(--stat-muted);font-size:11px;font-weight:800;letter-spacing:1px;text-transform:uppercase}
.overview-value{font-size:clamp(44px,5vw,64px);font-weight:900;letter-spacing:-2.5px;line-height:1.05;margin:13px 0 8px;color:var(--stat-text);font-variant-numeric:tabular-nums}
.overview-note{font-size:12px;line-height:1.5;color:var(--stat-muted)}.overview-side{border-left:1px solid var(--stat-border);padding-left:32px;display:flex;flex-direction:column;justify-content:center;min-width:0}
.overview-side-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:16px}.overview-side-head strong{font-size:13px;color:var(--stat-text)}.overview-side-head span{font-size:11px;color:var(--stat-muted)}
.distribution-bar,.meter{display:flex;width:100%;height:8px;overflow:hidden;border-radius:99px;background:var(--bg4)}.distribution-bar span{height:100%}.dist-primary{background:#e62c3c}.dist-cloud{background:#4b9cf6}.dist-archive{background:#a77af1}
.distribution-legend{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:15px}.legend-item{min-width:0}.legend-label{display:flex;align-items:center;gap:6px;color:var(--stat-muted);font-size:11px}.legend-dot{width:7px;height:7px;border-radius:50%;flex:none}.legend-value{font-size:14px;font-weight:800;color:var(--stat-text);margin-top:5px;font-variant-numeric:tabular-nums}
.section-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;margin:0 0 15px}.section-heading h2{font-size:19px;letter-spacing:-.45px;margin:6px 0 0;color:var(--stat-text)}.section-heading p{font-size:12px;color:var(--stat-muted);line-height:1.5}
.collection-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-bottom:31px}.stats-card{background:var(--stat-surface);border:1px solid var(--stat-border);border-radius:14px;padding:20px;min-width:0;transition:border-color .2s,transform .2s}
.stats-card:hover{border-color:var(--muted);transform:translateY(-2px)}.card-top{display:flex;align-items:center;justify-content:space-between;gap:12px}.card-title{display:flex;align-items:center;gap:10px;min-width:0}.stat-icon,.section-icon{display:grid;place-items:center;width:34px;height:34px;border-radius:10px;flex:none;background:var(--stat-soft);color:var(--stat-text);border:1px solid var(--stat-border)}
.card-title h3{font-size:13px;font-weight:800;color:var(--stat-text);line-height:1.3}.card-top .card-badge{font-size:10px;font-weight:800;color:var(--stat-muted);background:var(--stat-soft);border:1px solid var(--stat-border);border-radius:99px;padding:5px 9px;white-space:nowrap}
.collection-number{font-size:30px;font-weight:900;letter-spacing:-1px;margin:22px 0 4px;line-height:1;font-variant-numeric:tabular-nums;color:var(--stat-text)}.card-caption{font-size:11px;color:var(--stat-muted);line-height:1.5}.collection-card .meter{height:5px;margin:17px 0 12px}.collection-meta{display:flex;justify-content:space-between;gap:10px;font-size:11px;color:var(--stat-muted)}.collection-meta strong{color:var(--stat-text);font-weight:700}
.detail-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin-bottom:31px}.detail-card{padding:22px}.detail-card .card-top{align-items:flex-start}.detail-card .section-icon{width:38px;height:38px}.detail-card .section-icon svg{width:18px;height:18px}
.detail-number{font-size:32px;font-weight:900;letter-spacing:-1px;line-height:1.1;margin:21px 0 5px;color:var(--stat-text);font-variant-numeric:tabular-nums;overflow-wrap:anywhere}.detail-description{font-size:11px;color:var(--stat-muted);line-height:1.5}
.breakdown{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:18px}.breakdown-item{background:var(--stat-soft);border:1px solid var(--stat-border);border-radius:9px;padding:10px 12px;min-width:0}.breakdown-label{font-size:11px;color:var(--stat-muted);line-height:1.3}.breakdown-value{font-size:16px;font-weight:800;color:var(--stat-text);margin-top:5px;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}.breakdown-wide{grid-column:1/-1;display:flex;align-items:center;justify-content:space-between;gap:12px}.breakdown-wide .breakdown-value{margin:0}
.operations-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.operation-card{display:flex;flex-direction:column;gap:14px}.operation-card .detail-number{margin:4px 0 0;font-size:26px}.operation-line{display:flex;justify-content:space-between;align-items:center;gap:12px;font-size:11px;color:var(--stat-muted)}.operation-line strong{color:var(--stat-text);font-size:12px}.meter-fill{height:100%;width:0;background:var(--accent);border-radius:99px;transition:width .35s}.storage-warning{color:var(--accent)!important}.storage-retry{display:none;align-self:flex-start;border:0;padding:0;background:none;color:var(--accent);font-size:12px;font-weight:800;cursor:pointer}.storage-retry.visible{display:block}
.cache-btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;align-self:flex-start;border:1px solid var(--stat-border);border-radius:9px;background:var(--stat-soft);color:var(--stat-text);padding:10px 13px;cursor:pointer;font-size:12px;font-weight:800;transition:border-color .2s,opacity .2s}.cache-btn:hover{border-color:var(--accent)}.cache-btn:disabled{opacity:.6;cursor:wait}.cache-status{min-height:18px;font-size:11px;color:var(--stat-muted)}.stats-footnote{margin-top:21px;color:var(--stat-muted);font-size:11px;line-height:1.6}
@media(max-width:800px){.stats-head{align-items:flex-start}.overview-panel{grid-template-columns:1fr;gap:23px}.overview-side{border-left:0;border-top:1px solid var(--stat-border);padding:22px 0 0}.collection-grid{grid-template-columns:1fr 1fr}.collection-card:last-child{grid-column:1/-1}}
@media(max-width:560px){.stats-page{padding:26px 16px 48px}.stats-head{gap:12px}.stats-head h1{font-size:27px}.stats-head p{font-size:12px}.stats-refresh{padding:9px 10px}.overview-panel{padding:24px 22px;border-radius:15px}.overview-value{font-size:48px}.collection-grid{grid-template-columns:1fr}.collection-card:last-child{grid-column:auto}.collection-number{margin-top:18px}.detail-grid,.operations-grid{grid-template-columns:1fr}.section-heading{align-items:flex-start;flex-direction:column;gap:5px}.section-heading p{font-size:11px}.stats-card{padding:18px}.detail-card{padding:19px}}
@media(prefers-reduced-motion:reduce){.stats-page *{transition:none!important}}
</style>"""

_STATS_JS = """<script>
(function(){
  var retry = document.getElementById('storage-retry');
  var value = document.getElementById('db-used-val');
  var bar = document.getElementById('db-prog-bar');
  var pct = document.getElementById('db-pct-val');
  var limit = document.getElementById('db-limit-val');
  var pending = false;
  async function loadDbStats(){
    if(pending)return;
    pending=true;retry.classList.remove('visible');value.textContent='Loading…';
    try{
      var r=await fetch('/api/db_stats');
      var d=await r.json();
      if(!r.ok || !d.used || typeof d.percent !== 'number' || !Number.isFinite(d.percent))throw new Error('Storage unavailable');
      var n=Math.max(0,Math.min(100,Number(d.percent)));
      value.textContent=d.used;limit.textContent=d.total || '512.0 MB';
      pct.textContent=n+'%';bar.style.width=n+'%';
      value.classList.toggle('storage-warning',n>85);pct.classList.toggle('storage-warning',n>85);
    }catch(e){value.textContent='Unavailable';pct.textContent='—';bar.style.width='0%';retry.classList.add('visible');}
    finally{pending=false;}
  }
  retry.addEventListener('click',loadDbStats);
  loadDbStats();
})();
async function triggerCacheFlush(){
  var btn=document.getElementById('flushBtn'),status=document.getElementById('flush-status');
  if(btn.disabled)return;
  btn.disabled=true;status.textContent='Clearing cache…';
  try{
    var r=await fetch('/api/flush_cache',{method:'POST'}),d=await r.json().catch(()=>({}));
    if(!r.ok||!d.success||d.error)throw new Error('Cache clear failed');
    status.textContent='Cache cleared successfully.';
  }catch(e){status.textContent='Could not clear cache. Please try again.';}
  finally{btn.disabled=false;}
}
</script>"""

_ICON = {
    'refresh': '<path d="M20 7v5h-5"/><path d="M4 17v-5h5"/><path d="M5.5 9a7 7 0 0 1 12-2L20 12M4 12l2.5 5a7 7 0 0 0 12-2"/>',
    'database': '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v7c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12v7c0 1.7 3.6 3 8 3s8-1.3 8-3v-7"/>',
    'groups': '<rect x="3" y="4" width="8" height="7" rx="1"/><rect x="13" y="4" width="8" height="7" rx="1"/><rect x="3" y="13" width="8" height="7" rx="1"/><rect x="13" y="13" width="8" height="7" rx="1"/>',
    'people': '<circle cx="9" cy="8" r="3"/><path d="M3 20v-2a6 6 0 0 1 12 0v2"/><path d="M16 5a3 3 0 0 1 0 6M17 14a5 5 0 0 1 4 5v1"/>',
    'directory': '<rect x="4" y="3" width="16" height="18" rx="2"/><circle cx="12" cy="9" r="2.5"/><path d="M7.5 17c.8-2.7 8.2-2.7 9 0"/>',
    'posts': '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
    'storage': '<path d="M5 4h14l2 7v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-8z"/><path d="M3 11h18M7 16h.01M11 16h.01"/>',
    'image': '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/>',
}


def _icon(name):
    return f'<svg viewBox="0 0 24 24" aria-hidden="true">{_ICON[name]}</svg>'


def _collection_card(name, count, thumbs, pct, colour):
    return f'''<article class="stats-card collection-card">
      <div class="card-top"><div class="card-title"><span class="stat-icon">{_icon('database')}</span><h3>{name}</h3></div><span class="card-badge">{pct}% of files</span></div>
      <div class="collection-number">{count:,}</div><div class="card-caption">Files in this collection</div>
      <div class="meter" aria-hidden="true"><span class="{colour}" style="width:{pct}%"></span></div>
      <div class="collection-meta"><span>Thumbnail records</span><strong>{thumbs:,}</strong></div>
    </article>'''


def _breakdown(label, count, wide=False):
    return f'''<div class="breakdown-item{' breakdown-wide' if wide else ''}"><div class="breakdown-label">{label}</div><div class="breakdown-value">{count:,}</div></div>'''


async def _get_total_plays():
    stats_doc = await user_db.settings.find_one({"id": "global_stream_stats"}, {"total_web_plays": 1})
    return stats_doc.get("total_web_plays", 0) if stats_doc else 0


@stats_routes.get('/stats')
async def stats(req):
    role, _ = await get_auth(req)
    if role != 'admin':
        return web.HTTPFound('/dashboard')

    default_s = {'total': 0, 'primary': 0, 'cloud': 0, 'archive': 0,
                 'primary_thumb': 0, 'cloud_thumb': 0, 'archive_thumb': 0, 'total_thumb': 0}

    async def _safe(coro, default):
        try:
            return await coro
        except Exception:
            return default

    (s, users, total_plays, logged_in_today, premium_users,
     (tot_dir, act_dir, app_dir, web_dir), post_stats, group_stats) = await asyncio.gather(
        _safe(db_count_documents(), default_s),
        _safe(user_db.total_users_count(), 0),
        _safe(_get_total_plays(), 0),
        _safe(user_db.get_today_logged_in_users_count(), 0),
        _safe(user_db.get_premium_users_count(), 0),
        get_directory_counts(), get_post_category_counts(),
        _safe(get_saved_group_counts(), None),
    )
    if not isinstance(s, dict):
        s = default_s
    post_total, post_movies, post_webseries, post_appvid, post_porn = post_stats
    post_other = post_total - post_movies - post_webseries - post_appvid - post_porn
    p_tot, c_tot, a_tot = s.get('primary', 0), s.get('cloud', 0), s.get('archive', 0)
    grand_total = s.get('total', 0)
    divisor = grand_total or 1
    p_pct, c_pct, a_pct = (int(n / divisor * 100) for n in (p_tot, c_tot, a_tot))

    def group_count_markup(key, delay):
        if group_stats is None:
            return '—' if key != 'total' else 'Unavailable'
        count = group_stats[key]
        return f'<span data-count="{count}" data-delay="{delay}">{count:,}</span>'

    post_other_markup = _breakdown('Other / Uncategorized', post_other, True) if post_other > 0 else ''
    body = f'''{_STATS_CSS}<main class="stats-page">
  <header class="stats-head">
    <div><div class="stats-eyebrow">Admin workspace</div><h1>Database overview</h1><p>Your library, content and account activity, all in one place.</p></div>
    <a href="/stats" class="stats-refresh">{_icon('refresh')} Refresh</a>
  </header>

  <section class="overview-panel" aria-label="File overview">
    <div class="overview-main"><div class="overview-label">Total Files</div><div class="overview-value">{grand_total:,}</div><div class="overview-note">Across Primary, Cloud and Archive collections</div></div>
    <div class="overview-side"><div class="overview-side-head"><strong>Collection breakdown</strong><span>Share of total files</span></div>
      <div class="distribution-bar" aria-hidden="true"><span class="dist-primary" style="width:{p_pct}%"></span><span class="dist-cloud" style="width:{c_pct}%"></span><span class="dist-archive" style="width:{a_pct}%"></span></div>
      <div class="distribution-legend"><div class="legend-item"><div class="legend-label"><span class="legend-dot dist-primary"></span>Primary</div><div class="legend-value">{p_pct}%</div></div><div class="legend-item"><div class="legend-label"><span class="legend-dot dist-cloud"></span>Cloud</div><div class="legend-value">{c_pct}%</div></div><div class="legend-item"><div class="legend-label"><span class="legend-dot dist-archive"></span>Archive</div><div class="legend-value">{a_pct}%</div></div></div>
    </div>
  </section>

  <section aria-labelledby="collections-title"><div class="section-heading"><div><div class="section-kicker">01 / Library</div><h2 id="collections-title">File collections</h2></div><p>File and thumbnail records by source</p></div>
    <div class="collection-grid">{_collection_card('Primary', p_tot, s.get('primary_thumb', 0), p_pct, 'dist-primary')}{_collection_card('Cloud', c_tot, s.get('cloud_thumb', 0), c_pct, 'dist-cloud')}{_collection_card('Archive', a_tot, s.get('archive_thumb', 0), a_pct, 'dist-archive')}</div>
  </section>

  <section aria-labelledby="content-title"><div class="section-heading"><div><div class="section-kicker">02 / Content &amp; community</div><h2 id="content-title">At a glance</h2></div><p>A closer look at what you have saved</p></div>
    <div class="detail-grid">
      <article class="stats-card detail-card" id="saved-group-stats"><div class="card-top"><div class="card-title"><span class="section-icon">{_icon('groups')}</span><h3>Saved Groups · Total</h3></div><span class="card-badge">GROUPS</span></div>
        <div class="detail-number" id="saved-group-total">{group_count_markup('total', 0)}</div><div class="detail-description">Saved group records, including legacy records</div>
        <div class="breakdown"><div class="breakdown-item"><div class="breakdown-label">Quality Groups</div><div class="breakdown-value" id="saved-quality-count">{group_count_markup('quality', 0)}</div></div><div class="breakdown-item"><div class="breakdown-label">Series Groups</div><div class="breakdown-value" id="saved-series-count">{group_count_markup('series', 0)}</div></div></div>
      </article>
      <article class="stats-card detail-card"><div class="card-top"><div class="card-title"><span class="section-icon">{_icon('people')}</span><h3>System subscribers</h3></div><span class="card-badge">USERS</span></div>
        <div class="detail-number">{users:,}</div><div class="detail-description">Total user records</div><div class="breakdown">{_breakdown('Logged in today', logged_in_today)}{_breakdown('Premium users', premium_users)}</div>
      </article>
      <article class="stats-card detail-card"><div class="card-top"><div class="card-title"><span class="section-icon">{_icon('directory')}</span><h3>Directory profiles</h3></div><span class="card-badge">DIRECTORY</span></div>
        <div class="detail-number">{tot_dir:,}</div><div class="detail-description">Profiles across all categories</div><div class="breakdown">{_breakdown('Actors', act_dir)}{_breakdown('Apps', app_dir)}{_breakdown('Websites', web_dir, True)}</div>
      </article>
      <article class="stats-card detail-card"><div class="card-top"><div class="card-title"><span class="section-icon">{_icon('posts')}</span><h3>Content posts</h3></div><span class="card-badge">POSTS</span></div>
        <div class="detail-number">{post_total:,}</div><div class="detail-description">Posts across all categories</div><div class="breakdown">{_breakdown('Movies', post_movies)}{_breakdown('Web Series', post_webseries)}{_breakdown('App Video', post_appvid)}{_breakdown('Porn', post_porn)}{post_other_markup}</div>
      </article>
    </div>
  </section>

  <section aria-labelledby="tools-title"><div class="section-heading"><div><div class="section-kicker">03 / Database tools</div><h2 id="tools-title">Storage &amp; maintenance</h2></div><p>Monitor usage and manage cached data</p></div>
    <div class="operations-grid">
      <article class="stats-card operation-card"><div class="card-top"><div class="card-title"><span class="section-icon">{_icon('storage')}</span><h3>Database storage</h3></div><span class="card-badge">MONGODB</span></div>
        <div class="detail-number" id="db-used-val" aria-live="polite">Loading…</div><div class="operation-line"><span>Used storage</span><strong id="db-pct-val">—</strong></div>
        <div class="meter" aria-hidden="true"><div class="meter-fill" id="db-prog-bar"></div></div><div class="operation-line"><span>Free tier reference</span><strong id="db-limit-val">512.0 MB</strong></div><button type="button" class="storage-retry" id="storage-retry">Retry storage check</button>
      </article>
      <article class="stats-card operation-card"><div class="card-top"><div class="card-title"><span class="section-icon">{_icon('image')}</span><h3>Cache &amp; activity</h3></div><span class="card-badge">MAINTENANCE</span></div>
        <div class="breakdown"><div class="breakdown-item"><div class="breakdown-label">Thumbnail records</div><div class="breakdown-value">{s.get('total_thumb', 0):,}</div></div><div class="breakdown-item"><div class="breakdown-label">Video stream plays</div><div class="breakdown-value">{total_plays:,}</div></div></div>
        <div class="detail-description">Clear in-memory thumbnail and search caches when you need a fresh read.</div>
        <button class="cache-btn" id="flushBtn" type="button" onclick="triggerCacheFlush()">{_icon('refresh')} Clear RAM cache</button><div class="cache-status" id="flush-status" aria-live="polite"></div>
      </article>
    </div>
  </section>
  <p class="stats-footnote">File and thumbnail counts may be cached for up to a minute. Group counts are read from saved records; legacy records are included.</p>
</main>{_STATS_JS}'''
    return build_page("Stats - Fast Finder", body, "", "stats", role)
