// Run with a freshly started tests/group_ui_fixture.py.
const {chromium}=require('playwright-core');
const assert=require('node:assert/strict');
(async()=>{
 const launch={args:['--no-sandbox','--disable-dev-shm-usage'],headless:true};
 if(process.env.CHROMIUM_PATH)launch.executablePath=process.env.CHROMIUM_PATH;
 const browser=await chromium.launch(launch);
 const page=await browser.newPage({viewport:{width:320,height:720}}),errors=[];
 const base=process.env.ALL2_UI_URL||'http://127.0.0.1:8765';
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',r=>r.request().url().startsWith(base+'/')?r.continue():r.abort());
 await page.addInitScript(()=>localStorage.setItem('ff_view_mode','text'));
 await page.goto(base+'/dashboard');
 const file=page.locator('.file-card[data-fid="f1"]').first();await file.waitFor();
 await file.locator('.fc-text-info').click();
 // Compare the real migration dialog and file editor for exactly the same group.
 await file.locator('.text-admin-row button').filter({hasText:'Merge'}).click();
 await page.locator('#mergeId').fill('12');await page.locator('#mergePreview .target-name').waitFor();
 const migrationHtml=await page.locator('#mergePreview .target-preview').innerHTML();
 assert.equal(await page.locator('#mergePreview .target-image img').getAttribute('src'),'/api/thumb?file_id=s1&col=primary&v=initial');
 assert.equal(await page.locator('#mergePreview .target-image-wrap small').textContent(),'Sample file');
 assert.ok(!(await page.locator('#mergePreview').textContent()).includes('Episode 1.mp4'));
 await page.keyboard.press('Escape');
 if(!await file.evaluate(e=>e.classList.contains('admin-active')))await file.locator('.fc-text-info').click();
 await file.locator('.text-admin-row .btn-edit').first().click();
 const modal=page.locator('#editCombinedModal');
 await modal.locator('#emSaveBtn').waitFor({state:'visible'});
 await page.waitForFunction(()=>!document.querySelector('#emSaveBtn').disabled);
 assert.equal(await modal.locator('#emCurrentGroup').textContent(),'Current group: None');
 assert.ok((await modal.locator('#emQualityHelp').textContent()).includes('1280×720'));
 await modal.locator('#emQuality').fill('1080p');
 await modal.locator('#emGroupId').fill('invalid');await modal.locator('#emGroupCheck').click();
 assert.ok((await modal.locator('#emGroupStatus').textContent()).includes('valid numeric'));
 await modal.locator('#emGroupId').fill('999');await modal.locator('#emGroupCheck').click();
 await modal.locator('#emGroupStatus').filter({hasText:'not found'}).waitFor();
 await modal.locator('#emGroupId').fill('#12');await modal.locator('#emGroupCheck').click();
 await modal.locator('#emGroupPreview').filter({hasText:'The Long Way Home'}).waitFor();
 assert.equal(await modal.locator('#emGroupPreview .target-preview').innerHTML(),migrationHtml);
 assert.ok(!(await modal.locator('#emGroupPreview').textContent()).includes('Episode 1.mp4'));
 assert.equal(await modal.locator('#emGroupMove').isDisabled(),true);
 // Exercise covers, broken/missing images and hostile API content on the shared renderer.
 let mode='cover';
 await page.route('**/api/group/preview?*',async route=>{
   const response=await route.fetch(), data=await response.json();
   if(data.group&&mode){
     if(mode==='cover'){data.group.cover='/api/group/thumb?gid=12&v=revision';data.group.cover_label='Group cover';}
     if(mode==='missing')data.group.cover='';
     if(mode==='unsafe'){data.group.cover='https://evil.example/p.png';data.group.name='<img src=x onerror=window.__evil=1>';}
     if(mode==='broken'){data.group.cover='/api/thumb?broken=1';data.group.cover_label='Sample file';}
     if(mode==='mismatch')data.group.id='11';
   }
   await route.fulfill({response,json:data});
 });
 await page.route('**/api/group/thumb?*',r=>r.fulfill({status:200,contentType:'image/gif',body:Buffer.from('47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b','hex')}));
 await page.route('**/api/thumb?broken=1',r=>r.fulfill({status:404,body:''}));
 async function checkMode(m){mode=m;await modal.locator('#emGroupCheck').click();}
 await checkMode('cover');await modal.locator('#emGroupPreview .target-image-wrap small').filter({hasText:'Group cover'}).waitFor();
 assert.ok((await modal.locator('#emGroupPreview img').getAttribute('src')).startsWith('/api/group/thumb?'));
 await checkMode('missing');await modal.locator('#emGroupPreview .target-image-wrap small').filter({hasText:'No image'}).waitFor();
 assert.equal(await modal.locator('#emGroupPreview img').count(),0);
 await checkMode('unsafe');await modal.locator('#emGroupPreview .target-name').filter({hasText:'<img src=x'}).waitFor();
 assert.equal(await modal.locator('#emGroupPreview img').count(),0);assert.equal(await page.evaluate(()=>window.__evil||0),0);
 await checkMode('broken');await modal.locator('#emGroupPreview .target-image-wrap small').filter({hasText:'No image'}).waitFor();
 assert.equal(await modal.locator('#emGroupPreview img').isHidden(),true);
 await checkMode('mismatch');await modal.locator('#emGroupStatus').filter({hasText:'Could not verify'}).waitFor();
 assert.equal(await modal.locator('#emGroupPreview').isHidden(),true);assert.equal(await modal.locator('#emGroupMove').isDisabled(),true);
 mode='';await modal.locator('#emGroupCheck').click();await modal.locator('#emGroupPreview .target-name').filter({hasText:'The Long Way Home'}).waitFor();
 // Even a non-abortable slow response cannot replace a newer checked destination.
 await page.evaluate(()=>{const original=window.fetch;window.__editorSlowStarted=false;window.fetch=function(input,init){
   if(typeof input==='string'&&input.includes('/api/group/preview?id=11')){
     window.__editorSlowStarted=true;const options={...init};delete options.signal;
     return original.call(this,input,options).then(r=>new Promise(resolve=>setTimeout(()=>resolve(r),900)));
   }return original.call(this,input,init);
 };});
 await modal.locator('#emGroupId').fill('11');await modal.locator('#emGroupCheck').click();await page.waitForFunction(()=>window.__editorSlowStarted);
 await modal.locator('#emGroupId').fill('12');await modal.locator('#emGroupCheck').click();
 await modal.locator('#emGroupPreview .target-name').filter({hasText:'The Long Way Home'}).waitFor();
 await page.waitForTimeout(1000);assert.equal(await modal.locator('#emGroupPreview .target-name').textContent(),'The Long Way Home');
 assert.equal(await modal.locator('#emGroupConfirm').isChecked(),false);
 await page.evaluate(()=>document.documentElement.classList.add('light'));
 assert.equal(await modal.locator('#emGroupPreview .target-preview').isVisible(),true);
 await page.evaluate(()=>document.documentElement.classList.remove('light'));
 // Destination changed since preview: no move until a fresh preview and confirmation.
 let r=await page.request.post(base+'/api/group/update',{data:{group_id:'12',name:'Changed destination'}});assert.equal(r.status(),200);
 await modal.locator('#emGroupConfirm').check();await modal.locator('#emGroupMove').click();
 await modal.locator('#emGroupStatus').filter({hasText:'Destination changed'}).waitFor();
 assert.equal(await modal.locator('#emCurrentGroup').textContent(),'Current group: None');
 await modal.locator('#emGroupCheck').click();await modal.locator('#emGroupPreview').filter({hasText:'Changed destination'}).waitFor();
 await modal.locator('#emGroupConfirm').check();await modal.locator('#emGroupMove').click();
 await modal.locator('#emCurrentGroup').filter({hasText:'#12'}).waitFor();
 assert.equal(await modal.locator('#emQuality').inputValue(),'1080p');
 await modal.locator('#emGroupId').fill('12');await modal.locator('#emGroupCheck').click();
 assert.ok((await modal.locator('#emGroupStatus').textContent()).includes('already'));
 const dimensions=await modal.locator('.file-editor').evaluate(e=>({width:e.clientWidth,scroll:e.scrollWidth}));
 assert.ok(dimensions.scroll<=dimensions.width+1,JSON.stringify(dimensions));
 await modal.locator('#emSaveBtn').click();await page.waitForFunction(()=>!document.querySelector('#editCombinedModal').classList.contains('open'));
 r=await page.request.get(base+'/api/file/editor?file_id=f1&collection=primary');const data=await r.json();
 assert.equal(data.group_id,'12');assert.equal(data.quality_override,'1080p');
 await page.goto(base+'/fixture/actor-cards');
 const card=page.locator('#fixture-actor .file-card');await card.locator('.file-poster-trigger').click();await card.locator('.btn-edit').click();
 await page.waitForFunction(()=>!document.querySelector('#emSaveBtn').disabled);
 assert.equal(await page.locator('#emCurrentGroup').textContent(),'Current group: None');
 await page.locator('#emGroupId').fill('11');await page.locator('#emGroupCheck').click();
 await page.locator('#emGroupPreview').filter({hasText:'Aurora Rising'}).waitFor();
 await page.locator('#emGroupConfirm').check();await page.locator('#emGroupMove').click();
 await page.locator('#emCurrentGroup').filter({hasText:'#11'}).waitFor();
 await page.locator('#emQuality').fill('4K');await page.locator('#emSaveBtn').click();
 await page.waitForFunction(()=>!document.querySelector('#editCombinedModal').classList.contains('open'));
 r=await page.request.get(base+'/api/file/editor?file_id=actor-file&collection=primary');const actorData=await r.json();
 assert.equal(actorData.group_id,'11');assert.equal(actorData.quality_override,'4K');
 r=await page.request.get(base+'/api/group/preview?id=11');
 assert.equal((await r.json()).group.members.find(m=>m.name==='Actor file').label,'4K');
 assert.deepEqual(errors,[]);console.log('File editor: quality override, group preview, stale destination, moves, actor cards and 320px layout OK');
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
