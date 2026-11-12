# Tests

The grouping, editor, cache-invalidation and streaming tests use an in-memory
MongoDB mock and test-only configuration. They check signed inline/range headers,
thumbnail revisions, partial failures, and preservation of post/profile data;
they do not connect to Telegram or require a running MongoDB server. Grouping
checks cover the two-distinct-file group threshold, runtime/episode matching,
legacy/manual groups, exclusions, live joins, full scans and pagination across
collections. Removing, moving or deleting a member can dissolve its affected group
if fewer than two files remain; the surviving files are not deleted. Untouched
legacy singleton records are preserved for repair but displayed as individual
files, not groups. Actual media playback still depends on Telegram access and
browser-supported codecs. MongoDB text-index behavior still requires a real-service test.

For grouped `/api/search` requests, treat `next_offset` as an opaque continuation
value and send it back unchanged, including when a selective filter returns an
empty page. Large continuations are stored in `GroupSearchCursors` and expire after
two hours; the application's index setup creates a TTL index to clean them up.
Restart the search if a cursor expires. All searches saved GroupQuality records
first, followed by standalone files in Primary, Cloud, Archive order. Group reads
only saved group records. UnGroup searches individual files in Primary, Cloud,
Archive order, without group expansion; its offsets are numeric.

```sh
python -m venv .venv
.venv/bin/pip install -r requirements.txt -r tests/requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

## Optional group-move browser test

The browser test exercises group-card keyboard/name opening, duration and ID chips,
both file/group moves and the group editor: exact ID lookup, preview confirmation,
stale requests, changed targets, empty-page navigation and a 320px layout. It
also checks that dashboard and actor thumbnails reveal admin editing controls,
file names play, group names open groups, and text-mode controls start hidden and
can be revealed by clicking the card or using the keyboard. It also checks
outside-click dismissal, nested cards, selection mode and non-admin behavior.
The file-editor test checks quality overrides, current membership, destination
preview and confirmation, changed destinations, and moves from dashboard and
actor cards. The ungrouped-view test covers the All, Group and UnGroup filter
choices, grouped and standalone files, group-name-only exclusion, playback, group IDs
appearing only on group cards, and the admin scan control in Group Mode. The
recent-view test covers raw collection order, older group members, standalone files and multi-page
forward/back navigation without changing group membership and verifies next-page
prefetch reuse. Shared-view checks cover the All labels, common text/poster
preference across dashboard, posts, profiles and miniapp, including another tab.
The prefetch check verifies navigation retries when a speculative request fails.
The home search-panel check compares its shared style with posts/profiles and tests
responsive layout, themes, dropdowns and search on 320px through desktop widths.
The branding check covers the shared logo and navigation emoji across roles, themes,
the mini-app and landing page at mobile and desktop sizes.
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

# Restart the fixture before each of these additional tests:
NODE_PATH=/tmp/all2-playwright/node_modules node tests/file_editor_ui_check.cjs
NODE_PATH=/tmp/all2-playwright/node_modules node tests/ungrouped_view_ui_check.cjs
NODE_PATH=/tmp/all2-playwright/node_modules node tests/ungrouped_recent_ui_check.cjs
NODE_PATH=/tmp/all2-playwright/node_modules node tests/shared_view_ui_check.cjs
NODE_PATH=/tmp/all2-playwright/node_modules node tests/prefetch_ui_check.cjs
NODE_PATH=/tmp/all2-playwright/node_modules node tests/search_panel_ui_check.cjs
NODE_PATH=/tmp/all2-playwright/node_modules node tests/brand_ui_check.cjs
```

The fixture uses port 8765 by default. Set `ALL2_UI_PORT` on the fixture and
`ALL2_UI_URL` on the browser test to use a different port. `CHROMIUM_PATH` can
point to a compatible Chromium executable instead of Playwright's installed one.
The fixture and browser test do not use real Telegram or MongoDB services.

## Optional profile links browser test

With the same Playwright setup, run the separate test-only fixture and test:

```sh
# Terminal 1 (uses port 8765 by default):
.venv/bin/python tests/profile_ui_fixture.py

# Terminal 2:
NODE_PATH=/tmp/all2-playwright/node_modules node tests/profile_ui_check.cjs
```

It checks profile navigation and light/dark layouts, the mobile file editor's
thumbnail upload and metadata save, legacy and custom links, adding and removing
rows, validation, preserving links across saves, avatar upload inside the editor,
profile creation and the 320px layout. Both fixtures use mocked MongoDB and Telegram; stop one
before starting the other or set a different `ALL2_UI_PORT` and `ALL2_UI_URL`.
