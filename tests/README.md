# Tests

The grouping, editor, cache-invalidation and streaming tests use an in-memory
MongoDB mock and test-only configuration. They check signed inline/range headers,
thumbnail revisions, partial failures, and preservation of post/profile data;
they do not connect to Telegram or require a running MongoDB server. The dependency
upgrade checks also exercise the real PyMongo async driver against a mock MongoDB
wire-protocol server. Premium callback tests cover duplicate clicks, simultaneous
approve/reject decisions, Telegram edit errors and retryable database failures; that is not a substitute for testing a live MongoDB deployment. Grouping
checks cover the two-distinct-file group threshold, runtime/episode matching,
legacy/manual groups, exclusions, live joins, full scans and pagination across
collections. Bot startup schedules the full scan in the background after database
indexes and the web server are ready; the admin Scan button shares its status and
cannot start another scan while it runs. Shutdown, interrupted-write repair and
subsequent restart scans are covered with mocked services. Removing, moving or deleting a member can dissolve its affected group
if fewer than two files remain; the surviving files are not deleted. Untouched
legacy singleton records are preserved for repair but displayed as individual
files, not groups. Actual media playback still depends on Telegram access and
browser-supported codecs. MongoDB text-index behavior still requires a real-service test.
Catalogue tests cover stable timestamp ties and page boundaries, filters, access,
invalid offsets and database failures. MP4 probe tests cover the shared header/tail fallback for both magic bytes and
filename hints, including error and short-tail cases.
Database overview browser tests cover responsive themes, storage errors and retries,
real cache-clear request handling, and the saved-groups manual rescan control.
The rescan test checks real scan-created groups, confirmation, progress, existing
scans, completion, failures and status retry with the in-memory fixture. Saved-group stats tests cover quality/series counts, legacy records, lifecycle
changes, admin access and database failures. Counts represent stored records,
including preserved legacy singletons, not the number of visible search cards.

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

## Bot spelling suggestions

PM and group searches use only the Primary, Cloud and Archive catalogue; no
Google request is made. When a search returns nothing, candidates are ranked
by approximate word similarity, then each displayed filename is checked with
the bot's normal search before its button is shown. Results can disappear if a
file is removed or access changes between showing and clicking a button.

Candidate searches are capped to 50 per collection per retrieval strategy,
12 verifications, 1.2 seconds server time per candidate query and 8 seconds
per lookup. Only two suggestion lookups run per process; extra requests receive
no suggestions. The fuzzy substring fallback may still scan file names, so
measure it on the production dataset. The bounds mean suggestions can be
incomplete, especially for very short queries, busy databases, large catalogues
or changes to the first few characters. Suggestions are deduplicated by exact
filename (case/whitespace-insensitive), not by movie or quality group.

The Python tests include mongomock regex fallback and a real PyMongo client
against a mock wire server. MongoDB's actual text tokenization/ranking and
Telegram button delivery still need testing against live services.

## Dependency compatibility

Production dependencies are pinned in `requirements.txt`; the MongoDB driver is
PyMongo Async, not Motor. PyMongo 4.19 requires MongoDB 4.4 or newer, so check the
server version before deployment. The container remains on Python 3.11 until a
newer Python image and its native dependencies can be validated. Plyr 3.8.5 is
maintenance-only; a future player replacement should be tested separately.

Payment decisions are recorded under each `Premiums` document, keyed by Telegram
receipt chat and message IDs. The decision and plan update share a single atomic
MongoDB write; the required unique `Premiums.id` index is verified before a decision.
If the index cannot be created (for example due to duplicate user records), the
approval fails closed and logs the error. Records approved before this mechanism
was deployed do not have a decision marker; check their plan before acting on an
old or stale receipt. Purchase-conversation locking is per running bot instance.

Payment QR images use qrcode with its PyPNG backend, not Pillow. Timezone handling
uses Python `zoneinfo`: the Docker image installs system tzdata, and the Python
requirements install `tzdata` on Windows. Other environments without a system
IANA timezone database must install the `tzdata` package separately. Auto-delete
deadlines and the rolling login window use elapsed UTC time across DST changes.

## Audit and web authentication notes

Audit regressions cover indexing authorization, inclusive message ranges and
fetch failures, timer cleanup, HTML escaping, ImgBB URL restrictions, OTP
races and send limits, and registration/password handling. They use mocks; live
Telegram and MongoDB behavior still needs integration testing.

New or changed web passwords use salted PBKDF2-SHA256 (600,000 iterations).
Legacy SHA-256 passwords continue to work and are upgraded after a successful
login. **Older application versions cannot authenticate these upgraded hashes**:
plan a rollback accordingly. CPU cost is intentional; hashing runs off the event
loop with a two-operation per-process concurrency limit. Load-test on the target
instance before deployment. Login and registration do not yet have a distributed
rate limiter; registration OTP state is process-local and pending plaintext
passwords remain in memory until consumed, replaced, cleaned by a subsequent
registration, or process restart. Avoid multi-instance registration until that
state is moved to shared, appropriately protected storage.

The Docker build excludes `.env` and `.env.*`, `.git`, virtual environments and
other local caches. Supply runtime secrets via the deployment environment, not
files copied into the image.

## Optional group-move browser test

The browser test exercises group-card keyboard/name opening, duration and ID chips,
both file/group moves and the group editor: exact ID lookup, preview confirmation,
stale requests, changed targets, empty-page navigation and a 320px layout. It
also checks that dashboard and actor thumbnails reveal admin editing controls,
file names play, group names open groups, and text-mode controls start hidden and
can be revealed by clicking the card or using the keyboard. It also checks
outside-click dismissal, nested-card hover and reduced-motion behavior, selection mode and non-admin behavior.
The file-editor test checks quality overrides, current membership, destination
preview and confirmation, changed destinations, and moves from dashboard and
actor cards. The ungrouped-view test covers the All, Group and UnGroup filter
choices, grouped and standalone files, group-name-only exclusion, playback, group IDs
appearing only on group cards, and the admin scan control in Group Mode. The
recent-view test covers raw collection order, older group members, standalone files and multi-page
forward/back navigation without changing group membership and verifies next-page
prefetch reuse. Shared-view checks cover the All labels, common text/poster
preference across dashboard, posts, profiles and miniapp, including another tab.
The catalog search check covers error handling, same-query retry and stale-response races.
The prefetch check verifies navigation retries when a speculative request fails.
The home search-panel check compares its shared style with posts/profiles and tests
mobile layout, desktop filters below the full-width search, matching shared filter styles,
keyboard use, themes, dropdowns and search
on 320px through desktop widths.
The branding check covers the original red F logo and its original font sizes
on the dashboard, sidebar, guest page, mini-app, landing and watch page at
mobile and desktop sizes, as well as navigation emoji and both themes.
It uses a **test-only, always-admin, in-memory** server; never deploy that server.
Install Node.js and Playwright separately, for example:

```sh
mkdir -p /tmp/all2-playwright
npm --prefix /tmp/all2-playwright install --no-save --no-package-lock playwright cropperjs@2.3.1 plyr@3.8.5
/tmp/all2-playwright/node_modules/.bin/playwright install chromium

# Terminal 1, from the repository root (restart for each test run):
.venv/bin/python tests/group_ui_fixture.py

# Terminal 2, from the repository root:
NODE_PATH=/tmp/all2-playwright/node_modules node tests/group_ui_check.cjs

# Restart the fixture before each of these additional tests:
NODE_PATH=/tmp/all2-playwright/node_modules node tests/file_editor_ui_check.cjs
NODE_PATH=/tmp/all2-playwright/node_modules node tests/cropper_ui_check.cjs
NODE_PATH=/tmp/all2-playwright/node_modules node tests/plyr_ui_check.cjs
NODE_PATH=/tmp/all2-playwright/node_modules node tests/ungrouped_view_ui_check.cjs
NODE_PATH=/tmp/all2-playwright/node_modules node tests/ungrouped_recent_ui_check.cjs
NODE_PATH=/tmp/all2-playwright/node_modules node tests/shared_view_ui_check.cjs
NODE_PATH=/tmp/all2-playwright/node_modules node tests/catalog_search_ui_check.cjs
NODE_PATH=/tmp/all2-playwright/node_modules node tests/prefetch_ui_check.cjs
NODE_PATH=/tmp/all2-playwright/node_modules node tests/search_panel_ui_check.cjs
NODE_PATH=/tmp/all2-playwright/node_modules node tests/brand_ui_check.cjs
NODE_PATH=/tmp/all2-playwright/node_modules node tests/group_stats_ui_check.cjs
NODE_PATH=/tmp/all2-playwright/node_modules node tests/stats_ui_check.cjs
```

The cropper check loads the installed Cropper.js locally, checks portrait, landscape
and square selections, bounds, exact JPEG output, both uploads and the CDN fallback.
The Plyr check loads the installed player locally and uses a browser-generated video
to test watch and mini-app controls; it does not test real Telegram streams.

The group and file editor browser checks also verify matching destination previews,
thumbnail fallbacks, absence of member lists, and move confirmation and stale-target safety.

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

Thumbnail regressions also exercise concurrent cover requests, lock cancellation,
revision isolation and serving a poster without waiting for a slow metadata probe.
The backfill queue is bounded and falls back to inline work under saturation.
Grouped search tests check that repeated batches reuse request-local query plans.
These tests use mocks; real MongoDB query timing and Telegram throughput/flood
limits must be measured in the deployment environment.

## Temporary library repair

`plugins/repair_library_TEMP.py` is an optional, admin-only one-off tool.
After deploying and restarting the bot, run `/repair_library` in Telegram. It
combines metadata migration and thumbnail warmup in a single scan of Primary,
Cloud and Archive. Existing `TG_ID:`, `NO_THUMB`, and web-custom posters are
preserved; metadata still gets migrated when needed. It reads Telegram media,
probes eligible video bytes, writes MongoDB, and may upload posters to the
configured thumbnail storage channel. Back up the database before running it.

Use the run's Cancel button to stop after the current operation. A restart,
cancellation or individual failure can leave pending work; rerun the command
and inspect its error/cleanup counts before considering the job finished. Broken
or inaccessible references are left unchanged so they can be retried. A group
cover revision failure is reported separately: the thumbnail may already be saved,
so refresh the affected group cover manually (the bot log records the file ID).
Some probes fall back to Telegram metadata if byte probing fails. Only one repair can
run **per bot instance**; don't run it simultaneously from multiple instances.

After checking the results, remove `plugins/repair_library_TEMP.py` and redeploy
or restart the bot. The admin help entry disappears on restart; indexing, search,
streaming and shared metadata/probe helpers remain installed. The regression
tests for the plugin skip if it has been removed. Live Telegram and MongoDB
behavior must still be verified separately.
