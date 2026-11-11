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
   if(!await f.evaluate(e=>e.classList.contains('admin-active')))await f.locator('.file-menu').click();
   let b=f.locator(mode==='tg'?'.poster-admin button':'.text-admin-row button').filter({hasText:'Merge'});await b.click();
   await page.locator('#mergeModal').waitFor();return b;
 }
 async function waitTarget(name){await page.locator('#mergePreview .target-name').filter({hasText:name}).waitFor({timeout:10000});}
 await page.goto(base+'/dashboard',{waitUntil:'domcontentloaded'});await page.locator('.grp-card').first().waitFor();
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
 await group.locator('.grp-action').click();await group.locator('.grp-oadmin button').filter({hasText:'Merge'}).click();
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
 console.log('Page errors:',JSON.stringify(errors));assert.deepEqual(errors,[]);await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
