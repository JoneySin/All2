// Offline player smoke check against tests/group_ui_fixture.py and locally installed Plyr 3.8.5.
const {chromium}=require('playwright-core');
const assert=require('node:assert/strict');
const path=require('node:path');
(async()=>{
 const opts={headless:true,args:['--no-sandbox','--disable-dev-shm-usage']};if(process.env.CHROMIUM_PATH)opts.executablePath=process.env.CHROMIUM_PATH;
 const browser=await chromium.launch(opts), page=await browser.newPage(), errors=[];
 const base=process.env.ALL2_UI_URL||'http://127.0.0.1:8765', dist=path.dirname(require.resolve('plyr'));
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',r=>r.request().url().startsWith(base+'/')||r.request().url().startsWith('blob:')?r.continue():r.abort());
 await page.route('**/plyr@3.8.5/dist/*',r=>r.fulfill({path:path.join(dist,new URL(r.request().url()).pathname.split('/').pop())}));
 await page.addInitScript(()=>{window.Telegram={WebApp:{expand(){},ready(){},initData:'fixture'}};});
 // Record a tiny, local browser-generated video; no Telegram or remote media involved.
 async function videoUrl(){return page.evaluate(async()=>{const c=document.createElement('canvas');c.width=160;c.height=90;const ctx=c.getContext('2d');ctx.fillStyle='red';ctx.fillRect(0,0,160,90);const stream=c.captureStream(10);const chunks=[];const rec=new MediaRecorder(stream,{mimeType:'video/webm'});rec.ondataavailable=e=>chunks.push(e.data);rec.start();let n=0;const tick=setInterval(()=>{ctx.fillStyle=(n++%2?'red':'blue');ctx.fillRect(0,0,160,90);},50);await new Promise(r=>setTimeout(r,1000));clearInterval(tick);await new Promise(r=>{rec.onstop=r;rec.stop();});stream.getTracks().forEach(t=>t.stop());return URL.createObjectURL(new Blob(chunks,{type:'video/webm'}));});}
 async function confirmPlaying(selector){await page.evaluate(async sel=>{const v=document.querySelector(sel);v.muted=true;v.loop=true;await v.play();},selector);await page.waitForFunction(sel=>{const v=document.querySelector(sel);return v&&!v.paused&&v.readyState>=2;},selector);}
 await page.goto(base+'/fixture/watch',{waitUntil:'domcontentloaded'});await page.waitForSelector('.plyr__controls');
 const watchUrl=await videoUrl();await page.evaluate(url=>{const v=document.querySelector('#player');v.src=url;v.load();},watchUrl);await confirmPlaying('#player');
 await page.goto(base+'/miniapp',{waitUntil:'domcontentloaded'});await page.waitForFunction(()=>typeof Plyr==='function');
 const miniUrl=await videoUrl();await page.evaluate(url=>openSheet(url,'Test',url),miniUrl);await page.waitForSelector('#playerSheet .plyr__controls');await confirmPlaying('#pv2');
 await page.evaluate(()=>closePlayer());assert.equal(await page.locator('#playerSheet').evaluate(e=>e.classList.contains('open')),false);
 assert.deepEqual(errors,[]);await browser.close();console.log('Plyr watch and mini-app: local playback and controls OK');
})().catch(e=>{console.error(e);process.exit(1);});
