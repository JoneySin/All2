"""Shared browser-side file card renderer and view-mode preference."""

MEDIA_CARD_JS = r'''
// One preference for media and catalogue views; adapters keep existing API values.
var MediaView = {
    get: function(fallback) {
        var value;
        try {
            value = localStorage.getItem('ff_view_mode');
            if (!value) {
                var old = localStorage.getItem('ff_dashboard_mode') || localStorage.getItem('ff_mode');
                if (old === 'tg' || old === 'none') { value = old === 'tg' ? 'poster' : 'text'; localStorage.setItem('ff_view_mode', value); }
            }
        } catch (_) {}
        return value === 'text' || value === 'poster' ? value : (fallback === 'tg' || fallback === 'poster' ? 'poster' : 'text');
    },
    set: function(value) {
        var mode = value === 'tg' || value === 'poster' ? 'poster' : 'text';
        try { localStorage.setItem('ff_view_mode', mode); } catch (_) {}
        return mode;
    },
    media: function(fallback) { return this.get(fallback) === 'text' ? 'none' : 'tg'; },
    subscribe: function(callback) {
        window.addEventListener('storage', function(e) {
            if (e.key === 'ff_view_mode' && (e.newValue === 'text' || e.newValue === 'poster')) callback(e.newValue);
        });
    }
};
function mediaEscape(value) {
    return String(value == null ? '' : value).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}
// Layout and badges are shared; caller supplies its own playback/admin actions.
function renderMediaFile(f, mode, opts) {
    opts = opts || {};
    var mini = !!opts.mini, text = mode === 'none';
    var sc = String(f.raw_collection || f.source || 'primary').toLowerCase();
    if (!['primary','cloud','archive'].includes(sc)) sc = 'primary';
    var fid = mediaEscape(f.file_id), name = mediaEscape(f.name), size = mediaEscape(f.size || '');
    var ep = f.group_type === 'series' ? (f.episode_label || (f.episode_position ? 'File ' + f.episode_position : '')) : '';
    var episode = ep ? '<span class="episode-chip">' + mediaEscape(ep) + '</span>' : '';
    var sizeClass = mini ? (text ? 'ts' : 'sc') : (text ? 'tc-size' : 'size-chip');
    var durClass = mini ? (text ? 'td' : 'dc') : (text ? 'tc-dur' : 'dur-chip');
    var resClass = mini ? (text ? 'tr' : 'rc') : (text ? 'tc-res' : 'res-chip');
    var sourceClass = mini ? (text ? 'tp' : 'sp') : 'source-pill';
    var dot = mini ? 'sd' : 'source-dot';
    var badges = episode + '<span class="'+sizeClass+'">'+size+'</span>' +
        (f.duration ? '<span class="'+durClass+'">'+mediaEscape(f.duration)+'</span>' : '') +
        (f.res ? '<span class="'+resClass+'">'+mediaEscape(f.res)+'</span>' : '') +
        '<span class="'+sourceClass+' '+sc+'"><span class="'+dot+'"></span>'+sc.toUpperCase()+'</span>';
    if (mini) {
        var visual = text ? '<div class="ti">'+badges+'</div>' :
            '<div class="pb" id="pb-'+fid+'"><img src="'+mediaEscape(f.tg_thumb || '')+'" data-col="'+sc+'" class="fp" loading="lazy" decoding="async" onload="this.classList.add(\'on\')" onerror="thumbErr(this.closest(\'.fc\').dataset.fid)"><div class="pt">'+badges+'</div></div>';
        return '<div class="fc ce" data-fid="'+fid+'" onclick="miniPlayFile(this)">'+visual+'<div class="fb"><div class="fn">'+name+'</div></div></div>';
    }
    var actions = opts.actions || '';
    var trigger = opts.admin ? '<button type="button" class="file-poster-trigger" aria-label="Show file editing options" aria-expanded="false" onclick="toggleAdminBtns(this.closest(\'.file-card\'),event)"></button>' : '';
    var visual = text ? '<div class="fc-text-info">'+badges+'</div>'+(opts.admin?'<div class="text-admin-row">'+actions+'</div>':'') :
        '<div class="poster-box" id="poster-box-'+fid+'"><img src="'+mediaEscape(f.tg_thumb || '')+'" id="img-poster-'+fid+'" class="fc-poster" onload="this.classList.add(\'loaded\')" onerror="handleThumbError(this.closest(\'.file-card\').dataset.fid)" loading="lazy" decoding="async"><div class="poster-top">'+badges+'</div>'+trigger+(opts.admin?'<div class="poster-admin">'+actions+'</div>':'')+'</div>';
    var control = opts.admin && text ? ' role="button" tabindex="0" aria-label="Show file editing options" aria-expanded="false" onclick="textFileClick(this,event)" onkeydown="textFileKey(this,event)"' : '';
    return '<div class="file-card'+(opts.nested?'':' card-enter')+(opts.selected?' sel':'')+(control?' text-file-trigger':'')+'" data-fid="'+fid+'"'+control+'>'+visual+'<div class="fc-body"><button type="button" class="fc-name" id="name-title-'+fid+'" onclick="'+opts.play+'">'+name+'</button></div></div>';
}
'''
