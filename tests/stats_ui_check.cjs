// Run against a fresh group_ui_fixture.py (mock MongoDB and Telegram).
const {chromium} = require('playwright-core');
const assert = require('node:assert/strict');
(async () => {
  const opts = {headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage']};
  if (process.env.CHROMIUM_PATH) opts.executablePath = process.env.CHROMIUM_PATH;
  const browser = await chromium.launch(opts), page = await browser.newPage();
  const base = process.env.ALL2_UI_URL || 'http://127.0.0.1:8765', errors = [];
  let storageFails = false, flushFails = true, flushCalls = 0, storageCalls = 0;
  page.on('pageerror', e => errors.push(e.message));
  let acceptScan = true; page.on('dialog', dialog => acceptScan ? dialog.accept() : dialog.dismiss());
  await page.route('**/*', r => {
    const url = r.request().url();
    if (url.startsWith(base + '/api/db_stats')) {
      storageCalls++;
      return storageFails ? r.fulfill({status: 503, json: {error: 'offline'}}) :
        r.fulfill({json: {used: '473 MB', total: '512 MB', percent: 92.5}});
    }
    if (url.startsWith(base + '/api/flush_cache')) {
      flushCalls++;
      assert.equal(r.request().method(), 'POST');
      return flushFails ? r.fulfill({status: 503, json: {error: 'offline'}}) :
        r.fulfill({json: {success: true}});
    }
    return url.startsWith(base + '/') ? r.continue() : r.abort();
  });
  try {
    for (const width of [320, 390, 768, 1200]) {
      await page.setViewportSize({width, height: 900});
      await page.goto(base + '/stats');
      assert.equal(await page.locator('h1').innerText(), 'Database overview');
      assert.equal((await page.locator('#saved-group-total').innerText()).trim(), '2');
      assert.equal((await page.locator('#saved-quality-count').innerText()).trim(), '1');
      assert.equal((await page.locator('#saved-series-count').innerText()).trim(), '1');
      await page.locator('#db-used-val').getByText('473 MB').waitFor();
      assert.equal(await page.locator('#db-pct-val').innerText(), '92.5%');
      assert.ok(await page.locator('#db-used-val').evaluate(e => e.classList.contains('storage-warning')));
      assert.equal(await page.locator('#db-prog-bar').evaluate(e => e.style.width), '92.5%');
      for (const selector of ['.overview-panel', '.collection-card', '#saved-group-stats', '.operation-card']) {
        for (const element of await page.locator(selector).all()) {
          const rect = await element.boundingBox();
          assert.ok(rect.x >= 0 && rect.x + rect.width <= width + 0.5, `${selector} overflows at ${width}`);
        }
      }
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await page.locator('.theme-btn').click();
      assert.equal((await page.locator('#saved-series-count').innerText()).trim(), '1');
    }
    // A failed request is explicit and retry can recover without reloading the page.
    storageFails = true;
    await page.reload();
    await page.locator('#db-used-val').getByText('Unavailable').waitFor();
    assert.equal(await page.locator('#db-pct-val').innerText(), '—');
    assert.equal(await page.locator('#db-prog-bar').evaluate(e => e.style.width), '0%');
    storageFails = false;
    await page.locator('#storage-retry').click();
    await page.locator('#db-used-val').getByText('473 MB').waitFor();
    assert.equal(await page.locator('#storage-retry').isVisible(), false);
    assert.ok(storageCalls >= 6);
    await page.locator('#flushBtn').click();
    await page.locator('#flush-status').getByText('Could not clear cache', {exact:false}).waitFor();
    assert.equal(await page.locator('#flushBtn').isEnabled(), true);
    flushFails = false;
    await page.locator('#flushBtn').click();
    await page.locator('#flush-status').getByText('Cache cleared successfully', {exact:false}).waitFor();
    assert.equal(flushCalls, 2);
    assert.equal(await page.locator('.stats-refresh').getAttribute('href'), '/stats');

    // The actual admin endpoint scans newly indexed files and updates saved groups.
    await page.request.post(base + '/fixture/seed_scan');
    let groups = await (await page.request.get(base + '/api/group/list?q=Rescan%20Test%20Film')).json();
    assert.equal(groups.groups.length, 0);
    await page.locator('#group-rescan').waitFor({state:'visible'});
    await page.waitForFunction(() => !document.getElementById('group-rescan').disabled);
    acceptScan = false; await page.locator('#group-rescan').click();
    groups = await (await page.request.get(base + '/api/group/list?q=Rescan%20Test%20Film')).json();
    assert.equal(groups.groups.length, 0);  // cancelling confirmation did nothing
    acceptScan = true; await page.locator('#group-rescan').click();
    await page.locator('#group-scan-status').getByText('Scan complete', {exact:false}).waitFor({timeout:12000});
    groups = await (await page.request.get(base + '/api/group/list?q=Rescan%20Test%20Film')).json();
    assert.equal(groups.groups.length, 1);assert.equal(groups.groups[0].count, 2);
    assert.equal(await page.locator('#group-rescan').isEnabled(), true);
    assert.ok((await page.locator('#group-scan-status').innerText()).includes('Refresh this page'));
    await page.reload();
    assert.equal((await page.locator('#saved-group-total').innerText()).trim(), '3');

    // A running startup scan is observed on page load, and its failure is shown.
    let scan = {running:true, phase:'<img src=x onerror=window.evil=1>', scanned:3, total:10};
    let starts = 0, startMode = 'already';
    await page.route('**/api/group/scan_status', r => scan === null ? r.fulfill({status:503,json:{error:'offline'}}) : r.fulfill({json:scan}));
    await page.route('**/api/group/scan_all', r => {
      starts++;
      if(startMode==='fail')return r.fulfill({status:503,json:{error:'Scan unavailable'}});
      scan={running:true,phase:'files',scanned:5,total:10};
      return r.fulfill({json:startMode==='already'?{started:false,running:true}:{started:true}});
    });
    await page.reload();
    await page.locator('#group-scan-status').getByText('Scan in progress', {exact:false}).waitFor();
    assert.equal(await page.locator('#group-rescan').isDisabled(), true);
    assert.equal(await page.locator('#group-scan-status img').count(),0);assert.equal(await page.evaluate(()=>window.evil||0),0);
    scan={running:false,error:'Database offline',finished:1};
    await page.locator('#group-scan-status').getByText('Database offline', {exact:false}).waitFor({timeout:6000});
    assert.equal(await page.locator('#group-rescan').isEnabled(),true);
    await page.locator('#group-rescan').click();
    await page.locator('#group-scan-status').getByText('Scan in progress', {exact:false}).waitFor();
    assert.equal(await page.locator('#group-rescan').isDisabled(),true);assert.equal(starts,1);
    scan={running:false,finished:1,created:2,added:3,skipped_big:1};
    await page.locator('#group-scan-status').getByText('2 groups created, 3 files added', {exact:false}).waitFor({timeout:6000});
    assert.ok((await page.locator('#group-scan-status').innerText()).includes('1 oversized groups skipped'));
    startMode='fail';await page.locator('#group-rescan').click();
    await page.locator('#group-scan-status').getByText('Scan unavailable', {exact:false}).waitFor();
    assert.equal(await page.locator('#group-rescan').isEnabled(),true);
    scan=null;await page.reload();
    await page.locator('#group-scan-status').getByText('Could not check scan status', {exact:false}).waitFor();
    assert.equal(await page.locator('#group-rescan').isEnabled(),true);
    scan={running:false};startMode='started';await page.locator('#group-rescan').click();
    await page.locator('#group-scan-status').getByText('Scan in progress', {exact:false}).waitFor();
    assert.equal(starts,3);
    assert.deepEqual(errors, []);
    console.log('Database overview: responsive layouts, themes, storage/cache, real rescan, running/error/retry states OK');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
