import asyncio
import functools
import gzip
import html
import json
import logging
import logging.handlers
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import telebot
from telebot import types, util
from telebot.apihelper import ApiTelegramException

try:  # حالت فایل بزرگ (اختیاری)
    from telethon import TelegramClient, events
    from telethon.tl.types import DocumentAttributeAudio
    TELETHON = True
except Exception:
    TELETHON = False

# ═══════════════════════════ تنظیمات اصلی ═══════════════════════════
BASE = Path(__file__).resolve().parent
TOKEN = os.getenv("BOT_TOKEN", "8283289700:AAFmenImBoyJlZ6bAEOLx8IL4S0lOiu7MUU")
ADMINS = {1601379026} | {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}

# برای فایل‌های بالای ۲۰ مگ: از https://my.telegram.org بگیر و اینجا بذار
API_ID = int(os.getenv("API_ID", "0") or 0)
API_HASH = os.getenv("API_HASH", "")

DB_PATH = Path(os.getenv("DB_PATH", BASE / "data" / "bot.db"))
TMP_DIR = BASE / "tmp"
MAX_PARALLEL = int(os.getenv("MAX_PARALLEL", "1"))      # پردازش هم‌زمان (برای سرور اشتراکی ۱ بهتره)
BOT_API_DL = 20 * 1024 * 1024                            # سقف دانلود Bot API
BOT_API_UL = 49 * 1024 * 1024                            # سقف آپلود Bot API
PENDING_TTL = 30 * 60
PAGE_SIZE = 6
START_TS = time.time()

PRESETS = {"2": ("2x", 10.0, "success"), "5": ("5x", 18.0, "primary"), "10": ("10x", 26.0, "danger")}
STYLES = {
    "bal": ("⚖️ متعادل", 80, 0.6),
    "deep": ("🌊 عمیق", 60, 0.7),
    "punch": ("🥁 پانچی", 120, 0.5),
}
BITRATES = [128, 192, 256, 320]

DEFAULT_WELCOME = (
    "سلام {name} 👋✨\n"
    "به <b>ربات افزایش بیس</b> خوش اومدی 🔊🔥\n\n"
    "🎵 آهنگ (یا ویس و ویدیو) بفرست، سبک و میزان بیس رو انتخاب کن\n"
    "(2x / 5x / 10x یا یه عدد از <b>1 تا 100</b>) تا نسخه بیس‌دارش رو برات بفرستم 💥\n\n"
    "📌 از دکمه‌های پایین استفاده کن"
)
DEFAULT_CAPTION = "🔊 نسخه بیس‌دار • {label} • {style}\n🤖 @{bot}"

BTN_HELP, BTN_ME, BTN_TOP = "📖 راهنما", "👤 آمار من", "🏆 برترین‌ها"
BTN_SUP, BTN_ADMIN = "📞 پشتیبانی", "👑 پنل مدیریت"

# ═══════════════════════════ پیام‌های خطا ═══════════════════════════
ERR = {
    "banned": "🚫 <b>دسترسی مسدوده</b>\nشما از استفاده از این ربات محروم شده‌اید.",
    "maint": "🔧 <b>ربات در حال تعمیره</b>\nکمی بعد دوباره امتحان کن.",
    "join": "📢 برای استفاده از ربات اول تو کانال‌های زیر عضو شو، بعد دکمه «عضو شدم» رو بزن:",
    "join_no": "❗ هنوز عضو همه کانال‌ها نشدی!",
    "too_big": "⚠️ <b>حجم فایل زیاده</b>\nفایل تو {size} هست ولی سقف مجاز {max} ـه.",
    "large_off": "📦 <b>حالت فایل بزرگ فعال نیست</b>\nفایل‌های بالای ۲۰ مگابایت هنوز پشتیبانی نمی‌شن. به ادمین بگو فعالش کنه.",
    "busy": "⏳ آهنگ قبلیت هنوز در حال پردازشه، یکم صبر کن.",
    "flood": "⏱ آروم‌تر! بین هر آهنگ چند ثانیه صبر کن.",
    "expired": "⌛ این آهنگ منقضی شده، دوباره بفرستش 🎵",
    "need_song": "🎵 اول آهنگتو بفرست، بعد عدد بیس رو بگو.",
    "bad_type": "⚠️ فقط فایل <b>صوتی یا ویدیویی</b> بفرست 🎵",
    "num_range": "⚠️ یه عدد بین <b>1 تا 100</b> بفرست.",
    "limit": "⏱ <b>سقف روزانه تموم شد</b>\nامروز {n} آهنگ پردازش کردی. فردا برگرد 🌙",
    "dl_fail": "❌ <b>دریافت فایل ناموفق بود</b>\nدوباره بفرستش.",
    "ffmpeg": "❌ <b>این فایل قابل پردازش نیست</b>\nخراب یا فرمتش پشتیبانی نمی‌شه. فایل دیگه‌ای بفرست.",
    "timeout": "⌛ <b>پردازش خیلی طول کشید</b> و متوقف شد. یه فایل کوتاه‌تر امتحان کن.",
    "out_big": "⚠️ خروجی از حجم مجاز ارسال بزرگ‌تر شد. یه آهنگ کوتاه‌تر بفرست.",
    "ul_fail": "❌ <b>ارسال آهنگ ناموفق بود</b>\nچند لحظه بعد دوباره امتحان کن.",
    "net": "🌐 <b>مشکل شبکه</b>\nچند لحظه بعد دوباره امتحان کن.",
    "disk": "💽 فضای سرور کمه، کمی بعد امتحان کن.",
    "internal": "❌ <b>یه مشکل غیرمنتظره پیش اومد</b>\nدوباره امتحان کن؛ گزارشش برای ادمین ثبت شد.",
    "unexpected": "⚠️ یه خطای غیرمنتظره پیش اومد. دوباره امتحان کن.",
    "no_perm": "⛔ دسترسی نداری.",
}


def E(key, **kw):
    return ERR[key].format(**kw) if kw else ERR[key]


class UserError(Exception):
    def __init__(self, key, **kw):
        super().__init__(key)
        self.msg = E(key, **kw)


# ═══════════════════════════ لاگ ═══════════════════════════
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler(),
              logging.handlers.RotatingFileHandler(BASE / "bot.log", maxBytes=1_000_000,
                                                   backupCount=2, encoding="utf-8")])
log = logging.getLogger("bassbot")


def find_ffmpeg():
    p = shutil.which("ffmpeg")
    if p:
        return p
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


FFMPEG = find_ffmpeg()
TL_ENABLED = bool(TELETHON and API_ID and API_HASH)
TL_OK = False
STYLE_OK = True  # اگه تلگرام رنگ دکمه رو رد کنه خودکار false می‌شه

# ═══════════════════════════ دکمه‌های رنگی ═══════════════════════════
_EMO = {"primary": "🔵 ", "success": "🟢 ", "danger": "🔴 "}


class CB(types.InlineKeyboardButton):
    """دکمه شیشه‌ای با پشتیبانی از style (primary / success / danger)."""

    def __init__(self, text, callback_data=None, url=None, style=None):
        super().__init__(text, callback_data=callback_data, url=url)
        self.style = style

    def to_dict(self):
        d = super().to_dict()
        if self.style and STYLE_OK:
            d["style"] = self.style
        return d


class KB(types.KeyboardButton):
    """دکمه کیبورد پایین صفحه با style."""

    def __init__(self, text, style=None):
        super().__init__(text)
        self.style = style

    def to_dict(self):
        d = super().to_dict()
        if self.style and STYLE_OK:
            d["style"] = self.style
        return d


def btn(text, data=None, url=None, st=None):
    if st and not STYLE_OK:
        text = _EMO.get(st, "") + text
    return CB(text, data, url, st)


def mk(*rows):
    m = types.InlineKeyboardMarkup()
    for r in rows:
        if r:
            m.row(*r)
    return m


def main_kb(uid):
    k = types.ReplyKeyboardMarkup(resize_keyboard=True)
    k.row(KB(BTN_HELP, "primary"), KB(BTN_ME, "success"))
    k.row(KB(BTN_TOP, "primary"), KB(BTN_SUP))
    if uid in ADMINS:
        k.row(KB(BTN_ADMIN, "danger"))
    return k


bot = telebot.TeleBot(TOKEN, parse_mode="HTML", threaded=True, num_threads=8)
JOBS = ThreadPoolExecutor(max_workers=MAX_PARALLEL, thread_name_prefix="boost")
pending: dict = {}
busy: set = set()
astate: dict = {}
tl_cache: dict = {}
_last_media: dict = {}

# ═══════════════════════════ دیتابیس ═══════════════════════════
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
TMP_DIR.mkdir(parents=True, exist_ok=True)
_db = sqlite3.connect(DB_PATH, check_same_thread=False)
_db.row_factory = sqlite3.Row
_lock = threading.RLock()
_sc: dict = {}      # کش تنظیمات
_seen: dict = {}    # آخرین ثبت فعالیت کاربر
_member: dict = {}  # کش عضویت


def _init_db():
    with _lock:
        try:
            _db.execute("PRAGMA journal_mode=WAL")
            _db.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            pass
        _db.executescript("""
            CREATE TABLE IF NOT EXISTS users(
                id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
                joined INTEGER, last_seen INTEGER, banned INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS channels(
                id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER UNIQUE,
                title TEXT, link TEXT);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS jobs(
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                gain REAL, ts INTEGER);
        """)
        for tbl, col, ddl in (("users", "vip", "INTEGER DEFAULT 0"),
                              ("users", "style", "TEXT DEFAULT 'bal'"),
                              ("jobs", "mb", "REAL DEFAULT 0")):
            cols = {r["name"] for r in _db.execute(f"PRAGMA table_info({tbl})")}
            if col not in cols:
                _db.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {ddl}")
        _db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_user_ts ON jobs(user_id, ts)")
        _db.commit()


_init_db()


def ex(sql, args=()):
    with _lock:
        _db.execute(sql, args)
        _db.commit()


def one(sql, args=()):
    with _lock:
        return _db.execute(sql, args).fetchone()


def many(sql, args=()):
    with _lock:
        return _db.execute(sql, args).fetchall()


def cnt(sql, args=()):
    return one(sql, args)["c"]


def get_setting(key, default=""):
    if key not in _sc:
        r = one("SELECT value FROM settings WHERE key=?", (key,))
        _sc[key] = r["value"] if r else None
    return default if _sc[key] is None else _sc[key]


def set_setting(key, value):
    ex("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, str(value)))
    _sc[key] = str(value)


# ═══════════════════════════ ابزارها ═══════════════════════════
def esc(s):
    return html.escape(str(s) if s is not None else "")


def norm_digits(s):
    return (s or "").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")).strip()


def fdate(ts):
    return time.strftime("%Y-%m-%d", time.localtime(ts or 0))


def fdt(ts):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts or 0))


def day_start():
    return int(time.time()) // 86400 * 86400


def fsize(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


def bar(pct, n=10):
    f = max(0, min(n, round(pct / 100 * n)))
    return "▰" * f + "▱" * (n - f)


def fdur(sec):
    sec = int(sec)
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m, _ = divmod(r, 60)
    return (f"{d}d " if d else "") + f"{h}h {m}m"


def notify_admins(text, kb=None):
    for a in ADMINS:
        try:
            bot.send_message(a, text, reply_markup=kb)
        except Exception:
            pass


def safe_edit(cb, text, kb=None):
    try:
        bot.edit_message_text(text, cb.message.chat.id, cb.message.message_id, reply_markup=kb)
    except ApiTelegramException as e:
        if "not modified" not in str(e):
            bot.send_message(cb.message.chat.id, text, reply_markup=kb)


def safe_answer(cb, text=None, alert=False):
    try:
        bot.answer_callback_query(cb.id, text, show_alert=alert)
    except Exception:
        pass


def get_pending(uid):
    p = pending.get(uid)
    if p and time.time() - p["ts"] > PENDING_TTL:
        pending.pop(uid, None)
        return None
    return p


def max_in_bytes():
    mb = int(get_setting("max_mb", "200") or 200)
    if not TL_OK:
        return min(mb * 1024 * 1024, BOT_API_DL)
    return mb * 1024 * 1024


def touch_user(u):
    now = time.time()
    if now - _seen.get(u.id, 0) < 60:
        return
    _seen[u.id] = now
    t = int(now)
    existed = one("SELECT 1 FROM users WHERE id=?", (u.id,))
    with _lock:
        _db.execute("INSERT OR IGNORE INTO users(id,username,first_name,joined,last_seen) VALUES(?,?,?,?,?)",
                    (u.id, u.username, u.full_name, t, t))
        _db.execute("UPDATE users SET username=?, first_name=?, last_seen=? WHERE id=?",
                    (u.username, u.full_name, t, u.id))
        _db.commit()
    if not existed and u.id not in ADMINS and get_setting("notify", "1") == "1":
        un = f"@{u.username}" if u.username else "—"
        notify_admins(f"🆕 <b>کاربر جدید</b>\n👤 {esc(u.full_name)}\n"
                      f"🆔 <code>{u.id}</code> | {esc(un)}\n👥 مجموع: {cnt('SELECT COUNT(*) c FROM users')}")


def guard(fn):
    @functools.wraps(fn)
    def wrapper(arg, *a, **k):
        try:
            return fn(arg, *a, **k)
        except Exception as e:
            log.exception("handler error in %s", fn.__name__)
            try:
                if isinstance(arg, types.CallbackQuery):
                    bot.answer_callback_query(arg.id, "⚠️ خطای غیرمنتظره، دوباره امتحان کن.", show_alert=True)
                else:
                    bot.send_message(arg.chat.id, E("unexpected"))
            except Exception:
                pass
            notify_admins(f"⚠️ <b>خطای ربات</b> ({esc(fn.__name__)})\n"
                          f"<code>{esc(type(e).__name__)}: {esc(str(e))[:400]}</code>")
    return wrapper


def private(m):
    return m.chat.type == "private"


# ═══════════════════════════ دسترسی و جوین اجباری ═══════════════════════════
def not_joined(uid):
    missing = []
    now = time.time()
    for ch in many("SELECT * FROM channels"):
        if now - _member.get((uid, ch["chat_id"]), 0) < 120:
            continue
        try:
            st = bot.get_chat_member(ch["chat_id"], uid).status
            if st in ("left", "kicked"):
                missing.append(ch)
            else:
                _member[(uid, ch["chat_id"])] = now
        except Exception as e:
            log.warning("چک عضویت در %s ممکن نیست (ربات ادمین نیست؟): %s", ch["title"], e)
    return missing


def gate(event, user):
    touch_user(user)
    is_cb = isinstance(event, types.CallbackQuery)
    chat_id = event.message.chat.id if is_cb else event.chat.id
    if user.id in ADMINS:
        return True

    def deny(text, short=None):
        if is_cb:
            safe_answer(event, short or re.sub("<.*?>", "", text), True)
        else:
            bot.send_message(chat_id, text)

    row = one("SELECT banned FROM users WHERE id=?", (user.id,))
    if row and row["banned"]:
        deny(E("banned"), "🚫 شما مسدود شده‌اید")
        return False
    if get_setting("maintenance") == "1":
        deny(E("maint"), "🔧 ربات در حال تعمیره")
        return False
    missing = not_joined(user.id)
    if missing:
        rows = [[btn(f"📢 {ch['title']}", url=ch["link"], st="primary")] for ch in missing]
        rows.append([btn("✅ عضو شدم", "chk", st="success")])
        if is_cb:
            safe_answer(event, E("join_no"), True)
            if event.data != "chk":
                bot.send_message(chat_id, E("join"), reply_markup=mk(*rows))
        else:
            bot.send_message(chat_id, E("join"), reply_markup=mk(*rows))
        return False
    return True


# ═══════════════════════════ Telethon (فایل بزرگ) ═══════════════════════════
tl_loop = None
tl_client = None


def tl_call(coro, timeout):
    return asyncio.run_coroutine_threadsafe(coro, tl_loop).result(timeout)


def start_telethon():
    global tl_loop
    ready = threading.Event()
    tl_loop = asyncio.new_event_loop()

    async def _main():
        global tl_client, TL_OK
        try:
            tl_client = TelegramClient(str(DB_PATH.parent / "tl_session"), API_ID, API_HASH)
            await tl_client.start(bot_token=TOKEN)

            @tl_client.on(events.NewMessage(incoming=True))
            async def _cache(ev):
                if ev.is_private and ev.message.media:
                    tl_cache[(ev.chat_id, ev.message.id)] = ev.message
                    if len(tl_cache) > 300:
                        for k in list(tl_cache)[:100]:
                            tl_cache.pop(k, None)

            TL_OK = True
            log.info("✅ حالت فایل بزرگ (Telethon) فعال شد")
        except Exception:
            log.exception("راه‌اندازی Telethon ناموفق بود؛ حالت فایل بزرگ خاموش می‌مونه")
        finally:
            ready.set()

    def runner():
        asyncio.set_event_loop(tl_loop)
        tl_loop.run_until_complete(_main())
        tl_loop.run_forever()

    threading.Thread(target=runner, daemon=True, name="telethon").start()
    ready.wait(60)


async def _tl_download(chat_id, msg_id, path, progress):
    msg = tl_cache.get((chat_id, msg_id))
    if msg is None:
        msg = await tl_client.get_messages(chat_id, ids=msg_id)
    if not msg or not msg.media:
        raise UserError("dl_fail")
    await tl_client.download_media(msg, file=str(path), progress_callback=progress)


async def _tl_upload(chat_id, path, title, performer, duration, caption, progress):
    attrs = [DocumentAttributeAudio(duration=int(duration), title=title[:60], performer=(performer or "")[:60])]
    await tl_client.send_file(chat_id, str(path), caption=caption, parse_mode="html",
                              attributes=attrs, progress_callback=progress)


# ═══════════════════════════ بخش کاربر ═══════════════════════════
def send_welcome(chat_id, user):
    text = get_setting("welcome", DEFAULT_WELCOME).replace("{name}", esc(user.full_name))
    try:
        bot.send_message(chat_id, text, reply_markup=main_kb(user.id))
    except ApiTelegramException:
        bot.send_message(chat_id, html.escape(text), reply_markup=main_kb(user.id))


def send_help(chat_id):
    mx = max_in_bytes()
    bot.send_message(
        chat_id,
        "📖 <b>راهنمای ربات</b>\n\n"
        "1️⃣ آهنگ (یا ویس / ویدیو) بفرست\n"
        "2️⃣ سبک بیس رو انتخاب کن:\n"
        "   ⚖️ متعادل • 🌊 عمیق (زیر و کوبنده) • 🥁 پانچی (ضربه‌ای)\n"
        "3️⃣ میزان رو بزن: 🟢 2x  🔵 5x  🔴 10x\n"
        "   یا یه عدد <b>1 تا 100</b> بفرست (بزرگ‌تر = بیس قوی‌تر 💥)\n"
        "4️⃣ می‌تونی «پیش‌نمایش ۳۰ ثانیه‌ای» رو روشن کنی تا اول یه نمونه کوتاه بگیری\n"
        "5️⃣ چند لحظه صبر کن تا نسخه بیس‌دار برات بیاد 🎧\n\n"
        f"📦 حداکثر حجم فایل: <b>{fsize(mx)}</b>\n"
        "⚠️ برای بهترین کیفیت، آهنگ اصلی رو بفرست و عدد خیلی بالا نزن؛ بالای ۷۰ ممکنه صدا فشرده بشه.")


def send_me(chat_id, uid):
    total = cnt("SELECT COUNT(*) c FROM jobs WHERE user_id=?", (uid,))
    today = cnt("SELECT COUNT(*) c FROM jobs WHERE user_id=? AND ts>=?", (uid, day_start()))
    r = one("SELECT joined, vip FROM users WHERE id=?", (uid,))
    lim = int(get_setting("daily_limit", "0") or 0)
    if uid in ADMINS or (r and r["vip"]) or not lim:
        quota = "نامحدود ♾"
    else:
        quota = f"{max(lim - today, 0)} از {lim}"
    rank = cnt("SELECT COUNT(*) c FROM (SELECT user_id FROM jobs GROUP BY user_id HAVING COUNT(*) > ?)", (total,)) + 1
    badge = "👑 ادمین" if uid in ADMINS else ("⭐ VIP" if r and r["vip"] else "👤 عادی")
    bot.send_message(chat_id, f"👤 <b>پروفایل من</b>\n\n🆔 <code>{uid}</code>\n🏷 وضعیت: {badge}\n"
                              f"📅 عضویت: {fdate(r['joined'] if r else 0)}\n🎧 کل آهنگ‌ها: <b>{total}</b>\n"
                              f"🎶 امروز: <b>{today}</b>\n⏱ سهمیه امروز: <b>{quota}</b>\n🏆 رتبه: <b>{rank}</b>")


def send_top(chat_id):
    rows = many("SELECT u.first_name n, COUNT(*) c FROM jobs j JOIN users u ON u.id=j.user_id "
                "WHERE j.ts>=? GROUP BY j.user_id ORDER BY c DESC LIMIT 10", (int(time.time()) - 30 * 86400,))
    if not rows:
        return bot.send_message(chat_id, "🏆 هنوز کسی تو لیست نیست. اولیش تو باش!")
    medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
    lines = []
    for i, r in enumerate(rows):
        n = r["n"] or "؟"
        lines.append(f"{medals[i]} {esc(n[:3])}{'•' * 3} — <b>{r['c']}</b> آهنگ")
    bot.send_message(chat_id, "🏆 <b>برترین‌های ۳۰ روز اخیر</b>\n\n" + "\n".join(lines))


def send_support(chat_id):
    sup = get_setting("support", "").lstrip("@").strip()
    if not sup:
        return bot.send_message(chat_id, "📞 پشتیبانی هنوز تنظیم نشده.")
    bot.send_message(chat_id, "📞 برای ارتباط با پشتیبانی روی دکمه بزن:",
                     reply_markup=mk([btn("💬 ارتباط با پشتیبانی", url=f"https://t.me/{sup}", st="primary")]))


@bot.message_handler(commands=["start"], func=private)
@guard
def cmd_start(m):
    astate.pop(m.from_user.id, None)
    if not gate(m, m.from_user):
        return
    send_welcome(m.chat.id, m.from_user)
    if m.from_user.id in ADMINS:
        bot.send_message(m.chat.id, "👑 تو ادمینی! پنل مدیریت: /admin یا دکمه پایین.")


@bot.message_handler(commands=["help"], func=private)
@guard
def cmd_help(m):
    if gate(m, m.from_user):
        send_help(m.chat.id)


@bot.message_handler(commands=["me"], func=private)
@guard
def cmd_me(m):
    if gate(m, m.from_user):
        send_me(m.chat.id, m.from_user.id)


@bot.message_handler(commands=["top"], func=private)
@guard
def cmd_top(m):
    if gate(m, m.from_user):
        send_top(m.chat.id)


def level_kb(style="bal", preview=False):
    styles = [btn(("✅ " if k == style else "") + v[0], f"sty:{k}", st=("success" if k == style else None))
              for k, v in STYLES.items()]
    return mk([btn(f"{v[0]} بیس", f"bass:{k}", st=v[2]) for k, v in PRESETS.items()], styles,
              [btn("🎧 پیش‌نمایش ۳۰ ثانیه: " + ("روشن ✅" if preview else "خاموش"), "prev:t",
                   st=("primary" if preview else None))],
              [btn("❌ لغو", "bass:x", st="danger")])


def show_panel(chat_id, uid):
    p = get_pending(uid)
    bot.send_message(
        chat_id,
        f"🎧 <b>آهنگت رسید!</b>\n📦 حجم: {fsize(p['size']) if p else '?'}\n\n"
        "🎛 سبک بیس رو انتخاب کن و بعد میزانش رو بزن،\n"
        "یا <b>یه عدد از 1 تا 100</b> بفرست (هرچی بزرگ‌تر، بیس قوی‌تر 💥)",
        reply_markup=level_kb(p["style"] if p else "bal", p["preview"] if p else False))


AUDIO_EXT = (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus", ".aac", ".wma", ".amr",
             ".mp4", ".mkv", ".webm", ".mov", ".avi", ".3gp")


def is_media_doc(d):
    mt = (d.mime_type or "").lower()
    return mt.startswith(("audio", "video")) or (d.file_name or "").lower().endswith(AUDIO_EXT)


@bot.message_handler(commands=["admin", "cancel"], func=lambda m: private(m) and m.from_user.id in ADMINS)
@guard
def cmd_admin(m):
    astate.pop(m.from_user.id, None)
    t, kb = admin_home()
    bot.send_message(m.chat.id, t, reply_markup=kb)


@bot.message_handler(content_types=util.content_type_media,
                     func=lambda m: private(m) and m.from_user.id in astate)
@guard
def admin_state_msg(m):
    admin_state(m)


@bot.message_handler(content_types=["audio", "voice", "video", "document"], func=private)
@guard
def got_media(m):
    uid = m.from_user.id
    if not gate(m, m.from_user):
        pending.pop(uid, None)
        return
    obj = m.audio or m.voice or m.video or m.document
    if m.document and not is_media_doc(m.document):
        return bot.send_message(m.chat.id, E("bad_type"))
    now = time.time()
    if now - _last_media.get(uid, 0) < 2:
        return bot.send_message(m.chat.id, E("flood"))
    _last_media[uid] = now
    if uid in busy:
        return bot.send_message(m.chat.id, E("busy"))
    size = obj.file_size or 0
    mx = max_in_bytes()
    if size > mx:
        if size > BOT_API_DL and not TL_OK and size <= int(get_setting("max_mb", "200") or 200) * 1048576:
            return bot.send_message(m.chat.id, E("large_off"))
        return bot.send_message(m.chat.id, E("too_big", size=fsize(size), max=fsize(mx)))
    if size > BOT_API_DL and not TL_OK:
        return bot.send_message(m.chat.id, E("large_off"))
    name = str(getattr(obj, "title", None) or getattr(obj, "file_name", None) or "Track")
    ur = one("SELECT style FROM users WHERE id=?", (uid,))
    pending[uid] = dict(
        file_id=obj.file_id, size=size, chat_id=m.chat.id, msg_id=m.message_id,
        title=name.rsplit(".", 1)[0] if "." in name else name,
        performer=getattr(obj, "performer", None),
        style=(ur["style"] if ur and ur["style"] in STYLES else "bal"), preview=False, ts=now)
    show_panel(m.chat.id, uid)


@bot.message_handler(content_types=["text"], func=private)
@guard
def got_text(m):
    if not gate(m, m.from_user):
        return
    txt = (m.text or "").strip()
    if txt == BTN_HELP:
        return send_help(m.chat.id)
    if txt == BTN_ME:
        return send_me(m.chat.id, m.from_user.id)
    if txt == BTN_TOP:
        return send_top(m.chat.id)
    if txt == BTN_SUP:
        return send_support(m.chat.id)
    if txt == BTN_ADMIN and m.from_user.id in ADMINS:
        return cmd_admin(m)
    t = norm_digits(txt)
    if not t.isdigit():
        return bot.send_message(m.chat.id, "🎵 آهنگتو بفرست تا بیسشو زیاد کنم.\nراهنما: /help")
    p = get_pending(m.from_user.id)
    if not p:
        return bot.send_message(m.chat.id, E("need_song"))
    n = int(t)
    if not 1 <= n <= 100:
        return bot.send_message(m.chat.id, E("num_range"))
    submit_boost(m.chat.id, m.from_user, round(n * 0.3, 1), f"Lv{n}", p)


@bot.callback_query_handler(func=lambda c: True)
@guard
def on_callback(c):
    data = c.data or ""
    uid, cid = c.from_user.id, c.message.chat.id

    if data.startswith("adm:"):
        if uid not in ADMINS:
            return safe_answer(c, E("no_perm"), True)
        return adm_action(c)

    if data == "chk":
        _member.clear()
        if not gate(c, c.from_user):
            return
        try:
            bot.delete_message(cid, c.message.message_id)
        except Exception:
            pass
        send_welcome(cid, c.from_user)
        if get_pending(uid):
            show_panel(cid, uid)
        return safe_answer(c, "✅ عضویتت تایید شد")

    if data == "prev:t":
        p = get_pending(uid)
        if not p:
            return safe_answer(c, "⌛ این آهنگ منقضی شده، دوباره بفرستش 🎵", True)
        p["preview"] = not p["preview"]
        try:
            bot.edit_message_reply_markup(cid, c.message.message_id, reply_markup=level_kb(p["style"], p["preview"]))
        except ApiTelegramException:
            pass
        return safe_answer(c, "🎧 پیش‌نمایش " + ("روشن شد" if p["preview"] else "خاموش شد"))

    if data.startswith("sty:"):
        p = get_pending(uid)
        if not p:
            return safe_answer(c, "⌛ این آهنگ منقضی شده، دوباره بفرستش 🎵", True)
        key = data.split(":")[1]
        if key not in STYLES:
            return safe_answer(c)
        p["style"] = key
        ex("UPDATE users SET style=? WHERE id=?", (key, uid))
        try:
            bot.edit_message_reply_markup(cid, c.message.message_id, reply_markup=level_kb(key, p["preview"]))
        except ApiTelegramException:
            pass
        return safe_answer(c, f"سبک: {STYLES[key][0]}")

    if data.startswith("bass:"):
        key = data.split(":")[1]
        if key == "x":
            pending.pop(uid, None)
            safe_edit(c, "❌ لغو شد. هر وقت خواستی آهنگ جدید بفرست.")
            return safe_answer(c)
        if key not in PRESETS:
            return safe_answer(c)
        if not gate(c, c.from_user):
            return
        p = get_pending(uid)
        if not p:
            return safe_answer(c, "⌛ این آهنگ منقضی شده، دوباره بفرستش 🎵", True)
        label, gain, _ = PRESETS[key]
        safe_answer(c)
        try:
            bot.delete_message(cid, c.message.message_id)
        except Exception:
            pass
        return submit_boost(cid, c.from_user, gain, label, p)
    safe_answer(c)


# ═══════════════════════════ پردازش بیس ═══════════════════════════
def safe_name(s):
    s = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", s).strip()
    return (s or "Track")[:80]


def run_ffmpeg(src, out, gain, style, preview, size_bytes):
    _, freq, width = STYLES.get(style, STYLES["bal"])
    br = int(get_setting("bitrate", "192") or 192)
    af = (f"volume=-{gain / 3:.1f}dB,bass=g={gain}:f={freq}:w={width},alimiter=limit=0.95:level=0")
    cmd = [FFMPEG, "-nostdin", "-y", "-threads", "2", "-i", str(src), "-vn", "-map_metadata", "-1"]
    if preview:
        cmd += ["-t", "30"]
    cmd += ["-af", af, "-c:a", "libmp3lame", "-b:a", f"{br}k", str(out)]
    timeout = max(900, int(size_bytes / 1048576) * 25)
    kw = {}
    if os.name == "posix":
        kw["preexec_fn"] = lambda: os.nice(10)  # کم‌اولویت تا سرور اشتراکی اذیت نشه
    try:
        r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=timeout, **kw)
    except subprocess.TimeoutExpired:
        raise UserError("timeout")
    err = r.stderr.decode(errors="ignore")
    if r.returncode != 0 or not out.exists():
        log.error("ffmpeg error: %s", err[-500:])
        raise UserError("ffmpeg")
    dur = 0
    mt = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", err)
    if mt:
        dur = int(mt.group(1)) * 3600 + int(mt.group(2)) * 60 + float(mt.group(3))
    return min(dur, 30) if preview and dur else dur


def submit_boost(chat_id, user, gain, label, p):
    uid = user.id
    if uid in busy:
        return bot.send_message(chat_id, E("busy"))
    pending.pop(uid, None)
    row = one("SELECT vip FROM users WHERE id=?", (uid,))
    if uid not in ADMINS and not (row and row["vip"]):
        lim = int(get_setting("daily_limit", "0") or 0)
        if lim:
            done = cnt("SELECT COUNT(*) c FROM jobs WHERE user_id=? AND ts>=?", (uid, day_start()))
            if done >= lim:
                return bot.send_message(chat_id, E("limit", n=done))
    busy.add(uid)
    ahead = len(busy) - 1
    JOBS.submit(job_wrapper, chat_id, user, gain, label, p, ahead)


def job_wrapper(chat_id, user, gain, label, p, ahead):
    try:
        run_boost(chat_id, user, gain, label, p, ahead)
    except Exception:
        log.exception("job crashed")
    finally:
        busy.discard(user.id)


def run_boost(chat_id, user, gain, label, p, ahead):
    uid = user.id
    queue_txt = f"⏳ در صف پردازش (نفر {ahead - MAX_PARALLEL + 1})..." if ahead >= MAX_PARALLEL else None
    status = bot.send_message(chat_id, queue_txt or "⏬ در حال دریافت آهنگ...")

    def step(text):
        try:
            bot.edit_message_text(text, chat_id, status.message_id)
        except Exception:
            pass

    def progress(prefix):
        st = {"t": 0}

        def cb(cur, total):
            now = time.time()
            if now - st["t"] < 4 and cur < total:
                return
            st["t"] = now
            pct = int(cur * 100 / total) if total else 0
            threading.Thread(target=step, args=(f"{prefix}\n{bar(pct)} {pct}%  ({fsize(cur)} / {fsize(total)})",),
                             daemon=True).start()
        return cb

    try:
        size = p["size"]
        preview = p.get("preview", False)
        style = p.get("style", "bal")
        with tempfile.TemporaryDirectory(dir=TMP_DIR) as tmp:
            if shutil.disk_usage(tmp).free < max(size, 5 * 1048576) * 3:
                raise UserError("disk")
            src = Path(tmp) / "in"
            tag = f"Bass {label}" + (" Preview" if preview else "")
            out = Path(tmp) / f"{safe_name(p['title'])} ({tag}).mp3"
            step("⏬ در حال دریافت آهنگ...")
            if size <= BOT_API_DL:
                try:
                    info = bot.get_file(p["file_id"])
                    src.write_bytes(bot.download_file(info.file_path))
                except ApiTelegramException as e:
                    if "too big" in str(e).lower() and TL_OK:
                        tl_call(_tl_download(p["chat_id"], p["msg_id"], src, progress("⏬ دریافت فایل بزرگ...")), 3600)
                    else:
                        raise UserError("dl_fail")
            else:
                if not TL_OK:
                    raise UserError("large_off")
                tl_call(_tl_download(p["chat_id"], p["msg_id"], src, progress("⏬ دریافت فایل بزرگ...")), 3600)
            step("🎛 در حال افزایش بیس... 🔊\n" + bar(50))
            dur = run_ffmpeg(src, out, gain, style, preview, size)
            try:
                src.unlink()
            except Exception:
                pass
            osz = out.stat().st_size
            uname = bot.get_me().username
            cap = (get_setting("caption", DEFAULT_CAPTION)
                   .replace("{label}", label + (" • پیش‌نمایش" if preview else ""))
                   .replace("{style}", STYLES.get(style, STYLES["bal"])[0]).replace("{bot}", uname))
            if osz <= BOT_API_UL:
                step("📤 در حال ارسال...")
                with open(out, "rb") as f:
                    bot.send_audio(chat_id, f, title=f"{p['title']} ({tag})", performer=p["performer"],
                                   caption=cap, duration=int(dur) or None, timeout=600)
            else:
                if not TL_OK:
                    raise UserError("out_big")
                tl_call(_tl_upload(chat_id, out, f"{p['title']} ({tag})", p["performer"], dur, cap,
                                   progress("📤 در حال ارسال فایل بزرگ...")), 7200)
        ex("INSERT INTO jobs(user_id,gain,ts,mb) VALUES(?,?,?,?)", (uid, gain, int(time.time()), size / 1048576))
    except UserError as e:
        bot.send_message(chat_id, e.msg)
    except Exception as e:
        log.exception("boost failed")
        s = str(e).lower()
        if any(x in s for x in ("connection", "timed out", "timeout", "network", "read timed")):
            bot.send_message(chat_id, E("net"))
        elif isinstance(e, ApiTelegramException):
            bot.send_message(chat_id, E("ul_fail"))
            notify_admins(f"⚠️ <b>خطای ارسال</b>\n👤 {esc(user.full_name)} (<code>{uid}</code>)\n"
                          f"<code>{esc(str(e))[:300]}</code>")
        else:
            bot.send_message(chat_id, E("internal"))
            notify_admins(f"⚠️ <b>خطا در پردازش</b>\n👤 {esc(user.full_name)} (<code>{uid}</code>)\n"
                          f"<code>{esc(type(e).__name__)}: {esc(str(e))[:300]}</code>")
    finally:
        try:
            bot.delete_message(chat_id, status.message_id)
        except Exception:
            pass


# ═══════════════════════════ بک‌آپ ═══════════════════════════
TABLES = (("users", "REPLACE"), ("channels", "REPLACE"), ("settings", "REPLACE"), ("jobs", "IGNORE"))


def build_backup():
    data = {"version": 2, "created": int(time.time())}
    for t, _ in TABLES:
        data[t] = [dict(r) for r in many(f"SELECT * FROM {t}")]
    return data


def send_backup(chat_id, auto=False):
    data = build_backup()
    raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
    name = f"bassbot_backup_{time.strftime('%Y%m%d_%H%M')}.json"
    if len(raw) > 40 * 1048576:
        raw, name = gzip.compress(raw), name + ".gz"
    with tempfile.TemporaryDirectory(dir=TMP_DIR) as tmp:
        p = Path(tmp) / name
        p.write_bytes(raw)
        with open(p, "rb") as f:
            bot.send_document(
                chat_id, f, timeout=600,
                caption=("🗓 بک‌آپ خودکار\n" if auto else "💾 بک‌آپ دیتابیس\n") +
                        f"👥 {len(data['users'])} کاربر • 📢 {len(data['channels'])} کانال • "
                        f"⚙️ {len(data['settings'])} تنظیم • 🎧 {len(data['jobs'])} پردازش\n"
                        "برای بازگردانی: پنل ← بک‌آپ ← آپلود بک‌آپ")


def parse_backup(raw):
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    if raw[:15] == b"SQLite format 3":
        with tempfile.TemporaryDirectory(dir=TMP_DIR) as tmp:
            p = Path(tmp) / "b.db"
            p.write_bytes(raw)
            con = sqlite3.connect(p)
            con.row_factory = sqlite3.Row
            data = {}
            for t, _ in TABLES:
                try:
                    data[t] = [dict(r) for r in con.execute(f"SELECT * FROM {t}")]
                except sqlite3.Error:
                    data[t] = []
            con.close()
            return data
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict) or not any(k in data for k, _ in TABLES):
        raise ValueError("ساختار فایل بک‌آپ معتبر نیست")
    return data


def apply_backup(data):
    stats = {}
    with _lock:
        for t, mode in TABLES:
            cols = [r["name"] for r in _db.execute(f"PRAGMA table_info({t})")]
            n = 0
            for row in data.get(t, []) or []:
                if not isinstance(row, dict):
                    continue
                r = {k: v for k, v in row.items() if k in cols}
                if t == "channels":
                    r.pop("id", None)
                if not r:
                    continue
                if t == "users" and "id" in r:
                    cur = _db.execute("SELECT last_seen FROM users WHERE id=?", (r["id"],)).fetchone()
                    if cur and (cur["last_seen"] or 0) > (r.get("last_seen") or 0):
                        continue  # اطلاعات فعلی تازه‌تره
                names = ",".join(r)
                qs = ",".join("?" * len(r))
                _db.execute(f"INSERT OR {mode} INTO {t}({names}) VALUES({qs})", tuple(r.values()))
                n += 1
            stats[t] = n
        _db.commit()
    _sc.clear()
    _seen.clear()
    _member.clear()
    return stats


def autobackup_loop():
    while True:
        time.sleep(300)
        try:
            if get_setting("autobackup", "1") == "1":
                last = int(get_setting("last_backup", "0") or 0)
                if time.time() - last >= 86400:
                    set_setting("last_backup", int(time.time()))
                    for a in ADMINS:
                        try:
                            send_backup(a, auto=True)
                        except Exception:
                            log.exception("autobackup failed")
        except Exception:
            log.exception("autobackup loop")


# ═══════════════════════════ پنل ادمین: نماها ═══════════════════════════
def back_kb(to="adm:home"):
    return mk([btn("🔙 برگشت", to)])


def admin_home():
    maint = get_setting("maintenance") == "1"
    today_j = cnt("SELECT COUNT(*) c FROM jobs WHERE ts>=?", (day_start(),))
    head = (f"👑 <b>پنل مدیریت</b>\n\n👥 کاربران: <b>{cnt('SELECT COUNT(*) c FROM users')}</b> • "
            f"🎶 امروز: <b>{today_j}</b> • ⚙️ در حال پردازش: <b>{len(busy)}</b>\n"
            f"📦 فایل بزرگ: <b>{'فعال ✅' if TL_OK else 'خاموش ❌'}</b>")
    kb = mk([btn("📢 جوین اجباری", "adm:ch", st="primary"), btn("👥 کاربران", "adm:us:all:0", st="primary")],
            [btn("📊 آمار", "adm:stats", st="success"), btn("🖥 وضعیت سرور", "adm:srv", st="success")],
            [btn("📣 ارسال همگانی", "adm:bc", st="primary"), btn("🔎 جستجوی کاربر", "adm:find")],
            [btn("⚙️ تنظیمات", "adm:set"), btn("💾 بک‌آپ", "adm:bk", st="success")],
            [btn("📜 لاگ ربات", "adm:logs")],
            [btn("🟢 ربات روشنه (خاموش کن)" if not maint else "🔴 ربات خاموشه (روشن کن)", "adm:tg:maintenance",
                 st=("danger" if not maint else "success"))],
            [btn("❌ بستن", "adm:close", st="danger")])
    return head, kb


def settings_view():
    g = get_setting
    lim = int(g("daily_limit", "0") or 0)
    on = lambda k, d="1": "🟢 روشن" if g(k, d) == "1" else "🔴 خاموش"
    text = ("⚙️ <b>تنظیمات ربات</b>\n\n"
            f"⏱ سقف روزانه هر کاربر: <b>{lim or 'نامحدود'}</b>\n"
            f"📦 حداکثر حجم ورودی: <b>{g('max_mb', '200')} MB</b>"
            f"{'' if TL_OK else ' (فعلاً فقط تا 20MB چون حالت فایل بزرگ خاموشه)'}\n"
            f"🎚 کیفیت خروجی: <b>{g('bitrate', '192')} kbps</b>\n"
            f"📞 پشتیبانی: <b>{esc(g('support', '') or '—')}</b>\n"
            f"🔔 اعلان کاربر جدید: {on('notify')}\n🔧 حالت تعمیر: {on('maintenance', '0')}")
    kb = mk([btn("⏱ سقف روزانه", "adm:num:daily_limit", st="primary"),
             btn("📦 حداکثر حجم", "adm:num:max_mb", st="primary")],
            [btn(f"🎚 کیفیت: {g('bitrate', '192')}k (تغییر)", "adm:br", st="success")],
            [btn("💬 پیام خوش‌آمد", "adm:txt:welcome"), btn("🏷 کپشن آهنگ", "adm:txt:caption")],
            [btn("📞 آیدی پشتیبانی", "adm:txt:support"), btn("🔔 اعلان کاربر جدید", "adm:tg:notify")],
            [btn("🧹 پاکسازی غیرفعال‌ها", "adm:clean", st="danger")],
            [btn("🔙 برگشت", "adm:home")])
    return text, kb


def backup_view():
    last = int(get_setting("last_backup", "0") or 0)
    on = get_setting("autobackup", "1") == "1"
    text = ("💾 <b>بک‌آپ و بازگردانی</b>\n\n"
            "بک‌آپ شامل <b>همه کاربران، کانال‌ها، تنظیمات و آمار پردازش‌ها</b> است.\n"
            "با آپلود بک‌آپ، اطلاعات فعلی با فایل ادغام و به‌روز می‌شه.\n\n"
            f"🗓 آخرین بک‌آپ خودکار: <b>{fdt(last) if last else '—'}</b>\n"
            f"🤖 بک‌آپ خودکار روزانه: {'🟢 روشن' if on else '🔴 خاموش'}")
    kb = mk([btn("📥 دریافت بک‌آپ", "adm:bkget", st="success")],
            [btn("📤 آپلود بک‌آپ", "adm:bkup", st="primary")],
            [btn("🤖 بک‌آپ خودکار: " + ("روشن" if on else "خاموش"), "adm:tg:autobackup")],
            [btn("🔙 برگشت", "adm:home")])
    return text, kb


def channels_view():
    chs = many("SELECT * FROM channels")
    rows, lines = [], []
    for ch in chs:
        ok = "✅"
        try:
            st = bot.get_chat_member(ch["chat_id"], bot.get_me().id).status
            if st not in ("administrator", "creator"):
                ok = "⚠️"
        except Exception:
            ok = "⚠️"
        lines.append(f"{ok} {esc(ch['title'])}")
        rows.append([btn(f"📢 {ch['title'][:22]}", url=ch["link"]), btn("🗑 حذف", f"adm:chdel:{ch['id']}", st="danger")])
    rows.append([btn("➕ افزودن کانال", "adm:chadd", st="success")])
    rows.append([btn("🔙 برگشت", "adm:home")])
    text = ("📢 <b>مدیریت جوین اجباری</b>\n\n"
            + (f"کانال‌های فعال: <b>{len(chs)}</b>\n" + "\n".join(lines) +
               "\n\n✅ ربات ادمینه • ⚠️ ربات ادمین نیست (عضویت چک نمی‌شه)\nبا دکمه 🗑 هر کانال رو حذف کن."
               if chs else "هیچ کانالی فعال نیست."))
    return text, mk(*rows)


FILTERS = {"all": "👥 همه", "ban": "🚫 بن‌شده", "vip": "⭐ VIP", "act": "🔥 امروز"}


def users_view(flt, page):
    where, args, order = "", (), "joined DESC"
    if flt == "ban":
        where = "WHERE banned=1"
    elif flt == "vip":
        where = "WHERE vip=1"
    elif flt == "act":
        where, args, order = "WHERE last_seen>=?", (day_start(),), "last_seen DESC"
    total = cnt(f"SELECT COUNT(*) c FROM users {where}", args)
    pages = max(1, -(-total // PAGE_SIZE))
    page = max(0, min(page, pages - 1))
    rows = many(f"SELECT u.*, (SELECT COUNT(*) FROM jobs WHERE user_id=u.id) uses FROM users u {where} "
                f"ORDER BY {order} LIMIT ? OFFSET ?", args + (PAGE_SIZE, page * PAGE_SIZE))
    lines = [f"👥 <b>مدیریت کاربران</b> — {FILTERS[flt]} — صفحه {page + 1}/{pages} (کل: {total})\n"]
    kb_rows = [[btn(v, f"adm:us:{k}:0", st=("primary" if k == flt else None)) for k, v in FILTERS.items()]]
    for r in rows:
        un = f"@{r['username']}" if r["username"] else "—"
        flag = "🚫" if r["banned"] else ("⭐" if r["vip"] else "👤")
        lines.append(f"{flag} <b>{esc(r['first_name'])}</b>\n"
                     f"   🆔 <code>{r['id']}</code> | {esc(un)} | 🎧 {r['uses']} | 📅 {fdate(r['joined'])}")
        ban = (btn("آن‌بن", f"adm:unban:{r['id']}:{flt}:{page}", st="success") if r["banned"]
               else btn("بن", f"adm:ban:{r['id']}:{flt}:{page}", st="danger"))
        kb_rows.append([btn(f"{flag} {(r['first_name'] or '?')[:14]}", f"adm:u:{r['id']}:{flt}:{page}"), ban])
    nav = []
    if page > 0:
        nav.append(btn("⬅️ قبلی", f"adm:us:{flt}:{page - 1}"))
    if page < pages - 1:
        nav.append(btn("بعدی ➡️", f"adm:us:{flt}:{page + 1}"))
    kb_rows += [nav, [btn("🔙 برگشت", "adm:home")]]
    if not rows:
        lines.append("موردی پیدا نشد.")
    return "\n".join(lines), mk(*kb_rows)


def user_card(uid, flt="all", page=0):
    r = one("SELECT u.*, (SELECT COUNT(*) FROM jobs WHERE user_id=u.id) uses, "
            "(SELECT COALESCE(SUM(mb),0) FROM jobs WHERE user_id=u.id) mb FROM users u WHERE id=?", (uid,))
    if not r:
        return None, None
    status = "🚫 بن" if r["banned"] else ("⭐ VIP" if r["vip"] else "✅ عادی")
    text = (f"👤 <b>{esc(r['first_name'])}</b>\n🆔 <code>{r['id']}</code>\n@{esc(r['username'] or '-')}\n"
            f"📅 عضویت: {fdt(r['joined'])}\n🕒 آخرین فعالیت: {fdt(r['last_seen'])}\n"
            f"🎧 آهنگ‌ها: <b>{r['uses']}</b> • 📦 {r['mb']:.0f} MB\nوضعیت: <b>{status}</b>")
    ban = (btn("🟢 آن‌بن", f"adm:unban:{uid}:{flt}:{page}", st="success") if r["banned"]
           else btn("🔴 بن", f"adm:ban:{uid}:{flt}:{page}", st="danger"))
    kb = mk([ban, btn("⭐ VIP: " + ("برداشتن" if r["vip"] else "دادن"), f"adm:vip:{uid}:{flt}:{page}", st="primary")],
            [btn("✉️ ارسال پیام", f"adm:dm:{uid}", st="success")],
            [btn("🔙 برگشت", f"adm:us:{flt}:{page}")])
    return text, kb


def spark(vals):
    blocks = "▁▂▃▄▅▆▇█"
    mx = max(vals) or 1
    return "".join(blocks[min(7, int(v / mx * 7))] if v else "▁" for v in vals)


def stats_text():
    d, w = day_start(), day_start() - 6 * 86400
    days = [day_start() - i * 86400 for i in range(6, -1, -1)]
    new_trend = [cnt("SELECT COUNT(*) c FROM users WHERE joined>=? AND joined<?", (s, s + 86400)) for s in days]
    job_trend = [cnt("SELECT COUNT(*) c FROM jobs WHERE ts>=? AND ts<?", (s, s + 86400)) for s in days]
    top = many("SELECT u.first_name n, COUNT(*) c FROM jobs j JOIN users u ON u.id=j.user_id "
               "GROUP BY j.user_id ORDER BY c DESC LIMIT 5")
    top_txt = "\n".join(f"  {i}. {esc(r['n'])} — {r['c']}" for i, r in enumerate(top, 1)) or "  —"
    mbs = one("SELECT COALESCE(SUM(mb),0) s FROM jobs")["s"]
    return (f"📊 <b>آمار کلی</b>\n\n"
            f"👥 کل کاربران: <b>{cnt('SELECT COUNT(*) c FROM users')}</b>\n"
            f"🆕 عضو جدید امروز: <b>{cnt('SELECT COUNT(*) c FROM users WHERE joined>=?', (d,))}</b> • "
            f"۷ روز: <b>{cnt('SELECT COUNT(*) c FROM users WHERE joined>=?', (w,))}</b>\n"
            f"🔥 فعال امروز: <b>{cnt('SELECT COUNT(*) c FROM users WHERE last_seen>=?', (d,))}</b> • "
            f"۷ روز: <b>{cnt('SELECT COUNT(*) c FROM users WHERE last_seen>=?', (w,))}</b>\n"
            f"⭐ VIP: <b>{cnt('SELECT COUNT(*) c FROM users WHERE vip=1')}</b> • "
            f"🚫 بن‌شده: <b>{cnt('SELECT COUNT(*) c FROM users WHERE banned=1')}</b>\n\n"
            f"🎧 کل پردازش‌ها: <b>{cnt('SELECT COUNT(*) c FROM jobs')}</b> • امروز: "
            f"<b>{cnt('SELECT COUNT(*) c FROM jobs WHERE ts>=?', (d,))}</b>\n"
            f"📦 حجم کل پردازش‌شده: <b>{mbs:.0f} MB</b>\n"
            f"📢 کانال‌های جوین اجباری: <b>{cnt('SELECT COUNT(*) c FROM channels')}</b>\n\n"
            f"📈 عضو جدید ۷ روز اخیر: <code>{spark(new_trend)}</code>\n"
            f"📈 پردازش ۷ روز اخیر: <code>{spark(job_trend)}</code>\n\n"
            f"🏆 <b>برترین کاربران:</b>\n{top_txt}")


def server_text():
    lines = ["🖥 <b>وضعیت سرور</b>\n"]
    lines.append(f"⏱ آپ‌تایم ربات: <b>{fdur(time.time() - START_TS)}</b>")
    try:
        l1, l5, l15 = os.getloadavg()
        lines.append(f"🧮 لود CPU: <b>{l1:.2f}</b> / {l5:.2f} / {l15:.2f}")
    except Exception:
        pass
    try:
        mem = {}
        for ln in open("/proc/meminfo"):
            k, v = ln.split(":", 1)
            mem[k] = int(v.split()[0]) * 1024
        used = mem["MemTotal"] - mem.get("MemAvailable", mem["MemFree"])
        lines.append(f"🧠 رم: <b>{fsize(used)}</b> از {fsize(mem['MemTotal'])}")
    except Exception:
        pass
    try:
        du = shutil.disk_usage(BASE)
        lines.append(f"💽 دیسک: <b>{fsize(du.used)}</b> از {fsize(du.total)} (آزاد: {fsize(du.free)})")
    except Exception:
        pass
    lines.append(f"🗄 حجم دیتابیس: <b>{fsize(DB_PATH.stat().st_size)}</b>")
    ver = "?"
    try:
        ver = subprocess.run([FFMPEG, "-version"], capture_output=True, timeout=10).stdout.decode().split("\n")[0][:40]
    except Exception:
        pass
    lines.append(f"🎛 {esc(ver)}")
    lines.append(f"🐍 Python {platform.python_version()} • SQLite {sqlite3.sqlite_version}")
    lines.append(f"⚙️ پردازش فعال/صف: <b>{len(busy)}</b> (هم‌زمان مجاز: {MAX_PARALLEL})")
    lines.append(f"⏳ آهنگ‌های منتظر انتخاب: <b>{len(pending)}</b> • 🧵 ترد: {threading.active_count()}")
    lines.append(f"📦 فایل بزرگ: <b>{'فعال ✅' if TL_OK else ('خاموش (API_ID/API_HASH نیست یا telethon نصب نیست)' if not TL_ENABLED else 'خطا ❌ (لاگ رو ببین)')}</b>")
    lines.append(f"🎨 دکمه‌های رنگی: <b>{'فعال ✅' if STYLE_OK else 'غیرفعال (تلگرام رد کرد)'}</b>")
    return "\n".join(lines)


# ═══════════════════════════ پنل ادمین: مراحل ═══════════════════════════
NUM_SETTINGS = {"daily_limit": ("⏱ سقف روزانه هر کاربر (۰ = نامحدود)", 0, 1000),
                "max_mb": ("📦 حداکثر حجم ورودی بر حسب مگابایت", 1, 2000)}
TXT_SETTINGS = {"welcome": "💬 متن جدید پیام خوش‌آمد (از {name} برای اسم کاربر استفاده کن)",
                "caption": "🏷 کپشن آهنگ خروجی (متغیرها: {label} {style} {bot})",
                "support": "📞 آیدی تلگرام پشتیبانی (مثل @support). برای حذف، یه نقطه (.) بفرست"}


def add_channel(m):
    try:
        fchat = getattr(m, "forward_from_chat", None)
        if fchat is None:
            fchat = getattr(getattr(m, "forward_origin", None), "chat", None)
        if fchat is not None:
            ref = fchat.id
        else:
            ref = (m.text or "").strip()
            if "t.me/" in ref:
                ref = "@" + ref.split("t.me/")[1].split("/")[0].split("?")[0]
            if ref.lstrip("-").isdigit():
                ref = int(ref)
            elif not ref.startswith("@"):
                ref = "@" + ref
        chat = bot.get_chat(ref)
        me = bot.get_chat_member(chat.id, bot.get_me().id)
        if me.status not in ("administrator", "creator"):
            return bot.send_message(m.chat.id, "⚠️ ربات تو اون کانال ادمین نیست. اول ادمینش کن و دوباره بفرست.")
        link = f"https://t.me/{chat.username}" if chat.username else bot.export_chat_invite_link(chat.id)
    except Exception as e:
        return bot.send_message(m.chat.id, "❌ کانال پیدا نشد یا ربات دسترسی کافی نداره.\n"
                                           f"<code>{esc(str(e))[:150]}</code>\nدوباره بفرست یا /cancel")
    ex("INSERT OR REPLACE INTO channels(chat_id,title,link) VALUES(?,?,?)",
       (chat.id, chat.title or str(chat.id), link))
    astate.pop(m.from_user.id, None)
    t, kb = channels_view()
    bot.send_message(m.chat.id, "✅ کانال اضافه شد.\n\n" + t, reply_markup=kb)


def admin_state(m):
    uid = m.from_user.id
    st = astate.get(uid)
    if not st:
        return
    s = st["s"]
    done_kb = mk([btn("🔙 برگشت", "adm:home")])
    if s == "add_channel":
        add_channel(m)
    elif s == "find":
        q = (m.text or "").strip().lstrip("@")
        r = one("SELECT id FROM users WHERE id=? OR username=?", (int(q) if q.isdigit() else -1, q))
        if not r:
            return bot.send_message(m.chat.id, "❌ کاربری با این مشخصات پیدا نشد. دوباره بفرست یا /cancel")
        astate.pop(uid, None)
        t, kb = user_card(r["id"])
        bot.send_message(m.chat.id, t, reply_markup=kb)
    elif s == "dm":
        astate.pop(uid, None)
        try:
            bot.copy_message(st["uid"], m.chat.id, m.message_id)
            bot.send_message(m.chat.id, "✅ پیام ارسال شد.", reply_markup=done_kb)
        except Exception as e:
            bot.send_message(m.chat.id, f"❌ ارسال نشد: <code>{esc(str(e))[:150]}</code>", reply_markup=done_kb)
    elif s == "broadcast":
        st["mid"], st["cid"] = m.message_id, m.chat.id
        n_all = cnt("SELECT COUNT(*) c FROM users WHERE banned=0")
        n_act = cnt("SELECT COUNT(*) c FROM users WHERE banned=0 AND last_seen>=?", (day_start() - 6 * 86400,))
        bot.reply_to(m, "این پیام برای چه کسانی ارسال بشه؟",
                     reply_markup=mk([btn(f"👥 همه ({n_all})", "adm:bcgo:all", st="primary"),
                                      btn(f"🔥 فعال ۷ روز ({n_act})", "adm:bcgo:act", st="success")],
                                     [btn("❌ لغو", "adm:home", st="danger")]))
    elif s == "set_text":
        if not m.text:
            return bot.send_message(m.chat.id, "⚠️ فقط متن بفرست.")
        key = st["key"]
        val = m.html_text if key != "support" else ("" if m.text.strip() == "." else m.text.strip())
        set_setting(key, val)
        astate.pop(uid, None)
        bot.send_message(m.chat.id, "✅ ذخیره شد.", reply_markup=mk([btn("🔙 تنظیمات", "adm:set")]))
    elif s == "set_num":
        key = st["key"]
        _, lo, hi = NUM_SETTINGS[key]
        t = norm_digits(m.text)
        if not t.isdigit() or not lo <= int(t) <= hi:
            return bot.send_message(m.chat.id, f"⚠️ یه عدد بین {lo} تا {hi} بفرست (یا /cancel).")
        val = int(t)
        warn = ""
        if key == "max_mb" and val > 20 and not TL_OK:
            warn = "\n⚠️ حالت فایل بزرگ خاموشه؛ تا فعال نشه عملاً فقط 20MB قبول می‌شه."
        set_setting(key, val)
        astate.pop(uid, None)
        bot.send_message(m.chat.id, f"✅ ذخیره شد: {val}{warn}", reply_markup=mk([btn("🔙 تنظیمات", "adm:set")]))
    elif s == "restore_wait":
        if not m.document:
            return bot.send_message(m.chat.id, "⚠️ فایل بک‌آپ رو به‌صورت <b>فایل (Document)</b> بفرست یا /cancel")
        if (m.document.file_size or 0) > BOT_API_DL:
            return bot.send_message(m.chat.id, "⚠️ فایل بک‌آپ بزرگ‌تر از ۲۰ مگابایته و از طریق ربات قابل دریافت نیست.")
        try:
            info = bot.get_file(m.document.file_id)
            data = parse_backup(bot.download_file(info.file_path))
        except Exception as e:
            log.exception("restore parse failed")
            return bot.send_message(m.chat.id, "❌ فایل بک‌آپ خونده نشد یا معتبر نیست.\n"
                                               f"<code>{esc(str(e))[:150]}</code>\nفایل دیگه‌ای بفرست یا /cancel")
        st["s"], st["data"] = "restore_confirm", data
        bot.send_message(
            m.chat.id,
            "📦 <b>بک‌آپ خونده شد</b>\n\n"
            f"👥 کاربران: <b>{len(data.get('users', []))}</b>\n📢 کانال‌ها: <b>{len(data.get('channels', []))}</b>\n"
            f"⚙️ تنظیمات: <b>{len(data.get('settings', []))}</b>\n🎧 پردازش‌ها: <b>{len(data.get('jobs', []))}</b>\n\n"
            "اطلاعات فعلی با این فایل ادغام و به‌روز بشه؟",
            reply_markup=mk([btn("✅ اعمال بک‌آپ", "adm:bkok", st="success"), btn("❌ لغو", "adm:home", st="danger")]))
    elif s == "restore_confirm":
        bot.send_message(m.chat.id, "برای ادامه یکی از دکمه‌ها رو بزن یا /cancel")


def do_broadcast(admin_id, cid, mid, target):
    where = "banned=0" if target == "all" else f"banned=0 AND last_seen>={day_start() - 6 * 86400}"
    ids = [r["id"] for r in many(f"SELECT id FROM users WHERE {where}")]
    ok = fail = 0
    for uid in ids:
        for _ in range(3):
            try:
                bot.copy_message(uid, cid, mid)
                ok += 1
                break
            except ApiTelegramException as e:
                if e.error_code == 429:
                    try:
                        wait = int(e.result_json["parameters"]["retry_after"])
                    except Exception:
                        wait = 5
                    time.sleep(wait + 1)
                    continue
                fail += 1
                break
            except Exception:
                fail += 1
                break
        else:
            fail += 1
        time.sleep(0.05)
    bot.send_message(admin_id, f"📣 <b>ارسال همگانی تموم شد</b>\n✅ موفق: {ok}\n❌ ناموفق: {fail}")


def adm_action(c):
    p = c.data.split(":")
    act = p[1]
    cid, uid = c.message.chat.id, c.from_user.id

    def go(text_kb):
        safe_edit(c, text_kb[0], text_kb[1])

    if act == "home":
        astate.pop(uid, None)
        go(admin_home())
    elif act == "close":
        astate.pop(uid, None)
        try:
            bot.delete_message(cid, c.message.message_id)
        except Exception:
            pass
    elif act == "tg":
        key = p[2]
        if key not in ("maintenance", "notify", "autobackup"):
            return safe_answer(c)
        dflt = "0" if key == "maintenance" else "1"
        cur = get_setting(key, dflt) == "1"
        set_setting(key, "0" if cur else "1")
        go(settings_view() if key in ("notify",) else (backup_view() if key == "autobackup" else admin_home()))
        return safe_answer(c, "✅ تغییر کرد")
    elif act == "br":
        cur = int(get_setting("bitrate", "192") or 192)
        nxt = BITRATES[(BITRATES.index(cur) + 1) % len(BITRATES)] if cur in BITRATES else 192
        set_setting("bitrate", nxt)
        go(settings_view())
        return safe_answer(c, f"🎚 کیفیت خروجی: {nxt}k")
    elif act == "set":
        astate.pop(uid, None)
        go(settings_view())
    elif act == "num":
        key = p[2]
        if key not in NUM_SETTINGS:
            return safe_answer(c)
        astate[uid] = {"s": "set_num", "key": key}
        safe_edit(c, f"{NUM_SETTINGS[key][0]}\nفعلی: <b>{get_setting(key, '0')}</b>\n"
                     f"یه عدد بین {NUM_SETTINGS[key][1]} تا {NUM_SETTINGS[key][2]} بفرست:\n(انصراف: /cancel)",
                  back_kb("adm:set"))
    elif act == "txt":
        key = p[2]
        if key not in TXT_SETTINGS:
            return safe_answer(c)
        astate[uid] = {"s": "set_text", "key": key}
        cur = get_setting(key, DEFAULT_WELCOME if key == "welcome" else (DEFAULT_CAPTION if key == "caption" else ""))
        safe_edit(c, f"{TXT_SETTINGS[key]}\n(انصراف: /cancel)\n\n<b>فعلی:</b>\n<pre>{esc(cur) or '—'}</pre>",
                  back_kb("adm:set"))
    elif act == "clean":
        n = cnt("SELECT COUNT(*) c FROM users WHERE banned=0 AND vip=0 AND last_seen<?", (int(time.time()) - 90 * 86400,))
        safe_edit(c, f"🧹 <b>پاکسازی</b>\n\n{n} کاربر که ۹۰ روز یا بیشتر فعالیت نداشتن (غیر بن و غیر VIP) حذف بشن؟",
                  mk([btn("🗑 بله، حذف شوند", "adm:cleanok", st="danger"), btn("🟢 انصراف", "adm:set", st="success")]))
    elif act == "cleanok":
        with _lock:
            _db.execute("DELETE FROM users WHERE banned=0 AND vip=0 AND last_seen<?", (int(time.time()) - 90 * 86400,))
            n = _db.execute("SELECT changes()").fetchone()[0]
            _db.commit()
        go(settings_view())
        return safe_answer(c, f"🧹 {n} کاربر حذف شد")
    elif act == "stats":
        safe_edit(c, stats_text(), back_kb())
    elif act == "srv":
        safe_edit(c, server_text(), mk([btn("🔄 به‌روزرسانی", "adm:srv", st="success")], [btn("🔙 برگشت", "adm:home")]))
    elif act == "logs":
        safe_answer(c, "📜 در حال ارسال...")
        try:
            with tempfile.TemporaryDirectory(dir=TMP_DIR) as tmp:
                lp = BASE / "bot.log"
                data = lp.read_bytes()[-200_000:] if lp.exists() else b"(empty)"
                f = Path(tmp) / "bot_log_tail.txt"
                f.write_bytes(data)
                with open(f, "rb") as fh:
                    bot.send_document(cid, fh, caption="📜 آخرین لاگ‌های ربات")
        except Exception as e:
            bot.send_message(cid, f"❌ ارسال لاگ ناموفق بود: <code>{esc(str(e))[:200]}</code>")
        return
    # ── بک‌آپ
    elif act == "bk":
        astate.pop(uid, None)
        go(backup_view())
    elif act == "bkget":
        safe_answer(c, "💾 در حال آماده‌سازی...")
        try:
            send_backup(cid)
        except Exception as e:
            log.exception("backup failed")
            bot.send_message(cid, f"❌ بک‌آپ ناموفق بود: <code>{esc(str(e))[:200]}</code>")
        return
    elif act == "bkup":
        astate[uid] = {"s": "restore_wait"}
        safe_edit(c, "📤 <b>آپلود بک‌آپ</b>\n\nفایل بک‌آپ (<code>.json</code> یا <code>.json.gz</code> یا دیتابیس <code>.db</code>) "
                     "رو به‌صورت فایل برام بفرست.\n(انصراف: /cancel)", back_kb("adm:bk"))
    elif act == "bkok":
        st = astate.get(uid)
        if not st or st.get("s") != "restore_confirm":
            return safe_answer(c, "⌛ فایلی در انتظار نیست، دوباره آپلود کن.", True)
        astate.pop(uid, None)
        try:
            stats = apply_backup(st["data"])
        except Exception as e:
            log.exception("restore failed")
            return safe_edit(c, f"❌ بازگردانی ناموفق بود:\n<code>{esc(str(e))[:200]}</code>", back_kb("adm:bk"))
        safe_edit(c, "✅ <b>بک‌آپ با موفقیت اعمال شد</b>\n\n"
                     f"👥 کاربران: {stats.get('users', 0)}\n📢 کانال‌ها: {stats.get('channels', 0)}\n"
                     f"⚙️ تنظیمات: {stats.get('settings', 0)}\n🎧 پردازش‌ها: {stats.get('jobs', 0)}", back_kb("adm:bk"))
    # ── جوین اجباری
    elif act == "ch":
        astate.pop(uid, None)
        go(channels_view())
    elif act == "chdel":
        row = one("SELECT * FROM channels WHERE id=?", (int(p[2]),))
        if not row:
            return safe_answer(c, "قبلاً حذف شده", True)
        safe_edit(c, f"⚠️ کانال <b>{esc(row['title'])}</b> از جوین اجباری حذف بشه؟",
                  mk([btn("🗑 بله، حذف شود", f"adm:chok:{row['id']}", st="danger"),
                      btn("🟢 نه، انصراف", "adm:ch", st="success")]))
    elif act == "chok":
        ex("DELETE FROM channels WHERE id=?", (int(p[2]),))
        _member.clear()
        go(channels_view())
        return safe_answer(c, "🗑 حذف شد")
    elif act == "chadd":
        astate[uid] = {"s": "add_channel"}
        safe_edit(c, "➕ ربات رو اول <b>ادمین</b> کانال/گروه کن، بعد یکی از اینا رو بفرست:\n"
                     "• یوزرنیم مثل <code>@mychannel</code> یا لینک t.me\n"
                     "• آیدی عددی مثل <code>-100123...</code>\n• یه پیام فوروارد شده از کانال\n\n"
                     "برای انصراف: /cancel", back_kb("adm:ch"))
    # ── کاربران
    elif act == "us":
        astate.pop(uid, None)
        go(users_view(p[2], int(p[3])))
    elif act == "u":
        t, kb = user_card(int(p[2]), p[3], int(p[4]))
        if not t:
            return safe_answer(c, "کاربر پیدا نشد", True)
        safe_edit(c, t, kb)
    elif act in ("ban", "unban"):
        target, flt, page = int(p[2]), p[3], int(p[4])
        if target in ADMINS:
            return safe_answer(c, "نمی‌تونی ادمین رو بن کنی 😅", True)
        ex("UPDATE users SET banned=? WHERE id=?", (1 if act == "ban" else 0, target))
        pending.pop(target, None)
        try:
            bot.send_message(target, "🚫 دسترسی شما به ربات مسدود شد." if act == "ban"
                             else "✅ مسدودیت شما برداشته شد. خوش برگشتی!")
        except Exception:
            pass
        t, kb = user_card(target, flt, page)
        safe_edit(c, t, kb)
        return safe_answer(c, "🚫 بن شد" if act == "ban" else "✅ آن‌بن شد")
    elif act == "vip":
        target, flt, page = int(p[2]), p[3], int(p[4])
        r = one("SELECT vip FROM users WHERE id=?", (target,))
        ex("UPDATE users SET vip=? WHERE id=?", (0 if r and r["vip"] else 1, target))
        t, kb = user_card(target, flt, page)
        safe_edit(c, t, kb)
        return safe_answer(c, "⭐ تغییر کرد")
    elif act == "dm":
        astate[uid] = {"s": "dm", "uid": int(p[2])}
        safe_edit(c, "✉️ پیامی که می‌خوای برای این کاربر بره رو بفرست (هر نوع پیامی):\n(انصراف: /cancel)", back_kb())
    elif act == "find":
        astate[uid] = {"s": "find"}
        safe_edit(c, "🔎 آیدی عددی یا یوزرنیم کاربر رو بفرست:\n(انصراف: /cancel)", back_kb())
    # ── ارسال همگانی
    elif act == "bc":
        astate[uid] = {"s": "broadcast"}
        safe_edit(c, "📣 پیامی که می‌خوای برای کاربران بره رو بفرست (متن، عکس، فایل... هرچی):\n(انصراف: /cancel)",
                  back_kb())
    elif act == "bcgo":
        st = astate.pop(uid, None)
        if not st or not st.get("mid"):
            return safe_answer(c, "پیامی ثبت نشده", True)
        safe_edit(c, "🚀 ارسال شروع شد، بعد از پایان گزارش می‌دم...")
        threading.Thread(target=do_broadcast, args=(uid, st["cid"], st["mid"], p[2]), daemon=True).start()
    safe_answer(c)


# ═══════════════════════════ اجرا ═══════════════════════════
def clean_tmp():
    for x in TMP_DIR.glob("*"):
        shutil.rmtree(x, ignore_errors=True)


def announce_start():
    """پیام استارت؛ هم‌زمان تست می‌کنه تلگرام دکمه رنگی رو قبول می‌کنه یا نه."""
    global STYLE_OK
    text = ("✅ <b>ربات روشن شد</b>\n"
            f"📦 فایل بزرگ: {'فعال ✅' if TL_OK else 'خاموش ❌'}")
    for a in ADMINS:
        try:
            bot.send_message(a, text, reply_markup=mk([btn("👑 باز کردن پنل", "adm:home", st="success")]))
        except ApiTelegramException as e:
            if STYLE_OK and "style" in str(e).lower():
                STYLE_OK = False
                log.warning("تلگرام دکمه رنگی رو رد کرد؛ حالت ایموجی فعال شد: %s", e)
                try:
                    bot.send_message(a, text, reply_markup=mk([btn("👑 باز کردن پنل", "adm:home", st="success")]))
                except Exception:
                    pass
        except Exception:
            pass


def main():
    if not FFMPEG:
        sys.exit("❌ ffmpeg پیدا نشد. روی سرور نصبش کن یا  pip install imageio-ffmpeg  بزن.")
    try:
        me = bot.get_me()
    except Exception as e:
        sys.exit(f"❌ اتصال به تلگرام ناموفق بود (توکن یا اینترنت/فیلترشکن رو چک کن): {e}")
    clean_tmp()
    if TL_ENABLED:
        start_telethon()
    else:
        why = "telethon نصب نیست" if not TELETHON else "API_ID / API_HASH تنظیم نشده"
        log.warning("حالت فایل بزرگ خاموشه (%s). سقف فایل: 20MB", why)
    try:
        base = [types.BotCommand("start", "شروع"), types.BotCommand("help", "راهنما"),
                types.BotCommand("me", "پروفایل من"), types.BotCommand("top", "برترین‌ها")]
        bot.set_my_commands(base)
        for a in ADMINS:
            try:
                bot.set_my_commands(base + [types.BotCommand("admin", "پنل مدیریت")],
                                    scope=types.BotCommandScopeChat(a))
            except Exception:
                pass
    except Exception as e:
        log.warning("set_my_commands failed: %s", e)
    try:
        bot.remove_webhook()
    except Exception:
        pass
    threading.Thread(target=autobackup_loop, daemon=True, name="autobackup").start()
    log.info("✅ ربات @%s راه افتاد | ffmpeg: %s | ادمین‌ها: %s | فایل بزرگ: %s",
             me.username, FFMPEG, ADMINS, TL_OK)
    announce_start()
    bot.infinity_polling(timeout=20, long_polling_timeout=20, skip_pending=True,
                         allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("ربات متوقف شد.")
