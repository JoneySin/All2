"""Small same-page player shared by the dashboard, profiles and posts."""

PLAYER_UI = r'''
<style>
.inline-player-backdrop{position:fixed;inset:0;z-index:100000;display:flex;align-items:center;justify-content:center;padding:18px;background:rgba(0,0,0,.76);backdrop-filter:blur(8px)}
.inline-player-backdrop[hidden]{display:none}
.inline-player-card{width:min(100%,680px);max-height:calc(100dvh - 36px);overflow:auto;background:var(--card);border:1px solid var(--border);border-radius:16px;box-shadow:0 24px 80px rgba(0,0,0,.6)}
.inline-player-head{display:flex;align-items:center;gap:12px;padding:15px 17px}
.inline-player-mark{display:grid;place-items:center;width:38px;height:38px;flex:none;color:white;background:var(--accent);border-radius:10px;font-size:17px}
.inline-player-titlebox{flex:1;min-width:0}.inline-player-kicker{color:var(--muted);font-size:10px;letter-spacing:1px;text-transform:uppercase;font-weight:800}
.inline-player-title{color:var(--text);font-size:14px;font-weight:800;line-height:1.4;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:3px}
.inline-player-close{width:36px;height:36px;flex:none;border:1px solid var(--border);border-radius:9px;color:var(--text);background:var(--bg3);font-size:23px;cursor:pointer}
.inline-player-screen{background:#000;aspect-ratio:16/9;display:flex;align-items:center;justify-content:center;position:relative}
.inline-player-screen video{width:100%;height:100%;max-height:56vh;object-fit:contain;background:#000}
.inline-player-status{padding:11px 17px;color:var(--muted);font-size:12px;line-height:1.5;min-height:40px}
.inline-player-status.error{color:#ffb4a9}.inline-player-actions{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:0 17px 16px;flex-wrap:wrap}
.inline-player-note{color:var(--muted);font-size:11px}.inline-player-download{color:var(--text);text-decoration:none;border:1px solid var(--border);background:var(--bg3);padding:8px 11px;border-radius:8px;font-size:12px;font-weight:700}
.inline-player-download[hidden]{display:none}.inline-player-download:hover{border-color:var(--accent)}
@media(max-width:500px){.inline-player-backdrop{padding:10px}.inline-player-card{border-radius:13px}.inline-player-head{padding:12px}.inline-player-screen video{max-height:50vh}}
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
    <div class="inline-player-actions"><span class="inline-player-note">Playback depends on your browser's supported formats.</span><a id="inlinePlayerDownload" class="inline-player-download" hidden>Download file</a></div>
  </div>
</div>
<script>
var inlinePlayerRequest=0, inlinePlayerAbort=null, inlinePlayerPreviousFocus=null, inlinePlayerOverflow='';
function closeInlinePlayer(){
    var modal=document.getElementById('inlinePlayer'), video=document.getElementById('inlinePlayerVideo');
    if(!modal||modal.hidden)return;
    ++inlinePlayerRequest;
    if(inlinePlayerAbort){inlinePlayerAbort.abort();inlinePlayerAbort=null;}
    video.pause();video.removeAttribute('src');video.load();modal.hidden=true;document.body.style.overflow=inlinePlayerOverflow;
    if(inlinePlayerPreviousFocus&&inlinePlayerPreviousFocus.isConnected)inlinePlayerPreviousFocus.focus();
}
async function openInlinePlayer(fileId,title){
    var modal=document.getElementById('inlinePlayer'),video=document.getElementById('inlinePlayerVideo');
    var status=document.getElementById('inlinePlayerStatus'),download=document.getElementById('inlinePlayerDownload');
    if(!modal||!fileId)return;
    if(inlinePlayerAbort)inlinePlayerAbort.abort();
    if(modal.hidden){inlinePlayerPreviousFocus=document.activeElement;inlinePlayerOverflow=document.body.style.overflow;document.body.style.overflow='hidden';}
    var request=++inlinePlayerRequest;
    inlinePlayerAbort=new AbortController();
    video.pause();video.removeAttribute('src');video.load();
    document.getElementById('inlinePlayerTitle').textContent=title||'Video';
    status.className='inline-player-status';status.textContent='Preparing your video…';
    download.hidden=true;download.removeAttribute('href');
    modal.hidden=false;modal.querySelector('.inline-player-close').focus();
    try{
        var response=await fetch('/setup_stream',{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({file_id:fileId,mode:'inline'}),signal:inlinePlayerAbort.signal});
        var data=await response.json().catch(function(){return {};});
        if(request!==inlinePlayerRequest||modal.hidden)return;
        if(!response.ok||data.error)throw new Error(data.error||'Unable to prepare this video.');
        var url=new URL(data.url,window.location.origin);
        if(url.origin!==window.location.origin||!/^\/download\/\d+$/.test(url.pathname))throw new Error('Invalid video link.');
        var downloadUrl=new URL(url);downloadUrl.searchParams.delete('inline');
        download.href=downloadUrl.pathname+downloadUrl.search;download.hidden=false;
        video.src=url.pathname+url.search;
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
