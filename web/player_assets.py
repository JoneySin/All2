"""Small same-page player shared by the dashboard, profiles and posts."""

PLAYER_UI = r'''
<style>
.inline-player-backdrop{position:fixed;inset:0;z-index:100000;display:flex;align-items:center;justify-content:center;padding:18px;background:rgba(0,0,0,.78);backdrop-filter:blur(10px)}
.inline-player-backdrop[hidden]{display:none}
.inline-player-card{width:min(100%,690px);max-height:calc(100dvh - 36px);overflow:auto;background:var(--card);border:1px solid var(--border);border-radius:18px;box-shadow:0 24px 80px rgba(0,0,0,.62)}
body.light .inline-player-card{box-shadow:0 24px 70px rgba(15,23,42,.22)}
.inline-player-head{display:flex;align-items:center;gap:12px;padding:14px 17px;background:linear-gradient(125deg,rgba(229,9,20,.1),transparent 55%),var(--card);border-bottom:1px solid var(--border)}
.inline-player-mark{display:grid;place-items:center;width:38px;height:38px;flex:none;color:#fff;background:linear-gradient(135deg,var(--accent),#b20710);border-radius:10px;font-size:16px;box-shadow:0 4px 12px rgba(229,9,20,.32)}
.inline-player-titlebox{flex:1;min-width:0}.inline-player-kicker{color:var(--accent);font-size:10px;letter-spacing:1.1px;text-transform:uppercase;font-weight:900}
.inline-player-title{color:var(--text);font-size:14px;font-weight:800;line-height:1.35;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:2px}
.inline-player-close{display:grid;place-items:center;width:36px;height:36px;flex:none;border:1px solid var(--border);border-radius:10px;color:var(--text);background:var(--bg3);font-size:22px;line-height:1;cursor:pointer;transition:border-color .16s,background .16s,color .16s}
.inline-player-close:hover{border-color:var(--accent);color:var(--accent);background:var(--bg2)}
.inline-player-screen{background:#000;aspect-ratio:16/9;display:flex;align-items:center;justify-content:center;position:relative}
.inline-player-screen video{width:100%;height:100%;max-height:56vh;object-fit:contain;background:#000}
.inline-player-status{padding:9px 17px;color:var(--muted);font-size:12px;font-weight:600;line-height:1.45;background:var(--bg2);border-top:1px solid var(--border)}
.inline-player-status:empty{display:none}
.inline-player-status.error{color:#ffb4a9;background:rgba(229,9,20,.12)}
body.light .inline-player-status.error{color:#b91c1c;background:rgba(229,9,20,.08)}
.inline-player-switcher{padding:14px 17px 15px;background:var(--bg2);border-top:1px solid var(--border);display:flex;flex-direction:column;gap:12px}
.inline-player-switcher[hidden]{display:none}
.inline-player-switch-group{display:flex;flex-direction:column;gap:8px}
.inline-player-switch-head{display:flex;align-items:center;justify-content:space-between;gap:10px;color:var(--muted);font-size:10px;letter-spacing:1.1px;text-transform:uppercase;font-weight:900}
.inline-player-switch-head span:first-child{display:inline-flex;align-items:center;gap:6px;flex-shrink:0}
.inline-player-switch-head span:first-child::before{content:'';width:6px;height:6px;border-radius:50%;background:var(--accent);display:inline-block}
.inline-player-switch-head span:last-child{letter-spacing:0;text-transform:none;font-weight:700;font-size:11px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.inline-player-switch-row{display:grid;grid-template-columns:repeat(auto-fill,minmax(124px,1fr));gap:8px;max-height:196px;overflow-y:auto;padding:2px 1px;scrollbar-width:thin}
.inline-player-switch-row.episodes-row{grid-template-columns:repeat(auto-fill,minmax(92px,1fr));max-height:152px}
.inline-player-chip{display:flex;flex-direction:column;align-items:flex-start;justify-content:center;gap:3px;min-width:0;border:1.5px solid var(--border);background:var(--card);color:var(--text);padding:9px 11px;border-radius:11px;font-size:12.5px;font-weight:800;cursor:pointer;font-family:inherit;line-height:1.25;text-align:left;transition:border-color .16s,background .16s,box-shadow .16s}
body.light .inline-player-chip{box-shadow:0 2px 6px rgba(15,23,42,.05)}
.inline-player-chip:hover:not([aria-current="true"]){border-color:var(--accent);background:var(--bg3)}
.inline-player-chip:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.inline-player-chip-top{display:flex;align-items:center;justify-content:space-between;gap:6px;width:100%}
.inline-player-chip-lbl{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.inline-player-chip-state{font-size:10px;line-height:1;opacity:0;flex-shrink:0}
.inline-player-chip[aria-current="true"]{background:linear-gradient(135deg,var(--accent),#b20710);border-color:var(--accent);color:#fff;cursor:default;box-shadow:0 5px 16px rgba(229,9,20,.32)}
body.light .inline-player-chip[aria-current="true"]{box-shadow:0 6px 16px rgba(229,9,20,.26)}
.inline-player-chip[aria-current="true"] .inline-player-chip-state{opacity:1}
.inline-player-chip small{display:block;font-size:10px;font-weight:600;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%}
.inline-player-chip[aria-current="true"] small{color:rgba(255,255,255,.88)}
.inline-player-switch-note{color:var(--muted);font-size:10px}
.inline-player-actions{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:12px 17px;background:var(--card);border-top:1px solid var(--border);flex-wrap:wrap}
.inline-player-note{color:var(--muted);font-size:11px;line-height:1.4}
.inline-player-download{display:inline-flex;align-items:center;gap:6px;color:var(--text);text-decoration:none;border:1px solid var(--border);background:var(--bg3);padding:8px 13px;border-radius:9px;font-size:12px;font-weight:800;transition:border-color .16s,color .16s,background .16s}
.inline-player-download[hidden]{display:none}.inline-player-download:hover{border-color:var(--accent);color:var(--accent)}
@media(max-width:500px){.inline-player-backdrop{padding:10px}.inline-player-card{border-radius:14px}.inline-player-head{padding:12px 13px}.inline-player-switcher{padding:12px 13px 13px}.inline-player-actions{padding:11px 13px}.inline-player-screen video{max-height:50vh}}
@media(max-width:420px){.inline-player-switch-row{grid-template-columns:repeat(2,minmax(0,1fr))}.inline-player-switch-row.episodes-row{grid-template-columns:repeat(3,minmax(0,1fr))}}
</style>
<div id="inlinePlayer" class="inline-player-backdrop" role="dialog" aria-modal="true" aria-labelledby="inlinePlayerTitle" hidden>
  <div class="inline-player-card">
    <div class="inline-player-head">
      <span class="inline-player-mark" aria-hidden="true">&#9654;</span>
      <div class="inline-player-titlebox"><div class="inline-player-kicker">Now playing</div><div id="inlinePlayerTitle" class="inline-player-title"></div></div>
      <button type="button" class="inline-player-close" aria-label="Close player" onclick="closeInlinePlayer()">&times;</button>
    </div>
    <div class="inline-player-screen"><video id="inlinePlayerVideo" controls playsinline preload="metadata"></video></div>
    <div id="inlinePlayerStatus" class="inline-player-status" role="status" aria-live="polite"></div>
    <div id="inlinePlayerSwitcher" class="inline-player-switcher" aria-label="Other versions in this group" hidden></div>
    <div class="inline-player-actions"><span class="inline-player-note">Playback depends on your browser's supported formats.</span><a id="inlinePlayerDownload" class="inline-player-download" hidden>&#11015; Download file</a></div>
  </div>
</div>
<script>
var inlinePlayerRequest=0, inlinePlayerAbort=null, inlinePlayerPreviousFocus=null, inlinePlayerOverflow='';
var inlinePlayerFileId='', inlinePlayerSwitches=null, inlinePlayerEpisode='';
function closeInlinePlayer(){
    var modal=document.getElementById('inlinePlayer'), video=document.getElementById('inlinePlayerVideo');
    if(!modal||modal.hidden)return;
    ++inlinePlayerRequest;
    if(inlinePlayerAbort){inlinePlayerAbort.abort();inlinePlayerAbort=null;}
    video.pause();video.removeAttribute('src');video.load();modal.hidden=true;document.body.style.overflow=inlinePlayerOverflow;
    inlinePlayerFileId='';inlinePlayerSwitches=null;inlinePlayerEpisode='';
    var switcher=document.getElementById('inlinePlayerSwitcher');
    if(switcher){switcher.hidden=true;switcher.textContent='';}
    if(inlinePlayerPreviousFocus&&inlinePlayerPreviousFocus.isConnected)inlinePlayerPreviousFocus.focus();
}
function inlinePlayerDownloadLink(download){
    var link=document.getElementById('inlinePlayerDownload');
    if(!link)return;
    if(download){link.href=download;link.hidden=false;}else{link.hidden=true;link.removeAttribute('href');}
}
async function inlinePlayerPrepareStream(fileId,recycle){
    var endpoint=recycle?'/api/recycle/stream':'/setup_stream';
    var payload=recycle?{id:fileId}:{file_id:fileId,mode:'inline'};
    var response=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify(payload),signal:inlinePlayerAbort.signal});
    var data=await response.json().catch(function(){return {};});
    if(!response.ok||data.error)throw new Error(data.error||'Unable to prepare this video.');
    var url=new URL(data.url,window.location.origin);
    if(url.origin!==window.location.origin||!/^\/download\/\d+$/.test(url.pathname))throw new Error('Invalid video link.');
    var download=new URL(url);download.searchParams.delete('inline');
    return {src:url.pathname+url.search,download:download.pathname+download.search};
}
function inlinePlayerHead(label,detail){
    var head=document.createElement('div');head.className='inline-player-switch-head';
    var left=document.createElement('span');left.textContent=label;
    var right=document.createElement('span');right.textContent=detail||'';
    head.appendChild(left);head.appendChild(right);return head;
}
function inlinePlayerRow(label,extraClass){
    var row=document.createElement('div');row.className='inline-player-switch-row'+(extraClass?' '+extraClass:'');
    row.setAttribute('role','group');row.setAttribute('aria-label',label);return row;
}
function inlinePlayerItemMeta(item){
    var parts=[];if(item.duration)parts.push(item.duration);if(item.size)parts.push(item.size);return parts.join(' · ');
}
function inlinePlayerChip(row,label,meta,current,title,onClick){
    var chip=document.createElement('button');chip.type='button';chip.className='inline-player-chip';
    var top=document.createElement('div');top.className='inline-player-chip-top';
    var text=document.createElement('span');text.className='inline-player-chip-lbl';text.textContent=label||'Version';
    var state=document.createElement('span');state.className='inline-player-chip-state';state.setAttribute('aria-hidden','true');state.textContent='▶';
    top.appendChild(text);top.appendChild(state);chip.appendChild(top);
    if(meta){var small=document.createElement('small');small.textContent=meta;chip.appendChild(small);}
    chip.title=title||'';
    if(current){chip.setAttribute('aria-current','true');chip.title='Currently playing';}
    else if(onClick)chip.addEventListener('click',onClick);
    row.appendChild(chip);return chip;
}
function inlinePlayerQualityItem(episode,preferredLabel){
    var items=(episode&&episode.items)||[];
    if(!items.length)return null;
    if(preferredLabel){for(var i=0;i<items.length;i++){if(items[i].label===preferredLabel)return items[i];}}
    return items[items.length-1];
}
function inlinePlayerQualityLabelForFile(fileId,data){
    var episodes=(data&&data.episodes)||[];
    for(var i=0;i<episodes.length;i++){
        var items=episodes[i].items||[];
        for(var j=0;j<items.length;j++){if(items[j].file_id===fileId)return items[j].label||'';}
    }
    return '';
}
function inlinePlayerPaintSwitches(){
    var box=document.getElementById('inlinePlayerSwitcher');
    if(!box)return;
    box.textContent='';
    var data=inlinePlayerSwitches;
    if(!data||!data.group){box.hidden=true;return;}
    var group=data.group, name=group.name?group.name+' · ':'';
    if(group.type==='series'&&data.episodes&&data.episodes.length){
        var episodes=data.episodes, current=null, i;
        if(!inlinePlayerEpisode){inlinePlayerEpisode=data.current_episode||episodes[0].key;}
        for(i=0;i<episodes.length;i++){if(episodes[i].key===inlinePlayerEpisode){current=episodes[i];break;}}
        if(!current){current=episodes[0];inlinePlayerEpisode=current.key;}
        var epSec=document.createElement('div');epSec.className='inline-player-switch-group';
        epSec.appendChild(inlinePlayerHead('Episodes',name+episodes.length+(group.truncated?' of '+group.episode_count:'')+' episodes'));
        var episodeRow=inlinePlayerRow('Episodes','episodes-row');
        (function(){for(var j=0;j<episodes.length;j++){
            var episode=episodes[j];
            inlinePlayerChip(episodeRow,episode.label,'',episode.key===inlinePlayerEpisode,episode.label,
                (function(key){return function(){inlinePlayerPickEpisode(key);};})(episode.key));
        }})();
        epSec.appendChild(episodeRow);box.appendChild(epSec);
        var qSec=document.createElement('div');qSec.className='inline-player-switch-group';
        qSec.appendChild(inlinePlayerHead('Quality',current.label||''));
        var qualityRow=inlinePlayerRow('Quality versions of this episode');
        var items=current.items||[];
        (function(){for(var k=0;k<items.length;k++){
            var item=items[k];
            inlinePlayerChip(qualityRow,item.label,inlinePlayerItemMeta(item),item.file_id===inlinePlayerFileId,item.name,
                (function(target){return function(){switchInlinePlayer(target.file_id,target.name,false);};})(item));
        }})();
        qSec.appendChild(qualityRow);box.appendChild(qSec);
    }else{
        var items=data.items||[];
        if(items.length<2){box.hidden=true;return;}
        var qOnly=document.createElement('div');qOnly.className='inline-player-switch-group';
        qOnly.appendChild(inlinePlayerHead('Quality versions',name+items.length+(group.truncated?' of '+group.count:'')));
        var row=inlinePlayerRow('Quality versions');
        (function(){for(var j=0;j<items.length;j++){
            var item=items[j];
            inlinePlayerChip(row,item.label,inlinePlayerItemMeta(item),item.file_id===inlinePlayerFileId,item.name,
                (function(target){return function(){switchInlinePlayer(target.file_id,target.name,false);};})(item));
        }})();
        qOnly.appendChild(row);box.appendChild(qOnly);
    }
    if(group.truncated){var note=document.createElement('div');note.className='inline-player-switch-note';
        note.textContent=group.type==='series'?'Only the first '+episodes.length+' episodes are listed here.':'Only the first '+Math.min(items.length,300)+' files are listed here.';
        box.appendChild(note);}
    box.hidden=false;
}
function inlinePlayerRenderSwitches(data){
    inlinePlayerSwitches=data&&data.group?data:null;
    inlinePlayerEpisode=inlinePlayerSwitches?String(inlinePlayerSwitches.current_episode||''):'';
    inlinePlayerPaintSwitches();
}
async function inlinePlayerLoadSwitches(fileId,request){
    var box=document.getElementById('inlinePlayerSwitcher');
    if(box){box.hidden=true;box.textContent='';}
    inlinePlayerSwitches=null;
    try{
        var response=await fetch('/api/file/switches?file_id='+encodeURIComponent(fileId),
            {cache:'no-store',signal:inlinePlayerAbort.signal});
        if(!response.ok)return;
        var data=await response.json().catch(function(){return null;});
        if(request!==inlinePlayerRequest)return;
        inlinePlayerRenderSwitches(data);
    }catch(error){
        if(error.name==='AbortError')return;
    }
}
async function inlinePlayerPickEpisode(key){
    var data=inlinePlayerSwitches, episodes=(data&&data.episodes)||[], target=null, previous=inlinePlayerEpisode;
    for(var i=0;i<episodes.length;i++){if(episodes[i].key===key){target=episodes[i];break;}}
    if(!target||key===previous)return;
    var item=inlinePlayerQualityItem(target,inlinePlayerQualityLabelForFile(inlinePlayerFileId,data));
    if(!item)return;
    inlinePlayerEpisode=key;
    inlinePlayerPaintSwitches();
    var switched=await switchInlinePlayer(item.file_id,item.name,true);
    if(!switched){inlinePlayerEpisode=previous;inlinePlayerPaintSwitches();}
}
async function switchInlinePlayer(fileId,title,resetPosition){
    var modal=document.getElementById('inlinePlayer'),video=document.getElementById('inlinePlayerVideo');
    var status=document.getElementById('inlinePlayerStatus');
    if(!modal||modal.hidden||!fileId)return false;
    if(fileId===inlinePlayerFileId)return true;
    if(inlinePlayerAbort)inlinePlayerAbort.abort();
    var request=++inlinePlayerRequest;
    inlinePlayerAbort=new AbortController();
    var previousId=inlinePlayerFileId;
    var resume=resetPosition?0:(isFinite(video.currentTime)?video.currentTime:0), wasPlaying=!video.paused&&!video.ended;
    status.className='inline-player-status';status.textContent=resetPosition?'Loading episode…':'Switching…';
    try{
        var prepared=await inlinePlayerPrepareStream(fileId);
        if(request!==inlinePlayerRequest||modal.hidden)return false;
        inlinePlayerFileId=fileId;
        document.getElementById('inlinePlayerTitle').textContent=title||'Video';
        inlinePlayerPaintSwitches();
        video.pause();
        inlinePlayerDownloadLink(prepared.download);
        // Resume at the same position when only the quality changes; an episode
        // change starts from the beginning unless someone seeks.
        video.addEventListener('loadedmetadata',function(){
            if(request!==inlinePlayerRequest)return;
            if(resetPosition){video.currentTime=0;return;}
            if(resume>0.5&&isFinite(video.duration)&&video.duration>0)video.currentTime=Math.min(resume,Math.max(0,video.duration-1));
        },{once:true});
        video.src=prepared.src;
        status.textContent='Loading video…';
        if(wasPlaying){var playing=video.play();if(playing&&playing.catch)playing.catch(function(){if(request===inlinePlayerRequest&&!video.error)status.textContent='Press play to start.';});}
        return true;
    }catch(error){
        if(error.name==='AbortError'||request!==inlinePlayerRequest)return false;
        inlinePlayerFileId=previousId;
        inlinePlayerPaintSwitches();
        status.className='inline-player-status error';status.textContent=error.message||'Unable to switch this video.';
        return false;
    }
}
async function openInlinePlayer(fileId,title,recycle){
    var modal=document.getElementById('inlinePlayer'),video=document.getElementById('inlinePlayerVideo');
    var status=document.getElementById('inlinePlayerStatus');
    if(!modal||!fileId)return;
    if(inlinePlayerAbort)inlinePlayerAbort.abort();
    if(modal.hidden){inlinePlayerPreviousFocus=document.activeElement;inlinePlayerOverflow=document.body.style.overflow;document.body.style.overflow='hidden';}
    var request=++inlinePlayerRequest;
    inlinePlayerAbort=new AbortController();
    video.pause();video.removeAttribute('src');video.load();
    inlinePlayerFileId=fileId;inlinePlayerSwitches=null;inlinePlayerEpisode='';
    inlinePlayerPaintSwitches();
    document.getElementById('inlinePlayerTitle').textContent=title||'Video';
    status.className='inline-player-status';status.textContent='Preparing your video…';
    inlinePlayerDownloadLink('');
    modal.hidden=false;modal.querySelector('.inline-player-close').focus();
    if(!recycle)inlinePlayerLoadSwitches(fileId,request);
    try{
        var prepared=await inlinePlayerPrepareStream(fileId,!!recycle);
        if(request!==inlinePlayerRequest||modal.hidden)return;
        inlinePlayerDownloadLink(prepared.download);
        video.src=prepared.src;
        status.textContent='Loading video…';
        var playing=video.play();
        if(playing&&playing.catch)playing.catch(function(){if(request===inlinePlayerRequest&&!modal.hidden&&!video.error)status.textContent='Press play to start.';});
    }catch(error){
        if(error.name==='AbortError'||request!==inlinePlayerRequest)return;
        status.className='inline-player-status error';status.textContent=error.message||'Unable to load the video.';
    }
}
document.addEventListener('DOMContentLoaded',function(){
    var modal=document.getElementById('inlinePlayer'),video=document.getElementById('inlinePlayerVideo');
    if(!modal||!video)return;
    modal.addEventListener('click',function(e){if(e.target===modal)closeInlinePlayer();});
    document.addEventListener('keydown',function(e){
        if(modal.hidden)return;
        if(e.key==='Escape'){closeInlinePlayer();return;}
        if(e.key==='Tab'){
            var focusable=Array.from(modal.querySelectorAll('button:not([disabled]),a[href],video[controls]')).filter(function(el){return !el.hidden;});
            if(!focusable.length)return;
            var first=focusable[0],last=focusable[focusable.length-1];
            if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}
            else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
        }
    });
    video.addEventListener('playing',function(){if(!modal.hidden){var s=document.getElementById('inlinePlayerStatus');s.className='inline-player-status';s.textContent='';}});
    video.addEventListener('error',function(){if(!modal.hidden&&video.getAttribute('src')){var s=document.getElementById('inlinePlayerStatus');s.className='inline-player-status error';s.textContent='This video could not be played. Try downloading it or use a supported browser format.';}});
});
</script>
'''
