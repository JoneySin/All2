import time
from aiohttp import web
from web.web_assets import build_page, get_auth, form_wrapper, MAX_WEB_RESULTS, require_active_plan, DEFAULT_MEDIA_MODE
from utils import temp
from database.users_chats_db import web_db

dashboard_routes = web.RouteTableDef()

# ─────────────────────────────────────────────────────────────────────────────
# 🎨 DASHBOARD SPECIFIC CSS (सिर्फ सर्च बार और ड्रॉपडाउन के लिए, कार्ड्स ग्लोबल हैं)
# ─────────────────────────────────────────────────────────────────────────────
CARD_CSS = """
<style>
/* ── Search zone ── */
.search-zone{padding:16px 20px 0;max-width:1400px;margin:0 auto}
.search-row1{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.search-row2{display:flex;align-items:center;justify-content:center;gap:10px;margin-bottom:16px}
@media(min-width:768px){
  .search-zone{padding:24px 24px 10px;display:flex;align-items:center;justify-content:center;gap:14px;flex-wrap:nowrap}
  .search-row1{flex:1;max-width:650px;margin-bottom:0}
  .search-row2{margin-bottom:0;justify-content:flex-start;flex-shrink:0}
}
@media(max-width:767px){.search-row2 .cdd-wrap{flex:1 1 0}.search-row2 .cdd-btn{width:100%}}

.search-wrap{flex:1;min-width:0;display:flex;align-items:center;background:var(--bg3);border:1.5px solid var(--border);border-radius:12px;padding:0 6px 0 18px;gap:8px;overflow:hidden;min-height:38px;transition:border-color .18s}
.search-wrap:focus-within{border-color:var(--border)}
.search-spinner{display:none;width:15px;height:15px;flex-shrink:0;border:2px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:searchSpin .6s linear infinite}
.search-wrap.loading .search-spinner{display:inline-block}
@keyframes searchSpin{to{transform:rotate(360deg)}}
.search-input{flex:1;min-width:0;width:100%;background:transparent;border:none;outline:none;color:var(--text);caret-color:var(--accent);font-size:14px;font-weight:600;padding:6px 0;font-family:inherit;-webkit-tap-highlight-color:transparent}
.search-input::placeholder{color:var(--muted);font-weight:400}
.search-input:-webkit-autofill,
.search-input:-webkit-autofill:hover,
.search-input:-webkit-autofill:focus,
.search-input:-webkit-autofill:active{
  -webkit-box-shadow:0 0 0 100px var(--bg3) inset !important;
  box-shadow:0 0 0 100px var(--bg3) inset !important;
  -webkit-text-fill-color:var(--text) !important;
  caret-color:var(--accent) !important;
  border-radius:999px;
  transition:background-color 9999s ease-in-out 0s;
}
.search-btn{position:relative;overflow:hidden;flex-shrink:0;background:var(--accent);color:#fff;border:none;border-radius:12px;padding:0 20px;height:38px;font-size:14px;font-weight:700;cursor:pointer;white-space:nowrap;transition:transform .15s,box-shadow .15s,background .15s;letter-spacing:.3px}
.search-btn:hover{background:var(--accent-hover);transform:scale(1.03);box-shadow:0 6px 22px rgba(229,9,20,0.50)}
.search-btn:active{transform:scale(.96)}
/* ripple */
.search-btn::after{content:'';position:absolute;inset:0;background:rgba(255,255,255,0);border-radius:inherit;pointer-events:none}
.search-btn.ripple-go::after{animation:btnRipple .45s ease-out forwards}
@keyframes btnRipple{0%{background:rgba(255,255,255,0.28);transform:scale(.6)}100%{background:rgba(255,255,255,0);transform:scale(1.6)}}

/* ── Custom dropdown ── */
.cdd-wrap{flex:0 1 auto;min-width:0;position:relative;user-select:none}
.cdd-btn{width:170px;background:var(--bg3);color:var(--text);border:1.5px solid var(--border);border-radius:999px;padding:8px 28px 8px 14px;font-size:11px;font-weight:700;cursor:pointer;font-family:inherit;box-sizing:border-box;display:inline-flex;align-items:center;justify-content:flex-start;gap:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:border-color .15s,box-shadow .15s}
.cdd-btn:hover,.cdd-btn.open{border-color:var(--accent);box-shadow:0 0 0 3px rgba(229,9,20,0.12)}
.cdd-arrow{position:absolute;right:12px;top:50%;transform:translateY(-50%);pointer-events:none;font-size:9px;color:var(--muted);transition:transform .2s}
.cdd-btn.open+.cdd-arrow{transform:translateY(-50%) rotate(180deg)}

.cdd-menu{position:absolute;top:calc(100% + 7px);left:50%;transform:translateX(-50%);min-width:max-content;background:var(--bg2,var(--bg3));border:1.5px solid var(--border);border-radius:16px;overflow:hidden;z-index:9999;box-shadow:0 8px 32px rgba(0,0,0,.45);animation:cddIn .15s ease}
@keyframes cddIn{
    from{opacity:0;transform:translate(-50%, -6px)}
    to{opacity:1;transform:translate(-50%, 0)}
}

.cdd-item{display:flex;align-items:center;gap:10px;padding:13px 14px;font-size:13px;font-weight:700;color:var(--text);cursor:pointer;transition:background .12s;border-bottom:1px solid var(--border)}
.cdd-item:last-child{border-bottom:none}
.cdd-item:hover{background:var(--bg3)}
.cdd-item.selected{color:var(--accent)}
.cdd-radio{width:18px;height:18px;border-radius:50%;border:2px solid var(--border);margin-left:auto;flex-shrink:0;display:flex;align-items:center;justify-content:center;transition:border-color .15s}
.cdd-item.selected .cdd-radio{border-color:var(--accent)}
.cdd-radio-dot{width:8px;height:8px;border-radius:50%;background:var(--accent);display:none}
.cdd-item.selected .cdd-radio-dot{display:block}
.source-pill.mixed{background:#78350f;color:#fcd34d;border:1px solid #f59e0b}
.source-pill.mixed .source-dot{background:#fcd34d}
/* ── Group filter button (red, small) ── */
.gf-btn{width:auto!important;min-width:74px;background:var(--accent)!important;border-color:var(--accent)!important;color:#fff!important;padding:8px 26px 8px 14px!important;justify-content:center}
.gf-wrap{flex:0 0 auto}
.gf-wrap .cdd-arrow{color:#fff!important}
.gf-wrap .cdd-menu{left:auto;right:0;transform:none;min-width:130px}
/* ── Quality group card (master thumbnail = single file jaisa bada poster) ── */
.grp-card{background:var(--card);border:1px solid var(--border);border-radius:10px;overflow:hidden;display:flex;flex-direction:column;position:relative;cursor:pointer;box-shadow:0 4px 10px rgba(0,0,0,.2);transition:all .3s cubic-bezier(.25,.8,.25,1)}
.grp-card.open{border-color:var(--accent)}
/* ✅ file-card जैसा ही hover/press एनिमेशन (खुले हुए group पर नहीं) */
.grp-card:not(.open):hover{transform:translateY(-6px) scale(1.02);border-color:var(--accent);box-shadow:0 15px 35px rgba(0,0,0,.6),0 0 15px rgba(229,9,20,.3);z-index:2}
.grp-card:not(.open):active{transform:scale(.96);transition:transform .1s}
.grp-card:not(.open) .grp-title{transition:color .18s;text-decoration:none}
.grp-card:not(.open) .grp-title:hover{color:var(--accent);text-decoration:underline;text-decoration-color:var(--accent);text-underline-offset:2px}
.grp-card:hover .fc-poster{transform:scale(1.08)}
.grp-card.open{grid-column:1/-1;box-shadow:0 8px 28px rgba(0,0,0,.45);cursor:default}
.poster-top{flex-wrap:wrap;align-content:flex-start}
.group-id-chip{display:inline-flex;align-items:center;gap:3px;background:#39230b;color:#ffd58a;border:1px solid #d99b3b;border-radius:6px;padding:3px 7px;font-size:10px;font-weight:800;letter-spacing:.3px;line-height:1.4;white-space:nowrap}
.group-id-chip.pending{background:#302a35;color:#ddd0e8;border-color:#897797}
.episode-chip{background:#25104c;color:#e0c7ff;border:1px solid #a977ed;border-radius:6px;padding:3px 7px;font-size:10px;font-weight:800;line-height:1.4}
.grp-badge{background:rgba(229,9,20,.92);color:#fff;border-radius:6px;padding:3px 8px;font-size:10px;font-weight:800;letter-spacing:.4px;border:1px solid rgba(255,255,255,.18);line-height:1.4;white-space:nowrap}
.grp-bottom{position:absolute;left:0;right:0;bottom:0;display:flex;flex-wrap:wrap;gap:5px;padding:28px 8px 8px;background:linear-gradient(transparent,rgba(0,0,0,.88));z-index:3}
.grp-chip{background:#082f49;color:#7dd3fc;border:1px solid #0ea5e9;border-radius:5px;font-size:10px;font-weight:800;padding:2px 8px;line-height:1.5;text-shadow:none;max-width:100%;min-width:0;overflow-wrap:anywhere}
.grp-chip i{font-style:normal;color:#e0f2fe;opacity:1;margin-left:2px}
.grp-body{padding:12px 12px 13px}
.grp-title{color:var(--text);font-size:12.5px;font-weight:600;line-height:1.45;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.grp-title-button{width:fit-content;max-width:100%;padding:0;border:0;background:none;font-family:inherit;text-align:left;cursor:pointer}
.grp-title-button:focus-visible{outline:2px solid var(--accent);outline-offset:4px;border-radius:2px}
.grp-card.open .grp-title{-webkit-line-clamp:unset}
.grp-textinfo{display:none;align-items:center;gap:6px;flex-wrap:wrap;margin-top:8px}
.res-grid.mode-none .grp-textinfo{display:flex}
.grp-openhead{display:none;align-items:center;gap:10px;flex-wrap:wrap;padding:12px 14px;cursor:pointer}
.grp-openhead .grp-title{min-width:0}
.grp-arrow{margin-left:auto;color:var(--muted);font-size:13px;transform:rotate(180deg)}
.grp-card.open .grp-openhead{display:flex}
.grp-card.open .grp-master{display:none}
.grp-textadmin{display:none;gap:5px;padding-top:8px;flex-wrap:wrap}
.res-grid.mode-none .grp-card.grp-active .grp-master .grp-textadmin{display:flex}
.res-grid.mode-none .grp-openhead .grp-oadmin{display:none}
.res-grid.mode-none .grp-card.grp-active .grp-openhead .grp-oadmin{display:flex}
.grp-open-title{flex:0 1 auto;width:fit-content;max-width:100%;padding:0;border:0;background:none;color:var(--text);font:inherit;text-align:left;cursor:pointer}
.grp-open-title:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
.grp-card.grp-active .grp-master .poster-admin{opacity:1;visibility:visible;transform:translateY(0);pointer-events:all}
.grp-title{cursor:pointer}
.grp-openhead .grp-oadmin{display:flex;gap:5px}
.grp-openhead .grp-oadmin button{flex:none;padding:6px 10px}
.grp-variants .poster-admin{flex-wrap:wrap}
.grp-variants .poster-admin .btn-edit,.grp-variants .poster-admin .btn-del,.grp-variants .text-admin-row button{flex:1 1 45%}
.grp-variants .text-admin-row{flex-wrap:wrap}
.grp-variants{display:none;border-top:1px solid var(--border)}
.grp-card.open .grp-variants{display:grid;grid-template-columns:1fr;gap:8px;padding:10px}
@media(min-width:600px){.grp-card.open .grp-variants{grid-template-columns:repeat(3,1fr)}}
.grp-variants .file-card:hover{transform:none}
/* ── Group select mode + modal (admin) ── */
.sel-mode .file-card{cursor:pointer}
.sel-mode .file-card::after{content:'';position:absolute;top:8px;right:8px;width:22px;height:22px;border-radius:50%;border:2px solid #fff;background:rgba(0,0,0,.55);z-index:7;display:flex;align-items:center;justify-content:center;color:#fff;font-size:13px;font-weight:900}
.file-card.sel{outline:2px solid #22c55e;outline-offset:-2px}
.sel-mode .file-card.sel::after{content:'✓';background:#22c55e;border-color:#22c55e}
.sel-bar{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);z-index:150;background:var(--bg2);border:1.5px solid var(--border);border-radius:14px;padding:9px 12px;display:flex;align-items:center;gap:8px;box-shadow:0 8px 30px rgba(0,0,0,.55);max-width:96vw}
.sel-bar span{font-size:12px;font-weight:700;color:var(--text);white-space:nowrap}
.sel-bar button,.gm-btn{border:none;border-radius:8px;padding:8px 12px;font-size:12px;font-weight:800;cursor:pointer;color:#fff;background:var(--accent)}
.sel-bar button.alt,.gm-btn.alt{background:var(--bg4)}
.sel-fab{position:fixed;right:16px;bottom:18px;z-index:140;background:var(--accent);color:#fff;border:none;border-radius:999px;padding:11px 16px;font-size:12px;font-weight:800;cursor:pointer;box-shadow:0 6px 20px rgba(229,9,20,.45)}
.gm-card{max-width:620px!important;padding:24px!important}
.gm-saving .gm-card{pointer-events:none}
.gm-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
.gm-eyebrow{font-size:10px;font-weight:800;letter-spacing:1.2px;color:#f9a66d;text-transform:uppercase;margin-bottom:5px}
.gm-title{font-size:20px;font-weight:800;color:var(--text)}
.gm-sub{font-size:12px;line-height:1.5;color:var(--muted);margin-top:5px}
.gm-close{border:1px solid var(--border);border-radius:9px;background:var(--bg3);color:var(--text);font-size:20px;line-height:1;width:34px;height:34px;cursor:pointer}
.gm-label{font-size:11px;font-weight:800;color:var(--muted);letter-spacing:.5px;margin:18px 0 7px}
.gm-input{width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:11px;border-radius:8px;font-size:13px;font-family:inherit;outline:none}
.gm-input:focus,.gm-episode-input:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(229,9,20,.1)}
.gm-type-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;border:0;padding:0;margin:0}
.gm-type-grid label{cursor:pointer;min-width:0}
.gm-type-grid input{position:absolute;opacity:0;pointer-events:none}
.gm-type-option{display:block;height:100%;border:1px solid var(--border);border-radius:10px;background:var(--bg3);padding:12px;transition:.15s}
.gm-type-option strong{display:block;color:var(--text);font-size:12px;margin-bottom:4px}
.gm-type-option small{display:block;color:var(--muted);font-size:11px;line-height:1.4}
.gm-type-grid input:checked+.gm-type-option{border-color:var(--accent);background:rgba(229,9,20,.09);box-shadow:inset 0 0 0 1px var(--accent)}
.gm-type-grid input:focus-visible+.gm-type-option{outline:2px solid var(--accent);outline-offset:2px}
.gm-note{font-size:11px;color:var(--muted);line-height:1.5;margin-top:8px}
.gm-join-note{color:#f9c87a;background:rgba(217,155,59,.1);border:1px solid rgba(217,155,59,.3);padding:9px;border-radius:8px}
.gm-thumbs{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:8px;max-height:210px;overflow-y:auto;overscroll-behavior:contain}
.gm-th{position:relative;border:2px solid var(--border);border-radius:8px;overflow:hidden;cursor:pointer;background:var(--bg3);aspect-ratio:16/9}
.gm-th img{width:100%;height:100%;object-fit:cover;display:block}
.gm-th.on{border-color:#22c55e}
.gm-th em{position:absolute;left:0;right:0;bottom:0;font-style:normal;font-size:10px;font-weight:800;color:#7dd3fc;background:rgba(0,0,0,.75);padding:2px 5px}
.gm-auto{display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:800;color:var(--muted)}
#gmMembers{max-height:270px;overflow-y:auto;overscroll-behavior:contain}
.gm-mem{display:flex;align-items:center;gap:8px;padding:9px 0;border-bottom:1px solid var(--border);font-size:12px;color:var(--text)}
.gm-mem b{color:#7dd3fc;font-size:10px;min-width:28px;text-align:center}
.gm-mem-main{flex:1;min-width:0}
.gm-mem-name{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.gm-episode-input{width:100%;max-width:220px;margin-top:6px;background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:7px;padding:6px 8px;font:inherit;outline:none}
.gm-mem-actions{display:flex;gap:4px;flex-shrink:0}
.gm-mem-actions button{min-width:30px;min-height:30px;background:var(--bg4);border:1px solid var(--border);color:var(--text);border-radius:7px;padding:4px 7px;font-size:12px;font-weight:800;cursor:pointer}
.gm-mem-actions button:disabled{opacity:.35;cursor:not-allowed}
.gm-mem-actions button.gm-remove{background:rgba(160,8,8,.78);color:#fff}
.gm-row{display:flex;gap:8px;margin-top:18px}
.gm-row .gm-btn{flex:1;padding:12px}
#gmGroupList{max-height:180px;overflow-y:auto}
.gm-pick{width:100%;text-align:left;background:var(--bg3);padding:9px 10px;border:1px solid var(--border);border-radius:8px;margin-top:6px;font-size:12px;font-weight:700;color:var(--text);cursor:pointer;display:flex;justify-content:space-between;gap:10px}
.gm-pick span:first-child{min-width:0;overflow-wrap:anywhere}.gm-pick span:last-child{color:var(--muted);font-size:10px;white-space:nowrap}
.gm-pick.on{border-color:#22c55e;color:#22c55e}
.gm-btn:disabled{opacity:.45;cursor:not-allowed}
/* A reviewed destination is required before files or groups are moved. */
.merge-card{max-width:560px!important;padding:24px!important}
.merge-source,.merge-warning{border:1px solid var(--border);border-radius:10px;background:var(--bg3);padding:11px 12px;margin-top:14px;color:var(--text);font-size:12px;line-height:1.5;overflow-wrap:anywhere}
.merge-source small,.target-overline{display:block;color:var(--muted);font-size:10px;font-weight:800;letter-spacing:.7px;text-transform:uppercase;margin-bottom:4px}
.merge-warning{color:#f7c77d;background:rgba(217,155,59,.09);border-color:rgba(217,155,59,.3)}
.merge-id-row{display:flex;gap:8px}.merge-id-row .gm-input{min-width:0;flex:1}.merge-id-row button{flex-shrink:0;padding:0 15px}
.merge-status{min-height:18px;margin-top:8px;font-size:12px;line-height:1.45;color:var(--muted)}
.merge-status.error,.target-error{color:#fda4af}
.target-preview{border:1px solid rgba(34,197,94,.45);border-radius:11px;background:var(--bg3);padding:12px;margin-top:10px;color:var(--text)}
.target-head{display:flex;align-items:flex-start;gap:12px;min-width:0}.target-image-wrap{flex:0 0 96px;min-width:0;text-align:center}
.target-image{position:relative;display:flex;align-items:center;justify-content:center;aspect-ratio:16/9;border-radius:8px;overflow:hidden;background:var(--bg4);color:var(--muted);font-size:22px}
.target-image img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}.target-image-wrap small{display:block;color:var(--muted);font-size:10px;margin-top:4px}
.target-meta{min-width:0;flex:1}.target-name{font-size:15px;font-weight:800;line-height:1.35;overflow-wrap:anywhere}.target-badges{display:flex;flex-wrap:wrap;gap:5px;margin-top:7px}
.target-badge{border-radius:6px;background:var(--bg4);color:var(--text);padding:4px 7px;font-size:10px;font-weight:800;overflow-wrap:anywhere}.target-badge.id{background:#39230b;color:#ffd58a}.target-badge.kind{background:#103b55;color:#c2eaff}
.target-list-label{font-size:10px;font-weight:800;color:var(--muted);letter-spacing:.5px;margin:12px 0 5px;text-transform:uppercase}
.target-members{margin:0;padding:0;list-style:none}.target-members li{padding:6px 0;border-top:1px solid var(--border);font-size:11px;line-height:1.4;overflow-wrap:anywhere}
.target-members small{display:block;color:var(--muted);font-size:10px}.target-more{color:var(--muted);font-size:11px;margin-top:6px}
.target-confirm{display:flex;align-items:flex-start;gap:9px;color:var(--text);font-size:12px;font-weight:700;line-height:1.45;margin-top:12px;cursor:pointer}
.target-confirm input{width:18px;height:18px;flex:none;accent-color:#22c55e;margin:0}
.target-confirm[hidden],#mergePreview[hidden]{display:none!important}
.merge-row{display:flex;gap:8px;margin-top:16px}.merge-row .gm-btn{flex:1;padding:12px}
#gmPickNote .target-preview{margin-top:8px}#gmPickStatus:empty{display:none}
@media(max-width:480px){.gm-card,.merge-card{padding:18px!important}.gm-type-option{padding:10px}.grp-openhead .grp-oadmin{width:100%;flex-wrap:wrap}.gm-row{flex-wrap:wrap}.gm-row .gm-btn{min-width:100px}.target-image-wrap{flex-basis:76px}}
</style>
"""

# ─────────────────────────────────────────────────────────────────────────────
# 🎬 JS ENGINE — Smart Double Pre-fetching Engine Live Live
# ─────────────────────────────────────────────────────────────────────────────
JS_ENGINE = """
var curQ='',curOff=0,nextOff='',curCol='all',curPage=1;
var searchReqId=0;
// Dashboard mode has its own preference key so an old shared posterMode value
// cannot override the text-only dashboard default.
var pMode=localStorage.getItem('ff_dashboard_mode')||'__DEFAULT_MEDIA_MODE__';
var LIMIT_VAL = __LIMIT_PLACEHOLDER__;

var CDDS={col:['cddColMenu','cddColBtn'],mode:['cddModeMenu','cddModeBtn'],gf:['cddGfMenu','cddGfBtn']};
function closeCdds(){
    Object.keys(CDDS).forEach(function(k){
        var m=document.getElementById(CDDS[k][0]),b=document.getElementById(CDDS[k][1]);
        if(m)m.style.display='none';if(b)b.classList.remove('open');
    });
}
function toggleCdd(which,e){
    if(e){e.stopPropagation();}
    var menu=document.getElementById(CDDS[which][0]);
    var btn=document.getElementById(CDDS[which][1]);
    var isOpen=menu.style.display!=='none';
    closeCdds();
    if(!isOpen){menu.style.display='block';btn.classList.add('open');}
}
var curGF='all';
function pickGF(val,label,el,e){
    if(e){e.stopPropagation();}
    curGF=val;curPage=1;
    document.getElementById('cddGfLabel').textContent=label;
    document.querySelectorAll('#cddGfMenu .cdd-item').forEach(function(i){i.classList.remove('selected');});
    el.classList.add('selected');
    closeCdds();
    doSearch(0,true);
}
function pickCol(val,label,el,e){
    if(e){e.stopPropagation();}
    curCol=val;
    document.getElementById('cddColLabel').textContent=label;
    document.querySelectorAll('#cddColMenu .cdd-item').forEach(function(i){i.classList.remove('selected');});
    el.classList.add('selected');
    document.getElementById('cddColMenu').style.display='none';
    document.getElementById('cddColBtn').classList.remove('open');
    doSearch(0,true);
}
function pickMode(val,label,el,e){
    if(e){e.stopPropagation();}
    pMode=val;
    localStorage.setItem('ff_dashboard_mode',pMode);
    document.getElementById('cddModeLabel').textContent=label;
    document.querySelectorAll('#cddModeMenu .cdd-item').forEach(function(i){i.classList.remove('selected');});
    el.classList.add('selected');
    document.getElementById('cddModeMenu').style.display='none';
    document.getElementById('cddModeBtn').classList.remove('open');
    doSearch(curOff,true);
}
document.addEventListener('click',function(e){
    if(!e.target.closest('.cdd-wrap')){closeCdds();}
});
document.querySelectorAll('.cdd-menu').forEach(function(m){
    m.addEventListener('click',function(e){e.stopPropagation();});
});
function changeCol(val){curCol=val;doSearch(0,true);}

/* ✅ DUPLICATE REMOVED: handleThumbError() यहाँ दोबारा defined था, जबकि
   web_assets.py के global JS में यह पहले से है (और वहाँ वाला version बेहतर है —
   पूरा poster-box overlay करता है, सिर्फ़ छोटा span नहीं)। build_page() global JS
   <head> में डालता है और यह script <body> में बाद में आता है, इसलिए यही कमज़ोर
   copy global वाली को shadow कर रही थी — यानी dashboard पर thumbnail-fail हमेशा
   घटिया दिखता था। अब सिर्फ़ global version चलता है। */

function triggerRipple(btn){btn.classList.remove('ripple-go');void btn.offsetWidth;btn.classList.add('ripple-go');setTimeout(function(){btn.classList.remove('ripple-go');},460);}

var isAdminView=false;
var openGroups={};

/* 📄 Ek file ka card (pehle doSearch ke andar forEach me tha — bina badle yahan aa gaya).
   nested=true: group ke andar wala variant card (card-enter animation nahi). */
function cardHtml(f,nested){
            FILE_DATA[f.file_id]=f;
            var sc=(f.source||'primary').toLowerCase();
            if(!['primary','cloud','archive'].includes(sc))sc='primary';

            var encName = encodeURIComponent(f.name || '').replace(/'/g, "%27").replace(/"/g, "%22");
            var encCap = encodeURIComponent(f.caption || '').replace(/'/g, "%27").replace(/"/g, "%22");

            var adminBtns='';
            if(isAdminView){
                adminBtns='<div class="poster-admin">'+
                    '<button class="btn-edit" onclick="event.stopPropagation();editFile(\\''+f.file_id+'\\',\\''+f.raw_collection+'\\',\\''+encName+'\\', \\''+encCap+'\\')">&#9999; Edit</button>'+'<button class="btn-edit" onclick="event.stopPropagation();mergeFile(\\''+f.file_id+'\\')">&#128256; Merge</button>'+
                    '<button class="btn-del" onclick="event.stopPropagation();deleteFile(\\''+f.file_id+'\\',\\''+f.raw_collection+'\\')">&#128465; Delete</button>'+
                    '<button class="btn-edit" onclick="event.stopPropagation();quickGroup(\\''+f.file_id+'\\')">&#128279; Group</button>'+(f.gid?'<button class="btn-edit" onclick="event.stopPropagation();removeFromGroup(\\''+f.gid+'\\',\\''+f.file_id+'\\')">&#10006; Remove</button>':'')+
                '</div>';
            }

            /* ⏱️ Duration chip — sirf tab jab API ne asli duration bheja ho.
               Purani (bina-duration index huyi) files par f.duration khali aata hai,
               tab chip banta hi nahi — "0:00" jaisa bekaar text nahi dikhta. */
            var durChip  = f.duration ? '<span class="dur-chip">'+f.duration+'</span>' : '';
            var durText  = f.duration ? '<span class="tc-dur">'+f.duration+'</span>' : '';
            /* 🖼️ Resolution chip (1280×720 → "720p", 1920×1080 → "1080p") — duration chip
               jaisa hi null-tolerant: data na ho to chip banta hi nahi. */
            var resChip  = f.res ? '<span class="res-chip">'+esc(f.res)+'</span>' : '';
            var resText  = f.res ? '<span class="tc-res">'+esc(f.res)+'</span>' : '';
            var idChip = groupIdChip(f.group_num||f.gid);
            var epLabel = f.group_type==='series' ? (f.episode_label||(f.episode_position?'File '+f.episode_position:'')) : '';
            var epChip = epLabel ? '<span class="episode-chip">'+esc(epLabel)+'</span>' : '';
            var posterTrigger=isAdminView?'<button type="button" class="file-poster-trigger" aria-label="Show file editing options" aria-expanded="false" onclick="toggleAdminBtns(this.closest(\\'.file-card\\'),event)"></button>':'';

            var posterHtml='';
            if(pMode!=='none'){
                posterHtml='<div class="poster-box" id="poster-box-'+f.file_id+'">'+
                    '<img src="'+f.tg_thumb+'" id="img-poster-'+f.file_id+'" class="fc-poster" onload="this.classList.add(\\'loaded\\')" onerror="handleThumbError(\\''+f.file_id+'\\')" loading="lazy" decoding="async">'+
                    '<div class="poster-top">'+
                        idChip+epChip+'<span class="size-chip">'+f.size+'</span>'+
                        durChip+resChip+
                        '<span class="source-pill '+sc+'"><span class="source-dot"></span>'+sc.toUpperCase()+'</span>'+
                    '</div>'+posterTrigger+
                    adminBtns+
                '</div>';
            }

            var textInfo='';
            if(pMode==='none'){
                textInfo='<div class="fc-text-info">'+
                    idChip+epChip+'<span class="tc-size">'+f.size+'</span>'+
                    durText+resText+
                    '<span class="source-pill '+sc+'" style="margin-left:auto"><span class="source-dot"></span>'+sc.toUpperCase()+'</span>'+
                '</div>';
                if(isAdminView){
                    textInfo+='<div class="text-admin-row">'+
                        '<button class="btn-edit" onclick="event.stopPropagation();editFile(\\''+f.file_id+'\\',\\''+f.raw_collection+'\\',\\''+encName+'\\', \\''+encCap+'\\')">&#9999; Edit</button>'+'<button class="btn-edit" onclick="event.stopPropagation();mergeFile(\\''+f.file_id+'\\')">&#128256; Merge</button>'+
                        '<button class="btn-del" onclick="event.stopPropagation();deleteFile(\\''+f.file_id+'\\',\\''+f.raw_collection+'\\')">&#128465; Delete</button>'+
                    '<button class="btn-edit" onclick="event.stopPropagation();quickGroup(\\''+f.file_id+'\\')">&#128279; Group</button>'+(f.gid?'<button class="btn-edit" onclick="event.stopPropagation();removeFromGroup(\\''+f.gid+'\\',\\''+f.file_id+'\\')">&#10006; Remove</button>':'')+
                    '</div>';
                }
            }

            var textControl=isAdminView&&pMode==='none'?' role="button" tabindex="0" aria-label="Show file editing options" aria-expanded="false" onclick="textFileClick(this,event)" onkeydown="textFileKey(this,event)"':'';
            return '<div class="file-card'+(nested?'':' card-enter')+(SEL[f.file_id]?' sel':'')+(textControl?' text-file-trigger':'')+'" data-fid="'+esc(f.file_id)+'"'+textControl+'>'+
                posterHtml+
                textInfo+
                '<div class="fc-body">'+
                    '<button type="button" class="fc-name" id="name-title-'+esc(f.file_id)+'" onclick="playDashboardFile(this.closest(\\'.file-card\\').getAttribute(\\'data-fid\\'),this.closest(\\'.file-card\\'))">'+esc(f.name)+'</button>'+
                '</div>'+
            '</div>';
}

var GROUP_DATA={},FILE_DATA={},SEL={},selMode=false;
function playDashboardFile(fid,card){if(selMode){if(card)toggleSel(card);return;}var f=FILE_DATA[fid];if(f)openInlinePlayer(f.stream_id||f.file_id,f.name);}
function esc(x){return String(x==null?'':x).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
function unesc(x){var t=document.createElement('textarea');t.innerHTML=String(x||'');return t.value;}
function groupIdChip(id,pending){
    if(!id&&!pending)return '';
    return '<span class="group-id-chip'+(!id?' pending':'')+'" title="'+(id?'Saved group ID':'Group could not be saved')+'">'+(id?'GROUP #'+esc(id):'ID PENDING')+'</span>';
}
function qlabel(f){var m=String(f.res||'').match(/(\\d{3,5})\\D+(\\d{3,5})/);if(m){var h=Math.max(+m[2],Math.round(+m[1]*9/16));var L=[[4000,'8K'],[2000,'2160p'],[1300,'1440p'],[1000,'1080p'],[650,'720p'],[450,'480p'],[330,'360p'],[220,'240p']];for(var i=0;i<L.length;i++){if(h>=L[i][0])return L[i][1];}return h+'p';}return f.ql||'?';}

/* One clear card per saved group; its type and stable ID stay visible in both modes. */
function groupHtml(g){
    GROUP_DATA[g.key]=g;
    g.variants.forEach(function(v){FILE_DATA[v.file_id]=v;});
    var open=openGroups[g.key]?' open':'';
    var series=g.group_type==='series',chips='';
    if(series){
        g.variants.slice(0,3).forEach(function(v,i){
            chips+='<span class="episode-chip">'+esc(v.episode_label||('File '+(v.episode_position||i+1)))+'</span>';
        });
        if(g.count>3)chips+='<span class="episode-chip">+'+(g.count-3)+' more</span>';
    }else{
        (g.chips||[]).forEach(function(c){
            chips+='<span class="grp-chip">'+esc(c.label)+(c.count>1?' <i>×'+c.count+'</i>':'')+'</span>';
        });
    }
    var srcs=(g.sources&&g.sources.length)?g.sources:[(g.source||'primary').toLowerCase()];
    var sc=srcs.length>1?'mixed':srcs[0];
    if(!['primary','cloud','archive','mixed'].includes(sc))sc='primary';
    var pill='<span class="source-pill '+sc+'" title="'+esc(srcs.join(' + ').toUpperCase())+'"><span class="source-dot"></span>'+sc.toUpperCase()+'</span>';
    var dur=!series&&g.duration?'<span class="dur-chip">'+esc(g.duration)+'</span>':'';
    var idChip=groupIdChip(g.num||g.gid,true);
    var badge='<span class="grp-badge">'+(series?(g.episode_count==null?g.count:g.episode_count):g.count)+(series?' EPISODES':' QUALITY')+'</span>';
    var adm='';
    if(isAdminView){
        adm='<button class="btn-edit" onclick="event.stopPropagation();editGroup(\\''+g.key+'\\')">&#9999; '+(g.manual?'Edit Group':'Save / Edit')+'</button>'+
            '<button class="btn-edit" onclick="event.stopPropagation();mergeGroup(\\''+g.key+'\\')">&#128256; Merge</button>'+
            (g.manual?'<button class="btn-del" onclick="event.stopPropagation();ungroup(\\''+g.gid+'\\')">&#128465; Ungroup</button>':'');
    }
    var poster='';
    if(pMode!=='none'){
        poster='<div class="poster-box">'+
            (g.tg_thumb?'<img src="'+g.tg_thumb+'" class="fc-poster" onload="this.classList.add(\\'loaded\\')" onerror="this.style.display=\\'none\\'" loading="lazy" decoding="async">':'')+
            '<div class="poster-top">'+idChip+badge+dur+pill+'</div>'+
            '<div class="grp-bottom">'+chips+'</div>'+
            '<button type="button" class="group-poster-trigger" aria-label="'+(isAdminView?'Show group editing options':'Open group')+'" aria-expanded="'+(!isAdminView&&open?'true':'false')+'" onclick="grpPoster(this,event)"></button>'+
            (isAdminView?'<div class="poster-admin">'+adm+'</div>':'')+
        '</div>';
    }
    var textTrigger=isAdminView&&pMode==='none'?' role="button" tabindex="0" aria-label="Show group editing options" aria-expanded="false" onkeydown="textGroupKey(this.closest(\\'.grp-card\\'),event)"':'';
    var textInfo='<div class="grp-textinfo"'+textTrigger+'>'+idChip+badge+dur+chips+pill+'</div>'+
        ((isAdminView&&pMode==='none')?'<div class="grp-textadmin">'+adm+'</div>':'');
    var inner='';
    g.variants.forEach(function(v){inner+=cardHtml(v,true);});
    var textCard=isAdminView&&pMode==='none';
    var textCardClick=textCard?' onclick="textGroupClick(this,event)"':'';
    var headControl=textCard?' data-text-trigger role="button" tabindex="0" aria-label="Show group editing options" aria-expanded="false" onkeydown="textGroupKey(this.closest(\\'.grp-card\\'),event)"':' role="button" tabindex="0" aria-label="Collapse group" onclick="toggleGroup(this.parentNode)" onkeydown="if(event.target===this &amp;&amp; (event.key===\\'Enter\\' || event.key===\\' \\')){event.preventDefault();toggleGroup(this.parentNode)}"';
    return '<div class="grp-card card-enter'+open+'" data-gk="'+g.key+'"'+textCardClick+'>'+
        '<div class="grp-master">'+poster+
            '<div class="grp-body"><button type="button" class="grp-title grp-title-button" aria-expanded="'+(open?'true':'false')+'" aria-controls="gv-'+esc(g.key)+'" onclick="event.stopPropagation();toggleGroup(this.closest(\\'.grp-card\\'))">'+g.title+'</button>'+textInfo+'</div>'+
        '</div>'+
        '<div class="grp-openhead"'+headControl+'>'+idChip+badge+dur+'<button type="button" class="grp-title grp-open-title" onclick="event.stopPropagation();toggleGroup(this.closest(\\'.grp-card\\'))">'+g.title+'</button>'+(isAdminView?'<span class="grp-oadmin">'+adm+'</span>':'')+'<span class="grp-arrow">&#9662;</span></div>'+
        '<div class="grp-variants" id="gv-'+esc(g.key)+'">'+inner+'</div>'+
    '</div>';
}
/* Thumbnail click: admin ko edit popup, baaki users ke liye group khulta hai (title click se bhi khulta hai) */
function grpPoster(el,e){
    var card=el.closest('.grp-card');
    e.stopPropagation();
    if(!isAdminView){toggleGroup(card);return;}
    var was=card.classList.contains('grp-active');
    document.querySelectorAll('.grp-card.grp-active').forEach(function(c){setGroupMenu(c,false);});
    document.querySelectorAll('.file-card.admin-active').forEach(function(c){setFileMenu(c,false);});
    if(!was)setGroupMenu(card,true);
}
function textGroupClick(card,e){
    if(e.target.closest('.file-card,.grp-title-button,.grp-open-title,.grp-textadmin,.grp-oadmin'))return;
    grpPoster(card,e);
}
function textGroupKey(card,e){
    if(e.target!==e.currentTarget||!(e.key==='Enter'||e.key===' '))return;
    e.preventDefault();grpPoster(card,e);
}
document.addEventListener('click',function(){
    document.querySelectorAll('.grp-card.grp-active').forEach(function(c){setGroupMenu(c,false);});
});
function toggleGroup(el){
    var k=el.getAttribute('data-gk'),title=el.querySelector('.grp-title-button'),head=el.querySelector('.grp-openhead');
    var openTitle=el.querySelector('.grp-open-title');
    var focusWasTitle=document.activeElement===title,focusWasHead=document.activeElement===head||document.activeElement===openTitle;
    if(isAdminView)setGroupMenu(el,false);
    el.querySelectorAll('.file-card.admin-active').forEach(function(c){setFileMenu(c,false);});
    var isOpen=el.classList.toggle('open');
    if(title)title.setAttribute('aria-expanded',isOpen?'true':'false');
    if(!isAdminView){var poster=el.querySelector('.group-poster-trigger');if(poster)poster.setAttribute('aria-expanded',isOpen?'true':'false');}
    if(isOpen){openGroups[k]=1;if(focusWasTitle&&head)(head.hasAttribute('data-text-trigger')?openTitle:head).focus();}
    else{delete openGroups[k];if(focusWasHead&&title)title.focus();}
}

/* ───────── 🛠️ ADMIN: group banana / edit / select-mode ───────── */
async function grpPost(url,body){
    var r=await fetch(url,{method:'POST',body:JSON.stringify(body),headers:{'Content-Type':'application/json'}});
    var d={};try{d=await r.json();}catch(e){}
    if(!r.ok||d.error){var err=new Error(d.error||('HTTP '+r.status));err.status=r.status;err.code=d.code||'';throw err;}
    return d;
}
async function fetchGroupPreview(id,signal){
    var r=await fetch('/api/group/preview?id='+encodeURIComponent(id),{cache:'no-store',signal:signal});
    var d={};try{d=await r.json();}catch(e){}
    if(!r.ok||d.error){var err=new Error(d.error||('HTTP '+r.status));err.status=r.status;throw err;}
    var g=d.group;
    if(!g||String(g.id)!==id||!(/^[0-9a-f]{64}$/).test(g.signature||''))throw new Error('Could not verify this group. Please try again.');
    return g;
}
function targetPreviewHtml(g){
    var url=String(g.cover||''),safe=url.indexOf('/api/thumb?')===0||url.indexOf('/api/group/thumb?')===0;
    var image=safe?'<img src="'+esc(url)+'" alt="" onerror="this.hidden=true">':'';
    var kind=g.group_type==='series'?'Series / episodes':'Quality versions';
    var h='<div class="target-preview"><div class="target-head"><div class="target-image-wrap">'+
        '<div class="target-image"><span aria-hidden="true">&#127916;</span>'+image+'</div><small>'+esc(safe?(g.cover_label||'Preview'):'No image')+'</small></div>'+
        '<div class="target-meta"><span class="target-overline">Destination group</span><div class="target-name">'+esc(g.name||'Untitled group')+'</div>'+
        '<div class="target-badges"><span class="target-badge id">GROUP #'+esc(g.id)+'</span><span class="target-badge kind">'+esc(kind)+'</span>'+
        '<span class="target-badge">'+esc(g.count)+' files</span></div></div></div>';
    var members=Array.isArray(g.members)?g.members:[];
    h+='<div class="target-list-label">Files in this group'+(g.more?' (sample)':'')+'</div>';
    if(!members.length)h+='<div class="target-more">No saved files.</div>';
    else{
        h+='<ul class="target-members">';
        members.forEach(function(f){
            var meta=[f.label,f.source].filter(Boolean).join(' · ');
            h+='<li>'+esc(f.name||'File unavailable')+(meta?'<small>'+esc(meta)+'</small>':'')+'</li>';
        });
        h+='</ul>';
        if(g.more)h+='<div class="target-more">+'+esc(g.more)+' more files</div>';
    }
    return h+'</div>';
}
function selCount(){return Object.keys(SEL).length;}
function ensureAdminMenu(){
    var m=document.getElementById('cddGfMenu');
    if(!m||!isAdminView||document.getElementById('gfScanItem'))return;
    var d=document.createElement('div');
    d.id='gfScanItem';d.className='cdd-item';d.style.borderTop='1px solid var(--border)';d.style.color='#ffd166';
    d.innerHTML='&#9881; Scan all &amp; build groups';
    d.onclick=function(e){scanAllGroups(e);};
    m.appendChild(d);
}
var scanTimer=null;
async function scanAllGroups(e){
    if(e)e.stopPropagation();
    closeCdds();
    if(!confirm('Poori library scan karke permanent groups banayein? (40k files me kuch minute lag sakte hain)'))return;
    try{
        var r=await fetch('/api/group/scan_all',{method:'POST'}),d=await r.json();
        if(d.error)throw new Error(d.error);
        showToast(d.started?'Scan shuru ho gaya...':'Scan pehle se chal raha hai');
        clearInterval(scanTimer);
        scanTimer=setInterval(async function(){
            try{
                var s=await (await fetch('/api/group/scan_status')).json();
                if(s.running){showToast('Scan: '+s.phase+' ('+s.scanned+'/'+s.total+')');}
                else{
                    clearInterval(scanTimer);
                    if(s.error){showToast('Scan error: '+s.error,'error');}
                    else{showToast('Scan complete: '+s.created+' naye groups, '+s.added+' files jodi');refreshGridAfterEdit();}
                }
            }catch(x){}
        },3000);
    }catch(err){showToast(err.message,'error');}
}
function renderSelBar(){
    ensureAdminMenu();
    var bar=document.getElementById('selBar'),fab=document.getElementById('selFab');
    if(!isAdminView){if(bar)bar.remove();if(fab)fab.remove();return;}
    if(!fab){fab=document.createElement('button');fab.id='selFab';fab.className='sel-fab';fab.onclick=function(){toggleSelMode();};document.body.appendChild(fab);}
    fab.style.display=selMode?'none':'block';
    fab.innerHTML='&#9745; Group Mode';
    if(!selMode){if(bar)bar.remove();return;}
    if(!bar){bar=document.createElement('div');bar.id='selBar';bar.className='sel-bar';document.body.appendChild(bar);}
    var n=selCount();
    bar.innerHTML='<span>'+n+' selected</span>'+
        '<button onclick="openSelectedGroup()"'+(n?'':' disabled style="opacity:.5"')+'>&#128279; Group</button>'+
        '<button class="alt" onclick="toggleSelMode()">Cancel</button>';
}
function toggleSelMode(on){
    selMode=(typeof on==='boolean')?on:!selMode;
    var rd=document.getElementById('results');
    if(rd)rd.classList.toggle('sel-mode',selMode);
    if(!selMode){SEL={};document.querySelectorAll('.file-card.sel').forEach(function(c){c.classList.remove('sel');});}
    renderSelBar();
}
function toggleSel(card){
    var fid=card.getAttribute('data-fid');if(!fid)return;
    if(SEL[fid]){delete SEL[fid];card.classList.remove('sel');}
    else{SEL[fid]=FILE_DATA[fid]||{file_id:fid};card.classList.add('sel');}
    renderSelBar();
}
function quickGroup(fid){
    toggleSelMode(true);
    var c=document.querySelector('.file-card[data-fid="'+fid+'"]');
    if(c&&!SEL[fid])toggleSel(c);
}
document.addEventListener('click',function(e){
    if(!selMode)return;
    var c=e.target.closest&&e.target.closest('.file-card[data-fid]');
    if(!c)return;
    e.preventDefault();e.stopPropagation();
    toggleSel(c);
},true);

function openSelectedGroup(){
    var m=Object.keys(SEL).map(function(k){return FILE_DATA[k]||SEL[k];});
    if(!m.length)return;
    var nm=String(m[0].name||'').replace(/[.](mp4|mkv|avi|mov|webm|m4v|ts)$/i,'').replace(/(^|[^A-Za-z0-9])(240|360|480|540|576|720|1080|1440|2160)[pP]([^A-Za-z0-9]|$)/g,' ').replace(/ +/g,' ').trim();
    openGroupModal({mode:'create',name:nm,members:m});
}
function editGroup(key){
    var g=GROUP_DATA[key];if(!g)return;
    openGroupModal({mode:g.manual?'edit':'create',gid:g.gid,num:g.num,name:unesc(g.title),
        members:g.variants.slice(),groupType:g.group_type||'quality',thumbFid:g.thumb_fid||'',custom:!!g.custom_thumb});
}
var MERGE=null,mergeTimer=null,mergeSeq=0,mergeAbort=null;
function closeMergeModal(force){
    if(MERGE&&MERGE.saving&&!force){showToast('Please wait for the move to finish.');return;}
    clearTimeout(mergeTimer);++mergeSeq;if(mergeAbort){mergeAbort.abort();mergeAbort=null;}
    var previous=MERGE&&MERGE.returnFocus;MERGE=null;
    var modal=document.getElementById('mergeModal');if(modal)modal.remove();
    if(previous&&previous.isConnected)previous.focus();
}
function mergeModalKey(e){
    if(e.key==='Escape'){e.preventDefault();closeMergeModal();return;}
    if(e.key!=='Tab')return;
    var modal=document.getElementById('mergeModal');if(!modal)return;
    var controls=Array.from(modal.querySelectorAll('button:not([disabled]),input:not([disabled])')).filter(function(el){return el.getClientRects().length;});
    if(!controls.length)return;
    var first=controls[0],last=controls[controls.length-1];
    if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}
    else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
}
function openMergeModal(source){
    if(MERGE&&MERGE.saving)return;
    if(MERGE)closeMergeModal(true);
    MERGE={source:source,target:null,saving:false,returnFocus:document.activeElement};
    var isGroup=source.kind==='group';
    var sourceLabel=isGroup?'GROUP TO MOVE':'FILE TO MOVE';
    var sourceMeta=isGroup?((source.gid?'Group #'+source.gid+' · ':'')+source.items.length+' files'):
        (source.gid?'Currently in group #'+source.gid:'Not in a saved group');
    var warning=isGroup?(source.manual?'All files will move and the original group will be removed. The destination group keeps its ID and type.':
        'All listed files will join the destination group, which keeps its ID and type.'):
        'The file will move from any previous group to the destination group.';
    var h='<div class="edit-modal open" id="mergeModal" role="dialog" aria-modal="true" aria-labelledby="mergeTitle" onclick="if(event.target===this)closeMergeModal()" onkeydown="mergeModalKey(event)">'+
        '<div class="em-card merge-card"><div class="gm-heading"><div><div class="gm-eyebrow">Move to a group</div><div class="gm-title" id="mergeTitle">Review before merging</div>'+
        '<div class="gm-sub">Enter a group ID and check its details before continuing.</div></div><button type="button" class="gm-close" id="mergeClose" aria-label="Close" onclick="closeMergeModal()">&times;</button></div>'+
        '<div class="merge-source"><small>'+sourceLabel+'</small><strong>'+esc(source.name||'Untitled')+'</strong><div>'+esc(sourceMeta)+'</div></div>'+
        '<div class="merge-warning">'+esc(warning)+'</div><label class="gm-label" for="mergeId" style="display:block">DESTINATION GROUP ID</label>'+
        '<div class="merge-id-row"><input class="gm-input" id="mergeId" type="text" inputmode="numeric" maxlength="65" autocomplete="off" placeholder="e.g. 17" oninput="mergeLookup(false)" onkeydown="mergeInputKey(event)">'+
        '<button type="button" id="mergeCheck" class="gm-btn alt" onclick="mergeLookup(true)">Check</button></div>'+
        '<div class="merge-status" id="mergeStatus" role="status" aria-live="polite">Enter the number shown on the destination group.</div><div id="mergePreview" role="region" aria-label="Destination group details" aria-live="polite" hidden></div>'+
        '<label id="mergeConfirmWrap" class="target-confirm" hidden><input type="checkbox" id="mergeConfirm" onchange="mergeConfirmChanged()">'+
        '<span>I checked the destination group and want to move here.</span></label>'+
        '<div class="merge-row"><button type="button" class="gm-btn alt" id="mergeCancel" onclick="closeMergeModal()">Cancel</button>'+
        '<button type="button" class="gm-btn" id="mergeSubmit" onclick="submitMerge()" disabled>Confirm &amp; move</button></div></div></div>';
    document.body.insertAdjacentHTML('beforeend',h);
    document.getElementById('mergeId').focus();
}
function mergeGroup(key){
    var g=GROUP_DATA[key];if(!g)return;
    openMergeModal({kind:'group',name:unesc(g.title),gid:g.manual?String(g.gid||''):'',manual:!!g.manual,
        items:g.variants.map(function(f){return {id:f.file_id,name:f.name};})});
}
function mergeFile(fid){
    var f=FILE_DATA[fid];if(!f)return;
    openMergeModal({kind:'file',name:f.name||'Unknown file',gid:String(f.gid||''),manual:false,
        items:[{id:f.file_id,name:f.name}]});
}
function mergeTargetId(){return String(document.getElementById('mergeId').value||'').trim().replace(/^#/,'').trim();}
function mergeInputKey(e){if(e.key==='Enter'){e.preventDefault();mergeLookup(true);}}
function mergeStatus(text,error){
    var el=document.getElementById('mergeStatus');if(el){el.textContent=text;el.classList.toggle('error',!!error);}
}
function mergeConfirmChanged(){
    var btn=document.getElementById('mergeSubmit'),check=document.getElementById('mergeConfirm');
    if(btn)btn.disabled=!(MERGE&&!MERGE.saving&&MERGE.target&&MERGE.target.id===mergeTargetId()&&check&&check.checked);
}
function mergeLookup(immediate,notice){
    var state=MERGE;if(!state||state.saving)return;
    clearTimeout(mergeTimer);if(mergeAbort){mergeAbort.abort();mergeAbort=null;}
    var seq=++mergeSeq,id=mergeTargetId(),raw=document.getElementById('mergeId').value.trim();
    state.target=null;document.getElementById('mergeConfirm').checked=false;
    document.getElementById('mergeConfirmWrap').hidden=true;
    var preview=document.getElementById('mergePreview');preview.hidden=true;preview.innerHTML='';mergeConfirmChanged();
    if(!raw||raw==='#'){mergeStatus('Enter the number shown on the destination group.');return;}
    if(!/^[0-9]{1,64}$/.test(id)){mergeStatus('Enter a valid numeric group ID.',true);return;}
    if(state.source.gid&&state.source.gid===id){
        mergeStatus(state.source.kind==='file'?'This file is already in group #'+id+'.':'Choose a different group; this is the source group.',true);return;
    }
    mergeStatus('Looking up group #'+id+'...');
    mergeTimer=setTimeout(async function(){
        var controller=new AbortController();mergeAbort=controller;
        try{
            var group=await fetchGroupPreview(id,controller.signal);
            if(MERGE!==state||seq!==mergeSeq||mergeTargetId()!==id)return;
            state.target=group;preview.innerHTML=targetPreviewHtml(group);preview.hidden=false;
            document.getElementById('mergeConfirmWrap').hidden=false;
            mergeStatus(notice||'Check the name, type and files below, then confirm.');mergeConfirmChanged();
        }catch(e){
            if(e.name==='AbortError'||MERGE!==state||seq!==mergeSeq)return;
            mergeStatus(e.message||'Could not load the group. Try again.',true);
        }finally{if(mergeAbort===controller)mergeAbort=null;}
    },immediate?0:250);
}
function mergeSetBusy(busy){
    ['mergeId','mergeCheck','mergeConfirm','mergeClose','mergeCancel'].forEach(function(id){var el=document.getElementById(id);if(el)el.disabled=busy;});
    var btn=document.getElementById('mergeSubmit');if(btn){btn.textContent=busy?'Moving...':'Confirm & move';if(busy)btn.disabled=true;else mergeConfirmChanged();}
}
async function submitMerge(){
    var state=MERGE,check=document.getElementById('mergeConfirm');
    if(!state||state.saving||!state.target||!check||!check.checked||mergeTargetId()!==state.target.id)return;
    var target=state.target,source=state.source;state.saving=true;mergeSetBusy(true);
    try{
        var d=source.kind==='group'&&source.manual?
            await grpPost('/api/group/merge',{source:source.gid,target:target.id,expected_target:target.signature}):
            await grpPost('/api/group/save',{group_id:target.id,items:source.items,expected_target:target.signature});
        state.saving=false;closeMergeModal(true);
        showToast('Moved to group #'+(d.num||target.id)+' · '+(d.group_name||target.name));refreshGridAfterEdit();
    }catch(e){
        if(MERGE!==state)return;
        state.saving=false;mergeSetBusy(false);
        var message=e.code==='target_changed'?'Destination changed. Please review the updated group again.':
            ('Move failed: '+e.message+'. Check the latest group information before retrying.');
        // A failed response can follow a partial write. Refresh the page data and
        // require a fresh preview/confirmation instead of blindly retrying.
        if(e.code!=='target_changed')refreshGridAfterEdit();
        mergeLookup(true,message);
    }
}
async function ungroup(gid){
    if(!confirm('Ungroup karne par files delete nahi hongi aur dobara automatically group nahi hongi. Baad me manually jod sakte hain. Continue?'))return false;
    try{await grpPost('/api/group/delete',{group_id:gid});showToast('Group hata diya');refreshGridAfterEdit();return true;}
    catch(e){showToast(e.message,'error');return false;}
}
async function gmUngroup(){if(await ungroup(GM.gid))closeGroupModal();}
async function removeFromGroup(gid,fid){
    if(!confirm('Is file ko group se hata dein?'))return;
    try{await grpPost('/api/group/remove_file',{group_id:gid,file_id:fid});showToast('Group se hata di');refreshGridAfterEdit();}
    catch(e){showToast(e.message,'error');}
}

var GM={},gmCropper=null,gmSaveInProgress=false,gmPickRequest=0,gmPickAbort=null;
function gmSetBusy(busy){
    var modal=document.getElementById('grpModal');if(!modal)return;
    modal.classList.toggle('gm-saving',busy);modal.setAttribute('aria-busy',busy?'true':'false');
    modal.querySelectorAll('button,input,select,textarea').forEach(function(el){
        if(busy){el.setAttribute('data-gm-was-disabled',el.disabled?'1':'0');el.disabled=true;}
        else if(el.hasAttribute('data-gm-was-disabled')){el.disabled=el.getAttribute('data-gm-was-disabled')==='1';el.removeAttribute('data-gm-was-disabled');}
    });
}
function gmCancelPickLookup(){++gmPickRequest;if(gmPickAbort){gmPickAbort.abort();gmPickAbort=null;}}
function closeGroupModal(){if(gmSaveInProgress){showToast('Please wait for the save to finish.');return;}clearTimeout(gmSearchTimer);++gmSearchRequest;gmCancelPickLookup();if(gmCropper){gmCropper.destroy();gmCropper=null;}var m=document.getElementById('grpModal');if(m)m.remove();}
function gmThumbUrl(f){return '/api/thumb?file_id='+encodeURIComponent(f.file_id)+'&col='+encodeURIComponent(f.raw_collection||'primary')+'&v='+encodeURIComponent(GM.ts);}
function openGroupModal(o){
    if(gmSaveInProgress)return;
    var mode0=o.custom?'custom':(o.thumbFid?'member':'auto');
    GM={mode:o.mode,gid:o.gid||'',num:o.num||'',members:(o.members||[]).map(function(f){return Object.assign({},f);}),
        type:o.groupType==='series'?'series':'quality',seriesOrdered:o.groupType==='series',thumbFid:o.thumbFid||'',thumbMode:mode0,
        hasCustom:!!o.custom,pick:null,pickTarget:null,pickConfirmed:false,savedGid:'',ts:Date.now()+'-'+Math.random().toString(36).slice(2)};
    closeGroupModal();
    var edit=o.mode==='edit';
    var h='<div class="edit-modal open" id="grpModal" role="dialog" aria-modal="true" aria-label="Group editor" onclick="if(event.target===this)closeGroupModal()"><div class="em-card gm-card">'+
        '<div class="gm-heading"><div><div class="gm-eyebrow">Library groups</div><div class="gm-title">'+(edit?'Edit group #'+esc(GM.num):'Create a group')+'</div>'+
        '<div class="gm-sub">'+GM.members.length+' files · Choose how this collection should appear.</div></div>'+
        '<button class="gm-close" aria-label="Close group editor" onclick="closeGroupModal()">&times;</button></div>';
    h+='<div class="gm-label">GROUP NAME</div><input class="gm-input" id="gmName" value="'+esc(o.name||'')+'" placeholder="e.g. The Last Story">';
    if(!edit){
        h+='<div class="gm-label">ADD TO AN EXISTING GROUP <span style="font-weight:500">(optional)</span></div>'+
           '<input class="gm-input" id="gmSearch" placeholder="Search by group name or number" oninput="gmSearchGroups(this.value)">'+
           '<div id="gmGroupList"></div><div id="gmPickStatus" class="gm-note" role="status" aria-live="polite"></div>'+
           '<div id="gmPickNote" class="gm-note gm-join-note" role="region" aria-label="Destination group details" style="display:none"></div>';
    }
    h+='<div id="gmTypeSection"><div class="gm-label">GROUP TYPE</div><fieldset class="gm-type-grid" aria-label="Group type">'+
       '<label><input type="radio" name="gmType" value="quality"'+(GM.type==='quality'?' checked':'')+' onchange="gmChangeType(this.value)">'+
       '<span class="gm-type-option"><strong>🎞️ Quality versions</strong><small>Same title in different resolutions or formats.</small></span></label>'+
       '<label><input type="radio" name="gmType" value="series"'+(GM.type==='series'?' checked':'')+' onchange="gmChangeType(this.value)">'+
       '<span class="gm-type-option"><strong>📺 Series / episodes</strong><small>Multiple episodes, even when filenames are identical.</small></span></label></fieldset>'+
       '<div class="gm-note">Automatic groups start as quality versions. Change the type anytime.</div></div>';
    h+='<div class="gm-label">COVER IMAGE</div><div class="gm-thumbs" id="gmThumbs"></div>'+
       '<input type="file" id="gmFile" accept="image/*" style="display:none" onchange="gmLocalPreview(this)">'+
       '<div id="gmCropWrap" style="display:none;margin-top:10px"></div>';
    h+='<div class="gm-label" id="gmMembersLabel">FILES</div><div id="gmMemberHint" class="gm-note"></div><div id="gmMembers"></div>';
    h+='<div class="gm-row"><button class="gm-btn alt" onclick="closeGroupModal()">Cancel</button>'+
       (edit?'<button class="gm-btn" style="background:rgba(160,8,8,.85)" onclick="gmUngroup()">Ungroup</button>':'')+
       '<button class="gm-btn" id="gmSave" onclick="saveGroupModal()">Save group</button></div>';
    h+='</div></div>';
    document.body.insertAdjacentHTML('beforeend',h);
    gmRenderThumbs();gmRenderMembers();
    if(!edit)gmSearchGroups('');
}
function gmChangeType(type){
    if(type==='series'&&!GM.seriesOrdered){
        GM.members.sort(function(a,b){return (a.episode_position||999999)-(b.episode_position||999999);});
        GM.seriesOrdered=true;
    }
    GM.type=type==='series'?'series':'quality';
    gmRenderMembers();gmRenderThumbs();
}

function gmRenderThumbs(){
    var tm=GM.thumbMode;
    var h='<div class="gm-th gm-auto'+(tm==='auto'?' on':'')+'" onclick="gmPickThumb(\\'auto\\',\\'\\')">AUTO</div>';
    if(GM.hasCustom){
        h+='<div class="gm-th'+(tm==='custom'?' on':'')+'" onclick="gmPickThumb(\\'custom\\',\\'\\')"><img src="/api/group/thumb?gid='+encodeURIComponent(GM.gid)+'&v='+GM.ts+'"><em>CUSTOM</em></div>';
    }
    h+='<div class="gm-th gm-auto'+(tm==='newupload'?' on':'')+'" onclick="document.getElementById(\\'gmFile\\').click()">&#128206; UPLOAD</div>';
    GM.members.forEach(function(f,i){
        var label=GM.type==='series'?(f.episode_custom_label||f.episode_detected_label||('File '+(i+1))):qlabel(f);
        h+='<div class="gm-th'+(tm==='member'&&GM.thumbFid===f.file_id?' on':'')+'" onclick="gmPickThumb(\\'member\\',\\''+f.file_id+'\\')">'+
           '<img src="'+gmThumbUrl(f)+'" loading="lazy"><em>'+esc(label)+'</em></div>';
    });
    var el=document.getElementById('gmThumbs');if(el)el.innerHTML=h;
}
function gmPickThumb(mode,fid){
    GM.thumbMode=mode;GM.thumbFid=(mode==='member')?fid:'';
    if(mode!=='newupload'){
        if(gmCropper){gmCropper.destroy();gmCropper=null;}
        var w=document.getElementById('gmCropWrap');if(w){w.style.display='none';w.innerHTML='';}
        var fi=document.getElementById('gmFile');if(fi)fi.value='';
    }
    gmRenderThumbs();
}
function gmLocalPreview(input){
    if(!input.files||!input.files[0])return;
    var selected=input.files[0],reader=new FileReader();
    GM.thumbMode='newupload';GM.thumbFid='';gmRenderThumbs();
    reader.onload=function(e){
        if(!input.isConnected||!input.files||input.files[0]!==selected)return;
        if(gmCropper){gmCropper.destroy();gmCropper=null;}
        var w=document.getElementById('gmCropWrap');if(!w)return;
        var img=document.createElement('img');img.id='gmCropImg';img.alt='Selected group cover';img.style.maxWidth='100%';img.style.display='block';img.src=e.target.result;
        w.style.display='block';w.replaceChildren(img);
        if(typeof Cropper==='function')gmCropper=new Cropper(img,{aspectRatio:16/9,viewMode:1,background:false,zoomable:true,movable:true});
    };
    reader.onerror=function(){if(input.isConnected){input.value='';GM.thumbMode='auto';gmRenderThumbs();showToast('Could not read the selected image.','error');}};
    reader.readAsDataURL(selected);
}
function gmRenderMembers(){
    var series=GM.type==='series'&&!GM.pick,h='';
    var label=document.getElementById('gmMembersLabel'),hint=document.getElementById('gmMemberHint');
    if(label)label.textContent=series?'SERIES FILES & EPISODE ORDER':'FILES';
    if(hint)hint.textContent=series?'Use the arrows to arrange files. Add an optional episode label if filenames are the same.':'Choose a cover above or remove files from this group.';
    GM.members.forEach(function(f,i){
        var input=series?'<input class="gm-episode-input" maxlength="80" aria-label="Episode label for file '+(i+1)+'" placeholder="'+esc(f.episode_detected_label||'e.g. S01E01 or Episode 1')+'" value="'+esc(f.episode_custom_label||'')+'" oninput="gmSetEpisodeLabel('+i+',this.value)">':'';
        var arrows=series?'<button type="button" aria-label="Move file up" onclick="gmMoveMember('+i+',-1)"'+(i===0?' disabled':'')+'>&uarr;</button>'+
                          '<button type="button" aria-label="Move file down" onclick="gmMoveMember('+i+',1)"'+(i===GM.members.length-1?' disabled':'')+'>&darr;</button>':'';
        h+='<div class="gm-mem"><b>'+esc(series?String(i+1).padStart(2,'0'):qlabel(f))+'</b><div class="gm-mem-main">'+
           '<span class="gm-mem-name" title="'+esc(f.name||'')+'">'+esc(f.name||'Unknown file')+'</span>'+input+'</div>'+
           '<div class="gm-mem-actions">'+arrows+'<button type="button" class="gm-remove" aria-label="Remove file" onclick="gmRemoveMember('+i+')">&times;</button></div></div>';
    });
    var el=document.getElementById('gmMembers');if(el)el.innerHTML=h;
}
function gmSetEpisodeLabel(i,value){if(GM.members[i])GM.members[i].episode_custom_label=value;}
function gmMoveMember(i,direction){
    var j=i+direction;if(j<0||j>=GM.members.length)return;
    var tmp=GM.members[i];GM.members[i]=GM.members[j];GM.members[j]=tmp;
    gmRenderMembers();gmRenderThumbs();
}
async function gmRemoveMember(i){
    var f=GM.members[i];if(!f)return;
    var dissolved=false;
    if(GM.mode==='edit'){
        if(!confirm(GM.members.length<=2?'A group needs at least 2 files. Removing this file will dissolve the group, not delete its files. Continue?':'Remove this file from the group?'))return;
        try{var result=await grpPost('/api/group/remove_file',{group_id:GM.gid,file_id:f.file_id});dissolved=!!result.group_deleted;}
        catch(e){showToast(e.message,'error');return;}
    }
    GM.members.splice(i,1);
    if(GM.thumbFid===f.file_id){GM.thumbFid='';GM.thumbMode='auto';}
    gmRenderThumbs();gmRenderMembers();
    if(GM.mode==='edit'){
        showToast(dissolved?'Group dissolved; files were kept':'File removed from group');
        if(dissolved||!GM.members.length)closeGroupModal();
        refreshGridAfterEdit();
    }
}

var gmSearchTimer,gmSearchRequest=0;
function gmSyncSaveButton(){
    var btn=document.getElementById('gmSave');if(!btn||gmSaveInProgress)return;
    var search=document.getElementById('gmSearch'),searching=GM.mode==='create'&&search&&search.value.trim()&&!GM.pick;
    btn.disabled=!!searching||!!(GM.pick&&(!GM.pickTarget||!GM.pickConfirmed));
}
function gmPickStatus(text,error){
    var el=document.getElementById('gmPickStatus');if(el){el.textContent=text||'';el.classList.toggle('target-error',!!error);}
}
function gmSearchGroups(q){
    clearTimeout(gmSearchTimer);gmCancelPickLookup();
    GM.pick=null;GM.pickTarget=null;GM.pickConfirmed=false;
    var section=document.getElementById('gmTypeSection'),note=document.getElementById('gmPickNote'),list=document.getElementById('gmGroupList');
    if(section)section.style.display='';if(note){note.style.display='none';note.innerHTML='';}
    if(list)list.innerHTML='<div class="gm-note">Searching groups...</div>';
    gmPickStatus(q.trim()?'Select a destination below, or clear the search to create a new group.':'');
    gmRenderMembers();gmSyncSaveButton();
    var request=++gmSearchRequest;
    gmSearchTimer=setTimeout(async function(){
        try{
            var r=await fetch('/api/group/list?q='+encodeURIComponent(q||''),{cache:'no-store'}),d=await r.json(),h='';
            if(request!==gmSearchRequest||!document.getElementById('grpModal'))return;
            if(!r.ok||d.error)throw new Error(d.error||'Could not search groups.');
            (d.groups||[]).forEach(function(g){
                h+='<button type="button" class="gm-pick" data-gid="'+esc(g.id)+'" aria-pressed="false" onclick="gmPickGroup(this)"><span>#'+esc(g.num||g.id)+' '+esc(g.name)+'</span><span>'+esc(g.group_type==='series'?'SERIES':'QUALITY')+' · '+esc(g.count)+' files</span></button>';
            });
            var el=document.getElementById('gmGroupList');if(el)el.innerHTML=h||'<div class="gm-note">No matching groups.</div>';
        }catch(e){
            if(request!==gmSearchRequest||!document.getElementById('grpModal'))return;
            var el=document.getElementById('gmGroupList');if(el)el.innerHTML='';
            gmPickStatus(e.message||'Could not search groups.',true);
        }
    },q?250:0);
}
function gmPickGroup(el){
    var id=el.getAttribute('data-gid'),same=(GM.pick===id);
    gmCancelPickLookup();GM.pick=same?null:id;GM.pickTarget=null;GM.pickConfirmed=false;
    document.querySelectorAll('#gmGroupList .gm-pick').forEach(function(x){x.classList.remove('on');x.setAttribute('aria-pressed','false');});
    if(!same){el.classList.add('on');el.setAttribute('aria-pressed','true');}
    var section=document.getElementById('gmTypeSection'),note=document.getElementById('gmPickNote');
    if(section)section.style.display=same?'':'none';
    if(note){note.style.display='none';note.innerHTML='';}
    gmRenderMembers();gmSyncSaveButton();
    if(same){gmPickStatus((document.getElementById('gmSearch').value||'').trim()?'Select a destination, or clear the search to create a group.':'');}
    else gmLoadPick(id);
}
async function gmLoadPick(id,notice){
    gmCancelPickLookup();var request=gmPickRequest,state=GM,controller=new AbortController();gmPickAbort=controller;
    state.pickTarget=null;state.pickConfirmed=false;gmSyncSaveButton();
    var note=document.getElementById('gmPickNote');if(note){note.style.display='none';note.innerHTML='';}
    gmPickStatus('Looking up group #'+id+'...');
    try{
        var group=await fetchGroupPreview(id,controller.signal);
        if(GM!==state||request!==gmPickRequest||GM.pick!==id||!document.getElementById('grpModal'))return;
        state.pickTarget=group;
        note=document.getElementById('gmPickNote');
        note.innerHTML='<strong>Check the destination before joining.</strong>'+targetPreviewHtml(group)+
            '<label class="target-confirm"><input type="checkbox" id="gmConfirmTarget" onchange="gmConfirmPick(this.checked)">'+
            '<span>I checked this destination group. Its existing type and episode order will be kept.</span></label>';
        note.style.display='block';gmPickStatus(notice||'Confirm the selected group below.');gmSyncSaveButton();
    }catch(e){
        if(e.name==='AbortError'||GM!==state||request!==gmPickRequest||!document.getElementById('grpModal'))return;
        gmPickStatus(e.message||'Could not load the group. Try again.',true);
        note=document.getElementById('gmPickNote');if(note){note.style.display='block';note.innerHTML='<button type="button" class="gm-btn alt" onclick="gmRetryPick()">Retry group lookup</button>';}
    }finally{if(gmPickAbort===controller)gmPickAbort=null;}
}
function gmRetryPick(){if(GM.pick)gmLoadPick(GM.pick);}
function gmConfirmPick(checked){GM.pickConfirmed=!!checked;gmSyncSaveButton();}

async function saveGroupModal(){
    if(gmSaveInProgress)return;
    var btn=document.getElementById('gmSave');
    var name=(document.getElementById('gmName').value||'').trim();
    var create=(GM.mode==='create'),joining=create&&!!GM.pick;
    var search=document.getElementById('gmSearch');
    if(create&&!joining&&search&&search.value.trim()){showToast('Select a destination or clear the group search.','error');return;}
    if(joining&&(!GM.pickTarget||!GM.pickConfirmed||GM.pickTarget.id!==GM.pick)){showToast('Please review and confirm the destination group.','error');return;}
    if(!joining&&!name){showToast('Group ka naam likhiye','error');return;}
    if(create&&!joining&&GM.members.length<2){showToast('Kam se kam 2 files chunein','error');return;}
    if(!GM.members.length){showToast('Koi file select nahi hai','error');return;}
    var episodes=GM.type==='series'?{
        episode_order:GM.members.map(function(f){return f.file_id;}),
        episode_labels:GM.members.filter(function(f){return (f.episode_custom_label||'').trim();}).map(function(f){return {id:f.file_id,label:f.episode_custom_label.trim()};})
    }:{};
    gmSaveInProgress=true;gmSetBusy(true);btn.textContent='Saving...';
    var savedAny=false,gid=GM.gid,num=GM.num;
    try{
        if(create){
            var body={items:GM.members.map(function(f){return {id:f.file_id,name:f.name};}),group_id:GM.pick||'',name:name};
            if(joining)body.expected_target=GM.pickTarget.signature;
            else Object.assign(body,{group_type:GM.type},episodes);
            var d=await grpPost('/api/group/save',body);
            gid=d.group_id;num=d.num;GM.savedGid=gid;savedAny=true;
        }
        var tm=GM.thumbMode,upd={group_id:gid};
        if(!joining){upd.name=name;upd.group_type=GM.type;Object.assign(upd,episodes);}
        if(tm==='member'){
            var tf=GM.members.filter(function(f){return f.file_id===GM.thumbFid;})[0];
            upd.thumb_file_id=GM.thumbFid;upd.thumb_col=(tf&&tf.raw_collection)||'primary';upd.clear_custom=true;
        }else if(tm==='auto'){
            if(!joining){upd.thumb_file_id='';upd.clear_custom=true;}
        }else if(tm==='newupload'){
            upd.thumb_file_id='';
        }
        await grpPost('/api/group/update',upd);savedAny=true;
        if(tm==='newupload'){
            var fi=document.getElementById('gmFile'),file=fi&&fi.files&&fi.files[0],blob=null;
            if(gmCropper){
                var canvas=gmCropper.getCroppedCanvas({width:1280,height:720,imageSmoothingEnabled:true,imageSmoothingQuality:'high'});
                if(!canvas)throw new Error('The cover is not ready to crop');
                blob=await new Promise(function(r){canvas.toBlob(r,'image/jpeg',0.9);});
            }else if(file){blob=file;}
            if(!blob)throw new Error('Could not prepare the group cover');
            if(blob){
                showToast('Thumbnail upload ho raha hai...');
                var fd=new FormData();fd.append('group_id',gid);fd.append('image',blob,'group.jpg');
                var ur=await fetch('/api/group/upload_thumb',{method:'POST',body:fd}),ud={};
                try{ud=await ur.json();}catch(e){}
                if(!ur.ok||ud.error){throw new Error(ud.error||'Thumbnail upload failed');}
            }
        }
        showToast('Group #'+num+' save ho gaya');
        gmSaveInProgress=false;closeGroupModal();
        toggleSelMode(false);
        refreshGridAfterEdit();
    }catch(e){
        gmSaveInProgress=false;gmSetBusy(false);
        if(joining&&!savedAny&&!GM.savedGid){
            if(e.code!=='target_changed')refreshGridAfterEdit();
            btn.textContent='Save group';
            gmLoadPick(GM.pick,e.code==='target_changed'?'Destination changed. Please review it again.':
                'The move did not finish: '+e.message+'. Check the latest destination before retrying.');
            return;
        }
        if(savedAny||GM.savedGid){
            showToast('Group #'+(num||gid)+' saved, but '+e.message+'. Please retry the remaining changes.','error');
        }else{showToast(e.message,'error');}
        // The request may have committed before the network failed. Show any
        // saved changes immediately, but keep an existing editor open for retry.
        refreshGridAfterEdit();
        if(GM.savedGid){closeGroupModal();toggleSelMode(false);}
        else{btn.disabled=false;btn.textContent='Save group';gmSyncSaveButton();}
    }
}

async function doSearch(o,allowEmpty,fresh){
    // After an edit, start a fresh snapshot so moved/new groups appear immediately.
    if(fresh&&typeof o==='string'&&/^g[12]_/.test(o))o=0;
    var q=document.getElementById('q').value.trim();
    if(!q && !allowEmpty){showToast('Please enter a movie name','error');return;}
    curQ=q;curOff=o;if(o===0){curPage=1;offHist=[];pageGroups={};}
    if(q){sessionStorage.setItem('ff_dash_q',q);}else{sessionStorage.removeItem('ff_dash_q');}

    var myReq=++searchReqId;
    var resDiv=document.getElementById('results');
    var qWrap=document.getElementById('qWrap');
    var loadTimer=setTimeout(function(){
        if(myReq!==searchReqId)return;
        if(qWrap)qWrap.classList.add('loading');
    },150);

    try{
        var r=await fetch('/api/search?q='+encodeURIComponent(q)+'&offset='+encodeURIComponent(o)+'&col='+curCol+'&mode='+pMode+'&group=1&gf='+curGF+(fresh?'&fresh=1':''),{cache:'no-store'});
        if(myReq!==searchReqId){clearTimeout(loadTimer);if(qWrap)qWrap.classList.remove('loading');return;}
        clearTimeout(loadTimer);
        if(qWrap)qWrap.classList.remove('loading');
        var d=null;
        try{d=await r.json();}catch(parseErr){d=null;}
        if(myReq!==searchReqId)return;
        if(!r.ok || (d && d.error)){
            var msg=(d && d.error)?d.error:('Error fetching (HTTP '+r.status+')');
            showToast(msg,'error');
            if(!allowEmpty || q){
                resDiv.innerHTML='<div class="empty"><div class="empty-icon">&#9888;</div><p>'+esc(msg)+'</p></div>';
                document.getElementById('pageBox').style.display='none';
            }
            return;
        }
        document.getElementById('resInfo').style.display='none';
        isAdminView=!!d.is_admin;
        if(!d.results||!d.results.length){
            nextOff=d.next_offset;pageGroups[o]=[];
            resDiv.innerHTML = q
                ? '<div class="empty"><div class="empty-icon">&#9888;</div><p>No results for "'+esc(q)+'" on this page.</p>'+(nextOff?'<p>More results may be on the next page.</p>':'')+'</div>'
                : '<div class="empty"><div class="empty-icon">&#8981;</div><p>No files found on this page.</p>'+(nextOff?'<p>More results may be on the next page.</p>':'')+'</div>';
            var emptyPage=document.getElementById('pageBox');emptyPage.style.display=(nextOff||curPage>1)?'flex':'none';
            document.getElementById('pBtn').disabled=(o===0);
            document.getElementById('nBtn').disabled=!nextOff;
            document.getElementById('pgInfo').textContent='Page '+curPage;
            renderSelBar();return;
        }
        var h='';
        /* Group ka poora card ek hi baar: pichhle pages par dikh chuka ho to dobara nahi */
        var earlier={};
        offHist.forEach(function(oo){(pageGroups[oo]||[]).forEach(function(k){earlier[k]=1;});});
        var rows=d.results.filter(function(f){return !(f.group&&earlier[f.key]);});
        pageGroups[o]=rows.filter(function(f){return f.group;}).map(function(f){return f.key;});
        rows.forEach(function(f){
            h+=f.group?groupHtml(f):cardHtml(f,false);
        });
        resDiv.className='res-grid mode-'+pMode+(selMode?' sel-mode':'');
        resDiv.innerHTML=h;
        renderSelBar();
        staggerCards(resDiv);
        nextOff=d.next_offset;
        document.getElementById('pageBox').style.display='flex';
        document.getElementById('pBtn').disabled=(o===0);
        document.getElementById('nBtn').disabled=!nextOff;
        document.getElementById('pgInfo').textContent='Page '+curPage;

        if(nextOff) {
            fetch('/api/search?q='+encodeURIComponent(q)+'&offset='+encodeURIComponent(nextOff)+'&col='+curCol+'&mode='+pMode+'&group=1&gf='+curGF);
        }
    }catch(e){clearTimeout(loadTimer);if(myReq!==searchReqId)return;if(qWrap)qWrap.classList.remove('loading');showToast('Network error','error');}
}

var offHist=[],pageGroups={};
function next(){if(nextOff){offHist.push(curOff);curPage++;doSearch(nextOff,true);scrollTo(0,0);}}
function prev(){if(curPage>1){curPage--;doSearch(offHist.length?offHist.pop():0,true);scrollTo(0,0);}}

document.addEventListener('DOMContentLoaded',function(){
    var q=document.getElementById('q');
    if(q){
        var qLiveTimer;
        q.addEventListener('input',function(){
            clearTimeout(qLiveTimer);
            var val=q.value.trim();
            if(val.length<2){
                searchReqId++;
                curQ='';
                var qw=document.getElementById('qWrap');if(qw)qw.classList.remove('loading');
                var ri=document.getElementById('resInfo');if(ri)ri.style.display='none';
                var pb=document.getElementById('pageBox');if(pb)pb.style.display='none';
                doSearch(0,true);
                return;
            }
            qLiveTimer=setTimeout(function(){doSearch(0);},350);
        });
        q.addEventListener('keydown',function(e){if(e.key==='Enter'){clearTimeout(qLiveTimer);doSearch(0);}});
    }
    var mItems=document.querySelectorAll('#cddModeMenu .cdd-item');
    mItems.forEach(function(i){i.classList.remove('selected');if(i.dataset.val===pMode)i.classList.add('selected');});
    document.getElementById('cddModeLabel').textContent=(pMode==='none')?'\\ud83d\\udcc4 Text Mode':'\\ud83d\\uddbc\\ufe0f Poster Mode';
    var savedQ=sessionStorage.getItem('ff_dash_q');
    if(savedQ && q){q.value=savedQ;doSearch(0);}else{doSearch(0,true);}
});
""".replace("__LIMIT_PLACEHOLDER__", str(MAX_WEB_RESULTS)).replace("__DEFAULT_MEDIA_MODE__", DEFAULT_MEDIA_MODE)

# 🎛️ Default mode dropdown state (centralized via DEFAULT_MEDIA_MODE in web_assets.py)
_MODE_TG_LBL = '\U0001f5bc\ufe0f Poster Mode'
_MODE_NONE_LBL = '\U0001f4c4 Text Mode'
_DEF_MODE_LBL = _MODE_NONE_LBL if DEFAULT_MEDIA_MODE == 'none' else _MODE_TG_LBL
_SEL_TG = ' selected' if DEFAULT_MEDIA_MODE == 'tg' else ''
_SEL_NONE = ' selected' if DEFAULT_MEDIA_MODE == 'none' else ''

# ─────────────────────────────────────────────────────────────────────────────
# 🏠 SEARCH ZONE HTML
# ─────────────────────────────────────────────────────────────────────────────
SEARCH_ZONE = (
    '<div class="search-zone">'
        '<div class="search-row1">'
            '<div class="search-wrap" id="qWrap">'
                '<input class="search-input" id="q" placeholder="Titles, people, genres\u2026">'
                '<span class="search-spinner" id="qSpinner"></span>'
            '</div>'
            '<div class="cdd-wrap gf-wrap" id="cddGfWrap">'
                '<div class="cdd-btn gf-btn" id="cddGfBtn" onclick="toggleCdd(\'gf\')">'
                    '<span id="cddGfLabel">All</span>'
                '</div>'
                '<span class="cdd-arrow">&#9660;</span>'
                '<div class="cdd-menu" id="cddGfMenu" style="display:none">'
                    '<div class="cdd-item selected" data-val="all" onclick="pickGF(\'all\',\'All\',this)">All<span class="cdd-radio"><span class="cdd-radio-dot"></span></span></div>'
                    '<div class="cdd-item" data-val="group" onclick="pickGF(\'group\',\'Groups\',this)">All groups<span class="cdd-radio"><span class="cdd-radio-dot"></span></span></div>'
                    '<div class="cdd-item" data-val="quality" onclick="pickGF(\'quality\',\'Quality\',this)">Quality groups<span class="cdd-radio"><span class="cdd-radio-dot"></span></span></div>'
                    '<div class="cdd-item" data-val="series" onclick="pickGF(\'series\',\'Series\',this)">Series groups<span class="cdd-radio"><span class="cdd-radio-dot"></span></span></div>'
                    '<div class="cdd-item" data-val="single" onclick="pickGF(\'single\',\'Files\',this)">All files (no grouping)<span class="cdd-radio"><span class="cdd-radio-dot"></span></span></div>'
                '</div>'
            '</div>'
        '</div>'
        '<div class="search-row2">'
            '<div class="cdd-wrap" id="cddColWrap">'
                '<div class="cdd-btn" id="cddColBtn" onclick="toggleCdd(\'col\')">'
                    '<span id="cddColLabel">\U0001f4c2 All Collections</span>'
                '</div>'
                '<span class="cdd-arrow">&#9660;</span>'
                '<div class="cdd-menu" id="cddColMenu" style="display:none">'
                    '<div class="cdd-item selected" data-val="all" onclick="pickCol(\'all\',\'\U0001f4c2 All Collections\',this)">\U0001f4c2 All Collections<span class="cdd-radio"><span class="cdd-radio-dot"></span></span></div>'
                    '<div class="cdd-item" data-val="primary" onclick="pickCol(\'primary\',\'\U0001f7e2 Primary\',this)">\U0001f7e2 Primary<span class="cdd-radio"><span class="cdd-radio-dot"></span></span></div>'
                    '<div class="cdd-item" data-val="cloud" onclick="pickCol(\'cloud\',\'\U0001f535 Cloud\',this)">\U0001f535 Cloud<span class="cdd-radio"><span class="cdd-radio-dot"></span></span></div>'
                    '<div class="cdd-item" data-val="archive" onclick="pickCol(\'archive\',\'\U0001f7e0 Archive\',this)">\U0001f7e0 Archive<span class="cdd-radio"><span class="cdd-radio-dot"></span></span></div>'
                '</div>'
            '</div>'
            '<div class="cdd-wrap" id="cddModeWrap">'
                '<div class="cdd-btn" id="cddModeBtn" onclick="toggleCdd(\'mode\')">'
                    '<span id="cddModeLabel">' + _DEF_MODE_LBL + '</span>'
                '</div>'
                '<span class="cdd-arrow">&#9660;</span>'
                '<div class="cdd-menu" id="cddModeMenu" style="display:none">'
                    '<div class="cdd-item' + _SEL_TG + '" data-val="tg" onclick="pickMode(\'tg\',\'\U0001f5bc\ufe0f Poster Mode\',this)">\U0001f5bc\ufe0f Poster Mode<span class="cdd-radio"><span class="cdd-radio-dot"></span></span></div>'
                    '<div class="cdd-item' + _SEL_NONE + '" data-val="none" onclick="pickMode(\'none\',\'\U0001f4c4 Text Mode\',this)">\U0001f4c4 Text Mode<span class="cdd-radio"><span class="cdd-radio-dot"></span></span></div>'
                '</div>'
            '</div>'
        '</div>'
    '</div>'
    '<div class="main" style="padding-top:4px;">'
        '<div class="results-info" id="resInfo" style="padding:0 12px 8px;">'
            '<span class="results-count" id="resCount"></span>'
        '</div>'
        '<div style="padding:0 2px">'
            '<div id="results" class="res-grid">'
                '<div class="empty"><div class="empty-icon">&#8981;</div>'
                '<p>Find your favorite movies and TV shows.</p></div>'
            '</div>'
            '<div class="pagination" id="pageBox" style="display:none;">'
                '<button class="pg-btn" id="pBtn" onclick="prev()" disabled>Previous</button>'
                '<span class="pg-info" id="pgInfo">Page 1</span>'
                '<button class="pg-btn" id="nBtn" onclick="next()">Next</button>'
            '</div>'
        '</div>'
    '</div>'
    '<div class="toast" id="toast"></div>'
)

# ✅ OPTIMIZATION 1: Pre-compile the entire body string ONCE when the app starts.
DASHBOARD_BODY = CARD_CSS + SEARCH_ZONE + f"<script>{JS_ENGINE}</script>"


@dashboard_routes.get('/dashboard')
async def dash(req):
    role, tg_id = await get_auth(req)
    if not role:
        return web.HTTPFound('/login')
    if not await require_active_plan(role, tg_id):
        return web.HTTPFound('/premium_expired')

    return build_page("Home - Fast Finder", DASHBOARD_BODY, "", "dash", role)


@dashboard_routes.get('/logout')
async def logout(req):
    s_user = req.cookies.get('user_session')
    temp.USER_SESSIONS.pop(s_user, None)
    if s_user:
        try:
            await web_db.delete_session(s_user)
        except Exception:
            pass
    res = web.HTTPFound('/login')
    res.del_cookie('user_session', path='/')
    return res


@dashboard_routes.get('/premium_expired')
async def premium_expired(req):
    role, tg_id = await get_auth(req)
    if not role:
        return web.HTTPFound('/login')
    content = (
        '<div style="text-align:center;">'
        '<div style="font-size:50px;margin-bottom:15px;">&#9203;</div>'
        '<p style="color:var(--muted);margin-bottom:30px;">Your access to Fast Finder Web has expired. '
        'Please renew your plan via our Telegram Bot.</p>'
        '<div class="scard red" style="text-align:left;margin-bottom:25px;padding:15px;">'
        '<div class="scard-label">How to Renew?</div>'
        '<div class="scard-sub" style="color:var(--text)">1. Go to Telegram Bot</div>'
        '<div class="scard-sub" style="color:var(--text)">2. Use command <b>/plan</b></div>'
        '<div class="scard-sub" style="color:var(--text)">3. Pay & Activate instantly</div>'
        '</div>'
        f'<a href="https://t.me/{temp.U_NAME}" class="submit-btn" style="text-decoration:none;display:block;">Open Telegram Bot</a>'
        '<a href="/logout" style="display:block;margin-top:20px;color:var(--muted);text-decoration:none;">Sign Out</a>'
        '</div>'
    )
    return build_page("Premium Expired", form_wrapper("Premium Expired", content), "login-bg")


# ✅ OPTIMIZATION 2: Koyeb Health Check Route
# ✅ DEDUPE: /health पहले यहाँ और bot.py — दोनों में रजिस्टर था। web/__init__.py
# पहले चलने की वजह से यही वाला match होता था, bot.py वाला कभी execute नहीं होता था
# (dead code)। अब route एक ही है, और bot.py वाले handler का useful हिस्सा (uptime)
# यहाँ merge कर दिया गया है।
@dashboard_routes.get('/health')
async def koyeb_health_check(req):
    return web.json_response({
        "status": "alive",
        "platform": "koyeb",
        "uptime_seconds": round(time.time() - temp.START_TIME, 2),
    })
