// Run against a fresh group_ui_fixture.py with Playwright and cropperjs 2.3.1 installed.
const {chromium}=require('playwright-core');
const assert=require('node:assert/strict');
const cropperPath=require.resolve('cropperjs/dist/cropper.min.js');
const base=process.env.ALL2_UI_URL||'http://127.0.0.1:8765';
(async()=>{
 const options={args:['--no-sandbox','--disable-dev-shm-usage'],headless:true};
 if(process.env.CHROMIUM_PATH)options.executablePath=process.env.CHROMIUM_PATH;
 const browser=await chromium.launch(options);
 const page=await browser.newPage({viewport:{width:1440,height:950}}), errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',r=>r.request().url().startsWith(base+'/')?r.continue():r.abort());
 await page.route('**/cropperjs@2.3.1/dist/cropper.min.js',r=>r.fulfill({path:cropperPath,contentType:'application/javascript'}));
 await page.goto(base+'/dashboard',{waitUntil:'domcontentloaded'});await page.locator('.grp-card').first().waitFor();
 assert.equal(await page.evaluate(()=>window.Cropper.Cropper.version),'2.3.1');
 async function image(width,height){
   return Buffer.from(await page.evaluate(([w,h])=>{let c=document.createElement('canvas');c.width=w;c.height=h;let x=c.getContext('2d');x.fillStyle='#a0c030';x.fillRect(0,0,w,h);return c.toDataURL('image/png').split(',')[1];},[width,height]),'base64');
 }
 async function verify(instance){
   return page.evaluate(async name=>{
     const c=window[name];await c.thumbReady;const s=c.getCropperSelection(),i=c.getCropperImage(),v=c.getCropperCanvas();
     const bounds=()=>{const r=i.getBoundingClientRect(),cv=v.getBoundingClientRect();return {x:r.left-cv.left,y:r.top-cv.top,w:r.width,h:r.height};};
     const inside=()=>{let r=bounds();return s.x>=r.x-1&&s.y>=r.y-1&&s.x+s.width<=r.x+r.w+1&&s.y+s.height<=r.y+r.h+1;};
     if(!inside()||Math.abs(s.width/s.height-16/9)>0.04)throw Error('Initial crop is out of bounds');
     let prev=[s.x,s.y,s.width,s.height];s.$move(10000,10000);if(!inside())throw Error('Selection escaped image');
     s.$change(prev[0],prev[1],prev[2]*0.8,prev[3]*0.8);if(!inside())throw Error('Resize escaped image');
     i.$move(10000,10000);if(!inside())throw Error('Image movement escaped selection');
     i.$zoom(0.2);if(!inside())throw Error('Zoom escaped selection');i.$zoom(-0.99);if(!inside())throw Error('Zoom out escaped selection');
     let blob=await exportThumbCrop(c),bm=await createImageBitmap(blob);return {width:bm.width,height:bm.height,type:blob.type,size:blob.size};
   },instance);
 }
 for(const [w,h] of [[400,600],[900,400],[500,500]]){
   await page.evaluate(()=>editFile('f1','primary','test.mp4',''));
   await page.locator('#emFile').setInputFiles({name:'image.png',mimeType:'image/png',buffer:await image(w,h)});
   await page.waitForFunction(()=>window.cropperInstance&&window.cropperInstance.thumbReady);
   const info=await verify('cropperInstance');assert.deepEqual([info.width,info.height,info.type],[1280,720,'image/jpeg']);assert.ok(info.size>100);
   await page.evaluate(()=>closeCombinedModal());
 }
 // Actual editor upload: capture JPEG payload from the multipart request.
 let fileUpload;
 await page.route('**/api/upload_thumb',r=>{fileUpload=r.request().postDataBuffer();return r.fulfill({json:{success:true}});});
 await page.route('**/api/edit_name',r=>r.fulfill({json:{success:true}}));
 await page.evaluate(()=>editFile('f1','primary','test.mp4',''));
 await page.waitForFunction(()=>window.fileEditorLoaded);
 await page.locator('#emFile').setInputFiles({name:'portrait.png',mimeType:'image/png',buffer:await image(400,600)});
 await page.waitForFunction(()=>window.cropperInstance&&window.cropperInstance.thumbReady);
 await page.evaluate(()=>saveAllChanges());assert.ok(fileUpload&&fileUpload.includes(Buffer.from([0xff,0xd8,0xff])));
 // Group cover uses the same crop path and multipart upload.
 let groupUpload;
 await page.route('**/api/group/update',r=>r.fulfill({json:{success:true}}));
 await page.route('**/api/group/upload_thumb',r=>{groupUpload=r.request().postDataBuffer();return r.fulfill({json:{success:true}});});
 await page.evaluate(()=>openGroupModal({mode:'edit',gid:'11',num:11,name:'Test',members:[{file_id:'f1',name:'a'},{file_id:'f2',name:'b'}]}));
 await page.locator('#gmFile').setInputFiles({name:'portrait.png',mimeType:'image/png',buffer:await image(400,600)});
 await page.waitForFunction(()=>window.gmCropper&&window.gmCropper.thumbReady);
 assert.equal((await verify('gmCropper')).width,1280);
 await page.evaluate(()=>saveGroupModal());assert.ok(groupUpload&&groupUpload.includes(Buffer.from([0xff,0xd8,0xff])));
 // If the CDN fails, both editors retain original-file upload.
 await page.evaluate(()=>window.Cropper=undefined);
 await page.evaluate(()=>editFile('f1','primary','test.mp4',''));await page.waitForFunction(()=>window.fileEditorLoaded);
 const original=await image(400,600);await page.locator('#emFile').setInputFiles({name:'fallback.png',mimeType:'image/png',buffer:original});
 await page.waitForFunction(()=>document.querySelector('#emPreviewBox img')?.src.startsWith('data:'));
 fileUpload=null;await page.evaluate(()=>saveAllChanges());assert.ok(fileUpload&&fileUpload.includes(original));
 await page.evaluate(()=>openGroupModal({mode:'edit',gid:'11',num:11,name:'Test',members:[{file_id:'f1',name:'a'},{file_id:'f2',name:'b'}]}));
 await page.locator('#gmFile').setInputFiles({name:'fallback.png',mimeType:'image/png',buffer:original});
 await page.waitForFunction(()=>document.querySelector('#gmCropWrap img')?.src.startsWith('data:'));
 groupUpload=null;await page.evaluate(()=>saveGroupModal());assert.ok(groupUpload&&groupUpload.includes(original));
 assert.deepEqual(errors,[]);await browser.close();console.log('Cropper editor checks passed');
})().catch(e=>{console.error(e);process.exit(1);});
