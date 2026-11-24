import logging
import asyncio
import signal
import os
import time
from typing import Union, AsyncGenerator
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# ==========================================================
# 🔥 UVLOOP (High Performance C-Based Event Loop Engine)
# ==========================================================
try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

# ==========================================================
# 📊 LOGGING CENTER
# ==========================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
# Keep Pyrogram's retry warnings visible. The old ERROR level hid the real
# reason (for example "500 RPC_CALL_FAIL") and left only the generic
# "Failed to invoke auth.ImportBotAuthorization" at the top level. Set
# PYROGRAM_LOG_LEVEL=INFO for full session/connection diagnostics.
_pyro_level = getattr(logging, os.environ.get("PYROGRAM_LOG_LEVEL", "WARNING").upper(),
                      logging.WARNING)
logging.getLogger('pyrogram').setLevel(_pyro_level)
logging.getLogger('aiohttp.access').setLevel(logging.WARNING)
logging.getLogger('aiohttp.server').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# ==========================================================
# CORE IMPORTS
# ==========================================================
from aiohttp import web
from pyrogram import Client, types, StopPropagation, idle
from pyrogram.errors import FloodWait
from pyrogram.handlers import MessageHandler
from web import web_app
from web.search_api import start_group_scan, stop_group_scan
from info import (
    API_ID, API_HASH, BOT_TOKEN, PORT, ADMINS,
    LOG_CHANNEL, TIME_ZONE, STARTUP_GROUP_SCAN,
    PROXY, SESSION_STRING, SESSION_DIR, AUTH_RETRY_ATTEMPTS, AUTH_RETRY_DELAY
)
from utils import temp
from database.users_chats_db import db
from database.ia_filterdb import ensure_indexes
from plugins.premium import check_premium_expired
from plugins.commands import load_send_all_setting

# ❌ DEAD CODE REMOVED: यहाँ एक `/health` route था, पर web/dashboard_routes.py में
# भी वही route रजिस्टर है। web/__init__.py का register_admin_components() इस
# RouteTableDef से पहले चलता है, इसलिए dashboard वाला ही match होता था और यह
# handler कभी execute नहीं होता था (aiohttp first-match-wins)। अब /health एक ही
# जगह है (dashboard_routes) और उसी में uptime भी शामिल कर दिया गया है।

# ==========================================================
# ⏳ SMART AUTO-DELETE BACKGROUND WORKER (RAM Protected)
# ==========================================================
async def auto_delete_worker(bot):
    """रीस्टार्ट-प्रूफ मोंगोडीबी आधारित ऑटो-डिलीट इंजन - रैम और कैशे लीक प्रूफ पैच के साथ"""
    while True:
        try:
            cursor = await db.get_expired_delete_tasks()
            
            async for task in cursor:
                chat_id = task["chat_id"]
                message_id = task["message_id"]
                
                try:
                    await bot.delete_messages(chat_id, message_id)
                except FloodWait as fw:
                    # entry queue me hi rehne do — agle cycle me dobara try hoga
                    logger.warning(f"auto_delete FloodWait {fw.value}s")
                    await asyncio.sleep(fw.value)
                    break
                except Exception as tg_err:
                    # pehle har error par entry hata di jaati thi => file kabhi delete nahi hoti thi.
                    # ab 24 ghante tak retry; uske baad hi entry chhodi jaati hai.
                    d_at = task.get("delete_at")
                    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
                    too_old = bool(d_at) and getattr(d_at, "tzinfo", None) is None and (now_utc - d_at).total_seconds() > 86400
                    if not too_old:
                        logger.warning(f"auto_delete failed in {chat_id}/{message_id}, will retry: {tg_err}")
                        continue
                    logger.error(f"auto_delete giving up on {chat_id}/{message_id}: {tg_err}")

                await db.remove_from_delete_queue(chat_id, message_id)
            
            # (gc.collect() हटाया: 0.1 vCPU पर हर बार की पूरी सफ़ाई स्ट्रीमिंग को झटका देती थी)
                
        except Exception as e:
            logger.error(f"Error in auto_delete_worker loop: {e}")
            
        await asyncio.sleep(15) # आपके नियमानुसार कतार चेकिंग का सुपरफास्ट इंटरवल

# ==========================================================
# BOT CLIENT CLASS
# ==========================================================
class Bot(Client):
    def __init__(self):
        # Prefer an explicit path; otherwise use a mounted /data volume when
        # one exists so the auth key survives Koyeb redeploys.
        session_dir = SESSION_DIR or ("/data" if os.path.isdir("/data") else ".")
        try:
            os.makedirs(session_dir, exist_ok=True)
        except OSError as e:
            logger.error(f"SESSION_DIR is not writable ({session_dir}): {e}")
            raise
        if SESSION_STRING:
            logger.info("📁 Telegram session: using SESSION_STRING")
        else:
            session_file = os.path.join(session_dir, "Auto_Filter_Bot.session")
            logger.info("📁 Telegram session directory: %s (existing session: %s)",
                        session_dir, os.path.exists(session_file))
            if session_dir == "." and not SESSION_DIR:
                logger.warning(
                    "⚠️ No persistent /data volume for the Telegram session. "
                    "Every redeploy will create a new auth key; mount a volume at /data "
                    "and set SESSION_DIR=/data to keep it."
                )
        super().__init__(
            name="Auto_Filter_Bot",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            plugins={"root": "plugins"},
            workdir=session_dir,
            proxy=PROXY or None,
            session_string=SESSION_STRING or None,
        )
        self._runner = None 
        self._premium_task = None 
        self._delete_task = None  

    async def _start_web(self):
        """Bind the health/web port before Telegram auth.

        Koyeb marks an instance unhealthy when nothing listens on PORT. Starting
        this first means an auth retry (or a Telegram-side outage) no longer
        causes a restart loop that asks Telegram for a fresh auth key each time.
        """
        if getattr(self, "_runner", None):
            return
        temp.START_TIME = time.time()
        self._runner = web.AppRunner(web_app, access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, "0.0.0.0", PORT).start()
        logger.info(f"🌐 Web Server & Mini App Stream Live on Port {PORT}")

    async def _start_telegram(self):
        """Start Kurigram, keeping the web instance alive across an outage.

        Telegram's auth backend can return 500/RPC_CALL_FAIL for minutes (and
        FloodWait after repeated retries). Exiting here would make Koyeb restart
        the whole container, start a fresh auth attempt and lose any chance to
        recover automatically. Instead, keep the already-healthy web port up and
        retry with backoff. Invalid credentials still fail fast because
        Pyrogram raises a non-transport BadRequest for those.
        """
        fast_attempts = max(1, AUTH_RETRY_ATTEMPTS)
        configured_plugins = getattr(self, "plugins", None)
        attempt = 0
        while True:
            attempt += 1
            # Kurigram 2.2.27's Client.start() calls self.load_plugins() before
            # connect()/authorize() (initialize() only starts the dispatcher).
            # A retry must therefore skip plugin loading only when the dispatcher
            # actually contains handlers; otherwise re-enable plugins so a failure
            # that happened before loading cannot leave the bot without commands.
            if attempt > 1:
                handlers_loaded = bool(
                    getattr(getattr(self, "dispatcher", None), "groups", None)
                )
                self.plugins = None if handlers_loaded else configured_plugins
            try:
                await super().start()
                # Publish the client immediately. Index sync, settings and the
                # rest of start() can take many seconds on a small Koyeb worker;
                # until this assignment existed, /api/thumb and /setup_stream
                # raised "NoneType has no attribute send_cached_media" while the
                # web server was already accepting requests.
                temp.BOT = self
                temp.BOT_READY = True
                logger.info("✅ Telegram client connected; media APIs are live")
                return
            except FloodWait as e:
                wait = max(30, int(getattr(e, "value", 0) or 0))
                logger.error(
                    "Telegram FloodWait during startup: waiting %ss before retry %s. "
                    "Web is still up; do not redeploy repeatedly.", wait, attempt,
                )
                await asyncio.sleep(wait)
            except (TimeoutError, OSError) as e:
                detail = str(e) or repr(e)
                # First few retries are close together, then back off to five
                # minutes. This avoids hammering Telegram while still letting a
                # recovered session connect without another deployment.
                delay = max(5, AUTH_RETRY_DELAY * attempt) if attempt < fast_attempts else 300
                logger.error(
                    "Telegram authorization attempt %s failed: %s. "
                    "This is a Telegram/network failure; web stays healthy and "
                    "will retry in %ss. Do not redeploy repeatedly.",
                    attempt, detail, delay,
                )
                await asyncio.sleep(delay)
            finally:
                self.plugins = configured_plugins

    async def start(self):
        # 1. Health/web first so Koyeb does not kill an instance that is waiting
        # for Telegram's auth backend.
        await self._start_web()

        # 2. Start Kurigram Client Instance (with bounded transport retries).
        await self._start_telegram()

        # 2. Database Indexes Sync (Makkhan DB Tuning)
        await ensure_indexes()
        await db._ensure_indexes() 
        try:
            await load_send_all_setting()
        except Exception as e:
            logger.warning(f"Could not load Send All setting: {e}; keeping default ON")
        logger.info("✅ Database Connections & Indexes Fully Synced")

        # 3. Load banned users & chats into Runtime Buckets
        try:
            b_users, b_chats = await db.get_banned()
            temp.BANNED_USERS = [int(x) for x in b_users]
            temp.BANNED_CHATS = [int(x) for x in b_chats]
            logger.info(f"✅ Loaded {len(b_users)} banned users and {len(b_chats)} banned chats")
        except Exception as e:
            logger.error(f"Error loading banned list: {e}")

        # 4. Global Ban Middleware (The Strict Gatekeeper Security Guard)
        async def ban_check_middleware(client, message):
            uid = message.from_user.id if message.from_user else None
            cid = message.chat.id if message.chat else None
            if (uid and int(uid) in temp.BANNED_USERS) or (cid and int(cid) in temp.BANNED_CHATS):
                raise StopPropagation
        
        self.add_handler(MessageHandler(ban_check_middleware), group=-1)
        logger.info("🛡️ Premium Global Security Guard Activated")

        # 5. Persistent Hard Restart Logic Sync
        local_tz = ZoneInfo(TIME_ZONE)

        def build_status_msg():
            now = datetime.now(local_tz)
            return (
                "🤖 <b>Bot Restarted!</b>\n\n"
                "<blockquote>"
                f"📅 <b>Date:</b> {now.strftime('%d %B %Y')}\n"
                f"🕐 <b>Time:</b> {now.strftime('%I:%M:%S %p')}\n"
                f"🌏 <b>Timezone:</b> {TIME_ZONE}"
                "</blockquote>"
            )

        if os.path.exists("restart.txt"):
            try:
                with open("restart.txt", "r") as f:
                    content = f.read().strip().split()
                    if len(content) == 2:
                        chat_id, msg_id = map(int, content)
                        await self.edit_message_text(chat_id=chat_id, message_id=msg_id, text=build_status_msg())
            except Exception as e:
                logger.error(f"Restart message error: {e}")
            finally:
                try: os.remove("restart.txt")
                except: pass

        # 6. Set Centralized Context Registry Identity
        temp.BOT = self
        me = await self.get_me()
        temp.ME = me.id
        temp.U_NAME = me.username
        temp.B_NAME = me.first_name

        # The full-library scan is opt-in: on a small Koyeb worker it competes
        # with /start, search and callback queries for CPU and MongoDB time.
        # Admins can still run it from the dashboard whenever a repair is needed.
        if STARTUP_GROUP_SCAN:
            try:
                if start_group_scan():
                    logger.info("🗂️ Startup group scan scheduled in background")
            except Exception as e:
                logger.error(f"Could not schedule startup group scan: {e}")
        else:
            logger.info("🗂️ Startup group scan disabled (set STARTUP_GROUP_SCAN=true to enable)")

        # 8. Start Background Automation Tasks (Premium Engine & Auto-Delete Sync)
        self._premium_task = asyncio.create_task(check_premium_expired(self))
        self._delete_task = asyncio.create_task(auto_delete_worker(self)) 
        logger.info("⏳ Persistent Auto-Delete RAM Guard Activated")

        # 9. Send Startup Logs (Perfect info.py TIME_ZONE Sync)
        # ✅ FIX: हार्डकोडिंग हटाकर सीधे आपके कस्टमाइज्ड टाइमज़ोन इंजन से बाइंड किया गया
        startup_msg = build_status_msg()

        async def _safe_send(admin_id):
            try:
                await self.send_message(admin_id, startup_msg)
            except FloodWait as e:
                await asyncio.sleep(e.value)
                await self.send_message(admin_id, startup_msg)
            except Exception:
                pass

        await asyncio.gather(*[_safe_send(aid) for aid in ADMINS])

        if LOG_CHANNEL:
            try:
                await self.send_message(LOG_CHANNEL, f"<b>⚡ {me.mention} System Rebuilt & Synced Successfully on {TIME_ZONE}! 🚀</b>")
            except Exception as e:
                logger.warning(f"Failed to send log to LOG_CHANNEL: {e}")

        logger.info(f"@{me.username} is Smoothly Operational!")

    # ✅ GRACEFUL SHUTDOWN (Protects Database Pools & Containers)
    async def stop(self, *args):
        if getattr(self, "_stopped", False):
            return
        self._stopped = True
        logger.info("Initiating Graceful Shutdown Pipeline...")
        temp.BOT_READY = False
        
        if getattr(self, '_runner', None):
            await self._runner.cleanup()
            self._runner = None
            logger.info("✅ Web App Runner Cleaned Up")

        await stop_group_scan()

        if getattr(self, '_premium_task', None):
            self._premium_task.cancel()
            try: await self._premium_task 
            except asyncio.CancelledError: pass
            logger.info("✅ Premium Expiry Engine Stopped")

        if getattr(self, '_delete_task', None):
            self._delete_task.cancel()
            try: await self._delete_task
            except asyncio.CancelledError: pass
            logger.info("✅ Auto-Delete Engine Flushed & Stopped")

        if getattr(self, "is_connected", False):
            await super().stop()
        logger.info("System Halted Gracefully. All Memory Freed ✅")

    async def iter_messages(self, chat_id: Union[int, str], limit: int, offset: int = 0) -> AsyncGenerator["types.Message", None]:
        """Yield message IDs offset+1 through limit, including deleted placeholders."""
        current = offset
        while current < limit:
            diff = min(200, limit - current)
            try:
                messages = await self.get_messages(chat_id, list(range(current + 1, current + diff + 1)))
            except Exception:
                # The indexing UI must report an interrupted scan, not success.
                logger.exception("Error fetching indexing messages")
                raise
            for message in messages:
                if message is not None:
                    yield message
            current += diff

# ==========================================================
# KICKSTART LIFE-CYCLE LOOP
# ==========================================================
async def main():
    bot = Bot()
    
    # ✅ FIX: कोएब कंटेनर बंद/रीस्टार्ट करते समय कनेक्शन क्रैश रोकने के लिए सिग्नल्स बाइंडिंग
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(bot.stop()))
        except NotImplementedError:
            pass # Windows डेवलपमेंट फॉलबैक के लिए
            
    try:
        await bot.start()
        await idle()
    finally:
        # idle() restores the previous signal handlers and returns; it does not
        # stop the client itself. Close the web runner, background tasks and
        # Telegram session explicitly on SIGTERM/SIGINT.
        await bot.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Process Interrupted Externally.")
