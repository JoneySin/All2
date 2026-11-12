// Run against a freshly started group_ui_fixture.py.
const {chromium}=require('playwright-core');
const assert=require('node:assert/strict');
(async()=>{
 const options={headless:true,args:['--no-sandbox','--disable-dev-shm-usage']};
 if(process.env.CHROMIUM_PATH)options.executablePath=process.env.CHROMIUM_PATH;
 const browser=await chromium.launch(options),page=await browser.newPage(),base=process.env.ALL2_UI_URL||'http://127.0.0.1:8765',errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',r=>r.request().url().startsWith(base+'/')?r.continue():r.abort());
 await page.addInitScript(()=>{window.Telegram={WebApp:{expand(){},ready(){},initData:'fixture'}};});
 await page.goto(base+'/dashboard');await page.locator('.grp-card').first().waitFor();
 const logo=page.locator('.topbar .logo');
 assert.equal(await logo.getAttribute('aria-label'),'FastFinder home');
 assert.equal(await logo.locator('.brand-word').innerText(),'FAST FINDER');
 assert.equal(await logo.locator('.brand-mark').innerText(),'F');
 assert.equal(await logo.locator('.brand-mark svg').count(),0);
 const mark=await logo.locator('.brand-mark').innerHTML();
 for(const width of [320,768,1200]){
   await page.setViewportSize({width,height:800});
   const box=await logo.boundingBox(),theme=await page.locator('.topbar .theme-btn').boundingBox();
   const word=await logo.locator('.brand-word').boundingBox();
   assert.ok(box.x>=0&&word.x+word.width<theme.x,`header overlap at ${width}`);
   assert.ok(theme.x+theme.width<=width,`header overflow at ${width}`);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 }
 await page.setViewportSize({width:320,height:800});
 await page.locator('#hamBtn').click();
 const entries=[['/dashboard','🏠','Home'],['/posts','📝','Posts'],['/actors','🎭','Actors'],['/stats','📊','Database Stats'],['/profile','⚙️','Profile Settings']];
 for(const [href,icon,name] of entries){
   const link=page.locator(`.sb-link[href="${href}"]`);
   assert.equal(await link.locator('.sb-icon').textContent(),icon);
   assert.equal(await link.getAttribute('href'),href);
   assert.equal(await link.locator('.sb-icon').getAttribute('aria-hidden'),'true');
   assert.equal(await link.locator('span').last().textContent(),name);
 }
 assert.ok((await page.locator('.sb-link[href="/dashboard"]').getAttribute('class')).includes('active'));
 assert.ok((await page.locator('.sb-logout').innerText()).includes('🚪'));
 assert.equal(await page.locator('.sb-logo .brand-word').innerText(),'FAST FINDER');
 await page.locator('#sbOverlay').click({position:{x:300,y:400}});
 const dark=await logo.locator('.brand-word').evaluate(el=>getComputedStyle(el).color);
 await page.locator('.theme-btn').click();
 const light=await logo.locator('.brand-word').evaluate(el=>getComputedStyle(el).color);assert.equal(dark,light); // Original red wordmark in both themes.
 assert.equal(await logo.locator('.brand-mark').evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(229, 9, 20)');
 await page.screenshot({path:'/tmp/fastfinder-brand.png'});
 await page.goto(base+'/posts');assert.equal(await page.locator('.topbar .brand-word').innerText(),'FAST FINDER');
 await page.locator('#hamBtn').click();assert.ok((await page.locator('.sb-link[href="/posts"]').getAttribute('class')).includes('active'));
 await page.goto(base+'/fixture/user-dashboard');await page.locator('#hamBtn').click();assert.equal(await page.locator('.sb-link[href="/stats"]').count(),0);
 await page.goto(base+'/miniapp');assert.equal(await page.locator('.tb .brand-word').innerText(),'FAST FINDER');
 assert.equal(await page.locator('.tb .brand-mark').innerHTML(),mark);
 await page.goto(base+'/fixture/landing');assert.equal(await page.locator('.navbar .brand-word').innerText(),'FAST FINDER');
 assert.equal(await page.locator('.navbar .brand-mark').innerHTML(),mark);
 assert.deepEqual(errors,[]);await browser.close();console.log('FastFinder brand and emoji navigation: roles, themes and mobile/desktop OK');
})().catch(e=>{console.error(e);process.exit(1)});
