// Browser regression against tests/profile_ui_fixture.py, which is test-only.
const {chromium} = require('playwright-core');
const assert = require('node:assert/strict');
(async()=>{
  const launch={args:['--no-sandbox','--disable-dev-shm-usage'],headless:true};
  if(process.env.CHROMIUM_PATH)launch.executablePath=process.env.CHROMIUM_PATH;
  const browser=await chromium.launch(launch);
  const page=await browser.newPage({viewport:{width:320,height:720}}),errors=[];
  const base=process.env.ALL2_UI_URL||'http://127.0.0.1:8765';
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',route=>route.request().url().startsWith(base+'/')?route.continue():route.abort());
  await page.goto(base+'/actor/65ab12345678901234567890');
  assert.equal(await page.getByText('Change Avatar').count(),0);
  assert.equal(await page.locator('#avatarUpdateInput').count(),0);
  assert.equal(await page.locator('.actor-bio-copy').textContent(),'Biography');
  await page.getByRole('button',{name:'Gallery',exact:false}).click();
  assert.equal(await page.locator('.actor-gallery-empty').isVisible(),true);
  assert.equal(await page.locator('.actor-gallery-choose input').getAttribute('multiple'),'');
  await page.getByRole('button',{name:'Linked Media',exact:false}).click();
  assert.equal(await page.locator('#tab-video').isVisible(),true);
  await page.getByRole('button',{name:'Info',exact:false}).click();
  for(const width of [320,1100]){
    await page.setViewportSize({width,height:720});
    for(const theme of ['dark','light']){
      await page.evaluate(theme=>document.body.classList.toggle('light',theme==='light'),theme);
      const dims=await page.evaluate(()=>({view:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth}));
      assert.ok(dims.scroll<=dims.view+1,JSON.stringify({width,theme,...dims}));
      assert.equal(await page.locator('.actor-identity h1').isVisible(),true);
    }
  }
  await page.setViewportSize({width:320,height:720});
  await page.evaluate(()=>document.body.classList.remove('light'));
  // File editor remains usable at mobile widths, including image selection and saving.
  let savedFile=null,uploadCount=0;
  await page.route('**/api/upload_thumb',route=>{uploadCount++;return route.fulfill({json:{success:true}})});
  await page.route('**/api/edit_name',route=>{savedFile=route.request().postDataJSON();return route.fulfill({json:{success:true}})});
  await page.evaluate(()=>editFile('fixture-file','primary',encodeURIComponent('Original name'),encodeURIComponent('Original tags')));
  const fileEditor=page.locator('#editCombinedModal');
  assert.equal(await fileEditor.getByRole('heading',{name:'Edit file'}).isVisible(),true);
  await fileEditor.getByLabel('File name').fill('Updated name');
  await fileEditor.getByLabel('Search tags (optional)').fill('fresh tags');
  await fileEditor.getByLabel('Collection').selectOption('cloud');
  await fileEditor.locator('#emFile').setInputFiles({name:'cover.gif',mimeType:'image/gif',buffer:Buffer.from('47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b','hex')});
  assert.equal(await fileEditor.locator('#emImageHelp').textContent(),'Selected: cover.gif');
  const modalDims=await fileEditor.locator('.file-editor').evaluate(e=>({width:e.clientWidth,scroll:e.scrollWidth}));
  assert.ok(modalDims.scroll<=modalDims.width+1,JSON.stringify(modalDims));
  await fileEditor.getByRole('button',{name:'Save Changes'}).click();
  await page.waitForFunction(()=>!document.querySelector('#editCombinedModal').classList.contains('open'));
  assert.equal(uploadCount,1);
  assert.deepEqual(savedFile,{file_id:'fixture-file',collection:'primary',new_name:'Updated name',add_caption:'fresh tags',target_collection:'cloud'});
  await page.evaluate(()=>editFile('fixture-file','primary',encodeURIComponent('Original name'),''));
  assert.ok((await fileEditor.locator('#emImageHelp').textContent()).includes('Optional'));
  await fileEditor.getByRole('button',{name:'Cancel'}).click();
  await page.getByRole('button',{name:'Edit Profile',exact:false}).click();
  const modal=page.locator('#actorEditModal');await modal.waitFor({state:'visible'});
  assert.equal(await modal.locator('.profile-file').count(),1);
  const old=await page.locator('#actorMasterAvatarImage').getAttribute('src');
  await modal.locator('.profile-file').setInputFiles({name:'photo.gif',mimeType:'image/gif',buffer:Buffer.from('47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b','hex')});
  await page.waitForFunction(old=>document.querySelector('#actorMasterAvatarImage').getAttribute('src')!==old,old);
  assert.equal(await modal.locator('[data-profile-links] .profile-link-row').count(),3);
  assert.equal(await modal.locator('[name=link_label]').first().inputValue(),'Instagram');
  assert.equal(await modal.locator('[name=link_url]').first().inputValue(),'https://instagram.com/legacy');
  await modal.locator('.profile-link-row').filter({has:page.locator('input[value="YouTube"]')}).locator('[data-link-remove]').click();
  for(let i=0;i<8;i++){
    await modal.locator('[data-link-add]').click();const row=modal.locator('.profile-link-row').last();
    await row.locator('[name=link_label]').fill(i===0?'Shop':'Other '+i);
    await row.locator('[name=link_url]').fill(i===0?'shop.example/a?x=1&y=2':`https://example.com/${i}`);
  }
  const last=modal.locator('.profile-link-row').last();await last.locator('[name=link_url]').fill('javascript:alert(1)');
  await modal.locator('button[type=submit]').click();await modal.locator('.profile-form-error').waitFor({state:'visible'});
  assert.ok((await modal.locator('.profile-form-error').textContent()).includes('valid http'));
  assert.equal(await modal.locator('.profile-link-row').count(),10);
  await last.locator('[name=link_url]').fill('https://example.com/7');
  let dims=await page.evaluate(()=>({view:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth}));
  assert.ok(dims.scroll<=dims.view+1,JSON.stringify(dims));
  await modal.locator('button[type=submit]').click();await page.waitForURL(/Profile\+updated/);
  assert.equal(await page.getByRole('link',{name:'Instagram',exact:true}).getAttribute('href'),'https://instagram.com/legacy');
  assert.equal(await page.getByRole('link',{name:'Shop',exact:true}).getAttribute('href'),'https://shop.example/a?x=1&y=2');
  assert.equal(await page.getByRole('link',{name:'website',exact:true}).getAttribute('href'),'https://legacy.example');
  assert.equal(await page.getByRole('link',{name:'YouTube',exact:true}).count(),0);
  await page.getByRole('button',{name:'Edit Profile',exact:false}).click();
  assert.equal(await page.locator('#actorEditModal .profile-link-row').count(),10);
  assert.equal(await page.locator('#actorEditModal [name=link_url]').last().inputValue(),'https://example.com/7');
  console.log('Profile edit: avatar inside editor, legacy links, add/remove, validation, save and mobile layout OK');

  await page.goto(base+'/admin/create_actor');
  await page.locator('[name=name]').fill('New Profile');await page.locator('[name=bio]').fill('A biography');
  await page.locator('#newProfilePhoto').setInputFiles({name:'photo.gif',mimeType:'image/gif',buffer:Buffer.from('47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b','hex')});
  for(let i=0;i<5;i++){
    await page.locator('[data-link-add]').click();const row=page.locator('.profile-link-row').last();
    await row.locator('[name=link_label]').fill('Link '+i);await row.locator('[name=link_url]').fill(`https://site.example/${i}`);
  }
  await page.locator('button[type=submit]').click();await page.waitForURL(/Profile\+created/);
  assert.ok((await page.locator('body').textContent()).includes('New Profile'));
  console.log('Profile creation: multiple universal URLs and image upload OK');
  assert.deepEqual(errors,[]);await browser.close();
})().catch(error=>{console.error(error);process.exit(1)});
