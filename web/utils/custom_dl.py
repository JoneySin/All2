import asyncio
import io
import logging
import math
import os
from collections import deque

from hydrogram import Client, utils, raw
import hydrogram.errors as _herr
from hydrogram.types import Message
from hydrogram.session import Session, Auth
from hydrogram.errors import AuthBytesInvalid, FloodWait
from hydrogram.file_id import FileId, FileType, ThumbnailSource
from utils import temp

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# ⚙️ STREAM TUNING (env se badal sakte ho — Koyeb free 0.1 vCPU ke liye safe defaults)
#   STREAM_PREFETCH            : ek viewer ke liye aage ke kitne 1MB chunk pehle se mangwane hain
#   STREAM_FETCH_CONCURRENCY   : poore server par ek saath max kitne Telegram GetFile chalein
# ─────────────────────────────────────────────────────────
PREFETCH = max(1, int(os.environ.get("STREAM_PREFETCH", "3")))
FETCH_CONCURRENCY = max(1, int(os.environ.get("STREAM_FETCH_CONCURRENCY", "6")))

_fetch_sem = None


def _sem() -> asyncio.Semaphore:
    # lazily banta hai taaki event loop se pehle create na ho
    global _fetch_sem
    if _fetch_sem is None:
        _fetch_sem = asyncio.Semaphore(FETCH_CONCURRENCY)
    return _fetch_sem


# Network/Telegram ke temporary errors — inpar chunk dobara mangwaya jaata hai
_RETRY_ERRORS = (asyncio.TimeoutError, OSError) + (
    (_herr.InternalServerError,) if hasattr(_herr, "InternalServerError") else ()
)


# ─────────────────────────────────────────────────────────
# ✅ FIX: async हटाया — ये pure math functions हैं,
#         await करने की कोई ज़रूरत नहीं थी
# ─────────────────────────────────────────────────────────
def chunk_size(length):
    return 2 ** max(min(math.ceil(math.log2(length / 1024)), 10), 2) * 1024

def offset_fix(offset, chunksize):
    return offset - (offset % chunksize)


class TGCustomYield:
    _session_locks = {}   # dc_id -> asyncio.Lock

    def __init__(self):
        self.main_bot = temp.BOT

    @staticmethod
    async def generate_file_properties(msg: Message) -> FileId:
        return FileId.decode(getattr(msg, msg.media.value).file_id)

    # ─────────────────────────────────────────────────────────
    # Media session — har DC ke liye ek baar. Lock lagaya hai: pehle 2-3 parallel
    # requests ek saath naya session bana deti thi (ek leak ho jaata tha).
    # ─────────────────────────────────────────────────────────
    async def generate_media_session(self, c: Client, d: FileId) -> Session:
        ms = c.media_sessions.get(d.dc_id)
        if ms:
            return ms

        lock = TGCustomYield._session_locks.setdefault(d.dc_id, asyncio.Lock())
        async with lock:
            ms = c.media_sessions.get(d.dc_id)
            if ms:
                return ms

            test_mode = await c.storage.test_mode()
            if d.dc_id != await c.storage.dc_id():
                ms = Session(
                    c, d.dc_id,
                    await Auth(c, d.dc_id, test_mode).create(),
                    test_mode, is_media=True
                )
                await ms.start()
                for _ in range(3):
                    try:
                        ex = await c.invoke(raw.functions.auth.ExportAuthorization(dc_id=d.dc_id))
                        await ms.send(raw.functions.auth.ImportAuthorization(id=ex.id, bytes=ex.bytes))
                        break
                    except AuthBytesInvalid:
                        continue
                else:
                    await ms.stop()
                    raise AuthBytesInvalid
            else:
                ms = Session(c, d.dc_id, await c.storage.auth_key(), test_mode, is_media=True)
                await ms.start()
            c.media_sessions[d.dc_id] = ms

        return ms

    @staticmethod
    async def get_location(f: FileId):
        if f.file_type == FileType.CHAT_PHOTO:
            if f.chat_id > 0:
                peer = raw.types.InputPeerUser(user_id=f.chat_id, access_hash=f.chat_access_hash)
            elif f.chat_access_hash == 0:
                peer = raw.types.InputPeerChat(chat_id=-f.chat_id)
            else:
                peer = raw.types.InputPeerChannel(
                    channel_id=utils.get_channel_id(f.chat_id),
                    access_hash=f.chat_access_hash
                )
            return raw.types.InputPeerPhotoFileLocation(
                peer=peer, volume_id=f.volume_id, local_id=f.local_id,
                big=f.thumbnail_source == ThumbnailSource.CHAT_PHOTO_BIG
            )
        elif f.file_type == FileType.PHOTO:
            return raw.types.InputPhotoFileLocation(
                id=f.media_id, access_hash=f.access_hash,
                file_reference=f.file_reference, thumb_size=f.thumbnail_size
            )
        return raw.types.InputDocumentFileLocation(
            id=f.media_id, access_hash=f.access_hash,
            file_reference=f.file_reference, thumb_size=f.thumbnail_size
        )

    # ─────────────────────────────────────────────────────────
    # 📦 EK CHUNK — retry + global concurrency limit
    # ─────────────────────────────────────────────────────────
    async def _get_chunk(self, ms, loc, offset, limit) -> bytes:
        for attempt in range(4):
            try:
                async with _sem():
                    r = await ms.send(
                        raw.functions.upload.GetFile(location=loc, offset=offset, limit=limit)
                    )
                if isinstance(r, raw.types.upload.File):
                    return r.bytes
                logger.warning(f"GetFile unexpected response {type(r).__name__} @ {offset}")
                return b""
            except FloodWait as e:
                if attempt == 3 or e.value > 20:
                    raise
                logger.warning(f"GetFile FloodWait {e.value}s @ {offset}")
                await asyncio.sleep(e.value + 0.5)
            except _RETRY_ERRORS as e:
                if attempt == 3:
                    raise
                logger.warning(f"GetFile retry {attempt + 1} @ {offset}: {e!r}")
                await asyncio.sleep(0.4 * (attempt + 1))
        return b""  # pragma: no cover

    # ─────────────────────────────────────────────────────────
    # 🍿 STREAMING ENGINE — PREFETCH PIPELINE
    # Pehle: chunk mango → wait → bhejo → phir agla mango (har chunk par Telegram
    # round-trip ka intezaar). Ab: aage ke PREFETCH chunk pehle se parallel mangwaye
    # jaate hain, to client ko bhejte waqt agla chunk already raaste me hota hai.
    # `msg` ki jagah ab decoded FileId bhi de sakte ho (media_info cache se).
    # ─────────────────────────────────────────────────────────
    async def yield_file(
        self, msg,
        offset: int, first_cut: int, last_cut: int,
        parts: int, chunk_size: int
    ):
        file_props = msg if isinstance(msg, FileId) else await self.generate_file_properties(msg)
        ms = await self.generate_media_session(self.main_bot, file_props)
        loc = await self.get_location(file_props)

        pending = deque()
        sched_i, sched_off = 0, offset

        def _schedule():
            nonlocal sched_i, sched_off
            while sched_i < parts and len(pending) < PREFETCH:
                pending.append(asyncio.ensure_future(
                    self._get_chunk(ms, loc, sched_off, chunk_size)
                ))
                sched_i += 1
                sched_off += chunk_size

        try:
            _schedule()
            for i in range(1, parts + 1):
                chunk = await pending.popleft()
                _schedule()                     # ek chunk khatam → agla turant queue me
                if not chunk:
                    break

                if parts == 1:
                    yield chunk[first_cut:last_cut]
                elif i == 1:
                    yield chunk[first_cut:]
                elif i == parts:
                    yield chunk[:last_cut]
                else:
                    yield chunk

                if len(chunk) < chunk_size:     # file yahin khatam (EOF)
                    break
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"Streaming error near offset {offset}: {e!r}")
            raise                               # client ko adhoora body 'success' na dikhe
        finally:
            for t in pending:
                t.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

    # ─────────────────────────────────────────────────────────
    # 📥 BYTESIO PIPELINE — thumbnail / small file download
    # ─────────────────────────────────────────────────────────
    async def download_as_bytesio(self, msg: Message) -> io.BytesIO:
        """
        Thumbnail या छोटी files के लिए।
        ⚠️  4GB video इसमें मत डालो — पूरी file RAM में आ जाएगी।
        """
        file_props = await self.generate_file_properties(msg)
        ms = await self.generate_media_session(self.main_bot, file_props)
        loc = await self.get_location(file_props)

        limit, offset = 1_048_576, 0  # 1 MB blocks
        buf = io.BytesIO()

        try:
            while True:
                r = await ms.send(
                    raw.functions.upload.GetFile(location=loc, offset=offset, limit=limit)
                )
                if not isinstance(r, raw.types.upload.File) or not r.bytes:
                    break
                buf.write(r.bytes)
                offset += len(r.bytes)
        except Exception as e:
            logger.error(f"download_as_bytesio error: {e}")

        buf.seek(0)
        return buf
