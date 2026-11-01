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
from lru import LRU
from aiohttp import web
from pymongo import ReturnDocument, UpdateOne, UpdateMany

# कस्टमाइज्ड कोर यूटिल्स और कन्फर्म कंट्रोल्स इम्पोर्ट्स
from utils import temp, get_size, is_premium, get_duration_str
# ✅ SYNC: THUMBNAIL_STORAGE_CHANNEL को इम्पोर्ट किया गया है पृथक स्टोरेज के लिए
from info import BIN_CHANNEL, ADMINS, BOT_TOKEN, MAX_WEB_RESULTS, MAX_THUMB_CACHE, IS_PREMIUM, THUMBNAIL_STORAGE_CHANNEL
# यहाँ db_stats के लिए 'db as filter_db' ऐड किया गया है
from database.ia_filterdb import COLLECTIONS, FILE_COLLECTIONS, groups, group_seq, get_files_by_ids, find_phrase_files, search_groups, get_groups_by_ids, get_search_results, get_recent_files, db as filter_db, delete_single_file, build_media_meta, doc_resolution_text, msg_media
from media_probe import probe_telegram_file, should_probe_media
from database.users_chats_db import db
# ✅ SYNC FIX: cookie-session identity check अब यहाँ दोबारा नहीं लिखा, web_assets से reuse हो रहा है
# ✅ DRY: fast_json भी अब web_assets से ही आता है (पहले search_api/actor_routes/
# post_routes तीनों में इसकी अलग-अलग copy थी)।
from web.web_assets import get_auth as web_get_auth, fast_json, DEFAULT_MEDIA_MODE

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

# ─────────────────────────────────────────────────────────
# 📸 OPTIMIZED THUMBNAIL ENGINE (Bytes-in-RAM True LRU)
# ─────────────────────────────────────────────────────────
async def _get_or_fetch_thumb(fid, col_name="primary", is_retry=False):
    cache_key = f"{col_name}:{fid}"

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
                    {"thumb_url": 1, "duration": 1, "meta": 1,
                     "file_ref": 1, "file_size": 1, "file_name": 1}
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

                for attempt in range(5):
                    try:
                        msg = await temp.BOT.send_cached_media(chat_id=BIN_CHANNEL, file_id=fid)
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
                                await target_collection.update_one(
                                    {"_id": fid},
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

        docs, next_off = await _fetch_page(q, col, prefetch_offset, lim, group, gf)

        if docs:
            PREFETCH_CACHE[cache_key] = (docs, next_off)
            
            if mode != "none":
                warmup_docs = docs if tg_id in ADMINS else docs[:5]
                for doc in warmup_docs:
                    asyncio.create_task(
                        _get_or_fetch_thumb(doc["_id"], col_name=doc.get("source_col", "primary"))
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
            raw_thumb = d.get("thumb_url", "")
            # ⚠️ pehle yahan file_id ke sirf last 8 chars the — Telegram photo ids ka tail
            # aksar same hota hai, to naya thumbnail upload hone par bhi URL (aur browser
            # cache) wahi rehta tha. Ab poore thumb_url ka hash: thumbnail badla → URL badla.
            v_salt = f"{zlib.crc32(raw_thumb.encode('utf-8')):08x}" if (raw_thumb and raw_thumb.startswith("TG_ID:")) else "0"
            tg_thumb = f"/api/thumb?file_id={db_id}&col={source_collection_name}&v={v_salt}"
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
            "watch": f"/setup_stream?file_id={fid}&mode=watch",
            "download": f"/setup_stream?file_id={fid}&mode=download",
            "caption": d.get("caption", ""),  # ✅ यहाँ नया बदलाव किया गया है
        })
    return results_list


# ─────────────────────────────────────────────────────────
# 🗂️ QUALITY GROUPING — ek hi title ki alag-alag quality ek card me
# Dashboard `&group=1` bhejta hai. Naam se resolution token (480p/720p/1080p/1440p/2160p/4k)
# aur aakhri extension (mp4/mkv…) hata kar baaki naam EXACT same ho → ek group.
# Conservative hai: codec/uploader tag (x265, Sky, UnTuch…) alag ho to alag card rahenge.
# Grouping sirf is page ke results me hoti hai (offset-pagination ke saath safe).
# ─────────────────────────────────────────────────────────
_RES_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:(?:240|360|480|540|576|720|1080|1440|2160|4320)\s*[pP]|4[kK]|8[kK]|[uU][hH][dD])(?![A-Za-z0-9])")
_EXT_TAIL_RE = re.compile(
    r"[\s._\-]*(?<![A-Za-z0-9])(?:mp4|mkv|avi|mov|webm|m4v|ts|wmv|flv|mpg|mpeg)\s*$", re.I)
_SEP_RE = re.compile(r"[\s|_\-–.,:;()\[\]{}+~!@#$%^&*=/\\'\"`<>?·•]+")


def _group_key(name):
    """Quality/extension hata kar normalized key. Khali ho to '' (matlab group mat karo)."""
    s = _EXT_TAIL_RE.sub("", str(name or ""))
    s = _RES_TOKEN_RE.sub(" ", s).lower()
    return _SEP_RE.sub(" ", s).strip()


def _group_title(name):
    """Dikhane layak saaf title (original case me), quality + extension hata kar."""
    s = _EXT_TAIL_RE.sub("", str(name or ""))
    s = _RES_TOKEN_RE.sub(" ", s)
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
async def _manual_map(items, joins=None):
    """items = [(file_id, file_name)] → {file_id: group_doc}.
    Match: (1) group ke members me file_id, ya (2) naam ki auto-key group ki auto_keys me
    (isse baad me upload hui nayi quality bhi apne-aap isi group me aa jaati hai).
    Admin ne jo file group se nikali (excluded) wo auto-key se wapas nahi judti."""
    items = [(i, n) for i, n in items if i]
    out = {}
    if not items:
        return out
    ids = [i for i, _ in items]
    keys = list({k for k in (_group_key(n) for _, n in items) if k})
    try:
        cond = [{"members": {"$in": ids}}]
        if keys:
            cond.append({"auto_keys": {"$in": keys}})
        found = [g async for g in groups.find({"$or": cond})]
        by_key = {}
        for g in found:
            for k in g.get("auto_keys", []):
                by_key.setdefault(k, g)
        for g in found:                              # explicit membership sabse upar
            for m in g.get("members", []):
                out[m] = g
        for i, n in items:
            if i in out:
                continue
            g = by_key.get(_group_key(n))
            if g and i not in (g.get("excluded") or []):
                out[i] = g
                if joins is not None:           # nayi file, same naam-key: group me turant joddni hai
                    joins.append((str(g["_id"]), i, n))
    except Exception as e:
        logger.warning(f"manual group lookup failed: {e}")
    return out


def _bucket_key(file_id, name, manual):
    """Card-bucket ki key: manual group > auto (naam se) > akeli file."""
    g = manual.get(file_id)
    if g:
        return "m:" + str(g["_id"])
    k = _group_key(name)
    return ("a:" + k) if k else ("s:" + str(file_id))


def group_results(results, manual=None):
    """results_list ko quality-groups me badalta hai.

    - Akeli file → jaisi thi waisi (koi badlaav nahi)
    - 2+ files ek bucket me → {"group": True, "key", "title", "count", "type", "tg_thumb",
      "duration", "size", "source", "manual", "gid", "chips": [...], "variants": [...]}
    - Page me group ki jagah uski PEHLI file ki position rehti hai (search ranking bani rehti hai).
    - Input dicts mutate nahi hote (TRENDING_CACHE unhi dicts ko share karta hai).
    """
    manual = manual or {}
    order, buckets = [], {}
    for r in results:
        k = _bucket_key(r.get("file_id"), r.get("name"), manual)
        if k.startswith("s:"):                      # akeli file
            order.append(("single", r))
            continue
        if k not in buckets:
            buckets[k] = []
            order.append(("group", k))
        buckets[k].append(r)

    out = []
    for kind, v in order:
        if kind == "single":
            out.append(v)
            continue
        items = buckets[v]
        if len(items) == 1:
            out.append(items[0])
            continue
        is_manual = v.startswith("m:")
        mg = manual.get(items[0].get("file_id")) if is_manual else None
        variants = []
        for it in items:
            lab, eh = _quality_label(it.get("res"), it.get("name"))
            variants.append((eh, dict(it, ql=lab, gid=(str(mg["_id"]) if mg else ""))))
        variants.sort(key=lambda x: x[0])           # stable: barabar quality me original order
        vlist = [d for _, d in variants]
        chips, seen = [], {}
        for d in vlist:
            lab = d["ql"] or "?"
            if lab in seen:
                seen[lab]["count"] += 1
            else:
                seen[lab] = {"label": lab, "count": 1}
                chips.append(seen[lab])

        rep = vlist[-1]                              # sabse badi quality = master file
        # 🖼️ Master thumbnail: manual group me admin ne jo chuna wo; warna sabse badi
        # quality wali file ka thumbnail (single file jaisa hi bada poster).
        thumb = next((d.get("tg_thumb") for d in reversed(vlist) if d.get("tg_thumb")), "")
        if mg and thumb:
            ts = int(mg.get("updated_at") or 0)
            if mg.get("thumb_url"):                  # 1) admin ka upload kiya custom thumbnail
                thumb = f"/api/group/thumb?gid={mg['_id']}&v={ts}"
            elif mg.get("thumb_fid") and mg.get("thumb_col"):   # 2) kisi member ka chuna hua
                thumb = (f"/api/thumb?file_id={mg['thumb_fid']}&col={mg['thumb_col']}&v={ts}")
        if mg:
            title = _html.escape(str(mg.get("name") or ""))
            key = "m" + str(mg["_id"])
        else:
            title = _html.escape(_group_title(items[0].get("name")) or str(items[0].get("name") or ""))
            key = f"{zlib.crc32(v.encode('utf-8')):08x}"
        out.append({
            "group": True,
            "manual": bool(mg),
            "gid": str(mg["_id"]) if mg else "",
            "nkey": "" if mg else v[2:],
            "num": (mg.get("num") or "") if mg else "",
            "custom_thumb": bool(mg and mg.get("thumb_url")),
            "key": key,
            "title": title,
            "count": len(vlist),
            "type": rep.get("type", "VIDEO"),
            "tg_thumb": thumb,
            "thumb_fid": (mg.get("thumb_fid") or "") if mg else "",
            "duration": rep.get("duration", ""),
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
    """(docs, next_offset). group=False → purana behaviour (lim raw files).
    gf: "all" | "group" (sirf 2+ quality wale cards) | "single" (sirf ungrouped files).
    Filter laga ho to bhi page me `lim` matching cards banane ki koshish hoti hai."""
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
    raw, cur, more, manual = [], off, True, {}

    def kof(d):
        return _bucket_key(d.get("_id"), d.get("file_name"), manual)

    def count_buckets(rows):
        cnt = {}
        for d in rows:
            k = kof(d)
            cnt[k] = cnt.get(k, 0) + 1
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
        manual.update(await _manual_map([(d.get("_id"), d.get("file_name")) for d in docs]))
        more = bool(nxt)
        cur = nxt if nxt != "" else None

        cnt = count_buckets(raw)

        def ok(k):
            if gf == "group":
                return cnt[k] >= 2
            if gf == "single":
                return cnt[k] == 1
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
    if gf == "group":
        raw = [d for d in raw if cnt[kof(d)] >= 2]
    elif gf == "single":
        raw = [d for d in raw if cnt[kof(d)] == 1]
    return raw, (off + scanned if more else "")


GROUP_RESCAN_SECS = 6 * 3600     # saved group ko itni der me ek baar hi naye saathi ke liye scan karte hain


async def _mark_files(ids, gid):
    """File ke apne doc me `group_id` mark (gid="" ho to mark hata do)."""
    ids = [i for i in ids if i]
    if not ids:
        return
    upd = {"$set": {"group_id": str(gid)}} if gid else {"$unset": {"group_id": ""}}
    for col in FILE_COLLECTIONS.values():
        try:
            await col.update_many({"_id": {"$in": ids}}, upd)
        except Exception as e:
            logger.warning(f"mark group_id failed ({col.name}): {e}")


async def _persist_joins(joins):
    """Search/scan me mili nayi files ko saved group ke members me DB me jod do + file par mark."""
    try:
        by = {}
        for gid, i, n in joins:
            by.setdefault(gid, {})[i] = n
        for gid, m in by.items():
            await groups.update_one({"_id": gid}, {"$addToSet": {
                "members": {"$each": list(m)},
                "files": {"$each": [{"id": i, "name": n or ""} for i, n in m.items()]}}})
            await _mark_files(list(m), gid)
            logger.info(f"🗂️ Group #{gid}: {len(m)} nayi file(s) DB me jodi gayi")
        _GH_CACHE.clear()
    except Exception as e:
        logger.warning(f"persist group joins failed: {e}")


async def _mark_scanned(gids):
    try:
        await groups.update_many({"_id": {"$in": list(gids)}}, {"$set": {"scanned_at": int(time.time())}})
    except Exception as e:
        logger.warning(f"mark scanned failed: {e}")


_AUTO_SAVING = set()


async def _auto_persist(cards):
    """Har auto-group (2+ files) ko PERMANENT group bana do: apna number, members DB me,
    aur har file par `group_id` mark. Uske baad wo file jab bhi dikhegi, apne group ke saath dikhegi."""
    for c in cards:
        k = c.get("nkey")
        if not k or k in _AUTO_SAVING:
            continue
        _AUTO_SAVING.add(k)
        try:
            if await groups.find_one({"auto_keys": k}, {"_id": 1}):
                continue                                  # is naam-key ka saved group pehle se hai
            items = [(v["file_id"], v.get("name") or "") for v in c.get("variants", []) if v.get("file_id")]
            if len(items) < 2:
                continue
            ids = [i for i, _ in items]
            num = await _next_group_num()
            gid = str(num)
            now = int(time.time())
            await groups.insert_one({
                "_id": gid, "num": num, "name": _html.unescape(str(c.get("title") or ""))[:200],
                "members": ids, "files": [{"id": i, "name": n} for i, n in items],
                "auto_keys": [k], "excluded": [], "auto_created": True,
                "thumb_fid": "", "thumb_col": "", "thumb_url": "",
                "scanned_at": now, "created_at": now, "updated_at": now})
            await _mark_files(ids, gid)
            _GH_CACHE.clear()
            logger.info(f"🗂️ Auto group #{gid} permanent bana ({len(ids)} files)")
        except Exception as e:
            logger.warning(f"auto group persist failed: {e}")
        finally:
            _AUTO_SAVING.discard(k)


_SIB_CACHE = {}
_SIB_TTL = 300


async def _siblings(key):
    """Is naam-key wali SAARI files (search se independent). 5 min cache."""
    now = time.time()
    c = _SIB_CACHE.get(key)
    if c and c[0] > now:
        return c[1]
    try:
        docs = await asyncio.wait_for(find_phrase_files(key, 100), timeout=4)
    except Exception as e:
        logger.warning(f"siblings lookup failed for '{key}': {e}")
        return None
    docs = [d for d in docs if _group_key(d.get("file_name")) == key]
    if len(_SIB_CACHE) > 800:
        _SIB_CACHE.clear()
    _SIB_CACHE[key] = (now + _SIB_TTL, docs)
    return docs


async def _expand_groups(results_list, manual, mode, joins=None, siblings=True):
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
            else:
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
                m2 = await _manual_map([(i, d.get("file_name")) for i, (d, _) in cand.items()])
                use = []
                for i, (d, owner) in cand.items():
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


async def _finalize(results_list, want_group, gf="all", mode=DEFAULT_MEDIA_MODE, siblings=True):
    if not want_group:
        return results_list
    joins = []
    manual = await _manual_map([(r.get("file_id"), r.get("name")) for r in results_list], joins)
    results_list = await _expand_groups(results_list, manual, mode, joins, siblings)
    if joins:
        asyncio.create_task(_persist_joins(joins))      # nayi files DB me group me jod do (background)
    out = group_results(results_list, manual)
    autos = [r for r in out if r.get("group") and not r.get("manual")]
    if autos:
        asyncio.create_task(_auto_persist(autos))      # auto-group ko permanent group bana do (background)
    if gf == "group":
        out = [r for r in out if r.get("group")]
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
    file_cards = [c for c in file_cards if not (c.get("group") and c.get("manual") and c.get("gid") in seen)]
    return cards + file_cards, ((G + nf) if nf != "" else "")


@search_routes.get("/api/search")
async def api_search(req):
    role, tg_id = await get_user_role(req)
    if not role:
        return web.json_response({"error": "Unauthorized Access!"}, status=403, dumps=fast_json)

    q = req.query.get("q", "").strip()
    off = req.query.get("offset", "0")
    col = req.query.get("col", "all").lower()
    mode = req.query.get("mode", DEFAULT_MEDIA_MODE).lower()
    want_group = req.query.get("group", "") == "1"     # dashboard hi bhejta hai; baaki users raw list
    gf = req.query.get("gf", "all").lower()
    gf = {"ungroup": "single", "single": "single", "group": "group"}.get(gf, "all") if want_group else "all"
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
            cards, nxt = await _grouped_first_page(q, off, lim, mode, gf, gs)
            return web.json_response({
                "results": cards,
                "total": off + len(cards) + (1 if nxt else 0),
                "next_offset": nxt,
                "is_admin": role == "admin",
            }, dumps=fast_json)

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

    if off == 0 and results_list:
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

    res = await _get_or_fetch_thumb(fid, col_name=col_name, is_retry=is_retry)
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
    """watch/download mode को सही route path में बदलता है (unknown mode → watch)"""
    return f"/{'download' if mode == 'download' else 'watch'}/{msg_id}"


async def _tunnel_stream(fid: str, mode: str) -> str:
    """BIN_CHANNEL में file भेजकर उसका watch/download path लौटाता है"""
    msg = await temp.BOT.send_cached_media(chat_id=BIN_CHANNEL, file_id=fid)
    await db.add_to_delete_queue(BIN_CHANNEL, msg.id, 3600)
    if mode == "watch":
        await db.track_video_play()
    return stream_target_path(msg.id, mode)


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
            await _group_cleanup(pull_ids=[fid])
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
        
        PREFETCH_CACHE.clear()
        TRENDING_CACHE.clear()

        return web.json_response({"success": True}, dumps=fast_json)
    except Exception as e:
        logger.error(f"Edit/Transfer Error: {e}")
        return web.json_response({"error": str(e)}, status=500, dumps=fast_json)


# ─────────────────────────────────────────────────────────
# 🗂️ ADMIN: QUALITY-GROUPS (DB me save, har group ka apna number)
#   QualityGroups doc: {_id:"12", num:12, name, members:[file_id], auto_keys:[naam-key],
#     excluded:[file_id], thumb_fid, thumb_col, thumb_url("TG_ID:.." custom upload),
#     created_at, updated_at}
#   auto_keys ki wajah se baad me upload hui nayi quality (same naam) apne-aap group me judti hai.
# ─────────────────────────────────────────────────────────
async def _next_group_num():
    d = await group_seq.find_one_and_update(
        {"_id": "seq"}, {"$inc": {"n": 1}}, upsert=True, return_document=ReturnDocument.AFTER)
    return int(d["n"])


async def _group_cleanup(pull_ids=None):
    """Deleted files ko groups se hatao, khali groups mitao, caches saaf karo."""
    try:
        if pull_ids:
            await groups.update_many({"members": {"$in": pull_ids}}, {"$pull": {"members": {"$in": pull_ids}, "files": {"id": {"$in": pull_ids}}}})
        await groups.delete_many({"members": {"$size": 0}})
    except Exception as e:
        logger.warning(f"group cleanup failed: {e}")
    PREFETCH_CACHE.clear()
    TRENDING_CACHE.clear()
    _GH_CACHE.clear()


async def _admin_json(req):
    role, _ = await get_user_role(req)
    if role != "admin":
        return None, web.json_response({"error": "Core Admin Authorization Required!"}, status=403, dumps=fast_json)
    try:
        return await req.json(), None
    except Exception:
        return None, web.json_response({"error": "Invalid request body!"}, status=400, dumps=fast_json)


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
              added=0, skipped_big=0, error="", started=time.time(), finished=0)
    try:
        key2g, owner = {}, {}
        async for g in groups.find({}, {"auto_keys": 1, "members": 1, "excluded": 1}):
            gd = {"id": g["_id"], "excl": set(g.get("excluded") or [])}
            for m in g.get("members", []):
                owner[m] = g["_id"]
            for k in g.get("auto_keys", []):
                key2g.setdefault(k, gd)

        total = 0
        for col in FILE_COLLECTIONS.values():
            try:
                total += await col.estimated_document_count()
            except Exception:
                pass
        st["total"] = total

        st["phase"] = "files scan ho rahi hain"
        buckets = {}
        fix_set, fix_unset = {}, {}
        for cname, col in FILE_COLLECTIONS.items():
            async for d in col.find({}, {"file_name": 1, "group_id": 1}).batch_size(2000):
                st["scanned"] += 1
                og, cg = owner.get(d["_id"]), d.get("group_id")
                if og and cg != og:
                    fix_set.setdefault((cname, og), []).append(d["_id"])      # member hai par mark nahi/galat
                elif not og and cg:
                    fix_unset.setdefault(cname, []).append(d["_id"])          # mark hai par kisi group me nahi
                nm = d.get("file_name") or ""
                k = _group_key(nm)
                if len(k) >= 3:
                    buckets.setdefault(k, []).append((d["_id"], nm, cname))
                if st["scanned"] % 2000 == 0:
                    await asyncio.sleep(0)

        st["phase"] = "groups tay ho rahe hain"
        new_docs, adds, marks = [], {}, dict(fix_set)
        now = int(time.time())
        for k, items in buckets.items():
            g = key2g.get(k)
            if g:
                fresh = [it for it in items if it[0] not in owner and it[0] not in g["excl"]]
                if not fresh:
                    continue
                adds.setdefault(g["id"], []).extend(fresh)
                for i, _, cn in fresh:
                    marks.setdefault((cn, g["id"]), []).append(i)
                st["added"] += len(fresh)
                continue
            if len(items) < 2:
                continue
            if len(items) > SCAN_MAX_GROUP:
                st["skipped_big"] += 1
                continue
            cand = [it for it in items if it[0] not in owner]
            if len(cand) < 2:
                continue
            new_docs.append((k, cand))

        if new_docs:
            seq = await group_seq.find_one_and_update(
                {"_id": "seq"}, {"$inc": {"n": len(new_docs)}}, upsert=True, return_document=ReturnDocument.AFTER)
            start = int(seq["n"]) - len(new_docs) + 1
            docs = []
            for idx, (k, cand) in enumerate(new_docs):
                num = start + idx
                gid = str(num)
                docs.append({
                    "_id": gid, "num": num, "name": (_group_title(cand[0][1]) or cand[0][1])[:200],
                    "members": [i for i, _, _ in cand],
                    "files": [{"id": i, "name": n} for i, n, _ in cand],
                    "auto_keys": [k], "excluded": [], "auto_created": True, "scan_created": True,
                    "thumb_fid": "", "thumb_col": "", "thumb_url": "",
                    "scanned_at": now, "created_at": now, "updated_at": now})
                for i, _, cn in cand:
                    marks.setdefault((cn, gid), []).append(i)
            st["created"] = len(docs)
            st["phase"] = "groups DB me save ho rahe hain"
            for n in range(0, len(docs), 500):
                await groups.insert_many(docs[n:n + 500], ordered=False)

        if adds:
            ops = [UpdateOne({"_id": gid}, {"$addToSet": {
                "members": {"$each": [i for i, _, _ in its]},
                "files": {"$each": [{"id": i, "name": n} for i, n, _ in its]}},
                "$set": {"scanned_at": now}}) for gid, its in adds.items()]
            for n in range(0, len(ops), 500):
                await groups.bulk_write(ops[n:n + 500], ordered=False)

        st["phase"] = "files par group_id mark ho raha hai"
        per_col = {}
        for (cn, gid), ids in marks.items():
            per_col.setdefault(cn, []).append(UpdateMany({"_id": {"$in": ids}}, {"$set": {"group_id": gid}}))
        for cn, ops in per_col.items():
            for n in range(0, len(ops), 500):
                await FILE_COLLECTIONS[cn].bulk_write(ops[n:n + 500], ordered=False)
                await asyncio.sleep(0)

        for cn, ids in fix_unset.items():
            ops = [UpdateMany({"_id": {"$in": ids[n:n + 1000]}}, {"$unset": {"group_id": ""}})
                   for n in range(0, len(ids), 1000)]
            for n in range(0, len(ops), 500):
                await FILE_COLLECTIONS[cn].bulk_write(ops[n:n + 500], ordered=False)
        st["fixed_marks"] = sum(len(v) for v in fix_set.values()) + sum(len(v) for v in fix_unset.values())

        PREFETCH_CACHE.clear()
        TRENDING_CACHE.clear()
        _GH_CACHE.clear()
        st["phase"] = "complete"
    except Exception as e:
        logger.error(f"group scan failed: {e}")
        st["error"] = str(e)
        st["phase"] = "error"
    finally:
        st["running"] = False
        st["finished"] = time.time()
        logger.info(f"🗂️ Group scan done: created={st.get('created')} added={st.get('added')} "
                    f"skipped_big={st.get('skipped_big')} err={st.get('error')}")


@search_routes.post("/api/group/scan_all")
async def api_group_scan_all(req):
    role, _ = await get_user_role(req)
    if role != "admin":
        return web.json_response({"error": "Core Admin Authorization Required!"}, status=403, dumps=fast_json)
    if SCAN_STATE.get("running"):
        return web.json_response({"started": False, "running": True}, dumps=fast_json)
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
                    "count": len(g.get("members", []))})
    return web.json_response({"groups": out}, dumps=fast_json)


@search_routes.post("/api/group/save")
async def api_group_save(req):
    """Naya group banao (nayi number ke saath) YA maujooda group (group_id) me files jodo.
    body: {items:[{id,name}], group_id?, name?}.  Jo file kisi aur group me thi wo wahan se
    nikal kar yahan aa jaati hai."""
    data, err = await _admin_json(req)
    if err:
        return err
    try:
        items, seen = [], set()
        for x in data.get("items", []):
            fid = str((x or {}).get("id") or "").strip()
            if fid and fid not in seen:
                seen.add(fid)
                items.append((fid, str((x or {}).get("name") or "")))
        gid = str(data.get("group_id") or "").strip()
        name = str(data.get("name") or "").strip()[:200]
        if not items:
            return web.json_response({"error": "Koi file select nahi hai!"}, status=400, dumps=fast_json)
        file_ids = [i for i, _ in items]
        auto_keys = list({k for k in (_group_key(n) for _, n in items) if k})
        now = int(time.time())

        # pehle in files ko baaki sab groups se nikalo
        # jis group se file nikal rahi hai wahan BLACKLIST (excluded) ho jaati hai: wo wahan wapas
        # tab tak nahi judegi jab tak admin khud use us group me add na kare
        await groups.update_many({"members": {"$in": file_ids}}, {
            "$pull": {"members": {"$in": file_ids}, "files": {"id": {"$in": file_ids}}},
            "$addToSet": {"excluded": {"$each": file_ids}}})

        if gid:
            g = await groups.find_one({"_id": gid})
            if not g:
                return web.json_response({"error": "Group nahi mila!"}, status=404, dumps=fast_json)
            upd = {"$addToSet": {"members": {"$each": file_ids}, "files": {"$each": [{"id": i, "name": n} for i, n in items]}}, "$set": {"updated_at": now, "scanned_at": 0}}
            if auto_keys:
                upd["$addToSet"]["auto_keys"] = {"$each": auto_keys}
            upd["$pull"] = {"excluded": {"$in": file_ids}}
            await groups.update_one({"_id": gid}, upd)
            num = g.get("num", "")
            name = g.get("name", "")
        else:
            if not name:
                return web.json_response({"error": "Group ka naam likhiye!"}, status=400, dumps=fast_json)
            num = await _next_group_num()
            gid = str(num)
            await groups.insert_one({
                "_id": gid, "num": num, "name": name, "members": file_ids,
                "files": [{"id": i, "name": n} for i, n in items],
                "auto_keys": auto_keys, "excluded": [],
                "thumb_fid": "", "thumb_col": "", "thumb_url": "", "scanned_at": 0,
                "created_at": now, "updated_at": now})
        await _group_cleanup()
        await _mark_files(file_ids, gid)
        return web.json_response({"success": True, "group_id": gid, "num": num, "group_name": name}, dumps=fast_json)
    except Exception as e:
        logger.error(f"group save error: {e}")
        return web.json_response({"error": str(e)}, status=500, dumps=fast_json)


@search_routes.post("/api/group/update")
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
        if "name" in data:
            nm = str(data.get("name") or "").strip()[:200]
            if not nm:
                return web.json_response({"error": "Group ka naam khali nahi ho sakta!"}, status=400, dumps=fast_json)
            upd["name"] = nm
        if "thumb_file_id" in data:
            tf = str(data.get("thumb_file_id") or "").strip()
            tc = str(data.get("thumb_col") or "").strip().lower()
            if tf:
                if tc not in COLLECTIONS:
                    return web.json_response({"error": "Thumbnail ki collection galat hai!"}, status=400, dumps=fast_json)
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
        upd = {"$pull": {"members": fid, "files": {"id": fid}},
               "$addToSet": {"excluded": fid},          # auto-key se wapas na judey
               "$set": {"updated_at": int(time.time())}}
        if g and g.get("thumb_fid") == fid:
            upd["$set"].update({"thumb_fid": "", "thumb_col": ""})
        await groups.update_one({"_id": gid}, upd)
        await _group_cleanup()
        await _mark_files([fid], "")
        return web.json_response({"success": True}, dumps=fast_json)
    except Exception as e:
        logger.error(f"group remove error: {e}")
        return web.json_response({"error": str(e)}, status=500, dumps=fast_json)


@search_routes.post("/api/group/delete")
async def api_group_delete(req):
    """Group hatao (files delete nahi hoti; wo wapas auto-grouping me chali jaati hain)."""
    data, err = await _admin_json(req)
    if err:
        return err
    try:
        gid = str(data.get("group_id") or "").strip()
        old = await groups.find_one({"_id": gid}, {"members": 1})
        await groups.delete_one({"_id": gid})
        thumb_cache.pop(f"g:{gid}", None)
        await _group_cleanup()
        if old:
            await _mark_files(old.get("members", []), "")
        return web.json_response({"success": True}, dumps=fast_json)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500, dumps=fast_json)


@search_routes.post("/api/group/merge")
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
        await groups.update_one({"_id": tgt_id}, {"$addToSet": add, "$set": {"updated_at": int(time.time()), "scanned_at": 0}})
        await groups.update_one({"_id": tgt_id}, {"$pull": {"excluded": {"$in": src.get("members", [])}}})
        await groups.delete_one({"_id": src_id})
        await _mark_files(src.get("members", []), tgt_id)
        thumb_cache.pop(f"g:{src_id}", None)
        await _group_cleanup()
        return web.json_response({"success": True, "num": tgt.get("num", ""), "group_name": tgt.get("name", "")}, dumps=fast_json)
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

        await groups.update_one({"_id": gid}, {"$set": {"thumb_url": f"TG_ID:{new_id}", "updated_at": int(time.time())}})
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
    ck = f"g:{gid}"
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
        # ✅ UPGRADE: डेटाबेस में वेब कस्टमाइज्ड सिंक लॉक 'thumb_source: web' और 'is_thumb_permanent: True' लॉक किया गया
        await COLLECTIONS[collection_field].update_one(
            {"_id": file_id_field},
            {"$set": {"thumb_url": db_save_value, "thumb_source": "web", "is_thumb_permanent": True}}
        )

        # ✅ Cache DB update ke BAAD hatao. Pehle (Telegram upload se PEHLE) hatate the — us 1-2s
        # ke beech koi bhi thumb request aati to DB se PURANA thumbnail wapas cache me chadh jata
        # aur naya thumbnail LRU se nikalne tak (ya restart) tak nahi dikhta.
        thumb_cache.pop(cache_k, None)
        
        # ❌ (Removed auto-delete so permanent thumbnails stay in channel)
        # await db.add_to_delete_queue(THUMBNAIL_STORAGE_CHANNEL, msg.id, 5)
        
        PREFETCH_CACHE.clear()
        TRENDING_CACHE.clear()

        return web.json_response({"success": True}, dumps=fast_json)

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
        PREFETCH_CACHE.clear()
        TRENDING_CACHE.clear()
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
