"""Standalone mock dashboard for group_ui_check.cjs. Never deploy this fixture."""

import os
import sys
import time
from pathlib import Path

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


async def admin_role(_req):
    return "admin", 1


async def no_siblings(_key):
    return []


api.get_user_role = admin_role
api._siblings = no_siblings


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


async def seed_automatic_examples(_req):
    # Test-only data added after the move/editor scenarios have finished.
    specs = [
        ("aq1", "Auto Movie 720p.mkv", 65), ("aq2", "Auto Movie 1080p.mkv", 65),
        ("aq3", "Auto Movie 480p.mkv", 65),
        ("as1", "Auto Mystery S01E01.mkv", 1200), ("as2", "Auto Mystery S01E02.mkv", 1800),
        ("as3", "Auto Mystery S01E03.mkv", 0),
        ("two1", "Duo Film 720p.mkv", 65), ("two2", "Duo Film 1080p.mkv", 65),
        ("no1", "Unknown Runtime 720p.mkv", 0), ("no2", "Unknown Runtime 1080p.mkv", 0),
        ("no3", "Unknown Runtime 480p.mkv", 0),
    ]
    now = int(time.time()) + 100
    for index, (fid, name, duration) in enumerate(specs):
        source = ("primary", "cloud", "archive")[index % 3]
        await cols[source].insert_one({"_id": fid, "file_ref": fid, "file_name": name, "file_type": "video",
                                       "file_size": 1000, "duration": duration, "added_on": now - index})
    api._invalidate_search_caches()
    return web.json_response({"ok": True})


async def dashboard(_req):
    return build_page("Mock Dashboard", DASHBOARD_BODY, "", "dash", "admin")


async def thumb(_req):
    # Valid 1x1 GIF; avoid Telegram and external image requests.
    return web.Response(body=bytes.fromhex("47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"),
                        content_type="image/gif")


app = web.Application()
app.router.add_get("/dashboard", dashboard)
app.router.add_post("/fixture/seed_auto", seed_automatic_examples)
app.router.add_get("/api/thumb", thumb)
app.add_routes(api.search_routes)
app.on_startup.append(seed)
web.run_app(app, host="0.0.0.0", port=int(os.environ.get("ALL2_UI_PORT", "8765")), print=None)
