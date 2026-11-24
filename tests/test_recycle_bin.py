"""Deleted media records must be recoverable, but hidden from every search path."""
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

from database import ia_filterdb as db_layer
from web import recycle_routes as recycle_web


class RecycleBinTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mongo = AsyncMongoMockClient()
        self.cols = {
            "primary": self.mongo.test.Primary,
            "cloud": self.mongo.test.Cloud,
            "archive": self.mongo.test.Archive,
        }
        self.recycle = self.mongo.test.RecycleBin
        self.groups = self.mongo.test.QualityGroups
        await self.recycle.create_index([("source_col", 1), ("file_id", 1)], unique=True)
        self.patches = [
            patch.object(db_layer, "COLLECTIONS", {**self.cols, "actors": self.mongo.test.Actors}),
            patch.object(db_layer, "FILE_COLLECTIONS", self.cols),
            patch.object(db_layer, "primary", self.cols["primary"]),
            patch.object(db_layer, "cloud", self.cols["cloud"]),
            patch.object(db_layer, "archive", self.cols["archive"]),
            patch.object(db_layer, "recycle_bin", self.recycle),
            patch.object(db_layer, "groups", self.groups),
            patch.object(db_layer, "_backup_before_delete", AsyncMock()),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    async def _file(self, collection="primary", fid="a", name="Film 1080p.mkv", **extra):
        doc = {"_id": fid, "file_name": name, "file_ref": f"ref-{fid}", "file_size": 1024}
        doc.update(extra)
        await self.cols[collection].insert_one(doc)
        return doc

    async def test_single_delete_moves_document_and_hides_it(self):
        await self._file(group_id="7")
        self.assertTrue(await db_layer.delete_single_file("a", "primary", deleted_by=42))
        self.assertIsNone(await self.cols["primary"].find_one({"_id": "a"}))
        self.assertIsNone(await db_layer.get_file_details("a"))
        total, docs = await db_layer.list_recycle_files()
        self.assertEqual(total, 1)
        self.assertEqual(docs[0]["deleted_by"], 42)
        stored = await self.recycle.find_one({})
        self.assertEqual(stored["original"]["file_ref"], "ref-a")

    async def test_restore_puts_file_back_and_rejoins_surviving_group(self):
        await self._file(group_id="7")
        await self.groups.insert_one({"_id": "7", "members": ["b"], "group_type": "quality"})
        await db_layer.delete_single_file("a", "primary", deleted_by=1)
        _, docs = await db_layer.list_recycle_files()
        result = await db_layer.restore_recycle_file(str(docs[0]["_id"]))
        self.assertTrue(result["ok"])
        restored = await self.cols["primary"].find_one({"_id": "a"})
        self.assertEqual(restored["file_name"], "Film 1080p.mkv")
        group = await self.groups.find_one({"_id": "7"})
        self.assertIn("a", group["members"])
        self.assertEqual(await self.recycle.count_documents({}), 0)

    async def test_restore_rebuilds_a_dissolved_two_member_group(self):
        await self._file(group_id="7")
        await self._file(fid="b", name="Film 1080p.mkv", group_id="7")
        await self.groups.insert_one({"_id": "7", "num": 7, "name": "Film",
                                      "members": ["a", "b"],
                                      "files": [{"id": "a", "name": "Film 720p.mkv"},
                                                {"id": "b", "name": "Film 1080p.mkv"}],
                                      "group_type": "quality"})
        await db_layer.delete_single_file("a", "primary", deleted_by=1)
        # Simulate the web delete path dissolving the now one-member group.
        await self.groups.delete_one({"_id": "7"})
        await self.cols["primary"].update_one({"_id": "b"}, {"$unset": {"group_id": ""}})
        _, docs = await db_layer.list_recycle_files()
        result = await db_layer.restore_recycle_file(str(docs[0]["_id"]))
        self.assertTrue(result["ok"])
        group = await self.groups.find_one({"_id": "7"})
        self.assertIsNotNone(group)
        self.assertEqual(set(group["members"]), {"a", "b"})
        survivor = await self.cols["primary"].find_one({"_id": "b"})
        self.assertEqual(survivor["group_id"], "7")

    async def test_restore_does_not_duplicate_a_live_copy(self):
        await self._file("primary")
        await self._file("cloud")
        await db_layer.delete_single_file("a", "primary", deleted_by=1)
        _, docs = await db_layer.list_recycle_files()
        result = await db_layer.restore_recycle_file(str(docs[0]["_id"]))
        self.assertTrue(result["ok"])
        self.assertTrue(result["already"])
        self.assertEqual(await self.cols["primary"].count_documents({}), 0)
        self.assertEqual(await self.cols["cloud"].count_documents({"_id": "a"}), 1)
        self.assertEqual(await self.recycle.count_documents({}), 0)

    async def test_bulk_delete_and_permanent_purge(self):
        await self._file(name="Alpha One")
        await self._file(fid="b", name="Alpha Two")
        self.assertEqual(await db_layer.delete_files("Alpha", "primary", deleted_by=7), 2)
        self.assertEqual(await self.cols["primary"].count_documents({}), 0)
        total, docs = await db_layer.list_recycle_files("Alpha")
        self.assertEqual(total, 2)
        self.assertTrue(await db_layer.purge_recycle_file(str(docs[0]["_id"])))
        self.assertEqual(await db_layer.recycle_file_count(), 1)

    async def test_restore_rejects_invalid_or_missing_records(self):
        self.assertFalse((await db_layer.restore_recycle_file("not-an-id"))["ok"])
        self.assertFalse((await db_layer.restore_recycle_file("64b000000000000000000000"))["ok"])

    async def test_server_side_stream_lookup_returns_original_file_ref(self):
        await self._file()
        await db_layer.delete_single_file("a", "primary", deleted_by=1)
        _, docs = await db_layer.list_recycle_files()
        original = await db_layer.get_recycle_original(str(docs[0]["_id"]))
        self.assertEqual(original["file_ref"], "ref-a")
        self.assertIsNone(await db_layer.get_recycle_original("not-an-id"))
        self.assertIsNone(await db_layer.get_recycle_original("64b000000000000000000000"))

    async def test_recycle_list_is_searchable_and_paginated(self):
        await self._file(name="Bravo")
        await self._file(fid="b", name="Charlie")
        await self._file("cloud", fid="c", name="Cloud Only")
        await db_layer.delete_single_file("a", "primary")
        await db_layer.delete_single_file("b", "primary")
        await db_layer.delete_single_file("c", "cloud")
        total, docs = await db_layer.list_recycle_files("brav")
        self.assertEqual(total, 1)
        self.assertEqual(docs[0]["file_name"], "Bravo")
        total, docs = await db_layer.list_recycle_files("", offset=0, limit=1)
        self.assertEqual(total, 3)
        self.assertEqual(len(docs), 1)
        total, docs = await db_layer.list_recycle_files("", collection="cloud")
        self.assertEqual(total, 1)
        self.assertEqual(docs[0]["file_name"], "Cloud Only")
        total, _ = await db_layer.list_recycle_files("", collection="all")
        self.assertEqual(total, 3)


class RecyclePageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        app = web.Application()
        app.add_routes(recycle_web.recycle_routes)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.addCleanup(self.client.close)

    def test_admin_nav_has_recycle_link_and_users_do_not(self):
        from web.web_assets import build_page
        admin = build_page("Home", "", role="admin").text
        user = build_page("Home", "", role="user").text
        self.assertIn('href="/admin/recycle"', admin)
        self.assertIn("Recycle Bin", admin)
        self.assertNotIn('href="/admin/recycle"', user)

    async def test_page_and_api_are_admin_only(self):
        with patch.object(recycle_web, "get_auth", AsyncMock(return_value=("user", 5))):
            page = await self.client.get("/admin/recycle", allow_redirects=False)
            self.assertEqual(page.status, 302)
            self.assertTrue(page.headers["Location"].endswith("/dashboard"))
            denied = await self.client.get("/api/recycle/list")
            self.assertEqual(denied.status, 403)
            self.assertIn("Admin", (await denied.json())["error"])

    def test_page_has_auto_search_and_both_filters(self):
        body = recycle_web._page_body()
        self.assertIn('id="rbSearch"', body)
        self.assertNotIn('id="rbSearchBtn"', body)
        self.assertNotIn('id="rbClear"', body)
        self.assertIn('data-filter="col"', body)
        self.assertIn('data-filter="mode"', body)
        self.assertIn('id="rbColMenu"', body)
        self.assertIn('id="rbModeMenu"', body)
        self.assertIn('rb-grid mode-poster', body)
        self.assertIn('data-play', body)
        self.assertIn('data-action="restore"', body)

    async def test_admin_page_renders_filters_and_inline_player(self):
        with patch.object(recycle_web, "get_auth", AsyncMock(return_value=("admin", 1))):
            response = await self.client.get("/admin/recycle")
        self.assertEqual(response.status, 200)
        page = await response.text()
        self.assertIn('id="rbSearch"', page)
        self.assertIn('id="rbColMenu"', page)
        self.assertIn('id="rbModeMenu"', page)
        self.assertIn('id="inlinePlayer"', page)
        self.assertNotIn('id="rbSearchBtn"', page)

    async def test_stream_requires_admin_and_uses_server_side_file_ref(self):
        with patch.object(recycle_web, "get_auth", AsyncMock(return_value=("user", 5))):
            denied = await self.client.post("/api/recycle/stream", json={"id": "a"})
            self.assertEqual(denied.status, 403)
        with patch.object(recycle_web, "get_auth", AsyncMock(return_value=("admin", 1))), \
                patch.object(recycle_web, "get_recycle_original",
                             AsyncMock(return_value={"file_ref": "ref-a", "file_name": "Film.mkv"})), \
                patch("web.search_api._tunnel_stream",
                      AsyncMock(return_value="/download/9?sig&inline=1")):
            response = await self.client.post("/api/recycle/stream",
                                              json={"id": "64b000000000000000000001"})
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["url"], "/download/9?sig&inline=1")

    async def test_stream_rejects_record_without_telegram_reference(self):
        with patch.object(recycle_web, "get_auth", AsyncMock(return_value=("admin", 1))), \
                patch.object(recycle_web, "get_recycle_original",
                             AsyncMock(return_value={"file_name": "Only metadata"})):
            response = await self.client.post("/api/recycle/stream",
                                              json={"id": "64b000000000000000000001"})
        self.assertEqual(response.status, 400)
        self.assertIn("media reference", (await response.json())["error"])

    async def test_admin_list_returns_only_safe_metadata(self):
        doc = {
            "_id": "64b000000000000000000001", "source_col": "primary",
            "file_id": "a", "file_name": "Film.mkv", "deleted_at": 1700000000,
            "deleted_by": 42,
            "original": {"file_name": "Film.mkv", "file_size": 2048,
                         "thumb_url": "https://example.com/t.jpg", "group_id": "7",
                         "file_ref": "tg-ref"},
        }
        with patch.object(recycle_web, "get_auth", AsyncMock(return_value=("admin", 1))), \
                patch.object(recycle_web, "list_recycle_files",
                             AsyncMock(return_value=(1, [doc]))):
            response = await self.client.get("/api/recycle/list")
        self.assertEqual(response.status, 200)
        data = await response.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["file_name"], "Film.mkv")
        self.assertEqual(data["items"][0]["group_id"], "7")
        self.assertIn("2.00 KB", data["items"][0]["file_size"])
        self.assertTrue(data["items"][0]["playable"])
        self.assertNotIn("original", data["items"][0])
        self.assertNotIn("file_ref", data["items"][0])


if __name__ == "__main__":
    unittest.main()
