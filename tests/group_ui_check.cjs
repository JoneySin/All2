// Optional browser regression: run against tests/group_ui_fixture.py.
const { chromium: pw } = require('playwright-core');
const assert = require('node:assert/strict');
(async()=>{
 const options={args:['--no-sandbox','--disable-dev-shm-usage',...JSON.parse(process.env.ALL2_CHROMIUM_ARGS||'[]')],headless:true};
 if(process.env.CHROMIUM_PATH)options.executablePath=process.env.CHROMIUM_PATH;
 const browser=await pw.launch(options);
 const context=await browser.newContext({viewport:{width:1440,height:950}}), page=await context.newPage();
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const base=process.env.ALL2_UI_URL||'http://127.0.0.1:8765';
 await page.addInitScript(()=>{if(!localStorage.getItem('ff_dashboard_mode'))localStorage.setItem('ff_dashboard_mode','tg');});
 await page.route('**/*',r=>r.request().url().startsWith(base+'/')?r.continue():r.abort());
 async function json(path){const r=await page.request.get(base+path);return {status:r.status(),data:await r.json()};}
 async function update(body){const r=await page.request.post(base+'/api/group/update',{data:body});assert.equal(r.status(),200,await r.text());}
 async function openFile(fid,mode='tg'){
   let f=page.locator('.file-card[data-fid="'+fid+'"]').first();await f.waitFor();
   if(!await f.evaluate(e=>e.classList.contains('admin-active')))await f.locator(mode==='tg'?'.file-poster-trigger':'.fc-text-info').click();
   let b=f.locator(mode==='tg'?'.poster-admin button':'.text-admin-row button').filter({hasText:'Merge'});await b.click();
   await page.locator('#mergeModal').waitFor();return b;
 }
 async function waitTarget(name){await page.locator('#mergePreview .target-name').filter({hasText:name}).waitFor({timeout:10000});}
 await page.goto(base+'/dashboard',{waitUntil:'domcontentloaded'});await page.locator('.grp-card').first().waitFor();
 // Groups open from their names, not an extra action beneath them. Only quality
 // groups show a common duration; VIDEO/type chips are absent from file cards.
 const quality=page.locator('.grp-card').filter({hasText:'Aurora Rising'}).first();
 const series=page.locator('.grp-card').filter({hasText:'The Long Way Home'}).first();
 assert.equal(await page.locator('.grp-action').count(),0);
 assert.equal(await page.locator('.file-card .type-chip, .file-card .tc-type').count(),0);
 assert.equal(await page.locator('.file-actions-toggle, .file-menu').count(),0);
 const fileAction=page.locator('.file-card[data-fid="f1"] .file-poster-trigger');
 await fileAction.focus();await page.keyboard.press('Enter');
 assert.equal(await fileAction.getAttribute('aria-expanded'),'true');
 assert.equal(await page.locator('.file-card[data-fid="f1"] .poster-admin').isVisible(),true);
 assert.equal(await page.locator('#inlinePlayer').isHidden(),true);
 await page.keyboard.press('Enter');assert.equal(await fileAction.getAttribute('aria-expanded'),'false');
 assert.equal(await page.locator('.file-card[data-fid="f1"] .poster-admin').isVisible(),false);
 await page.evaluate(()=>{window.__originalPlayer=window.openInlinePlayer;window.__played=0;window.openInlinePlayer=()=>window.__played++;});
 const fileName=page.locator('.file-card[data-fid="f1"] .fc-name');
 await fileName.click();await fileName.focus();await page.keyboard.press('Enter');
 assert.equal(await page.evaluate(()=>window.__played),2);
 await page.evaluate(()=>window.openInlinePlayer=window.__originalPlayer);
 assert.equal(await quality.locator('.grp-master .poster-top .dur-chip').textContent(),'0:03');
 assert.equal(await series.locator('.grp-master .poster-top .dur-chip').count(),0);
 assert.equal(await quality.locator('.grp-master .poster-top .grp-badge').textContent(),'3 QUALITY');
 assert.equal(await series.locator('.grp-master .poster-top .grp-badge').textContent(),'2 EPISODES');
 assert.equal(await page.locator('.grp-card .grp-kind').count(),0);
 assert.deepEqual(await quality.locator('.grp-master .poster-top > span').allTextContents(),
                  ['GROUP #11', '3 QUALITY', '0:03', 'MIXED']);
 assert.deepEqual(await series.locator('.grp-master .poster-top > span').allTextContents(),
                  ['GROUP #12', '2 EPISODES', 'MIXED']);
 assert.ok((await quality.locator('.grp-master .poster-top .group-id-chip').textContent()).includes('#11'));
 const groupPoster=quality.locator('.group-poster-trigger');await groupPoster.focus();await page.keyboard.press('Enter');
 assert.equal(await groupPoster.getAttribute('aria-expanded'),'true');
 assert.equal(await quality.locator('.grp-master .poster-admin').isVisible(),true);
 assert.equal(await quality.evaluate(e=>e.classList.contains('open')),false);
 await page.keyboard.press('Enter');assert.equal(await groupPoster.getAttribute('aria-expanded'),'false');
 await quality.locator('.grp-title-button').focus();await page.keyboard.press('Enter');
 assert.equal(await quality.evaluate(e=>e.classList.contains('open')),true);
 assert.equal(await quality.locator('.grp-title-button').getAttribute('aria-expanded'),'true');
 assert.equal(await quality.locator('.grp-openhead').evaluate(e=>document.activeElement===e),true);
 await page.keyboard.press('Enter');assert.equal(await quality.evaluate(e=>e.classList.contains('open')),false);
 assert.equal(await quality.locator('.grp-title-button').evaluate(e=>document.activeElement===e),true);
 await series.locator('.grp-title-button').click();assert.equal(await series.locator('.grp-variants .file-card').count(),2);
 const nested=series.locator('.grp-variants .file-card').first();
 assert.equal(await nested.locator('.file-actions-toggle').count(),0);
 await nested.locator('.file-poster-trigger').click();
 assert.equal(await nested.locator('.poster-admin').isVisible(),true);
 assert.equal(await nested.locator('.file-poster-trigger').getAttribute('aria-expanded'),'true');
 assert.equal(await series.evaluate(e=>e.classList.contains('open')),true);
 await series.locator('.grp-openhead').click();
 // A non-admin still plays by file name and opens by group name, without
 // receiving any edit controls on the thumbnail.
 await page.evaluate(()=>{
   isAdminView=false;window.__originalPlayer=window.openInlinePlayer;window.__played=0;window.openInlinePlayer=()=>window.__played++;
   const fixture=document.createElement('div');fixture.id='non-admin-cards';fixture.className='res-grid mode-tg';
   fixture.innerHTML=cardHtml(FILE_DATA.f1,false)+groupHtml({...GROUP_DATA.m11,key:'non-admin-test'});document.body.appendChild(fixture);
 });
 const guestFile=page.locator('#non-admin-cards .file-card[data-fid="f1"]');
 assert.equal(await guestFile.locator('.file-poster-trigger, .poster-admin').count(),0);
 await guestFile.locator('.fc-name').click();assert.equal(await page.evaluate(()=>window.__played),1);
 const guestGroup=page.locator('#non-admin-cards .grp-card');
 assert.equal(await guestGroup.locator('.poster-admin').count(),0);
 await guestGroup.locator('.grp-title-button').click();assert.equal(await guestGroup.evaluate(e=>e.classList.contains('open')),true);
 await page.evaluate(()=>{document.getElementById('non-admin-cards').remove();isAdminView=true;window.openInlinePlayer=window.__originalPlayer;});
 await page.evaluate(()=>localStorage.setItem('ff_dashboard_mode','none'));await page.reload();
 await page.locator('.grp-card').first().waitFor();
 assert.equal(await page.locator('.grp-card').filter({hasText:'Aurora Rising'}).first().locator('.grp-textinfo .dur-chip').textContent(),'0:03');
 assert.equal(await page.locator('.grp-card').filter({hasText:'The Long Way Home'}).first().locator('.grp-textinfo .dur-chip').count(),0);
 assert.equal(await page.locator('.file-card .type-chip, .file-card .tc-type').count(),0);
 const textFile=page.locator('.file-card[data-fid="f1"]').first(),textGroup=page.locator('.grp-card').filter({hasText:'Aurora Rising'}).first();
 assert.equal(await textFile.locator('.text-admin-row').isHidden(),true);
 assert.equal(await textGroup.locator('.grp-master .grp-textadmin').isHidden(),true);
 await textFile.locator('.fc-body').click({position:{x:2,y:2}});
 assert.equal(await textFile.locator('.text-admin-row').isVisible(),true);
 assert.equal(await textFile.getAttribute('aria-expanded'),'true');
 assert.equal(await textGroup.locator('.grp-master .grp-textadmin').isHidden(),true);
 await textGroup.locator('.grp-textinfo .grp-badge').click();
 assert.equal(await textFile.locator('.text-admin-row').isHidden(),true);
 assert.equal(await textGroup.locator('.grp-master .grp-textadmin').isVisible(),true);
 assert.equal(await textGroup.locator('.grp-textinfo').getAttribute('aria-expanded'),'true');
 await page.evaluate(()=>document.body.click());
 assert.equal(await textGroup.locator('.grp-master .grp-textadmin').isHidden(),true);
 await textFile.focus();await page.keyboard.press('Enter');assert.equal(await textFile.locator('.text-admin-row').isVisible(),true);
 await page.keyboard.press('Enter');assert.equal(await textFile.locator('.text-admin-row').isHidden(),true);
 await textGroup.locator('.grp-textinfo').focus();await page.keyboard.press('Enter');
 assert.equal(await textGroup.locator('.grp-master .grp-textadmin').isVisible(),true);
 await page.keyboard.press('Enter');assert.equal(await textGroup.locator('.grp-master .grp-textadmin').isHidden(),true);
 await page.evaluate(()=>{window.__originalPlayer=window.openInlinePlayer;window.__played=0;window.openInlinePlayer=()=>window.__played++;});
 await textFile.locator('.fc-name').click();assert.equal(await page.evaluate(()=>window.__played),1);
 assert.equal(await textFile.locator('.text-admin-row').isHidden(),true);
 await page.evaluate(()=>window.openInlinePlayer=window.__originalPlayer);
 await textGroup.locator('.grp-title-button').focus();await page.keyboard.press('Enter');assert.equal(await textGroup.evaluate(e=>e.classList.contains('open')),true);
 assert.equal(await textGroup.locator('.grp-open-title').evaluate(e=>document.activeElement===e),true);
 assert.equal(await textGroup.locator('.grp-openhead .grp-oadmin').isHidden(),true);
 await textGroup.locator('.grp-openhead .grp-badge').click();
 assert.equal(await textGroup.locator('.grp-openhead .grp-oadmin').isVisible(),true);
 const nestedText=textGroup.locator('.grp-variants .file-card').first();
 assert.equal(await nestedText.locator('.text-admin-row').isHidden(),true);
 await nestedText.locator('.fc-text-info').click();assert.equal(await nestedText.locator('.text-admin-row').isVisible(),true);
 assert.equal(await textGroup.locator('.grp-openhead .grp-oadmin').isHidden(),true);
 await textGroup.locator('.grp-open-title').click();assert.equal(await textGroup.evaluate(e=>e.classList.contains('open')),false);
 await page.locator('#selFab').click();await textFile.locator('.fc-text-info').click();
 assert.equal(await textFile.evaluate(e=>e.classList.contains('sel')),true);
 assert.equal(await textFile.locator('.text-admin-row').isHidden(),true);
 await textFile.focus();await page.keyboard.press('Enter');assert.equal(await textFile.evaluate(e=>e.classList.contains('sel')),false);
 await textFile.locator('.fc-name').click();assert.equal(await textFile.evaluate(e=>e.classList.contains('sel')),true);
 await page.locator('#selBar .alt').click();
 await page.evaluate(()=>{
   isAdminView=false;window.__originalPlayer=window.openInlinePlayer;window.__played=0;window.openInlinePlayer=()=>window.__played++;
   const fixture=document.createElement('div');fixture.id='non-admin-text';fixture.className='res-grid mode-none';
   fixture.innerHTML=cardHtml(FILE_DATA.f1,false)+groupHtml({...GROUP_DATA.m11,key:'guest-text'});document.body.appendChild(fixture);
 });
 const guestText=page.locator('#non-admin-text');
 assert.equal(await guestText.locator('.text-admin-row, .grp-textadmin, .grp-oadmin').count(),0);
 await guestText.locator('.file-card .fc-name').first().click();assert.equal(await page.evaluate(()=>window.__played),1);
 await guestText.locator('.grp-title-button').click();assert.equal(await guestText.locator('.grp-card').evaluate(e=>e.classList.contains('open')),true);
 await guestText.locator('.grp-open-title').click();assert.equal(await guestText.locator('.grp-card').evaluate(e=>e.classList.contains('open')),false);
 await page.evaluate(()=>{document.getElementById('non-admin-text').remove();isAdminView=true;window.openInlinePlayer=window.__originalPlayer;});
 await page.evaluate(()=>localStorage.setItem('ff_dashboard_mode','tg'));await page.reload();await page.locator('.grp-card').first().waitFor();
 console.log('Card UI: name/keyboard opening, IDs, quality duration, no series duration or type chip OK');
 let trigger=await openFile('f1');
 assert.equal(await page.evaluate(()=>document.activeElement.id),'mergeId');
 assert.equal(await page.locator('#mergeSubmit').isDisabled(),true);
 assert.equal(await page.locator('#mergeConfirmWrap').isHidden(),true);
 await page.locator('#mergeId').fill('17x');await page.locator('#mergeStatus').filter({hasText:'valid numeric'}).waitFor();
 assert.equal(await page.locator('#mergeSubmit').isDisabled(),true);
 await page.locator('#mergeId').fill('999');await page.locator('#mergeStatus').filter({hasText:'was not found'}).waitFor();
 assert.equal(await page.locator('#mergePreview').isHidden(),true);
 // Simulate a non-abortable old response: the later ID must remain authoritative.
 await page.evaluate(()=>{const orig=window.fetch;window.__slow11=true;window.__slowStarted=false;window.fetch=function(input,init){
   if(window.__slow11&&typeof input==='string'&&input.includes('/api/group/preview?id=11')){
     window.__slowStarted=true;const options={...init};delete options.signal;
     return orig.call(this,input,options).then(r=>new Promise(resolve=>setTimeout(()=>resolve(r),1000)));
   }return orig.call(this,input,init);
 };});
 await page.locator('#mergeId').fill('11');await page.waitForFunction(()=>window.__slowStarted);
 await page.locator('#mergeId').fill('12');await waitTarget('The Long Way Home');
 await page.waitForTimeout(1100);assert.equal((await page.locator('#mergePreview .target-name').textContent()).trim(),'The Long Way Home');
 assert.equal(await page.locator('#mergeConfirm').isChecked(),false);
 // Closing during a slow lookup must not let that result contaminate the next dialog.
 await page.evaluate(()=>window.__slowStarted=false);await page.locator('#mergeId').fill('11');await page.waitForFunction(()=>window.__slowStarted);
 await page.keyboard.press('Escape');assert.equal(await page.locator('#mergeModal').count(),0);
 assert.equal(await trigger.evaluate(e=>document.activeElement===e),true);
 await openFile('f1');await page.locator('#mergeId').fill('12');await waitTarget('The Long Way Home');
 await page.waitForTimeout(1100);assert.equal((await page.locator('#mergePreview .target-name').textContent()).trim(),'The Long Way Home');
 await page.evaluate(()=>window.__slow11=false);
 // A failed lookup is retryable and cannot enable the action.
 await page.route('**/api/group/preview?*',r=>r.request().url().includes('id=11')?r.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'Lookup temporarily failed'})}):r.fallback(),{times:1});
 await page.locator('#mergeId').fill('# 11');await page.locator('#mergeStatus').filter({hasText:'Lookup temporarily failed'}).waitFor();
 assert.equal(await page.locator('#mergeSubmit').isDisabled(),true);
 await page.locator('#mergeCheck').click();await waitTarget('Aurora Rising');
 assert.ok((await page.locator('#mergePreview').textContent()).includes('GROUP #11'));
 assert.ok((await page.locator('#mergePreview').textContent()).includes('Quality versions'));
 assert.ok((await page.locator('#mergePreview').textContent()).includes('Aurora Rising 480p.mkv'));
 assert.equal(await page.locator('#mergePreview .target-image-wrap small').textContent(),'Sample file');
 assert.equal(await page.locator('#mergeSubmit').isDisabled(),true);
 await page.locator('#mergeConfirm').check();assert.equal(await page.locator('#mergeSubmit').isEnabled(),true);
 // Another admin changes the target after it was reviewed. The server refuses the stale move.
 await update({group_id:'11',name:'Aurora Reviewed'});
 await page.locator('#mergeSubmit').click();await waitTarget('Aurora Reviewed');
 await page.locator('#mergeStatus').filter({hasText:'Destination changed'}).waitFor();
 assert.equal(await page.locator('#mergeConfirm').isChecked(),false);assert.equal(await page.locator('#mergeSubmit').isDisabled(),true);
 assert.equal((await json('/api/group/preview?id=11')).data.group.count,3);
 await page.locator('#mergeConfirm').check();await page.locator('#mergeSubmit').click();await page.locator('#mergeModal').waitFor({state:'detached'});
 assert.equal((await json('/api/group/preview?id=11')).data.group.count,4);
 console.log('File: exact lookup, validation, retry, stale/closed request races, change detection and confirmed move OK');

 // A whole-group move shows the source and protects against self-merge / duplicate clicks.
 const group=page.locator('.grp-card').filter({hasText:'Aurora Reviewed'}).first();await group.waitFor();
 await group.locator('.grp-title-button').click();await group.locator('.grp-oadmin button').filter({hasText:'Merge'}).click();
 await page.locator('#mergeModal').waitFor();assert.ok((await page.locator('.merge-source').textContent()).includes('Group #11'));
 await page.locator('#mergeId').fill('11');await page.locator('#mergeStatus').filter({hasText:'source group'}).waitFor();
 assert.equal(await page.locator('#mergeSubmit').isDisabled(),true);
 await page.locator('#mergeId').fill('12');await waitTarget('The Long Way Home');
 assert.ok((await page.locator('#mergePreview').textContent()).includes('Series / episodes'));
 await page.locator('#mergeConfirm').check();let posts=0;
 await page.route('**/api/group/merge',async r=>{posts++;await new Promise(resolve=>setTimeout(resolve,700));await r.continue();},{times:1});
 await page.locator('#mergeSubmit').click();assert.equal(await page.locator('#mergeId').isDisabled(),true);
 await page.evaluate(()=>document.querySelector('#mergeModal').dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true})));
 assert.equal(await page.locator('#mergeModal').count(),1);
 await page.locator('#mergeModal').waitFor({state:'detached',timeout:10000});assert.equal(posts,1);
 assert.equal((await json('/api/group/preview?id=11')).status,404);
 let dest=(await json('/api/group/preview?id=12')).data.group;assert.equal(dest.count,6);assert.equal(dest.group_type,'series');
 console.log('Group: source warning, same-group block, busy lock and target-preserving merge OK');

 // The group editor's existing-group picker must also preview and require confirmation.
 await page.locator('#selFab').click();let f2=page.locator('.file-card[data-fid="f2"]').first();await f2.waitFor();await f2.click();
 await page.locator('#selBar button').filter({hasText:'Group'}).click();await page.locator('#grpModal').waitFor();
 await page.locator('#gmSearch').fill('12');assert.equal(await page.locator('#gmSave').isDisabled(),true);
 const pick=page.locator('#gmGroupList .gm-pick[data-gid="12"]');await pick.waitFor();await pick.click();
 await page.locator('#gmPickNote .target-name').filter({hasText:'The Long Way Home'}).waitFor();
 assert.equal(await page.locator('#gmSave').isDisabled(),true);assert.equal(await page.locator('#gmConfirmTarget').isChecked(),false);
 await page.locator('#gmConfirmTarget').check();assert.equal(await page.locator('#gmSave').isEnabled(),true);
 await update({group_id:'12',name:'Series Reviewed'});await page.locator('#gmSave').click();
 await page.locator('#gmPickNote .target-name').filter({hasText:'Series Reviewed'}).waitFor();
 await page.locator('#gmPickStatus').filter({hasText:'Destination changed'}).waitFor();
 assert.equal(await page.locator('#gmConfirmTarget').isChecked(),false);assert.equal(await page.locator('#gmSave').isDisabled(),true);
 await page.locator('#gmConfirmTarget').check();
 await page.route('**/api/group/save',async r=>{await new Promise(resolve=>setTimeout(resolve,700));await r.continue();},{times:1});
 await page.locator('#gmSave').click();assert.equal(await page.locator('#gmSearch').isDisabled(),true);
 assert.equal(await page.locator('#gmConfirmTarget').isDisabled(),true);await page.locator('#grpModal').waitFor({state:'detached'});
 dest=(await json('/api/group/preview?id=12')).data.group;assert.equal(dest.count,7);assert.equal(dest.group_type,'series');
 console.log('Group editor: exact ID result, target preview, confirmation and changed-target retry OK');

 // Narrow text-mode layout, long/malicious names, keyboard close and real move.
 const attack=('Long destination name '.repeat(6)+'<img src=x onerror=window.__evil=1>').slice(0,190);
 await update({group_id:'12',name:attack});
 const edit=await page.request.post(base+'/api/edit_name',{data:{file_id:'s1',collection:'primary',target_collection:'primary',new_name:'<img src=x onerror=window.__evil=2>.mp4',add_caption:'Actor'}});
 assert.equal(edit.status(),200,await edit.text());
 await page.setViewportSize({width:320,height:720});await page.evaluate(()=>localStorage.setItem('ff_dashboard_mode','none'));await page.reload();
 trigger=await openFile('f3','none');await page.keyboard.press('Escape');assert.equal(await trigger.evaluate(e=>document.activeElement===e),true);
 await openFile('f3','none');await page.locator('#mergeId').fill('12');await page.locator('#mergePreview .target-name').waitFor();
 assert.equal(await page.locator('#mergePreview .target-name').textContent(),attack);
 assert.equal(await page.locator('#mergePreview .target-members li img').count(),0);assert.equal(await page.evaluate(()=>window.__evil||0),0);
 let size=await page.evaluate(()=>({view:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,card:document.querySelector('#mergeModal .merge-card').getBoundingClientRect().toJSON()}));
 assert.ok(size.scroll<=size.view+1,JSON.stringify(size));assert.ok(size.card.left>=0&&size.card.right<=320,JSON.stringify(size));
 await page.locator('#mergeConfirm').scrollIntoViewIfNeeded();await page.locator('#mergeConfirm').check();
 await page.locator('#mergeSubmit').scrollIntoViewIfNeeded();await page.locator('#mergeSubmit').click();await page.locator('#mergeModal').waitFor({state:'detached'});
 assert.equal((await json('/api/group/preview?id=12')).data.group.count,8);
 await page.locator('#cddGfBtn').click();await page.locator('#cddGfMenu [data-val=single]').click();
 await page.locator('.file-card[data-fid="f3"]').first().waitFor();await openFile('f3','none');
 await page.locator('#mergeId').fill('12');await page.locator('#mergeStatus').filter({hasText:'already in group'}).waitFor();
 assert.equal(await page.locator('#mergeSubmit').isDisabled(),true);await page.keyboard.press('Escape');
 console.log('320px text mode: no overflow, safe text, reachable controls and already-in-group block OK');

 // Choosing no destination still permits creating and editing a new series.
 await page.locator('#selFab').click();await page.locator('.file-card[data-fid="f3"]').first().click();
 await page.locator('.file-card[data-fid="s1"]').first().click();await page.locator('#selBar button').filter({hasText:'Group'}).click();
 await page.locator('#grpModal').waitFor();await page.locator('#gmName').fill('Fresh Series');
 await page.locator('#gmSearch').fill('99999');assert.equal(await page.locator('#gmSave').isDisabled(),true);
 await page.locator('#gmSearch').clear();assert.equal(await page.locator('#gmSave').isEnabled(),true);
 await page.locator('#grpModal .gm-type-option').filter({hasText:'Series / episodes'}).click();
 await page.locator('#gmMembers .gm-episode-input').first().fill('First episode');
 await page.locator('#gmSave').scrollIntoViewIfNeeded();await page.locator('#gmSave').click();
 await page.locator('#grpModal').waitFor({state:'detached'});
 let created=(await json('/api/group/preview?id=13')).data.group;
 assert.equal(created.name,'Fresh Series');assert.equal(created.group_type,'series');assert.equal(created.count,2);
 assert.equal(created.members[0].label,'First episode');
 console.log('Group editor: new series creation and episode labels remain functional');

 // Automatic groups need at least two distinct files; runtimes are required
 // for quality but may differ or be missing for marked episodes.
 assert.equal((await page.request.post(base+'/fixture/seed_auto')).status(),200);
 await page.reload();
 const autoMovie=page.locator('.grp-card').filter({hasText:'Auto Movie'}).first();await autoMovie.waitFor();
 const autoSeries=page.locator('.grp-card').filter({hasText:'Auto Mystery'}).first();await autoSeries.waitFor();
 assert.ok((await autoMovie.locator('.grp-textinfo').textContent()).includes('3 QUALITY'));
 assert.equal(await autoMovie.locator('.grp-textinfo .dur-chip').textContent(),'1:05');
 assert.ok((await autoSeries.locator('.grp-textinfo').textContent()).includes('3 EPISODES'));
 assert.equal(await autoSeries.locator('.grp-textinfo .dur-chip').count(),0);
 const duo=page.locator('.grp-card').filter({hasText:'Duo Film'}).first();await duo.waitFor();
 assert.equal(await duo.locator('.grp-textinfo .grp-badge').textContent(),'2 QUALITY');
 assert.equal(await page.locator('.grp-card').filter({hasText:'Unknown Runtime'}).count(),0);
 assert.equal(await page.locator('.file-card[data-fid^="no"]').count(),3);
 await page.locator('#cddGfBtn').click();await page.locator('#cddGfMenu [data-val=quality]').click();
 await autoSeries.waitFor({state:'detached'});await autoMovie.waitFor();
 await duo.waitFor();
 await page.locator('#cddGfBtn').click();await page.locator('#cddGfMenu [data-val=series]').click();
 await autoMovie.waitFor({state:'detached'});await duo.waitFor({state:'detached'});await autoSeries.waitFor();
 console.log('Automatic cards: two-file threshold, runtimes, episode series and filters OK');

 // Removing a member from a two-file group warns and closes its now-deleted
 // editor, while leaving both files intact.
 await page.locator('#cddGfBtn').click();await page.locator('#cddGfMenu [data-val=quality]').click();await duo.waitFor();
 const duoGid=(await duo.locator('.grp-textinfo .group-id-chip').textContent()).match(/\d+/)[0];
 await page.evaluate(k=>editGroup(k),await duo.getAttribute('data-gk'));
 await page.locator('#grpModal').waitFor();
 page.once('dialog',dialog=>{assert.ok(dialog.message().includes('dissolve'));dialog.accept();});
 await page.evaluate(()=>gmRemoveMember(0));await page.locator('#grpModal').waitFor({state:'detached'});
 assert.equal((await json('/api/group/preview?id='+duoGid)).status,404);
 console.log('Removing from a two-file group dissolves it without deleting files OK');

 // A selective filter can produce an empty continuation page. Even its final
 // page must retain Previous, and an edit must restart a stored cursor snapshot.
 const offsets=[];
 await page.route('**/api/search?*',r=>{
   const off=new URL(r.request().url()).searchParams.get('offset');offsets.push(off);
   return r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({
     results:[],next_offset:off==='0'?'g2_'+('a'.repeat(32)):'',is_admin:true
   })});
 });
 await page.evaluate(async()=>{document.querySelector('#q').value='Pagination Test';await doSearch(0,true);});
 assert.equal(await page.locator('#nBtn').isEnabled(),true);await page.locator('#nBtn').click();
 await page.locator('#pgInfo').filter({hasText:'Page 2'}).waitFor();
 assert.equal(await page.locator('#pageBox').isVisible(),true);assert.equal(await page.locator('#pBtn').isEnabled(),true);
 assert.equal(await page.locator('#nBtn').isDisabled(),true);await page.locator('#pBtn').click();
 await page.locator('#pgInfo').filter({hasText:'Page 1'}).waitFor();assert.equal(await page.locator('#nBtn').isEnabled(),true);
 await page.locator('#nBtn').click();await page.locator('#pgInfo').filter({hasText:'Page 2'}).waitFor();
 await page.evaluate(async()=>await doSearch(curOff,true,true));
 assert.equal(await page.locator('#pgInfo').textContent(),'Page 1');assert.equal(offsets[offsets.length-1],'0');
 console.log('Pagination: empty-page Previous and fresh stored-cursor reset OK');

 // Actor cards follow the same click-to-reveal and name/play behavior.
 await page.goto(base+'/fixture/actor-cards');
 for(const mode of ['tg','none']){
   await page.evaluate(mode=>showActorCard(mode,true),mode);
   const card=page.locator('#fixture-actor .file-card');
   assert.equal(await card.locator('.file-actions-toggle, .file-menu').count(),0);
   if(mode==='tg'){
     const toggle=card.locator('.file-poster-trigger');await toggle.focus();await page.keyboard.press('Enter');
     assert.equal(await toggle.getAttribute('aria-expanded'),'true');
   }else{
     assert.equal(await card.locator('.text-admin-row').isHidden(),true);
     await card.focus();await page.keyboard.press('Enter');
     assert.equal(await card.getAttribute('aria-expanded'),'true');
     assert.equal(await card.locator('.text-admin-row').isVisible(),true);
   }
   let edit=card.locator(mode==='tg'?'.poster-admin .btn-edit':'.text-admin-row .btn-edit');
   await edit.click();assert.equal(await page.locator('#emName').inputValue(),'Actor file');
   await page.evaluate(()=>closeCombinedModal());
   await page.evaluate(()=>{window.__actorPlayed=0;window.openInlinePlayer=()=>window.__actorPlayed++;});
   const name=card.locator('.fc-name');await name.click();await name.focus();await page.keyboard.press('Enter');
   assert.equal(await page.evaluate(()=>window.__actorPlayed),2);
   await page.evaluate(mode=>showActorCard(mode,false),mode);
   assert.equal(await page.locator('#fixture-actor .file-poster-trigger, #fixture-actor .text-admin-row').count(),0);
 }
 console.log('Actor cards: thumbnail edit and name playback work in poster and text modes');
 console.log('Page errors:',JSON.stringify(errors));assert.deepEqual(errors,[]);await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
