import secrets
import time
from aiohttp import web
from web.web_assets import build_page, form_wrapper, get_auth
from utils import temp
from database.users_chats_db import web_db, get_local_now, OTPRateLimited  # <-- समय सिंक के लिए इम्पोर्ट किया

login_routes = web.RouteTableDef()

MIN_PASSWORD_LEN = 6


def _is_https(req):
    # Koyeb जैसे proxy के पीछे असली scheme X-Forwarded-Proto में आता है
    return req.secure or req.headers.get("X-Forwarded-Proto", "").split(",")[0].strip().lower() == "https"


@login_routes.get('/login')
async def login_user(req):
    role, _ = await get_auth(req)
    if role:                                   # पहले से लॉगिन है → सीधे dashboard
        return web.HTTPFound('/dashboard')
    content = '<form action="/api/login" method="post"><input type="email" name="email" placeholder="Email Address" required><input type="password" name="password" placeholder="Password" required><button class="submit-btn" type="submit">Sign In</button></form><div style="margin-top:20px; display:flex; justify-content:space-between; font-size:14px;"><a href="/forgot_password" style="color:var(--muted); text-decoration:none;">Forgot Password?</a><a href="/register" style="color:var(--text); text-decoration:none; font-weight:700;">New? Join Now</a></div>'
    return build_page("Sign In", form_wrapper("Sign In", content, req.query.get('err',''), req.query.get('msg','')), "login-bg")

@login_routes.post('/api/login')
async def api_login_user(req):
    d = await req.post()
    user = await web_db.verify_login(d.get('email'), d.get('password'))
    if user:
        # ✅ LOGIN TRACK ENGINE: डेटाबेस में यूजर का अंतिम लॉगिन टाइमस्टैम्प अभी का सेट करें
        await web_db.col.update_one(
            {"tg_id": user['tg_id']},
            {"$set": {"last_login": get_local_now()}}
        )

        s = secrets.token_urlsafe(32)
        expiry = time.time() + 86400 * 7
        temp.USER_SESSIONS[s] = {'tg_id': user['tg_id'], 'expiry': expiry}
        if len(temp.USER_SESSIONS) > 5000:     # RAM में पुराने expired सेशन साफ़
            now = time.time()
            for k in [k for k, v in temp.USER_SESSIONS.items() if v.get('expiry', 0) <= now]:
                temp.USER_SESSIONS.pop(k, None)
        await web_db.create_session(s, user['tg_id'], expiry)     # DB में भी — रीस्टार्ट पर बचा रहे
        res = web.HTTPFound('/dashboard')
        res.set_cookie('user_session', s, max_age=86400 * 7, path='/',
                       httponly=True, secure=_is_https(req), samesite='Lax')
        return res
    return web.HTTPFound('/login?err=Invalid Email or Password')

@login_routes.get('/register')
async def register_user(req):
    content = '<form action="/api/register_step1" method="post"><input type="number" name="tg_id" placeholder="Telegram ID (e.g. 123456)" required><input type="email" name="email" placeholder="Email Address" required><input type="password" name="password" placeholder="Create Password" required><button class="submit-btn" type="submit">Send OTP via Telegram</button></form><p style="margin-top:15px; font-size:14px; color:var(--muted)">Already have an account? <a href="/login" style="color:var(--text); text-decoration:none; font-weight:700;">Sign In</a></p>'
    return build_page("Create Account", form_wrapper("Create Account", content, req.query.get('err','')), "login-bg")

@login_routes.post('/api/register_step1')
async def api_register_step1(req):
    d = await req.post()
    try: tg_id = int(d.get('tg_id'))
    except: return web.HTTPFound('/register?err=Invalid Telegram ID')
    email, password = d.get('email'), d.get('password')
    if not password or len(password) < MIN_PASSWORD_LEN:
        return web.HTTPFound(f'/register?err=Password must be at least {MIN_PASSWORD_LEN} characters')
    
    if await web_db.col.find_one({"$or": [{"tg_id": tg_id}, {"email": email}]}, {"_id": 1}): 
        return web.HTTPFound('/register?err=Telegram ID or Email already registered!')
        
    otp = str(secrets.randbelow(900000) + 100000)
    now = time.time()
    # Discard expired registrations so abandoned OTPs and passwords do not
    # stay in memory indefinitely when new users register.
    for key, pending in list(temp.REG_PENDING.items()):
        if pending.get('expiry', 0) <= now:
            temp.REG_PENDING.pop(key, None)
    if len(temp.REG_PENDING) >= 2000 and tg_id not in temp.REG_PENDING:
        return web.HTTPFound('/register?err=Too many pending registrations. Please try again later.')
    temp.REG_PENDING[tg_id] = {'email': email, 'password': password, 'otp': otp, 'expiry': now + 300}
    try: 
        await temp.BOT.send_message(tg_id, f"🔐 **Web Registration Verification**\n\nSomeone is trying to link your Telegram ID to this email: `{email}`\n\n**Your OTP is:** `{otp}`\n\n_Valid for 5 mins._")
    except Exception:
        # Do not retain plaintext password/OTP if delivery failed. Preserve a
        # newer registration that may have started during the send.
        if temp.REG_PENDING.get(tg_id, {}).get('otp') == otp:
            temp.REG_PENDING.pop(tg_id, None)
        return web.HTTPFound('/register?err=Failed to send OTP. Please start the Bot first in Telegram PM.')
    return web.HTTPFound(f'/verify_registration?tg_id={tg_id}')

@login_routes.get('/verify_registration')
async def verify_registration_page(req):
    try:
        tg_id = int(req.query.get('tg_id', ''))
        if tg_id <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return web.HTTPFound('/register')
    content = f'<p style="color:var(--muted); margin-bottom:15px; font-size:14px;">We sent a 6-digit OTP to your Telegram bot PM.</p><form action="/api/register_step2" method="post"><input type="hidden" name="tg_id" value="{tg_id}"><input type="text" name="otp" placeholder="Enter 6-digit OTP" required><button class="submit-btn" type="submit">Verify & Create Account</button></form>'
    return build_page("Verify Registration", form_wrapper("Verify OTP", content, req.query.get('err','')), "login-bg")

@login_routes.post('/api/register_step2')
async def api_register_step2(req):
    d = await req.post()
    try: tg_id = int(d.get('tg_id'))
    except: return web.HTTPFound('/register?err=Invalid Request')
    otp = str(d.get('otp') or '').strip()
    if tg_id not in getattr(temp, 'REG_PENDING', {}): return web.HTTPFound('/register?err=Session expired. Try again.')
    pending = temp.REG_PENDING[tg_id]
    if time.time() > pending['expiry']:
        del temp.REG_PENDING[tg_id]
        return web.HTTPFound('/register?err=OTP Expired. Please restart registration.')
    pending['tries'] = pending.get('tries', 0) + 1
    if pending['tries'] > 5:                   # बहुत गलत प्रयास → यह रजिस्ट्रेशन रद्द
        temp.REG_PENDING.pop(tg_id, None)
        return web.HTTPFound('/register?err=Too many wrong attempts. Please start again.')
    if not secrets.compare_digest(str(pending['otp']).encode(), otp.encode()): return web.HTTPFound(f'/verify_registration?tg_id={tg_id}&err=Invalid OTP')
    # Consume before awaiting the database so parallel correct submissions
    # cannot both create an account or delete a newer pending registration.
    temp.REG_PENDING.pop(tg_id, None)
    try:
        success, msg = await web_db.create_user(tg_id, pending['email'], pending['password'])
    except Exception:
        return web.HTTPFound('/register?err=Could not complete registration. Please try again.')
    if success:
        return web.HTTPFound('/login?msg=Account created successfully! Please login.')
    return web.HTTPFound(f'/register?err={msg}')

@login_routes.get('/forgot_password')
async def forgot_password(req):
    content = '<p style="color:var(--muted); margin-bottom:15px; font-size:14px;">Enter your Telegram ID to receive an OTP.</p><form action="/api/forgot_password" method="post"><input type="number" name="tg_id" placeholder="Telegram ID" required><button class="submit-btn" type="submit">Send OTP to Telegram</button></form><hr style="border:0; border-top:1px solid var(--border); margin:25px 0;"><form action="/api/reset_password" method="post"><input type="number" name="tg_id" placeholder="Confirm TG ID" required><input type="text" name="otp" placeholder="Enter OTP" required><input type="password" name="new_password" placeholder="New Password" required><button class="submit-btn" style="background:var(--text);color:var(--card);" type="submit">Update Password</button></form>'
    return build_page("Reset Password", form_wrapper("Reset Password", content, req.query.get('err',''), req.query.get('msg','')), "login-bg")

@login_routes.post('/api/forgot_password')
async def api_forgot_password(req):
    try: tg_id = int((await req.post()).get('tg_id'))
    except: return web.HTTPFound('/forgot_password?err=Invalid Telegram ID')
    try:
        otp = await web_db.generate_otp(tg_id)
    except OTPRateLimited:
        return web.HTTPFound('/forgot_password?err=Too many OTP requests. Please try again after 10 minutes.')
    if otp:
        try:
            await temp.BOT.send_message(tg_id, f"🔐 **Fast Finder Password Reset**\n\nYour Password Reset OTP is: `{otp}`\n\nValid for 10 minutes. Do not share!")
            return web.HTTPFound('/forgot_password?msg=OTP sent to your Telegram!')
        except: return web.HTTPFound('/forgot_password?err=Error sending OTP. Have you started the bot?')
    return web.HTTPFound('/forgot_password?err=Telegram ID not registered!')

@login_routes.post('/api/reset_password')
async def api_reset_password(req):
    d = await req.post()
    try: tg_id = int(d.get('tg_id'))
    except: return web.HTTPFound('/forgot_password?err=Invalid Input')
    new_password = d.get('new_password') or ''
    if len(new_password) < MIN_PASSWORD_LEN:
        return web.HTTPFound(f'/forgot_password?err=Password must be at least {MIN_PASSWORD_LEN} characters')
    if await web_db.verify_otp_and_reset(tg_id, d.get('otp'), new_password):
        # पासवर्ड बदला है तो पुराने सारे लॉगिन सेशन बंद (RAM + DB)
        for k in [k for k, v in temp.USER_SESSIONS.items() if v.get('tg_id') == tg_id]:
            temp.USER_SESSIONS.pop(k, None)
        try:
            await web_db.delete_user_sessions(tg_id)
        except Exception:
            pass
        return web.HTTPFound('/login?msg=Password updated successfully! Please login.')
    return web.HTTPFound('/forgot_password?err=Invalid or Expired OTP.')
