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
.source-pill.mixed{color:#ffd166;border-color:rgba(255,209,102,.55);background:rgba(120,90,0,.4)}
.source-pill.mixed .source-dot{background:#ffd166}
/* ── Group filter button (red, small) ── */
.gf-btn{width:auto!important;min-width:74px;background:var(--accent)!important;border-color:var(--accent)!important;color:#fff!important;padding:8px 26px 8px 14px!important;justify-content:center}
.gf-wrap{flex:0 0 auto}
.gf-wrap .cdd-arrow{color:#fff!important}
.gf-wrap .cdd-menu{left:auto;right:0;transform:none;min-width:130px}
/* ── Quality group card (master thumbnail = single file jaisa bada poster) ── */
.grp-card{background:var(--card);border:1px solid var(--border);border-radius:10px;overflow:hidden;display:flex;flex-direction:column;position:relative;cursor:pointer;box-shadow:0 4px 10px rgba(0,0,0,.2);transition:border-color .2s,box-shadow .2s}
.grp-card:hover,.grp-card.open{border-color:var(--accent)}
.grp-card:hover .fc-poster{transform:scale(1.08)}
.grp-card.open{grid-column:1/-1;box-shadow:0 8px 28px rgba(0,0,0,.45);cursor:default}
.grp-badge{background:rgba(229,9,20,.92);color:#fff;border-radius:5px;padding:3px 8px;font-size:10px;font-weight:800;letter-spacing:.5px;border:1px solid rgba(255,255,255,.18);line-height:1.4;white-space:nowrap}
.grp-bottom{position:absolute;left:0;right:0;bottom:0;display:flex;flex-wrap:wrap;gap:5px;padding:28px 8px 8px;background:linear-gradient(transparent,rgba(0,0,0,.88));z-index:3}
.grp-chip{background:rgba(0,0,0,.65);backdrop-filter:blur(6px);color:#ffd166;border:1px solid rgba(255,209,102,.38);border-radius:5px;font-size:10px;font-weight:800;padding:2px 8px;line-height:1.5}
.grp-chip i{font-style:normal;opacity:.75}
.grp-body{padding:10px 11px 12px}
.grp-title{color:var(--text);font-size:12.5px;font-weight:600;line-height:1.45;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.grp-card.open .grp-title{-webkit-line-clamp:unset}
.grp-textinfo{display:none;align-items:center;gap:6px;flex-wrap:wrap;margin-top:8px}
.res-grid.mode-none .grp-textinfo{display:flex}
.grp-textinfo .grp-chip{background:var(--bg3)}
.grp-openhead{display:none;align-items:center;gap:10px;flex-wrap:wrap;padding:12px 14px;cursor:pointer}
.grp-openhead .grp-title{flex:1;min-width:140px}
.grp-openhead .grp-chip{background:var(--bg3)}
.grp-arrow{margin-left:auto;color:var(--muted);font-size:13px;transform:rotate(180deg)}
.grp-card.open .grp-openhead{display:flex}
.grp-card.open .grp-master{display:none}
.grp-textadmin{display:none;gap:5px;padding-top:8px}
.grp-card.grp-active .grp-textadmin{display:flex}
.grp-card.grp-active .grp-master .poster-admin{opacity:1;transform:translateY(0);pointer-events:all}
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
.gm-card{max-width:560px!important}
.gm-label{font-size:11px;font-weight:800;color:var(--muted);letter-spacing:.5px;margin:14px 0 6px}
.gm-input{width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:11px;border-radius:8px;font-size:13px;font-family:inherit;outline:none}
.gm-thumbs{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:8px}
.gm-th{position:relative;border:2px solid var(--border);border-radius:8px;overflow:hidden;cursor:pointer;background:var(--bg3);aspect-ratio:16/9}
.gm-th img{width:100%;height:100%;object-fit:cover;display:block}
.gm-th.on{border-color:#22c55e}
.gm-th em{position:absolute;left:0;right:0;bottom:0;font-style:normal;font-size:10px;font-weight:800;color:#ffd166;background:rgba(0,0,0,.75);padding:2px 5px}
.gm-auto{display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:800;color:var(--muted)}
.gm-mem{display:flex;align-items:center;gap:8px;padding:7px 0;border-bottom:1px solid var(--border);font-size:12px;color:var(--text)}
.gm-mem b{color:#ffd166;font-size:11px;min-width:46px}
.gm-mem span{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.gm-mem button{background:rgba(160,8,8,.78);border:none;color:#fff;border-radius:6px;padding:4px 8px;font-size:11px;font-weight:800;cursor:pointer}
.gm-row{display:flex;gap:8px;margin-top:18px}
.gm-row .gm-btn{flex:1;padding:12px}
.gm-pick{padding:8px 10px;border:1px solid var(--border);border-radius:8px;margin-top:6px;font-size:12px;font-weight:700;color:var(--text);cursor:pointer;display:flex;justify-content:space-between}
.gm-pick.on{border-color:#22c55e;color:#22c55e}
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
            var resChip  = f.res ? '<span class="res-chip">'+f.res+'</span>' : '';
            var resText  = f.res ? '<span class="tc-res">'+f.res+'</span>' : '';

            var posterHtml='';
            if(pMode!=='none'){
                posterHtml='<div class="poster-box" id="poster-box-'+f.file_id+'" onclick="toggleAdminBtns(this.closest(\\'.file-card\\'),event)">'+
                    '<img src="'+f.tg_thumb+'" id="img-poster-'+f.file_id+'" class="fc-poster" onload="this.classList.add(\\'loaded\\')" onerror="handleThumbError(\\''+f.file_id+'\\')" loading="lazy" decoding="async">'+
                    '<div class="poster-top">'+
                        '<span class="type-chip">'+f.type.toUpperCase()+'</span>'+
                        '<span class="size-chip">'+f.size+'</span>'+
                        durChip+resChip+
                        '<span class="source-pill '+sc+'"><span class="source-dot"></span>'+sc.toUpperCase()+'</span>'+
                    '</div>'+
                    adminBtns+
                '</div>';
            }

            var textInfo='';
            if(pMode==='none'){
                textInfo='<div class="fc-text-info" onclick="toggleAdminBtns(this.closest(\\'.file-card\\'),event)">'+
                    '<span class="tc-type">'+f.type.toUpperCase()+'</span>'+
                    '<span class="tc-size">'+f.size+'</span>'+
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

            return '<div class="file-card'+(nested?'':' card-enter')+(SEL[f.file_id]?' sel':'')+'" data-fid="'+f.file_id+'">'+
                posterHtml+
                textInfo+
                '<div class="fc-body">'+
                    '<div class="fc-name" id="name-title-'+f.file_id+'" onclick="window.open(\\''+f.watch+'\\',\\'_blank\\')">'+f.name+'</div>'+
                '</div>'+
            '</div>';
}

var GROUP_DATA={},FILE_DATA={},SEL={},selMode=false;
function esc(x){return String(x==null?'':x).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function unesc(x){var t=document.createElement('textarea');t.innerHTML=String(x||'');return t.value;}
function qlabel(f){var m=String(f.res||'').match(/(\\d{3,5})\\D+(\\d{3,5})/);if(m){var h=Math.max(+m[2],Math.round(+m[1]*9/16));var L=[[4000,'8K'],[2000,'2160p'],[1300,'1440p'],[1000,'1080p'],[650,'720p'],[450,'480p'],[330,'360p'],[220,'240p']];for(var i=0;i<L.length;i++){if(h>=L[i][0])return L[i][1];}return h+'p';}return f.ql||'?';}

/* 🗂️ Group card: bina-group file jaisa hi bada master thumbnail; thumbnail ke andar
   upar "N QUALITIES" aur neeche har quality ka chip. Tap par poora group khulta hai. */
function groupHtml(g){
    GROUP_DATA[g.key]=g;
    g.variants.forEach(function(v){FILE_DATA[v.file_id]=v;});
    var open=openGroups[g.key]?' open':'';
    var chips='';
    (g.chips||[]).forEach(function(c){
        chips+='<span class="grp-chip">'+c.label+(c.count>1?' <i>x'+c.count+'</i>':'')+'</span>';
    });
    /* Group ki files alag-alag collection me ho sakti hain: ek hi source ho to wahi tag, warna MIXED */
    var srcs=(g.sources&&g.sources.length)?g.sources:[(g.source||'primary').toLowerCase()];
    var sc=srcs.length>1?'mixed':srcs[0];
    if(!['primary','cloud','archive','mixed'].includes(sc))sc='primary';
    var pill='<span class="source-pill '+sc+'" title="'+srcs.join(' + ').toUpperCase()+'"><span class="source-dot"></span>'+sc.toUpperCase()+'</span>';
    var dur=g.duration?'<span class="dur-chip">'+g.duration+'</span>':'';
    var badge='<span class="grp-badge">'+g.count+' QUALITIES</span>';
    var type=String(g.type||'VIDEO').toUpperCase();
    /* Admin buttons — file card ki tarah click par popup hote hain */
    var adm='';
    if(isAdminView){
        adm='<button class="btn-edit" onclick="event.stopPropagation();editGroup(\\''+g.key+'\\')">&#9999; '+(g.manual?'Edit Group #'+g.num:'Save as Group')+'</button>'+
            '<button class="btn-edit" onclick="event.stopPropagation();mergeGroup(\\''+g.key+'\\')">&#128256; Merge</button>'+
            (g.manual?'<button class="btn-del" onclick="event.stopPropagation();ungroup(\\''+g.gid+'\\')">&#128465; Ungroup</button>':'');
    }
    var poster='';
    if(pMode!=='none'){
        poster='<div class="poster-box" onclick="grpPoster(this,event)">'+
            (g.tg_thumb?'<img src="'+g.tg_thumb+'" class="fc-poster" onload="this.classList.add(\\'loaded\\')" onerror="this.style.display=\\'none\\'" loading="lazy" decoding="async">':'')+
            '<div class="poster-top"><span class="type-chip">'+type+'</span>'+badge+dur+pill+'</div>'+
            '<div class="grp-bottom">'+chips+'</div>'+
            (isAdminView?'<div class="poster-admin">'+adm+'</div>':'')+
        '</div>';
    }
    var textInfo='<div class="grp-textinfo" onclick="grpPoster(this,event)"><span class="tc-type">'+type+'</span>'+badge+dur+chips+pill+'</div>'+
        ((isAdminView&&pMode==='none')?'<div class="grp-textadmin">'+adm+'</div>':'');
    var inner='';
    g.variants.forEach(function(v){inner+=cardHtml(v,true);});
    return '<div class="grp-card card-enter'+open+'" data-gk="'+g.key+'">'+
        '<div class="grp-master">'+poster+
            '<div class="grp-body"><div class="grp-title" onclick="event.stopPropagation();toggleGroup(this.closest(\\'.grp-card\\'))">'+g.title+'</div>'+textInfo+'</div>'+
        '</div>'+
        '<div class="grp-openhead" onclick="toggleGroup(this.parentNode)">'+badge+'<div class="grp-title">'+g.title+'</div><span class="grp-chips" style="display:flex;gap:5px;flex-wrap:wrap">'+chips+'</span>'+(isAdminView?'<span class="grp-oadmin">'+adm+'</span>':'')+'<span class="grp-arrow">&#9662;</span></div>'+
        '<div class="grp-variants">'+inner+'</div>'+
    '</div>';
}
/* Thumbnail click: admin ko edit popup, baaki users ke liye group khulta hai (title click se bhi khulta hai) */
function grpPoster(el,e){
    var card=el.closest('.grp-card');
    if(!isAdminView){toggleGroup(card);return;}
    e.stopPropagation();
    var was=card.classList.contains('grp-active');
    document.querySelectorAll('.grp-card.grp-active').forEach(function(c){c.classList.remove('grp-active');});
    document.querySelectorAll('.file-card.admin-active').forEach(function(c){c.classList.remove('admin-active');});
    if(!was)card.classList.add('grp-active');
}
document.addEventListener('click',function(){
    document.querySelectorAll('.grp-card.grp-active').forEach(function(c){c.classList.remove('grp-active');});
});
function toggleGroup(el){
    var k=el.getAttribute('data-gk');
    var isOpen=el.classList.toggle('open');
    if(isOpen){openGroups[k]=1;}else{delete openGroups[k];}
}

/* ───────── 🛠️ ADMIN: group banana / edit / select-mode ───────── */
async function grpPost(url,body){
    var r=await fetch(url,{method:'POST',body:JSON.stringify(body),headers:{'Content-Type':'application/json'}});
    var d={};try{d=await r.json();}catch(e){}
    if(!r.ok||d.error){throw new Error(d.error||('HTTP '+r.status));}
    return d;
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
    var nm=unesc(m[0].name||'').replace(/[.](mp4|mkv|avi|mov|webm|m4v|ts)$/i,'').replace(/(^|[^A-Za-z0-9])(240|360|480|540|576|720|1080|1440|2160)[pP]([^A-Za-z0-9]|$)/g,' ').replace(/ +/g,' ').trim();
    openGroupModal({mode:'create',name:nm,members:m});
}
function editGroup(key){
    var g=GROUP_DATA[key];if(!g)return;
    if(g.manual){openGroupModal({mode:'edit',gid:g.gid,num:g.num,name:unesc(g.title),members:g.variants.slice(),thumbFid:g.thumb_fid||'',custom:!!g.custom_thumb});}
    else{saveAutoGroup(key);}
}
/* "Save as Group": ek click me DB me save (apna group number milta hai). Baad me is naam ki
   nayi quality upload hogi to wo bhi apne-aap isi group me judegi. */
async function saveAutoGroup(key){
    var g=GROUP_DATA[key];if(!g)return;
    try{
        var d=await grpPost('/api/group/save',{items:g.variants.map(function(f){return {id:f.file_id,name:f.name};}),name:unesc(g.title)});
        showToast('Group #'+d.num+' save ho gaya. Naam/thumbnail badalne ke liye Edit Group dabayein');
        refreshGridAfterEdit();
    }catch(e){showToast(e.message,'error');}
}
function askGroupNum(){
    var v=prompt('Kis Group number me merge karna hai? (jaise 17)');
    if(v===null)return null;
    v=String(v).replace('#','').trim();
    if(!/^[0-9]+$/.test(v)){showToast('Sahi group number likhiye','error');return null;}
    return v;
}
async function mergeGroup(key){
    var g=GROUP_DATA[key];if(!g)return;
    var id=askGroupNum();if(!id)return;
    try{
        var d;
        if(g.manual){
            if(String(g.gid)===id){showToast('Same group me merge nahi ho sakta','error');return;}
            d=await grpPost('/api/group/merge',{source:g.gid,target:id});
        }else{
            d=await grpPost('/api/group/save',{group_id:id,items:g.variants.map(function(f){return {id:f.file_id,name:f.name};})});
        }
        showToast('Group #'+d.num+' me merge ho gaya');
        refreshGridAfterEdit();
    }catch(e){showToast(e.message,'error');}
}
async function mergeFile(fid){
    var f=FILE_DATA[fid];if(!f)return;
    var id=askGroupNum();if(!id)return;
    try{
        var d=await grpPost('/api/group/save',{group_id:id,items:[{id:f.file_id,name:f.name}]});
        showToast('File Group #'+d.num+' me merge ho gayi');
        refreshGridAfterEdit();
    }catch(e){showToast(e.message,'error');}
}
async function ungroup(gid){
    if(!confirm('Group hata dein? Files delete nahi hongi, bas ye group khul jaayega.'))return;
    try{await grpPost('/api/group/delete',{group_id:gid});showToast('Group hata diya');refreshGridAfterEdit();}
    catch(e){showToast(e.message,'error');}
}
async function removeFromGroup(gid,fid){
    if(!confirm('Is file ko group se hata dein?'))return;
    try{await grpPost('/api/group/remove_file',{group_id:gid,file_id:fid});showToast('Group se hata di');refreshGridAfterEdit();}
    catch(e){showToast(e.message,'error');}
}

var GM={},gmCropper=null;
function closeGroupModal(){if(gmCropper){gmCropper.destroy();gmCropper=null;}var m=document.getElementById('grpModal');if(m)m.remove();}
function gmThumbUrl(f){return '/api/thumb?file_id='+encodeURIComponent(f.file_id)+'&col='+encodeURIComponent(f.raw_collection||'primary');}
function openGroupModal(o){
    var mode0=o.custom?'custom':(o.thumbFid?'member':'auto');
    GM={mode:o.mode,gid:o.gid||'',num:o.num||'',members:o.members||[],thumbFid:o.thumbFid||'',thumbMode:mode0,hasCustom:!!o.custom,pick:null,ts:Date.now()};
    closeGroupModal();
    var edit=o.mode==='edit';
    var h='<div class="edit-modal open" id="grpModal" onclick="if(event.target===this)closeGroupModal()"><div class="em-card gm-card">'+
        '<div style="font-size:17px;font-weight:800;margin-bottom:4px;color:var(--text)">'+(edit?'&#9999; Edit Group #'+GM.num:'&#128279; Group banayein')+'</div>'+
        '<div style="font-size:12px;color:var(--muted)">'+GM.members.length+' files</div>';
    h+='<div class="gm-label">GROUP KA NAAM</div><input class="gm-input" id="gmName" value="'+esc(o.name||'')+'" placeholder="Group name">';
    if(!edit){
        h+='<div class="gm-label">YA PEHLE SE BANE GROUP ME JODEIN (naam ya number se search)</div>'+
           '<input class="gm-input" id="gmSearch" placeholder="Group ka naam ya number..." oninput="gmSearchGroups(this.value)">'+
           '<div id="gmGroupList"></div>';
    }
    h+='<div class="gm-label">MASTER THUMBNAIL</div><div class="gm-thumbs" id="gmThumbs"></div>'+
       '<input type="file" id="gmFile" accept="image/*" style="display:none" onchange="gmLocalPreview(this)">'+
       '<div id="gmCropWrap" style="display:none;margin-top:10px"></div>';
    h+='<div class="gm-label">FILES</div><div id="gmMembers"></div>';
    h+='<div class="gm-row"><button class="gm-btn alt" onclick="closeGroupModal()">Cancel</button>'+
       (edit?'<button class="gm-btn" style="background:rgba(160,8,8,.85)" onclick="ungroup(GM.gid);closeGroupModal()">Ungroup</button>':'')+
       '<button class="gm-btn" id="gmSave" onclick="saveGroupModal()">Save</button></div>';
    h+='</div></div>';
    document.body.insertAdjacentHTML('beforeend',h);
    gmRenderThumbs();gmRenderMembers();
    if(!edit)gmSearchGroups('');
}
function gmRenderThumbs(){
    var tm=GM.thumbMode;
    var h='<div class="gm-th gm-auto'+(tm==='auto'?' on':'')+'" onclick="gmPickThumb(\\'auto\\',\\'\\')">AUTO</div>';
    if(GM.hasCustom){
        h+='<div class="gm-th'+(tm==='custom'?' on':'')+'" onclick="gmPickThumb(\\'custom\\',\\'\\')"><img src="/api/group/thumb?gid='+encodeURIComponent(GM.gid)+'&v='+GM.ts+'"><em>CUSTOM</em></div>';
    }
    h+='<div class="gm-th gm-auto'+(tm==='newupload'?' on':'')+'" onclick="document.getElementById(\\'gmFile\\').click()">&#128206; UPLOAD</div>';
    GM.members.forEach(function(f){
        h+='<div class="gm-th'+(tm==='member'&&GM.thumbFid===f.file_id?' on':'')+'" onclick="gmPickThumb(\\'member\\',\\''+f.file_id+'\\')">'+
           '<img src="'+gmThumbUrl(f)+'" loading="lazy"><em>'+esc(qlabel(f))+'</em></div>';
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
    var reader=new FileReader();
    reader.onload=function(e){
        if(gmCropper){gmCropper.destroy();gmCropper=null;}
        var w=document.getElementById('gmCropWrap');
        w.style.display='block';
        w.innerHTML='<img id="gmCropImg" src="'+e.target.result+'" style="max-width:100%;display:block">';
        if(typeof Cropper!=='undefined'){
            gmCropper=new Cropper(document.getElementById('gmCropImg'),{aspectRatio:16/9,viewMode:1,background:false,zoomable:true,movable:true});
        }
        GM.thumbMode='newupload';GM.thumbFid='';
        gmRenderThumbs();
    };
    reader.readAsDataURL(input.files[0]);
}
function gmRenderMembers(){
    var h='';
    GM.members.forEach(function(f,i){
        h+='<div class="gm-mem"><b>'+esc(qlabel(f))+'</b><span title="'+esc(unesc(f.name))+'">'+f.name+'</span>'+
           (GM.mode==='edit'?'<button onclick="gmRemoveMember('+i+')">&#10006;</button>':'')+'</div>';
    });
    var el=document.getElementById('gmMembers');if(el)el.innerHTML=h;
}
async function gmRemoveMember(i){
    var f=GM.members[i];if(!f)return;
    if(GM.members.length<=2&&!confirm('Sirf 2 files bachi hain, hatane par group asal me khatam ho jaayega. Aage badhein?'))return;
    try{
        await grpPost('/api/group/remove_file',{group_id:GM.gid,file_id:f.file_id});
        GM.members.splice(i,1);
        if(GM.thumbFid===f.file_id){GM.thumbFid='';GM.thumbMode='auto';}
        gmRenderThumbs();gmRenderMembers();
        showToast('Group se hata di');
        if(GM.members.length<2){closeGroupModal();}
        refreshGridAfterEdit();
    }catch(e){showToast(e.message,'error');}
}
var gmSearchTimer;
function gmSearchGroups(q){
    clearTimeout(gmSearchTimer);
    gmSearchTimer=setTimeout(async function(){
        try{
            var r=await fetch('/api/group/list?q='+encodeURIComponent(q||'')),d=await r.json(),h='';
            (d.groups||[]).forEach(function(g){
                h+='<div class="gm-pick'+(GM.pick===g.id?' on':'')+'" onclick="gmPickGroup(\\''+g.id+'\\',this)"><span>#'+g.num+' '+esc(g.name)+'</span><span>'+g.count+' files</span></div>';
            });
            var el=document.getElementById('gmGroupList');if(el)el.innerHTML=h;
        }catch(e){}
    },q?250:0);
}
function gmPickGroup(id,el){
    var same=(GM.pick===id);
    GM.pick=same?null:id;
    document.querySelectorAll('#gmGroupList .gm-pick').forEach(function(x){x.classList.remove('on');});
    if(!same&&el)el.classList.add('on');
}
async function saveGroupModal(){
    var btn=document.getElementById('gmSave');
    var name=(document.getElementById('gmName').value||'').trim();
    var create=(GM.mode==='create');
    if(create&&!GM.pick&&!name){showToast('Group ka naam likhiye','error');return;}
    if(create&&!GM.pick&&GM.members.length<2){showToast('Kam se kam 2 files chunein','error');return;}
    btn.disabled=true;btn.textContent='Saving...';
    try{
        var gid=GM.gid,num=GM.num;
        if(create){
            var d=await grpPost('/api/group/save',{items:GM.members.map(function(f){return {id:f.file_id,name:f.name};}),group_id:GM.pick||'',name:name});
            gid=d.group_id;num=d.num;
        }
        var tm=GM.thumbMode;
        var upd={group_id:gid};
        if(name&&!(create&&GM.pick))upd.name=name;
        if(tm==='member'){
            var tf=GM.members.filter(function(f){return f.file_id===GM.thumbFid;})[0];
            upd.thumb_file_id=GM.thumbFid;upd.thumb_col=(tf&&tf.raw_collection)||'primary';upd.clear_custom=true;
        }else if(tm==='auto'){
            if(!(create&&GM.pick)){upd.thumb_file_id='';upd.clear_custom=true;}
        }else if(tm==='newupload'){
            upd.thumb_file_id='';
        }
        await grpPost('/api/group/update',upd);
        if(tm==='newupload'){
            var fi=document.getElementById('gmFile'),file=fi&&fi.files&&fi.files[0],blob=null;
            if(gmCropper){
                var canvas=gmCropper.getCroppedCanvas({width:1280,height:720,imageSmoothingEnabled:true,imageSmoothingQuality:'high'});
                blob=await new Promise(function(r){canvas.toBlob(r,'image/jpeg',0.9);});
            }else if(file){blob=file;}
            if(blob){
                showToast('Thumbnail upload ho raha hai...');
                var fd=new FormData();fd.append('group_id',gid);fd.append('image',blob,'group.jpg');
                var ur=await fetch('/api/group/upload_thumb',{method:'POST',body:fd}),ud={};
                try{ud=await ur.json();}catch(e){}
                if(!ur.ok||ud.error){throw new Error(ud.error||'Thumbnail upload failed');}
            }
        }
        showToast('Group #'+num+' save ho gaya');
        closeGroupModal();
        toggleSelMode(false);
        refreshGridAfterEdit();
    }catch(e){showToast(e.message,'error');btn.disabled=false;btn.textContent='Save';}
}

async function doSearch(o,allowEmpty){
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
        var r=await fetch('/api/search?q='+encodeURIComponent(q)+'&offset='+o+'&col='+curCol+'&mode='+pMode+'&group=1&gf='+curGF);
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
                resDiv.innerHTML='<div class="empty"><div class="empty-icon">&#9888;</div><p>'+msg+'</p></div>';
                document.getElementById('pageBox').style.display='none';
            }
            return;
        }
        document.getElementById('resInfo').style.display='none';
        if(!d.results||!d.results.length){
            resDiv.innerHTML = q
                ? '<div class="empty"><div class="empty-icon">&#9888;</div><p>No titles found for "'+q+'"'+(curGF==='group'?' in Group (sirf group wale results)':'')+'</p></div>'
                : '<div class="empty"><div class="empty-icon">&#8981;</div><p>No files added yet.</p></div>';
            document.getElementById('pageBox').style.display='none';return;
        }
        var h='';
        isAdminView=!!d.is_admin;
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
            fetch('/api/search?q='+encodeURIComponent(q)+'&offset='+nextOff+'&col='+curCol+'&mode='+pMode+'&group=1&gf='+curGF);
        }
    }catch(e){clearTimeout(loadTimer);if(qWrap)qWrap.classList.remove('loading');showToast('Network error','error');}
}

var offHist=[],pageGroups={};
function next(){if(nextOff){offHist.push(curOff);curPage++;doSearch(nextOff);scrollTo(0,0);}}
function prev(){if(curPage>1){curPage--;doSearch(offHist.length?offHist.pop():0);scrollTo(0,0);}}

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
                    '<div class="cdd-item" data-val="group" onclick="pickGF(\'group\',\'Group\',this)">Group<span class="cdd-radio"><span class="cdd-radio-dot"></span></span></div>'
                    '<div class="cdd-item" data-val="single" onclick="pickGF(\'single\',\'Ungroup\',this)">Ungroup<span class="cdd-radio"><span class="cdd-radio-dot"></span></span></div>'
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
        await web_db.delete_session(s_user)
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
