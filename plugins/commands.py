import asyncio
import random
import logging
from time import time as time_now
from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait
from pyrogram.types import WebAppInfo
from keyboards import ui_button, ui_keyboard

from Script import script
# ✅ DRY: directory + post-category counts अब ia_filterdb के shared helpers से आते हैं
# (पहले यहाँ actors.count_documents × 4 और posts aggregation खुद लिखी थी, और वही
# ब्लॉक web/stats_routes.py में भी कॉपी था)।
from database.ia_filterdb import (
    db_count_documents, get_file_details, delete_files,
    get_directory_counts, get_post_category_counts,
    get_group_for_file, get_files_by_ids, get_groups_by_ids,
)
from database.users_chats_db import db

from info import (
    IS_PREMIUM, URL, BIN_CHANNEL, ADMINS,
    LOG_CHANNEL, PICS, IS_STREAM, REACTIONS, PM_FILE_DELETE_TIME,
    PROTECT_CONTENT
)
from utils import (
    is_premium, get_settings, get_size, temp,
    get_readable_time, get_wish, get_seconds, react_to_message
)
from stream_security import sign_params, USER_LINK_TTL, STREAM_TTL, MAX_ADMIN_TTL
from web.utils.custom_dl import TGCustomYield
from web.utils.media_info import prime_media_info

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# ✅ MINI APP URL - HTTPS Auto-Fix Sync
# ─────────────────────────────────────────────
def _build_mini_app_url(base_url: str) -> str:
    url = base_url.strip() if base_url else ""
    if not url:
        return ""
    if url.startswith("http://"):
        url = "https://" + url[len("http://"):]
    if not url.startswith("https://"):
        url = f"https://{url}"
    return f"{url.rstrip('/')}/miniapp"

MINI_APP_URL = _build_mini_app_url(URL)

# One bulk send per user+group at a time: repeated taps must not flood Telegram.
_GROUP_SEND_ACTIVE = set()


def _clear_web_search_cache():
    """Drop web catalogue/page caches after a bot-side delete or restore."""
    try:
        from web.search_api import _invalidate_search_caches
        _invalidate_search_caches()
    except Exception:
        pass


async def load_send_all_setting():
    """Load the admin's global Send All switch after the DB is ready."""
    temp.SEND_ALL_ENABLED = await db.get_send_all_enabled()
    logger.info("📦 Send All group buttons: %s", "ON" if temp.SEND_ALL_ENABLED else "OFF")


def _group_member_order(group):
    """Members in episode order for series groups, saved order otherwise."""
    members = list(dict.fromkeys(str(x) for x in (group.get("members") or [])))
    if (group.get("group_type") or "quality") != "series":
        return members
    saved = [str(x) for x in (group.get("episode_order") or [])]
    return list(dict.fromkeys([x for x in saved if x in members] + members))


def _group_action_label(group):
    count = len({str(x) for x in (group.get("members") or [])})
    if (group.get("group_type") or "quality") == "series":
        return f"⚡Send All {count} Episode"
    return f"♻️Send All {count} Quality"


def _group_button(group):
    """One blue action row for a multi-file quality/series group.

    Watch/Download is green, so Send All stays blue to keep the stacked
    buttons visually distinct (a row-level colour check cannot see other rows).
    """
    if not group or len(group.get("members") or []) < 2:
        return None
    return [ui_button(
        _group_action_label(group),
        callback_data=f"grp#{group['_id']}",
        style=enums.ButtonStyle.PRIMARY,
    )]


def _file_caption(template, file):
    return (template or script.FILE_CAPTION).format(
        file_name=str(file.get("file_name", "File")),
        file_size=get_size(file.get("file_size") or 0),
    )


# ─────────────────────────────────────────────
# 📊 STATS PAYLOAD BUILDER
# ✅ DRY: यह पूरा "counts लाओ → STATUS_TXT format करो" ब्लॉक दो बार लिखा था —
# /stats command में और ui_cb के "stats" branch में — और directory/post counts तो
# web/stats_routes.py में तीसरी बार। तीनों जगह अलग-अलग होने की वजह से script.py
# का placeholder बदलते ही कोई न कोई जगह IndexError देती थी। अब एक ही builder है।
# ⚡ FAST: पहले 7+ DB calls sequentially चलते थे, अब independent वाले parallel हैं।
# ─────────────────────────────────────────────
async def build_stats_texts():
    """(admin_status_text, user_status_text) लौटाता है। हर counter fail-safe है।"""
    try:
        files = await db_count_documents()
        f = files if isinstance(files, dict) else {}
    except Exception as e:
        f = {}
        logger.error(f"File Stats Error: {e}")

    # directory + posts + users/chats/premium — सब एक-दूसरे से independent हैं
    (dir_total, dir_actors, dir_apps, dir_web), post_stats = await asyncio.gather(
        get_directory_counts(),
        get_post_category_counts(),
    )
    post_total, post_movies, post_webseries, post_appvid, post_porn = post_stats

    try:
        users, chats, premium = await asyncio.gather(
            db.total_users_count(), db.total_chat_count(), db.get_premium_users_count()
        )
    except Exception:
        users = chats = premium = 0

    uptime = get_readable_time(time_now() - temp.START_TIME)

    # STATUS_TXT → 21 placeholders
    admin_text = script.STATUS_TXT.format(
        users, chats, premium,
        f.get('total', 0),
        f.get('primary', 0), f.get('primary_thumb', 0),
        f.get('cloud', 0), f.get('cloud_thumb', 0),
        f.get('archive', 0), f.get('archive_thumb', 0),
        dir_total, dir_actors, dir_apps, dir_web,
        post_total, post_movies, post_webseries, post_appvid, post_porn,
        f.get('total_thumb', 0), uptime
    )

    # USER_STATUS_TXT → 10 placeholders
    user_text = script.USER_STATUS_TXT.format(
        f.get('total', 0), f.get('primary', 0), f.get('cloud', 0), f.get('archive', 0),
        dir_total, dir_actors, dir_apps, dir_web, post_total, uptime
    )
    return admin_text, user_text


# ─────────────────────────────────────────────
# 🚀 /start COMMAND HANDLER
# ─────────────────────────────────────────────
@Client.on_message(filters.command("start") & filters.incoming)
async def start(client, message):
    await react_to_message(message, REACTIONS, big=True)

    if message.chat.type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        if not await db.get_chat(message.chat.id):
            total = await client.get_chat_members_count(message.chat.id)
            await client.send_message(LOG_CHANNEL, script.NEW_GROUP_TXT.format(
                message.chat.title, message.chat.id,
                f"@{message.chat.username or 'Private'}", total
            ))
            await db.add_chat(message.chat.id, message.chat.title)
        return await message.reply(
            f"<b>Hey {message.from_user.mention}, <i>{get_wish()}</i>\nHow can I help you?</b>"
        )

    if not await db.is_user_exist(message.from_user.id):
        await db.add_user(message.from_user.id, message.from_user.first_name)
        await client.send_message(LOG_CHANNEL, script.NEW_USER_TXT.format(
            message.from_user.mention, message.from_user.id
        ))

    if IS_PREMIUM and message.from_user.id not in ADMINS and not await is_premium(message.from_user.id, client):
        return await message.reply_photo(
            random.choice(PICS),
            caption=script.PLAN_TXT.format(10, "@admin"),
            reply_markup=ui_keyboard([[
                ui_button("💎 Buy Premium Plan", callback_data="activate_plan")
            ]])
        )

    if len(message.command) > 1 and message.command[1] != "premium":
        try:
            parts = message.command[1].split("_")
            if len(parts) >= 3:
                try: await message.delete()
                except: pass

                grp_id, file_id = int(parts[1]), "_".join(parts[2:])
                file = await get_file_details(file_id)
                if not file:
                    return await message.reply("❌ File Not Found!")

                settings = await get_settings(grp_id)
                cap_template = settings.get('caption', script.FILE_CAPTION)
                caption = cap_template.format(
                    file_name=str(file.get('file_name', 'File')),
                    file_size=get_size(file.get('file_size', 0))
                )

                group = await get_group_for_file(file_id, file.get("group_id")) if temp.SEND_ALL_ENABLED else None
                btn = []
                group_row = _group_button(group) if temp.SEND_ALL_ENABLED else None
                if group_row:
                    btn.append(group_row)
                if IS_STREAM:
                    btn.append([ui_button("▶️ Watch / Download", callback_data=f"stream#{file_id}")])
                btn.append([ui_button('❌ Close', callback_data=f'close_{message.from_user.id}')])

                target_media = file.get('file_ref') if file.get('file_ref') else file_id

                msg = await client.send_cached_media(
                    message.chat.id,
                    target_media,
                    caption=caption,
                    protect_content=settings.get("file_secure", PROTECT_CONTENT),
                    reply_markup=ui_keyboard(btn)
                )
                if PM_FILE_DELETE_TIME > 0:
                    del_msg = await msg.reply(
                        f"⚠️ This message will delete in {get_readable_time(PM_FILE_DELETE_TIME)}."
                    )
                    
                    await db.add_to_delete_queue(message.chat.id, msg.id, PM_FILE_DELETE_TIME)
                    await db.add_to_delete_queue(message.chat.id, del_msg.id, PM_FILE_DELETE_TIME)
                    
                    temp.PM_FILES[msg.id] = {'file_msg': msg.id, 'note_msg': del_msg.id}
                
                return
                
        except Exception as e:
            logger.error(f"Start File Extraction Error: {e}")
            return
        return

    btn = [
        [ui_button("🍿 Open Mini App", web_app=WebAppInfo(url=MINI_APP_URL))],
        [ui_button("+ Add to Group +", url=f"https://t.me/{temp.U_NAME}?startgroup=start")],
        [ui_button("👨‍🚒 Help Menu", callback_data="help"), ui_button("📊 Global Stats", callback_data="stats")]
    ]
    if message.from_user.id not in ADMINS:
        btn.append([ui_button("💎 Premium Duration", callback_data="myplan")])

    await message.reply_photo(
        random.choice(PICS),
        caption=script.START_TXT.format(message.from_user.mention, get_wish()),
        reply_markup=ui_keyboard(btn)
    )


# ─────────────────────────────────────────────
# ⚙️ SEND ALL FEATURE SWITCH (BOT ADMIN)
# ─────────────────────────────────────────────
@Client.on_message(filters.command(["sendall", "send_all"]) & filters.user(ADMINS))
async def send_all_toggle(client, message):
    arg = message.command[1].lower() if len(message.command) > 1 else ""
    current = "ON" if temp.SEND_ALL_ENABLED else "OFF"
    if arg not in ("on", "off"):
        return await message.reply(
            "⚙️ <b>Send All Buttons</b>\n\n"
            f"Current: <b>{current}</b>\n\n"
            "Usage: <code>/sendAll on</code> or <code>/sendAll off</code>"
        )

    enabled = arg == "on"
    temp.SEND_ALL_ENABLED = enabled
    try:
        await db.set_send_all_enabled(enabled)
    except Exception as e:
        logger.error("Could not persist Send All setting: %s", e)
        return await message.reply(
            f"⚠️ Send All is <b>{'ON' if enabled else 'OFF'}</b> for this run, "
            "but saving it to the database failed. It may reset after a restart."
        )
    await message.reply(
        f"✅ Send All buttons are now <b>{'ON' if enabled else 'OFF'}</b>."
    )


# ─────────────────────────────────────────────
# 📦 SEND A WHOLE QUALITY / SERIES GROUP
# ─────────────────────────────────────────────
@Client.on_callback_query(filters.regex(r"^grp#"))
async def send_group_files(client, query):
    """Send every member of the file's group to the user who tapped the button."""
    if not query.message or not query.from_user:
        return await query.answer("❌ Invalid request.", show_alert=True)

    uid = query.from_user.id
    if not temp.SEND_ALL_ENABLED:
        return await query.answer("❌ Send All buttons are turned off by the admin.", show_alert=True)
    if IS_PREMIUM and uid not in ADMINS and not await is_premium(uid, client):
        return await query.answer("❌ Premium Expired!", show_alert=True)

    gid = query.data.split("#", 1)[1].strip() if "#" in query.data else ""
    if not gid:
        return await query.answer("❌ Group not found.", show_alert=True)

    send_key = (uid, gid)
    if send_key in _GROUP_SEND_ACTIVE:
        return await query.answer("⏳ This group is already being sent.", show_alert=True)
    _GROUP_SEND_ACTIVE.add(send_key)

    try:
        groups = await get_groups_by_ids([gid])
        group = groups[0] if groups else None
        if not group:
            return await query.answer("❌ This group is no longer available.", show_alert=True)

        order = _group_member_order(group)
        if len(order) < 2:
            return await query.answer("❌ This group has only one file.", show_alert=True)

        await query.answer(
            f"📤 Sending {len(order)} files…" if query.message.chat.id == uid
            else "📩 Check your PM — sending all files…"
        )

        files = await get_files_by_ids(order)
        by_id = {str(doc.get("_id")): doc for doc in files if doc}
        ordered = [by_id[fid] for fid in order if fid in by_id]
        if not ordered:
            return

        settings = await get_settings(query.message.chat.id)
        template = settings.get("caption", script.FILE_CAPTION)
        protect_content = settings.get("file_secure", PROTECT_CONTENT)
        target = uid
        sent = 0
        sent_messages = []

        for file in ordered:
            fid = str(file.get("_id"))
            buttons = [[ui_button("❌ Close", callback_data=f"close_{uid}")]]
            if IS_STREAM:
                buttons.insert(0, [ui_button("▶️ Watch / Download", callback_data=f"stream#{fid}")])
            media = file.get("file_ref") if file.get("file_ref") else fid
            caption = _file_caption(template, file)

            message = None
            for attempt in range(2):
                try:
                    message = await client.send_cached_media(
                        target, media, caption=caption,
                        protect_content=protect_content,
                        reply_markup=ui_keyboard(buttons)
                    )
                    break
                except FloodWait as e:
                    if attempt:
                        logger.warning("Group send FloodWait retry failed for %s", fid)
                        break
                    await asyncio.sleep(e.value)
                except Exception as e:
                    logger.warning("Group send failed for %s: %s", fid, e)
                    break
            if message is not None:
                sent += 1
                sent_messages.append(message)

        if not sent:
            try:
                await client.send_message(
                    query.message.chat.id,
                    "❌ Files could not be sent. Start the bot in PM and try again.",
                )
            except Exception:
                pass
            return

        if PM_FILE_DELETE_TIME > 0 and sent_messages:
            try:
                note = await client.send_message(
                    target,
                    f"⚠️ These {sent} files will be deleted in {get_readable_time(PM_FILE_DELETE_TIME)}.",
                )
                for message in sent_messages:
                    await db.add_to_delete_queue(target, message.id, PM_FILE_DELETE_TIME)
                await db.add_to_delete_queue(target, note.id, PM_FILE_DELETE_TIME)
            except Exception as e:
                logger.warning("Could not schedule bulk file deletion: %s", e)
    finally:
        _GROUP_SEND_ACTIVE.discard(send_key)


# ─────────────────────────────────────────────
# 📊 /stats COMMAND HANDLER (Admin Only) - 100% SECURE FAIL-SAFE
# ─────────────────────────────────────────────
@Client.on_message(filters.command("stats") & filters.user(ADMINS))
async def stats(_, message):
    msg = await message.reply("🔄 Fetching Advanced Database Metrics...")
    
    try:
        # ✅ DRY: पूरा counts+format काम अब build_stats_texts() में है (ui_cb के
        # "stats" branch के साथ shared), इसलिए script.py का placeholder count बदलने
        # पर दोनों जगह एक साथ सही रहेंगी।
        stats_text, _ = await build_stats_texts()

        buttons = [
            [ui_button("❌ CLOSE PANEL", callback_data=f"close_{message.from_user.id}")]
        ]
        await msg.edit(stats_text, reply_markup=ui_keyboard(buttons))
        
    except Exception as ex:
        await msg.edit(f"❌ **System Error during Stats generation:**\n\n<code>{ex}</code>\n\n_Please check your script.py placeholders._")


# ─────────────────────────────────────────────
# 🗑 FILE DELETION LOGICS
# ─────────────────────────────────────────────
@Client.on_message(filters.command("delete") & filters.user(ADMINS))
async def delete_file_cmd(client, message):
    if len(message.command) < 3:
        return await message.reply("Usage: `/delete primary Avengers.mkv`")
    storage = message.command[1].lower()
    if storage not in ["primary", "cloud", "archive"]:
        return await message.reply("❌ Invalid Storage! Use: primary, cloud, archive")

    msg = await message.reply("♻️ Moving matching files to Recycle Bin...")
    count = await delete_files(" ".join(message.command[2:]), storage,
                               deleted_by=message.from_user.id)
    _clear_web_search_cache()
    await msg.edit(
        f"♻️ Moved `{count}` files to Recycle Bin from `{storage}`."
        if count else "❌ No files found match."
    )


@Client.on_message(filters.command("delete_all") & filters.user(ADMINS))
async def delete_all_cmd(client, message):
    if len(message.command) < 2:
        return await message.reply("Usage: `/delete_all primary`")
    storage = message.command[1].lower()
    if storage not in ["primary", "cloud", "archive", "all"]:
        return await message.reply("❌ Invalid Collection Target!")

    await message.reply(
        f"⚠️ <b>DANGER ZONE WARNING!</b>\n\nYou are moving ALL documents from `{storage}` to the Recycle Bin.\nThey can be restored from Web → Recycle Bin.\nAre you absolutely sure?",
        reply_markup=ui_keyboard([[
            ui_button("♻️ MOVE ALL TO RECYCLE BIN", callback_data=f"confirm_del#{storage}",
                      style=enums.ButtonStyle.DANGER),
            ui_button("❌ ABORT", callback_data=f"close_{message.from_user.id}")
        ]])
    )


# ─────────────────────────────────────────────
# 🔗 LINK GENERATOR (Stream Routing Tunnel)
# ─────────────────────────────────────────────
@Client.on_message(filters.command("link"))
async def link_generator(client, message):
    if IS_PREMIUM and message.from_user.id not in ADMINS and not await is_premium(message.from_user.id, client):
        return await message.reply(
            "🔒 **Premium Feature**\n\nOnly Admins and active Premium Members can generate direct links.",
            reply_markup=ui_keyboard([[
                ui_button("💎 Buy Premium Plan", callback_data="activate_plan")
            ]]),
        )

    media = (
        getattr(message.reply_to_message, 'document', None) or
        getattr(message.reply_to_message, 'video', None) or
        getattr(message.reply_to_message, 'audio', None)
    )
    if not media:
        return await message.reply("❌ **No streamable media found in the replied message.**")

    # ⏳ Link validity: premium user = fixed 1 din | admin = /link 12h, /link 3d, /link 0 (kabhi nahi)
    ttl = USER_LINK_TTL
    if message.from_user.id in ADMINS and len(message.command) > 1:
        arg = message.command[1].lower()
        if arg in ("0", "never", "forever"):
            ttl = None
        else:
            secs = await get_seconds(arg)
            if secs <= 0:
                return await message.reply(
                    "❌ **Usage:** `/link` (default 1 day)\n`/link 12h` | `/link 3d` | `/link 30m` | `/link 0` (never expire)"
                )
            ttl = min(secs, MAX_ADMIN_TTL)

    msg = await message.reply("⏳ **Injecting into Stream Stream Tunnel...**")
    try:
        copied = await message.reply_to_message.copy(BIN_CHANNEL)
        primed = prime_media_info(copied)
        if primed:
            TGCustomYield.warm_media_session(primed.file_id_obj)
        q = sign_params(copied.id, ttl)
        valid_txt = "Never" if ttl is None else get_readable_time(ttl)
        btn = [
            [
                ui_button("🍿 WATCH ONLINE", url=f"{URL}watch/{copied.id}?{q}"),
                ui_button("📥 FAST DOWNLOAD", url=f"{URL}download/{copied.id}?{q}")
            ],
            [ui_button("❌ CLOSE ❌", callback_data=f"close_{message.from_user.id}")]
        ]
        coros = [
            msg.edit_text(
                f"<i><b>Direct High-Speed Pipeline Ready ⚡</b></i>\n⏳ <b>Valid for:</b> <code>{valid_txt}</code>",
                reply_markup=ui_keyboard(btn)
            )
        ]
        if ttl is not None:
            # link expire hote hi BIN_CHANNEL se file bhi delete (persistent queue, restart-proof)
            coros.append(db.add_to_delete_queue(BIN_CHANNEL, copied.id, ttl))
        await asyncio.gather(*coros)
    except Exception as e:
        await msg.edit_text(f"❌ **Error generating links:** `{e}`")


# ─────────────────────────────────────────────
# 🎨 CENTRAL BUTTONS INLINE UI CALLBACKS - SECURE
# ─────────────────────────────────────────────
@Client.on_callback_query(filters.regex(r"^(help|user_cmds|admin_cmds|stats|back_start)$"))
async def ui_cb(client, query):
    data = query.data
    buttons_markup = None

    # Answer first: Telegram keeps the button's loading spinner until a
    # callback query is acknowledged. Help/Stats must not wait for DB work.
    if data == "admin_cmds" and query.from_user.id not in ADMINS:
        return await query.answer("❌ You are not an Admin!", show_alert=True)
    await query.answer()

    if data == "back_start":
        text = script.START_TXT.format(query.from_user.mention, get_wish())
        btn = [
            [ui_button("🍿 Open Mini App", web_app=WebAppInfo(url=MINI_APP_URL))],
            [ui_button("+ Add to Group +", url=f"https://t.me/{temp.U_NAME}?startgroup=start")],
            [ui_button("👨‍🚒 Help Menu", callback_data="help"), ui_button("📊 Global Stats", callback_data="stats")]
        ]
        if query.from_user.id not in ADMINS:
            btn.append([ui_button("💎 Premium Duration", callback_data="myplan")])
        buttons_markup = ui_keyboard(btn)

    elif data == "help":
        text = script.HELP_TXT.format(query.from_user.mention)
        btn = [[ui_button("👨‍💻 User Commands", callback_data="user_cmds")]]
        if query.from_user.id in ADMINS:
            btn[0].append(ui_button("👮‍♂️ Admin Commands", callback_data="admin_cmds"))
        btn.append([ui_button("⬅️ Back Menu", callback_data="back_start")])
        buttons_markup = ui_keyboard(btn)

    elif data == "user_cmds":
        text = script.USER_COMMAND_TXT
        btn = [[ui_button("⬅️ Back Menu", callback_data="help")]]
        buttons_markup = ui_keyboard(btn)

    elif data == "admin_cmds":
        text = script.ADMIN_COMMAND_TXT
        btn = [[ui_button("⬅️ Back Menu", callback_data="help")]]
        buttons_markup = ui_keyboard(btn)

    elif data == "stats":
        try:
            # ✅ DRY: /stats command और यह callback पहले एक ही 40-लाइन का counts+format
            # ब्लॉक दो बार चलाते थे। अब दोनों build_stats_texts() शेयर करते हैं।
            admin_text, user_text = await build_stats_texts()
            text = admin_text if query.from_user.id in ADMINS else user_text
            buttons_markup = ui_keyboard(
                [[ui_button("⬅️ Back Menu", callback_data="back_start")]]
            )
        except Exception as ex:
            logger.error(f"Stats callback failed: {ex}")
            return

    try:
        await query.message.edit_caption(
            caption=text,
            reply_markup=buttons_markup
        )
    except Exception:
        try: await query.message.edit_text(text=text, reply_markup=buttons_markup)
        except: pass


# ─────────────────────────────────────────────
# 📤 EXTRA OPERATIONAL CALLBAK LOGICS
# ─────────────────────────────────────────────
@Client.on_callback_query(filters.regex(r"^confirm_del#"))
async def confirm_del(client, query):
    if query.from_user.id not in ADMINS:
        return await query.answer("❌ You are not an Admin!", show_alert=True)
    await query.answer()

    storage = query.data.split("#")[1]
    await query.message.edit("♻️ Moving collection blocks to Recycle Bin... Please stand by.")
    count = await delete_files("*", storage, deleted_by=query.from_user.id)
    _clear_web_search_cache()
    await query.message.edit(
        f"♻️ Moved `{count}` files to Recycle Bin from `{storage}`. "
        "Restore them from Web → Recycle Bin."
    )


@Client.on_callback_query(filters.regex(r"^stream#"))
async def stream_cb(client, query):
    file_id = query.data.split("#")[1]
    await query.answer("🔗 Generating Video Stream Tunnel Link...", show_alert=False)
    try:
        file = await get_file_details(file_id)
        if not file:
            return await query.answer("❌ File removed or structural ID broken!", show_alert=True)
            
        target_media = file.get('file_ref') if file.get('file_ref') else file_id

        msg = await client.send_cached_media(BIN_CHANNEL, target_media)
        primed = prime_media_info(msg)
        if primed:
            TGCustomYield.warm_media_session(primed.file_id_obj)
        q = sign_params(msg.id, STREAM_TTL)
        btn = [
            [
                ui_button("🎬 Stream Online", url=f"{URL}watch/{msg.id}?{q}"),
                ui_button("⚡ Download File", url=f"{URL}download/{msg.id}?{q}")
            ],
            [ui_button("❌ Close Panel", callback_data=f"close_{query.from_user.id}")]
        ]
        # Watch/Download replaces the file card: Send All must disappear here.
        await asyncio.gather(
            query.message.edit_reply_markup(ui_keyboard(btn)),
            db.add_to_delete_queue(BIN_CHANNEL, msg.id, STREAM_TTL),   # link expiry == file delete time
        )
    except Exception as e:
        await query.answer(f"Error: {e}", show_alert=True)


# ❌ DUPLICATE HANDLER REMOVED: यहाँ एक `close_cb` था जो plugins/filter.py के
# close_callback के साथ `^close_` regex पर रजिस्टर होता था — यानी हर Close tap पर
# दोनों चलते थे (दो बार delete + दो बार queue cleanup, दूसरी बार हमेशा exception)।
# अब एक ही merged handler plugins/filter.py में है, जो PM_FILES, auto-delete timer
# और search-result cache तीनों की सफाई करता है।
