# Tests

The grouping, editor, cache-invalidation and streaming tests use an in-memory
MongoDB mock and test-only configuration. They check signed inline/range headers,
thumbnail revisions, partial failures, and preservation of post/profile data;
they do not connect to Telegram or require a running MongoDB server. Actual media
playback still depends on Telegram access and browser-supported codecs.

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt -r tests/requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

## Optional group-move browser test

The browser test exercises both file/group moves and the group editor: exact ID
lookup, preview confirmation, stale requests, changed targets and a 320px layout.
It uses a **test-only, always-admin, in-memory** server; never deploy that server.
Install Node.js and Playwright separately, for example:

```sh
mkdir -p /tmp/all2-playwright
npm --prefix /tmp/all2-playwright install --no-save --no-package-lock playwright
/tmp/all2-playwright/node_modules/.bin/playwright install chromium

# Terminal 1, from the repository root (restart for each test run):
.venv/bin/python tests/group_ui_fixture.py

# Terminal 2, from the repository root:
NODE_PATH=/tmp/all2-playwright/node_modules node tests/group_ui_check.cjs
```

The fixture uses port 8765 by default. Set `ALL2_UI_PORT` on the fixture and
`ALL2_UI_URL` on the browser test to use a different port. `CHROMIUM_PATH` can
point to a compatible Chromium executable instead of Playwright's installed one.
The fixture and browser test do not use real Telegram or MongoDB services.
