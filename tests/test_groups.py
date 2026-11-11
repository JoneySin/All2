"""Grouping regression tests. No Telegram account or live MongoDB is required."""

import asyncio
import copy
import os
import unittest
from unittest.mock import AsyncMock, patch

# info.py validates configuration at import time; these are test-only values.
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
from web.grouping import episode_number, order_series


def doc(fid, name, source="primary", **extra):
    return {"_id": fid, "file_ref": fid, "file_name": name, "file_size": 1000,
            "file_type": "video", "source_col": source, **extra}


class GroupingUnitTests(unittest.TestCase):
    def test_quality_key_handles_dimensions_but_keeps_episode_identity(self):
        self.assertEqual(api._group_key("Film 720p.mkv"), api._group_key("Film 1920x1080.mp4"))
        self.assertNotEqual(api._group_key("Show S01E01 720p.mkv"),
                            api._group_key("Show S01E02 720p.mkv"))
        self.assertIn("2024", api._group_key("Film 2024 1080p.mkv"))

    def test_episode_parsing_and_order_are_conservative(self):
        self.assertEqual(episode_number("Show S02E03 720p"), (2, 3, "S02E03"))
        self.assertEqual(episode_number("Show Season 1 Episode 4"), (1, 4, "S01E04"))
        self.assertEqual(episode_number("Show 1x12"), (1, 12, "S01E12"))
        self.assertIsNone(episode_number("Show 1920x1080 2024"))
        variants = [{"file_id": "b", "name": "Show Episode 10"},
                    {"file_id": "a", "name": "Show Episode 2"},
                    {"file_id": "c", "name": "Show"}]
        ordered = order_series(variants, {"members": ["b", "c", "a"]})
        self.assertEqual([v["file_id"] for v in ordered], ["a", "b", "c"])
        self.assertEqual([v["episode_label"] for v in ordered], ["E02", "E10", ""])
        ordered = order_series(variants, {"members": ["b", "c", "a"],
                                          "episode_order": ["c", "b"],
                                          "episode_labels": [{"id": "c", "label": "Episode 1"}]})
        self.assertEqual([v["file_id"] for v in ordered], ["c", "b", "a"])
        self.assertEqual(ordered[0]["episode_label"], "Episode 1")

    def test_group_cards_default_legacy_to_quality_and_are_immutable(self):
        originals = api._build_results_list([doc("a", "Movie 720p.mkv"),
                                             doc("b", "Movie 1080p.mkv")], "tg")
        snapshot = copy.deepcopy(originals)
        group = {"_id": "17", "num": 17, "name": "Movie", "members": ["a", "b"]}
        result = api.group_results(originals, {"a": group, "b": group})[0]
        self.assertEqual(result["group_type"], "quality")
        self.assertEqual(result["num"], 17)
        self.assertEqual([x["label"] for x in result["chips"]], ["720p", "1080p"])
        self.assertTrue(all(x["gid"] == "17" and x["group_num"] == 17 for x in result["variants"]))
        self.assertEqual(originals, snapshot)
        self.assertIn("group_type", db.GROUP_PROJECTION)

    def test_same_file_in_two_collections_is_not_two_quality_versions(self):
        rows = api._build_results_list([doc("same", "Film 720p.mkv"),
                                         doc("same", "Film 720p.mkv", "cloud")], "none")
        cards = api.group_results(rows)
        self.assertEqual(len(cards), 1)
        self.assertFalse(cards[0].get("group"))

    def test_saved_one_member_group_is_still_editable(self):
        item = api._build_results_list([doc("a", "Episode 1")], "none")
        group = {"_id": "4", "num": 4, "name": "Series", "members": ["a"], "group_type": "series"}
        card = api.group_results(item, {"a": group})[0]
        self.assertTrue(card["group"])
        self.assertEqual((card["num"], card["group_type"], card["count"]), (4, "series", 1))


class GroupingIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mongo = AsyncMongoMockClient()
        self.db = self.mongo["group_test"]
        self.cols = {name: self.db[name.capitalize()] for name in ("primary", "cloud", "archive")}
        self.groups = self.db.QualityGroups
        self.seq = self.db.QualityGroupSeq
        patches = [
            patch.object(api, "groups", self.groups), patch.object(api, "group_seq", self.seq),
            patch.object(api, "FILE_COLLECTIONS", self.cols),
            patch.object(api, "COLLECTIONS", {**self.cols, "actors": self.db.Actors}),
            patch.object(api, "get_user_role", AsyncMock(return_value=("admin", 1))),
            patch.object(api, "_AUTO_GROUP_LOCK", asyncio.Lock()),
            patch.object(db, "primary", self.cols["primary"]),
            patch.object(db, "cloud", self.cols["cloud"]), patch.object(db, "archive", self.cols["archive"]),
            patch.object(db, "groups", self.groups),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        api._GH_CACHE.clear()
        api._SIB_CACHE.clear()
        api.PREFETCH_CACHE.clear()
        api.TRENDING_CACHE.clear()
        app = web.Application()
        app.add_routes(api.search_routes)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.mongo.close()

    async def insert_files(self, *docs):
        for d in docs:
            d = dict(d)
            source = d.pop("source_col", "primary")
            await self.cols[source].insert_one(d)

    async def post(self, path, body):
        response = await self.client.post(path, json=body)
        return response.status, await response.json()

    async def test_auto_group_has_real_id_on_first_response_and_does_not_duplicate(self):
        docs = [doc("a", "Film 720p.mkv"), doc("b", "Film 1080p.mkv", "cloud")]
        await self.insert_files(*docs)
        rows = api._build_results_list(docs, "tg")
        first, second = await asyncio.gather(api._finalize(rows, True, siblings=False),
                                             api._finalize(rows, True, siblings=False))
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["num"], 1)
        self.assertEqual(first[0]["gid"], "1")
        self.assertEqual(second[0]["gid"], "1")
        self.assertTrue(all(v["group_num"] == 1 for v in first[0]["variants"]))
        self.assertEqual(await self.groups.count_documents({}), 1)
        self.assertEqual((await self.cols["primary"].find_one({"_id": "a"}))["group_id"], "1")
        self.assertEqual((await self.cols["cloud"].find_one({"_id": "b"}))["group_id"], "1")

    async def test_auto_group_and_admin_move_are_serialized(self):
        docs = [doc("a", "Film 720p.mkv"), doc("b", "Film 1080p.mkv", "cloud")]
        await self.insert_files(*docs)
        entered, release = asyncio.Event(), asyncio.Event()
        real_lookup = api._live_group_files

        async def paused_lookup(ids):
            entered.set()
            await release.wait()
            return await real_lookup(ids)

        with patch.object(api, "_live_group_files", paused_lookup):
            auto = asyncio.create_task(api._finalize(api._build_results_list(docs, "none"), True, siblings=False))
            await asyncio.wait_for(entered.wait(), 2)
            admin = asyncio.create_task(self.post("/api/group/save", {
                "name": "Hand-picked", "items": [{"id": "a"}, {"id": "b"}], "group_type": "series"}))
            try:
                await asyncio.sleep(0.02)
                self.assertFalse(admin.done())
            finally:
                release.set()
            await asyncio.wait_for(auto, 2)
            status, saved = await asyncio.wait_for(admin, 2)
        self.assertEqual(status, 200, saved)
        self.assertEqual(await self.groups.count_documents({}), 1)
        group = await self.groups.find_one({"_id": saved["group_id"]})
        self.assertEqual(group["group_type"], "series")
        self.assertEqual(set(group["members"]), {"a", "b"})
        self.assertEqual((await self.cols["primary"].find_one({"_id": "a"}))["group_id"], group["_id"])
        self.assertEqual((await self.cols["cloud"].find_one({"_id": "b"}))["group_id"], group["_id"])

    async def test_auto_group_respects_exclusion_in_any_collection(self):
        await self.insert_files(doc("a", "Film 720p.mkv"),
                                doc("a", "Film 720p.mkv", "cloud", group_auto_excluded=True),
                                doc("b", "Film 1080p.mkv"))
        # The page may contain the other, stale copy without its exclusion flag.
        cards = await api._finalize(api._build_results_list([
            doc("a", "Film 720p.mkv"), doc("b", "Film 1080p.mkv")], "none"), True, siblings=False)
        self.assertTrue(all(not c.get("group") for c in cards))
        self.assertEqual(await self.groups.count_documents({}), 0)
        await api._scan_all_groups()
        self.assertEqual(api.SCAN_STATE.get("error"), "")
        self.assertEqual(await self.groups.count_documents({}), 0)

    async def test_failed_live_recheck_never_invents_a_group_number(self):
        rows = api._build_results_list([doc("a", "Film 720p.mkv"), doc("b", "Film 1080p.mkv")], "none")
        with patch.object(api, "_live_group_files", AsyncMock(side_effect=RuntimeError("database offline"))):
            cards = await api._finalize(rows, True, siblings=False)
        self.assertTrue(cards[0]["group"])
        self.assertEqual(cards[0]["gid"], "")
        self.assertEqual(await self.groups.count_documents({}), 0)

    async def test_series_create_edit_order_labels_and_auto_join(self):
        docs = [doc("a", "Same Name.mkv"), doc("b", "Same Name.mkv", "cloud")]
        await self.insert_files(*docs)
        status, result = await self.post("/api/group/save", {
            "name": "My Series", "group_type": "series",
            "items": [{"id": "a"}, {"id": "b"}],
            "episode_order": ["b", "a"],
            "episode_labels": [{"id": "b", "label": "Episode 1"}, {"id": "a", "label": "Episode 2"}],
        })
        self.assertEqual(status, 200, result)
        gid = result["group_id"]
        group = await self.groups.find_one({"_id": gid})
        card = (await api._group_cards([group], "none"))[0]
        self.assertEqual(card["group_type"], "series")
        self.assertEqual([v["file_id"] for v in card["variants"]], ["b", "a"])
        self.assertEqual([v["episode_label"] for v in card["variants"]], ["Episode 1", "Episode 2"])
        self.assertEqual(card["chips"], [])

        # Adding a same-name episode respects the type and appends after the admin order.
        new_doc = doc("c", "Same Name.mkv", "archive")
        await self.insert_files(new_doc)
        card = (await api._finalize(api._build_results_list([new_doc], "none"), True, siblings=False))[0]
        self.assertEqual(card["group_type"], "series")
        self.assertEqual([v["file_id"] for v in card["variants"]], ["b", "a", "c"])
        self.assertEqual((await self.cols["archive"].find_one({"_id": "c"}))["group_id"], gid)

        status, result = await self.post("/api/group/update", {"group_id": gid, "group_type": "quality"})
        self.assertEqual(status, 200, result)
        quality_group = await self.groups.find_one({"_id": gid})
        self.assertEqual(quality_group["group_type"], "quality")
        quality_card = (await api._group_cards([quality_group], "none"))[0]
        self.assertEqual({v["file_id"]: v["episode_custom_label"] for v in quality_card["variants"]},
                         {"a": "Episode 2", "b": "Episode 1", "c": ""})
        self.assertEqual({v["file_id"]: v["episode_position"] for v in quality_card["variants"]},
                         {"b": 1, "a": 2, "c": 3})
        status, result = await self.post("/api/group/update", {"group_id": gid, "group_type": "series",
                                                               "episode_order": ["c", "a", "b"],
                                                               "episode_labels": [{"id": "c", "label": "Finale"}]})
        self.assertEqual(status, 200, result)
        card = (await api._group_cards([await self.groups.find_one({"_id": gid})], "none"))[0]
        self.assertEqual([v["file_id"] for v in card["variants"]], ["c", "a", "b"])
        self.assertEqual(card["variants"][0]["episode_label"], "Finale")

    async def test_invalid_operations_do_not_move_or_unmark_files(self):
        await self.insert_files(doc("a", "Film 720p.mkv", group_id="7"), doc("b", "Film 1080p.mkv", group_id="7"))
        await self.groups.insert_one({"_id": "7", "num": 7, "name": "Original", "members": ["a", "b"],
                                      "files": [{"id": "a", "name": "Film 720p.mkv"}, {"id": "b", "name": "Film 1080p.mkv"}],
                                      "auto_keys": ["film"], "excluded": []})
        for body, expected in [({"group_id": "999", "items": [{"id": "a"}]}, 404),
                               ({"name": "", "items": [{"id": "a"}]}, 400),
                               ({"name": "Bad", "group_type": "bad", "items": [{"id": "a"}]}, 400),
                               ({"name": "Bad", "items": [{"id": "missing"}]}, 400)]:
            status, _ = await self.post("/api/group/save", body)
            self.assertEqual(status, expected)
            self.assertEqual((await self.groups.find_one({"_id": "7"}))["members"], ["a", "b"])
            self.assertEqual((await self.cols["primary"].find_one({"_id": "a"}))["group_id"], "7")
        status, _ = await self.post("/api/group/remove_file", {"group_id": "999", "file_id": "a"})
        self.assertEqual(status, 404)
        self.assertEqual((await self.cols["primary"].find_one({"_id": "a"}))["group_id"], "7")
        status, _ = await self.post("/api/group/update", {"group_id": "7", "group_type": "series",
                                                          "episode_order": ["a", "other"]})
        self.assertEqual(status, 400)
        self.assertNotIn("group_type", await self.groups.find_one({"_id": "7"}))

    async def test_ungroup_and_remove_stay_excluded_but_manual_regroup_works(self):
        docs = [doc("a", "Film 720p.mkv"), doc("b", "Film 1080p.mkv")]
        await self.insert_files(*docs)
        _, made = await self.post("/api/group/save", {"name": "Film", "items": [{"id": "a"}, {"id": "b"}]})
        status, result = await self.post("/api/group/delete", {"group_id": made["group_id"]})
        self.assertEqual(status, 200, result)
        stored = [await self.cols["primary"].find_one({"_id": x}) for x in ("a", "b")]
        self.assertTrue(all(d.get("group_auto_excluded") and "group_id" not in d for d in stored))
        rows = api._build_results_list(stored, "none")
        self.assertTrue(all(not x.get("group") for x in await api._finalize(rows, True, siblings=False)))
        # A search that read the files before ungrouping must not recreate the group.
        stale_rows = api._build_results_list(docs, "none")
        self.assertTrue(all(not x.get("group") for x in await api._finalize(stale_rows, True, siblings=False)))
        await api._scan_all_groups()
        self.assertFalse(api.SCAN_STATE.get("error"))
        self.assertEqual(await self.groups.count_documents({}), 0)
        status, regrouped = await self.post("/api/group/save", {"name": "Film again", "items": [{"id": "a"}, {"id": "b"}]})
        self.assertEqual(status, 200, regrouped)
        self.assertNotIn("group_auto_excluded", await self.cols["primary"].find_one({"_id": "a"}))
        status, _ = await self.post("/api/group/remove_file", {"group_id": regrouped["group_id"], "file_id": "a"})
        self.assertEqual(status, 200)
        removed = await self.cols["primary"].find_one({"_id": "a"})
        self.assertTrue(removed["group_auto_excluded"])
        self.assertNotIn("group_id", removed)

    async def test_deleting_one_copy_keeps_the_group_and_remaining_cover(self):
        await self.insert_files(doc("a", "Film 720p.mkv", group_id="7"),
                                doc("a", "Film alternate.mkv", "cloud", group_id="7"),
                                doc("b", "Film 1080p.mkv", group_id="7"))
        await self.groups.insert_one({"_id": "7", "num": 7, "name": "Film", "members": ["a", "b"],
                                      "files": [{"id": "a", "name": "Film 720p.mkv"}, {"id": "b", "name": "Film 1080p.mkv"}],
                                      "group_type": "series", "episode_order": ["a", "b"],
                                      "episode_labels": [{"id": "a", "label": "First"}],
                                      "thumb_fid": "a", "thumb_col": "primary"})

        async def delete_copy(fid, source):
            return bool((await self.cols[source].delete_one({"_id": fid})).deleted_count)

        with patch.object(api, "delete_single_file", delete_copy):
            status, result = await self.post("/api/delete", {"file_id": "a", "collection": "primary"})
            self.assertEqual(status, 200, result)
            group = await self.groups.find_one({"_id": "7"})
            self.assertEqual(group["members"], ["a", "b"])
            self.assertEqual(group["episode_order"], ["a", "b"])
            self.assertEqual(group["thumb_col"], "cloud")
            self.assertEqual(group["files"][0]["name"], "Film alternate.mkv")
            status, result = await self.post("/api/delete", {"file_id": "a", "collection": "cloud"})
            self.assertEqual(status, 200, result)
        group = await self.groups.find_one({"_id": "7"})
        self.assertEqual(group["members"], ["b"])
        self.assertEqual(group["episode_order"], ["b"])
        self.assertEqual(group["episode_labels"], [])
        self.assertEqual(group["thumb_fid"], "")

    async def test_delete_reports_when_post_delete_cleanup_fails(self):
        await self.insert_files(doc("a", "Film 720p.mkv", group_id="7"))

        async def delete_copy(fid, source):
            return bool((await self.cols[source].delete_one({"_id": fid})).deleted_count)

        with patch.object(api, "delete_single_file", delete_copy), \
             patch.object(api, "_cleanup_deleted_copy", AsyncMock(side_effect=RuntimeError("write failed"))):
            status, result = await self.post("/api/delete", {"file_id": "a", "collection": "primary"})
        self.assertEqual(status, 500)
        self.assertIn("File was deleted", result["error"])
        self.assertIsNone(await self.cols["primary"].find_one({"_id": "a"}))

    async def test_remove_keeps_membership_when_exclusion_write_fails(self):
        await self.insert_files(doc("a", "Film 720p.mkv", group_id="7"))
        await self.groups.insert_one({"_id": "7", "members": ["a"], "files": [{"id": "a", "name": "Film 720p.mkv"}],
                                      "auto_keys": ["film"], "excluded": []})
        with patch.object(api, "_mark_files", AsyncMock(side_effect=RuntimeError("write failed"))):
            status, _ = await self.post("/api/group/remove_file", {"group_id": "7", "file_id": "a"})
        self.assertEqual(status, 500)
        self.assertEqual((await self.groups.find_one({"_id": "7"}))["members"], ["a"])
        self.assertEqual((await self.cols["primary"].find_one({"_id": "a"}))["group_id"], "7")

    async def test_group_preview_is_exact_admin_only_and_uses_live_details(self):
        members = [f"f{i}" for i in range(1, 8)]
        for i, fid in enumerate(members, 1):
            await self.insert_files(doc(fid, f"Current Episode {i}.mp4", "cloud" if i == 3 else "primary"))
        await self.groups.insert_one({
            "_id": "17", "num": 17, "name": "Series <Example>", "group_type": "series",
            "members": members, "files": [{"id": fid, "name": "Old name"} for fid in members],
            "episode_order": ["f3", "f1"], "episode_labels": [{"id": "f3", "label": "Pilot"}],
            "thumb_url": "TG_ID:private-telegram-id", "thumb_revision": "revision-17",
        })
        response = await self.client.get("/api/group/preview", params={"id": "#17"})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        data = await response.json()
        group = data["group"]
        self.assertEqual((group["id"], group["name"], group["group_type"], group["count"]),
                         ("17", "Series <Example>", "series", 7))
        self.assertEqual(len(group["members"]), 5)
        self.assertEqual(group["more"], 2)
        self.assertEqual(group["members"][0], {"name": "Current Episode 3.mp4", "label": "Pilot",
                                                 "source": "cloud", "available": True})
        self.assertEqual(group["cover"], "/api/group/thumb?gid=17&v=revision-17")
        self.assertEqual(group["cover_label"], "Group cover")
        self.assertRegex(group["signature"], r"^[0-9a-f]{64}$")
        self.assertNotIn("private-telegram-id", str(data))
        response = await self.client.get("/api/group/preview", params={"id": "# 17 "})
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["group"]["id"], "17")
        for invalid in ("", "17x", "-17", "##17", "1" * 65):
            response = await self.client.get("/api/group/preview", params={"id": invalid})
            self.assertEqual(response.status, 400, invalid)
        for missing in ("1", "0017", "999"):
            response = await self.client.get("/api/group/preview", params={"id": missing})
            self.assertEqual(response.status, 404, missing)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
        api.get_user_role.return_value = ("user", 9)
        response = await self.client.get("/api/group/preview", params={"id": "17"})
        self.assertEqual(response.status, 403)

    async def test_group_preview_legacy_and_missing_member_are_honest(self):
        await self.insert_files(doc("a", "Film 720p.mkv", thumb_url="TG_ID:cover", thumb_revision="r1"))
        await self.groups.insert_one({"_id": "7", "name": "Legacy", "members": ["a", "missing"],
                                      "files": [{"id": "missing", "name": "Stale filename"}]})
        response = await self.client.get("/api/group/preview", params={"id": "7"})
        self.assertEqual(response.status, 200)
        group = (await response.json())["group"]
        self.assertEqual(group["group_type"], "quality")
        self.assertEqual(group["members"][0]["label"], "720p")
        self.assertEqual(group["members"][1]["name"], "File unavailable")
        self.assertFalse(group["members"][1]["available"])
        self.assertEqual(group["cover"], "/api/thumb?file_id=a&col=primary&v=r1")
        self.assertEqual(group["cover_label"], "Sample file")
        await self.groups.update_one({"_id": "7"}, {"$set": {"thumb_fid": "a", "thumb_col": "primary", "thumb_revision": "group-r"}})
        response = await self.client.get("/api/group/preview", params={"id": "7"})
        group = (await response.json())["group"]
        self.assertEqual(group["cover"], "/api/thumb?file_id=a&col=primary&v=group-r")
        self.assertEqual(group["cover_label"], "Group cover")

    async def test_group_preview_fails_closed_when_database_is_unavailable(self):
        with patch.object(api.groups, "find_one", AsyncMock(side_effect=RuntimeError("private database error"))):
            response = await self.client.get("/api/group/preview", params={"id": "7"})
        self.assertEqual(response.status, 503)
        data = await response.json()
        self.assertNotIn("private database error", str(data))

    async def test_group_preview_does_not_hide_collection_read_failures(self):
        await self.groups.insert_one({"_id": "7", "name": "Example", "members": ["x"]})
        with patch.object(self.cols["primary"], "find", side_effect=RuntimeError("collection offline")):
            response = await self.client.get("/api/group/preview", params={"id": "7"})
        self.assertEqual(response.status, 503)
        self.assertNotIn("collection offline", str(await response.json()))

    async def test_group_list_prioritizes_the_exact_number(self):
        await self.groups.insert_one({"_id": "17", "name": "The exact group", "members": ["a"], "updated_at": 0})
        await self.groups.insert_many([
            {"_id": str(i), "name": f"Name 17 match {i}", "members": ["b"], "updated_at": i}
            for i in range(100, 130)
        ])
        response = await self.client.get("/api/group/list", params={"q": "#17"})
        data = await response.json()
        self.assertEqual(response.status, 200)
        self.assertEqual(len(data["groups"]), 25)
        self.assertEqual(data["groups"][0]["id"], "17")
        self.assertEqual(sum(g["id"] == "17" for g in data["groups"]), 1)

    async def test_stale_preview_rejects_file_and_group_moves_before_writing(self):
        await self.insert_files(doc("a", "Target 720p.mkv", group_id="10"),
                                doc("b", "Source 720p.mkv", group_id="11"))
        await self.groups.insert_many([
            {"_id": "10", "num": 10, "name": "Target", "members": ["a"], "files": [{"id": "a", "name": "Target 720p.mkv"}]},
            {"_id": "11", "num": 11, "name": "Source", "members": ["b"], "files": [{"id": "b", "name": "Source 720p.mkv"}]},
        ])
        response = await self.client.get("/api/group/preview", params={"id": "10"})
        signature = (await response.json())["group"]["signature"]
        await self.groups.update_one({"_id": "10"}, {"$set": {"name": "Renamed target", "group_type": "series"}})
        for path, body in [
            ("/api/group/save", {"group_id": "10", "items": [{"id": "b"}], "expected_target": signature}),
            ("/api/group/merge", {"source": "11", "target": "10", "expected_target": signature}),
        ]:
            status, result = await self.post(path, body)
            self.assertEqual(status, 409, result)
            self.assertEqual(result["code"], "target_changed")
            self.assertEqual((await self.groups.find_one({"_id": "10"}))["members"], ["a"])
            self.assertEqual((await self.groups.find_one({"_id": "11"}))["members"], ["b"])
            self.assertEqual((await self.cols["primary"].find_one({"_id": "b"}))["group_id"], "11")
        status, _ = await self.post("/api/group/save", {"group_id": "10", "items": [{"id": "b"}],
                                                        "expected_target": "not a signature"})
        self.assertEqual(status, 400)
        response = await self.client.get("/api/group/preview", params={"id": "10"})
        signature = (await response.json())["group"]["signature"]
        await self.groups.update_one({"_id": "10"}, {"$set": {"files.0.name": "Renamed member.mp4"}})
        status, result = await self.post("/api/group/merge", {"source": "11", "target": "10", "expected_target": signature})
        self.assertEqual((status, result.get("code")), (409, "target_changed"))
        response = await self.client.get("/api/group/preview", params={"id": "10"})
        signature = (await response.json())["group"]["signature"]
        status, result = await self.post("/api/group/merge", {"source": "11", "target": "10", "expected_target": signature})
        self.assertEqual(status, 200, result)
        self.assertIsNone(await self.groups.find_one({"_id": "11"}))
        self.assertEqual((await self.groups.find_one({"_id": "10"}))["members"], ["a", "b"])
        self.assertEqual((await self.cols["primary"].find_one({"_id": "b"}))["group_id"], "10")

    async def test_reviewed_move_compare_and_sets_target_at_write_time(self):
        await self.insert_files(doc("a", "Target.mp4", group_id="10"), doc("b", "Source.mp4", group_id="11"))
        await self.groups.insert_many([
            {"_id": "10", "name": "Target", "members": ["a"], "files": [{"id": "a", "name": "Target.mp4"}]},
            {"_id": "11", "name": "Source", "members": ["b"], "files": [{"id": "b", "name": "Source.mp4"}]},
        ])
        response = await self.client.get("/api/group/preview", params={"id": "10"})
        signature = (await response.json())["group"]["signature"]
        entered, release = asyncio.Event(), asyncio.Event()
        real_lookup = api.get_files_by_ids

        async def paused_lookup(ids):
            entered.set()
            await release.wait()
            return await real_lookup(ids)

        # Simulate a separate worker modifying the destination after its first
        # validation but before this worker writes to it.
        with patch.object(api, "get_files_by_ids", paused_lookup):
            task = asyncio.create_task(self.post("/api/group/save", {"group_id": "10", "items": [{"id": "b"}],
                                                                     "expected_target": signature}))
            await asyncio.wait_for(entered.wait(), 2)
            try:
                await self.groups.update_one({"_id": "10"}, {"$set": {"name": "Changed between read and write"}})
            finally:
                release.set()
            status, result = await asyncio.wait_for(task, 2)
        self.assertEqual((status, result.get("code")), (409, "target_changed"))
        self.assertEqual((await self.groups.find_one({"_id": "10"}))["members"], ["a"])
        self.assertEqual((await self.groups.find_one({"_id": "11"}))["members"], ["b"])
        self.assertEqual((await self.cols["primary"].find_one({"_id": "b"}))["group_id"], "11")

        response = await self.client.get("/api/group/preview", params={"id": "10"})
        signature = (await response.json())["group"]["signature"]
        real_update = self.groups.update_one

        async def raced_update(flt, update, **kwargs):
            await real_update({"_id": "10"}, {"$set": {"group_type": "series"}})
            return await real_update(flt, update, **kwargs)

        with patch.object(api.groups, "update_one", raced_update):
            status, result = await self.post("/api/group/merge", {"source": "11", "target": "10", "expected_target": signature})
        self.assertEqual((status, result.get("code")), (409, "target_changed"))
        self.assertEqual((await self.groups.find_one({"_id": "10"}))["members"], ["a"])
        self.assertEqual((await self.groups.find_one({"_id": "11"}))["members"], ["b"])

    async def test_reviewed_file_move_and_deleted_target(self):
        await self.insert_files(doc("a", "Target.mp4", group_id="10"), doc("b", "Source.mp4"))
        await self.groups.insert_one({"_id": "10", "num": 10, "name": "Target", "members": ["a"], "files": []})
        response = await self.client.get("/api/group/preview", params={"id": "10"})
        signature = (await response.json())["group"]["signature"]
        status, result = await self.post("/api/group/save", {"group_id": "10", "items": [{"id": "b"}],
                                                             "expected_target": signature})
        self.assertEqual(status, 200, result)
        self.assertEqual((await self.cols["primary"].find_one({"_id": "b"}))["group_id"], "10")
        await self.groups.delete_one({"_id": "10"})
        status, _ = await self.post("/api/group/save", {"group_id": "10", "items": [{"id": "b"}],
                                                        "expected_target": signature})
        self.assertEqual(status, 404)
        self.assertEqual((await self.cols["primary"].find_one({"_id": "b"}))["group_id"], "10")

    async def test_merge_keeps_target_type_and_series_metadata(self):
        await self.insert_files(doc("a", "Show 1.mkv", group_id="10"), doc("b", "Show 2.mkv", group_id="10"),
                                doc("c", "Show 3.mkv", "cloud", group_id="11"))
        await self.groups.insert_one({"_id": "10", "num": 10, "name": "Series", "members": ["a", "b"],
                                      "files": [{"id": "a", "name": "Show 1.mkv"}, {"id": "b", "name": "Show 2.mkv"}],
                                      "auto_keys": [], "excluded": [], "group_type": "series",
                                      "episode_order": ["b"], "episode_labels": [{"id": "b", "label": "Episode 1"}]})
        await self.groups.insert_one({"_id": "11", "num": 11, "name": "Other", "members": ["c"],
                                      "files": [{"id": "c", "name": "Show 3.mkv"}], "auto_keys": [],
                                      "excluded": [], "group_type": "quality"})
        status, result = await self.post("/api/group/merge", {"source": "11", "target": "10"})
        self.assertEqual(status, 200, result)
        target = await self.groups.find_one({"_id": "10"})
        self.assertEqual(target["group_type"], "series")
        self.assertEqual(target["episode_order"], ["b", "a", "c"])
        self.assertEqual(target["episode_labels"], [{"id": "b", "label": "Episode 1"}])
        self.assertIsNone(await self.groups.find_one({"_id": "11"}))
        self.assertEqual((await self.cols["cloud"].find_one({"_id": "c"}))["group_id"], "10")

    async def test_group_first_search_shows_new_member_without_refresh(self):
        docs = [doc("a", "Film 720p.mkv", group_id="7"), doc("b", "Film 1080p.mkv", group_id="7"),
                doc("c", "Film 480p.mkv", "cloud")]
        await self.insert_files(*docs)
        group = {"_id": "7", "num": 7, "name": "Film", "members": ["a", "b"],
                 "files": [{"id": "a", "name": docs[0]["file_name"]}, {"id": "b", "name": docs[1]["file_name"]}],
                 "auto_keys": ["film"], "excluded": [], "group_type": "quality"}
        await self.groups.insert_one(group)
        with patch.object(api, "_fetch_page", AsyncMock(return_value=([docs[2]], ""))):
            cards, _ = await api._grouped_first_page("Film", 0, 21, "none", "all", [group])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["gid"], "7")
        self.assertEqual({v["file_id"] for v in cards[0]["variants"]}, {"a", "b", "c"})
        self.assertEqual((await self.cols["cloud"].find_one({"_id": "c"}))["group_id"], "7")

    async def test_scan_counts_unique_files_across_collections(self):
        await self.insert_files(doc("same", "Film 720p.mkv"), doc("same", "Film 720p.mkv", "cloud"))
        await api._scan_all_groups()
        self.assertEqual(api.SCAN_STATE.get("error"), "")
        self.assertEqual(await self.groups.count_documents({}), 0)
        await self.insert_files(doc("other", "Film 1080p.mkv", "archive"))
        await api._scan_all_groups()
        self.assertEqual(api.SCAN_STATE.get("error"), "")
        group = await self.groups.find_one({})
        self.assertEqual(set(group["members"]), {"same", "other"})
        self.assertEqual(len(group["members"]), 2)
        for col in self.cols.values():
            self.assertEqual((await col.find_one({}))["group_id"], group["_id"])

    async def test_scan_does_not_group_one_id_under_conflicting_names(self):
        # The library resolves duplicate IDs in primary/cloud/archive order.
        await self.insert_files(doc("same", "Film 720p.mkv"),
                                doc("same", "Different 720p.mkv", "cloud"),
                                doc("film", "Film 1080p.mkv"),
                                doc("different", "Different 1080p.mkv", "cloud"))
        await api._scan_all_groups()
        self.assertEqual(api.SCAN_STATE.get("error"), "")
        groups = [g async for g in self.groups.find({})]
        self.assertEqual(len(groups), 1)
        self.assertEqual(set(groups[0]["members"]), {"same", "film"})
        self.assertEqual((await self.cols["cloud"].find_one({"_id": "same"}))["group_id"], groups[0]["_id"])
        self.assertNotIn("group_id", await self.cols["cloud"].find_one({"_id": "different"}))

    async def test_scan_rechecks_snapshot_before_creating_groups(self):
        await self.insert_files(doc("a", "Film 720p.mkv"), doc("b", "Film 1080p.mkv", "cloud"),
                                doc("c", "Film 480p.mkv", "archive"))

        class ChangeBeforeCreation:
            changed = False
            async def __aenter__(lock):
                if not lock.changed:
                    lock.changed = True
                    # Simulate an admin's completed move/removal after the scan read its snapshot.
                    await self.groups.insert_one({"_id": "99", "members": ["a"], "auto_keys": [], "excluded": []})
                    await self.cols["primary"].update_one({"_id": "a"}, {"$set": {"group_id": "99"}})
                    await self.cols["cloud"].update_one({"_id": "b"}, {"$set": {"group_auto_excluded": True}})
            async def __aexit__(lock, *args):
                pass

        with patch.object(api, "_AUTO_GROUP_LOCK", ChangeBeforeCreation()):
            await api._scan_all_groups()
        self.assertEqual(api.SCAN_STATE.get("error"), "")
        self.assertEqual(await self.groups.count_documents({}), 1)
        self.assertEqual((await self.groups.find_one({"_id": "99"}))["members"], ["a"])
        self.assertEqual((await self.cols["primary"].find_one({"_id": "a"}))["group_id"], "99")
        self.assertTrue((await self.cols["cloud"].find_one({"_id": "b"}))["group_auto_excluded"])
        self.assertNotIn("group_id", await self.cols["archive"].find_one({"_id": "c"}))

    async def test_library_scan_creates_numbered_quality_groups(self):
        await self.insert_files(doc("a", "Film 720p.mkv"), doc("b", "Film 1080p.mkv", "cloud"))
        await api._scan_all_groups()
        self.assertEqual(api.SCAN_STATE.get("error"), "")
        self.assertEqual(api.SCAN_STATE.get("created"), 1)
        group = await self.groups.find_one({})
        self.assertEqual(group["group_type"], "quality")
        self.assertEqual((await self.cols["primary"].find_one({"_id": "a"}))["group_id"], group["_id"])
        self.assertEqual((await self.cols["cloud"].find_one({"_id": "b"}))["group_id"], group["_id"])

    async def test_delayed_auto_join_does_not_undo_a_move_or_exclusion(self):
        await self.insert_files(doc("a", "Film 720p.mkv", group_id="7"),
                                doc("b", "Film 1080p.mkv", group_id="8"))
        await self.groups.insert_one({"_id": "7", "members": ["a"], "auto_keys": ["film"], "excluded": ["b"]})
        await self.groups.insert_one({"_id": "8", "members": ["b"], "auto_keys": [], "excluded": []})
        await api._persist_joins([("7", "b", "Film 1080p.mkv")])
        self.assertEqual((await self.groups.find_one({"_id": "7"}))["members"], ["a"])
        self.assertEqual((await self.cols["primary"].find_one({"_id": "b"}))["group_id"], "8")

    async def test_delayed_auto_join_checks_the_current_filename(self):
        await self.insert_files(doc("a", "Film 720p.mkv", group_id="7"), doc("b", "Different 1080p.mkv"))
        await self.groups.insert_one({"_id": "7", "members": ["a"], "auto_keys": ["film"], "excluded": []})
        # The candidate was renamed after the search read its earlier name.
        await api._persist_joins([("7", "b", "Film 1080p.mkv")])
        self.assertEqual((await self.groups.find_one({"_id": "7"}))["members"], ["a"])
        self.assertNotIn("group_id", await self.cols["primary"].find_one({"_id": "b"}))

    async def test_rejected_auto_join_is_not_shown_as_saved_membership(self):
        await self.insert_files(doc("a", "Film 720p.mkv", group_id="7"), doc("b", "Different 1080p.mkv"))
        await self.groups.insert_one({"_id": "7", "num": 7, "name": "Film", "members": ["a"],
                                      "auto_keys": ["film"], "excluded": []})
        stale = api._build_results_list([doc("b", "Film 1080p.mkv")], "none")
        cards = await api._finalize(stale, True, siblings=False)
        group = next(c for c in cards if c.get("gid") == "7")
        self.assertEqual([v["file_id"] for v in group["variants"]], ["a"])
        self.assertTrue(any(c.get("file_id") == "b" and not c.get("gid") for c in cards))
        self.assertEqual((await self.groups.find_one({"_id": "7"}))["members"], ["a"])

    async def test_type_filters_and_raw_mode_resolve_legacy_members(self):
        await self.insert_files(doc("a", "Quality 720p.mkv"), doc("b", "Quality 1080p.mkv"),
                                doc("c", "Episode 1.mkv"), doc("d", "Episode 2.mkv", "cloud"))
        await self.groups.insert_one({"_id": "11", "num": 11, "name": "Quality", "members": ["a", "b"], "auto_keys": []})
        await self.groups.insert_one({"_id": "12", "num": 12, "name": "Series", "members": ["c", "d"],
                                      "auto_keys": [], "group_type": "series"})
        for kind, expected in (("series", "12"), ("quality", "11")):
            response = await self.client.get('/api/search', params={"group": "1", "gf": kind, "mode": "none"})
            data = await response.json()
            self.assertEqual(response.status, 200, data)
            self.assertEqual([r["gid"] for r in data["results"]], [expected])
            self.assertEqual(data["results"][0]["group_type"], kind)
        # The old file docs have no group_id marks, but the raw/miniapp view still gets IDs.
        response = await self.client.get('/api/search', params={"mode": "none"})
        data = await response.json()
        self.assertEqual({r["file_id"]: r["gid"] for r in data["results"]},
                         {"a": "11", "b": "11", "c": "12", "d": "12"})

    async def test_admin_endpoints_require_admin(self):
        api.get_user_role.return_value = ("user", 9)
        for path in ("/api/group/save", "/api/group/update", "/api/group/remove_file", "/api/group/delete"):
            status, _ = await self.post(path, {})
            self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
