// Run against a freshly started tests/group_ui_fixture.py.
const {chromium}=require('playwright-core');
const assert=require('node:assert/strict');
(async()=>{
 const options={headless:true,args:['--no-sandbox','--disable-dev-shm-usage']};
 if(process.env.CHROMIUM_PATH)options.executablePath=process.env.CHROMIUM_PATH;
 const browser=await chromium.launch(options),page=await browser.newPage({viewport:{width:1100,height:850}});
 const base=process.env.ALL2_UI_URL||'http://127.0.0.1:8765',errors=[],requests=[];
 page.on('request',r=>{if(r.url().includes('/api/search?'))requests.push(r.url());});
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',r=>r.request().url().startsWith(base+'/')?r.continue():r.abort());
 const seeded=await page.request.post(base+'/fixture/seed_mixed_recent');assert.equal(seeded.status(),200);
 const {members,singles}=await seeded.json();
 await page.addInitScript(()=>localStorage.setItem('ff_view_mode','text'));
 await page.goto(base+'/dashboard');await page.locator('.grp-card').filter({hasText:'Mixed Recent Group'}).waitFor();
 assert.ok(await page.locator('#results > .file-card').count()>0);
 await page.locator('#cddGfBtn').click();
 await Promise.all([page.waitForResponse(r=>r.url().includes('/api/search?')&&r.url().includes('gf=single')),page.locator('#cddGfMenu [data-val=single]').click()]);
 await page.locator('.file-card[data-fid="oldgroup00"]').waitFor();
 assert.equal(await page.locator('#results > .grp-card').count(),0);
 const first=await page.locator('#results > .file-card').evaluateAll(es=>es.map(e=>e.dataset.fid));
 assert.deepEqual(first.slice(0,12),[...singles].reverse()); // Primary's newest standalone files stay first.
 assert.ok(first.includes('oldgroup00'));
 // Membership is retained and editable even though its badge is hidden.
 const f=page.locator('.file-card[data-fid="oldgroup00"]');await f.locator('.fc-text-info').click();await f.locator('.text-admin-row .btn-edit').first().click();
 await page.locator('#emCurrentGroup').filter({hasText:'#19'}).waitFor();await page.locator('#editCombinedModal .file-editor-cancel').click();
 const all=[...first];let pageNum=1;
 const prefetched=requests.find(u=>{let p=new URL(u).searchParams;return p.get('gf')==='single'&&p.get('offset')==='21';});
 assert.ok(prefetched,'next page was not prefetched');
 while(await page.locator('#nBtn').isEnabled()){
   assert.ok(pageNum<12,'pagination did not terminate');
   pageNum++;await page.locator('#nBtn').click();await page.locator('#pgInfo').filter({hasText:'Page '+pageNum}).waitFor();
   if(pageNum===2)assert.equal(requests.filter(u=>u===prefetched).length,1,'navigation should reuse prefetched page');
   assert.equal(await page.locator('#results > .grp-card').count(),0);
   all.push(...await page.locator('#results > .file-card').evaluateAll(es=>es.map(e=>e.dataset.fid)));
 }
 for(const fid of [...members,...singles,'a1','a2','a3','s1','s2','f1','f2','f3'])assert.ok(all.includes(fid),fid);
 assert.equal(all.length,new Set(all).size);
 await page.locator('#pBtn').click();await page.locator('#pgInfo').filter({hasText:'Page '+(pageNum-1)}).waitFor();
 const preview=await page.request.get(base+'/api/group/preview?id=19');assert.equal((await preview.json()).group.count,27);
 assert.deepEqual(errors,[]);await browser.close();console.log('Recent UnGroup: raw source order, every file across pages, back navigation and membership OK');
})().catch(e=>{console.error(e);process.exit(1)});
