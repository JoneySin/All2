"""Grouping regression tests. No Telegram account or live MongoDB is required."""

import asyncio
import copy
import os
import re
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
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
from web.grouping import (auto_group_plan, duration_seconds, episode_identity, episode_number,
                          order_series, quality_title_key, series_key, series_title)


def doc(fid, name, source="primary", **extra):
    return {"_id": fid, "file_ref": fid, "file_name": name, "file_size": 1000,
            "file_type": "video", "source_col": source, "duration": 3600, **extra}


class GroupingUnitTests(unittest.TestCase):
    def test_miniapp_file_cards_do_not_render_group_ids(self):
        miniapp = (Path(__file__).resolve().parents[1] / 'web' / 'miniapp.html').read_text()
        self.assertNotIn('gid-chip', miniapp)
        self.assertNotIn('GROUP #${', miniapp)

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
        # Previously saved automatic groups remain visible even with two files.
        group = {"_id": "17", "num": 17, "name": "Movie", "members": ["a", "b"], "auto_created": True}
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

    def test_saved_one_member_group_is_shown_as_a_file(self):
        item = api._build_results_list([doc("a", "Episode 1", group_id="4")], "none")
        group = {"_id": "4", "num": 4, "name": "Series", "members": ["a"], "group_type": "series"}
        card = api.group_results(item, {"a": group})[0]
        self.assertFalse(card.get("group"))
        self.assertEqual((card["file_id"], card["gid"]), ("a", ""))

    def test_normalization_and_explicit_episode_formats(self):
        self.assertEqual(quality_title_key("A New Film 2024 Hindi WEB-DL 720p.mkv"),
                         quality_title_key("A.New.Film.2024.English.BluRay.1080p.mp4"))
        self.assertNotEqual(quality_title_key("A New Film 2023 720p"), quality_title_key("A New Film 2024 720p"))
        self.assertEqual(quality_title_key("A_Film_1920x1080.mkv"), quality_title_key("A Film 720p.mp4"))
        self.assertEqual(quality_title_key("Film [Uploader A] (2024) 720p"),
                         quality_title_key("Film [Uploader B] 2024 1080p"))
        self.assertNotEqual(quality_title_key("Film (2023) 720p"), quality_title_key("Film (2024) 1080p"))
        for name, identity in (("North Star S01E02", "S01E02"), ("North Star 1x02", "S01E02"),
                               ("North Star Episode 2", "E02"), ("North Star Part 2", "E02"),
                               ("North Star Chapter 2", "E02"), ("North Star 2 of 10", "E02")):
            self.assertEqual(episode_identity(name), identity)
            self.assertEqual(series_key(name), "north star")
        self.assertEqual(series_key("24 [S01E01] 1080p.mkv"), "24")
        self.assertEqual(series_key("नीला आकाश S01E01.mkv"), "नीला आकाश")
        self.assertEqual(quality_title_key("कहानी 720p.mkv"), "कहानी")
        self.assertNotEqual(quality_title_key("कहानी 720p.mkv"), quality_title_key("कहनी 1080p.mkv"))
        self.assertEqual(series_title("Northern Lights [S01E02] WEB-DL 1080p.mkv"), "Northern Lights")
        self.assertEqual(series_title("Northern Lights (2024) [S01E02].mkv"), "Northern Lights (2024)")
        self.assertNotEqual(series_key("The Long Journey Home North S01E01.mkv"),
                            series_key("The Long Journey Home South S01E02.mkv"))
        self.assertEqual(duration_seconds("1:02:03"), 3723)
        self.assertEqual(duration_seconds({"duration_seconds": 0, "duration": "2:30"}), 150)
        self.assertEqual(duration_seconds("unknown"), 0)

    def test_automatic_threshold_runtime_and_series_precedence(self):
        def cards(*docs):
            return api.group_results(api._build_results_list(list(docs), "none"))

        # Two distinct files are enough; a single file never makes a group.
        self.assertFalse(cards(doc("a", "Film 720p"))[0].get("group"))
        pair = cards(doc("a", "Film 720p"), doc("b", "Film 1080p"))
        self.assertEqual((len(pair), pair[0]["group_type"], pair[0]["count"]), (1, "quality", 2))
        series_pair = cards(doc("a", "Show S01E01", duration=100), doc("b", "Show S01E02", duration=0))
        self.assertEqual((series_pair[0]["group_type"], series_pair[0]["count"]), ("series", 2))
        quality = cards(doc("a", "Film Hindi 720p", duration=5400),
                        doc("b", "Film English 1080p", duration=5400),
                        doc("c", "Film WEB-DL 480p", duration=5400))[0]
        self.assertEqual((quality["group_type"], quality["count"], quality["duration"]), ("quality", 3, "1:30:00"))
        self.assertTrue(all(not c.get("group") for c in cards(
            doc("a", "Film 720p", duration=5400), doc("b", "Film 1080p", duration=5401),
            doc("c", "Film 480p", duration=0))))

        # A series needs at least two distinct episode identities.
        same_ep = cards(doc("a", "Show S01E01 720p"), doc("b", "Show S01E01 1080p"),
                        doc("c", "Show 1x01 480p"))[0]
        self.assertEqual(same_ep["group_type"], "quality")
        series = cards(doc("a", "Show S01E01 720p", duration=1200),
                       doc("b", "Show S01E01 1080p", duration=1200),
                       doc("c", "Show S01E02 480p", duration=2400))[0]
        self.assertEqual((series["group_type"], series["count"], series["episode_count"], series["duration"]),
                         ("series", 3, 2, ""))
        self.assertEqual(cards(doc("x", "Show S01E01"), doc("y", "Show S01E02"))[0]["count"], 2)
        mixed = cards(doc("a", "Show S01E01", duration=100), doc("b", "Show S01E02", duration=100),
                      doc("c", "Other Show S01E03", duration=100))
        self.assertEqual({v["file_id"] for card in mixed if card.get("group") for v in card["variants"]}, {"a", "b"})
        self.assertTrue(any(card.get("file_id") == "c" for card in mixed))

    def test_large_automatic_buckets_are_not_misidentified(self):
        quality = [doc(str(i), "Popular Film 720p", duration=60) for i in range(31)]
        self.assertEqual(auto_group_plan(quality), [])
        series = [doc(str(i), f"Popular Series S01E{i:03d}", duration=60) for i in range(1, 502)]
        self.assertFalse(any(plan["kind"] == "series" for plan in auto_group_plan(series)))

    def test_manual_quality_duration_uses_mode_and_series_never_has_one(self):
        rows = api._build_results_list([doc("a", "One 720p", duration=3600),
                                        doc("b", "Two 1080p", duration=4000),
                                        doc("c", "Three 480p", duration=3600)], "none")
        group = {"_id": "17", "name": "Manual", "members": ["a", "b", "c"]}
        manual = {fid: group for fid in ("a", "b", "c")}
        self.assertEqual(api.group_results(rows, manual)[0]["duration"], "1:00:00")
        group["group_type"] = "series"
        self.assertEqual(api.group_results(rows, manual)[0]["duration"], "")


class GroupingIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mongo = AsyncMongoMockClient()
        self.db = self.mongo["group_test"]
        self.cols = {name: self.db[name.capitalize()] for name in ("primary", "cloud", "archive")}
        self.groups = self.db.QualityGroups
        self.seq = self.db.QualityGroupSeq
        patches = [
            patch.object(api, "groups", self.groups), patch.object(api, "group_seq", self.seq),
            patch.object(api, "group_search_cursors", self.db.GroupSearchCursors),
            patch.object(api, "FILE_COLLECTIONS", self.cols),
            patch.object(api, "COLLECTIONS", {**self.cols, "actors": self.db.Actors}),
            patch.object(api, "get_user_role", AsyncMock(return_value=("admin", 1))),
            patch.object(api, "_AUTO_GROUP_LOCK", asyncio.Lock()),
            patch.object(db, "primary", self.cols["primary"]),
            patch.object(db, "cloud", self.cols["cloud"]), patch.object(db, "archive", self.cols["archive"]),
            patch.object(db, "groups", self.groups),
            patch.object(self.groups, "aggregate", AsyncMock(wraps=self.groups.aggregate)),
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
        docs = [doc("a", "Film 720p.mkv"), doc("b", "Film 1080p.mkv", "cloud"),
                doc("c", "Film 480p.mkv", "archive")]
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
        docs = [doc("a", "Film 720p.mkv"), doc("b", "Film 1080p.mkv", "cloud"),
                doc("c", "Film 480p.mkv", "archive")]
        await self.insert_files(*docs)
        entered, release = asyncio.Event(), asyncio.Event()
        real_lookup = api._live_group_files

        async def paused_lookup(ids):
            if api._AUTO_GROUP_LOCK.locked():
                entered.set()
                await release.wait()
            return await real_lookup(ids)

        with patch.object(api, "_live_group_files", paused_lookup):
            auto = asyncio.create_task(api._finalize(api._build_results_list(docs, "none"), True, siblings=False))
            await asyncio.wait_for(entered.wait(), 2)
            admin = asyncio.create_task(self.post("/api/group/save", {
                "name": "Hand-picked", "items": [{"id": "a"}, {"id": "b"}, {"id": "c"}], "group_type": "series"}))
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
        self.assertEqual(set(group["members"]), {"a", "b", "c"})
        self.assertEqual((await self.cols["primary"].find_one({"_id": "a"}))["group_id"], group["_id"])
        self.assertEqual((await self.cols["cloud"].find_one({"_id": "b"}))["group_id"], group["_id"])
        self.assertEqual((await self.cols["archive"].find_one({"_id": "c"}))["group_id"], group["_id"])

    async def test_auto_group_respects_exclusion_in_any_collection(self):
        await self.insert_files(doc("a", "Film 720p.mkv"),
                                doc("a", "Film 720p.mkv", "cloud", group_auto_excluded=True),
                                doc("b", "Film 1080p.mkv"), doc("c", "Film 480p.mkv"))
        # The page may contain the other, stale copy without its exclusion flag.
        cards = await api._finalize(api._build_results_list([
            doc("a", "Film 720p.mkv"), doc("b", "Film 1080p.mkv"), doc("c", "Film 480p.mkv")], "none"), True, siblings=False)
        group = next(c for c in cards if c.get("group"))
        self.assertEqual({v["file_id"] for v in group["variants"]}, {"b", "c"})
        self.assertTrue(any(c.get("file_id") == "a" for c in cards))
        self.assertEqual(await self.groups.count_documents({}), 1)
        await api._scan_all_groups()
        self.assertEqual(api.SCAN_STATE.get("error"), "")
        self.assertEqual(set((await self.groups.find_one({}))["members"]), {"b", "c"})

    async def test_failed_live_recheck_never_invents_a_group_number(self):
        rows = api._build_results_list([doc("a", "Film 720p.mkv"), doc("b", "Film 1080p.mkv"),
                                         doc("c", "Film 480p.mkv")], "none")
        with patch.object(api, "_live_group_files", AsyncMock(side_effect=RuntimeError("database offline"))):
            cards = await api._finalize(rows, True, siblings=False)
        self.assertTrue(cards[0]["group"])
        self.assertEqual(cards[0]["gid"], "")
        self.assertEqual(await self.groups.count_documents({}), 0)

    async def test_saved_group_stats_follow_create_type_change_and_removal(self):
        await self.insert_files(doc('a', 'Episode 1'), doc('b', 'Episode 2', 'cloud'))
        status, result = await self.post('/api/group/save', {
            'name': 'Series', 'group_type': 'series', 'items': [{'id': 'a'}, {'id': 'b'}]})
        self.assertEqual(status, 200, result)
        gid = result['group_id']
        self.assertEqual(await db.get_saved_group_counts(), {'total': 1, 'quality': 0, 'series': 1})
        status, result = await self.post('/api/group/update', {'group_id': gid, 'group_type': 'quality'})
        self.assertEqual(status, 200, result)
        self.assertEqual(await db.get_saved_group_counts(), {'total': 1, 'quality': 1, 'series': 0})
        status, result = await self.post('/api/group/remove_file', {'group_id': gid, 'file_id': 'a'})
        self.assertEqual(status, 200, result)
        self.assertEqual(await db.get_saved_group_counts(), {'total': 0, 'quality': 0, 'series': 0})
        self.assertIsNotNone(await self.cols['primary'].find_one({'_id': 'a'}))
        self.assertIsNotNone(await self.cols['cloud'].find_one({'_id': 'b'}))

    async def test_series_create_edit_order_labels_and_auto_join(self):
        docs = [doc("a", "Same Name Episode 1.mkv", duration=1500),
                doc("b", "Same Name Episode 2.mkv", "cloud", duration=2500)]
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

        # A marked episode of the same series may join despite its different runtime.
        new_doc = doc("c", "Same Name Episode 3.mkv", "archive", duration=1800)
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

    async def test_single_file_creation_is_rejected_even_with_duplicate_ids(self):
        await self.insert_files(doc("a", "Film 720p"))
        for items in ([{"id": "a"}], [{"id": "a"}, {"id": "a"}]):
            status, result = await self.post("/api/group/save", {"name": "Film", "items": items})
            self.assertEqual(status, 400, result)
            self.assertIn("2 distinct", result["error"])
        self.assertEqual(await self.groups.count_documents({}), 0)

    async def test_legacy_singleton_is_a_file_until_another_file_joins(self):
        await self.insert_files(doc("a", "Legacy 720p", group_id="7"), doc("b", "Other title"))
        await self.groups.insert_one({"_id": "7", "num": 7, "name": "Legacy", "members": ["a"],
                                      "files": [{"id": "a", "name": "Legacy 720p"}], "auto_keys": []})
        for grouped in ("0", "1"):
            response = await self.client.get("/api/search", params={"group": grouped, "mode": "none"})
            cards = (await response.json())["results"]
            card = next(row for row in cards if row.get("file_id") == "a")
            self.assertFalse(card.get("group"))
            self.assertEqual(card["gid"], "")
        self.assertIsNotNone(await self.groups.find_one({"_id": "7"}))
        status, result = await self.post("/api/group/save", {"group_id": "7", "items": [{"id": "b"}]})
        self.assertEqual(status, 200, result)
        cards = await api._group_cards([await self.groups.find_one({"_id": "7"})], "none")
        self.assertEqual((cards[0]["gid"], cards[0]["count"]), ("7", 2))

    async def test_dissolve_does_not_delete_a_concurrently_expanded_group(self):
        await self.insert_files(doc("a", "Film A", group_id="7"), doc("b", "Film B", group_id="7"))
        await self.groups.insert_one({"_id": "7", "members": ["a"]})
        original = self.groups.delete_one
        async def concurrent_delete(query):
            await self.groups.update_one({"_id": "7"}, {"$addToSet": {"members": "b"}})
            return await original(query)
        with patch.object(self.groups, "delete_one", side_effect=concurrent_delete):
            await api._group_cleanup(dissolve_ids=["7"], strict=True)
        self.assertEqual((await self.groups.find_one({"_id": "7"}))["members"], ["a", "b"])
        self.assertEqual((await self.cols["primary"].find_one({"_id": "a"}))["group_id"], "7")

    async def test_move_dissolves_source_left_with_one_file(self):
        await self.insert_files(doc("a", "Film A", group_id="7"), doc("b", "Film B", "cloud", group_id="7"),
                                doc("c", "Film C", group_id="8"), doc("d", "Film D", group_id="8"))
        for gid, members in (("7", ["a", "b"]), ("8", ["c", "d"])):
            await self.groups.insert_one({"_id": gid, "num": int(gid), "name": "Film", "members": members})
        status, result = await self.post("/api/group/save", {"group_id": "8", "items": [{"id": "a"}]})
        self.assertEqual(status, 200, result)
        self.assertIsNone(await self.groups.find_one({"_id": "7"}))
        self.assertNotIn("group_id", await self.cols["cloud"].find_one({"_id": "b"}))
        self.assertEqual(set((await self.groups.find_one({"_id": "8"}))["members"]), {"a", "c", "d"})

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
        status, result = await self.post("/api/group/remove_file", {"group_id": regrouped["group_id"], "file_id": "a"})
        self.assertEqual(status, 200)
        self.assertTrue(result["group_deleted"])
        self.assertIsNone(await self.groups.find_one({"_id": regrouped["group_id"]}))
        removed = await self.cols["primary"].find_one({"_id": "a"})
        self.assertTrue(removed["group_auto_excluded"])
        self.assertNotIn("group_id", removed)
        self.assertNotIn("group_id", await self.cols["primary"].find_one({"_id": "b"}))

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
        self.assertIsNone(await self.groups.find_one({"_id": "7"}))
        survivor = await self.cols["primary"].find_one({"_id": "b"})
        self.assertIsNotNone(survivor)
        self.assertNotIn("group_id", survivor)

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

    async def test_all_search_does_not_auto_join_unsaved_matching_file(self):
        docs = [doc("a", "Film 720p.mkv", group_id="7"), doc("b", "Film 1080p.mkv", group_id="7"),
                doc("c", "Film 480p.mkv", "cloud")]
        await self.insert_files(*docs)
        group = {"_id": "7", "num": 7, "name": "Film", "members": ["a", "b"],
                 "auto_keys": ["film"], "excluded": [], "group_type": "quality"}
        await self.groups.insert_one(group)
        with patch.object(api, 'build_query_filter', lambda raw, regex, lang=None: ({'file_name':regex}, False)):
            response = await self.client.get('/api/search', params={'q':'Film', 'group':'1', 'gf':'all', 'mode':'none'})
        data = await response.json()
        self.assertEqual(response.status, 200, data)
        self.assertEqual(data['results'][0]['gid'], '7')
        self.assertEqual({v['file_id'] for v in data['results'][0]['variants']}, {'a','b'})
        self.assertEqual([r['file_id'] for r in data['results'][1:]], ['c'])
        self.assertNotIn('group_id', await self.cols['cloud'].find_one({'_id':'c'}))
        self.assertEqual((await self.groups.find_one({'_id':'7'}))['members'], ['a','b'])

    async def test_bot_start_schedules_scan_without_waiting_and_restarts_it(self):
        import bot as bot_module

        await self.insert_files(doc("a", "Film 720p"), doc("b", "Film 1080p", "cloud"))
        entered, release = asyncio.Event(), asyncio.Event()
        original_scan = api._scan_all_groups
        async def delayed_scan():
            entered.set()
            await release.wait()
            await original_scan()
        async def background(_bot):
            await asyncio.Event().wait()

        runner = SimpleNamespace(setup=AsyncMock(), cleanup=AsyncMock())
        site = SimpleNamespace(start=AsyncMock())
        me = SimpleNamespace(id=1, username="test", first_name="Test", mention="Test")
        instance = bot_module.Bot.__new__(bot_module.Bot)
        with (patch.object(bot_module.Client, "start", AsyncMock()),
              patch.object(bot_module.Client, "stop", AsyncMock()),
              patch.object(bot_module.Bot, "add_handler"),
              patch.object(bot_module.Bot, "get_me", AsyncMock(return_value=me)),
              patch.object(bot_module.Bot, "send_message", AsyncMock()),
              patch.object(bot_module, "ensure_indexes", AsyncMock()),
              patch.object(bot_module.db, "_ensure_indexes", AsyncMock()),
              patch.object(bot_module.db, "get_banned", AsyncMock(return_value=([], []))),
              patch.object(bot_module.web, "AppRunner", return_value=runner),
              patch.object(bot_module.web, "TCPSite", return_value=site),
              patch.object(bot_module, "check_premium_expired", background),
              patch.object(bot_module, "auto_delete_worker", background),
              patch.object(bot_module, "ADMINS", []), patch.object(bot_module, "LOG_CHANNEL", None),
              patch.object(api, "_scan_all_groups", delayed_scan)):
            await asyncio.wait_for(instance.start(), 2)
            await asyncio.wait_for(entered.wait(), 2)
            self.assertTrue(api.SCAN_STATE["running"])
            self.assertEqual(await self.groups.count_documents({}), 0)
            release.set()
            await api._SCAN_TASK
            first = await self.groups.find_one({})
            self.assertEqual(set(first["members"]), {"a", "b"})
            await instance.stop()
            await self.insert_files(doc("c", "Film 480p", "archive"))
            await instance.start()
            await api._SCAN_TASK
            self.assertEqual(set((await self.groups.find_one({"_id": first["_id"]}))["members"]), {"a", "b", "c"})
            self.assertEqual(await self.groups.count_documents({}), 1)
            await instance.stop()

    async def test_startup_scan_reservation_shutdown_and_restart(self):
        # Startup and the manual button must share a reservation even before
        # the background coroutine gets its first event-loop turn.
        await self.insert_files(doc("a", "Film 720p"), doc("b", "Film 1080p", "cloud"))
        task = api.start_group_scan()
        self.assertIsNotNone(task)
        self.assertIsNone(api.start_group_scan())
        await task
        self.assertEqual(api.SCAN_STATE["phase"], "complete")
        original = await self.groups.find_one({})
        self.assertEqual(set(original["members"]), {"a", "b"})
        await self.insert_files(doc("c", "Film 480p", "archive"),
                                doc("d", "New Show S01E01"), doc("e", "New Show S01E02"))
        task = api.start_group_scan()
        await task
        self.assertEqual(await self.groups.count_documents({}), 2)
        self.assertEqual(set((await self.groups.find_one({"_id": original["_id"]}))["members"]), {"a", "b", "c"})
        self.assertEqual(api.SCAN_STATE["phase"], "complete")
        # Shutdown before the worker has even begun must free the reservation.
        api.start_group_scan()
        await api.stop_group_scan()
        await asyncio.sleep(0)
        self.assertFalse(api.SCAN_STATE["running"])
        self.assertEqual(api.SCAN_STATE["phase"], "cancelled")
        await api.start_group_scan()
        self.assertEqual(api.SCAN_STATE["phase"], "complete")
        self.assertEqual(await self.groups.count_documents({}), 2)

    async def test_scan_cancellation_while_running_and_manual_retry(self):
        entered = asyncio.Event()
        async def blocked_scan():
            entered.set()
            await asyncio.Event().wait()
        with patch.object(api, "_scan_all_groups", blocked_scan):
            task = api.start_group_scan()
            await asyncio.wait_for(entered.wait(), 2)
            status, body = await self.post("/api/group/scan_all", {})
            self.assertEqual(status, 200)
            self.assertEqual(body, {"started": False, "running": True})
            await api.stop_group_scan()
            self.assertTrue(task.cancelled())
            await asyncio.sleep(0)
            self.assertFalse(api.SCAN_STATE["running"])
        status, body = await self.post("/api/group/scan_all", {})
        self.assertEqual(status, 200)
        self.assertTrue(body["started"])
        task = api._SCAN_TASK
        await task
        self.assertEqual(api.SCAN_STATE["phase"], "complete")

    async def test_cancelled_partial_startup_scan_is_repaired_on_next_run(self):
        await self.insert_files(doc("a", "Film 720p"), doc("b", "Film 1080p", "cloud"))
        entered = asyncio.Event()
        async def interrupted_mark(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()
        with patch.object(api, "_mark_files", interrupted_mark):
            task = api.start_group_scan()
            await asyncio.wait_for(entered.wait(), 2)
            await api.stop_group_scan()
            self.assertTrue(task.cancelled())
        self.assertEqual(api.SCAN_STATE["phase"], "cancelled")
        group = await self.groups.find_one({})
        self.assertIsNotNone(group)
        await api.start_group_scan()
        self.assertEqual(api.SCAN_STATE["phase"], "complete")
        self.assertEqual(await self.groups.count_documents({}), 1)
        for fid, source in (("a", "primary"), ("b", "cloud")):
            self.assertEqual((await self.cols[source].find_one({"_id": fid}))["group_id"], group["_id"])

    async def test_scan_endpoints_are_admin_only(self):
        for role in ("user", None):
            with patch.object(api, "get_user_role", AsyncMock(return_value=(role, 2))):
                response = await self.client.post("/api/group/scan_all", json={})
                self.assertEqual(response.status, 403)
                response = await self.client.get("/api/group/scan_status")
                self.assertEqual(response.status, 403)
        self.assertFalse(api.SCAN_STATE.get("running"))

    async def test_scan_counts_unique_files_across_collections(self):
        await self.insert_files(doc("same", "Film 720p.mkv"), doc("same", "Film 720p.mkv", "cloud"))
        await api._scan_all_groups()
        self.assertEqual(api.SCAN_STATE.get("error"), "")
        self.assertEqual(await self.groups.count_documents({}), 0)
        await self.insert_files(doc("other", "Film 1080p.mkv", "archive"))
        await api._scan_all_groups()
        self.assertEqual(await self.groups.count_documents({}), 1)
        self.assertEqual(set((await self.groups.find_one({}))["members"]), {"same", "other"})
        await self.insert_files(doc("third", "Film 480p.mkv", "cloud"))
        await api._scan_all_groups()
        self.assertEqual(api.SCAN_STATE.get("error"), "")
        group = await self.groups.find_one({})
        self.assertEqual(set(group["members"]), {"same", "other", "third"})
        self.assertEqual(len(group["members"]), 3)
        for col in self.cols.values():
            self.assertEqual((await col.find_one({}))["group_id"], group["_id"])

    async def test_scan_does_not_group_one_id_under_conflicting_names(self):
        # The library resolves duplicate IDs in primary/cloud/archive order.
        await self.insert_files(doc("same", "Film 720p.mkv"),
                                doc("same", "Different 720p.mkv", "cloud"),
                                doc("film", "Film 1080p.mkv"), doc("film2", "Film 480p.mkv", "archive"),
                                doc("different", "Different 1080p.mkv", "cloud"))
        await api._scan_all_groups()
        self.assertEqual(api.SCAN_STATE.get("error"), "")
        groups = [g async for g in self.groups.find({})]
        self.assertEqual(len(groups), 1)
        self.assertEqual(set(groups[0]["members"]), {"same", "film", "film2"})
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
        await self.insert_files(doc("a", "Film 720p.mkv"), doc("b", "Film 1080p.mkv", "cloud"),
                                doc("c", "Film 480p.mkv", "archive"))
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
        # The stale search result must not pull in an unrelated saved group.
        self.assertFalse(any(c.get("gid") == "7" for c in cards))
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

    async def test_ungrouped_search_only_matches_files_not_group_names(self):
        await self.insert_files(doc('a', 'Festival matching', group_id='11'),
                                doc('b', 'Unrelated sibling', 'cloud', group_id='11'),
                                doc('c', 'Festival single', 'archive'))
        await self.groups.insert_one({'_id': '11', 'name': 'Special Collection', 'members': ['a', 'b'],
                                      'files': [{'id':'a', 'name':'Festival matching'}, {'id':'b', 'name':'Unrelated sibling'}]})
        def regex_filter(raw, regex, lang=None):
            return {'file_name': regex}, False
        with patch.object(api, 'build_query_filter', regex_filter), \
             patch.object(api.groups, 'find', side_effect=AssertionError('UnGroup must not read groups')):
            response = await self.client.get('/api/search', params={'q':'Festival', 'group':'1', 'gf':'single'})
            data = await response.json()
            self.assertEqual(response.status, 200, data)
            self.assertEqual([r['file_id'] for r in data['results']], ['a', 'c'])
            response = await self.client.get('/api/search', params={'q':'Special Collection', 'group':'1', 'gf':'single'})
            self.assertEqual((await response.json())['results'], [])
        self.assertEqual((await self.groups.find_one({'_id':'11'}))['members'], ['a', 'b'])

    async def test_recent_ungroup_pages_in_collection_order(self):
        docs = [doc(f'{source}{i}', 'File', source, added_on=i, group_id='11')
                for source in ('primary','cloud','archive') for i in range(4)]
        await self.insert_files(*docs)
        expected = [(source, f'{source}{i}') for source in ('primary','cloud','archive') for i in reversed(range(4))]
        with patch.object(api, 'MAX_WEB_RESULTS', 5), patch.object(api.groups, 'find', side_effect=AssertionError('group lookup')):
            found, offset = [], 0
            for _ in range(5):
                response = await self.client.get('/api/search', params={'group':'1', 'gf':'single', 'offset':offset})
                data = await response.json()
                self.assertEqual(response.status, 200, data)
                found.extend((r['raw_collection'], r['file_id']) for r in data['results'])
                offset = data['next_offset']
                if not offset: break
            else: self.fail('pagination did not terminate')
        self.assertEqual(found, expected)

    async def test_search_partitions_durations_and_series_and_is_idempotent(self):
        docs = [
            doc("q1", "River Film 720p.mkv", duration=5400),
            doc("q2", "River Film 1080p.mkv", "cloud", duration=5400),
            doc("q3", "River Film 480p.mkv", "archive", duration=5400),
            doc("d1", "River Film 720p.mkv", duration=5401),
            doc("d2", "River Film 1080p.mkv", "cloud", duration=5401),
            doc("d3", "River Film 480p.mkv", "archive", duration=5401),
            doc("u1", "River Film 720p.mkv", duration=0),
            doc("u2", "River Film 1080p.mkv", "cloud", duration=0),
            doc("u3", "River Film 480p.mkv", "archive", duration=0),
            doc("s1", "North Star S01E01 720p.mkv", duration=1200),
            doc("s2", "North Star S01E01 1080p.mkv", "cloud", duration=1200),
            doc("s3", "North Star S01E02 480p.mkv", "archive", duration=2200),
            doc("t1", "Just Two 720p.mkv"), doc("t2", "Just Two 1080p.mkv", "cloud"),
        ]
        await self.insert_files(*docs)
        rows = api._build_results_list(docs, "none")
        cards = await api._finalize(rows, True, siblings=False)
        groups = [card for card in cards if card.get("group")]
        self.assertEqual(len(groups), 4)
        self.assertEqual({frozenset(v["file_id"] for v in card["variants"]) for card in groups},
                         {frozenset({"q1", "q2", "q3"}), frozenset({"d1", "d2", "d3"}),
                          frozenset({"s1", "s2", "s3"}), frozenset({"t1", "t2"})})
        series = next(card for card in groups if card["group_type"] == "series")
        self.assertEqual(series["duration"], "")
        self.assertEqual({card["duration"] for card in groups if card["group_type"] == "quality"},
                         {"1:30:00", "1:30:01", "1:00:00"})
        self.assertEqual({card["file_id"] for card in cards if not card.get("group")},
                         {"u1", "u2", "u3"})
        await api._finalize(rows, True, siblings=False)
        await api._scan_all_groups()
        self.assertEqual(api.SCAN_STATE["error"], "")
        self.assertEqual(await self.groups.count_documents({}), 4)

    async def test_full_scan_creates_only_two_or_more_compatible_groups(self):
        docs = [doc("q1", "A Film 720p", duration=100), doc("q2", "A Film 1080p", "cloud", duration=100),
                doc("q3", "A Film 480p", "archive", duration=100), doc("qd", "A Film 4K", duration=101),
                doc("u1", "Unknown 720p", duration=0), doc("u2", "Unknown 1080p", duration=0),
                doc("u3", "Unknown 480p", duration=0),
                doc("e1", "24 S01E01.mkv", duration=1200), doc("e2", "24 S01E02.mkv", "cloud", duration=2200),
                doc("e3", "24 S01E03.mkv", "archive", duration=0),
                doc("t1", "Only Two 720p"), doc("t2", "Only Two 1080p")]
        await self.insert_files(*docs)
        await api._scan_all_groups()
        self.assertEqual(api.SCAN_STATE["error"], "")
        groups = [group async for group in self.groups.find({})]
        self.assertEqual(len(groups), 3)
        self.assertEqual({(group["group_type"], frozenset(group["members"])) for group in groups},
                         {("quality", frozenset({"q1", "q2", "q3"})),
                          ("quality", frozenset({"t1", "t2"})),
                          ("series", frozenset({"e1", "e2", "e3"}))})
        self.assertTrue(all(group.get("scan_created") for group in groups))
        for fid in ("qd", "u1", "u2", "u3"):
            self.assertNotIn("group_id", await self.cols["primary"].find_one({"_id": fid}))
        await api._scan_all_groups()
        self.assertEqual(api.SCAN_STATE["error"], "")
        self.assertEqual(await self.groups.count_documents({}), 3)

    async def test_existing_groups_accept_only_fully_compatible_live_members(self):
        docs = [doc("q1", "Film 720p", group_id="7", duration=100),
                doc("q2", "Film 1080p", group_id="7", duration=100),
                doc("good", "Film 480p", "cloud", duration=100),
                doc("wrong_time", "Film 4K", duration=101),
                doc("unknown", "Film 360p", duration=0),
                doc("wrong_episode", "Film S01E01 720p", duration=100),
                doc("s1", "North Star S01E01", group_id="8", duration=800),
                doc("s2", "North Star S01E02", group_id="8", duration=900),
                doc("s3", "North Star S01E03", "archive", duration=0),
                doc("missing_old", "Broken Film 720p", group_id="9", duration=100),
                doc("missing_new", "Broken Film 1080p", duration=100)]
        await self.insert_files(*docs)
        await self.groups.insert_many([
            {"_id": "7", "num": 7, "name": "Film", "members": ["q1", "q2"],
             "auto_keys": ["film"], "excluded": [], "group_type": "quality"},
            {"_id": "8", "num": 8, "name": "North Star", "members": ["s1", "s2"],
             "auto_keys": ["north star s01e01", "north star s01e02"], "excluded": [], "group_type": "series"},
            {"_id": "9", "num": 9, "name": "Broken", "members": ["missing_old", "deleted"],
             "auto_keys": ["broken film"], "excluded": [], "group_type": "quality"},
        ])
        candidates = [next(doc for doc in docs if doc["_id"] == fid)
                      for fid in ("good", "wrong_time", "unknown", "wrong_episode", "s3", "missing_new")]
        cards = await api._finalize(api._build_results_list(candidates, "none"), True, siblings=False)
        self.assertEqual(set((await self.groups.find_one({"_id": "7"}))["members"]), {"q1", "q2", "good"})
        self.assertEqual(set((await self.groups.find_one({"_id": "8"}))["members"]), {"s1", "s2", "s3"})
        self.assertEqual((await self.groups.find_one({"_id": "9"}))["members"], ["missing_old", "deleted"])
        self.assertEqual({card["file_id"] for card in cards if not card.get("group")},
                         {"wrong_time", "unknown", "wrong_episode", "missing_new"})
        await api._scan_all_groups()
        self.assertEqual(api.SCAN_STATE["error"], "")
        self.assertEqual(set((await self.groups.find_one({"_id": "7"}))["members"]), {"q1", "q2", "good"})
        self.assertEqual((await self.groups.find_one({"_id": "9"}))["members"], ["missing_old", "deleted"])

    async def test_scan_reports_partial_write_failure_and_retry_repairs_marks(self):
        await self.insert_files(doc("a", "Film 720p"), doc("b", "Film 1080p", "cloud"),
                                doc("c", "Film 480p", "archive"))
        with patch.object(api, "_mark_files", AsyncMock(side_effect=RuntimeError("mark write failed"))):
            await api._scan_all_groups()
        self.assertIn("mark write failed", api.SCAN_STATE["error"])
        self.assertEqual(api.SCAN_STATE["phase"], "error")
        group = await self.groups.find_one({})
        self.assertIsNotNone(group)  # the group insert may already have succeeded
        await api._scan_all_groups()
        self.assertEqual(api.SCAN_STATE["error"], "")
        self.assertEqual(await self.groups.count_documents({}), 1)
        for fid, source in (("a", "primary"), ("b", "cloud"), ("c", "archive")):
            self.assertEqual((await self.cols[source].find_one({"_id": fid}))["group_id"], group["_id"])

    async def test_live_duration_change_and_conflicting_copies_prevent_grouping(self):
        stale = [doc("a", "Film 720p", duration=100), doc("b", "Film 1080p", "cloud", duration=100),
                 doc("c", "Film 480p", "archive", duration=100)]
        await self.insert_files(stale[0], stale[1], doc("c", "Film 480p", "archive", duration=101))
        cards = await api._finalize(api._build_results_list(stale, "none"), True, siblings=False)
        self.assertEqual({v["file_id"] for card in cards if card.get("group") for v in card["variants"]}, {"a", "b"})
        self.assertEqual(next(card for card in cards if card.get("file_id") == "c")["duration"], "1:41")
        await self.groups.delete_many({})
        for col in self.cols.values():
            await col.update_many({}, {"$unset": {"group_id": ""}})
        await self.cols["archive"].update_one({"_id": "c"}, {"$set": {"duration": 100}})
        await self.insert_files(doc("a", "Film 720p", "archive", duration=102))
        cards = await api._finalize(api._build_results_list(stale, "none"), True, siblings=False)
        self.assertEqual({v["file_id"] for card in cards if card.get("group") for v in card["variants"]}, {"b", "c"})
        self.assertTrue(any(card.get("file_id") == "a" for card in cards))
        await api._scan_all_groups()
        self.assertEqual(api.SCAN_STATE["error"], "")
        self.assertEqual(set((await self.groups.find_one({}))["members"]), {"b", "c"})

    async def test_known_runtime_on_another_copy_can_complete_a_quality_group(self):
        rows = [doc("a", "Shared Film 720p", duration=0),
                doc("b", "Shared Film 1080p", "cloud", duration=120),
                doc("c", "Shared Film 480p", "archive", duration=120)]
        await self.insert_files(*rows, doc("a", "Shared Film 720p", "cloud", duration=120))
        cards = await api._finalize(api._build_results_list(rows, "none"), True, siblings=False)
        self.assertEqual(len(cards), 1)
        self.assertEqual((cards[0]["group_type"], cards[0]["duration"]), ("quality", "2:00"))
        self.assertEqual({item["file_id"] for item in cards[0]["variants"]}, {"a", "b", "c"})
        self.assertEqual((await self.cols["primary"].find_one({"_id": "a"}))["group_id"], cards[0]["gid"])
        self.assertEqual((await self.cols["cloud"].find_one({"_id": "a"}))["group_id"], cards[0]["gid"])
        saved = await self.groups.find_one({"_id": cards[0]["gid"]})
        self.assertEqual((await api._group_cards([saved], "none"))[0]["duration"], "2:00")

    async def test_sibling_expansion_groups_matching_files_without_leaking_other_results(self):
        docs = [doc("a", "River Film 720p", duration=100), doc("b", "River Film 1080p", "cloud", duration=100),
                doc("c", "River Film 480p", "archive", duration=100), doc("wrong", "River Film 4K", duration=101)]
        await self.insert_files(*docs)
        with patch.object(api, "_siblings", AsyncMock(return_value=docs)):
            cards = await api._finalize(api._build_results_list([docs[0]], "none"), True, siblings=True)
        self.assertEqual(len(cards), 1)
        self.assertEqual({v["file_id"] for v in cards[0]["variants"]}, {"a", "b", "c"})
        self.assertEqual(cards[0]["duration"], "1:40")
        self.assertNotIn("group_id", await self.cols["primary"].find_one({"_id": "wrong"}))

    async def test_sibling_lookup_accepts_release_tags_between_title_words_and_fails_closed(self):
        class Cursor:
            def __init__(self, rows):
                self.rows = rows
            def limit(self, limit):
                self.rows = self.rows[:limit]
                return self
            async def to_list(self, length):
                return [dict(row) for row in self.rows[:length]]

        class Collection:
            def __init__(self, name, rows, fail=False):
                self.name, self.rows, self.fail, self.query = name, rows, fail, None
            def find(self, query, projection):
                if self.fail:
                    raise RuntimeError("offline")
                self.query = query
                return Cursor([row for row in self.rows if query["file_name"].search(row["file_name"])])

        primary = Collection("Primary", [doc("a", "Film [Uploader] (2024) 720p.mkv"),
                                         doc("wrong", "Film (2023) 720p.mkv")])
        cloud = Collection("Cloud", [doc("b", "Film.2024.1080p.mkv")])
        archive = Collection("Archive", [])
        with patch.object(db, "primary", primary), patch.object(db, "cloud", cloud), patch.object(db, "archive", archive):
            rows = await db.find_phrase_files("film 2024")
            self.assertEqual({row["_id"] for row in rows}, {"a", "b"})
            self.assertIn("$text", primary.query)
            self.assertEqual({row["source_col"] for row in rows}, {"primary", "cloud"})
            primary.rows.append(doc("one", "The One 720p.mkv"))
            self.assertEqual({row["_id"] for row in await db.find_phrase_files("the one")}, {"one"})
            self.assertEqual(primary.query["$text"]["$search"], '"one"')
            await db.find_phrase_files("the")
            self.assertNotIn("$text", primary.query)  # Mongo's English index omits stop words.
            archive.fail = True
            with self.assertRaises(RuntimeError):
                await db.find_phrase_files("film 2024")

    async def test_cross_collection_bypass_offsets_do_not_repeat_or_skip(self):
        for source, count in (("primary", 3), ("cloud", 4), ("archive", 2)):
            await self.insert_files(*(doc(f"{source}{i}", f"Query File {i}", source) for i in range(count)))
        def regex_filter(raw, _regex, lang=None):
            return {"file_name": re.compile(re.escape(raw), re.I)}, False
        expected = [(source, f"{source}{i}") for source, count in (("primary", 3), ("cloud", 4), ("archive", 2))
                    for i in reversed(range(count))]
        collected, offset = [], 0
        with patch.object(db, "build_query_filter", regex_filter):
            for _ in range(10):
                docs, nxt, _, _ = await db.get_search_results("Query", 2, offset=offset,
                                                               collection_type="all", bypass_count=True)
                collected.extend((row["source_col"], row["_id"]) for row in docs)
                if nxt == "":
                    break
                offset = nxt
        self.assertEqual(collected, expected)

    async def test_text_search_exhaustion_does_not_switch_to_regex_midstream(self):
        class Cursor:
            def __init__(self, rows):
                self.rows, self.offset, self.count = rows, 0, len(rows)
            def sort(self, *_args):
                return self
            def skip(self, offset):
                self.offset = offset
                return self
            def limit(self, count):
                self.count = count
                return self
            async def to_list(self, length):
                return [dict(row) for row in self.rows[self.offset:self.offset + min(self.count, length)]]

        class Collection:
            name = "Primary"
            def __init__(self, text_rows, regex_rows):
                self.text_rows, self.regex_rows, self.regex_calls = text_rows, regex_rows, 0
            def find(self, query, _projection):
                if "$text" in query:
                    return Cursor(self.text_rows)
                self.regex_calls += 1
                return Cursor(self.regex_rows)

        regex = re.compile("Example", re.I)
        text = [doc("a", "Example A"), doc("b", "Example B")]
        regex_rows = [doc(str(i), f"Example {i}") for i in range(4)]
        col = Collection(text, regex_rows)
        rows, _ = await db._search(col, "Example", regex, 2, 2, bypass_count=True)
        self.assertEqual(rows, [])
        self.assertEqual(col.regex_calls, 0)
        # A genuinely empty text search still uses the regex stream on every page.
        col = Collection([], regex_rows)
        rows, _ = await db._search(col, "Example", regex, 2, 2, bypass_count=True)
        self.assertEqual([row["_id"] for row in rows], ["2", "3"])
        self.assertEqual(col.regex_calls, 1)

    async def test_single_collection_grouped_only_applies_to_regex_fallback(self):
        await self.db.Primary.insert_many([doc("a", "Example Alpha", group_id="7"), doc("b", "Example Beta")])
        # Make the text stream empty, so the regex fallback is exercised.
        original = self.cols["primary"].find
        class EmptyTextCursor:
            def sort(self, *_args): return self
            def skip(self, *_args): return self
            def limit(self, *_args): return self
            async def to_list(self, **_kwargs): return []
        def find(query, *args, **kwargs):
            if "$text" in query or ("$and" in query and any("$text" in term for term in query["$and"])):
                return EmptyTextCursor()
            return original(query, *args, **kwargs)
        with patch.object(db, "COLLECTIONS", {"primary": self.cols["primary"]}), \
             patch.object(self.cols["primary"], "find", side_effect=find):
            rows, _, _, _ = await db.get_search_results("Example", 10, collection_type="primary",
                                                       grouped_only=True, bypass_count=True)
            self.assertEqual([row["_id"] for row in rows], ["a"])
            rows, _, _, _ = await db.get_search_results("Example", 10, collection_type="primary",
                                                       grouped_only=True, exclude_grouped=True,
                                                       bypass_count=True)
            self.assertEqual([row["_id"] for row in rows], ["b"])

    async def test_cross_collection_text_pages_have_stable_score_tiebreaks(self):
        class Cursor:
            def __init__(self, rows, collection):
                self.rows, self.collection, self.offset, self.count = rows, collection, 0, len(rows)
            def sort(self, spec):
                self.collection.sort_specs.append(spec)
                self.rows = sorted(self.rows, key=lambda row: (row["score"], row["_id"]), reverse=True)
                return self
            def skip(self, offset):
                self.offset = offset
                return self
            def limit(self, count):
                self.count = count
                return self
            async def to_list(self, length):
                return [dict(row) for row in self.rows[self.offset:self.offset + min(self.count, length)]]

        class Collection:
            def __init__(self, name, count):
                self.name, self.sort_specs = name, []
                self.rows = [dict(doc(f"{name}{i}", "Query"), score=1.0) for i in range(count)]
            def find(self, _query, _projection):
                return Cursor(self.rows, self)
            async def count_documents(self, _query):
                return len(self.rows)

        cols = [Collection("Primary", 3), Collection("Cloud", 4), Collection("Archive", 2)]
        expected = [(col.name.lower(), f"{col.name}{i}") for col in cols for i in reversed(range(len(col.rows)))]
        collected, offset = [], 0
        with patch.object(db, "primary", cols[0]), patch.object(db, "cloud", cols[1]), patch.object(db, "archive", cols[2]):
            for _ in range(10):
                rows, nxt, _, _ = await db.get_search_results("Query", 2, offset=offset,
                                                               collection_type="all", bypass_count=True)
                collected.extend((row["source_col"], row["_id"]) for row in rows)
                if not nxt:
                    break
                offset = nxt
        self.assertEqual(collected, expected)
        for col in cols:
            self.assertTrue(col.sort_specs)
            self.assertTrue(all(spec == [("score", {"$meta": "textScore"}), ("_id", -1)]
                                for spec in col.sort_specs))

    async def test_group_and_file_query_plans_are_reused_within_one_page(self):
        # Several batches of the same group's members precede a standalone file.
        members = [f'z{i:02}' for i in range(8)]
        await self.insert_files(*(doc(fid, 'Library grouped', group_id='7') for fid in members),
                                doc('a', 'Library single'))
        await self.groups.insert_one({'_id': '7', 'name': 'Library group', 'members': members})
        group_query = api._group_records_query
        find = self.cols['primary'].find
        text_probes = []

        def counted_find(query, *args, **kwargs):
            if '$text' in query:
                text_probes.append(query)
            return find(query, *args, **kwargs)

        with patch.object(api, '_group_records_query', AsyncMock(wraps=group_query)) as planned, \
             patch.object(self.cols['primary'], 'find', side_effect=counted_find):
            cards, nxt = await api._collection_results_page('Library', 'primary', 0, 2, 'none', False)
        self.assertEqual([card.get('gid') or card.get('file_id') for card in cards], ['7', 'a'])
        self.assertFalse(nxt)
        self.assertEqual(planned.await_count, 1)
        self.assertEqual(len(text_probes), 1)

    async def test_group_only_reads_saved_records_not_file_search(self):
        await self.insert_files(doc('a', 'Other 720p'), doc('b', 'Other 1080p', 'cloud'),
                                doc('c', 'Special 720p'), doc('d', 'Special 1080p'))
        await self.groups.insert_one({'_id':'7', 'name':'Special Collection', 'members':['a','b'], 'group_type':'quality'})
        with patch.object(api, '_ordered_file_page', AsyncMock(side_effect=AssertionError('file search'))), \
             patch.object(api, '_finalize', AsyncMock(side_effect=AssertionError('group write'))):
            response = await self.client.get('/api/search', params={'q':'Special Collection','group':'1','gf':'group'})
            data = await response.json()
            self.assertEqual(response.status, 200, data)
            self.assertEqual([r['gid'] for r in data['results']], ['7'])
        self.assertEqual(await self.groups.count_documents({}), 1)

    async def test_stored_cursor_is_reusable_query_scoped_and_expires(self):
        stream = [doc(f"file{i}", f"Library {i}") for i in range(3)]

        async def raw(_q, limit, offset=0, **_kwargs):
            page = stream[offset:offset + limit]
            return page, (offset + len(page) if offset + len(page) < len(stream) else ""), 0, "All"

        await self.insert_files(*stream)

        params = {"q": "Library", "group": "1", "mode": "none"}
        with patch.object(api, "build_query_filter", lambda raw, regex, lang=None: ({"file_name": regex}, False)), patch.object(api, "MAX_WEB_RESULTS", 1), \
             patch.object(api, "_GROUP_CURSOR_INLINE_LIMIT", 1):
            first = await self.client.get("/api/search", params=params)
            token = (await first.json())["next_offset"]
            self.assertRegex(token, r"^g2_[0-9a-f]{32}$")
            saved = await self.db.GroupSearchCursors.find_one({"_id": token[3:]})
            self.assertIsNotNone(saved)
            self.assertGreater(saved["expires_at"], datetime.utcnow())
            a = await self.client.get("/api/search", params={**params, "offset": token})
            b = await self.client.get("/api/search", params={**params, "offset": token})
            self.assertEqual((await a.json())["results"], (await b.json())["results"])
            wrong = await self.client.get("/api/search", params={**params, "q": "Different", "offset": token})
            self.assertEqual(wrong.status, 400)
            await self.db.GroupSearchCursors.update_one({"_id": token[3:]},
                                                        {"$set": {"expires_at": datetime.utcnow() - timedelta(seconds=1)}})
            expired = await self.client.get("/api/search", params={**params, "offset": token})
            self.assertEqual(expired.status, 400)
            self.assertIn("expired", (await expired.json())["error"].lower())

    async def test_cursor_limits_and_storage_read_failures_are_explicit(self):
        context = api._cursor_context("Library", "all", "all")
        state = {"v": 1, "ctx": context, "groups": [], "gp": 0, "fp": 1, "seen": ["f:one", "f:two"]}
        with patch.object(api, "_GROUP_CURSOR_SEEN_LIMIT", 1):
            with self.assertRaises(api._GroupCursorLimitError):
                await api._encode_group_cursor(state)
        with patch.object(api, "_GROUP_CURSOR_RAW_LIMIT", 1):
            with self.assertRaises(api._GroupCursorLimitError):
                await api._encode_group_cursor(state)
        with patch.object(api.group_search_cursors, "find_one", AsyncMock(side_effect=RuntimeError("offline"))):
            response = await self.client.get("/api/search", params={"q": "Library", "group": "1",
                                                                        "offset": "g2_" + "a" * 32})
        self.assertEqual(response.status, 503)
        self.assertIn("temporarily unavailable", (await response.json())["error"])
        response = await self.client.get("/api/search", params={"q": "Library", "group": "1", "offset": "g1_bad"})
        self.assertEqual(response.status, 400)

    async def test_cursor_ttl_index_is_created(self):
        with patch.object(db, "db", self.db), patch.object(db, "FILE_COLLECTIONS", self.cols), \
             patch.object(db, "actors", self.db.Actors), patch.object(db, "posts", self.db.Posts), \
             patch.object(db, "group_search_cursors", self.db.GroupSearchCursors):
            await db.ensure_indexes()
        indexes = await self.db.GroupSearchCursors.index_information()
        self.assertEqual(indexes["group_search_cursor_ttl"]["expireAfterSeconds"], 0)

    async def test_group_pages_and_cursor_storage_failure(self):
        for i in range(5):
            await self.insert_files(doc(f'a{i}', f'Library {i} A'), doc(f'b{i}', f'Library {i} B', 'cloud'))
            await self.groups.insert_one({'_id':str(i), 'name':f'Library {i}', 'members':[f'a{i}',f'b{i}'], 'updated_at':i})
        params = {'q':'Library', 'group':'1', 'gf':'group'}
        with patch.object(api, 'MAX_WEB_RESULTS', 2), patch.object(api, '_GROUP_CURSOR_INLINE_LIMIT', 1):
            first = await self.client.get('/api/search', params=params)
            data = await first.json()
            self.assertEqual(first.status, 200, data)
            self.assertEqual([r['gid'] for r in data['results']], ['4','3'])
            self.assertTrue(data['next_offset'].startswith('g2_'))
            second = await self.client.get('/api/search', params={**params, 'offset':data['next_offset']})
            self.assertEqual([r['gid'] for r in (await second.json())['results']], ['2','1'])
            with patch.object(api.group_search_cursors, 'insert_one', AsyncMock(side_effect=RuntimeError('offline'))):
                failed = await self.client.get('/api/search', params=params)
            self.assertEqual(failed.status, 503)

    async def test_selective_filter_may_continue_after_an_empty_page(self):
        stream = [doc(f"solo{i:03d}", f"Library {i}") for i in range(192)] + [doc("target", "Library Series")]

        async def raw(_q, limit, offset=0, **_kwargs):
            page = stream[offset:offset + limit]
            return page, (offset + len(page) if offset + len(page) < len(stream) else ""), 0, "All"

        async def finalize(rows, *_args, **_kwargs):
            return [{"group": True, "gid": "42", "group_type": "series", "variants": [row]}
                    if row["file_id"] == "target" else row for row in rows]

        params = {"q": "Library", "group": "1", "gf": "series"}
        with patch.object(api, "_group_hits", AsyncMock(return_value=[])), patch.object(api, "get_search_results", raw), \
             patch.object(api, "_finalize", finalize), patch.object(api, "MAX_WEB_RESULTS", 1):
            first = await self.client.get("/api/search", params=params)
            data = await first.json()
            self.assertEqual(data["results"], [])
            self.assertTrue(data["next_offset"])
            second = await self.client.get("/api/search", params={**params, "offset": data["next_offset"]})
            data = await second.json()
            self.assertEqual([card["gid"] for card in data["results"]], ["42"])
            self.assertFalse(data["next_offset"])

    async def test_all_includes_matching_file_when_its_saved_group_does_not_match(self):
        await self.insert_files(doc('a', 'Festival file', group_id='7'),
                                doc('b', 'Unrelated sibling', 'cloud', group_id='7'),
                                doc('c', 'Festival archive', 'archive'))
        await self.groups.insert_one({'_id':'7', 'name':'Other Collection', 'members':['a','b']})
        with patch.object(api, 'build_query_filter', lambda raw, regex, lang=None: ({'file_name':regex}, False)):
            response = await self.client.get('/api/search', params={'q':'Festival', 'group':'1', 'gf':'all'})
            data = await response.json()
            self.assertEqual(response.status, 200, data)
            self.assertEqual([r['file_id'] for r in data['results']], ['a', 'c'])
            response = await self.client.get('/api/search', params={'q':'Festival', 'group':'1', 'gf':'single', 'col':'archive'})
            self.assertEqual([r['file_id'] for r in (await response.json())['results']], ['c'])
        self.assertEqual(await self.groups.count_documents({}), 1)

    async def test_group_page_batches_member_reads_and_keeps_overlaps(self):
        await self.insert_files(doc('a', 'A'), doc('b', 'B', 'cloud'), doc('c', 'C', 'archive'))
        records = [{'_id':'1', 'name':'One', 'members':['a','b']},
                   {'_id':'2', 'name':'Two', 'members':['b','c']}]
        real_files, real_refresh = api.get_files_by_ids, api._refresh_group_rows
        with patch.object(api, 'get_files_by_ids', AsyncMock(wraps=real_files)) as lookup, \
             patch.object(api, '_refresh_group_rows', AsyncMock(wraps=real_refresh)) as refresh:
            cards = await api._group_cards(records, 'none')
        self.assertEqual([card['gid'] for card in cards], ['1', '2'])
        self.assertEqual([{x['file_id'] for x in c['variants']} for c in cards], [{'a','b'},{'b','c'}])
        self.assertEqual(lookup.await_count, 1)
        self.assertEqual(refresh.await_count, 1)

    async def test_group_only_recent_excludes_singletons_and_unsaved_files(self):
        await self.insert_files(doc('a', 'Saved A'), doc('b', 'Saved B', 'cloud'),
                                doc('c', 'Singleton', group_id='2'), doc('d', 'Unsaved'))
        await self.groups.insert_many([{'_id':'1', 'name':'Saved', 'members':['a','b']},
                                       {'_id':'2', 'name':'Legacy', 'members':['c']}])
        with patch.object(api, '_ordered_file_page', AsyncMock(side_effect=AssertionError('file search'))):
            response = await self.client.get('/api/search', params={'group':'1', 'gf':'group'})
            data = await response.json()
        self.assertEqual(response.status, 200, data)
        self.assertEqual([r['gid'] for r in data['results']], ['1'])
        self.assertEqual(await self.groups.count_documents({}), 2)

    async def test_all_pages_saved_groups_then_standalone_in_source_order(self):
        docs = [doc('a', 'Library A', group_id='7'), doc('b', 'Library B', 'cloud', group_id='7')]
        docs += [doc(f'{src}{i}', 'Library single', src) for src in ('primary','cloud','archive') for i in range(3)]
        await self.insert_files(*docs)
        await self.groups.insert_one({'_id':'7', 'num':7, 'name':'Library Group', 'members':['a','b'], 'group_type':'quality'})
        before = await self.groups.find_one({'_id':'7'})
        with patch.object(api, 'build_query_filter', lambda raw, regex, lang=None: ({'file_name':regex}, False)), \
             patch.object(api, '_finalize', AsyncMock(side_effect=AssertionError('must not create groups'))), \
             patch.object(api, 'MAX_WEB_RESULTS', 2):
            found, offset, first = [], '0', None
            for _ in range(15):
                r = await self.client.get('/api/search', params={'q':'Library','group':'1','offset':offset})
                data = await r.json(); self.assertEqual(r.status, 200, data)
                found.extend(data['results']); offset = data['next_offset']
                if first is None: first = offset
                if not offset: break
            else: self.fail('pagination did not terminate')
            r = await self.client.get('/api/search', params={'q':'Different','group':'1','offset':first})
            self.assertEqual(r.status, 400)
        self.assertEqual(found[0]['gid'], '7')
        self.assertTrue(found[0]['group'])
        expected = [(src, f'{src}{i}') for src in ('primary','cloud','archive') for i in reversed(range(3))]
        self.assertEqual([(x['raw_collection'], x['file_id']) for x in found[1:]], expected)
        self.assertEqual(await self.groups.find_one({'_id':'7'}), before)
        self.assertEqual(await self.groups.count_documents({}), 1)

    async def test_recent_series_filter_paginates_with_small_saved_group(self):
        docs = [doc("old1", "Older Show S01E01", group_id="12"),
                doc("old2", "Older Show S01E02", "cloud", group_id="12"),
                doc("new1", "New Show S01E01", duration=0), doc("new2", "New Show S01E02", duration=0),
                doc("new3", "New Show S01E03", "archive", duration=0),
                doc("alone", "Unrelated", duration=0)]
        await self.insert_files(*docs)
        await self.groups.insert_one({"_id": "12", "num": 12, "name": "Older Show", "group_type": "series",
                                      "members": ["old1", "old2"], "auto_keys": ["older show"], "excluded": []})

        async def siblings(key):
            return [item for item in docs if series_key(item["file_name"]) == key]

        collected, offset = [], "0"
        with patch.object(api, "_siblings", siblings), patch.object(api, "MAX_WEB_RESULTS", 1):
            for _ in range(8):
                response = await self.client.get("/api/search", params={"group": "1", "gf": "series",
                                                                          "mode": "none", "offset": offset})
                data = await response.json()
                self.assertEqual(response.status, 200, data)
                collected.extend(data["results"])
                offset = data["next_offset"]
                if not offset:
                    break
            else:
                self.fail("series cursor did not terminate")
        self.assertEqual(len(collected), 2)
        self.assertTrue(all(card["group_type"] == "series" and not card["duration"] for card in collected))
        self.assertEqual({card["count"] for card in collected}, {2, 3})

    async def test_admin_endpoints_require_admin(self):
        api.get_user_role.return_value = ("user", 9)
        for path in ("/api/group/save", "/api/group/update", "/api/group/remove_file", "/api/group/delete"):
            status, _ = await self.post(path, {})
            self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
