"""One-off admin tool: /repair_library. Remove this file and restart after use.

Works on the existing file collections only. It does not own any helpers used by
indexing, search or streaming, so deleting this plugin won't break those paths.
"""
import asyncio
import logging
import random
import re
import secrets
import time
from dataclasses import dataclass, field

from hydrogram import Client, filters
from hydrogram.errors import BadRequest, FloodWait, MessageNotModified
from hydrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.ia_filterdb import (
    FILE_COLLECTIONS, META_SCHEMA_VERSION, apply_media_meta_update, groups,
    build_meta_migration_query, msg_media,
)
from info import ADMINS, BIN_CHANNEL, LOG_CHANNEL, THUMBNAIL_STORAGE_CHANNEL
from media_probe import probe_telegram_file, should_probe_media
from utils import get_readable_time
from web.search_api import _invalidate_search_caches, thumb_cache

logger = logging.getLogger(__name__)
THUMB_QUERY = {"thumb_url": {"$not": re.compile(r"^TG_ID:"), "$ne": "NO_THUMB"},
               "thumb_source": {"$ne": "web"}}
DELETE_BATCH = 100


@dataclass
class RepairRun:
    token: str = field(default_factory=lambda: secrets.token_hex(6))
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    status: object = None
    total: int = 0
    scanned: int = 0
    meta: int = 0
    probed: int = 0
    thumbs: int = 0
    no_thumb: int = 0
    errors: int = 0
    cleanup_errors: int = 0
    group_errors: int = 0
    started: float = field(default_factory=time.monotonic)


_active_run = None


def _needs_thumb(doc):
    thumb = doc.get("thumb_url")
    return (doc.get("thumb_source") != "web" and thumb != "NO_THUMB"
            and not (isinstance(thumb, str) and thumb.startswith("TG_ID:")))


def _needs_meta(doc):
    meta = doc.get("meta") if isinstance(doc.get("meta"), dict) else {}
    mime = meta.get("mime")
    return ("err" not in meta and
            (meta.get("v") != META_SCHEMA_VERSION or
             (doc.get("file_type") == "document" and isinstance(mime, str)
              and (mime.startswith("video/") or mime.startswith("audio/")))))


def _buttons(run):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Cancel repair", callback_data=f"repair_cancel:{run.token}")]])


def _summary(run, heading):
    return (f"<b>{heading}</b>\n\n"
            f"📂 Scanned: <code>{run.scanned:,}/{run.total:,}</code>\n"
            f"🎬 Metadata updated: <code>{run.meta:,}</code> (probed: <code>{run.probed:,}</code>)\n"
            f"🖼 Thumbnails saved: <code>{run.thumbs:,}</code> (no thumbnail: <code>{run.no_thumb:,}</code>)\n"
            f"⚠️ Errors: <code>{run.errors:,}</code> (group covers: <code>{run.group_errors:,}</code>; cleanup: <code>{run.cleanup_errors:,}</code>)\n"
            f"⏱ Time: <code>{get_readable_time(time.monotonic() - run.started)}</code>")


async def _show(run, text, running=True):
    try:
        await run.status.edit(text, reply_markup=_buttons(run) if running else None)
    except MessageNotModified:
        pass
    except Exception:
        logger.warning("Could not update repair progress", exc_info=True)


async def _pause(run, seconds):
    try:
        await asyncio.wait_for(run.stop.wait(), timeout=seconds)
    except asyncio.TimeoutError:
        pass


async def _flush_messages(client, pending, run):
    while pending:
        batch = pending[:DELETE_BATCH]
        del pending[:DELETE_BATCH]
        try:
            await client.delete_messages(BIN_CHANNEL, batch)
        except FloodWait as exc:
            await asyncio.sleep(exc.value + 1)
            try:
                await client.delete_messages(BIN_CHANNEL, batch)
            except Exception:
                run.cleanup_errors += len(batch)
                logger.warning("Could not clean repair messages", exc_info=True)
        except Exception:
            run.cleanup_errors += len(batch)
            logger.warning("Could not clean repair messages", exc_info=True)


async def _update_thumb(collection, doc, value, run):
    # Recheck at write time: never overwrite a website poster or another
    # process's newly saved thumbnail while this job was contacting Telegram.
    observed_thumb = doc["thumb_url"] if "thumb_url" in doc else {"$exists": False}
    revision = secrets.token_hex(16)
    result = await collection.update_one(
        {"$and": [{"_id": doc["_id"], "thumb_url": observed_thumb}, THUMB_QUERY]},
        {"$set": {**value, "thumb_revision": revision}})
    if result.modified_count:
        try:
            await groups.update_many({"thumb_fid": doc["_id"], "thumb_col": collection.name.lower()},
                                     {"$set": {"thumb_revision": revision}})
        except Exception:
            run.errors += 1
            run.group_errors += 1
            logger.warning("Thumbnail saved but group cover revision failed for %s; refresh group cover manually",
                           doc["_id"], exc_info=True)
        finally:
            thumb_cache.pop(f"{collection.name.lower()}:{doc['_id']}", None)
            _invalidate_search_caches()
    return result


async def _repair_file(client, collection, doc, run, pending):
    need_meta, need_thumb = _needs_meta(doc), _needs_thumb(doc)
    if not need_meta and not need_thumb:
        return
    fid = doc.get("file_ref") or doc.get("file_id") or doc.get("_id")
    if not fid:
        run.errors += 1
        return

    # A flood can occur mid-file. Keep flags so already-saved work is not
    # counted twice and retry this file rather than silently skipping it.
    for attempt in range(4):
        msg = None
        try:
            try:
                msg = await client.send_cached_media(chat_id=BIN_CHANNEL, file_id=fid)
            except BadRequest:
                # BadRequest can also mean a bad destination or missing bot
                # permissions. Do not permanently mark the file as broken.
                run.errors += 1
                logger.warning("Could not fetch cached media for %s", doc.get("_id"), exc_info=True)
                return

            media = msg_media(msg)
            if not media:
                raise RuntimeError("Cached message did not contain media")
            if need_meta:
                probed = {}
                if should_probe_media(media, doc.get("file_name", "")):
                    try:
                        probed = await probe_telegram_file(
                            client, getattr(media, "file_id", None) or fid,
                            file_size=doc.get("file_size", 0) or 0,
                            file_name=str(doc.get("file_name", "")))
                    except FloodWait:
                        raise
                    except Exception:
                        logger.debug("Media probe failed; using Telegram attributes", exc_info=True)
                await apply_media_meta_update(collection, doc["_id"], media,
                                              current_type=doc.get("file_type"), probed=probed or None)
                run.meta += 1
                _invalidate_search_caches()
                if probed.get("w") and probed.get("h"):
                    run.probed += 1
                need_meta = False

            if run.stop.is_set():
                return
            if need_thumb:
                thumbnail_media = getattr(msg, "video", None) or getattr(msg, "document", None)
                thumbs = getattr(thumbnail_media, "thumbs", None) or []
                thumb_id = getattr(thumbs[0], "file_id", None) if thumbs else None
                if not isinstance(thumb_id, str) or len(thumb_id.strip()) <= 20 or "NO_THUMB" in thumb_id:
                    result = await _update_thumb(collection, doc, {"thumb_url": "NO_THUMB"}, run)
                    run.no_thumb += bool(result.modified_count)
                else:
                    buffer = await client.download_media(thumb_id, in_memory=True)
                    if not buffer:
                        raise RuntimeError("Thumbnail download returned no data")
                    try:
                        buffer.seek(0)
                        uploaded = await client.send_photo(chat_id=THUMBNAIL_STORAGE_CHANNEL, photo=buffer)
                    finally:
                        buffer.close()
                    photo = getattr(uploaded, "photo", None)
                    sizes = getattr(photo, "sizes", None) if photo else None
                    new_id = getattr(sizes[-1], "file_id", None) if sizes else getattr(photo, "file_id", None)
                    if not new_id:
                        raise RuntimeError("Thumbnail upload returned no file ID")
                    result = await _update_thumb(collection, doc, {"thumb_url": f"TG_ID:{new_id}", "is_thumb_permanent": True}, run)
                    run.thumbs += bool(result.modified_count)
                need_thumb = False
            return
        except FloodWait as exc:
            if attempt == 3:
                run.errors += 1
                logger.warning("Repair flood wait retries exhausted")
                return
            await _show(run, _summary(run, f"⏳ Telegram rate limit: waiting {exc.value + 10}s"))
            await _pause(run, exc.value + 10)
            if run.stop.is_set():
                return
        except Exception:
            run.errors += 1
            logger.warning("Repair failed for file %s", doc.get("_id"), exc_info=True)
            return
        finally:
            if msg is not None:
                pending.append(msg.id)
                if len(pending) >= DELETE_BATCH:
                    await _flush_messages(client, pending, run)


async def run_repair(client, run):
    query = {"$or": [build_meta_migration_query(), THUMB_QUERY]}
    pending = []
    interrupted = False
    try:
        counts = await asyncio.gather(*(col.count_documents(query) for col in FILE_COLLECTIONS.values()))
        run.total = sum(counts)
        await _show(run, _summary(run, "🔄 Library repair running"))
        for (name, collection), count in zip(FILE_COLLECTIONS.items(), counts):
            if not count or run.stop.is_set():
                continue
            logger.info("Repairing collection %s", name)
            cursor = collection.find(query, {"_id": 1, "file_ref": 1, "file_id": 1, "file_name": 1,
                                             "file_size": 1, "file_type": 1, "meta": 1,
                                             "thumb_url": 1, "thumb_source": 1}).sort("_id", 1)
            try:
                async for doc in cursor:
                    if run.stop.is_set():
                        break
                    run.scanned += 1
                    await _repair_file(client, collection, doc, run, pending)
                    if run.scanned % 10 == 0 or run.scanned == run.total:
                        await _show(run, _summary(run, "🔄 Library repair running"))
                    if not run.stop.is_set():
                        await _pause(run, random.uniform(1.2, 3.0))
            finally:
                await cursor.close()
    except asyncio.CancelledError:
        interrupted = True
        raise
    except Exception:
        interrupted = True
        run.errors += 1
        logger.exception("Library repair stopped unexpectedly")
    finally:
        await _flush_messages(client, pending, run)
        heading = ("🛑 Library repair cancelled" if run.stop.is_set() else
                   "❌ Library repair interrupted" if interrupted else
                   "⚠️ Library repair finished with errors" if run.errors or run.cleanup_errors else
                   "✅ Library repair complete")
        report = _summary(run, heading)
        await _show(run, report, running=False)
        if LOG_CHANNEL:
            try:
                await client.send_message(LOG_CHANNEL, report)
            except Exception:
                logger.warning("Could not send library repair log", exc_info=True)


@Client.on_message(filters.command("repair_library") & filters.user(ADMINS))
async def repair_library_cmd(client, message):
    global _active_run
    if not message.from_user or message.from_user.id not in ADMINS:
        return
    if _active_run is not None:
        return await message.reply("⏳ A library repair is already running.")
    run = _active_run = RepairRun()
    try:
        run.status = await message.reply("⚙️ Starting library repair…", reply_markup=_buttons(run))
        await run_repair(client, run)
    finally:
        if _active_run is run:
            _active_run = None


@Client.on_callback_query(filters.regex(r"^repair_cancel:"))
async def repair_cancel(client, query):
    run = _active_run
    if not query.from_user or query.from_user.id not in ADMINS:
        return await query.answer("❌ Admin only.", show_alert=True)
    if (not run or not run.status or query.data != f"repair_cancel:{run.token}"
            or query.message.chat.id != run.status.chat.id or query.message.id != run.status.id):
        return await query.answer("This repair is no longer running.", show_alert=True)
    run.stop.set()
    await query.answer("🛑 Stopping after the current operation.")
