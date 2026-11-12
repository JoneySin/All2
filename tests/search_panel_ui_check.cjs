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
 for(const width of [320,768,1100]){
   await page.setViewportSize({width,height:800});
   const bounds=await panel.boundingBox();assert.ok(bounds.x>=0&&bounds.x+bounds.width<=width);
   for(const selector of ['#qWrap','#cddGfWrap','#cddColWrap','#cddModeWrap']){
     const el=panel.locator(selector);assert.equal(await el.count(),1);
     const rect=await el.boundingBox();assert.ok(rect.x>=bounds.x&&rect.x+rect.width<=bounds.x+bounds.width,selector+' horizontal overflow');
     assert.ok(rect.y>=bounds.y&&rect.y+rect.height<=bounds.y+bounds.height,selector+' vertical overflow');
   }
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'page overflow '+width);
   for(const type of ['Gf','Col','Mode']){
     await page.locator('#cdd'+type+'Btn').click();
     const menu=page.locator('#cdd'+type+'Menu');assert.equal(await menu.isVisible(),true);
     const rect=await menu.boundingBox();assert.ok(rect.x>=0&&rect.x+rect.width<=width,'menu overflow '+type+' '+width);
     await page.locator('#cdd'+type+'Btn').click();
   }
 }
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
