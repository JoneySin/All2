// Run with a fresh group_ui_fixture.py (one saved quality group and one series).
const {chromium}=require('playwright-core');
const assert=require('node:assert/strict');
(async()=>{
 const opts={headless:true,args:['--no-sandbox','--disable-dev-shm-usage']};
 if(process.env.CHROMIUM_PATH)opts.executablePath=process.env.CHROMIUM_PATH;
 const browser=await chromium.launch(opts),page=await browser.newPage();
 const base=process.env.ALL2_UI_URL||'http://127.0.0.1:8765',errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',r=>{
   const url=r.request().url();
   if(url.startsWith(base+'/api/db_stats')) return r.fulfill({json:{used:'0 MB',percent:0}});
   return url.startsWith(base+'/') ? r.continue() : r.abort();
 });
 try {
   for(const width of [320,768,1200]){
     await page.setViewportSize({width,height:900});
     await page.goto(base+'/stats');
     const card=page.locator('#saved-group-stats');
     await card.scrollIntoViewIfNeeded();
     await page.waitForFunction(()=>performance.now()>1600 && document.querySelector('#saved-group-total')?.textContent.trim()==='2' &&
       document.querySelector('#saved-quality-count')?.textContent.trim()==='1' &&
       document.querySelector('#saved-series-count')?.textContent.trim()==='1');
     assert.match(await card.innerText(),/Saved Groups · Total/i);
     assert.match(await card.innerText(),/Quality Groups/);
     assert.match(await card.innerText(),/Series Groups/);
     const box=await card.boundingBox();
     assert.ok(box.x>=0 && box.x+box.width<=width,`card overflow at ${width}`);
     for(const id of ['saved-group-total','saved-quality-count','saved-series-count']){
       const item=await page.locator('#'+id).boundingBox();
       assert.ok(item.x>=box.x && item.x+item.width<=box.x+box.width,`${id} overflow at ${width}`);
     }
     assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
     await page.locator('.theme-btn').click();
     assert.equal((await page.locator('#saved-series-count').innerText()).trim(),'1');
   }
   assert.deepEqual(errors,[]);
   console.log('Database stats: saved quality and series counts, responsive card and themes OK');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
