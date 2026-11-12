"""Standalone mock dashboard for group_ui_check.cjs. Never deploy this fixture."""

import os
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

for key, value in {
    "API_ID": "1", "API_HASH": "test", "BOT_TOKEN": "1:test", "ADMINS": "1",
    "LOG_CHANNEL": "-1001", "BIN_CHANNEL": "-1002",
    "DATABASE_URL": "mongodb://localhost:27017", "URL": "https://example.com",
}.items():
    os.environ.setdefault(key, value)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiohttp import web
from mongomock_motor import AsyncMongoMockClient
from database import ia_filterdb as db
from web import search_api as api
from web.dashboard_routes import DASHBOARD_BODY
from web.actor_routes import ACTOR_MEDIA_SCRIPT
from web import actor_routes as actor, post_routes as post, stream_routes as stream, stats_routes as stats
from bson import ObjectId
from web.web_assets import build_page

mongo = AsyncMongoMockClient()
store = mongo["group_ui_fixture"]
cols = {name: store[name.capitalize()] for name in ("primary", "cloud", "archive")}
for name, col in cols.items():
    setattr(db, name, col)
db.COLLECTIONS = api.COLLECTIONS = {**cols, "actors": store.Actors}
db.groups = api.groups = store.QualityGroups
api.group_seq = store.QualityGroupSeq
api.group_search_cursors = store.GroupSearchCursors
api.FILE_COLLECTIONS = cols
actor.actors = store.Actors
post.posts_col = store.Posts


async def admin_role(_req):
    return "admin", 1


async def no_siblings(_key):
    return []


async def active(_role, _tg_id):
    return True


actor.get_auth = post.get_auth = stats.get_auth = admin_role
stats.db_count_documents = AsyncMock(return_value={})
stats.get_directory_counts = AsyncMock(return_value=(0, 0, 0, 0))
stats.get_post_category_counts = AsyncMock(return_value=(0, 0, 0, 0, 0))
stats.user_db = SimpleNamespace(
    total_users_count=AsyncMock(return_value=0),
    get_today_logged_in_users_count=AsyncMock(return_value=0),
    get_premium_users_count=AsyncMock(return_value=0),
    settings=SimpleNamespace(find_one=AsyncMock(return_value=None)),
)
actor.require_active_plan = post.require_active_plan = active
api.get_user_role = admin_role
api._siblings = no_siblings

# mongomock has no Mongo $text; use equivalent fixture-only regex searches.
def fixture_filter(raw, regex, lang=None):
    return ({'$or': [{'file_name': regex}, {'caption': regex}]}, False) if regex else (None, False)

async def fixture_groups(query):
    regex = re.compile(re.escape(query), re.I)
    return await store.QualityGroups.find({'$or': [{'name': regex}, {'files.name': regex}]}, db.GROUP_PROJECTION).to_list(length=600)

db.build_query_filter = fixture_filter
api.build_query_filter = fixture_filter
api.search_groups = fixture_groups


async def seed(_app):
    now = int(time.time())
    specs = [
        ("a1", "Aurora Rising 480p.mkv", "primary", "11"),
        ("a2", "Aurora Rising 720p.mkv", "cloud", "11"),
        ("a3", "Aurora Rising 1080p.mkv", "archive", "11"),
        ("s1", "The Long Way Home Episode 1.mp4", "primary", "12"),
        ("s2", "The Long Way Home Episode 2.mp4", "cloud", "12"),
        ("f1", "Coastal Stories 2024.mp4", "primary", None),
        ("f2", "Night Drive 2023.mp4", "cloud", None),
        ("f3", "Into the Blue.mp4", "archive", None),
    ]
    for index, (fid, name, source, gid) in enumerate(specs):
        doc = {"_id": fid, "file_ref": fid, "file_name": name, "file_type": "video",
               "file_size": 1000, "duration": 3, "meta": {"w": 1280, "h": 720},
               "caption": "Actor", "added_on": now - index, "thumb_revision": "initial"}
        if gid:
            doc["group_id"] = gid
        await cols[source].insert_one(doc)
    await store.QualityGroups.insert_many([
        {"_id": "11", "num": 11, "name": "Aurora Rising", "group_type": "quality",
         "members": ["a1", "a2", "a3"],
         "files": [{"id": fid, "name": name} for fid, name, _, _ in specs[:3]],
         "auto_keys": ["aurora rising"], "excluded": [], "scanned_at": now, "updated_at": now},
        {"_id": "12", "num": 12, "name": "The Long Way Home", "group_type": "series",
         "members": ["s1", "s2"], "files": [{"id": fid, "name": name} for fid, name, _, _ in specs[3:5]],
         "auto_keys": ["the long way home"], "excluded": [], "episode_order": ["s1", "s2"],
         "episode_labels": [{"id": "s1", "label": "S01E01"}, {"id": "s2", "label": "S01E02"}],
         "scanned_at": now, "updated_at": now},
    ])
    await store.QualityGroupSeq.insert_one({"_id": "seq", "n": 12})
    await store.Actors.insert_one({'_id': ObjectId('65ab12345678901234567890'), 'name':'Test Profile',
                                   'category':'actor', 'tags':[], 'gallery':[], 'created_at':1})
    await store.Posts.insert_one({'_id': ObjectId('65ab12345678901234567891'), 'title':'Test Post',
                                  'category':'Movies', 'created_at':1})


async def seed_automatic_examples(_req):
    # Test-only data added after the move/editor scenarios have finished.
    specs = [
        ("aq1", "Auto Movie 720p.mkv", 65), ("aq2", "Auto Movie 1080p.mkv", 65),
        ("aq3", "Auto Movie 480p.mkv", 65),
        ("as1", "Auto Mystery S01E01.mkv", 1200), ("as2", "Auto Mystery S01E02.mkv", 1800),
        ("as3", "Auto Mystery S01E03.mkv", 0), ("as4", "Auto Mystery S01E01 1080p.mkv", 1200),
        ("two1", "Duo Film 720p.mkv", 65), ("two2", "Duo Film 1080p.mkv", 65),
        ("no1", "Unknown Runtime 720p.mkv", 0), ("no2", "Unknown Runtime 1080p.mkv", 0),
        ("no3", "Unknown Runtime 480p.mkv", 0),
    ]
    now = int(time.time()) + 100
    for index, (fid, name, duration) in enumerate(specs):
        source = ("primary", "cloud", "archive")[index % 3]
        await cols[source].insert_one({"_id": fid, "file_ref": fid, "file_name": name, "file_type": "video",
                                       "file_size": 1000, "duration": duration, "added_on": now - index})
    # Simulate the admin scan; normal search now only reads saved groups.
    docs = await db.get_files_by_ids([fid for fid, _, _ in specs])
    await api._finalize(api._build_results_list(docs, 'none'), True, siblings=False)
    api._invalidate_search_caches()
    return web.json_response({"ok": True})


async def seed_scan_examples(_req):
    # Leave these compatible files ungrouped so the stats UI must actually run a scan.
    for fid, name, source in (("scan1", "Rescan Test Film 720p.mkv", "primary"),
                              ("scan2", "Rescan Test Film 1080p.mkv", "cloud")):
        await cols[source].insert_one({"_id": fid, "file_ref": fid, "file_name": name,
                                       "file_type": "video", "file_size": 1000, "duration": 3600})
    return web.json_response({"ok": True})


async def seed_mixed_recent(_req):
    # Large enough that a naive first raw page contains mostly standalone files,
    # even though grouped view can expand the recent anchor's older siblings.
    now = int(time.time()) + 10000
    members = [f'oldgroup{i:02}' for i in range(27)]
    for i, fid in enumerate(members):
        source = ('primary', 'cloud', 'archive')[i % 3]
        doc = {'_id': fid, 'file_ref': fid, 'file_name': f'Mixed Group Member {i:02}',
               'file_type': 'video', 'file_size': 1000, 'duration': 3,
               'added_on': now if i == 0 else 1}
        if i % 2:
            doc['group_id'] = '19'
        await cols[source].insert_one(doc)
    for i in range(12):
        await cols['primary'].insert_one({'_id': f'standalone{i:02}', 'file_ref': f'standalone{i:02}',
                                          'file_name': f'Standalone {i:02}', 'file_type': 'video',
                                          'file_size': 1000, 'duration': 3, 'added_on': now + i + 1})
    await store.QualityGroups.insert_one({'_id': '19', 'num': 19, 'name': 'Mixed Recent Group',
        'group_type': 'series', 'members': members,
        'files': [{'id': fid, 'name': f'Mixed Group Member {i:02}'} for i, fid in enumerate(members)],
        'auto_keys': [], 'excluded': [], 'scanned_at': now, 'updated_at': now})
    api._invalidate_search_caches()
    return web.json_response({'members': members, 'singles': [f'standalone{i:02}' for i in range(12)]})


async def dashboard(_req):
    return build_page("Mock Dashboard", DASHBOARD_BODY, "", "dash", "admin")


async def guest_page(_req):
    return build_page("Mock Guest", "", "login-bg")


async def watch_page(_req):
    from web.utils import render_template
    info = SimpleNamespace(mime_type='video/mp4', file_name='Example.mp4')
    with patch.object(render_template, 'get_media_info', AsyncMock(return_value=info)):
        return web.Response(text=await render_template.media_watch(123), content_type='text/html')


async def user_dashboard(_req):
    return build_page("Mock Dashboard", DASHBOARD_BODY, "", "dash", "user")


async def guest_role(_req):
    return None, None


stream.get_auth = guest_role


async def actor_cards(_req):
    # Exercise the actual shared actor-card renderer without a Telegram account.
    await cols['primary'].update_one({'_id': 'actor-file'}, {'$set': {'file_name': 'Actor file'}}, upsert=True)
    body = ACTOR_MEDIA_SCRIPT + '''<div id="fixture-actor" class="res-grid"></div>
    <script>
    var testActorFile={file_id:'actor-file',name:'Actor file',size:'1 MB',raw_collection:'primary',tg_thumb:'/api/thumb',gid:'11',group_num:11};
    function triggerActorSearchAjax(){}
    function showActorCard(mode,admin){var grid=document.getElementById('fixture-actor');grid.className='res-grid mode-'+mode;
        grid.innerHTML=renderActorMediaCard(testActorFile,mode,admin);staggerCards(grid);}
    showActorCard('tg',true);
    </script>'''
    return build_page("Mock Actor Cards", body, "", "actors", "admin")


async def thumb(_req):
    # Valid 1x1 GIF; avoid Telegram and external image requests.
    return web.Response(body=bytes.fromhex("47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"),
                        content_type="image/gif")


app = web.Application()
app.router.add_get("/dashboard", dashboard)
app.router.add_get("/fixture/user-dashboard", user_dashboard)
app.router.add_get("/fixture/guest", guest_page)
app.router.add_get("/fixture/watch", watch_page)
app.router.add_get("/fixture/landing", stream.root_route_handler)
app.router.add_get("/fixture/actor-cards", actor_cards)
app.router.add_post("/fixture/seed_auto", seed_automatic_examples)
app.router.add_post("/fixture/seed_scan", seed_scan_examples)
app.router.add_post("/fixture/seed_mixed_recent", seed_mixed_recent)
app.router.add_get("/api/thumb", thumb)
app.add_routes(api.search_routes)
app.add_routes(actor.actor_routes)
app.add_routes(post.post_routes)
app.add_routes(stats.stats_routes)
app.on_startup.append(seed)
web.run_app(app, host="0.0.0.0", port=int(os.environ.get("ALL2_UI_PORT", "8765")), print=None)
