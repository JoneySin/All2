"""Shared create/edit post studio. Field names match the existing multipart API."""
import html
from urllib.parse import quote, urlsplit


def post_image_src(value):
    """Only return safe image URLs; Telegram images are served by our own proxy."""
    value = str(value or "").strip()
    if value.startswith("TG_ID:"):
        return "/api/post/photo?id=" + quote(value[6:], safe="")
    if value.startswith("/") and not value.startswith("//"):
        return value
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() in ("http", "https") and parsed.netloc:
            return value
    except ValueError:
        pass
    return ""


POST_EDITOR_CSS = r'''<style>
.post-studio{max-width:970px;margin:auto;padding:30px 20px 65px}
.post-studio-header{display:flex;align-items:flex-start;gap:16px;margin-bottom:22px}
.post-back,.post-cancel{display:inline-flex;align-items:center;color:var(--text);text-decoration:none;border:1px solid var(--border);background:var(--bg3);border-radius:9px;padding:10px 14px;font-size:13px;font-weight:700;white-space:nowrap}
.post-kicker,.post-section-kicker{font-size:10px;letter-spacing:1.4px;text-transform:uppercase;color:var(--accent);font-weight:900}
.post-studio-header h1{font-size:26px;line-height:1.2;margin:5px 0}.post-studio-header p,.post-hint{font-size:12px;line-height:1.55;color:var(--muted)}
.post-form-layout{display:grid;grid-template-columns:minmax(0,1fr) 250px;align-items:start;gap:16px}
.post-section{background:var(--bg2);border:1px solid var(--border);border-radius:14px;padding:20px;margin-bottom:14px}
.post-section-heading{display:flex;align-items:flex-start;gap:12px;margin-bottom:17px}.post-section-heading h2{font-size:16px;margin:4px 0}.post-section-heading p{font-size:12px;line-height:1.5;color:var(--muted)}
.post-step{display:grid;place-items:center;width:32px;height:32px;flex:none;border:1px solid var(--border);border-radius:10px;background:var(--bg3);color:var(--text);font-size:12px;font-weight:900}
.post-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.post-field{display:flex;flex-direction:column;gap:7px;min-width:0;color:var(--text);font-size:12px;font-weight:800}.post-field.full{grid-column:1/-1}
.post-input{width:100%;min-width:0;background:var(--bg);border:1px solid var(--border);padding:12px;color:var(--text);border-radius:9px;outline:none;font:inherit;font-size:14px;font-weight:500;line-height:1.4}
.post-input:focus{border-color:var(--accent);box-shadow:0 0 0 2px rgba(229,9,20,.12)}textarea.post-input{min-height:100px;resize:vertical}.post-input::placeholder{color:var(--muted);opacity:.7}
.post-file{font-size:12px;color:var(--muted)}.post-file::file-selector-button{border:1px solid var(--border);background:var(--bg3);color:var(--text);padding:8px 11px;border-radius:7px;font:inherit;font-weight:700;cursor:pointer;margin-right:10px}
.post-cover-grid{display:grid;grid-template-columns:108px minmax(0,1fr);gap:16px}.post-cover-preview{position:relative;aspect-ratio:3/4;overflow:hidden;border:1px solid var(--border);border-radius:10px;background:var(--bg3);display:grid;place-items:center;color:var(--muted);font-size:12px;text-align:center}.post-cover-preview img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}.post-cover-preview img[hidden]{display:none}
.post-preview-list{display:flex;gap:8px;overflow-x:auto;padding:2px 0 5px}.post-shot{position:relative;flex:none;width:96px;aspect-ratio:16/9;border-radius:8px;overflow:hidden;background:var(--bg3);border:1px solid var(--border)}.post-shot img{width:100%;height:100%;object-fit:cover}.post-shot-remove{position:absolute;right:3px;top:3px;width:25px;height:25px;border:0;border-radius:6px;background:rgba(0,0,0,.8);color:#fff;cursor:pointer}
.post-search-results{max-height:240px;overflow:auto;border:1px solid var(--border);background:var(--bg);border-radius:9px;margin-top:8px}.post-search-results[hidden]{display:none}.post-hit,.post-more{display:block;width:100%;padding:11px 13px;text-align:left;background:transparent;border:0;border-bottom:1px solid var(--border);color:var(--text);font:inherit;cursor:pointer}.post-hit:hover,.post-hit:focus-visible,.post-more:hover{background:var(--bg3)}.post-hit strong{display:block;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.post-hit small{display:block;color:var(--muted);font-size:11px;margin-top:4px}.post-more{color:var(--accent);text-align:center;font-weight:800}
.post-video-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:18px 0 8px;font-size:12px;font-weight:800}.post-video-count{font-size:11px;color:var(--muted)}.post-video-list{display:flex;flex-direction:column;gap:9px}.post-video-empty{color:var(--muted);font-size:12px;text-align:center;padding:17px;border:1px dashed var(--border);border-radius:9px}.post-video-empty[hidden]{display:none}
.selected-video{background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:12px}.selected-video-name{font-size:12px;font-weight:800;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-bottom:10px}.selected-video-fields{display:grid;grid-template-columns:1fr 1fr;gap:10px}.selected-video-fields .post-input{font-size:13px;padding:10px}.post-video-actions{display:flex;justify-content:flex-end;gap:6px;margin-top:10px}.post-video-actions button{background:var(--bg3);border:1px solid var(--border);border-radius:7px;color:var(--text);padding:7px 10px;font:inherit;font-size:11px;font-weight:800;cursor:pointer}.post-video-actions button:disabled{opacity:.35;cursor:not-allowed}.post-video-actions .remove{color:#ff9a9f}
.post-summary{position:sticky;top:84px;background:var(--bg2);border:1px solid var(--border);border-radius:14px;padding:18px}.post-summary h2{font-size:15px;margin-bottom:8px}.post-summary p{font-size:12px;color:var(--muted);line-height:1.6}.post-summary hr{border:0;border-top:1px solid var(--border);margin:15px 0}.post-submit{display:block;width:100%;background:var(--accent);color:#fff;border:0;padding:13px;border-radius:9px;font:inherit;font-size:13px;font-weight:900;cursor:pointer}.post-submit:hover{background:var(--accent-hover)}.post-submit:disabled{opacity:.5;cursor:wait}.post-summary .post-cancel{display:flex;justify-content:center;margin-top:9px}
@media(max-width:760px){.post-studio{padding:20px 14px 50px}.post-studio-header h1{font-size:22px}.post-form-layout{grid-template-columns:1fr}.post-summary{position:static}.post-section{padding:16px}.post-fields{grid-template-columns:1fr}.post-field.full{grid-column:auto}}
@media(max-width:400px){.post-cover-grid{grid-template-columns:80px minmax(0,1fr);gap:10px}.selected-video-fields{grid-template-columns:1fr}}
</style>'''


POST_EDITOR_JS = r'''<script>
(function(){
    var form=document.getElementById('postEditorForm'),cover=document.getElementById('postCoverUrl');
    var coverFile=document.getElementById('postCoverFile'),coverImg=document.getElementById('postCoverPreview'),objectUrl='';
    var shots=document.getElementById('postScreenshotUrls'),shotList=document.getElementById('postScreenshotPreview');
    var search=document.getElementById('videoSearchInput'),results=document.getElementById('videoSearchResults');
    var selected=document.getElementById('selectedVideosContainer'),empty=document.getElementById('postVideoEmpty'),count=document.getElementById('postVideoCount');
    var searchRequest=0,searchTimer=null,nextOffset='',lastQuery='';
    function imageUrl(value){
        value=String(value||'').trim();if(value.indexOf('TG_ID:')===0)return '/api/post/photo?id='+encodeURIComponent(value.slice(6));
        if(value[0]==='/'&&value[1]!=='/')return value;
        try{var u=new URL(value);return (u.protocol==='http:'||u.protocol==='https:')?u.href:'';}catch(e){return '';}
    }
    function updateCover(){
        if(objectUrl){URL.revokeObjectURL(objectUrl);objectUrl='';}
        var src=coverFile.files&&coverFile.files[0]?(objectUrl=URL.createObjectURL(coverFile.files[0])):imageUrl(cover.value);
        coverImg.hidden=!src;if(src)coverImg.src=src;else coverImg.removeAttribute('src');
    }
    coverImg.addEventListener('error',function(){this.hidden=true;});cover.addEventListener('input',updateCover);coverFile.addEventListener('change',updateCover);updateCover();
    function renderShots(){
        var values=shots.value.split('\n').map(function(v){return v.trim();}).filter(Boolean);shotList.replaceChildren();
        values.forEach(function(value,index){
            var src=imageUrl(value),box=document.createElement('div');box.className='post-shot';
            if(src){var img=document.createElement('img');img.src=src;img.alt='Screenshot '+(index+1);box.appendChild(img);}
            var b=document.createElement('button');b.type='button';b.className='post-shot-remove';b.textContent='×';b.setAttribute('aria-label','Remove screenshot '+(index+1));
            b.addEventListener('click',function(){values.splice(index,1);shots.value=values.join('\n');renderShots();});box.appendChild(b);shotList.appendChild(box);
        });
    }
    shots.addEventListener('input',renderShots);renderShots();
    function refreshSelected(){
        var items=Array.from(selected.querySelectorAll('.selected-video'));count.textContent=items.length+' selected';empty.hidden=items.length>0;
        items.forEach(function(item,i){item.querySelector('[data-action="up"]').disabled=i===0;item.querySelector('[data-action="down"]').disabled=i===items.length-1;});
    }
    function inputField(label,name,value,placeholder){
        var wrap=document.createElement('label');wrap.className='post-field';wrap.appendChild(document.createTextNode(label));
        var input=document.createElement('input');input.className='post-input';input.type='text';input.name=name;input.placeholder=placeholder;input.required=true;input.value=value||'';wrap.appendChild(input);return wrap;
    }
    function addVideo(fileId,fileName){
        var item=document.createElement('div');item.className='selected-video';
        var title=document.createElement('div');title.className='selected-video-name';title.textContent=fileName||'Selected media';item.appendChild(title);
        var hidden=document.createElement('input');hidden.type='hidden';hidden.name='video_id';hidden.value=fileId;item.appendChild(hidden);
        var fields=document.createElement('div');fields.className='selected-video-fields';fields.appendChild(inputField('Episode / group','video_heading','','e.g. Episode 1'));fields.appendChild(inputField('Button label','video_name','','e.g. 1080p'));item.appendChild(fields);
        var actions=document.createElement('div');actions.className='post-video-actions';[['up','↑ Up'],['down','↓ Down'],['remove','Remove']].forEach(function(pair){var b=document.createElement('button');b.type='button';b.dataset.action=pair[0];b.textContent=pair[1];if(pair[0]==='remove')b.className='remove';actions.appendChild(b);});item.appendChild(actions);selected.appendChild(item);
        results.hidden=true;refreshSelected();fields.querySelector('input').focus();
    }
    selected.addEventListener('click',function(e){
        var button=e.target.closest('button[data-action]');if(!button)return;var item=button.closest('.selected-video');if(!item)return;
        if(button.dataset.action==='remove')item.remove();
        if(button.dataset.action==='up'&&item.previousElementSibling)selected.insertBefore(item,item.previousElementSibling);
        if(button.dataset.action==='down'&&item.nextElementSibling)selected.insertBefore(item.nextElementSibling,item);
        refreshSelected();
    });refreshSelected();
    function resultMessage(text){results.replaceChildren();var div=document.createElement('div');div.className='post-hint';div.style.padding='14px';div.textContent=text;results.appendChild(div);results.hidden=false;}
    async function findVideos(loadMore){
        var q=search.value.trim();if(!q){++searchRequest;results.hidden=true;return;}
        if(!loadMore||q!==lastQuery){nextOffset='';lastQuery=q;loadMore=false;}
        var request=++searchRequest,offset=loadMore?nextOffset:0;
        if(!loadMore)resultMessage('Searching files…');
        try{
            var response=await fetch('/api/search?q='+encodeURIComponent(q)+'&mode=none&offset='+encodeURIComponent(offset),{cache:'no-store'});
            var data=await response.json();if(request!==searchRequest)return;
            if(!response.ok||data.error)throw new Error(data.error||'Search failed.');
            if(!loadMore)results.replaceChildren();else{var old=results.querySelector('.post-more');if(old)old.remove();}
            var files=data.results||[];if(!loadMore&&!files.length){resultMessage('No matching files found.');return;}
            files.forEach(function(file){
                var button=document.createElement('button');button.type='button';button.className='post-hit';
                var title=document.createElement('strong');title.textContent=file.name||'Untitled file';var meta=document.createElement('small');meta.textContent=[file.size,file.source].filter(Boolean).join(' · ');
                button.append(title,meta);button.addEventListener('click',function(){addVideo(file.file_id,file.name);});results.appendChild(button);
            });
            nextOffset=data.next_offset||'';if(nextOffset){var more=document.createElement('button');more.type='button';more.className='post-more';more.textContent='Show more';more.addEventListener('click',function(){findVideos(true);});results.appendChild(more);}results.hidden=false;
        }catch(error){if(request===searchRequest)resultMessage(error.message||'Could not search files.');}
    }
    search.addEventListener('input',function(){clearTimeout(searchTimer);++searchRequest;if(this.value.trim().length<2){results.hidden=true;return;}searchTimer=setTimeout(function(){findVideos(false);},350);});
    search.addEventListener('keydown',function(e){if(e.key==='Enter'){e.preventDefault();clearTimeout(searchTimer);findVideos(false);}});
    form.addEventListener('submit',async function(event){
        event.preventDefault();var button=document.getElementById('postSubmit'),notice=document.getElementById('postEditorError');
        if(button.disabled)return;button.disabled=true;button.textContent='Saving…';notice.hidden=true;
        try{
            var response=await fetch(form.action,{method:'POST',body:new FormData(form),headers:{'Accept':'application/json'}});
            var data=await response.json().catch(function(){return {};});
            if(!response.ok||!data.success)throw new Error(data.error||'Could not confirm the save. Please retry.');
            if(typeof data.redirect!=='string'||data.redirect[0]!=='/'||data.redirect[1]==='/')throw new Error('Saved, but could not open the result.');
            window.location.assign(data.redirect);return;
        }catch(error){
            notice.textContent=error.message||'Could not confirm the save. Check your connection before retrying.';
            notice.hidden=false;notice.scrollIntoView({block:'nearest'});button.disabled=false;button.textContent=button.dataset.label;
        }
    });
    window.addEventListener('pageshow',function(){var button=document.getElementById('postSubmit');button.disabled=false;button.textContent=button.dataset.label;});
})();
</script>'''


def _saved_video(video):
    esc = lambda value: html.escape(str(value or ""), quote=True)
    fid = str(video.get("file_id") or "")
    return f'''<div class="selected-video"><div class="selected-video-name">Saved media · {esc(fid[:24])}</div>
      <input type="hidden" name="video_id" value="{esc(fid)}"><div class="selected-video-fields">
      <label class="post-field">Episode / group<input class="post-input" type="text" name="video_heading" value="{esc(video.get('heading') or 'Download Links')}" required></label>
      <label class="post-field">Button label<input class="post-input" type="text" name="video_name" value="{esc(video.get('custom_name') or 'Play')}" required></label></div>
      <div class="post-video-actions"><button type="button" data-action="up">↑ Up</button><button type="button" data-action="down">↓ Down</button><button type="button" class="remove" data-action="remove">Remove</button></div></div>'''


def build_post_editor(post=None, post_id="", err="", msg=""):
    post = post or {}
    editing = bool(post_id)
    esc = lambda value: html.escape(str(value or ""), quote=True)
    heading, submit = ("Edit post", "Save changes") if editing else ("Create a post", "Publish post")
    back = f"/post/{quote(str(post_id), safe='')}" if editing else "/posts"
    action = "/api/post/update" if editing else "/api/post/publish"
    hidden = f'<input type="hidden" name="post_id" value="{esc(post_id)}">' if editing else ''
    notices = (f'<div class="err-box">{esc(err)}</div>' if err else '') + (f'<div class="success-box">{esc(msg)}</div>' if msg else '')
    categories = ['Movies', 'Web Series', 'App Video', 'Porn']
    saved_category = post.get('category') or 'Movies'
    if saved_category not in categories:
        categories.insert(0, saved_category)
    options = ''.join(f'<option value="{esc(cat)}"{" selected" if saved_category == cat else ""}>{esc(cat)}</option>' for cat in categories)
    video_html = ''.join(_saved_video(v) for v in (post.get('videos') or []))
    cover = str(post.get('cover_image') or '')
    cover_preview = post_image_src(cover)
    preview_attr = f' src="{esc(cover_preview)}"' if cover_preview else ' hidden'
    screenshots = '\n'.join(str(s) for s in (post.get('screenshots') or []))
    tags = ', '.join(str(t) for t in (post.get('tags') or []))
    return POST_EDITOR_CSS + f'''
    <main class="post-studio"><header class="post-studio-header"><a class="post-back" href="{esc(back)}">← Back</a><div><div class="post-kicker">Content studio</div><h1>{heading}</h1><p>Organize the details, artwork and videos your audience will see.</p></div></header>
    {notices}<div id="postEditorError" class="err-box" role="alert" hidden></div><form id="postEditorForm" action="{action}" method="post" enctype="multipart/form-data">{hidden}
    <div class="post-form-layout"><div>
      <section class="post-section"><div class="post-section-heading"><span class="post-step">01</span><div><div class="post-section-kicker">The basics</div><h2>Post details</h2><p>Make this post easy to discover.</p></div></div><div class="post-fields">
        <label class="post-field">Title<input class="post-input" name="title" value="{esc(post.get('title'))}" placeholder="e.g. Series name, season 1" required></label>
        <label class="post-field">Category<select class="post-input" name="category" required>{options}</select></label>
        <label class="post-field full">Description<textarea class="post-input" name="description" placeholder="Write a short description..." required>{esc(post.get('description'))}</textarea></label>
        <label class="post-field full">Search tags<input class="post-input" name="tags" value="{esc(tags)}" placeholder="e.g. Action, Drama, 2026"><span class="post-hint">Separate tags with commas.</span></label>
      </div></section>
      <section class="post-section"><div class="post-section-heading"><span class="post-step">02</span><div><div class="post-section-kicker">Artwork</div><h2>Cover image</h2><p>Add a direct link or choose a new image.</p></div></div>
        <div class="post-cover-grid"><div class="post-cover-preview"><span>No preview</span><img id="postCoverPreview" alt="Cover preview"{preview_attr}></div><div class="post-fields" style="grid-template-columns:1fr">
        <label class="post-field">Image URL or stored image<input id="postCoverUrl" class="post-input" name="cover_url" value="{esc(cover)}" placeholder="https://..."></label>
        <label class="post-field">Or upload an image<input id="postCoverFile" class="post-input post-file" type="file" name="cover_file" accept="image/*"><span class="post-hint">An upload replaces the link above.</span></label></div></div>
      </section>
      <section class="post-section"><div class="post-section-heading"><span class="post-step">03</span><div><div class="post-section-kicker">Visuals</div><h2>Screenshots</h2><p>Keep existing images, add links or upload more.</p></div></div><div class="post-fields">
        <label class="post-field full">Image URLs or stored images<textarea id="postScreenshotUrls" class="post-input" name="screenshot_urls" placeholder="One image link per line">{esc(screenshots)}</textarea><span class="post-hint">Remove a line or use × on a preview to remove an existing image.</span></label>
        <div class="post-field full"><div id="postScreenshotPreview" class="post-preview-list"></div></div>
        <label class="post-field full">Upload additional images<input class="post-input post-file" type="file" name="screenshot_files" accept="image/*" multiple></label>
      </div></section>
      <section class="post-section"><div class="post-section-heading"><span class="post-step">04</span><div><div class="post-section-kicker">Playback</div><h2>Videos &amp; episodes</h2><p>Search your library, then name and order the buttons.</p></div></div>
        <label class="post-field">Find a file<input id="videoSearchInput" class="post-input" type="search" autocomplete="off" placeholder="Search library files..."></label>
        <div id="videoSearchResults" class="post-search-results" hidden></div>
        <div class="post-video-head"><span>Selected media</span><span id="postVideoCount" class="post-video-count">0 selected</span></div>
        <div id="postVideoEmpty" class="post-video-empty">No files selected yet. Search above to add one.</div><div id="selectedVideosContainer" class="post-video-list">{video_html}</div>
      </section>
    </div><aside class="post-summary"><h2>{'Update your post' if editing else 'Ready to publish?'}</h2><p>Review the details and artwork. Selected files will appear in the order shown.</p><hr><button id="postSubmit" class="post-submit" type="submit" data-label="{submit}">{submit}</button><a class="post-cancel" href="{esc(back)}">Cancel</a></aside></div>
    </form></main>''' + POST_EDITOR_JS
