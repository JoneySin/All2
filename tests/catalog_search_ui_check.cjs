// Run against the group UI fixture: search failure, retry and stale responses.
const {chromium} = require('playwright-core');
const assert = require('node:assert/strict');
(async () => {
  const options = {headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage']};
  if (process.env.CHROMIUM_PATH) options.executablePath = process.env.CHROMIUM_PATH;
  const browser = await chromium.launch(options);
  const page = await browser.newPage();
  const base = process.env.ALL2_UI_URL || 'http://127.0.0.1:8765';
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  try {
    for (const spec of [
      {page: '/actors', api: '/api/directory/search', input: 'dir_q', fn: 'searchDirectory', grid: '#dir_grid_container'},
      {page: '/posts', api: '/api/posts/search', input: 'post_q', fn: 'searchPosts', grid: '#post_grid_container'},
    ]) {
      await page.goto(base + spec.page);
      let failOnce = true, release;
      const held = new Promise(resolve => { release = resolve; });
      let started;
      const oldStarted = new Promise(resolve => { started = resolve; });
      const handler = async route => {
        const q = new URL(route.request().url()).searchParams.get('q');
        if (q === 'retry' && failOnce) {
          failOnce = false;
          return route.fulfill({status: 503, contentType: 'application/json', body: '{}'});
        }
        if (q === 'old') {
          started(); await held;
          return route.fulfill({status: 503, contentType: 'application/json', body: '{}'});
        }
        return route.fulfill({json: {html: `<div>${q} result</div>`, has_next: false}});
      };
      await page.route('**' + spec.api + '?*', handler);
      const search = q => page.evaluate(({input, fn, q}) => {
        document.getElementById(input).value = q;
        window[fn]();
      }, {...spec, q});
      await search('retry');
      await page.locator(spec.grid).getByText('Please retry', {exact: false}).waitFor();
      await search('retry');
      await page.locator(spec.grid).getByText('retry result').waitFor();
      await search('old'); await oldStarted;
      await search('new');
      await page.locator(spec.grid).getByText('new result').waitFor();
      release();
      await page.waitForTimeout(150);
      assert.match(await page.locator(spec.grid).innerText(), /new result/);
      await page.unroute('**' + spec.api + '?*', handler);
    }
    assert.deepEqual(errors, []);
    console.log('Catalog searches: HTTP failure, same-query retry and stale error protection OK');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
