import io
import os
import gc
import re
import json
import time
import hmac
import hashlib
import zlib
import uuid
import html as _html
import asyncio
import base64
import logging
import urllib.parse
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from functools import wraps
from lru import LRU
from aiohttp import web
from pymongo import ReturnDocument, UpdateMany

# कस्टमाइज्ड कोर यूटिल्स और कन्फर्म कंट्रोल्स इम्पोर्ट्स
from utils import temp, get_size, is_premium, get_duration_str
# ✅ SYNC: THUMBNAIL_STORAGE_CHANNEL को इम्पोर्ट किया गया है पृथक स्टोरेज के लिए
from stream_security import sign_params, STREAM_TTL
from info import BIN_CHANNEL, ADMINS, BOT_TOKEN, MAX_WEB_RESULTS, MAX_THUMB_CACHE, IS_PREMIUM, THUMBNAIL_STORAGE_CHANNEL
# यहाँ db_stats के लिए 'db as filter_db' ऐड किया गया है
from database.ia_filterdb import COLLECTIONS, FILE_COLLECTIONS, groups, group_seq, group_search_cursors, get_files_by_ids, find_phrase_files, search_groups, get_groups_by_ids, get_search_results, get_recent_files, db as filter_db, delete_single_file, build_media_meta, doc_resolution_text, msg_media
from media_probe import probe_telegram_file, should_probe_media
from database.users_chats_db import db
# ✅ SYNC FIX: cookie-session identity check अब यहाँ दोबारा नहीं लिखा, web_assets से reuse हो रहा है
# ✅ DRY: fast_json भी अब web_assets से ही आता है (पहले search_api/actor_routes/
# post_routes तीनों में इसकी अलग-अलग copy थी)।
from web.web_assets import get_auth as web_get_auth, fast_json, DEFAULT_MEDIA_MODE
from web.grouping import (AUTO_QUALITY_MAX, AUTO_SERIES_MAX, GROUP_TYPES,
                          auto_group_plan, duration_seconds, episode_identity, group_type,
                          order_series, quality_title_key, series_key, series_title)

logger = logging.getLogger(__name__)

search_routes = web.RouteTableDef()

# ✅ BUG FIX: यह duplicate function हटाया गया।
# ia_filterdb.py के get_search_results()/_search() पहले से ही raw query से
# strict "word" "word" $text-query बना लेते हैं। यहाँ पहले से quote-wrapped
# string भेजने से get_search_results के अंदर regex fallback (_build_regex)
# को वही quote marks literal characters की तरह मिल जाते थे, जिससे fallback
# regex कभी किसी real filename से match ही नहीं करता था। अब raw `q` सीधे
# get_search_results को भेजा जाता है (नीचे देखें)।

# ─────────────────────────────────────────────────────────
# 📸 TRUE LRU THUMBNAIL STORAGE (C-Based LRU-Dict)
# ─────────────────────────────────────────────────────────
MAX_CACHE = MAX_THUMB_CACHE
thumb_semaphore = asyncio.Semaphore(15)
thumb_cache = LRU(MAX_CACHE)  # ✅ C-लेंग्वेज आधारित सुपरफास्ट कैशे (Size Fixed)
thumb_locks = {}

# KOYEB OPTIMIZATION: Limits reduced to 40 to protect 512MB RAM limits
PREFETCH_CACHE = LRU(40)  
TRENDING_CACHE = LRU(40)  
TRENDING_CACHE_TTL = 300
_SEARCH_CACHE_EPOCH = 0


def _invalidate_search_caches():
    """Invalidate results and prevent in-flight prefetches from restoring old data."""
    global _SEARCH_CACHE_EPOCH
    _SEARCH_CACHE_EPOCH += 1
    PREFETCH_CACHE.clear()
    TRENDING_CACHE.clear()
    _GH_CACHE.clear()
    _SIB_CACHE.clear()

# ─────────────────────────────────────────────────────────
# 📸 OPTIMIZED THUMBNAIL ENGINE (Bytes-in-RAM True LRU)
# ─────────────────────────────────────────────────────────
async def _get_or_fetch_thumb(fid, col_name="primary", is_retry=False, version=""):
    # The requested revision is part of the server cache key too. A new URL
    # therefore cannot be served an old image from another worker's RAM cache.
    cache_key = f"{col_name}:{fid}" + (f":{version[:100]}" if version else "")

    if is_retry:
        if cache_key in thumb_cache and thumb_cache[cache_key] == "NO_THUMB":
            del thumb_cache[cache_key]

    if cache_key in thumb_cache:
        cached_val = thumb_cache[cache_key]
        return None if cached_val == "NO_THUMB" else cached_val

    lock = thumb_locks.setdefault(cache_key, asyncio.Lock())

    try:
        async with lock:
            if cache_key in thumb_cache:
                cached_val = thumb_cache[cache_key]
                return None if cached_val == "NO_THUMB" else cached_val

            async def _fetch():
                target_collection = COLLECTIONS.get(col_name, COLLECTIONS["primary"])
                existing = await target_collection.find_one(
                    {"_id": fid},
                    {"thumb_url": 1, "thumb_revision": 1, "is_thumb_permanent": 1,
                     "duration": 1, "meta": 1, "file_ref": 1, "file_size": 1, "file_name": 1}
                )

                if existing and existing.get("thumb_url", "").startswith("TG_ID:"):
                    saved_thumb_id = existing["thumb_url"].replace("TG_ID:", "")
                    try:
                        file_data = await temp.BOT.download_media(saved_thumb_id, in_memory=True)
                        if file_data:
                            img_bytes = file_data.getvalue()
                            thumb_cache[cache_key] = img_bytes
                            return img_bytes
                    except Exception:
                        pass
                    # A permanent, user-uploaded image must not be silently
                    # replaced with Telegram's original thumbnail on failure.
                    if existing.get("is_thumb_permanent"):
                        return None

                for attempt in range(5):
                    try:
                        msg = await temp.BOT.send_cached_media(chat_id=BIN_CHANNEL, file_id=(existing or {}).get("file_ref") or fid)
                        thumb_id = None

                        # ✅ NEW: purane (duration ke bina index huye) docs ke liye free
                        # backfill — yeh msg hum thumbnail ke liye waise hi bhejte hain,
                        # isliye extra Telegram API call ya DB read nahi lagti. Sirf tab
                        # likhte hain jab doc me duration abhi maujood na ho.
                        await _backfill_duration(target_collection, fid, existing, msg)

                        # ✅ NEW: usi free msg se width/height/mime_type bhi backfill
                        # (meta) — ye fields sirf index ke waqt milte hain, isliye
                        # purani files ke liye yahi ek-matra free mauka hai.
                        await _backfill_media_meta(target_collection, fid, existing, msg)

                        if msg.video and msg.video.thumbs and len(msg.video.thumbs) > 0:
                            thumb_id = msg.video.thumbs[0].file_id
                        elif msg.document and msg.document.thumbs and len(msg.document.thumbs) > 0:
                            thumb_id = msg.document.thumbs[0].file_id

                        if thumb_id:
                            file_data = await temp.BOT.download_media(thumb_id, in_memory=True)
                            if file_data:
                                img_bytes = file_data.getvalue()
                                thumb_cache[cache_key] = img_bytes
                                # A slow original-thumbnail lookup must never overwrite
                                # a new admin upload that completed while it was running.
                                observed_thumb = (existing or {}).get("thumb_url", {"$exists": False})
                                await target_collection.update_one(
                                    {"_id": fid, "thumb_url": observed_thumb, "is_thumb_permanent": {"$ne": True}},
                                    {"$set": {"thumb_url": f"TG_ID:{thumb_id}"}}
                                )
                                await db.add_to_delete_queue(BIN_CHANNEL, msg.id, 5)
                                return img_bytes
                        else:
                            thumb_cache[cache_key] = "NO_THUMB"
                            await db.add_to_delete_queue(BIN_CHANNEL, msg.id, 5)
                            return None

                    except Exception as e:
                        err_text = str(e)
                        if "FLOOD_WAIT" in err_text or "420" in err_text:
                            match = re.search(r'wait of (\d+) second', err_text)
                            wait_time = int(match.group(1)) if match else 20
                            await asyncio.sleep(wait_time + 2)
                            continue
                        await asyncio.sleep(2)
                        continue

                return None

            async with thumb_semaphore:
                return await _fetch()

    finally:
        thumb_locks.pop(cache_key, None)


# ─────────────────────────────────────────────────────────
# 📐 MEDIA META LAZY BACKFILL (purani files ke liye, bina extra API call)
# ─────────────────────────────────────────────────────────
async def _backfill_media_meta(col, fid, existing, msg):
    """Thumbnail msg se width/height/mime_type nikal ke meta me save karta hai (sirf missing ho to).

    Duration backfill ki tarah hi free hai (msg waise bhi fetch hota hai) aur fail
    hone par thumbnail flow ko bilkul nahi rokta. Purani (meta ke bina index huyi)
    files par bhi chalta hai, isliye doc me meta pehle se hai to write skip.

    🔍 Video-ish file ho to asli dims file BYTES se probe hote hain (Telegram ke
    attributes uploader ke likhe hote hain — 1280×720 default wala bug). Probe
    fail ho to attributes likhte hain par `meta.v` NAHI (taaki /migrate_meta ise
    dobara uthakar probe kar sake; migration hamesha v likhta hai, isliye koi
    infinite loop nahi). Probed duration ground-truth hai — attr wali ko correct
    bhi karta hai.
    """
    try:
        if existing and (existing.get("meta") or {}).get("w"):
            return  # pehle se maujood hai, dobara likhne ki zaroorat nahi
        media = msg_media(msg)
        if not media:
            return
        existing = existing or {}
        probed = {}
        needs_probe = should_probe_media(media, existing.get("file_name", ""))
        if needs_probe:
            try:
                fresh_ref = getattr(media, "file_id", None) or existing.get("file_ref")
                if fresh_ref:
                    probed = await probe_telegram_file(
                        temp.BOT, fresh_ref,
                        file_size=existing.get("file_size", 0) or 0,
                        file_name=str(existing.get("file_name", "")),
                    )
            except Exception:
                probed = {}
        meta = build_media_meta(media, probed or None)
        if not (meta["w"] or meta["h"] or meta["mime"]):
            return  # kuch bhi useful nahi mila (documents par width/height 0 hota hai)
        set_payload = {f"meta.{k}": v for k, v in meta.items()}
        if needs_probe and not (probed.get("w") and probed.get("h")):
            # probe nahi ho paya → v mat likho, migration retry karega
            set_payload.pop("meta.v", None)
        else:
            try:
                pdur = int((probed or {}).get("duration") or 0)
            except (TypeError, ValueError):
                pdur = 0
            if pdur > 0:
                set_payload["duration"] = pdur
        await col.update_one({"_id": fid}, {"$set": set_payload})
    except Exception as e:
        logger.debug(f"Media meta backfill skipped for {fid}: {e}")


# ─────────────────────────────────────────────────────────
# ⏱️ DURATION LAZY BACKFILL (purani files ke liye, bina extra API call)
# ─────────────────────────────────────────────────────────
async def _backfill_duration(col, fid, existing, msg):
    """Thumbnail msg se video duration nikalkar DB me save karta hai (sirf agar missing ho).

    Fail hone par thumbnail flow ko bilkul nahi rokta — duration sirf ek cosmetic
    web-UI field hai, iske liye poster serve karna band nahi hona chahiye.
    """
    try:
        if existing and existing.get("duration"):
            return  # pehle se maujood hai, dobara likhne ki zaroorat nahi
        media = msg_media(msg)
        duration = int(getattr(media, "duration", 0) or 0)
        if duration > 0:
            await col.update_one({"_id": fid}, {"$set": {"duration": duration}})
    except Exception as e:
        logger.debug(f"Duration backfill skipped for {fid}: {e}")


# ─────────────────────────────────────────────────────────
# 🔄 BACKGROUND PRE-FETCH WORKER (Controlled Warmup Load)
# ─────────────────────────────────────────────────────────
async def bg_prefetch_worker(tg_id, q, col, mode, prefetch_offset, lim, group=False, gf="all"):
    try:
        gflag = ("g1" + gf) if group else "g0"
        cache_key = f"{tg_id}_{q}_{col}_{mode}_{prefetch_offset}_{gflag}"
        if cache_key in PREFETCH_CACHE:
            return

        epoch = _SEARCH_CACHE_EPOCH
        docs, next_off = await _fetch_page(q, col, prefetch_offset, lim, group, gf)

        if docs and epoch == _SEARCH_CACHE_EPOCH:
            PREFETCH_CACHE[cache_key] = (docs, next_off)
            
            if mode != "none":
                warmup_docs = docs if tg_id in ADMINS else docs[:5]
                for doc in warmup_docs:
                    asyncio.create_task(
                        _get_or_fetch_thumb(doc["_id"], col_name=doc.get("source_col", "primary"), version=_thumb_version(doc))
                    )
                    await asyncio.sleep(0.01) 

    except Exception as e:
        logger.error(f"❌ Prefetch worker execution failed: {e}")


# ─────────────────────────────────────────────────────────
# 🔒 STRICT SECURITY: Telegram initData HMAC Verification
# ─────────────────────────────────────────────────────────
def verify_telegram_init_data(init_data: str) -> dict | None:
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop("hash", None)
        if not received_hash:
            return None
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_hash, received_hash):
            return None
        user_str = parsed.get("user", "{}")
        return json.loads(user_str)
    except Exception:
        return None


# ✅ SYNC FIX: यह छोटा helper दोनों branches (init_data + cookie) में एक जैसा
# admin/premium/IS_PREMIUM-fallback logic apply करता है, ताकि दोनों branch में
# rule अलग-अलग न हो जाए (पहले cookie-branch में IS_PREMIUM fallback मिसिंग था)।
async def _resolve_role_for_tg(tg_id):
    if tg_id in ADMINS: return "admin"
    # ℹ️ सुधार: पहले यहाँ लिखा था कि bot arg required है और is_premium(tg_id) क्रैश
    # करेगा — यह गलत था। utils.py में is_premium(user_id, bot=None) है, bot optional
    # है, इसलिए 1-arg कॉल पहले भी सुरक्षित था। premium.py में एक अलग (dead/unused)
    # is_premium(uid, bot) कॉपी है जो कहीं import ही नहीं होती। यहाँ temp.BOT भेजना
    # सिर्फ इसलिए रखा है ताकि plan expire होने पर user को notify भी मिल जाए
    # (filter.py/commands.py जैसा), यह जरूरी bugfix नहीं बल्कि एक छोटा सुधार है।
    if await is_premium(tg_id, temp.BOT): return "user"
    if not IS_PREMIUM: return "user"
    return None


async def get_user_role(req):
    init_data = req.headers.get("X-Telegram-Init-Data", "").strip()
    if init_data:
        user = verify_telegram_init_data(init_data)
        if user:
            tg_id = int(user.get("id", 0))
            if tg_id:
                role = await _resolve_role_for_tg(tg_id)
                if role: return role, tg_id
        return None, None

    # ✅ DUPLICATION FIX: cookie/session पढ़ने वाला logic अब web_assets.get_auth() से
    # ही आता है (वही function जो /dashboard, /actors, /posts पेज इस्तेमाल करते हैं),
    # यहाँ दोबारा वही कोड नहीं लिखा गया। सिर्फ premium resolution अलग से जोड़ी गई है
    # क्योंकि API endpoints को JSON 403 चाहिए, redirect नहीं।
    role, tg_id = await web_get_auth(req)
    if not role:
        return None, None
    if role == "admin":
        return "admin", tg_id
    resolved = await _resolve_role_for_tg(tg_id)
    return (resolved, tg_id) if resolved else (None, None)


# ─────────────────────────────────────────────────────────
# 🔍 SEARCH API — Smart Pre-fetch Grid Engine (orjson dumps)
# ─────────────────────────────────────────────────────────
def _thumb_version(doc):
    raw = str(doc.get("thumb_url") or "")
    return str(doc.get("thumb_revision") or (f"{zlib.crc32(raw.encode('utf-8')):08x}" if raw.startswith("TG_ID:") else "0"))


def _build_results_list(all_m, mode):
    results_list = []
    for d in all_m:
        fid = d.get("file_ref") or d.get("_id")
        db_id = d.get("_id")
        source_collection_name = d.get("source_col", "primary")

        if mode == "none":
            tg_thumb = ""
            poster_url = ""
        else:
            # Legacy files use a hash; every web upload has a unique revision.
            v_salt = _thumb_version(d)
            tg_thumb = f"/api/thumb?file_id={urllib.parse.quote(str(db_id), safe='')}&col={urllib.parse.quote(str(source_collection_name), safe='')}&v={urllib.parse.quote(str(v_salt), safe='')}"
            poster_url = tg_thumb

        results_list.append({
            "file_id": db_id,
            "name": d.get("file_name", "Unknown File"),
            "size": get_size(d.get("file_size", 0)),
            # ✅ NEW: video duration (e.g. "1:02:03"). Purani/unindexed files me duration
            # 0 hota hai, tab khali string jaati hai aur UI me chip ban hi nahi.
            "duration": get_duration_str(duration_seconds(d)),
            "duration_seconds": duration_seconds(d),
            # ✅ NEW: resolution chip — asli resolution jaisa "1280×720"
            # (koi "720p"/"1080p" guess nahi). meta.w/h se, warna file_name se
            # (purani files) — kuch pata na chale to khali, chip ban hi nahi.
            "res": doc_resolution_text(d),
            "type": d.get("file_type", "document").upper(),
            "source": source_collection_name.capitalize(),
            "raw_collection": source_collection_name,
            "poster": poster_url,
            "tg_thumb": tg_thumb,
            "stream_id": fid,
            "watch": f"/setup_stream?file_id={fid}&mode=watch",
            "download": f"/setup_stream?file_id={fid}&mode=download",
            "caption": d.get("caption", ""),
            # Saved group IDs are also needed in the ungrouped/raw and mini-app views.
            # Group IDs are the same stable numeric strings as the group number.
            "gid": str(d.get("group_id") or ""),
            "group_num": str(d.get("group_id") or ""),
            "group_auto_excluded": bool(d.get("group_auto_excluded")),
        })
    return results_list


# ─────────────────────────────────────────────────────────
# 🗂️ GROUPING — same title's quality versions or an admin-defined series.
# Automatic matching strips resolution/extension, but keeps episode, codec and
# uploader tokens. Saved groups can contain files from all three collections.
# ─────────────────────────────────────────────────────────
_RES_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:(?:240|360|480|540|576|720|1080|1440|2160|4320)\s*[pP]|4[kK]|8[kK]|[uU][hH][dD])(?![A-Za-z0-9])")
_EXT_TAIL_RE = re.compile(
    r"[\s._\-]*(?<![A-Za-z0-9])(?:mp4|mkv|avi|mov|webm|m4v|ts|wmv|flv|mpg|mpeg)\s*$", re.I)
_SEP_RE = re.compile(r"[\s|_\-–.,:;()\[\]{}+~!@#$%^&*=/\\'\"`<>?·•]+")
_DIM_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])(\d{3,4})[x×](\d{3,4})(?![A-Za-z0-9])", re.I)


def _strip_dimensions(name):
    # Keep unrelated numbers (including episode markers); strip only plausible resolutions.
    def replace(match):
        w, h = int(match.group(1)), int(match.group(2))
        return " " if 320 <= w <= 7680 and 200 <= h <= 4320 else match.group(0)
    return _DIM_TOKEN_RE.sub(replace, name)


def _group_key(name):
    """Normalize quality and extension, while retaining season/episode markers."""
    s = _EXT_TAIL_RE.sub("", str(name or ""))
    s = _strip_dimensions(_RES_TOKEN_RE.sub(" ", s)).lower()
    return _SEP_RE.sub(" ", s).strip()


def _group_title(name):
    """Dikhane layak saaf title (original case me), quality + extension hata kar."""
    s = _EXT_TAIL_RE.sub("", str(name or ""))
    s = _strip_dimensions(_RES_TOKEN_RE.sub(" ", s))
    s = re.sub(r"([|\-–_.])(\s*\1)+", r"\1", s)          # '| |' / '..' jaise doble separator
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"^[\s|\-–_.]+|[\s|\-–_.]+$", "", s)
    return s


def _quality_label(res_text, name=""):
    """(label, sort_height). res "1920×1080" se; na ho to naam ke token se; warna ('', 0)."""
    m = re.search(r"(\d{3,5})\D+(\d{3,5})", str(res_text or ""))
    eh = 0
    if m:
        w, h = int(m.group(1)), int(m.group(2))
        eh = max(h, int(w * 9 / 16))          # 1920×800 (scope) bhi 1080p ginta hai
    else:
        t = _RES_TOKEN_RE.search(str(name or "")) or _RES_TOKEN_RE.search(str(res_text or ""))
        if t:
            tok = t.group(0).lower().replace(" ", "")
            eh = {"4k": 2160, "8k": 4320, "uhd": 2160}.get(tok) or int(re.sub(r"\D", "", tok) or 0)
    if not eh:
        return "", 0
    for lim, lab in ((4000, "8K"), (2000, "2160p"), (1300, "1440p"), (1000, "1080p"),
                     (650, "720p"), (450, "480p"), (330, "360p"), (220, "240p")):
        if eh >= lim:
            return lab, eh
    return f"{eh}p", eh


# ── Manual (admin-bane) groups ─────────────────────────────────────────────
# Naam alag hone par jo files auto-group nahi hoti, admin unhe khud ek group me jod sakta hai.
# Ye DB (Groups collection) me save rehta hai, isliye baar-baar grouping nahi karni padti.
# Manual membership hamesha auto-grouping se upar chalti hai.
def _row_id(row):
    return row.get("file_id") or row.get("_id")


def _row_name(row):
    return str(row.get("name") or row.get("file_name") or "")


def _file_auto_keys(name):
    """Include old keys so saved groups remain discoverable without a migration."""
    keys = {_group_key(name), quality_title_key(name)}
    if episode_identity(name):
        keys.add(series_key(name))
    return {key for key in keys if key}


def _stored_auto_keys(group):
    keys = set()
    for value in group.get("auto_keys") or []:
        value = str(value or "")
        if value:
            keys.update((value, quality_title_key(value)))
            if episode_identity(value):
                keys.add(series_key(value))
    if keys:
        # Older keys flattened brackets, making uploader tags impossible to
        # remove afterwards. Stored filenames provide safe aliases; live
        # member metadata is still required before anything can join.
        for item in group.get("files") or []:
            if isinstance(item, dict):
                keys.update(_file_auto_keys(item.get("name") or ""))
    return {key for key in keys if key}


def _join_compatible(group, incoming, members):
    """Fail closed when any live member is missing or incompatible."""
    ids = list(dict.fromkeys(group.get("members") or []))
    if not ids or any(fid not in members for fid in ids):
        return False
    name = _row_name(incoming)
    episode = episode_identity(name)
    if group_type(group) == "series":
        key = series_key(name) if episode else ""
        return bool(key) and all(episode_identity(_row_name(members[fid]))
                                 and series_key(_row_name(members[fid])) == key for fid in ids)
    key, seconds = quality_title_key(name), duration_seconds(incoming)
    return bool(key and seconds) and all(
        quality_title_key(_row_name(members[fid])) == key
        and duration_seconds(members[fid]) == seconds
        and episode_identity(_row_name(members[fid])) == episode for fid in ids)


async def _manual_map(items, joins=None, blocked=None, strict=False):
    """Resolve saved members, then only compatible automatic additions.

    The indexed legacy keys may contain an episode or release suffix. Anchored
    first-word lookups find those old documents; all candidates are checked
    against *every* live member before an optimistic association is returned.
    """
    rows = []
    for item in items:
        if isinstance(item, dict):
            row = item
        else:  # Older internal callers may supply (file_id, name).
            row = {"file_id": item[0], "name": item[1]}
        if _row_id(row):
            rows.append(row)
    out = {}
    if not rows:
        return out
    ids = {_row_id(row) for row in rows}
    keys = set().union(*(_file_auto_keys(_row_name(row)) for row in rows))
    # Existing auto_keys were built from full filenames. Match title words even
    # when legacy release words appear between them ("show web dl name").
    def legacy_prefix(key):
        words = key.split()[:12]
        if not words or len(words[0]) < 2:
            return None
        # Independent lookaheads avoid pathological backtracking on long or
        # attacker-controlled filenames. Compatibility is checked afterwards.
        return re.compile("^" + re.escape(words[0]) + r"(?=\s|$)" + "".join(
            r"(?=.*\s" + re.escape(word) + r"(?=\s|$))" for word in words[1:]))
    prefixes = {pattern for key in keys if (pattern := legacy_prefix(key))}
    try:
        cond = [{"members": {"$in": list(ids)}}]
        if keys:
            cond.append({"auto_keys": {"$in": list(keys | prefixes)}})
        found = [g async for g in groups.find({"$or": cond})]
        by_key = defaultdict(list)
        for group in found:
            for key in _stored_auto_keys(group):
                by_key[key].append(group)
            for fid in group.get("members") or []:
                if fid in ids:
                    out[fid] = group
        candidates = [row for row in rows if _row_id(row) not in out]
        if not candidates or not by_key:
            return out
        candidate_keys = set().union(*(_file_auto_keys(_row_name(row)) for row in candidates))
        relevant = {str(group["_id"]): group for key in candidate_keys for group in by_key.get(key, [])}
        if not relevant:
            return out
        member_ids = {fid for group in relevant.values() for fid in (group.get("members") or [])}
        live, exclusions = await _live_group_files(member_ids | {_row_id(row) for row in candidates})
        if blocked is not None:
            blocked.update(exclusions)
        for row in candidates:
            fid = _row_id(row)
            if fid not in live or fid in exclusions or (blocked is not None and fid in blocked):
                continue
            matches, seen = [], set()
            for key in _file_auto_keys(_row_name(live[fid])):
                for group in by_key.get(key, []):
                    gid = str(group["_id"])
                    if gid not in seen:
                        seen.add(gid)
                        matches.append(group)
            # A deliberate removal wins even if another group shares this key.
            if any(fid in (group.get("excluded") or []) for group in matches):
                if blocked is not None:
                    blocked.add(fid)
                continue
            matches.sort(key=lambda group: (group_type(group) != "series", str(group["_id"])))
            for group in matches:
                if _join_compatible(group, live[fid], live):
                    out[fid] = group
                    if joins is not None:
                        joins.append((str(group["_id"]), fid, _row_name(live[fid])))
                    break
    except Exception as e:
        logger.warning(f"manual group lookup failed: {e}")
        if strict:
            raise
    return out


def group_results(results, manual=None, blocked=None):
    """Build cards without mutating inputs; a group card needs two visible files."""
    manual = manual or {}
    blocked = set(blocked or ())
    rows, seen = [], set()
    for row in results:
        fid = _row_id(row)
        if row.get("group_auto_excluded") and fid:
            blocked.add(fid)
        if fid and fid in seen:
            continue  # multiple collections can contain the same Telegram file
        if fid:
            seen.add(fid)
        rows.append(row)

    plans = auto_group_plan([row for row in rows if _row_id(row) not in manual], blocked)
    automatic = {}
    for index, plan in enumerate(plans):
        for fid, _ in plan["items"]:
            automatic[fid] = index
    order, buckets = [], {}
    for row in rows:
        fid = _row_id(row)
        if fid in manual:
            key = ("saved", str(manual[fid]["_id"]))
        elif fid in automatic:
            key = ("auto", automatic[fid])
        else:
            order.append(("single", row))
            continue
        if key not in buckets:
            buckets[key] = []
            order.append(("group", key))
        buckets[key].append(row)

    out = []
    for kind, bucket in order:
        if kind == "single":
            out.append(bucket)
            continue
        items = buckets[bucket]
        # A legacy singleton, or a group with only one retrievable member, is a
        # file card, not a group. Keep its stored metadata for possible repair.
        if len(items) < 2:
            out.extend(dict(item, gid="", group_num="", group_type="") for item in items)
            continue
        mg = manual.get(_row_id(items[0])) if bucket[0] == "saved" else None
        plan = plans[bucket[1]] if not mg else None
        gid = str(mg["_id"]) if mg else ""
        num = (mg.get("num") or gid) if mg else ""
        gtype = group_type(mg) if mg else plan["kind"]
        variants = []
        for it in items:
            lab, height = _quality_label(it.get("res"), it.get("name"))
            variants.append((height, dict(it, ql=lab, gid=gid, group_num=num, group_type=gtype)))
        if gtype == "series":
            vlist = order_series([d for _, d in variants], mg)
        else:
            variants.sort(key=lambda x: x[0])
            vlist = [d for _, d in variants]
            # Preserve saved series labels/order if an admin switches back later.
            if mg:
                series_info = {d["file_id"]: d for d in order_series(vlist, mg)}
                for item in vlist:
                    info = series_info[item["file_id"]]
                    for field in ("episode_label", "episode_custom_label", "episode_detected_label", "episode_position"):
                        item[field] = info.get(field)

        chips, seen = [], {}
        if gtype == "quality":
            for d in vlist:
                lab = d["ql"] or "Unknown"
                if lab in seen:
                    seen[lab]["count"] += 1
                else:
                    seen[lab] = {"label": lab, "count": 1}
                    chips.append(seen[lab])

        # A series uses its first episode as the default poster, not the highest resolution.
        choices = vlist if gtype == "series" else list(reversed(vlist))
        rep = choices[0]
        thumb = next((d.get("tg_thumb") for d in choices if d.get("tg_thumb")), "")
        if mg and thumb:
            revision = urllib.parse.quote(str(mg.get("thumb_revision") or mg.get("updated_at") or 0), safe="")
            if mg.get("thumb_url"):
                thumb = f"/api/group/thumb?gid={urllib.parse.quote(gid, safe='')}&v={revision}"
            elif mg.get("thumb_fid") and mg.get("thumb_col"):
                thumb = f"/api/thumb?file_id={urllib.parse.quote(str(mg['thumb_fid']), safe='')}&col={urllib.parse.quote(str(mg['thumb_col']), safe='')}&v={revision}"
        if mg:
            title = _html.escape(str(mg.get("name") or ""))
            key = "m" + gid
        else:
            name = _row_name(items[0])
            title = _html.escape((series_title(name) if gtype == "series" else _group_title(name)) or name)
            identity = (gtype, plan["key"], plan.get("seconds", 0), plan.get("episode", ""))
            key = f"{zlib.crc32(repr(identity).encode('utf-8')):08x}"
        runtimes = [duration_seconds(item) for item in vlist if duration_seconds(item)]
        common_duration = Counter(runtimes).most_common(1)[0][0] if runtimes else 0
        out.append({
            "group": True,
            "group_type": gtype,
            "manual": bool(mg),
            "gid": gid,
            "nkey": "" if mg else plan["key"],
            "num": num,
            "custom_thumb": bool(mg and mg.get("thumb_url")),
            "key": key,
            "title": title,
            "count": len(vlist),
            # Repeated quality copies of one explicitly marked episode count as
            # one episode; files without a marker remain individually countable.
            "episode_count": len({("episode", episode_identity(item.get("name")))
                                  if episode_identity(item.get("name")) else ("file", item.get("file_id"))
                                  for item in vlist}) if gtype == "series" else None,
            "type": rep.get("type", "VIDEO"),
            "tg_thumb": thumb,
            "thumb_fid": (mg.get("thumb_fid") or "") if mg else "",
            "duration": get_duration_str(common_duration) if gtype == "quality" else "",
            "size": rep.get("size", ""),
            "source": rep.get("raw_collection", "primary"),
            "sources": [c for c in ("primary", "cloud", "archive")
                        if any(d.get("raw_collection") == c for d in vlist)],
            "chips": chips,
            "variants": vlist,
        })
    return out


# ── 📄 Page fetch: "21 CARDS" per page ──────────────────────────────────────
# Pehle 21 *files* aati thi aur grouping ke baad 5-6 card bachte the. Ab group=1 me
# itni files uthayi jaati hain ki poore `lim` (21) CARDS ban jaayein. Offset hamesha
# raw-file position hai, isliye pagination me na koi file repeat hoti hai na chhutti hai.
async def _fetch_page(q, col, off, lim, group, gf="all", exclude_grouped=False):
    """Fetch raw files or enough buckets for a page of grouped cards.

    gf is all, group, quality, series, or single. A saved one-file group still
    counts as a group so its settings remain accessible.
    """
    async def raw_fetch(o, n):
        if not q:
            return await get_recent_files(n, offset=o, collection_type=col)
        docs, nxt, _, _ = await get_search_results(
            q, n, offset=o, collection_type=col, bypass_count=True, exclude_grouped=exclude_grouped)
        return docs, nxt

    if not group:
        return await raw_fetch(off, lim)

    batch = max(lim * 4, 4)
    hops_max = 4 if gf == "all" else 12
    raw, cur, more, manual, blocked = [], off, True, {}, set()

    def selected(card):
        if gf == "group":
            return bool(card.get("group"))
        if gf in ("quality", "series"):
            return bool(card.get("group")) and card.get("group_type") == gf
        if gf == "single":
            return not card.get("group")
        return True

    for _hop in range(hops_max):
        docs, nxt = await raw_fetch(cur, batch)
        if not docs:
            more = False
            break
        raw.extend(docs)
        blocked.update(d.get("_id") for d in docs if d.get("group_auto_excluded"))
        manual.update(await _manual_map(docs, blocked=blocked))
        more = bool(nxt)
        cur = nxt if more else None
        cards = group_results(_build_results_list(raw, "none"), manual, blocked)
        ids_by_card = [[v.get("file_id") for v in card["variants"]] if card.get("group")
                       else [card.get("file_id")] for card in cards]
        card_for_id = {fid: index for index, ids in enumerate(ids_by_card) for fid in ids}
        accepted = [index for index, card in enumerate(cards) if selected(card)]
        if len(accepted) > lim:
            omitted = accepted[lim]
            cut = next(i for i, doc in enumerate(raw) if card_for_id.get(doc.get("_id")) == omitted)
            chosen = set(accepted[:lim])
            # Keep all known members of a selected auto bucket even when its
            # remaining rows occur after the page boundary.
            return [doc for i, doc in enumerate(raw)
                    if card_for_id.get(doc.get("_id")) in chosen
                    and (i < cut or cards[card_for_id[doc["_id"]]].get("group"))], off + cut
        if not more:
            break

    cards = group_results(_build_results_list(raw, "none"), manual, blocked)
    allowed = {v.get("file_id") for card in cards if selected(card)
               for v in (card.get("variants") if card.get("group") else [card])}
    return [doc for doc in raw if doc.get("_id") in allowed], (off + len(raw) if more else "")


GROUP_RESCAN_SECS = 6 * 3600     # saved group ko itni der me ek baar hi naye saathi ke liye scan karte hain


async def _mark_files(ids, gid, expected_gid=None, suppress_auto=False, strict=False, only_unassigned=False):
    """Mark members or unmark them without accidentally clearing another group."""
    ids = [i for i in ids if i]
    if not ids:
        return
    if gid:
        upd = {"$set": {"group_id": str(gid)}, "$unset": {"group_auto_excluded": ""}}
    else:
        upd = {"$unset": {"group_id": ""}}
        if suppress_auto:
            upd["$set"] = {"group_auto_excluded": True}
    flt = {"_id": {"$in": ids}}
    if expected_gid is not None:
        if suppress_auto:
            flt["$or"] = [{"group_id": str(expected_gid)}, {"group_id": {"$exists": False}}]
        else:
            flt["group_id"] = str(expected_gid)
    elif only_unassigned and gid:
        flt["$or"] = [{"group_id": str(gid)}, {"group_id": {"$exists": False}}]
        flt["group_auto_excluded"] = {"$ne": True}
    failures = []
    for col in FILE_COLLECTIONS.values():
        try:
            await col.update_many(flt, upd)
        except Exception as e:
            logger.warning(f"mark group_id failed ({col.name}): {e}")
            failures.append(col.name)
    if strict and failures:
        raise RuntimeError("Could not update group marks in: " + ", ".join(failures))


async def _live_group_files(ids):
    """Strictly re-read canonical names, durations and exclusions from all copies.

    The first collection supplies the name. A known runtime on another copy can
    fill an unknown one, but conflicting positive runtimes are treated as unknown
    so they cannot accidentally create or join a quality group.
    """
    ids = list(dict.fromkeys(i for i in ids if i))
    rows, runtimes, blocked = {}, defaultdict(set), set()
    for start in range(0, len(ids), 1000):
        batch = ids[start:start + 1000]
        for col in FILE_COLLECTIONS.values():
            projection = {"file_name": 1, "duration": 1, "duration_seconds": 1, "group_auto_excluded": 1}
            async for doc in col.find({"_id": {"$in": batch}}, projection):
                fid = doc["_id"]
                rows.setdefault(fid, {"_id": fid, "file_name": str(doc.get("file_name") or "")})
                seconds = duration_seconds(doc)
                if seconds:
                    runtimes[fid].add(seconds)
                if doc.get("group_auto_excluded"):
                    blocked.add(fid)
    for fid, row in rows.items():
        values = runtimes[fid]
        row["duration_seconds"] = next(iter(values)) if len(values) == 1 else 0
        row["duration"] = row["duration_seconds"]
    return rows, blocked


async def _persist_joins(joins, strict=False):
    """Serialize automatic joins with administrative membership changes."""
    async with _AUTO_GROUP_LOCK:
        return await _persist_joins_locked(joins, strict=strict)


async def _persist_joins_locked(joins, strict=False):
    """Recheck ownership, exclusions, filenames and all member metadata at write time."""
    accepted, blocked = set(), set()
    try:
        by = {}
        for gid, fid, name in joins:
            by.setdefault(str(gid), {})[fid] = name
        fresh, blocked = await _live_group_files({fid for candidates in by.values() for fid in candidates})
        for gid, candidates in by.items():
            group = await groups.find_one({"_id": gid})
            if not group:
                continue
            member_meta, _ = await _live_group_files(group.get("members") or [])
            claimed = set()
            async for other in groups.find({"_id": {"$ne": gid}, "members": {"$in": list(candidates)}}, {"members": 1}):
                claimed.update(other.get("members") or [])
            excluded = set(group.get("excluded") or [])
            blocked.update(fid for fid in candidates if fid in excluded)
            keys = _stored_auto_keys(group)
            items = {fid: row for fid, row in fresh.items() if fid in candidates and fid not in blocked
                     and fid not in excluded and fid not in claimed
                     and keys.intersection(_file_auto_keys(_row_name(row)))
                     and _join_compatible(group, row, member_meta)}
            if not items:
                continue
            ids = list(items)
            # The exact member list, type and keys guard against edits by another
            # worker between our read and write as well as against exclusions.
            flt = {"_id": gid, "members": group.get("members", []), "excluded": {"$nin": ids}}
            for field in ("group_type", "auto_keys"):
                flt[field] = group[field] if field in group else {"$exists": False}
            added_keys = set().union(*(_file_auto_keys(_row_name(row)) for row in items.values()))
            result = await groups.update_one(flt, {"$addToSet": {
                "members": {"$each": ids},
                "files": {"$each": [{"id": fid, "name": _row_name(row)} for fid, row in items.items()]},
                "auto_keys": {"$each": sorted(added_keys)}}})
            if result.matched_count:
                accepted.update((gid, fid) for fid in ids)
                await _mark_files(ids, gid, only_unassigned=True, strict=strict)
                logger.info(f"🗂️ Group #{gid}: {len(ids)} new file(s) added")
        if accepted:
            _GH_CACHE.clear()
    except Exception as e:
        logger.warning(f"persist group joins failed: {e}")
        if strict:
            raise
    return accepted, blocked


async def _confirm_joined_members(manual, joins, accepted):
    """Do not show an optimistic join if it failed the live write-side checks."""
    rejected = {i for gid, i, _ in joins if (gid, i) not in accepted}
    for i in rejected:
        manual.pop(i, None)
    if not rejected:
        return
    try:
        async for g in groups.find({"members": {"$in": list(rejected)}}):
            for i in g.get("members") or []:
                if i in rejected:
                    manual[i] = g
    except Exception as e:
        logger.warning(f"group membership recheck failed: {e}")


async def _mark_scanned(gids):
    try:
        await groups.update_many({"_id": {"$in": list(gids)}}, {"$set": {"scanned_at": int(time.time())}})
    except Exception as e:
        logger.warning(f"mark scanned failed: {e}")


# Search requests for the same new group can overlap (including prefetches).
# Serialize creation in this process, re-checking membership inside the lock.
_AUTO_GROUP_LOCK = asyncio.Lock()


def _serialize_group_writes(handler):
    """Keep group edits and automatic membership writes ordered in this process."""
    @wraps(handler)
    async def wrapped(req):
        async with _AUTO_GROUP_LOCK:
            return await handler(req)
    return wrapped


async def _auto_persist(cards, scan=False):
    """Revalidate and save automatic groups before returning their real IDs.

    An unavailable database leaves a usable, unnumbered virtual card; a changed
    filename or runtime is instead reflected in the response and re-partitioned.
    """
    resolved, blocked, fresh = {}, set(), {}
    stats = {"created": 0, "added": 0}
    async with _AUTO_GROUP_LOCK:
        ids = list(dict.fromkeys(v["file_id"] for card in cards
                                 for v in card.get("variants", []) if v.get("file_id")))
        try:
            fresh, blocked = await _live_group_files(ids)
            blocked.update(fid for fid in ids if fid not in fresh)
            joins = []
            resolved = await _manual_map([fresh[fid] for fid in ids if fid in fresh], joins, blocked, strict=True)
            if joins:
                accepted, excluded = await _persist_joins_locked(joins, strict=scan)
                blocked.update(excluded)
                stats["added"] = len(accepted)
                await _confirm_joined_members(resolved, joins, accepted)

            # Membership can change after a search snapshot. Never make a second
            # group for a file that an admin or another request has already claimed.
            for start in range(0, len(ids), 1000):
                async for group in groups.find({"members": {"$in": ids[start:start + 1000]}}):
                    for fid in group.get("members") or []:
                        if fid in fresh:
                            resolved[fid] = group

            remaining = [fresh[fid] for fid in ids if fid in fresh and fid not in resolved and fid not in blocked]
            for plan in auto_group_plan(remaining, blocked):
                entries = plan["items"]
                member_ids = [fid for fid, _ in entries]
                name = _row_name(entries[0][1])
                title = series_title(name) if plan["kind"] == "series" else _group_title(name)
                num = await _next_group_num()
                gid, now = str(num), int(time.time())
                keys = set().union(*(_file_auto_keys(_row_name(row)) for _, row in entries))
                group = {
                    "_id": gid, "num": num, "name": (title or name)[:200],
                    "members": member_ids, "files": [{"id": fid, "name": _row_name(row)} for fid, row in entries],
                    "auto_keys": sorted(keys), "excluded": [], "auto_created": True,
                    "group_type": plan["kind"], "thumb_fid": "", "thumb_col": "", "thumb_url": "",
                    "scanned_at": now, "created_at": now, "updated_at": now,
                }
                if scan:
                    group["scan_created"] = True
                await groups.insert_one(group)
                await _mark_files(member_ids, gid, only_unassigned=True, strict=scan)
                resolved.update({fid: group for fid in member_ids})
                stats["created"] += 1
                logger.info(f"🗂️ Auto {plan['kind']} group #{gid} saved ({len(member_ids)} files)")
            if stats["created"] or stats["added"]:
                _GH_CACHE.clear()
        except Exception as e:
            logger.warning(f"auto group persist failed: {e}")
            if scan:
                raise
    return resolved, blocked, fresh, stats


_SIB_CACHE = {}
_SIB_TTL = 300


async def _siblings(key):
    """Find bounded title/series candidates independently of the search query."""
    now = time.time()
    cached = _SIB_CACHE.get(key)
    if cached and cached[0] > now:
        return cached[1]
    epoch = _SEARCH_CACHE_EPOCH
    try:
        docs = await asyncio.wait_for(find_phrase_files(key, AUTO_SERIES_MAX + 1), timeout=4)
    except Exception as e:
        logger.warning(f"siblings lookup failed for '{key}': {e}")
        return None
    docs = [doc for doc in docs if quality_title_key(doc.get("file_name")) == key
            or (episode_identity(doc.get("file_name")) and series_key(doc.get("file_name")) == key)]
    if epoch == _SEARCH_CACHE_EPOCH:
        if len(_SIB_CACHE) > 800:
            _SIB_CACHE.clear()
        _SIB_CACHE[key] = (now + _SIB_TTL, docs)
    return docs


async def _expand_groups(results_list, manual, mode, joins=None, siblings=True, blocked=None):
    """Expand saved members and find compatible title/episode siblings."""
    have = {row.get("file_id") for row in results_list}
    results_list = list(results_list)
    need, seen_groups = [], set()
    for group in list(manual.values()):
        if group["_id"] in seen_groups:
            continue
        seen_groups.add(group["_id"])
        for fid in group.get("members") or []:
            if fid not in have:
                need.append((fid, group))
    if need:
        try:
            docs = await get_files_by_ids([fid for fid, _ in need])
            owner = {fid: group for fid, group in need}
            extra = _build_results_list(docs, mode)
            for row in extra:
                manual[row["file_id"]] = owner[row["file_id"]]
                have.add(row["file_id"])
            results_list += extra
        except Exception as e:
            logger.warning(f"group expand failed: {e}")

    if not siblings:
        return results_list
    try:
        joins = joins if joins is not None else []
        now = time.time()
        targets, key_groups = set(), defaultdict(set)
        for row in results_list:
            fid, name = row.get("file_id"), _row_name(row)
            group = manual.get(fid)
            if group and ((group.get("scanned_at") or 0) + GROUP_RESCAN_SECS > now
                          or not group.get("auto_keys")):
                continue
            if not group and blocked and fid in blocked:
                continue
            if not episode_identity(name) and not duration_seconds(row):
                continue  # an unknown-runtime movie cannot form a safe auto group
            keys = {quality_title_key(name)}
            if episode_identity(name):
                keys.add(series_key(name))
            keys.discard("")
            targets.update(keys)
            if group:
                key_groups[group["_id"]].update(keys)
        keys = sorted(targets)[:40]
        if keys:
            sibling_rows = await asyncio.gather(*[_siblings(key) for key in keys])
            sib_of = dict(zip(keys, sibling_rows))
            candidates = {}
            for docs in sibling_rows:
                for doc in docs or []:
                    fid = doc["_id"]
                    if blocked is not None and doc.get("group_auto_excluded"):
                        blocked.add(fid)
                    if fid not in have:
                        candidates.setdefault(fid, doc)
            if candidates:
                possible_joins = []
                owners = await _manual_map(list(candidates.values()), possible_joins, blocked)
                use = []
                for fid, doc in candidates.items():
                    if blocked and fid in blocked:
                        continue
                    owner = owners.get(fid)
                    if owner and owner["_id"] not in seen_groups:
                        continue  # Do not pull another saved group into this result.
                    if owner:
                        manual[fid] = owner
                    use.append(doc)
                used = {doc["_id"] for doc in use}
                joins.extend(join for join in possible_joins if join[1] in used)
                results_list += _build_results_list(use, mode)
            done = [gid for gid, wanted in key_groups.items()
                    if wanted and all(key in sib_of and sib_of[key] is not None for key in wanted)]
            if done:
                asyncio.create_task(_mark_scanned(done))
                for group in manual.values():
                    if group["_id"] in done:
                        group["scanned_at"] = int(now)
    except Exception as e:
        logger.warning(f"sibling expand failed: {e}")
    return results_list


async def _annotate_raw_groups(results_list):
    """Expose authoritative saved membership on raw cards, including legacy unmarked files."""
    ids = [r.get("file_id") for r in results_list if r.get("file_id")]
    if not ids:
        return results_list
    try:
        owners, wanted = {}, set(ids)
        async for g in groups.find({"members": {"$in": ids}},
                                   {"members": 1, "num": 1, "group_type": 1}):
            if len(set(g.get("members") or [])) < 2:
                continue
            for fid in g.get("members") or []:
                if fid in wanted:
                    owners[fid] = g
        out = []
        for r in results_list:
            g = owners.get(r.get("file_id"))
            gid = str(g["_id"]) if g else ""
            out.append(dict(r, gid=gid, group_num=(g.get("num") or gid) if g else "",
                            group_type=group_type(g) if g else ""))
        return out
    except Exception as e:
        logger.warning(f"raw group lookup failed: {e}")
        return results_list  # Keep any file-level marks when MongoDB is unavailable.


async def _refresh_group_rows(rows, blocked, ids):
    """Use the same cross-collection metadata as the write-side safety check."""
    ids = {fid for fid in ids if fid}
    if not ids:
        return rows, set()
    try:
        fresh, exclusions = await _live_group_files(ids)
        blocked.update(exclusions)
        updated = [dict(row, name=_row_name(fresh[row["file_id"]]),
                        duration_seconds=duration_seconds(fresh[row["file_id"]]),
                        duration=get_duration_str(duration_seconds(fresh[row["file_id"]])))
                   if row.get("file_id") in fresh else row for row in rows]
        return updated, set(fresh)
    except Exception as exc:
        logger.warning(f"group metadata lookup failed: {exc}")
        return rows, set()


async def _finalize(results_list, want_group, gf="all", mode=DEFAULT_MEDIA_MODE, siblings=True):
    if not want_group:
        return await _annotate_raw_groups(results_list)
    anchors = {row.get("file_id") for row in results_list if row.get("file_id")}
    joins = []
    blocked = {row.get("file_id") for row in results_list if row.get("group_auto_excluded")}
    results_list, checked = await _refresh_group_rows(results_list, blocked, anchors)
    manual = await _manual_map(results_list, joins, blocked)
    results_list = await _expand_groups(results_list, manual, mode, joins, siblings, blocked)
    added_ids = {row.get("file_id") for row in results_list} - checked
    results_list, _ = await _refresh_group_rows(results_list, blocked, added_ids)
    if joins:
        accepted, excluded = await _persist_joins(joins)
        blocked.update(excluded)
        await _confirm_joined_members(manual, joins, accepted)
    out = group_results(results_list, manual, blocked)
    autos = [row for row in out if row.get("group") and not row.get("manual")]
    if autos:
        saved, newly_blocked, fresh, _ = await _auto_persist(autos)
        manual.update(saved)
        blocked.update(newly_blocked)
        if fresh:
            # Do not show a group based on a stale filename or runtime.
            results_list = [dict(row, name=_row_name(fresh[row["file_id"]]),
                                 duration_seconds=duration_seconds(fresh[row["file_id"]]),
                                 duration=get_duration_str(duration_seconds(fresh[row["file_id"]])))
                            if row.get("file_id") in fresh else row for row in results_list]
        results_list = await _expand_groups(results_list, manual, mode, siblings=False, blocked=blocked)
        out = group_results(results_list, manual, blocked)
    # Sibling lookups provide context, not unrelated additional search results.
    out = [row for row in out if (any(v.get("file_id") in anchors for v in row.get("variants", []))
                                  if row.get("group") else row.get("file_id") in anchors)]
    if gf == "group":
        out = [row for row in out if row.get("group")]
    elif gf in ("quality", "series"):
        out = [row for row in out if row.get("group") and row.get("group_type") == gf]
    elif gf == "single":
        out = [row for row in out if not row.get("group")]
    return out


# ── 🗂️ GROUP-FIRST SEARCH ────────────────────────────────────────────────
# Pehle QualityGroups me search (poore group, teeno collections ki files ke saath),
# phir primary → cloud → archive me sirf wahi files jo kisi group me NAHI hain (group_id nahi).
# Offset ek hi line me chalta hai: [group matches ...][ungrouped files ...]
_GH_CACHE = {}
_GH_TTL = 60


async def _group_hits(q):
    """Query se jude groups: (1) group ke naam/files ke naam se, (2) jinki kisi member file ka
    naam YA CAPTION query se match kare (file-search jaisa hi filter). None = fail (purana tareeka)."""
    key = q.lower()
    c = _GH_CACHE.get(key)
    now = time.time()
    if c and c[0] > now:
        return c[1]
    epoch = _SEARCH_CACHE_EPOCH
    gs = await search_groups(q)
    if gs is None:
        return None
    gs = list(gs)
    try:
        have = {g["_id"] for g in gs}
        docs, _, _, _ = await get_search_results(q, 600, offset=0, collection_type="all",
                                                 bypass_count=True, grouped_only=True)
        gids = []
        for d in docs:
            gid = d.get("group_id")
            if gid and gid not in have and gid not in gids:
                gids.append(gid)
        if gids:
            gs += await get_groups_by_ids(gids)
    except Exception as e:
        logger.warning(f"group hits via member files failed: {e}")
    if epoch == _SEARCH_CACHE_EPOCH:
        if len(_GH_CACHE) > 300:
            _GH_CACHE.clear()
        _GH_CACHE[key] = (now + _GH_TTL, gs)
    return gs


async def _group_cards(page_groups, mode):
    ids = [m for g in page_groups for m in g.get("members", [])]
    docs = await get_files_by_ids(ids) if ids else []
    by = {d["_id"]: d for d in docs}
    ordered, manual = [], {}
    for g in page_groups:                      # search ka group-order bana rahe
        for m in g.get("members", []):
            d = by.get(m)
            if d:
                ordered.append(d)
                manual[m] = g
    rows = _build_results_list(ordered, mode)
    rows, _ = await _refresh_group_rows(rows, set(), {row.get("file_id") for row in rows})
    return group_results(rows, manual)


async def _grouped_first_page(q, off, lim, mode, gf, gs):
    """(cards, next_offset)"""
    G = len(gs) if gf != "single" else 0
    cards = []
    if off < G:
        page = gs[off: off + lim]
        cards = await _group_cards(page, mode)
        taken = len(page)
        if off + taken < G:
            return cards, off + taken
        rem = lim - taken
        if rem <= 0:                            # groups ne page bhar diya; aage files bachi hain?
            peek, _ = await _fetch_page(q, "all", 0, 1, True, gf, True)
            return cards, (G if peek else "")
        fo = 0
    else:
        rem, fo = lim, off - G

    docs, nf = await _fetch_page(q, "all", fo, rem, True, gf, True)
    file_cards = await _finalize(_build_results_list(docs, mode), True, gf, mode, siblings=False)
    seen = {c.get("gid") for c in cards if c.get("group") and c.get("manual")}
    # A same-name file can join a group after its first card was assembled.
    # Use the expanded card from this response instead of hiding the new member
    # until the next refresh.
    refreshed = {c.get("gid"): c for c in file_cards
                 if c.get("group") and c.get("manual") and c.get("gid") in seen}
    cards = [refreshed.get(c.get("gid"), c) for c in cards]
    file_cards = [c for c in file_cards if not (c.get("group") and c.get("manual") and c.get("gid") in seen)]
    return cards + file_cards, ((G + nf) if nf != "" else "")


_GROUP_CURSOR_PREFIX = "g1_"
_GROUP_CURSOR_STORED_PREFIX = "g2_"
_GROUP_CURSOR_INLINE_LIMIT = 3200  # Leave room for the URL, query and proxy limits.
_GROUP_CURSOR_INLINE_RAW_LIMIT = 131072
_GROUP_CURSOR_RAW_LIMIT = 4_000_000
_GROUP_CURSOR_SEEN_LIMIT = 100_000
_GROUP_CURSOR_TTL = 2 * 60 * 60


class _GroupCursorStorageError(RuntimeError):
    pass


class _GroupCursorLimitError(RuntimeError):
    pass


def _cursor_context(q, col, gf):
    return hashlib.sha256(json.dumps([q.lower(), col, gf], ensure_ascii=False).encode()).hexdigest()[:20]


def _validate_group_cursor(state, context):
    # _group_hits() takes at most 600 direct hits and 600 member-file hits.
    if (not isinstance(state, dict) or state.get("v") != 1 or state.get("ctx") != context
            or not isinstance(state.get("groups"), list) or len(state["groups"]) > 1200
            or not isinstance(state.get("seen"), list) or len(state["seen"]) > _GROUP_CURSOR_SEEN_LIMIT
            or any(not isinstance(item, str) or len(item) > 256 for item in state["groups"] + state["seen"])
            or not isinstance(state.get("gp"), int) or not 0 <= state["gp"] <= len(state["groups"])
            or not isinstance(state.get("fp"), int) or not 0 <= state["fp"] <= 100000000):
        raise ValueError("Invalid cursor data")


async def _encode_group_cursor(state):
    """Keep small cursors in the URL; store larger immutable snapshots in MongoDB.

    A short random token works across workers and is safe to reuse for Back and
    prefetch. TTL cleanup bounds how long old snapshots occupy the database.
    """
    try:
        _validate_group_cursor(state, state.get("ctx"))
    except ValueError as exc:
        raise _GroupCursorLimitError from exc
    payload = json.dumps(state, separators=(",", ":"), ensure_ascii=False).encode()
    if len(payload) > _GROUP_CURSOR_RAW_LIMIT:
        raise _GroupCursorLimitError
    compressed = zlib.compress(payload, 6)
    inline = _GROUP_CURSOR_PREFIX + base64.urlsafe_b64encode(compressed).decode().rstrip("=")
    if len(inline) <= _GROUP_CURSOR_INLINE_LIMIT and len(payload) <= _GROUP_CURSOR_INLINE_RAW_LIMIT:
        return inline
    token = uuid.uuid4().hex
    try:
        await group_search_cursors.insert_one({
            "_id": token, "payload": compressed,
            "expires_at": datetime.utcnow() + timedelta(seconds=_GROUP_CURSOR_TTL),
        })
    except Exception as exc:
        logger.warning(f"group pagination snapshot write failed: {exc}")
        raise _GroupCursorStorageError from exc
    return _GROUP_CURSOR_STORED_PREFIX + token


async def _decode_group_cursor(value, context):
    """Read a bounded, query-specific continuation token; offsets are opaque to the UI."""
    try:
        if value.startswith(_GROUP_CURSOR_PREFIX) and len(value) <= 48000:
            encoded = value[len(_GROUP_CURSOR_PREFIX):]
            compressed = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
            limit = _GROUP_CURSOR_INLINE_RAW_LIMIT
        elif re.fullmatch(r"g2_[0-9a-f]{32}", value):
            try:
                stored = await group_search_cursors.find_one({
                    "_id": value[len(_GROUP_CURSOR_STORED_PREFIX):],
                    "expires_at": {"$gt": datetime.utcnow()},
                })
            except Exception as exc:
                logger.warning(f"group pagination snapshot read failed: {exc}")
                raise _GroupCursorStorageError from exc
            if not stored:
                raise ValueError("Expired group pagination cursor")
            compressed = bytes(stored["payload"])
            limit = _GROUP_CURSOR_RAW_LIMIT
        else:
            raise ValueError("Invalid group pagination cursor")
        decoder = zlib.decompressobj()
        payload = decoder.decompress(compressed, limit + 1)
        if len(payload) > limit or decoder.unconsumed_tail or decoder.unused_data or not decoder.eof:
            raise ValueError("Cursor too large or incomplete")
        state = json.loads(payload)
        _validate_group_cursor(state, context)
        return state
    except (ValueError, TypeError, KeyError, zlib.error) as exc:
        raise ValueError("Invalid or expired group pagination cursor.") from exc


def _card_cursor_token(card):
    if card.get("group"):
        return "g:" + str(card.get("gid") or card.get("key") or "")
    fid = str(card.get("file_id") or "")
    return "f:" + hashlib.blake2s(fid.encode(), digest_size=16).hexdigest()


async def _grouped_cursor_page(q, col, offset, lim, mode, gf):
    """Page a stable raw-file stream, with saved groups first for all-source search.

    The cursor records which groups have already appeared. Raw positions never
    depend on group_id marks, so saving a new group between page requests cannot
    shift the file stream or skip unrelated files.
    """
    context = _cursor_context(q, col, gf)
    value = str(offset or "0")
    if value.startswith((_GROUP_CURSOR_PREFIX, _GROUP_CURSOR_STORED_PREFIX)):
        state = await _decode_group_cursor(value, context)
    else:
        try:
            legacy_offset = max(0, int(value))
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid group pagination offset.") from exc
        found = await _group_hits(q) if q and col == "all" else []
        found = found or []
        if gf in ("quality", "series"):
            found = [group for group in found if group_type(group) == gf]
        group_ids = list(dict.fromkeys(str(group["_id"]) for group in found if group.get("_id")))
        gp = min(legacy_offset, len(group_ids))
        state = {"v": 1, "ctx": context, "groups": group_ids, "gp": gp,
                 "fp": max(0, legacy_offset - len(group_ids)),
                 "seen": ["g:" + gid for gid in group_ids[:gp]]}

    seen = set(state["seen"])
    cards = []
    positions = {}

    def remember(token):
        seen.add(token)

    def save_seen():
        # Keep every seen fingerprint, including copies separated by many
        # pages. Large snapshots use a short, expiring database-backed cursor.
        state["seen"] = sorted(seen)

    def eligible(card):
        if gf == "group":
            return bool(card.get("group"))
        if gf in ("quality", "series"):
            return bool(card.get("group")) and card.get("group_type") == gf
        return True

    # The group-first list is captured once per search, rather than changing
    # when automatic groups are persisted on later pages.
    while state["gp"] < len(state["groups"]) and len(cards) < lim:
        wanted = state["groups"][state["gp"]:state["gp"] + max(1, lim - len(cards))]
        page_groups = await get_groups_by_ids(wanted)
        state["gp"] += len(wanted)
        for card in await _group_cards(page_groups, mode):
            token = _card_cursor_token(card)
            if token not in seen and eligible(card):
                positions[token] = len(cards)
                cards.append(card)
                remember(token)
    if state["gp"] < len(state["groups"]):
        save_seen()
        return cards, await _encode_group_cursor(state)

    async def raw_fetch(pos, count):
        if not q:
            return await get_recent_files(count, offset=pos, collection_type=col)
        docs, nxt, _, _ = await get_search_results(q, count, offset=pos, collection_type=col, bypass_count=True)
        return docs, nxt

    # The finite hop cap keeps a selective group filter responsive on a very
    # large library; a continuation may legitimately lead to an empty page.
    more = False
    for _ in range(4 if gf == "all" else 12):
        pos = state["fp"]
        docs, nxt = await raw_fetch(pos, max(lim * 2, 16))
        if not docs:
            more = False
            break
        by_id = {}
        for index, doc in enumerate(docs):
            by_id.setdefault(doc.get("_id"), index)
        results = await _finalize(_build_results_list(docs, mode), True, "all", mode, siblings=True)
        for card in results:
            ids = [variant.get("file_id") for variant in card.get("variants", [])] if card.get("group") else [card.get("file_id")]
            anchor = min((by_id[fid] for fid in ids if fid in by_id), default=None)
            if anchor is None or not eligible(card):
                continue
            token = _card_cursor_token(card)
            if token in seen:
                # A just-joined member can refresh a group already on this page.
                if card.get("group") and token in positions:
                    cards[positions[token]] = card
                continue
            if len(cards) >= lim:
                state["fp"] = pos + anchor
                save_seen()
                return cards, await _encode_group_cursor(state)
            positions[token] = len(cards)
            cards.append(card)
            remember(token)
        state["fp"] = pos + len(docs)
        more = bool(nxt)
        if not more:
            break
    if more:
        save_seen()
        return cards, await _encode_group_cursor(state)
    return cards, ""


@search_routes.get("/api/search")
async def api_search(req):
    role, tg_id = await get_user_role(req)
    if not role:
        return web.json_response({"error": "Unauthorized Access!"}, status=403, dumps=fast_json)
    # A post-edit read may be routed to a different worker from the write.
    if role == "admin" and req.query.get("fresh") == "1":
        _invalidate_search_caches()

    q = req.query.get("q", "").strip()
    off = req.query.get("offset", "0")
    col = req.query.get("col", "all").lower()
    mode = req.query.get("mode", DEFAULT_MEDIA_MODE).lower()
    want_group = req.query.get("group", "") == "1"     # dashboard hi bhejta hai; baaki users raw list
    gf = req.query.get("gf", "all").lower()
    gf = {"ungroup": "single", "single": "single", "group": "group",
          "quality": "quality", "series": "series"}.get(gf, "all") if want_group else "all"
    if want_group and gf == "single":
        want_group, gf = False, "all"      # UNGROUP = ग्रुप फीचर से पहले वाला साधारण सर्च (सारी फाइलें, कोई ग्रुपिंग नहीं)
    gflag = ("g1" + gf) if want_group else "g0"

    if want_group:
        try:
            cards, nxt = await _grouped_cursor_page(q, col, off, MAX_WEB_RESULTS, mode, gf)
        except ValueError:
            return web.json_response({"error": "Invalid or expired pagination cursor. Start the search again."}, status=400, dumps=fast_json)
        except _GroupCursorLimitError:
            return web.json_response({"error": "Too many results to continue. Please narrow your search."}, status=400, dumps=fast_json)
        except _GroupCursorStorageError:
            return web.json_response({"error": "Pagination is temporarily unavailable. Please try again."}, status=503, dumps=fast_json)
        return web.json_response({
            "results": cards, "total": len(cards) + (1 if nxt else 0), "next_offset": nxt,
            "is_admin": role == "admin", "is_recent": not bool(q),
        }, dumps=fast_json)

    try:
        off = max(0, int(off))
    except Exception:
        off = 0

    lim = MAX_WEB_RESULTS

    # 🆕 कोई query नहीं दी गई — सबसे नई अपलोड की गई फाइलें (Recently Added)
    if not q:
        recent_docs, recent_next_offset = await _fetch_page("", col, off, lim, want_group, gf)
        results_list = _build_results_list(recent_docs, mode)
        has_more = bool(recent_next_offset)
        return web.json_response({
            "results": await _finalize(results_list, want_group, gf, mode),
            "total": off + len(results_list) + (1 if has_more else 0),
            "next_offset": recent_next_offset,
            "is_admin": role == "admin",
            "is_recent": True,
        }, dumps=fast_json)

    cache_epoch = _SEARCH_CACHE_EPOCH
    trend_key = f"{col}_{mode}_{q.lower()}_{gflag}"
    if off == 0:
        now_ts = time.time()
        if trend_key in TRENDING_CACHE and TRENDING_CACHE[trend_key]["expiry"] > now_ts:
            cached = TRENDING_CACHE[trend_key]

            if cached["next_offset"]:
                asyncio.create_task(bg_prefetch_worker(tg_id, q, col, mode, cached["next_offset"], lim, want_group, gf))

            return web.json_response({
                "results": await _finalize(cached["results"], want_group, gf, mode),
                "total": off + len(cached["results"]) + (1 if cached["next_offset"] else 0),
                "next_offset": cached["next_offset"],
                "is_admin": role == "admin"
            }, dumps=fast_json)

    current_cache_key = f"{tg_id}_{q}_{col}_{mode}_{off}_{gflag}"
    all_m = []
    next_offset = ""

    if current_cache_key in PREFETCH_CACHE:
        all_m, next_offset = PREFETCH_CACHE[current_cache_key]
        del PREFETCH_CACHE[current_cache_key]

    if not all_m:
        all_m, next_offset = await _fetch_page(q, col, off, lim, want_group, gf)

    has_more = bool(next_offset)

    if has_more:
        asyncio.create_task(bg_prefetch_worker(tg_id, q, col, mode, next_offset, lim, want_group, gf))

    results_list = _build_results_list(all_m, mode)

    if off == 0 and results_list and cache_epoch == _SEARCH_CACHE_EPOCH:
        TRENDING_CACHE[trend_key] = {
            "results": results_list,
            "next_offset": next_offset,
            "expiry": time.time() + TRENDING_CACHE_TTL
        }

    return web.json_response({
        "results": await _finalize(results_list, want_group, gf, mode),
        "total": off + len(results_list) + (1 if has_more else 0),
        "next_offset": next_offset,
        "is_admin": role == "admin",
    }, dumps=fast_json)


# ─────────────────────────────────────────────────────────
# 📸 THUMBNAIL API
# ─────────────────────────────────────────────────────────
@search_routes.get("/api/thumb")
async def get_telegram_thumb(req):
    fid = req.query.get("file_id")
    col_name = req.query.get("col", "primary").lower()
    is_retry = req.query.get("retry", "false").lower() == "true"
    if not fid:
        return web.Response(status=400)

    headers = {
        "Content-Disposition": 'inline; filename="poster.jpg"',
        "Cache-Control": "max-age=86400"
    }

    res = await _get_or_fetch_thumb(fid, col_name=col_name, is_retry=is_retry, version=req.query.get("v", ""))
    if res is None:
        return web.Response(status=404)

    return web.Response(body=res, content_type="image/jpeg", headers=headers)


# ─────────────────────────────────────────────────────────
# 🎥 STREAM SETUP PIPELINE
# ✅ DRY: GET और POST दोनों versions में वही 4-step tunnel logic (send_cached_media
# → delete-queue → play-count → URL बनाना) दो बार लिखा था। अब सिर्फ़ input parsing
# और response format अलग है, असली काम एक ही _tunnel_stream() करता है।
# ─────────────────────────────────────────────────────────
def stream_target_path(msg_id: int, mode: str) -> str:
    """Inline playback uses the signed byte-range endpoint, not the watch page."""
    return f"/{'download' if mode in ('download', 'inline') else 'watch'}/{msg_id}"


async def _tunnel_stream(fid: str, mode: str) -> str:
    """Resolve stored IDs to Telegram's current file reference, then sign a link."""
    docs = await get_files_by_ids([fid])
    if docs:
        fid = docs[0].get("file_ref") or fid
    msg = await temp.BOT.send_cached_media(chat_id=BIN_CHANNEL, file_id=fid)
    await db.add_to_delete_queue(BIN_CHANNEL, msg.id, STREAM_TTL)   # link expiry == file delete time
    if mode in ("watch", "inline"):
        await db.track_video_play()
    inline = "&inline=1" if mode == "inline" else ""
    return f"{stream_target_path(msg.id, mode)}?{sign_params(msg.id, STREAM_TTL)}{inline}"


@search_routes.get("/setup_stream")
async def setup_stream(req):
    role, _ = await get_user_role(req)
    if not role:
        return web.Response(text="❌ Unauthorized Access Denied!", status=403)
    fid = req.query.get("file_id")
    mode = req.query.get("mode", "watch")
    if not fid:
        return web.Response(text="❌ Missing file_id!", status=400)
    try:
        return web.HTTPFound(await _tunnel_stream(fid, mode))
    except Exception as e:
        return web.Response(text=f"❌ Error Tunneling Stream: {e}", status=500)


@search_routes.post("/setup_stream")
async def setup_stream_post(req):
    role, _ = await get_user_role(req)
    if not role:
        return web.json_response({"error": "Unauthorized Web Access!"}, status=403, dumps=fast_json)
    try:
        data = await req.json()
        fid = data.get("file_id")
        mode = data.get("mode", "watch")
    except Exception:
        fid = req.query.get("file_id")
        mode = req.query.get("mode", "watch")
    if not fid:
        return web.json_response({"error": "Missing file_id!"}, status=400, dumps=fast_json)
    try:
        return web.json_response({"url": await _tunnel_stream(fid, mode)}, dumps=fast_json)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500, dumps=fast_json)


# ─────────────────────────────────────────────────────────
# ⚖️ ADMIN CONTROLS: EDIT, ADD CAPTION & TRANSFER PIPELINE
# ─────────────────────────────────────────────────────────
@search_routes.post("/api/delete")
async def api_delete(req):
    role, _ = await get_user_role(req)
    if role != "admin":
        return web.json_response({"error": "Core Admin Authorization Required!"}, status=403, dumps=fast_json)
    try:
        data = await req.json()
        fid = data.get("file_id")
        col = data.get("collection", "primary").lower()
        if col not in COLLECTIONS:
            return web.json_response({"error": "Invalid target collection!"}, status=400, dumps=fast_json)
        # ✅ NEW: डिलीट से पहले DELETE_CHANNEL में बैकअप भेजा जाता है (delete_single_file के अंदर)
        success = await delete_single_file(fid, col)
        if success:
            try:
                if col in FILE_COLLECTIONS:
                    await _cleanup_deleted_copy(fid, col)
                else:
                    await _group_cleanup()
            except Exception as e:
                logger.error(f"file deleted but group cleanup failed: {e}")
                return web.json_response({"error": "File was deleted, but group metadata could not be updated. Please check the group."}, status=500, dumps=fast_json)
        return web.json_response({"success": success}, dumps=fast_json)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500, dumps=fast_json)


@search_routes.post("/api/edit_name")
@_serialize_group_writes
async def api_edit_name(req):
    role, _ = await get_user_role(req)
    if role != "admin":
        return web.json_response({"error": "Core Admin Authorization Required!"}, status=403, dumps=fast_json)
    try:
        data = await req.json()
        fid = data.get("file_id")
        col = data.get("collection", "primary").lower()
        
        new_name = data.get("new_name", "").strip()
        add_caption = data.get("add_caption", "").strip()
        target_col = data.get("target_collection", col).lower()

        if not fid or col not in COLLECTIONS or target_col not in COLLECTIONS:
            return web.json_response({"error": "Missing structural inputs!"}, status=400, dumps=fast_json)

        doc = await COLLECTIONS[col].find_one({"_id": fid})
        if not doc:
            return web.json_response({"error": "File not found in database!"}, status=404, dumps=fast_json)

        update_fields = {}
        if new_name:
            update_fields["file_name"] = new_name

        # ✅ यहाँ बदलाव किया गया है: अब नया टैग पुराने को पूरी तरह रिप्लेस करेगा
        update_fields["caption"] = add_caption

        if col != target_col:
            doc.update(update_fields)  
            await COLLECTIONS[target_col].insert_one(doc)
            await COLLECTIONS[col].delete_one({"_id": fid})
        else:
            if update_fields:
                await COLLECTIONS[col].update_one({"_id": fid}, {"$set": update_fields})
        
        if new_name:
            # Keep group-first search in sync with an edited member filename.
            await groups.update_many({"files.id": fid}, {
                "$set": {"files.$.name": new_name, "scanned_at": 0, "updated_at": int(time.time())},
                "$addToSet": {"auto_keys": {"$each": sorted(_file_auto_keys(new_name))}}})
        if col != target_col:
            await groups.update_many({"thumb_fid": fid, "thumb_col": col}, {"$set": {
                "thumb_col": target_col, "thumb_revision": uuid.uuid4().hex, "updated_at": int(time.time())}})
            thumb_cache.pop(f"{col}:{fid}", None)
            thumb_cache.pop(f"{target_col}:{fid}", None)

        return web.json_response({"success": True}, dumps=fast_json)
    except Exception as e:
        logger.error(f"Edit/Transfer Error: {e}")
        return web.json_response({"error": str(e)}, status=500, dumps=fast_json)
    finally:
        # An update can partially complete before a later group operation fails.
        _invalidate_search_caches()


# ─────────────────────────────────────────────────────────
# 🗂️ ADMIN: saved quality / series groups (legacy QualityGroups collection)
#   group_type defaults to quality for old documents. Series can additionally store
#   episode_order and episode_labels [{id, label}], without changing the files.
#   auto_keys allow later same-name files to join, unless explicitly excluded.
# ─────────────────────────────────────────────────────────
async def _next_group_num():
    d = await group_seq.find_one_and_update(
        {"_id": "seq"}, {"$inc": {"n": 1}}, upsert=True, return_document=ReturnDocument.AFTER)
    return int(d["n"])


async def _group_cleanup(pull_ids=None, strict=False, dissolve_ids=()):
    """Remove deleted members and dissolve affected groups with fewer than two files.

    Untouched legacy singleton documents are retained for admin recovery; search
    renders their surviving file without a group card. Compare the member list
    at deletion so a concurrent addition cannot be discarded.
    """
    try:
        affected = set(dissolve_ids)
        if pull_ids:
            async for group in groups.find({"members": {"$in": pull_ids}}, {"_id": 1}):
                affected.add(str(group["_id"]))
            await groups.update_many({"members": {"$in": pull_ids}}, {"$pull": {
                "members": {"$in": pull_ids}, "files": {"id": {"$in": pull_ids}},
                "episode_order": {"$in": pull_ids}, "episode_labels": {"id": {"$in": pull_ids}}}})
            await groups.update_many({"thumb_fid": {"$in": pull_ids}},
                                     {"$set": {"thumb_fid": "", "thumb_col": ""}})
        for gid in affected:
            group = await groups.find_one({"_id": gid}, {"members": 1})
            if not group:
                continue
            members = group.get("members") or []
            if len(set(members)) >= 2:
                continue
            deleted = await groups.delete_one({"_id": gid, "members": members})
            if deleted.deleted_count:
                await _mark_files(members, "", expected_gid=gid, strict=True)
                thumb_cache.pop(f"g:{gid}", None)
        await groups.delete_many({"members": {"$size": 0}})
    except Exception as e:
        logger.warning(f"group cleanup failed: {e}")
        if strict:
            raise
    finally:
        _invalidate_search_caches()


async def _cleanup_deleted_copy(fid, deleted_col):
    """Keep group membership while the same Telegram file exists elsewhere."""
    async with _AUTO_GROUP_LOCK:
        thumb_cache.pop(f"{deleted_col}:{fid}", None)
        remaining, source = None, ""
        for name, col in FILE_COLLECTIONS.items():
            remaining = await col.find_one({"_id": fid}, {"file_name": 1})
            if remaining:
                source = name
                break
        if not remaining:
            await _group_cleanup(pull_ids=[fid], strict=True)
            return
        now = int(time.time())
        await groups.update_many({"files.id": fid}, {"$set": {
            "files.$.name": str(remaining.get("file_name") or ""), "updated_at": now}})
        # If the chosen cover copy was deleted, point it at the surviving copy.
        await groups.update_many({"thumb_fid": fid, "thumb_col": deleted_col},
                                 {"$set": {"thumb_col": source, "updated_at": now}})
        await _group_cleanup(strict=True)


async def _admin_json(req):
    role, _ = await get_user_role(req)
    if role != "admin":
        return None, web.json_response({"error": "Core Admin Authorization Required!"}, status=403, dumps=fast_json)
    try:
        data = await req.json()
        if not isinstance(data, dict):
            raise ValueError("Expected an object")
        return data, None
    except Exception:
        return None, web.json_response({"error": "Invalid request body!"}, status=400, dumps=fast_json)


def _episode_updates(data, members):
    """Validate optional series order and custom labels against actual members."""
    allowed = set(members)
    updates = {}
    if "episode_order" in data:
        order = data["episode_order"]
        if not isinstance(order, list) or any(not isinstance(i, str) or i not in allowed for i in order):
            raise ValueError("Episode order must contain group members only.")
        if len(order) != len(set(order)):
            raise ValueError("Episode order contains duplicates.")
        # A newly joined episode can be absent from a stale editor; don't lose it.
        ordered_ids = set(order)
        updates["episode_order"] = order + [i for i in members if i not in ordered_ids]
    if "episode_labels" in data:
        labels = data["episode_labels"]
        if not isinstance(labels, list):
            raise ValueError("Episode labels must be a list.")
        clean, seen = [], set()
        for item in labels:
            if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                    or item["id"] not in allowed or item["id"] in seen):
                raise ValueError("Episode labels must refer to unique group members.")
            label = item.get("label", "")
            if not isinstance(label, str) or len(label.strip()) > 80:
                raise ValueError("Episode labels must be at most 80 characters.")
            seen.add(item["id"])
            if label.strip():
                clean.append({"id": item["id"], "label": label.strip()})
        updates["episode_labels"] = clean
    return updates


SCAN_STATE = {"running": False}


async def _scan_all_groups():
    """Scan all collections using the same safe rules as search.

    New automatic groups need at least two distinct file IDs; joins are checked
    against live metadata. Legacy singleton metadata remains available for repair.
    """
    st = SCAN_STATE
    st.update(running=True, phase="groups load ho rahe hain", scanned=0, total=0, created=0,
              added=0, skipped_big=0, skipped_keys=[], fixed_marks=0, existing_groups=0,
              multi_buckets=0, error="", started=time.time(), finished=0)
    try:
        existing = [group async for group in groups.find({})]
        st["existing_groups"] = len(existing)
        owner = {fid: str(group["_id"]) for group in existing for fid in (group.get("members") or [])}
        for col in FILE_COLLECTIONS.values():
            try:
                st["total"] += await col.estimated_document_count()
            except Exception:
                pass

        st["phase"] = "files scan ho rahi hain"
        canonical, runtimes, locations = {}, defaultdict(set), defaultdict(list)
        excluded_ids, fix_set, fix_unset = set(), defaultdict(list), defaultdict(list)
        projection = {"file_name": 1, "duration": 1, "duration_seconds": 1,
                      "group_id": 1, "group_auto_excluded": 1}
        for cname, col in FILE_COLLECTIONS.items():
            async for doc in col.find({}, projection).batch_size(2000):
                st["scanned"] += 1
                if st["scanned"] % 2000 == 0:
                    await asyncio.sleep(0)
                fid = doc["_id"]
                canonical.setdefault(fid, {"_id": fid, "file_name": str(doc.get("file_name") or "")})
                seconds = duration_seconds(doc)
                if seconds:
                    runtimes[fid].add(seconds)
                locations[fid].append(cname)
                if doc.get("group_auto_excluded") and fid not in owner:
                    excluded_ids.add(fid)
                observed, actual = doc.get("group_id"), owner.get(fid)
                if actual and observed != actual:
                    fix_set[(cname, actual)].append(fid)
                elif not actual and observed:
                    fix_unset[(cname, observed)].append(fid)
        for fid, row in canonical.items():
            values = runtimes[fid]
            row["duration_seconds"] = next(iter(values)) if len(values) == 1 else 0
            row["duration"] = row["duration_seconds"]

        st["phase"] = "groups tay ho rahe hain"
        # Add normalized aliases to existing nonempty keys, without deleting or
        # replacing the administrator's data. This also upgrades legacy series
        # keys that contained an individual episode marker.
        key_groups = defaultdict(list)
        upgrades = []
        for group in existing:
            keys = _stored_auto_keys(group)
            if group.get("auto_keys"):
                for fid in group.get("members") or []:
                    if fid in canonical:
                        keys.update(_file_auto_keys(_row_name(canonical[fid])))
                new_keys = keys.difference(group.get("auto_keys") or [])
                if new_keys:
                    upgrades.append((group, sorted(new_keys)))
            for key in keys:
                key_groups[key].append(group)
        if upgrades:
            async with _AUTO_GROUP_LOCK:
                for group, keys in upgrades:
                    await groups.update_one({"_id": group["_id"], "members": group.get("members", [])},
                                            {"$addToSet": {"auto_keys": {"$each": keys}}})
                    await asyncio.sleep(0)

        # A single compatible file may join an existing group; the three-file
        # threshold only applies when creating a new automatic group.
        joins = []
        for fid, row in canonical.items():
            if fid in owner or fid in excluded_ids:
                continue
            matches, seen = [], set()
            for key in _file_auto_keys(_row_name(row)):
                for group in key_groups.get(key, []):
                    gid = str(group["_id"])
                    if gid not in seen:
                        seen.add(gid)
                        matches.append(group)
            if any(fid in (group.get("excluded") or []) for group in matches):
                excluded_ids.add(fid)
                continue
            matches.sort(key=lambda group: (group_type(group) != "series", str(group["_id"])))
            for group in matches:
                if _join_compatible(group, row, canonical):
                    joins.append((str(group["_id"]), fid, _row_name(row)))
                    break
        if joins:
            accepted, blocked = await _persist_joins(joins, strict=True)
            excluded_ids.update(blocked)
            st["added"] += len(accepted)
            for gid, fid in accepted:
                owner[fid] = gid
                for cname in locations[fid]:
                    fix_set[(cname, gid)].append(fid)
            if accepted:
                await _mark_scanned({gid for gid, _ in accepted})

        available = [row for fid, row in canonical.items() if fid not in owner and fid not in excluded_ids]
        plans = auto_group_plan(available, excluded_ids)
        st["multi_buckets"] = len(plans)
        series_ids = {fid for plan in plans if plan["kind"] == "series" for fid, _ in plan["items"]}
        series_counts, quality_counts = defaultdict(list), defaultdict(list)
        for row in available:
            name, fid = _row_name(row), row["_id"]
            if episode_identity(name) and series_key(name):
                series_counts[series_key(name)].append(row)
            if fid not in series_ids and quality_title_key(name) and duration_seconds(row):
                quality_counts[(quality_title_key(name), duration_seconds(row), episode_identity(name))].append(row)
        for key, rows in series_counts.items():
            if len(rows) > AUTO_SERIES_MAX and len({episode_identity(_row_name(row)) for row in rows}) >= 2:
                st["skipped_big"] += 1
                if len(st["skipped_keys"]) < 20:
                    st["skipped_keys"].append(f"{key} ({len(rows)} files)")
        for (key, _, _), rows in quality_counts.items():
            if len(rows) > AUTO_QUALITY_MAX:
                st["skipped_big"] += 1
                if len(st["skipped_keys"]) < 20:
                    st["skipped_keys"].append(f"{key} ({len(rows)} files)")

        st["phase"] = "groups DB me save ho rahe hain"
        # Recheck the snapshot under the same lock as edits and search writes.
        # Keep whole buckets together, but bound each live metadata lookup.
        batch, batch_size = [], 0

        async def save_batch(cards):
            resolved, _, _, stats = await _auto_persist(cards, scan=True)
            st["created"] += stats["created"]
            st["added"] += stats["added"]
            for fid, group in resolved.items():
                gid = str(group["_id"])
                for cname in locations.get(fid, []):
                    fix_set[(cname, gid)].append(fid)

        for plan in plans:
            card = {"variants": [{"file_id": fid} for fid, _ in plan["items"]]}
            if batch and batch_size + len(card["variants"]) > 1500:
                await save_batch(batch)
                batch, batch_size = [], 0
                await asyncio.sleep(0)
            batch.append(card)
            batch_size += len(card["variants"])
        if batch:
            await save_batch(batch)

        st["phase"] = "files par group_id mark ho raha hai"
        async with _AUTO_GROUP_LOCK:
            live_members = {}
            gids = list({gid for _, gid in fix_set})
            for start in range(0, len(gids), 1000):
                async for group in groups.find({"_id": {"$in": gids[start:start + 1000]}}, {"members": 1}):
                    live_members[str(group["_id"])] = set(group.get("members") or [])
            per_col = defaultdict(list)
            for (cname, gid), ids in fix_set.items():
                current = live_members.get(gid, set())
                ids = list({fid for fid in ids if fid in current})
                for start in range(0, len(ids), 1000):
                    per_col[cname].append(UpdateMany(
                        {"_id": {"$in": ids[start:start + 1000]}, "group_auto_excluded": {"$ne": True}},
                        {"$set": {"group_id": gid}}))
            for cname, ops in per_col.items():
                for start in range(0, len(ops), 500):
                    await FILE_COLLECTIONS[cname].bulk_write(ops[start:start + 500], ordered=False)
                    await asyncio.sleep(0)

            stale_ids = {fid for ids in fix_unset.values() for fid in ids}
            still_owned = set()
            stale_list = list(stale_ids)
            for start in range(0, len(stale_list), 1000):
                async for group in groups.find({"members": {"$in": stale_list[start:start + 1000]}}, {"members": 1}):
                    still_owned.update(fid for fid in (group.get("members") or []) if fid in stale_ids)
            for (cname, observed), ids in fix_unset.items():
                ids = [fid for fid in ids if fid not in still_owned]
                ops = [UpdateMany({"_id": {"$in": ids[start:start + 1000]}, "group_id": observed},
                                  {"$unset": {"group_id": ""}})
                       for start in range(0, len(ids), 1000)]
                for start in range(0, len(ops), 500):
                    await FILE_COLLECTIONS[cname].bulk_write(ops[start:start + 500], ordered=False)
            st["fixed_marks"] = sum(len(set(ids)) for ids in fix_set.values()) + sum(len(ids) for ids in fix_unset.values())

        _invalidate_search_caches()
        st["phase"] = "complete"
    except Exception as exc:
        logger.error(f"group scan failed: {exc}")
        st["error"] = str(exc)
        st["phase"] = "error"
    finally:
        st["running"] = False
        st["finished"] = time.time()
        logger.info(f"🗂️ Group scan done: scanned={st.get('scanned')}/{st.get('total')} "
                    f"existing_groups={st.get('existing_groups')} buckets={st.get('multi_buckets')} "
                    f"created={st.get('created')} added={st.get('added')} fixed_marks={st.get('fixed_marks')} "
                    f"skipped_big={st.get('skipped_big')} err={st.get('error')}")
        if st.get("skipped_keys"):
            logger.info("🗂️ Skipped large buckets: " + " | ".join(st["skipped_keys"]))

@search_routes.post("/api/group/scan_all")
async def api_group_scan_all(req):
    role, _ = await get_user_role(req)
    if role != "admin":
        return web.json_response({"error": "Core Admin Authorization Required!"}, status=403, dumps=fast_json)
    if SCAN_STATE.get("running"):
        return web.json_response({"started": False, "running": True}, dumps=fast_json)
    SCAN_STATE["running"] = True  # reserve before scheduling so concurrent clicks cannot start two scans
    asyncio.create_task(_scan_all_groups())
    return web.json_response({"started": True}, dumps=fast_json)


@search_routes.get("/api/group/scan_status")
async def api_group_scan_status(req):
    role, _ = await get_user_role(req)
    if role != "admin":
        return web.json_response({"error": "Core Admin Authorization Required!"}, status=403, dumps=fast_json)
    return web.json_response({k: v for k, v in SCAN_STATE.items()}, dumps=fast_json)


@search_routes.get("/api/group/list")
async def api_group_list(req):
    role, _ = await get_user_role(req)
    if role != "admin":
        return web.json_response({"error": "Core Admin Authorization Required!"}, status=403, dumps=fast_json)
    q = req.query.get("q", "").strip().lstrip("#").strip()
    exact = await groups.find_one({"_id": q}) if q.isdigit() else None
    if not q:
        flt = {}
    elif q.isdigit():
        # An exact number must never be hidden by 25 newer name matches.
        flt = {"_id": {"$ne": q}, "name": {"$regex": re.escape(q), "$options": "i"}}
    else:
        flt = {"name": {"$regex": re.escape(q), "$options": "i"}}

    def summary(g):
        return {"id": str(g["_id"]), "num": g.get("num", ""), "name": g.get("name", ""),
                "group_type": group_type(g), "count": len(g.get("members", []))}

    out = [summary(exact)] if exact else []
    async for g in groups.find(flt).sort("updated_at", -1).limit(25 - len(out)):
        out.append(summary(g))
    return web.json_response({"groups": out}, dumps=fast_json)


def _group_preview_signature(group):
    """Fingerprint the target details an admin is asked to review before moving files."""
    def pairs(key, value_key):
        return [[str(item.get("id") or ""), str(item.get(value_key) or "")]
                for item in (group.get(key) or []) if isinstance(item, dict)]

    visible = {
        "id": str(group["_id"]), "num": str(group.get("num") or group["_id"]),
        "name": str(group.get("name") or ""), "type": group_type(group),
        "members": [str(fid) for fid in (group.get("members") or [])],
        "files": pairs("files", "name"),
        "episode_order": [str(fid) for fid in (group.get("episode_order") or [])],
        "episode_labels": pairs("episode_labels", "label"),
        "thumb_url": str(group.get("thumb_url") or ""),
        "thumb_fid": str(group.get("thumb_fid") or ""),
        "thumb_col": str(group.get("thumb_col") or ""),
        "thumb_revision": str(group.get("thumb_revision") or ""),
        "created_at": str(group.get("created_at") or ""),
    }
    return hashlib.sha256(fast_json(visible).encode("utf-8")).hexdigest()


def _target_changed_response():
    return web.json_response({"error": "Target group changed. Please review it again.", "code": "target_changed"},
                             status=409, dumps=fast_json)


def _check_group_preview(data, group):
    """Reject a stale reviewed target; older API clients may omit the fingerprint."""
    if "expected_target" not in data:
        return None
    expected = data["expected_target"]
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        return web.json_response({"error": "Invalid target preview. Please look up the group again."},
                                 status=400, dumps=fast_json)
    if not hmac.compare_digest(expected, _group_preview_signature(group)):
        return _target_changed_response()
    return None


def _preview_write_filter(group, require_preview):
    """Atomically reject target changes between validation and the membership write."""
    flt = {"_id": group["_id"]}
    if require_preview:
        for key in ("num", "name", "group_type", "members", "files", "episode_order", "episode_labels",
                    "thumb_url", "thumb_fid", "thumb_col", "thumb_revision", "created_at"):
            flt[key] = {"$eq": group[key]} if key in group else {"$exists": False}
    return flt


@search_routes.get("/api/group/preview")
async def api_group_preview(req):
    """Look up exactly one group for an admin, without using the search caches."""
    def respond(data, status=200):
        return web.json_response(data, status=status, dumps=fast_json, headers={"Cache-Control": "no-store"})

    role, _ = await get_user_role(req)
    if role != "admin":
        return respond({"error": "Core Admin Authorization Required!"}, status=403)
    gid = req.query.get("id", "").strip()
    if gid.startswith("#"):
        gid = gid[1:].strip()
    if not re.fullmatch(r"[0-9]{1,64}", gid):
        return respond({"error": "Enter a valid group number."}, status=400)
    try:
        g = await groups.find_one({"_id": gid})
        if not g:
            return respond({"error": f"Group #{gid} was not found."}, status=404)

        members = list(g.get("members") or [])
        member_set = set(members)
        # A small sample keeps lookups bounded even for a very large series.
        ordered = ([fid for fid in (g.get("episode_order") or []) if fid in member_set]
                   if group_type(g) == "series" else [])
        ordered = list(dict.fromkeys(ordered + members))
        sample = ordered[:5]
        remaining = set(sample)
        docs = {}
        for source, col in FILE_COLLECTIONS.items():
            if not remaining:
                break
            found = await col.find({"_id": {"$in": list(remaining)}},
                                   {"file_name": 1, "meta": 1, "thumb_url": 1, "thumb_revision": 1}).to_list(length=len(remaining))
            for doc in found:
                docs[doc["_id"]] = (doc, source)
                remaining.discard(doc["_id"])

        labels = {item.get("id"): str(item.get("label") or "") for item in (g.get("episode_labels") or [])
                  if isinstance(item, dict) and item.get("id")}
        preview_members = []
        for fid in sample:
            doc, source = docs.get(fid, ({}, ""))
            name = str(doc.get("file_name") or "")
            label = labels.get(fid, "") if group_type(g) == "series" else _quality_label(doc_resolution_text(doc), name)[0]
            preview_members.append({"name": name or "File unavailable", "label": label,
                                    "source": source, "available": bool(doc)})

        revision = urllib.parse.quote(str(g.get("thumb_revision") or g.get("updated_at") or 0), safe="")
        cover, cover_label = "", ""
        if str(g.get("thumb_url") or "").startswith("TG_ID:"):
            cover = f"/api/group/thumb?gid={urllib.parse.quote(gid, safe='')}&v={revision}"
            cover_label = "Group cover"
        elif g.get("thumb_fid") in member_set and g.get("thumb_col") in FILE_COLLECTIONS:
            cover = (f"/api/thumb?file_id={urllib.parse.quote(str(g['thumb_fid']), safe='')}"
                     f"&col={urllib.parse.quote(str(g['thumb_col']), safe='')}&v={revision}")
            cover_label = "Group cover"
        else:
            for fid in sample:
                if fid in docs:
                    doc, source = docs[fid]
                    cover = (f"/api/thumb?file_id={urllib.parse.quote(str(fid), safe='')}"
                             f"&col={urllib.parse.quote(source, safe='')}&v={urllib.parse.quote(_thumb_version(doc), safe='')}")
                    cover_label = "Sample file"
                    break
        result = {"id": gid, "num": g.get("num") or gid, "name": str(g.get("name") or ""),
                  "group_type": group_type(g), "count": len(members), "members": preview_members,
                  "more": max(0, len(members) - len(sample)), "cover": cover, "cover_label": cover_label,
                  "signature": _group_preview_signature(g)}
        return respond({"group": result})
    except Exception as exc:
        logger.warning(f"group preview failed: {exc}")
        return respond({"error": "Could not load group information. Please try again."}, status=503)


@search_routes.post("/api/group/save")
@_serialize_group_writes
async def api_group_save(req):
    """Create a group or add members to an existing one, preserving its type."""
    data, err = await _admin_json(req)
    if err:
        return err
    try:
        supplied = data.get("items", [])
        if not isinstance(supplied, list) or any(not isinstance(x, dict) for x in supplied):
            return web.json_response({"error": "Invalid file selection."}, status=400, dumps=fast_json)
        file_ids = list(dict.fromkeys(str(x.get("id") or "").strip() for x in supplied if x.get("id")))
        gid = str(data.get("group_id") or "").strip()
        name = str(data.get("name") or "").strip()[:200]
        requested_type = data.get("group_type", "quality")
        if not isinstance(requested_type, str) or requested_type not in GROUP_TYPES:
            return web.json_response({"error": "Choose quality or series."}, status=400, dumps=fast_json)
        if not file_ids:
            return web.json_response({"error": "Koi file select nahi hai!"}, status=400, dumps=fast_json)

        # Validate everything before changing any existing membership. Previously a
        # missing target ID or blank name removed files from their old groups first.
        target = await groups.find_one({"_id": gid}) if gid else None
        if gid and not target:
            return web.json_response({"error": "Group nahi mila!"}, status=404, dumps=fast_json)
        if target:
            preview_error = _check_group_preview(data, target)
            if preview_error is not None:
                return preview_error
        if not gid and not name:
            return web.json_response({"error": "Group ka naam likhiye!"}, status=400, dumps=fast_json)
        if not gid and len(file_ids) < 2:
            return web.json_response({"error": "A group needs at least 2 distinct files."}, status=400, dumps=fast_json)
        docs = await get_files_by_ids(file_ids)
        by_id = {d["_id"]: d for d in docs}
        if any(fid not in by_id for fid in file_ids):
            return web.json_response({"error": "Some selected files no longer exist. Refresh and try again."}, status=400, dumps=fast_json)
        items = [(fid, str(by_id[fid].get("file_name") or "")) for fid in file_ids]
        auto_keys = sorted(set().union(*(_file_auto_keys(name) for _, name in items)))
        try:
            episode_data = _episode_updates(data, file_ids) if not target else {}
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400, dumps=fast_json)
        now = int(time.time())

        if target:
            num, name = target.get("num") or gid, target.get("name", "")
            fresh = [(i, n) for i, n in items if i not in (target.get("members") or [])]
            add = {"members": {"$each": file_ids}}
            if fresh:
                add["files"] = {"$each": [{"id": i, "name": n} for i, n in fresh]}
            if auto_keys:
                add["auto_keys"] = {"$each": auto_keys}
            result = await groups.update_one(_preview_write_filter(target, "expected_target" in data), {"$addToSet": add,
                "$set": {"updated_at": now, "scanned_at": 0},
                "$pull": {"excluded": {"$in": file_ids}}})
            if not result.matched_count:
                return _target_changed_response()
            saved_type = group_type(target)
        else:
            num = await _next_group_num()
            gid = str(num)
            saved_type = requested_type
            await groups.insert_one({
                "_id": gid, "num": num, "name": name, "members": file_ids,
                "files": [{"id": i, "name": n} for i, n in items],
                "auto_keys": auto_keys, "excluded": [], "group_type": saved_type, **episode_data,
                "thumb_fid": "", "thumb_col": "", "thumb_url": "", "scanned_at": 0,
                "created_at": now, "updated_at": now})

        # Move files out of other groups, but never pull/reorder the target's own members.
        other = {"_id": {"$ne": gid}, "members": {"$in": file_ids}}
        affected = [str(group["_id"]) async for group in groups.find(other, {"_id": 1})]
        await groups.update_many(other, {
            "$pull": {"members": {"$in": file_ids}, "files": {"id": {"$in": file_ids}},
                      "episode_order": {"$in": file_ids}, "episode_labels": {"id": {"$in": file_ids}}},
            "$addToSet": {"excluded": {"$each": file_ids}}, "$set": {"updated_at": now}})
        await groups.update_many({"_id": {"$ne": gid}, "thumb_fid": {"$in": file_ids}},
                                 {"$set": {"thumb_fid": "", "thumb_col": ""}})
        await _mark_files(file_ids, gid)
        await _group_cleanup(dissolve_ids=affected, strict=True)
        return web.json_response({"success": True, "group_id": gid, "num": num,
                                  "group_name": name, "group_type": saved_type}, dumps=fast_json)
    except Exception as e:
        logger.error(f"group save error: {e}")
        return web.json_response({"error": str(e)}, status=500, dumps=fast_json)


@search_routes.post("/api/group/update")
@_serialize_group_writes
async def api_group_update(req):
    """Group ka naam / thumbnail badlo.
    thumb_file_id: member ka thumbnail (khali '' = AUTO).  clear_custom=true: upload kiya
    custom thumbnail hata do."""
    data, err = await _admin_json(req)
    if err:
        return err
    try:
        gid = str(data.get("group_id") or "").strip()
        g = await groups.find_one({"_id": gid})
        if not g:
            return web.json_response({"error": "Group nahi mila!"}, status=404, dumps=fast_json)
        upd = {"updated_at": int(time.time())}
        if "thumb_file_id" in data or data.get("clear_custom"):
            upd["thumb_revision"] = uuid.uuid4().hex
        if "group_type" in data:
            kind = data["group_type"]
            if not isinstance(kind, str) or kind not in GROUP_TYPES:
                return web.json_response({"error": "Choose quality or series."}, status=400, dumps=fast_json)
            upd["group_type"] = kind
            if kind != group_type(g):
                upd["scanned_at"] = 0
        try:
            upd.update(_episode_updates(data, g.get("members") or []))
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400, dumps=fast_json)
        if "name" in data:
            nm = str(data.get("name") or "").strip()[:200]
            if not nm:
                return web.json_response({"error": "Group ka naam khali nahi ho sakta!"}, status=400, dumps=fast_json)
            upd["name"] = nm
        if "thumb_file_id" in data:
            tf = str(data.get("thumb_file_id") or "").strip()
            tc = str(data.get("thumb_col") or "").strip().lower()
            if tf:
                if tc not in FILE_COLLECTIONS or tf not in (g.get("members") or []):
                    return web.json_response({"error": "Thumbnail must be a group member in a file collection."}, status=400, dumps=fast_json)
                upd["thumb_fid"], upd["thumb_col"] = tf, tc
            else:
                upd["thumb_fid"], upd["thumb_col"] = "", ""
        if data.get("clear_custom"):
            upd["thumb_url"] = ""
            thumb_cache.pop(f"g:{gid}", None)
        await groups.update_one({"_id": gid}, {"$set": upd})
        await _group_cleanup()
        return web.json_response({"success": True}, dumps=fast_json)
    except Exception as e:
        logger.error(f"group update error: {e}")
        return web.json_response({"error": str(e)}, status=500, dumps=fast_json)


@search_routes.post("/api/group/remove_file")
@_serialize_group_writes
async def api_group_remove_file(req):
    data, err = await _admin_json(req)
    if err:
        return err
    try:
        gid = str(data.get("group_id") or "").strip()
        fid = str(data.get("file_id") or "").strip()
        if not gid or not fid:
            return web.json_response({"error": "Missing inputs!"}, status=400, dumps=fast_json)
        g = await groups.find_one({"_id": gid})
        if not g:
            return web.json_response({"error": "Group nahi mila!"}, status=404, dumps=fast_json)
        if fid not in (g.get("members") or []):
            return web.json_response({"error": "File is not in this group."}, status=400, dumps=fast_json)
        upd = {"$pull": {"members": fid, "files": {"id": fid},
                         "episode_order": fid, "episode_labels": {"id": fid}},
               "$addToSet": {"excluded": fid},
               "$set": {"updated_at": int(time.time())}}
        if g.get("thumb_fid") == fid:
            upd["$set"].update({"thumb_fid": "", "thumb_col": ""})
        # Mark the exclusion first. If a collection write fails, keep the saved
        # membership so a retry can finish without silently losing the decision.
        await _mark_files([fid], "", expected_gid=gid, suppress_auto=True, strict=True)
        await groups.update_one({"_id": gid, "members": fid}, upd)
        await _group_cleanup(dissolve_ids=[gid], strict=True)
        return web.json_response({"success": True, "group_deleted": not bool(await groups.find_one({"_id": gid}, {"_id": 1}))}, dumps=fast_json)
    except Exception as e:
        logger.error(f"group remove error: {e}")
        return web.json_response({"error": str(e)}, status=500, dumps=fast_json)


@search_routes.post("/api/group/delete")
async def api_group_delete(req):
    """Delete the group, not its files; keep them out of automatic regrouping."""
    data, err = await _admin_json(req)
    if err:
        return err
    try:
        gid = str(data.get("group_id") or "").strip()
        async with _AUTO_GROUP_LOCK:
            old = await groups.find_one({"_id": gid}, {"members": 1})
            if not old:
                return web.json_response({"error": "Group nahi mila!"}, status=404, dumps=fast_json)
            # Prevent an in-flight search from recreating the group while it is removed.
            await _mark_files(old.get("members", []), "", expected_gid=gid, suppress_auto=True, strict=True)
            await groups.delete_one({"_id": gid})
        thumb_cache.pop(f"g:{gid}", None)
        await _group_cleanup()
        return web.json_response({"success": True}, dumps=fast_json)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500, dumps=fast_json)


@search_routes.post("/api/group/merge")
@_serialize_group_writes
async def api_group_merge(req):
    """Source group ki saari files (aur auto-keys) target group (number) me daalo; source hat jaata hai."""
    data, err = await _admin_json(req)
    if err:
        return err
    try:
        src_id = str(data.get("source") or "").strip()
        tgt_id = str(data.get("target") or "").strip().lstrip("#")
        if not src_id or not tgt_id:
            return web.json_response({"error": "Group number likhiye!"}, status=400, dumps=fast_json)
        if src_id == tgt_id:
            return web.json_response({"error": "Same group me merge nahi ho sakta!"}, status=400, dumps=fast_json)
        src = await groups.find_one({"_id": src_id})
        tgt = await groups.find_one({"_id": tgt_id})
        if not src:
            return web.json_response({"error": "Source group nahi mila!"}, status=404, dumps=fast_json)
        if not tgt:
            return web.json_response({"error": f"Group #{tgt_id} nahi mila!"}, status=404, dumps=fast_json)
        preview_error = _check_group_preview(data, tgt)
        if preview_error is not None:
            return preview_error
        add = {"members": {"$each": src.get("members", [])}}
        if src.get("files"):
            add["files"] = {"$each": src["files"]}
        if src.get("auto_keys"):
            add["auto_keys"] = {"$each": src["auto_keys"]}
        if src.get("excluded"):
            add["excluded"] = {"$each": src["excluded"]}
        updates = {"updated_at": int(time.time()), "scanned_at": 0}
        if group_type(tgt) == "series":
            if tgt.get("episode_order") or src.get("episode_order"):
                def complete_order(group):
                    saved = group.get("episode_order") or []
                    seen = set(saved)
                    return saved + [i for i in group.get("members") or [] if i not in seen]
                updates["episode_order"] = list(dict.fromkeys(complete_order(tgt) + complete_order(src)))
            labels = {x.get("id"): x for x in (tgt.get("episode_labels") or []) if isinstance(x, dict)}
            for item in src.get("episode_labels") or []:
                if isinstance(item, dict) and item.get("id") not in labels:
                    labels[item.get("id")] = item
            if labels:
                updates["episode_labels"] = list(labels.values())
        result = await groups.update_one(_preview_write_filter(tgt, "expected_target" in data),
                                         {"$addToSet": add, "$set": updates})
        if not result.matched_count:
            return _target_changed_response()
        await groups.update_one({"_id": tgt_id}, {"$pull": {"excluded": {"$in": src.get("members", [])}}})
        await groups.delete_one({"_id": src_id})
        await _mark_files(src.get("members", []), tgt_id)
        thumb_cache.pop(f"g:{src_id}", None)
        await _group_cleanup()
        return web.json_response({"success": True, "num": tgt.get("num", ""), "group_name": tgt.get("name", ""),
                                  "group_type": group_type(tgt)}, dumps=fast_json)
    except Exception as e:
        logger.error(f"group merge error: {e}")
        return web.json_response({"error": str(e)}, status=500, dumps=fast_json)


@search_routes.post("/api/group/upload_thumb")
async def api_group_upload_thumb(req):
    """Group ka apna custom thumbnail (file ke thumbnail upload jaisa). multipart: group_id, image"""
    role, _ = await get_user_role(req)
    if role != "admin":
        return web.json_response({"error": "Core Admin Authorization Required!"}, status=403, dumps=fast_json)
    try:
        reader = await req.multipart()
        gid, image_bytes = "", None
        while True:
            part = await reader.next()
            if part is None:
                break
            if part.name == "group_id":
                gid = (await part.read()).decode().strip()
            elif part.name == "image":
                image_bytes = await part.read()
        if not gid or not image_bytes:
            return web.json_response({"error": "Missing required assets!"}, status=400, dumps=fast_json)
        if not await groups.find_one({"_id": gid}, {"_id": 1}):
            return web.json_response({"error": "Group nahi mila!"}, status=404, dumps=fast_json)

        with io.BytesIO(image_bytes) as buf:
            buf.name = "group_poster.jpg"
            msg = await temp.BOT.send_photo(chat_id=THUMBNAIL_STORAGE_CHANNEL, photo=buf)
        if not msg or not msg.photo:
            return web.json_response({"error": "Telegram Node failed!"}, status=500, dumps=fast_json)
        try:
            new_id = msg.photo.sizes[-1].file_id if getattr(msg.photo, "sizes", None) else msg.photo.file_id
        except Exception:
            new_id = msg.photo.file_id

        await groups.update_one({"_id": gid}, {"$set": {"thumb_url": f"TG_ID:{new_id}", "thumb_revision": uuid.uuid4().hex, "updated_at": int(time.time())}})
        thumb_cache.pop(f"g:{gid}", None)
        await _group_cleanup()
        return web.json_response({"success": True}, dumps=fast_json)
    except Exception as e:
        logger.error(f"❌ Group thumb upload crash: {e}")
        return web.json_response({"error": str(e)}, status=500, dumps=fast_json)


@search_routes.get("/api/group/thumb")
async def api_group_thumb(req):
    gid = req.query.get("gid", "").strip()
    if not gid:
        return web.Response(status=400)
    revision = req.query.get("v", "")[:100]
    ck = f"g:{gid}" + (f":{revision}" if revision else "")
    img = thumb_cache.get(ck)
    if img is None:
        g = await groups.find_one({"_id": gid}, {"thumb_url": 1})
        tu = (g or {}).get("thumb_url", "")
        if not tu.startswith("TG_ID:"):
            return web.Response(status=404)
        try:
            fd = await temp.BOT.download_media(tu.replace("TG_ID:", ""), in_memory=True)
            img = fd.getvalue() if fd else None
        except Exception as e:
            logger.warning(f"group thumb fetch failed: {e}")
            img = None
        if not img:
            return web.Response(status=404)
        thumb_cache[ck] = img
    return web.Response(body=img, content_type="image/jpeg",
                        headers={"Content-Disposition": 'inline; filename="poster.jpg"', "Cache-Control": "max-age=86400"})


# ─────────────────────────────────────────────────────────
# 📥 NATIVE THUMBNAIL UPLOAD & CACHE BUSTER API
# ─────────────────────────────────────────────────────────
@search_routes.post("/api/upload_thumb")
async def api_upload_thumb(req):
    role, _ = await get_user_role(req)
    if role != "admin":
        return web.json_response({"error": "Core Admin Authorization Required!"}, status=403, dumps=fast_json)
    try:
        reader = await req.multipart()
        file_id_field, collection_field, image_bytes = None, None, None
        while True:
            part = await reader.next()
            if part is None:
                break
            if part.name == 'file_id':
                file_id_field = (await part.read()).decode().strip()
            elif part.name == 'collection':
                collection_field = (await part.read()).decode().strip().lower()
            elif part.name == 'image':
                image_bytes = await part.read()

        if not file_id_field or not collection_field or not image_bytes:
            return web.json_response({"error": "Missing required assets!"}, status=400, dumps=fast_json)
        if collection_field not in COLLECTIONS:
            return web.json_response({"error": "Target collection missing!"}, status=400, dumps=fast_json)

        cache_k = f"{collection_field}:{file_id_field}"

        with io.BytesIO(image_bytes) as img_buffer:
            img_buffer.name = "poster.jpg"
            # ✅ UPGRADE: पुराने मिक्स्ड 'BIN_CHANNEL' के बजाय पृथक 'THUMBNAIL_STORAGE_CHANNEL' का उपयोग
            msg = await temp.BOT.send_photo(chat_id=THUMBNAIL_STORAGE_CHANNEL, photo=img_buffer)

        if not msg or not msg.photo:
            return web.json_response({"error": "Telegram Node failed!"}, status=500, dumps=fast_json)

        try:
            new_thumb_id = (
                msg.photo.sizes[-1].file_id
                if hasattr(msg.photo, "sizes") and msg.photo.sizes
                else msg.photo.file_id
            )
        except Exception:
            new_thumb_id = msg.photo.file_id

        db_save_value = f"TG_ID:{new_thumb_id}"
        revision = uuid.uuid4().hex
        result = await COLLECTIONS[collection_field].update_one(
            {"_id": file_id_field},
            {"$set": {"thumb_url": db_save_value, "thumb_revision": revision,
                      "thumb_source": "web", "is_thumb_permanent": True}}
        )
        if not result.matched_count:
            return web.json_response({"error": "File not found in database."}, status=404, dumps=fast_json)

        # Group covers that point at this member have their own versioned URL.
        # Invalidate cached search data even if updating the group metadata fails.
        try:
            await groups.update_many({"thumb_fid": file_id_field, "thumb_col": collection_field},
                                     {"$set": {"thumb_revision": revision}})
        except Exception as exc:
            logger.error(f"Thumbnail saved, but group cover revision failed: {exc}")
            return web.json_response({"partial": True, "error": "Could not refresh the selected group cover. Edit the group to retry."}, status=500, dumps=fast_json)
        finally:
            thumb_cache.pop(cache_k, None)
            _invalidate_search_caches()

        return web.json_response({"success": True, "thumb_revision": revision}, dumps=fast_json)

    except Exception as e:
        logger.error(f"❌ Upload thumb endpoint crash: {e}")
        return web.json_response({"error": str(e)}, status=500, dumps=fast_json)


@search_routes.get("/api/db_stats")
async def api_db_stats(req):
    role, _ = await get_user_role(req)
    if role != "admin":
        return web.json_response({"error": "Admin Authorization Required!"}, status=403, dumps=fast_json)
    
    try:
        stats = await filter_db.command("dbstats")
        used_bytes = stats.get("storageSize", 0) + stats.get("indexSize", 0)
        limit_bytes = 512 * 1024 * 1024
        percent = (used_bytes / limit_bytes) * 100
        
        return web.json_response({
            "used": get_size(used_bytes),
            "total": "512.0 MB",
            "percent": min(round(percent, 2), 100) 
        }, dumps=fast_json)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500, dumps=fast_json)


# ─────────────────────────────────────────────
# 🧹 ADMIN: RAM CACHE FLUSH (stats.py के "Flush RAM Cache" बटन के लिए)
# ✅ FIX: पहले यह बटन सिर्फ़ UI में setTimeout से "✅ Cleared!" दिखा देता था,
# असल में कोई cache clear नहीं होता था। अब यहाँ पहले से मौजूद LRU caches
# (thumb_cache, PREFETCH_CACHE, TRENDING_CACHE - जो api_edit_name/api_upload_thumb
# में भी clear होते हैं) को ही दोबारा इस्तेमाल किया गया है, नया कैशे सिस्टम नहीं बनाया।
# ─────────────────────────────────────────────
@search_routes.post("/api/flush_cache")
async def api_flush_cache(req):
    role, _ = await get_user_role(req)
    if role != "admin":
        return web.json_response({"error": "Admin Authorization Required!"}, status=403, dumps=fast_json)
    try:
        thumb_cache.clear()
        _invalidate_search_caches()
        gc.collect()
        return web.json_response({"success": True}, dumps=fast_json)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500, dumps=fast_json)


@search_routes.get("/miniapp")
async def miniapp_page(req):
    # ❌ DEAD CODE REMOVED: पहले "web/" न मिलने पर "Web/" (capital W) fallback भी
    # चेक होता था, पर repo में ऐसा कोई directory है ही नहीं — वह शाखा कभी नहीं चलती थी।
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html_path = os.path.join(base_dir, "web", "miniapp.html")
    if not os.path.exists(html_path):
        return web.Response(text="miniapp.html page template not found.", status=404)
    # 🎛️ Centralized default view mode inject (DEFAULT_MEDIA_MODE — web_assets.py)
    with open(html_path, "r", encoding="utf-8") as f:
        html_src = f.read()
    html_src = html_src.replace("__DEFAULT_MEDIA_MODE__", DEFAULT_MEDIA_MODE)
    return web.Response(text=html_src, content_type="text/html", charset="utf-8")
