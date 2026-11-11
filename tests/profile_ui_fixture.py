"""Test-only in-memory profile server for profile_ui_check.cjs; never deploy."""
import io
import os
import sys
from pathlib import Path
from types import SimpleNamespace

for key, value in {
    "API_ID": "1", "API_HASH": "test", "BOT_TOKEN": "1:test", "ADMINS": "1",
    "LOG_CHANNEL": "-1001", "BIN_CHANNEL": "-1002",
    "DATABASE_URL": "mongodb://localhost:27017", "URL": "https://example.com",
}.items():
    os.environ.setdefault(key, value)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiohttp import web
from bson import ObjectId
from mongomock_motor import AsyncMongoMockClient
from utils import temp
from web import actor_routes as actor

mongo = AsyncMongoMockClient()
actor.actors = mongo["profile_ui_fixture"].Actors


async def admin(_req):
    return "admin", 1


async def active(_role, _tg_id):
    return True


class FakeBot:
    async def send_photo(self, **_kwargs):
        return SimpleNamespace(photo=SimpleNamespace(file_id="test-photo"))

    async def download_media(self, *_args, **_kwargs):
        return io.BytesIO(bytes.fromhex("47494638396101000100800000000000ffffff21f90401000000002c00000000010001000002024401003b"))


actor.get_auth = admin
actor.require_active_plan = active
temp.BOT = FakeBot()


async def seed(_app):
    await actor.actors.insert_one({
        "_id": ObjectId("65ab12345678901234567890"), "name": "Legacy Profile", "bio": "Biography",
        "category": "actor", "tags": [], "gallery": [], "created_at": 1, "photo_url": "TG_ID:old",
        "social_links": {"instagram": "https://instagram.com/legacy", "youtube": "https://youtube.com/legacy",
                         "twitter": "", "website": "https://legacy.example"},
    })


app = web.Application()
app.add_routes(actor.actor_routes)
app.on_startup.append(seed)
web.run_app(app, host="0.0.0.0", port=int(os.environ.get("ALL2_UI_PORT", "8765")), print=None)
