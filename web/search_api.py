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
import logging
import urllib.parse
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
from database.ia_filterdb import COLLECTIONS, FILE_COLLECTIONS, groups, group_seq, get_files_by_ids, find_phrase_files, search_groups, get_groups_by_ids, get_search_results, get_recent_files, db as filter_db, delete_single_file, build_media_meta, doc_resolution_text, msg_media
from media_probe import probe_telegram_file, should_probe_media
from database.users_chats_db import db
# ✅ SYNC FIX: cookie-session identity check अब यहाँ दोबारा नहीं लिखा, web_assets से reuse हो रहा है
# ✅ DRY: fast_json भी अब web_assets से ही आता है (पहले search_api/actor_routes/
# post_routes तीनों में इसकी अलग-अलग copy थी)।
from web.web_assets import get_auth as web_get_auth, fast_json, DEFAULT_MEDIA_MODE
from web.grouping import GROUP_TYPES, group_type, order_series

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
            "duration": get_duration_str(d.get("duration")),
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
async def _manual_map(items, joins=None, blocked=None):
    """Resolve explicit members first, then eligible same-name additions.

    An admin-excluded file must not form another automatic group with the same
    key or be re-added in a later scan/search. `blocked` carries that decision
    through page counting and sibling expansion as well.
    """
    items = [(i, n) for i, n in items if i]
    out = {}
    if not items:
        return out
    ids = {i for i, _ in items}
    keys = list({k for k in (_group_key(n) for _, n in items) if k})
    try:
        cond = [{"members": {"$in": list(ids)}}]
        if keys:
            cond.append({"auto_keys": {"$in": keys}})
        found = [g async for g in groups.find({"$or": cond})]
        by_key = {}
        for g in found:
            for k in g.get("auto_keys", []):
                by_key.setdefault(k, []).append(g)
            for m in g.get("members", []):
                if m in ids:
                    out[m] = g
        for i, n in items:
            if i in out or (blocked is not None and i in blocked):
                continue
            matches = by_key.get(_group_key(n), [])
            # A deliberate removal wins even if another group shares this key.
            if any(i in (g.get("excluded") or []) for g in matches):
                if blocked is not None:
                    blocked.add(i)
                continue
            if matches:
                g = matches[0]
                out[i] = g
                if joins is not None:
                    joins.append((str(g["_id"]), i, n))
    except Exception as e:
        logger.warning(f"manual group lookup failed: {e}")
    return out


def _bucket_key(file_id, name, manual, blocked=None):
    """Saved group > explicit exclusion > conservative automatic name key."""
    g = manual.get(file_id)
    if g:
        return "m:" + str(g["_id"])
    if blocked and file_id in blocked:
        return "s:" + str(file_id)
    k = _group_key(name)
    return ("a:" + k) if k else ("s:" + str(file_id))


def group_results(results, manual=None, blocked=None):
    """Build cards without mutating cached input; legacy groups default to quality."""
    manual = manual or {}
    order, buckets, bucket_ids = [], {}, {}
    for r in results:
        k = _bucket_key(r.get("file_id"), r.get("name"), manual, blocked)
        if k.startswith("s:"):
            order.append(("single", r))
            continue
        if k not in buckets:
            buckets[k] = []
            bucket_ids[k] = set()
            order.append(("group", k))
        fid = r.get("file_id")
        if fid and fid in bucket_ids[k]:
            continue  # the same Telegram file can be indexed in multiple collections
        bucket_ids[k].add(fid)
        buckets[k].append(r)

    out = []
    for kind, v in order:
        if kind == "single":
            out.append(v)
            continue
        items = buckets[v]
        mg = manual.get(items[0].get("file_id")) if v.startswith("m:") else None
        # A saved group can have one remaining member; keep it editable and numbered.
        if len(items) == 1 and not mg:
            out.append(items[0])
            continue
        gid = str(mg["_id"]) if mg else ""
        num = (mg.get("num") or gid) if mg else ""
        gtype = group_type(mg)
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
            title = _html.escape(_group_title(items[0].get("name")) or str(items[0].get("name") or ""))
            key = f"{zlib.crc32(v.encode('utf-8')):08x}"
        out.append({
            "group": True,
            "group_type": gtype,
            "manual": bool(mg),
            "gid": gid,
            "nkey": "" if mg else v[2:],
            "num": num,
            "custom_thumb": bool(mg and mg.get("thumb_url")),
            "key": key,
            "title": title,
            "count": len(vlist),
            "type": rep.get("type", "VIDEO"),
            "tg_thumb": thumb,
            "thumb_fid": (mg.get("thumb_fid") or "") if mg else "",
            "duration": rep.get("duration", "") if gtype == "quality" else "",
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

    batch = lim * 4
    hops_max = 4 if gf == "all" else 12
    raw, cur, more, manual, blocked = [], off, True, {}, set()

    def kof(d):
        return _bucket_key(d.get("_id"), d.get("file_name"), manual, blocked)

    def count_buckets(rows):
        unique = {}
        for d in rows:
            unique.setdefault(kof(d), set()).add(d.get("_id"))
        cnt = {k: len(ids) for k, ids in unique.items()}
        for d in rows:                       # saved group = hamesha "group" (uski baaki files bhi dikhengi)
            g = manual.get(d.get("_id"))
            if g:
                k = kof(d)
                cnt[k] = max(cnt[k], len(g.get("members", [])))
        return cnt

    for _hop in range(hops_max):
        docs, nxt = await raw_fetch(cur, batch)
        if not docs:
            more = False
            break
        raw.extend(docs)
        blocked.update(d.get("_id") for d in docs if d.get("group_auto_excluded"))
        manual.update(await _manual_map([(d.get("_id"), d.get("file_name")) for d in docs], blocked=blocked))
        more = bool(nxt)
        cur = nxt if nxt != "" else None

        cnt = count_buckets(raw)
        bucket_groups = {kof(d): manual[d["_id"]] for d in raw if d.get("_id") in manual}

        def ok(k):
            is_group = k.startswith("m:") or cnt[k] >= 2
            if gf == "group":
                return is_group
            if gf in ("quality", "series"):
                if not is_group:
                    return False
                return group_type(bucket_groups.get(k)) == gf
            if gf == "single":
                return not is_group
            return True

        keys, cut = set(), None
        for i, d in enumerate(raw):
            k = kof(d)
            if not ok(k):
                continue
            if k not in keys:
                if len(keys) >= lim:
                    cut = i
                    break
                keys.add(k)
        if cut is not None:
            return [d for d in raw[:cut] if ok(kof(d))], off + cut
        if not more:
            break

    scanned = len(raw)
    cnt = count_buckets(raw)
    if raw and gf != "all":
        raw = [d for d in raw if ok(kof(d))]
    return raw, (off + scanned if more else "")


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
    """Re-read names and exclusions from every file collection, in bounded batches.

    A Telegram file ID can appear in several collections. Its first copy in
    primary/cloud/archive order supplies the canonical name, while an explicit
    auto-group exclusion in any copy must be respected. Unlike the ordinary
    display lookup, a failed collection read aborts this write-side check.
    """
    ids = list(dict.fromkeys(i for i in ids if i))
    names, blocked = {}, set()
    for start in range(0, len(ids), 1000):
        batch = ids[start:start + 1000]
        for col in FILE_COLLECTIONS.values():
            async for d in col.find({"_id": {"$in": batch}}, {"file_name": 1, "group_auto_excluded": 1}):
                fid = d["_id"]
                names.setdefault(fid, str(d.get("file_name") or ""))
                if d.get("group_auto_excluded"):
                    blocked.add(fid)
    return names, blocked


async def _persist_joins(joins):
    """Serialize automatic joins with administrative membership changes."""
    async with _AUTO_GROUP_LOCK:
        return await _persist_joins_locked(joins)


async def _persist_joins_locked(joins):
    """Persist new same-name members without undoing an admin removal/move."""
    accepted, blocked = set(), set()
    try:
        by = {}
        for gid, i, n in joins:
            by.setdefault(gid, {})[i] = n
        all_ids = list({i for candidates in by.values() for i in candidates})
        fresh, blocked = await _live_group_files(all_ids)
        for gid, candidates in by.items():
            g = await groups.find_one({"_id": gid}, {"excluded": 1, "auto_keys": 1})
            if not g:
                continue
            claimed = set()
            async for other in groups.find({"_id": {"$ne": gid}, "members": {"$in": list(candidates)}}, {"members": 1}):
                claimed.update(other.get("members") or [])
            excluded = set(g.get("excluded") or [])
            blocked.update(i for i in candidates if i in excluded)
            keys = set(g.get("auto_keys") or [])
            items = {i: fresh[i] for i in candidates if i in fresh and i not in blocked
                     and i not in excluded and i not in claimed and _group_key(fresh[i]) in keys}
            if not items:
                continue
            ids = list(items)
            # If an admin excluded a member since the read, skip this batch. A later
            # search can retry the remaining members safely.
            result = await groups.update_one({"_id": gid, "excluded": {"$nin": ids}}, {"$addToSet": {
                "members": {"$each": ids},
                "files": {"$each": [{"id": i, "name": n or ""} for i, n in items.items()]}}})
            if result.matched_count:
                accepted.update((gid, i) for i in ids)
                await _mark_files(ids, gid, only_unassigned=True)
                logger.info(f"🗂️ Group #{gid}: {len(ids)} new file(s) added")
        _GH_CACHE.clear()
    except Exception as e:
        logger.warning(f"persist group joins failed: {e}")
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


async def _auto_persist(cards):
    """Save auto-groups before returning them, so the first response has a real ID.

    Return resolved memberships and exclusions. On database failure cards remain
    usable but unnumbered rather than displaying a fabricated ID.
    """
    resolved, blocked = {}, set()
    async with _AUTO_GROUP_LOCK:
        ids = list({v["file_id"] for c in cards for v in c.get("variants", []) if v.get("file_id")})
        try:
            fresh, blocked = await _live_group_files(ids)
        except Exception as e:
            logger.warning(f"auto group recheck failed: {e}")
            return resolved, blocked
        for c in cards:
            k = c.get("nkey")
            if not k:
                continue
            try:
                card_ids = dict.fromkeys(v.get("file_id") for v in c.get("variants", []) if v.get("file_id"))
                items = [(i, fresh[i]) for i in card_ids if i in fresh and _group_key(fresh[i]) == k]
                joins = []
                existing = await _manual_map(items, joins, blocked)
                if joins:
                    accepted, excluded = await _persist_joins_locked(joins)
                    blocked.update(excluded)
                    await _confirm_joined_members(existing, joins, accepted)
                resolved.update(existing)
                remaining = [(i, n) for i, n in items if i not in existing and i not in blocked]
                if len(remaining) < 2 or await groups.find_one({"auto_keys": k}, {"_id": 1}):
                    continue
                ids = [i for i, _ in remaining]
                num = await _next_group_num()
                gid = str(num)
                now = int(time.time())
                group = {
                    "_id": gid, "num": num, "name": (_group_title(remaining[0][1]) or remaining[0][1])[:200],
                    "members": ids, "files": [{"id": i, "name": n} for i, n in remaining],
                    "auto_keys": [k], "excluded": [], "auto_created": True, "group_type": "quality",
                    "thumb_fid": "", "thumb_col": "", "thumb_url": "",
                    "scanned_at": now, "created_at": now, "updated_at": now,
                }
                await groups.insert_one(group)
                await _mark_files(ids, gid)
                resolved.update({i: group for i in ids})
                _GH_CACHE.clear()
                logger.info(f"🗂️ Auto group #{gid} saved ({len(ids)} files)")
            except Exception as e:
                logger.warning(f"auto group persist failed: {e}")
    return resolved, blocked


_SIB_CACHE = {}
_SIB_TTL = 300


async def _siblings(key):
    """Is naam-key wali SAARI files (search se independent). 5 min cache."""
    now = time.time()
    c = _SIB_CACHE.get(key)
    if c and c[0] > now:
        return c[1]
    epoch = _SEARCH_CACHE_EPOCH
    try:
        docs = await asyncio.wait_for(find_phrase_files(key, 100), timeout=4)
    except Exception as e:
        logger.warning(f"siblings lookup failed for '{key}': {e}")
        return None
    docs = [d for d in docs if _group_key(d.get("file_name")) == key]
    if epoch == _SEARCH_CACHE_EPOCH:
        if len(_SIB_CACHE) > 800:
            _SIB_CACHE.clear()
        _SIB_CACHE[key] = (now + _SIB_TTL, docs)
    return docs


async def _expand_groups(results_list, manual, mode, joins=None, siblings=True, blocked=None):
    """Group kabhi adhoora nahi dikhna chahiye. Isliye:
    (1) Saved group ki saari members (kisi bhi collection se, search se match ho ya na ho)
    (2) Har group/file ki same-naam wali baaki saari files (auto-group ki siblings;
        saved group ke auto_keys wali nayi quality bhi) — search query kuch bhi ho, count same."""
    have = {r.get("file_id") for r in results_list}
    results_list = list(results_list)

    # (1) saved-group members
    need, seen_g = [], set()
    for g in list(manual.values()):
        if g["_id"] in seen_g:
            continue
        seen_g.add(g["_id"])
        for m in g.get("members", []):
            if m not in have:
                need.append((m, g))
    if need:
        try:
            docs = await get_files_by_ids([m for m, _ in need])
            owner = {m: g for m, g in need}
            extra = _build_results_list(docs, mode)
            for r in extra:
                manual[r["file_id"]] = owner[r["file_id"]]
                have.add(r["file_id"])
            results_list += extra
        except Exception as e:
            logger.warning(f"group expand failed: {e}")

    if not siblings:
        return results_list
    # (2) same-naam siblings.
    #     Saved group ko DB me `scanned_at` se yaad rehta hai: ek baar scan hone ke baad
    #     GROUP_RESCAN_SECS tak dobara scan nahi hota (members DB se hi aate hain).
    #     Scan me jo nayi file mile wo turant group ke members me DB me jud jaati hai.
    try:
        joins = joins if joins is not None else []
        now = time.time()
        targets, key_groups = {}, {}
        for r in results_list:
            g = manual.get(r.get("file_id"))
            if g:
                if (g.get("scanned_at") or 0) + GROUP_RESCAN_SECS > now:
                    continue
                for k in (g.get("auto_keys") or [])[:6]:
                    targets.setdefault(k, g)
                    key_groups.setdefault(g["_id"], set()).add(k)
            elif not blocked or r.get("file_id") not in blocked:
                k = _group_key(r.get("name"))
                if k:
                    targets.setdefault(k, None)
        keys = list(targets)[:40]
        if keys:
            sibs = await asyncio.gather(*[_siblings(k) for k in keys])
            sib_of = dict(zip(keys, sibs))
            cand = {}
            for k, docs in sib_of.items():
                owner = targets[k]
                for d in (docs or []):
                    i = d["_id"]
                    if i in have or i in cand:
                        continue
                    if owner and i in (owner.get("excluded") or []):
                        continue
                    cand[i] = (d, owner)
            if cand:
                if blocked is not None:
                    blocked.update(i for i, (d, _) in cand.items() if d.get("group_auto_excluded"))
                m2 = await _manual_map([(i, d.get("file_name")) for i, (d, _) in cand.items()], blocked=blocked)
                use = []
                for i, (d, owner) in cand.items():
                    if blocked and i in blocked:
                        continue
                    g2 = m2.get(i)
                    if owner:
                        if g2 and g2["_id"] != owner["_id"]:
                            continue
                        manual[i] = owner
                        joins.append((str(owner["_id"]), i, d.get("file_name")))
                    elif g2:
                        continue                      # kisi saved group ki hai, auto-sibling nahi
                    use.append(d)
                if use:
                    results_list += _build_results_list(use, mode)
            done = [gid for gid, ks in key_groups.items()
                    if all(k in sib_of and sib_of[k] is not None for k in ks)]
            if done:
                asyncio.create_task(_mark_scanned(done))
                for g in manual.values():
                    if g["_id"] in done:
                        g["scanned_at"] = int(now)
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


async def _finalize(results_list, want_group, gf="all", mode=DEFAULT_MEDIA_MODE, siblings=True):
    if not want_group:
        return await _annotate_raw_groups(results_list)
    joins = []
    blocked = {r.get("file_id") for r in results_list if r.get("group_auto_excluded")}
    manual = await _manual_map([(r.get("file_id"), r.get("name")) for r in results_list], joins, blocked)
    results_list = await _expand_groups(results_list, manual, mode, joins, siblings, blocked)
    if joins:
        accepted, excluded = await _persist_joins(joins)
        blocked.update(excluded)
        await _confirm_joined_members(manual, joins, accepted)
    out = group_results(results_list, manual, blocked)
    autos = [r for r in out if r.get("group") and not r.get("manual")]
    if autos:
        saved, newly_blocked = await _auto_persist(autos)
        manual.update(saved)
        blocked.update(newly_blocked)
        out = group_results(results_list, manual, blocked)
    if gf == "group":
        out = [r for r in out if r.get("group")]
    elif gf in ("quality", "series"):
        out = [r for r in out if r.get("group") and r.get("group_type") == gf]
    elif gf == "single":
        out = [r for r in out if not r.get("group")]
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
    return group_results(_build_results_list(ordered, mode), manual)


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

    # 🗂️ GROUP-FIRST: pehle groups, phir ungrouped files (sirf "all" collections par)
    if want_group and col == "all":
        gs = await _group_hits(q)
        if gs is not None:
            if gf in ("quality", "series"):
                gs = [g for g in gs if group_type(g) == gf]
            cards, nxt = await _grouped_first_page(q, off, lim, mode, gf, gs)
            return web.json_response({
                "results": cards,
                "total": off + len(cards) + (1 if nxt else 0),
                "next_offset": nxt,
                "is_admin": role == "admin",
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
            await groups.update_many({"files.id": fid}, {"$set": {
                "files.$.name": new_name, "scanned_at": 0, "updated_at": int(time.time())}})
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


async def _group_cleanup(pull_ids=None, strict=False):
    """Deleted files ko groups se hatao, khali groups mitao, caches saaf karo."""
    try:
        if pull_ids:
            await groups.update_many({"members": {"$in": pull_ids}}, {"$pull": {
                "members": {"$in": pull_ids}, "files": {"id": {"$in": pull_ids}},
                "episode_order": {"$in": pull_ids}, "episode_labels": {"id": {"$in": pull_ids}}}})
            await groups.update_many({"thumb_fid": {"$in": pull_ids}},
                                     {"$set": {"thumb_fid": "", "thumb_col": ""}})
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
SCAN_MAX_GROUP = 30        # isse bade bucket generic naam maane jaate hain, group nahi bante


async def _scan_all_groups():
    """Poori library (primary+cloud+archive) ek baar scan karke PERMANENT groups banata hai.
    - Same naam-key wali 2+ files → ek group (apna number, members DB me, file par group_id mark)
    - Pehle se bane groups me sirf nayi files jodta hai
    - Jo file kisi group ki `excluded` (blacklist) me hai wo wahan nahi jodi jaati
    - Jo file kisi aur group ki member hai use chhedta nahi
    Dobara chalana safe hai."""
    st = SCAN_STATE
    st.update(running=True, phase="groups load ho rahe hain", scanned=0, total=0, created=0,
              added=0, skipped_big=0, skipped_keys=[], fixed_marks=0, existing_groups=0,
              multi_buckets=0, error="", started=time.time(), finished=0)
    try:
        key2g, owner = {}, {}
        async for g in groups.find({}, {"auto_keys": 1, "members": 1, "excluded": 1}):
            gd = {"id": g["_id"], "excl": set(g.get("excluded") or [])}
            for m in g.get("members", []):
                owner[m] = g["_id"]
            for k in g.get("auto_keys", []):
                key2g.setdefault(k, gd)

        st["existing_groups"] = len({g["id"] for g in key2g.values()})
        total = 0
        for col in FILE_COLLECTIONS.values():
            try:
                total += await col.estimated_document_count()
            except Exception:
                pass
        st["total"] = total

        st["phase"] = "files scan ho rahi hain"
        buckets, canonical_names, excluded_ids = {}, {}, set()
        fix_set, fix_unset = {}, {}
        for cname, col in FILE_COLLECTIONS.items():
            async for d in col.find({}, {"file_name": 1, "group_id": 1, "group_auto_excluded": 1}).batch_size(2000):
                st["scanned"] += 1
                if st["scanned"] % 2000 == 0:
                    await asyncio.sleep(0)
                og, cg = owner.get(d["_id"]), d.get("group_id")
                if og and cg != og:
                    fix_set.setdefault((cname, og), []).append(d["_id"])      # member hai par mark nahi/galat
                elif not og and cg:
                    fix_unset.setdefault((cname, cg), []).append(d["_id"])  # remember the observed mark
                if d.get("group_auto_excluded") and not og:
                    excluded_ids.add(d["_id"])  # any copy can carry the admin's decision
                nm = str(d.get("file_name") or "")
                nm, k = canonical_names.setdefault(d["_id"], (nm, _group_key(nm)))
                if len(k) >= 3:
                    # Copies with divergent names follow the first collection's
                    # canonical name, but all copies still receive group marks.
                    buckets.setdefault(k, []).append((d["_id"], nm, cname))

        st["phase"] = "groups tay ho rahe hain"
        new_docs, adds, marks = [], {}, dict(fix_set)
        now = int(time.time())
        for k, items in buckets.items():
            items = [item for item in items if item[0] not in excluded_ids]
            g = key2g.get(k)
            unique_count = len({i for i, _, _ in items})
            if unique_count >= 2:
                st["multi_buckets"] += 1
            if g:
                fresh = [it for it in items if it[0] not in owner and it[0] not in g["excl"]]
                if not fresh:
                    continue
                adds.setdefault(g["id"], []).extend(fresh)
                st["added"] += len({i for i, _, _ in fresh})
                continue
            if unique_count < 2:
                continue
            if unique_count > SCAN_MAX_GROUP:
                st["skipped_big"] += 1
                if len(st["skipped_keys"]) < 20:
                    st["skipped_keys"].append(f"{k} ({unique_count} files)")
                continue
            cand = [it for it in items if it[0] not in owner]
            if len({i for i, _, _ in cand}) < 2:
                continue
            new_docs.append((k, cand))

        if new_docs:
            async with _AUTO_GROUP_LOCK:
                keys = [k for k, _ in new_docs]
                existing = set()
                for start in range(0, len(keys), 1000):
                    async for g in groups.find({"auto_keys": {"$in": keys[start:start + 1000]}}, {"auto_keys": 1}):
                        existing.update(g.get("auto_keys") or [])
                new_docs = [entry for entry in new_docs if entry[0] not in existing]

                # Scanning a large library takes time. Re-check current ownership,
                # names and exclusions before turning the old snapshot into groups.
                candidate_ids = list({i for _, cand in new_docs for i, _, _ in cand})
                fresh, blocked = await _live_group_files(candidate_ids)
                claimed = set()
                for start in range(0, len(candidate_ids), 1000):
                    batch = candidate_ids[start:start + 1000]
                    async for g in groups.find({"members": {"$in": batch}}, {"members": 1}):
                        claimed.update(g.get("members") or [])
                checked = []
                for k, cand in new_docs:
                    cand = [(i, fresh[i], cn) for i, _, cn in cand
                            if i in fresh and i not in blocked and i not in claimed and _group_key(fresh[i]) == k]
                    if len({i for i, _, _ in cand}) >= 2:
                        checked.append((k, cand))
                new_docs = checked
                if new_docs:
                    seq = await group_seq.find_one_and_update(
                        {"_id": "seq"}, {"$inc": {"n": len(new_docs)}}, upsert=True, return_document=ReturnDocument.AFTER)
                    start = int(seq["n"]) - len(new_docs) + 1
                    docs = []
                    for idx, (k, cand) in enumerate(new_docs):
                        num = start + idx
                        gid = str(num)
                        unique_files = {}
                        for i, n, _ in cand:
                            unique_files.setdefault(i, n)
                        docs.append({
                            "_id": gid, "num": num, "name": (_group_title(cand[0][1]) or cand[0][1])[:200],
                            "members": list(unique_files),
                            "files": [{"id": i, "name": n} for i, n in unique_files.items()],
                            "auto_keys": [k], "excluded": [], "auto_created": True, "scan_created": True,
                            "group_type": "quality",
                            "thumb_fid": "", "thumb_col": "", "thumb_url": "",
                            "scanned_at": now, "created_at": now, "updated_at": now})
                        for i, _, cn in cand:
                            marks.setdefault((cn, gid), []).append(i)
                    st["created"] = len(docs)
                    st["phase"] = "groups DB me save ho rahe hain"
                    for n in range(0, len(docs), 500):
                        await groups.insert_many(docs[n:n + 500], ordered=False)

        if adds:
            # Reuse search's guarded join path: the scan snapshot may be stale if
            # an admin removed or moved a member while the scan was running.
            await _persist_joins([(gid, i, n) for gid, items in adds.items() for i, n, _ in items])
            await _mark_scanned(adds.keys())

        st["phase"] = "files par group_id mark ho raha hai"
        async with _AUTO_GROUP_LOCK:
            # Revalidate the snapshot: a group may have been edited/deleted mid-scan.
            live_members = {}
            gids = list({gid for _, gid in marks})
            for start in range(0, len(gids), 1000):
                async for g in groups.find({"_id": {"$in": gids[start:start + 1000]}}, {"members": 1}):
                    live_members[g["_id"]] = set(g.get("members") or [])
            per_col = {}
            for (cn, gid), ids in marks.items():
                members_now = live_members.get(gid, set())
                ids = [i for i in ids if i in members_now]
                for start in range(0, len(ids), 1000):
                    per_col.setdefault(cn, []).append(UpdateMany(
                        {"_id": {"$in": ids[start:start + 1000]}, "group_auto_excluded": {"$ne": True}},
                        {"$set": {"group_id": gid}}))
            for cn, ops in per_col.items():
                for n in range(0, len(ops), 500):
                    await FILE_COLLECTIONS[cn].bulk_write(ops[n:n + 500], ordered=False)
                    await asyncio.sleep(0)

            stale_ids = {i for ids in fix_unset.values() for i in ids}
            still_owned = set()
            stale_list = list(stale_ids)
            for start in range(0, len(stale_list), 1000):
                async for g in groups.find({"members": {"$in": stale_list[start:start + 1000]}}, {"members": 1}):
                    still_owned.update(i for i in (g.get("members") or []) if i in stale_ids)
            for (cn, observed_gid), ids in fix_unset.items():
                ids = [i for i in ids if i not in still_owned]
                ops = [UpdateMany({"_id": {"$in": ids[n:n + 1000]}, "group_id": observed_gid},
                                  {"$unset": {"group_id": ""}})
                       for n in range(0, len(ids), 1000)]
                for n in range(0, len(ops), 500):
                    await FILE_COLLECTIONS[cn].bulk_write(ops[n:n + 500], ordered=False)
            st["fixed_marks"] = sum(len(v) for v in fix_set.values()) + sum(len(v) for v in fix_unset.values())

        _invalidate_search_caches()
        st["phase"] = "complete"
    except Exception as e:
        logger.error(f"group scan failed: {e}")
        st["error"] = str(e)
        st["phase"] = "error"
    finally:
        st["running"] = False
        st["finished"] = time.time()
        logger.info(f"🗂️ Group scan done: scanned={st.get('scanned')}/{st.get('total')} "
                    f"existing_groups={st.get('existing_groups')} same-name buckets={st.get('multi_buckets')} "
                    f"created={st.get('created')} added={st.get('added')} fixed_marks={st.get('fixed_marks')} "
                    f"skipped_big={st.get('skipped_big')} err={st.get('error')}")
        if st.get("skipped_keys"):
            logger.info("🗂️ Skipped (30+ files, bahut aam naam): " + " | ".join(st["skipped_keys"]))


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
    q = req.query.get("q", "").strip().lstrip("#")
    if not q:
        flt = {}
    elif q.isdigit():
        flt = {"$or": [{"_id": q}, {"name": {"$regex": re.escape(q), "$options": "i"}}]}
    else:
        flt = {"name": {"$regex": re.escape(q), "$options": "i"}}
    out = []
    async for g in groups.find(flt).sort("updated_at", -1).limit(25):
        out.append({"id": str(g["_id"]), "num": g.get("num", ""), "name": g.get("name", ""),
                    "group_type": group_type(g), "count": len(g.get("members", []))})
    return web.json_response({"groups": out}, dumps=fast_json)


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
        if not gid and not name:
            return web.json_response({"error": "Group ka naam likhiye!"}, status=400, dumps=fast_json)
        docs = await get_files_by_ids(file_ids)
        by_id = {d["_id"]: d for d in docs}
        if any(fid not in by_id for fid in file_ids):
            return web.json_response({"error": "Some selected files no longer exist. Refresh and try again."}, status=400, dumps=fast_json)
        items = [(fid, str(by_id[fid].get("file_name") or "")) for fid in file_ids]
        auto_keys = list({k for k in (_group_key(n) for _, n in items) if k})
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
            await groups.update_one({"_id": gid}, {"$addToSet": add,
                "$set": {"updated_at": now, "scanned_at": 0},
                "$pull": {"excluded": {"$in": file_ids}}})
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
        await groups.update_many(other, {
            "$pull": {"members": {"$in": file_ids}, "files": {"id": {"$in": file_ids}},
                      "episode_order": {"$in": file_ids}, "episode_labels": {"id": {"$in": file_ids}}},
            "$addToSet": {"excluded": {"$each": file_ids}}, "$set": {"updated_at": now}})
        await groups.update_many({"_id": {"$ne": gid}, "thumb_fid": {"$in": file_ids}},
                                 {"$set": {"thumb_fid": "", "thumb_col": ""}})
        await _mark_files(file_ids, gid)
        await _group_cleanup()
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
        await _group_cleanup()
        return web.json_response({"success": True}, dumps=fast_json)
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
        await groups.update_one({"_id": tgt_id}, {"$addToSet": add, "$set": updates})
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
