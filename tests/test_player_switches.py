"""In-player quality/episode switching: API membership and player wiring."""
import os
import unittest
from unittest.mock import AsyncMock, patch

for key, value in {
    "API_ID": "1", "API_HASH": "test", "BOT_TOKEN": "1:test", "ADMINS": "1",
    "LOG_CHANNEL": "-1001", "BIN_CHANNEL": "-1002",
    "DATABASE_URL": "mongodb://localhost:27017", "URL": "https://example.com",
}.items():
    os.environ.setdefault(key, value)

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from mongomock_motor import AsyncMongoMockClient
from database import ia_filterdb as db
from web import search_api as api
from web.player_assets import PLAYER_UI

MINI_APP = os.path.join(os.path.dirname(__file__), "..", "web", "miniapp.html")


class SwitchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mongo = AsyncMongoMockClient()
        store = self.mongo["switch_test"]
        self.cols = {name: store[name.capitalize()] for name in ("primary", "cloud", "archive")}
        self.groups = store.QualityGroups
        self.role = ("user", 7)
        patches = [
            patch.object(db, "primary", self.cols["primary"]),
            patch.object(db, "cloud", self.cols["cloud"]),
            patch.object(db, "archive", self.cols["archive"]),
            patch.object(db, "groups", self.groups),
            patch.object(api, "groups", self.groups),
            patch.object(api, "FILE_COLLECTIONS", self.cols),
            patch.object(api, "get_user_role", AsyncMock(side_effect=lambda _req: self.role)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        app = web.Application()
        app.add_routes(api.search_routes)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.mongo.close()

    async def add(self, collection, fid, name, height=None, **extra):
        doc = {"_id": fid, "file_ref": "ref-" + fid, "file_name": name, "file_type": "video",
               "file_size": 1000, "duration": 95, **extra}
        if height:
            doc["meta"] = {"w": int(height * 16 / 9), "h": height}
        await self.cols[collection].insert_one(doc)

    async def get(self, fid):
        response = await self.client.get("/api/file/switches", params={"file_id": fid})
        return response, await response.json()

    async def test_quality_versions_are_sorted_and_flagged(self):
        await self.add("primary", "q480", "Aurora Rising 480p.mkv", 480)
        await self.add("cloud", "q720", "Aurora Rising 720p.mkv", 720)
        await self.add("archive", "q1080", "Aurora Rising 1080p.mkv", 1080)
        await self.groups.insert_one({"_id": "11", "num": 11, "name": "Aurora Rising", "group_type": "quality",
                                      "members": ["q1080", "q480", "q720"]})
        response, data = await self.get("q720")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(data["group"]["id"], "11")
        self.assertEqual((data["group"]["type"], data["group"]["count"]), ("quality", 3))
        self.assertEqual([item["file_id"] for item in data["items"]], ["q480", "q720", "q1080"])
        self.assertEqual([item["label"] for item in data["items"]], ["480p", "720p", "1080p"])
        self.assertEqual([item["current"] for item in data["items"]], [False, True, False])
        self.assertTrue(data["items"][0]["duration"])

    async def test_series_uses_saved_episode_order_and_labels(self):
        for fid, episode in (("s1", "Episode 1"), ("s2", "S01E02"), ("s3", "Episode 3")):
            await self.add("primary", fid, f"The Long Way Home {episode}.mp4", 1080)
        await self.groups.insert_one({
            "_id": "12", "num": 12, "name": "The Long Way Home <b>", "group_type": "series",
            "members": ["s1", "s2", "s3"], "episode_order": ["s3", "s1", "s2"],
            "episode_labels": [{"id": "s1", "label": "S01E01"}, {"id": "s3", "label": "Finale"}]})
        _, data = await self.get("s1")
        self.assertEqual(data["group"]["type"], "series")
        self.assertEqual([item["file_id"] for item in data["items"]], ["s3", "s1", "s2"])
        self.assertEqual([item["label"] for item in data["items"]], ["Finale", "S01E01", "S01E02"])
        self.assertEqual(data["group"]["name"], "The Long Way Home <b>")

    async def test_quality_override_wins_over_resolution_label(self):
        await self.add("primary", "o1", "Movie.mkv", 480)
        await self.add("primary", "o2", "Movie.mkv", 480, quality_override="4K HDR")
        await self.groups.insert_one({"_id": "20", "name": "Movie", "group_type": "quality",
                                      "members": ["o1", "o2"]})
        _, data = await self.get("o1")
        labels = {item["file_id"]: item["label"] for item in data["items"]}
        self.assertEqual(labels["o2"], "4K HDR")

    async def test_stale_group_mark_cannot_expose_another_group(self):
        await self.add("primary", "mine", "Mine.mkv", 720, group_id="999")
        await self.add("primary", "other", "Other.mkv", 1080)
        await self.add("primary", "sibling", "Mine 480p.mkv", 480)
        await self.groups.insert_one({"_id": "30", "name": "Mine", "group_type": "quality",
                                      "members": ["mine", "sibling"]})
        # The stale mark points at a record that no longer owns this file.
        await self.groups.insert_one({"_id": "999", "name": "Other", "group_type": "quality",
                                      "members": ["other"]})
        _, data = await self.get("mine")
        self.assertEqual(data["group"]["id"], "30")
        self.assertEqual([item["file_id"] for item in data["items"]], ["sibling", "mine"])

    async def test_series_wins_if_legacy_data_has_two_containers(self):
        await self.add("primary", "both", "Show S01E01.mp4", 720)
        await self.add("primary", "ep2", "Show S01E02.mp4", 720)
        await self.add("primary", "quality-dup", "Show S01E01 1080p.mp4", 1080)
        await self.groups.insert_one({"_id": "60", "name": "Show", "group_type": "quality",
                                      "members": ["both", "quality-dup"]})
        await self.groups.insert_one({"_id": "61", "name": "Show", "group_type": "series",
                                      "members": ["both", "ep2"], "episode_order": ["both", "ep2"]})
        _, data = await self.get("both")
        self.assertEqual((data["group"]["id"], data["group"]["type"]), ("61", "series"))

    async def test_unowned_or_dissolved_groups_return_no_switcher(self):
        await self.add("primary", "alone", "Alone.mkv", 720)
        _, data = await self.get("alone")
        self.assertEqual(data, {"group": None, "items": []})
        await self.add("primary", "ghost", "Ghost.mkv", 720, group_id="40")
        await self.groups.insert_one({"_id": "40", "name": "Ghost", "group_type": "quality",
                                      "members": ["ghost", "deleted-file"]})
        _, data = await self.get("ghost")
        self.assertEqual(data, {"group": None, "items": []})

    async def test_huge_series_is_bounded_and_keeps_current_item(self):
        members = [f"e{index}" for index in range(api.SWITCH_ITEM_LIMIT + 3)]
        for index, fid in enumerate(members):
            await self.add("primary", fid, f"Daily Show Episode {index}.mp4", 720)
        await self.groups.insert_one({"_id": "50", "name": "Daily Show", "group_type": "series",
                                      "members": members})
        _, data = await self.get(members[-1])
        self.assertTrue(data["group"]["truncated"])
        self.assertEqual(len(data["items"]), api.SWITCH_ITEM_LIMIT)
        self.assertTrue(data["items"][-1]["current"])

    async def test_access_and_error_responses(self):
        self.role = (None, None)
        response, data = await self.get("anything")
        self.assertEqual((response.status, data["error"]), (403, "Unauthorized Web Access!"))
        self.role = ("user", 7)
        response = await self.client.get("/api/file/switches")
        self.assertEqual(response.status, 400)
        response, data = await self.get("unknown")
        self.assertEqual((response.status, data), (200, {"group": None, "items": []}))
        with patch.object(self.groups, "find", side_effect=RuntimeError("offline")), \
             self.assertLogs("web.search_api", level="WARNING"):
            response, data = await self.get("unknown")
        self.assertEqual(response.status, 503)
        self.assertIn("try again", data["error"])

    async def test_players_render_the_switcher_below_the_video(self):
        self.assertIn('id="inlinePlayerSwitcher"', PLAYER_UI)
        self.assertIn('/api/file/switches?file_id=', PLAYER_UI)
        self.assertIn("switchInlinePlayer", PLAYER_UI)
        self.assertIn("loadedmetadata", PLAYER_UI)
        video = PLAYER_UI.index('<video id="inlinePlayerVideo"')
        self.assertGreater(PLAYER_UI.index('id="inlinePlayerSwitcher"'), video)
        with open(MINI_APP, encoding="utf-8") as handle:
            mini = handle.read()
        self.assertIn('id="psSwitch"', mini)
        self.assertIn('/api/file/switches?file_id=', mini)
        self.assertIn("miniSwitchFile", mini)
        self.assertGreater(mini.index('id="psSwitch"'), mini.index('<div class="ppl"'))
        self.assertIn("openStream(f.file_id,f.name)", mini)


if __name__ == "__main__":
    unittest.main()
