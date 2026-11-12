// Run against a freshly started group_ui_fixture.py.
const {chromium}=require('playwright-core');
const assert=require('node:assert/strict');
(async()=>{
 const options={headless:true,args:['--no-sandbox','--disable-dev-shm-usage']};
 if(process.env.CHROMIUM_PATH)options.executablePath=process.env.CHROMIUM_PATH;
 const browser=await chromium.launch(options),page=await browser.newPage();
 const base=process.env.ALL2_UI_URL||'http://127.0.0.1:8765',errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',r=>r.request().url().startsWith(base+'/')?r.continue():r.abort());
 await page.goto(base+'/dashboard');await page.locator('#results .grp-card').first().waitFor();
 const panel=page.locator('.home-search-panel');
 const appearance=()=>panel.evaluate(el=>{const s=getComputedStyle(el);return [s.backgroundColor,s.borderColor,s.borderWidth,s.borderRadius,s.boxShadow];});
 const dark=await appearance();assert.equal(dark[2],'1px');assert.equal(dark[3],'12px');
 for(const width of [320,390,767,768,1024,1440,1920]){
   await page.setViewportSize({width,height:800});
   const bounds=await panel.boundingBox();assert.ok(bounds.x>=0&&bounds.x+bounds.width<=width);
   for(const selector of ['#qWrap','#cddGfWrap','#cddColWrap','#cddModeWrap']){
     const el=panel.locator(selector);assert.equal(await el.count(),1);
     const rect=await el.boundingBox();assert.ok(rect.x>=bounds.x&&rect.x+rect.width<=bounds.x+bounds.width,selector+' horizontal overflow');
     assert.ok(rect.y>=bounds.y&&rect.y+rect.height<=bounds.y+bounds.height,selector+' vertical overflow');
   }
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'page overflow '+width);
   const q=await page.locator('#qWrap').boundingBox(),gf=await page.locator('#cddGfWrap').boundingBox();
   const col=await page.locator('#cddColWrap').boundingBox(),mode=await page.locator('#cddModeWrap').boundingBox();
   if(width>=768){
     for(const r of [gf,col,mode])assert.ok(r.y>=q.y+q.height-1,'filter below search at '+width);
     assert.ok(Math.abs(gf.y-col.y)<1&&Math.abs(col.y-mode.y)<1,'filters share a row at '+width);
     assert.ok(gf.x+gf.width<=col.x+1&&col.x+col.width<=mode.x+1,'filter order at '+width);
     assert.ok(Math.abs(gf.width-col.width)<1&&Math.abs(col.width-mode.width)<1,'equal filter widths at '+width);
     assert.ok(Math.abs(q.width-(mode.x+mode.width-q.x))<1,'full-width search at '+width);
   }else{
     assert.ok(Math.abs((q.y+q.height/2)-(gf.y+gf.height/2))<1,'mobile group filter stays alongside search at '+width);
     assert.ok(col.y>=q.y+q.height-1&&Math.abs(col.y-mode.y)<1,'mobile secondary filters stay below at '+width);
   }
   for(const type of ['Gf','Col','Mode']){
     await page.locator('#cdd'+type+'Btn').click();
     const menu=page.locator('#cdd'+type+'Menu');assert.equal(await menu.isVisible(),true);
     const rect=await menu.boundingBox();assert.ok(rect.x>=0&&rect.x+rect.width<=width,'menu overflow '+type+' '+width);
     await page.locator('#cdd'+type+'Btn').click();
   }
 }
 await page.setViewportSize({width:1100,height:800});
 await page.locator('#cddColBtn').click();
 await Promise.all([page.waitForResponse(r=>r.url().includes('/api/search?')&&r.url().includes('col=cloud')),page.locator('#cddColMenu [data-val=cloud]').click()]);
 assert.equal(await page.locator('#cddColLabel').innerText(),'🔵 Cloud');
 await page.locator('#cddColBtn').click();
 await Promise.all([page.waitForResponse(r=>r.url().includes('/api/search?')&&r.url().includes('col=all')),page.locator('#cddColMenu [data-val=all]').click()]);
 await page.locator('#cddModeBtn').click();
 await Promise.all([page.waitForResponse(r=>r.url().includes('/api/search?')&&r.url().includes('mode=none')),page.locator('#cddModeMenu [data-val=none]').click()]);
 assert.equal(await page.locator('#cddModeLabel').innerText(),'📄 Text Mode');
 await page.locator('#cddGfBtn').click();
 await Promise.all([page.waitForResponse(r=>r.url().includes('/api/search?')&&r.url().includes('gf=single')),page.locator('#cddGfMenu [data-val=single]').click()]);
 await page.locator('#results > .file-card').first().waitFor();
 await page.locator('#q').fill('Aurora');
 await page.waitForResponse(r=>r.url().includes('/api/search?')&&r.url().includes('q=Aurora'));
 await page.locator('#results .file-card').first().waitFor();
 await page.locator('.theme-btn').click();
 const light=await appearance();assert.notEqual(light[0],dark[0]);assert.notEqual(light[1],dark[1]);
 await page.goto(base+'/posts');
 const post=await page.locator('.search-box').evaluate(el=>{const s=getComputedStyle(el);return [s.backgroundColor,s.borderColor,s.borderWidth,s.borderRadius,s.boxShadow];});
 assert.deepEqual(post,light);
 await page.goto(base+'/actors');
 const actor=await page.locator('.search-box').evaluate(el=>{const s=getComputedStyle(el);return [s.backgroundColor,s.borderColor,s.borderWidth,s.borderRadius,s.boxShadow];});
 assert.deepEqual(actor,light);
 assert.deepEqual(errors,[]);await browser.close();console.log('Home search panel: shared style, themes, filters and responsive menus OK');
})().catch(e=>{console.error(e);process.exit(1)});
