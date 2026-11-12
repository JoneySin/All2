// A failed speculative request must be retried when the user actually navigates.
const {chromium}=require('playwright-core');
const assert=require('node:assert/strict');
(async()=>{
 const opt={headless:true,args:['--no-sandbox','--disable-dev-shm-usage']};if(process.env.CHROMIUM_PATH)opt.executablePath=process.env.CHROMIUM_PATH;
 const browser=await chromium.launch(opt),page=await browser.newPage(),base=process.env.ALL2_UI_URL||'http://127.0.0.1:8765';
 let count=0,errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',r=>{
   if(!r.request().url().startsWith(base+'/'))return r.abort();
   const u=new URL(r.request().url());
   if(u.pathname==='/api/search'&&u.searchParams.get('gf')==='single'&&u.searchParams.get('offset')==='21'){
     count++;if(count===1)return r.fulfill({status:503,contentType:'application/json',body:'{"error":"temporary"}'});
   }
   return r.continue();
 });
 await page.request.post(base+'/fixture/seed_mixed_recent');
 await page.goto(base+'/dashboard');await page.locator('#results .grp-card').first().waitFor();
 await page.locator('#cddGfBtn').click();
 await Promise.all([page.waitForResponse(r=>r.url().includes('gf=single')&&r.url().includes('offset=21')),page.locator('#cddGfMenu [data-val=single]').click()]);
 await page.locator('#nBtn').click();await page.locator('#pgInfo').filter({hasText:'Page 2'}).waitFor();
 assert.equal(count,2);assert.ok(await page.locator('#results > .file-card').count()>0);assert.deepEqual(errors,[]);
 await browser.close();console.log('Failed prefetch retries on navigation OK');
})().catch(e=>{console.error(e);process.exit(1)});
