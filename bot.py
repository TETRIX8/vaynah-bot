#!/usr/bin/env python3
# VAYNAH VPN Telegram bot (@MyVainakhBot) — MVP
import sys, asyncio, json, os, sqlite3, subprocess, uuid, time, logging, base64, hashlib, io, qrcode, urllib.parse
import aiohttp
import secrets as _amb_secrets
from aiohttp import web
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.types import (Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
                           LabeledPrice, PreCheckoutQuery, BufferedInputFile, FSInputFile,
                           ReplyKeyboardMarkup, KeyboardButton, BotCommand, WebAppInfo)
from aiogram.filters import CommandStart, Command, CommandObject
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("zpnbot")

# ---------- config ----------
TOKEN = os.environ.get("BOT_TOKEN", "")
SEED_ADMINS = {int(x) for x in os.environ.get("INGVERTU_ADMIN_ID", "0").replace(";", ",").split(",") if x.strip().isdigit() and int(x) > 0}
ADMIN_ID = next(iter(sorted(SEED_ADMINS)), 0)
DB = os.environ.get("INGVERTU_DB", "/opt/zpnbot/ingvertuvpn.sqlite3")
SSH_KEY = ""

# reality params (shared across nodes)
REALITY = {"port": 443, "sni": "example.invalid", "fingerprint": "chrome", "public_key": "", "short_id": ""}

# Актуальная топология 01.11.2026: РФ-вход + Cloudflare/NL + DE + реальный FI.
# Поля NODES и исторические заметки ниже; актуальные значения имеет только список NODES.
#   cfg = путь xray-конфига; svc = systemd-сервис; tags = ВСЕ vless-inbound теги ноды (провижиним клиента в каждый).
# 🇩🇪 DE  — reality :443, локально (это же хост бота).
# 🇳🇱 NL  — reality :8443 на панели 0.0.0.0 (физически NL, чистый IP). Совмещена с бекендом подписки.
# 🇫🇮 FI  — 3 inbound'а (reality :443 / ws-in .14.164:443 / ws80 :8080); клиент ходит на ws-in ЧЕРЕЗ моск. релей firu.
#          провижиним во ВСЕ три (ws-in — тот, что реально использует релей).
# Архитектура подключения: клиент использует стабильную техническую площадку.
# Яндекс сам выходит в загран (NL/DE/FI) служебным uuid, РФ-сайты — напрямую с Яндекса (серверный роутинг).
# Провижининг клиентов = только на Яндекс-вход (3 инбаунда). Выходы держат INFRA_UUID, бот их не трогает.
YCFG = ""
NODES = []
ACCESS_ISSUANCE_ENABLED = os.environ.get("INGVERTU_ACCESS_ISSUANCE_ENABLED", "0").lower() in ("1", "true", "yes", "on")
PAYMENTS_ENABLED = False
WEBAPP_BIND = os.environ.get("INGVERTU_WEBAPP_BIND", "127.0.0.1")

PLANS = {
    "trial":   {"title": "🎁 Пробный · 1 день",       "days": 1,  "stars": 0,    "rub": 0,    "devices": 3, "tier": "std"},
    # Публичная ссылка free2: отдельный 48-часовой trial после подписки на канал.
    "channel_trial": {"title": "🎁 Пробный по ссылке · 2 дня", "days": 2, "stars": 0, "rub": 0, "devices": 3, "tier": "std"},
    # 04.11.2026: воронка — первая оплата «Старт · 3 дня за 10 ₽» (разовая, Lava СБП/карта + Stars)
    "intro":   {"title": "🔥 Старт · 7 дней за 50 ₽",  "days": 7,  "stars": 40,   "rub": 50,   "devices": 3, "tier": "std"},
    # Стандарт — до 3 устройств
    "1m":      {"title": "Стандарт · 1 месяц",       "days": 30, "stars": 140,  "rub": 199,  "devices": 3, "tier": "std"},
    "3m":      {"title": "Стандарт · 3 месяца",      "days": 90, "stars": 350,  "rub": 499,  "devices": 3, "tier": "std"},
    "6m":      {"title": "Стандарт · 6 месяцев",     "days": 180,"stars": 630,  "rub": 899,  "devices": 3, "tier": "std"},
    "12m":     {"title": "Стандарт · 12 месяцев",    "days": 365,"stars": 1120, "rub": 1590, "devices": 3, "tier": "std"},
    # Семейный — до 5 устройств
    "fam_1m":  {"title": "Семейный · 1 месяц",       "days": 30, "stars": 210,  "rub": 299,  "devices": 5, "tier": "fam"},
    "fam_3m":  {"title": "Семейный · 3 месяца",      "days": 90, "stars": 520,  "rub": 749,  "devices": 5, "tier": "fam"},
    "fam_6m":  {"title": "Семейный · 6 месяцев",     "days": 180,"stars": 940,  "rub": 1350, "devices": 5, "tier": "fam"},
    "fam_12m": {"title": "Семейный · 12 месяцев",    "days": 365,"stars": 1670, "rub": 2390, "devices": 5, "tier": "fam"},
}

REF_BONUS_DAYS = 7       # (режим ref_mode=pay) дней рефереру за первую оплату приглашённого
CFG = {}                 # кэш таблицы settings (обновляет apply_settings)
MONITOR_INTERVAL = 300   # проверка нод раз в 5 мин
BOT_USERNAME = os.environ.get("BOT_USERNAME", "MyVainakhBot")
LOGO_PATH = "/opt/zpnbot/assets/vaynah/vaynah-avatar-neon.png"
REF_BANNER_PATH = "/opt/zpnbot/assets/vaynah/vaynah-promo-funnel-neon.png"

# Heleket (СБП→USDT).
HELEKET_MERCHANT = ""
HELEKET_API_KEY = ""
HELEKET_API = "https://api.heleket.com/v1"
# Cloudflare перед api.heleket.com режет дефолтный UA как бота (error 1010) — нужен браузерный
HELEKET_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
def _hel_hdr(sign):
    return {"merchant": HELEKET_MERCHANT, "sign": sign, "Content-Type": "application/json",
            "Accept": "application/json", "User-Agent": HELEKET_UA}

bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
dp = Dispatcher()

def _heleket_sign(body: dict):
    raw = json.dumps(body, separators=(",", ":"))
    b64 = base64.b64encode(raw.encode()).decode()
    return raw, hashlib.md5((b64 + HELEKET_API_KEY).encode()).hexdigest()

async def heleket_create(amount_rub, order_id):
    if not (0 < float(amount_rub) <= 10000): raise ValueError("сумма превышает лимит 10 000 ₽ за одну оплату")
    body = {"amount": str(amount_rub), "currency": "RUB", "order_id": order_id,
            "lifetime": 1800}
    raw, sign = _heleket_sign(body)
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{HELEKET_API}/payment", data=raw, headers=_hel_hdr(sign), timeout=20) as r:
            return await r.json()

async def heleket_status(order_id):
    body = {"order_id": order_id}
    raw, sign = _heleket_sign(body)
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{HELEKET_API}/payment/info", data=raw, headers=_hel_hdr(sign), timeout=20) as r:
            return await r.json()

# ---------- Lava.top (карта/СБП) ----------
LAVA_KEY = ""
LAVA_API = "https://gate.lava.top"
LAVA_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
LAVA_OFFERS = {}  # pid -> offerId (Стандарт/Семейный, один оффер на тариф)
# наш срок -> периодичность Lava (цена берётся из оффера по периодичности)
LAVA_PERIODICITY = {"1m": "MONTHLY", "3m": "PERIOD_90_DAYS", "6m": "PERIOD_180_DAYS", "12m": "PERIOD_YEAR",
                    "fam_1m": "MONTHLY", "fam_3m": "PERIOD_90_DAYS", "fam_6m": "PERIOD_180_DAYS", "fam_12m": "PERIOD_YEAR"}
_lava_recent = {}  # (tg_id, amount) -> ts: дедуп поллинг+вебхук (не выдать дважды одну оплату)
def _lava_seen(tg_id, amount):
    now = time.time()
    for kk in [kk for kk, t in _lava_recent.items() if now - t > 600]:
        _lava_recent.pop(kk, None)
    key = (tg_id, int(amount or 0))
    if key in _lava_recent:
        return True
    _lava_recent[key] = now
    return False

def _lava_hdr():
    return {"X-Api-Key": LAVA_KEY, "User-Agent": LAVA_UA,
            "Content-Type": "application/json", "Accept": "application/json"}

async def lava_products():
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{LAVA_API}/api/v2/products", headers=_lava_hdr(), timeout=20) as r:
            return await r.json()

async def lava_load_offers():
    """Сопоставить offerId по тарифу (Стандарт/Семейный по имени оффера). Возвращает кол-во сматченных."""
    global LAVA_OFFERS
    try:
        data = await lava_products()
    except Exception as e:
        log.error(f"lava products: {e}"); return 0
    std_id = fam_id = None
    for item in data.get("items", []):
        for off in item.get("offers", []):
            nm = (off.get("name") or "").lower()
            oid = off.get("id")
            if "семейн" in nm: fam_id = oid
            elif "стандарт" in nm: std_id = oid
    m = {}
    for pid, p in PLANS.items():
        if pid in ("trial", "intro"): continue
        oid = fam_id if p.get("tier") == "fam" else std_id
        if oid: m[pid] = oid
    LAVA_OFFERS = m
    return len(m)

async def lava_create(offer_id, email, periodicity="MONTHLY", currency="RUB"):
    body = {"email": email, "offerId": offer_id, "currency": currency, "periodicity": periodicity}
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{LAVA_API}/api/v2/invoice", json=body, headers=_lava_hdr(), timeout=20) as r:
            return await r.json()

# СБП — разовые одноразовые продукты (Стандарт + Семейный).
LAVA_SBP_OFFERS = {
    "1m":      "4c881027-0698-44a8-a79c-f18d2de6f25c",   # Стандарт 199₽
    "3m":      "2ec2a85e-f333-4ed0-9377-354630f666ee",   # Стандарт 499₽
    "6m":      "f9f283d6-f077-456b-87d6-993971e02fc4",   # Стандарт 899₽
    "12m":     "5d94e409-b4a5-4b0f-9711-6792f3216666",   # Стандарт 1590₽
    "fam_1m":  "d43a73f4-f937-405b-bb03-f57eab0b7068",   # Семейный 299₽
    "fam_3m":  "68e0f711-fb48-486a-8562-af657d150d48",   # Семейный 749₽
    "fam_6m":  "03e17172-4414-4425-aaab-c37055d2aece",   # Семейный 1350₽
    "fam_12m": "d4491650-87fa-457d-a675-192b4f3f3409",   # Семейный 2390₽
}

async def lava_create_sbp(offer_id, email, currency="RUB"):
    # СБП = разовый платёж (PAY2ME) на одноразовом оффере, эндпоинт v3
    body = {"email": email, "offerId": offer_id, "paymentProvider": "PAY2ME",
            "currency": currency, "paymentMethod": "SBP"}
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{LAVA_API}/api/v3/invoice", json=body, headers=_lava_hdr(), timeout=20) as r:
            return await r.json()

async def lava_status(invoice_id):
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{LAVA_API}/api/v1/invoices/{invoice_id}", headers=_lava_hdr(), timeout=20) as r:
            return await r.json()

async def lava_cancel_sub(contract_id, email):
    """Отменить автопродление подписки Lava (для «Старта» — разовая оплата, без автосписаний)."""
    if not contract_id or not email: return False
    for i in range(5):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.delete(f"{LAVA_API}/api/v1/subscriptions", params={"contractId": str(contract_id), "email": email},
                                    headers=_lava_hdr(), timeout=20) as r:
                    txt = await r.text()
                    if r.status in (200, 204):
                        log.info(f"lava sub cancelled {contract_id}"); return True
                    if r.status == 404 and i >= 1:
                        log.warning(f"lava cancel {contract_id}: 404 {txt[:200]}"); return False
                    log.warning(f"lava cancel {contract_id}: {r.status} {txt[:200]}")
        except Exception as e:
            log.error(f"lava cancel {contract_id}: {e}")
        await asyncio.sleep(60 * (i + 1))
    try: await notify_admins(f"⚠️ Не удалось отменить автопродление Lava «Старт»: <code>{contract_id}</code> ({email}) — отмени вручную")
    except Exception: pass
    return False

def intro_once_mark(order_id):
    try:
        c = db(); c.execute("CREATE TABLE IF NOT EXISTS intro_once(order_id TEXT PRIMARY KEY, ts INTEGER)")
        c.execute("INSERT OR IGNORE INTO intro_once VALUES(?,?)", (str(order_id), int(time.time()))); c.commit(); c.close()
    except Exception as e: log.error(f"intro_once_mark: {e}")
def intro_once_is(order_id):
    try:
        c = db(); c.execute("CREATE TABLE IF NOT EXISTS intro_once(order_id TEXT PRIMARY KEY, ts INTEGER)")
        r = c.execute("SELECT 1 FROM intro_once WHERE order_id=?", (str(order_id),)).fetchone(); c.close(); return bool(r)
    except Exception: return False

def intro_is_sub(): return (LAVA_INTRO.get("per") or "ONE_TIME") != "ONE_TIME"

# ---------- db ----------
_DB_READY = False
def db():
    global _DB_READY
    c = sqlite3.connect(DB, timeout=10)
    try:
        c.execute("PRAGMA busy_timeout=8000")
        if not _DB_READY: c.execute("PRAGMA journal_mode=WAL")   # параллельные читатели+писатель без 'database is locked'
    except Exception: pass
    if _DB_READY:
        return c
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        tg_id INTEGER PRIMARY KEY, uuid TEXT, plan TEXT,
        expires_at INTEGER, created_at INTEGER, trial_used INTEGER DEFAULT 0)""")
    for col, ddl in [("referrer", "INTEGER"), ("ref_bonus_given", "INTEGER DEFAULT 0"),
                     ("revoked", "INTEGER DEFAULT 0"),
                     ("rem3", "INTEGER DEFAULT 0"), ("rem1", "INTEGER DEFAULT 0"),
                     ("rem3h", "INTEGER DEFAULT 0"),
                     ("first_paid_at", "INTEGER"), ("pay_count", "INTEGER DEFAULT 0"),
                     ("trial_at", "INTEGER"), ("needs_sync", "INTEGER DEFAULT 0"),
                     ("sync_tries", "INTEGER DEFAULT 0"), ("dev_limit", "INTEGER"),
                     ("tr_reset", "INTEGER DEFAULT 0"), ("lim_notified", "INTEGER DEFAULT 0"),
                     ("captcha_ok", "INTEGER DEFAULT 0"), ("terms_at", "INTEGER")]:
        try: c.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
        except sqlite3.OperationalError: pass
    c.execute("""CREATE TABLE IF NOT EXISTS hosting_bills(
        name TEXT PRIMARY KEY, bill_date TEXT, r3 INTEGER DEFAULT 0, r1 INTEGER DEFAULT 0)""")
    c.execute("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)")
    c.execute("""CREATE TABLE IF NOT EXISTS promos(
        code TEXT PRIMARY KEY, days INTEGER, max_uses INTEGER, used INTEGER DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS promo_redemptions(
        code TEXT, tg_id INTEGER, PRIMARY KEY(code, tg_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS trial_ips(
        ip TEXT, tg_id INTEGER, ts INTEGER, PRIMARY KEY(ip, tg_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS abuse_flags(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, tg_id INTEGER, reason TEXT, ip TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS pending_pays(
        order_id TEXT PRIMARY KEY, provider TEXT, tg_id INTEGER, pid TEXT,
        created_at INTEGER, done INTEGER DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS paid_orders(
        order_id TEXT PRIMARY KEY, tg_id INTEGER, pid TEXT, ts INTEGER)""")
    c.execute("CREATE TABLE IF NOT EXISTS admins(tg_id INTEGER PRIMARY KEY)")
    c.execute("CREATE TABLE IF NOT EXISTS bypass_grants(tg_id INTEGER PRIMARY KEY, granted_by INTEGER NOT NULL, granted_at INTEGER NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS ambassadors(tg_id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, created_at INTEGER NOT NULL, created_by INTEGER NOT NULL)")
    c.execute("CREATE TABLE IF NOT EXISTS payment_ui(order_id TEXT PRIMARY KEY, chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL, created_at INTEGER NOT NULL, last_edit INTEGER NOT NULL DEFAULT 0)")
    c.commit()
    _DB_READY = True
    return c

def days_word(n):
    """Склонение слова 'день' под число: 1 день, 2 дня, 5 дней."""
    n = abs(int(n)); d100 = n % 100; d10 = n % 10
    if 11 <= d100 <= 14: return "дней"
    if d10 == 1: return "день"
    if 2 <= d10 <= 4: return "дня"
    return "дней"

def trial_days():
    return int(PLANS["trial"]["days"])

def apply_settings():
    """Подтянуть цены/тариф/реф-бонус из settings в рантайм (клиент правит через админку)."""
    global REF_BONUS_DAYS
    c = db(); ov = dict(c.execute("SELECT key,value FROM settings").fetchall()); c.close()
    CFG.clear(); CFG.update(ov)
    for pid in PLANS:
        for kind in ("rub", "stars", "days"):
            v = ov.get(f"{pid}_{kind}")
            if v is not None:
                try: PLANS[pid][kind] = int(v)
                except Exception: pass
    for _p in PLANS.values():                      # лимит провайдера: одна оплата <= 10 000 ₽
        if int(_p.get("rub") or 0) > 10000: _p["rub"] = 10000
    try: REF_BONUS_DAYS = int(ov.get("ref_bonus_days", REF_BONUS_DAYS))
    except Exception: pass
    # титул пробного всегда отражает актуальное число дней (из админки)
    td = trial_days()
    PLANS["trial"]["title"] = f"🎁 Пробный · {td} {days_word(td)}"
    ip = PLANS["intro"]
    if LAVA_INTRO.get("rub"): ip["rub"] = LAVA_INTRO["rub"]      # цена «Старта» = цена оффера в Lava
    ip["title"] = f"🔥 Старт · {ip['days']} {days_word(ip['days'])} за {ip['rub']} ₽"

def cfg_set(key, value):
    c = db(); c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, str(value)))
    c.commit(); c.close(); apply_settings()

# счета хостинга (напоминания за 3 и 1 день). Даты от клиента 24.08.
HOSTING_BILLS_SEED = [
    ("Cloudzy (панель + подписки + NL)", "2026-10-19"),
    ("ISHosting (нода 🇩🇪 DE)", "2026-09-16"),
    ("ISHosting (нода 🇫🇮 Финляндия)", "2026-09-23"),
]
def seed_bills():
    c = db()
    for name, date in HOSTING_BILLS_SEED:
        c.execute("INSERT OR IGNORE INTO hosting_bills(name, bill_date) VALUES(?,?)", (name, date))
    c.commit(); c.close()

def get_user(tg_id):
    c = db(); r = c.execute("SELECT tg_id,uuid,plan,expires_at,created_at,trial_used,"
                            "referrer,ref_bonus_given,revoked FROM users WHERE tg_id=?", (tg_id,)).fetchone(); c.close()
    if not r: return None
    return dict(tg_id=r[0], uuid=r[1], plan=r[2], expires_at=r[3], created_at=r[4],
                trial_used=r[5], referrer=r[6], ref_bonus_given=r[7], revoked=r[8])

def upsert_user(tg_id, uuid_, plan, expires_at, trial_used=None):
    c = db(); ex = get_user(tg_id)
    tu = trial_used if trial_used is not None else (ex["trial_used"] if ex else 0)
    if ex:
        c.execute("UPDATE users SET uuid=?,plan=?,expires_at=?,trial_used=? WHERE tg_id=?",
                  (uuid_, plan, expires_at, tu, tg_id))
    else:
        c.execute("INSERT INTO users(tg_id,uuid,plan,expires_at,created_at,trial_used) VALUES(?,?,?,?,?,?)",
                  (tg_id, uuid_, plan, expires_at, int(time.time()), tu))
    c.commit(); c.close()

def db_set(tg_id, **cols):
    if not cols: return
    c = db()
    sets = ",".join(f"{k}=?" for k in cols)
    c.execute(f"UPDATE users SET {sets} WHERE tg_id=?", (*cols.values(), tg_id))
    c.commit(); c.close()

def ensure_user(tg_id):
    if not get_user(tg_id):
        c = db(); c.execute("INSERT INTO users(tg_id,created_at) VALUES(?,?)", (tg_id, int(time.time())))
        c.commit(); c.close()

# ---------- админы (несколько; seed из env + управляемые в боте) ----------
def admin_ids():
    try:
        c = db(); extra = {r[0] for r in c.execute("SELECT tg_id FROM admins").fetchall()}; c.close()
    except Exception: extra = set()
    return SEED_ADMINS | extra

def is_admin(uid):
    return uid in admin_ids()

def add_admin(tg_id):
    c = db(); c.execute("INSERT OR IGNORE INTO admins(tg_id) VALUES(?)", (int(tg_id),)); c.commit(); c.close()

def rm_admin(tg_id):
    c = db(); c.execute("DELETE FROM admins WHERE tg_id=?", (int(tg_id),)); c.commit(); c.close()

async def notify_admins(text, **kw):
    for a in admin_ids():
        try: await bot.send_message(a, text, **kw)
        except Exception: pass

def set_referrer(tg_id, ref_id):
    if ref_id == tg_id: return
    u = get_user(tg_id)
    if u and not u["referrer"] and not get_user(ref_id) is None:
        db_set(tg_id, referrer=ref_id)

def ref_count(tg_id):
    c = db(); n = c.execute("SELECT COUNT(*) FROM users WHERE referrer=?", (tg_id,)).fetchone()[0]; c.close()
    return n

def grant_ref_bonus(paid_tg_id):
    """Начислить рефереру бонусные дни за первую оплату приглашённого. Возвращает (ref_id, new_exp) или None."""
    u = get_user(paid_tg_id)
    if not u or not u["referrer"] or u["ref_bonus_given"]:
        return None
    db_set(paid_tg_id, ref_bonus_given=1)
    ref = get_user(u["referrer"])
    if not ref:
        return None
    base = max(time.time(), ref["expires_at"] or 0)
    new_exp = int(base + REF_BONUS_DAYS * 86400)
    ruuid = ref["uuid"] or str(uuid.uuid4())
    was_inactive = (not ref["expires_at"] or ref["expires_at"] < time.time() or ref["revoked"])
    upsert_user(u["referrer"], ruuid, ref["plan"] or "ref", new_exp)
    if was_inactive:
        db_set(u["referrer"], revoked=0, needs_sync=1)   # ключ дольёт notify_ref_bonus (в потоке) / sync_worker
    # ruuid_to_add != None => вызывающий должен добавить ключ на ноды НЕ блокируя loop
    return u["referrer"], new_exp, (ruuid if was_inactive else None)

# ---------- xray user management (multi-node, via API — NO restart) ----------
import paramiko, shlex

XRAY_BIN = ""
API_PORT = 8090
INBOUND_TAG = "vless-in"

def _ssh(host):
    cl = paramiko.SSHClient(); cl.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cl.connect(host, username="root", pkey=paramiko.Ed25519Key.from_private_key_file(SSH_KEY),
               timeout=15, banner_timeout=20, auth_timeout=20)
    return cl

import threading as _threading
_ssh_pool = {}                          # host -> живой SSHClient (переиспользуем)
_ssh_pool_lock = _threading.Lock()

def _ssh_run(host, cmd, timeout=20):
    """SSH-команда с ПЕРЕИСПОЛЬЗОВАНИЕМ соединения + таймаутом канала.
    Убирает шторм хендшейков (дружит с fail2ban на NL/FI) и не виснет навсегда при зависшей ноде."""
    with _ssh_pool_lock:
        cl = _ssh_pool.get(host)
        tr = cl.get_transport() if cl else None
        if cl is None or tr is None or not tr.is_active():
            if cl:
                try: cl.close()
                except Exception: pass
            cl = _ssh(host)
            try: cl.get_transport().set_keepalive(30)
            except Exception: pass
            _ssh_pool[host] = cl
        try:
            si, so, se = cl.exec_command(cmd, timeout=timeout)
            return (so.read() + se.read()).decode("utf-8", "replace")
        except Exception:
            try: cl.close()
            except Exception: pass
            _ssh_pool.pop(host, None)
            raise

def _api_cmd(uuid_, tag, add, flow=""):
    """Shell-команда adu/rmu одного юзера в КОНКРЕТНЫЙ inbound-тег через xray API (без рестарта). email=uuid."""
    if add:
        # port/listen — заглушка для парсера (adu находит РЕАЛЬНЫЙ inbound по тегу, порт стаба не важен)
        # flow нужен для reality-tcp+vision инбаундов (Яндекс-вход); для grpc/ws пусто.
        j = json.dumps({"inbounds": [{"tag": tag, "port": 443, "listen": "0.0.0.0", "protocol": "vless",
              "settings": {"clients": [{"id": uuid_, "flow": flow, "email": uuid_}],
              "decryption": "none"}}]})
        return (f"F=$(mktemp); cat > $F <<'JJJ'\n{j}\nJJJ\n"
                f"{XRAY_BIN} api adu --server=127.0.0.1:{API_PORT} $F; rm -f $F")
    return f"{XRAY_BIN} api rmu --server=127.0.0.1:{API_PORT} -tag {shlex.quote(tag)} {shlex.quote(uuid_)}"

def _file_sync_py(cfg_path, uuid_, add, flow=""):
    """Персистентный синк конфига: добавить/убрать клиента во ВСЕ vless-inbound'ы (не только первый!). НЕ рестартит.
    flow берётся из streamSettings инбаунда: reality-tcp -> vision, иначе пусто (чтобы grpc/ws не ломались)."""
    op = ("  if u not in [c.get('id') for c in cl]:\n"
          "    ss=ib.get('streamSettings',{})\n"
          "    fl='xtls-rprx-vision' if (ss.get('security')=='reality' and ss.get('network','tcp')=='tcp') else ''\n"
          "    cl.append({'id':u,'email':u,'flow':fl})" if add
          else "  ib['settings']['clients']=[c for c in cl if c.get('id')!=u]")
    return ("import json\n"
            f"p={cfg_path!r}; u={uuid_!r}\n"
            "d=json.load(open(p))\n"
            "for ib in d['inbounds']:\n"
            "  if ib.get('protocol')!='vless': continue\n"
            "  cl=ib['settings'].setdefault('clients',[])\n"
            f"{op}\n"
            "json.dump(d,open(p,'w'),indent=2)\n")

def _apply_node(node, uuid_, add):
    """Синк файла (ВСЕ vless-inbound'ы, персистентность) + adu/rmu по КАЖДОМУ тегу ноды (мгновенно, БЕЗ рестарта)."""
    if node.get("rw"): return  # Remnawave: провижининг через rw_sync.py
    fpy = _file_sync_py(node["cfg"], uuid_, add)
    flow = node.get("flow", "")
    expected = "Added" if add else "Removed"
    def check_api(out, tag, rc=0):
        if rc != 0 or expected not in (out or ""):
            raise RuntimeError(f"xray API {tag}: {(out or '').strip()[:300] or 'пустой ответ'}")
    if node["ssh"] is None:
        subprocess.run(["python3", "-c", fpy], check=True, timeout=25)
        for tag in node.get("tags", [INBOUND_TAG]):
            r = subprocess.run(_api_cmd(uuid_, tag, add, flow), shell=True,
                               capture_output=True, text=True, timeout=25)
            check_api(r.stdout + r.stderr, tag, r.returncode)
    else:
        _ssh_run(node["ssh"], "python3 -c " + shlex.quote(fpy), timeout=25)
        for tag in node.get("tags", [INBOUND_TAG]):
            check_api(_ssh_run(node["ssh"], _api_cmd(uuid_, tag, add, flow), timeout=25), tag)

def xray_add_client(uuid_):
    """Добавить клиента на все ноды. Возвращает список имён нод, где НЕ удалось (для досинка)."""
    failed = []
    for n in NODES:
        try: _apply_node(n, uuid_, True)
        except Exception as e:
            log.error(f"add {n['name']}: {e}"); failed.append(n["name"])
    return failed

def xray_remove_client(uuid_):
    for n in NODES:
        try: _apply_node(n, uuid_, False)
        except Exception as e: log.error(f"rm {n['name']}: {e}")

def rw_sync_now(tg_id):
    """03.11.2026: мгновенный синк юзера в Remnawave (не ждём 20с цикла zpn-rw-sync) — ссылка работает сразу."""
    if not RW_API or not RW_TOKEN:
        raise RuntimeError("Remnawave API integration is not configured")
    try:
        r = subprocess.run(["python3", "/opt/zpnbot/rw_sync.py", "--only", str(int(tg_id))],
                           capture_output=True, text=True, timeout=20)
    except Exception as e:
        log.error(f"rw_sync_now {tg_id}: {type(e).__name__}"); raise
    if r.returncode != 0:
        log.error(f"rw_sync_now {tg_id}: rc={r.returncode}")
        raise RuntimeError("Remnawave synchronization failed")
    try:
        remote = _rw_call("GET", f"/users/by-username/tg{int(tg_id)}").get("response") or {}
        local = get_user(int(tg_id))
        if not local or remote.get("vlessUuid") != local.get("uuid"):
            raise RuntimeError("Remnawave did not confirm the subscription")
    except Exception as e:
        log.error(f"rw_sync_now {tg_id}: verification {type(e).__name__}"); raise

# ---------- лимит устройств (#8) через xray Stats (онлайн-IP на юзера) ----------
import re as _re
DEVICES = {}       # uuid -> кол-во онлайн-устройств (уникальных IP), обновляет worker
_dev_notified = set()  # uuid, кого уже предупредили в текущем эпизоде превышения

def _node_ips(node, uuid_):
    if node.get("rw"): return set()
    cmd = f"{XRAY_BIN} api statsonlineiplist --server=127.0.0.1:{API_PORT} -email {shlex.quote(uuid_)} 2>/dev/null"
    try:
        if node["ssh"] is None:
            out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15).stdout
        else:
            out = _ssh_run(node["ssh"], cmd, timeout=15)
    except Exception:
        return set()
    return set(_re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", out))

def device_ips(uuid_):
    ips = set()
    for n in NODES:
        try: ips |= _node_ips(n, uuid_)
        except Exception: pass
    return ips

def device_count(uuid_):
    return len(device_ips(uuid_))

def node_online_ips(node):
    """ОДИН SSH на ноду: {email(uuid): set(IP)} по всем онлайн-юзерам разом (вместо запроса на юзера)."""
    if node.get("rw"): return {}
    cmd = f"{XRAY_BIN} api statsgetallonlineusers --server=127.0.0.1:{API_PORT} 2>/dev/null"
    try:
        if node["ssh"] is None:
            out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20).stdout
        else:
            out = _ssh_run(node["ssh"], cmd, timeout=20)
    except Exception:
        return {}
    out = (out or "").strip()
    if not out or out == "{}":
        return {}
    res = {}
    try:
        data = json.loads(out)
        if isinstance(data, dict):
            for email, v in data.items():
                # IP тянем регэкспом из значения (устойчиво к формату: список/строка/с портами)
                res[email] = set(_re.findall(r"\d{1,3}(?:\.\d{1,3}){3}", json.dumps(v)))
    except Exception as e:
        log.error(f"node_online_ips {node['name']}: {e}")
    return res

async def all_online_ips():
    """Слить онлайн-IP со всех нод: {uuid: set(IP)}. Всего SSH = число нод (не число юзеров)."""
    merged = {}
    for n in NODES:
        try:
            m = await asyncio.to_thread(node_online_ips, n)
            for email, ips in m.items():
                merged.setdefault(email, set()).update(ips)
        except Exception: pass
    return merged

# ---------- антиабуз пробного периода (#15) ----------
ABUSE_TRIAL_PER_IP = 3     # больше стольких триал-аккаунтов с одного IP -> лишние глушим
TRIAL_BURST = 15           # триалов в час -> сигнал админу о возможной атаке ботами
_abuse_revoked = set()     # tg_id, кого уже разжаловали за абуз (не дёргать повторно)

def record_trial_ips(tg_id, ips):
    if not ips: return
    c = db(); now = int(time.time())
    for ip in ips:
        c.execute("INSERT OR IGNORE INTO trial_ips(ip, tg_id, ts) VALUES(?,?,?)", (ip, tg_id, now))
    c.commit(); c.close()

def flag_abuse(tg_id, reason, ip=None):
    c = db(); c.execute("INSERT INTO abuse_flags(ts, tg_id, reason, ip) VALUES(?,?,?,?)",
                        (int(time.time()), tg_id, reason, ip)); c.commit(); c.close()

def trial_ip_offenders():
    """[(ip, [tg_id...]) ...] — IP, с которых триал-аккаунтов больше лимита (старые -> новые)."""
    c = db(); rows = c.execute("SELECT ip, tg_id, MIN(ts) t FROM trial_ips GROUP BY ip, tg_id ORDER BY t").fetchall(); c.close()
    by_ip = {}
    for ip, tg, _ in rows:
        by_ip.setdefault(ip, [])
        if tg not in by_ip[ip]: by_ip[ip].append(tg)
    return [(ip, tgs) for ip, tgs in by_ip.items() if len(tgs) > ABUSE_TRIAL_PER_IP]

def trials_last_hour():
    c = db(); n = c.execute("SELECT COUNT(*) FROM users WHERE trial_at>?",
                            (int(time.time()) - 3600,)).fetchone()[0]; c.close()
    return n

# ---------- AVTO по нагрузке (#3 Smart Routing + #5 контроль нагрузки) ----------
# example.invalid указывает на ЖИВУЮ наименее загруженную ноду. Единый владелец записи — бот
# (на панели rotate.py оставлен только failover IP внутри одной ноды).
AUTO_DOMAIN = ""
AUTO_PRIORITY = ["example.invalid", "example.invalid", "example.invalid"]  # при равной нагрузке — ближе к РФ
# 🔴 AVTO закреплён (settings.auto_pin=0.0.0.0=DE): example.invalid:443 reality может жить ТОЛЬКО на DE
# (у NL reality на :8443, у FI вход через релей) — поэтому нагрузочный выбор ниже дремлет, это ОК.
LOAD_ALERT = 300            # порог активных соединений на ноду -> тревога админу
LOAD_SWITCH_MIN = 50        # ниже этого нагрузку не считаем поводом переключать AVTO
LOAD_SWITCH_MARGIN = 30     # насколько лучшая нода должна быть легче текущей, чтобы свапнуть
_auto_state = {"ip": None, "dom": None}
_load_notified = set()
_last_loads = {}            # dom -> последняя измеренная нагрузка (переиспользуем, не меряем дважды за цикл)

def node_load(node):
    """Активных TCP-соединений на VPN-порту ноды (прокси нагрузки). -1 если недоступно."""
    if node.get("rw"): return -1
    port = node.get("port", 443)
    cmd = f"ss -Htn state established '( sport = :{port} )' 2>/dev/null | wc -l"
    try:
        if node["ssh"] is None:
            out = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15).stdout
        else:
            out = _ssh_run(node["ssh"], cmd, timeout=15)
        return int((out.strip().splitlines() or ["0"])[-1])
    except Exception:
        return -1

async def node_loads():
    """dom -> нагрузка для живых нод (для админ-статуса)."""
    res = {}
    for n in NODES:
        host = n["ssh"] or n["host"]
        if await asyncio.to_thread(_tcp_up, host, n["port"]):
            res[n["host"]] = await asyncio.to_thread(node_load, n)
    return res

async def pick_auto_node(force=False):
    """Выбрать живую наименее загруженную ноду и навести на неё example.invalid (с гистерезисом).
    Если задан settings.auto_pin (IP) — держим auto на нём."""
    if all(n.get("rw") for n in NODES): return None  # Авто теперь внутри Remnawave (leastPing DE/FI)
    try:
        c = db(); pin = dict(c.execute("SELECT key,value FROM settings").fetchall()).get("auto_pin"); c.close()
    except Exception: pin = None
    if pin:
        a = await cf_record(AUTO_DOMAIN)
        if a and a["content"] != pin:
            await cf_set_ip(a["id"], pin)
            log.info(f"AVTO закреплён (pin) -> {pin}")
        return pin
    info = []  # {load, prio, dom, ip}
    for n in NODES:
        host = n["ssh"] or n["host"]
        if not await asyncio.to_thread(_tcp_up, host, n["port"]):
            continue
        rec = await cf_record(n["host"])
        ip = rec["content"] if rec else None
        if not ip:
            continue
        load = await asyncio.to_thread(node_load, n)
        _last_loads[n["host"]] = load          # кэш для auto_worker/cb_adm_load — без повторного SSH
        info.append({"load": load if load >= 0 else 10**9,
                     "prio": AUTO_PRIORITY.index(n["host"]) if n["host"] in AUTO_PRIORITY else 99,
                     "dom": n["host"], "ip": ip})
    if not info:
        return None
    info.sort(key=lambda x: (x["load"], x["prio"]))
    best = info[0]
    auto = await cf_record(AUTO_DOMAIN)
    if not auto:
        return None
    cur_ip = auto["content"]
    cur = next((x for x in info if x["ip"] == cur_ip), None)
    switch = force or cur is None            # текущий AVTO мёртв/неизвестен -> чиним
    if not switch and cur is not None and best["ip"] != cur_ip:
        if cur["load"] >= LOAD_SWITCH_MIN and best["load"] + LOAD_SWITCH_MARGIN < cur["load"]:
            switch = True                    # текущая перегружена, лучшая заметно легче
    if switch and best["ip"] != cur_ip:
        await cf_set_ip(auto["id"], best["ip"])
        if ADMIN_ID:
            try: await notify_admins(
                f"🧭 AVTO → {best['dom'].split('.')[0].upper()} ({best['ip']}), нагрузка {best['load']} соед.")
            except Exception: pass
    _auto_state.update(ip=best["ip"], dom=best["dom"])
    return best["dom"]

async def auto_worker():
    """Периодически ведёт example.invalid к наименее загруженной живой ноде + алерт о перегрузе."""
    await asyncio.sleep(60)
    while True:
        try:
            await pick_auto_node()               # меряет нагрузку и кладёт в _last_loads
            for n in NODES:                      # алерт по КЭШУ — без повторного SSH
                load = _last_loads.get(n["host"])
                if load is None or load < 0:
                    continue
                if load >= LOAD_ALERT and n["host"] not in _load_notified:
                    _load_notified.add(n["host"])
                    if ADMIN_ID:
                        try: await notify_admins(
                            f"🔥 <b>Высокая нагрузка</b>: {n['name']} — {load} соединений. "
                            f"Стоит добавить ноду/IP.")
                        except Exception: pass
                elif load < LOAD_ALERT * 0.8:
                    _load_notified.discard(n["host"])
        except Exception as e:
            log.error(f"auto: {e}")
        await asyncio.sleep(90)

def vless_link(uuid_, node):
    frag = urllib.parse.quote(f"{node['name']} · VAYNAH VPN")   # флаг+страна, URL-энкод для совместимости
    return (f"vless://{uuid_}@{node['host']}:{REALITY['port']}?encryption=none&security=reality"
            f"&sni={REALITY['sni']}&fp=chrome&pbk={REALITY['pbk']}&sid={REALITY['sid']}"
            f"&type=grpc&serviceName={REALITY['svc']}&mode=multi#{frag}")

def all_links(uuid_):
    return "\n\n".join(f"{n['name']}:\n<code>{vless_link(uuid_, n)}</code>" for n in NODES)

SUB_DOMAIN = ""
SUB_DOMAIN = os.environ.get("INGVERTU_SUB_DOMAIN", "sub.vertuwpn.ru").strip("/")
SUB_PATH = "/" + os.environ.get("INGVERTU_SUB_PATH", "/api/sub").strip("/")
# 16.11.2026: ссылки на САМУ подписку идут через Yandex CDN (не блокируется в РФ, GET-only). Кабинет/админка остаются на SUB_DOMAIN.
SUB_LINK_DOMAIN = os.environ.get("INGVERTU_SUB_LINK_DOMAIN", SUB_DOMAIN).strip("/")
def sub_url(uuid_):
    # 03.11.2026: новая подписка Remnawave (XHTTP, домены). shortUuid = первые 16 hex UUID (см. rw_sync.py)
    return f"https://{SUB_LINK_DOMAIN}{SUB_PATH}/{uuid_.replace('-', '')[:16]}"
def old_sub_url(uuid_):
    return sub_url(uuid_)
def happ_url(uuid_):
    # 05.11.2026: своя страница-переходник: сразу открывает Happ (happ://add/…) + кнопки установки/копирования
    return f"https://{SUB_DOMAIN}/app/happ/{uuid_.replace('-', '')[:16]}"

HAPP_PAGE = ""

async def happ_page(request):
    s = request.match_info.get("s", "")
    if not _re.fullmatch(r"[0-9a-fA-F]{16}", s): return web.Response(status=404, text="not found")
    sub = f"https://{SUB_LINK_DOMAIN}{SUB_PATH}/{s.lower()}"
    page = HAPP_PAGE or open("/opt/zpnbot/happ_page.html", encoding="utf-8").read()   # 16.11.2026: была пустая страница
    return web.Response(text=page.replace("__SUB__", sub), content_type="text/html",
                        headers={"Cache-Control": "no-store"})
def incy_url(uuid_):
    return f"https://{SUB_DOMAIN}/app/incy/{uuid_.replace('-', '')[:16]}"

async def incy_page(request):
    s = request.match_info.get("s", "")
    if not _re.fullmatch(r"[0-9a-fA-F]{16}", s):
        return web.Response(status=404, text="not found", headers={"Cache-Control": "no-store"})
    sub = f"https://{SUB_LINK_DOMAIN}{SUB_PATH}/{s.lower()}"
    page = open("/opt/zpnbot/incy_page.html", encoding="utf-8").read().replace("__SUB__", sub)
    return web.Response(text=page, content_type="text/html", headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"})


def connect_url(uuid_):
    return f"https://{SUB_DOMAIN}/app/connect/{uuid_.replace('-', '')[:16]}"

async def connect_page(request):
    s = request.match_info.get("s", "")
    if not _re.fullmatch(r"[0-9a-fA-F]{16}", s):
        return web.Response(status=404, text="not found", headers={"Cache-Control": "no-store"})
    sub = f"https://{SUB_LINK_DOMAIN}{SUB_PATH}/{s.lower()}"
    plan_name, exp_text, devices = "Стандарт", "Активна", "до 3"
    try:
        c = db()
        row = c.execute("SELECT plan, expires_at, dev_limit FROM users WHERE lower(replace(uuid, '-', '')) LIKE ? LIMIT 1", (s.lower() + "%",)).fetchone()
        c.close()
        if row:
            plan_name = PLANS.get(row[0], {}).get("title", "Стандарт").split(" · ")[0]
            if row[1]: exp_text = datetime.fromtimestamp(row[1]).strftime("%d.%m.%Y")
            limit = row[2] or PLANS.get(row[0], {}).get("devices", 3)
            devices = "без лимита" if int(limit) >= 99 else f"до {limit}"
    except Exception:
        pass
    try:
        page = open("/opt/zpnbot/device_page.html", encoding="utf-8").read()
    except Exception:
        return web.Response(status=503, text="page unavailable")
    page = (page.replace("__SUB__", sub).replace("__PLAN__", plan_name)
            .replace("__EXP__", exp_text).replace("__DEVICES__", devices))
    return web.Response(text=page, content_type="text/html",
                        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                                 "X-Content-Type-Options": "nosniff"})

def conf_url(uuid_, geo=""):
    # Legacy /conf route was not registered in this deployment; use the active Remnawave subscription URL.
    return sub_url(uuid_)
def me_url(uuid_):
    return f"https://{SUB_DOMAIN}/me/{uuid_}"
def clash_url(uuid_):
    return f"https://{SUB_DOMAIN}/clash/{uuid_}"
def sb_url(uuid_):
    # ЕДИНЫЙ дефолт: sing-box (РОДНОЙ для Happ) = 4 гео (флажки) + РФ-сайты напрямую, из коробки, без ошибки 39.
    return f"https://{SUB_DOMAIN}/singbox/{uuid_}"

APPS = ("📲 <b>Приложения</b>\n"
        "• 🤖 Android — <b>Happ</b>, <b>INCY</b>, v2rayNG\n"
        "• 🍏 iPhone / iPad — <b>Happ</b>, <b>INCY</b>, Streisand\n"
        "• 🪟 Windows — <b>Happ</b>, <b>INCY</b>, Hiddify\n"
        "• 💻 macOS — <b>Happ</b>, <b>INCY</b>, V2Box\n"
        "<i>Happ: happ.su · INCY: incy.cc (компьютерная версия pre-alpha)</i>")

def key_block(uuid_):
    return (f"🔗 <b>Ссылка-подписка</b> <i>(нажми, чтобы скопировать)</i>\n"
            f"<code>{sub_url(uuid_)}</code>\n\n"
            f"<b>Подключение за 3 шага</b>\n"
            f"1️⃣ Установи <b>Happ</b> или <b>INCY</b>\n"
            f"2️⃣ Нажми кнопку своего приложения ниже — или вставь ссылку вручную\n"
            f"3️⃣ Выбери 🇫🇮 <b>Финляндия · ⚡ Быстрый</b> и включи\n\n"
            f"🇷🇺 Банки, Госуслуги и маркетплейсы работают без отключения VPN")

def qr_png(data):
    img = qrcode.make(data)
    buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
    return buf.read()

async def deliver_key(chat_id, uuid_, header):
    """Отдать ключ красиво: QR подписки с пятью серверами. Техчасть скрыта."""
    cu = sub_url(uuid_)
    cap = (f"{header}\n\n"
           f"📷 <b>Отсканируй QR в Happ или INCY</b>.\n"
           f"Или нажми «🚀 Подключить» ниже.\n\n"
           f"🌍 🇩🇪 · 🇳🇱 · 🇪🇸 · 🇫🇮 — выбор страны в приложении\n"
           f"🇷🇺 Банки и Госуслуги работают без отключения VPN\n\n"
           f"🔗 <code>{cu}</code>")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(style="primary", text="📲 Подключить устройство", url=connect_url(uuid_))],
        [InlineKeyboardButton(style="primary", text="📖 Инструкция", callback_data="help"),
         InlineKeyboardButton(style="primary", text="🏠 Меню", callback_data="menu")]])
    try:
        await bot.send_photo(chat_id, BufferedInputFile(qr_png(cu), "zpn-qr.png"), caption=cap, reply_markup=kb)
    except Exception as e:
        log.error(f"deliver_key: {e}")
        await bot.send_message(chat_id, cap + "\n\n" + APPS, reply_markup=kb)

# ---------- ротация IP нод (Cloudflare) ----------
CF_TOKEN = ""
CF_ZONE = ""
ROTATE_POOL = {}

async def _cf(path, method="GET", body=None):
    if not CF_TOKEN or not CF_ZONE:
        raise RuntimeError("Cloudflare integration is not configured")
    hdr = {"Authorization": "Bearer " + CF_TOKEN, "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as s:
        async with s.request(method, "https://api.cloudflare.com/client/v4" + path,
                             json=body, headers=hdr, timeout=20) as r:
            return await r.json()

async def cf_record(name):
    d = await _cf(f"/zones/{CF_ZONE}/dns_records?type=A&name={name}")
    r = d.get("result", [])
    return r[0] if r else None

async def cf_set_ip(rec_id, ip):
    await _cf(f"/zones/{CF_ZONE}/dns_records/{rec_id}", "PATCH", {"content": ip, "proxied": False})

# ---------- ui ----------
def game_on():
    return False

def main_menu(tg_id):
    # 16.11.2026: новая раскладка — главное действие зелёное, вторичное серое, личный кабинет
    u = get_user(tg_id)
    active = bool(u and u["expires_at"] and u["expires_at"] > time.time())
    kb = []
    if active:
        kb.append([InlineKeyboardButton(text="🔑 Подключить VPN", callback_data="my", style="success")])
        if u["uuid"]:
            kb.append([InlineKeyboardButton(text="🏔 Личный кабинет", web_app=WebAppInfo(url=me_url(u["uuid"])), style="primary")])
        if autopay_get(tg_id) and autopay_get(tg_id)["active"]:
            kb.append([InlineKeyboardButton(text="🔁 Автопродление", callback_data="autopay")])
    else:
        if intro_ready() and intro_eligible(tg_id):
            ip = PLANS["intro"]
            kb.append([InlineKeyboardButton(style="success", text=f"🔥 {ip['days']} {days_word(ip['days'])} за {ip['rub']} ₽", callback_data="intro")])
        if trial_allowed(tg_id):
            kb.append([InlineKeyboardButton(text="🎁 Попробовать бесплатно", callback_data="plan:trial", style="success")])
        kb.append([InlineKeyboardButton(text="💳 Тарифы", callback_data="buy", style="primary")])
    kb.append([InlineKeyboardButton(text="👥 Друзьям", callback_data="ref"),
               InlineKeyboardButton(text="🎟 Промокод", callback_data="usepromo")])
    kb.append([InlineKeyboardButton(text="📖 Как подключить", callback_data="help"),
               InlineKeyboardButton(text="💬 Поддержка", callback_data="support")])
    if active:
        kb.append([InlineKeyboardButton(text="💳 Продлить подписку", callback_data="buy")])
    kb.append([InlineKeyboardButton(text="📄 Документы", callback_data="docs")])
    if ambassador_get(tg_id):
        kb.append([InlineKeyboardButton(text="🤝 Кабинет амбассадора", callback_data="amb:mine")])
    if is_admin(tg_id):
        kb.append([InlineKeyboardButton(text="⚙️ Админка", callback_data="admin", style="danger"),
                   InlineKeyboardButton(text="🖥 Веб-панель", callback_data="adm:web")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# --- Шаблон A: текстовая шапка-«баннер» (лого пока нет) + тарифы по дням с ∞ Безлим ---
BANNER = ("⚡️ <b>VAYNAH VPN</b>\n"
          "<i>Выбери подходящий тариф</i>\n")

def plan_discount(p):
    """Скидка периода относительно помесячной цены того же тарифа, %."""
    base = 199 if p.get("tier") == "std" else 299   # цена за 30 дней
    full = base * (p["days"] / 30)
    return max(0, round((1 - p["rub"] / full) * 100)) if full else 0

def plans_menu(tier="std", uid=None):
    kb = []
    for pid, p in PLANS.items():
        if pid in ("trial", "intro", "channel_trial") or not p.get("rub") or p.get("tier") != tier: continue
        d = plan_discount(p)
        disc = f" −{d}%" if d >= 5 else ""
        kb.append([InlineKeyboardButton(style="primary", text=f"📅 {p['days']} дней · 50 ГБ{disc} — {p['rub']}₽",
                                        callback_data=f"plan:{pid}")])
    if uid and trial_allowed(uid):
        kb.append([InlineKeyboardButton(style="primary", text=PLANS["trial"]["title"], callback_data="plan:trial")])
    kb.append([InlineKeyboardButton(style="primary", text="⬅️ Назад", callback_data="buy")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def pay_menu(pid):
    if platega_ready():
        kb = [[InlineKeyboardButton(text=PLATEGA_METHOD_TITLES.get(m, f"Оплатить ({m})"),
                                    callback_data=f"plg:{pid}:{m}", style="primary")] for m in PLATEGA_METHODS]
    else:
        kb = [[InlineKeyboardButton(text="🕓 Platega — подключим позже", callback_data="pay_stub", style="primary")]]
    kb.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="buy", style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.callback_query(F.data == "pay_stub")
async def cb_pay_stub(q: CallbackQuery):
    await q.answer("Оплата пока отключена. Сейчас платежи не принимаются; Platega подключим позже.", show_alert=True)

# ---------------------------------- Platega (добавлено 2026-11-25) ----------------------------------
# Ключи берутся ТОЛЬКО из /etc/ingvertuvpn/bot.env: PLATEGA_MERCHANT_ID, PLATEGA_SECRET, PLATEGA_METHODS (напр. "2,11").
# Пока ключей нет — кнопки Platega не показываются, вебхук отвечает 503.
PLATEGA_API = "https://app.platega.io"
PLATEGA_MERCHANT_ID = os.environ.get("PLATEGA_MERCHANT_ID", "").strip()
PLATEGA_SECRET = os.environ.get("PLATEGA_SECRET", "").strip()
PLATEGA_METHODS = [int(x) for x in os.environ.get("PLATEGA_METHODS", "2,11").replace(" ", "").split(",") if x.isdigit()]
PLATEGA_METHOD_TITLES = {2: "⚡️ СБП", 11: "💳 Банковская карта", 12: "🌍 Международная карта",
                         13: "🪙 Криптовалюта", 14: "🟢 SberPay", 3: "ЕРИП"}

def platega_ready():
    return bool(PLATEGA_MERCHANT_ID and PLATEGA_SECRET and PLATEGA_METHODS)

async def platega_req(method, path, body=None):
    hdr = {"X-MerchantId": PLATEGA_MERCHANT_ID, "X-Secret": PLATEGA_SECRET, "Content-Type": "application/json"}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25)) as s:
        async with s.request(method, PLATEGA_API + path, json=body, headers=hdr) as r:
            txt = await r.text()
            try: data = json.loads(txt) if txt else {}
            except Exception: data = {"raw": txt[:300]}
            if r.status >= 400:
                raise RuntimeError(f"platega {method} {path}: HTTP {r.status} {str(data)[:300]}")
            return data

async def platega_check(tx_id):
    """Не верим телу вебхука: статус и сумму берём из API Platega, план — из нашей pending_pays."""
    st = await platega_req("GET", f"/transaction/{tx_id}")
    status = str(st.get("status") or "").upper()
    if status == "CANCELED":
        pending_done(tx_id); return False
    if status != "CONFIRMED":
        return False
    c = db(); row = c.execute("SELECT tg_id, pid FROM pending_pays WHERE order_id=? AND provider='platega'",
                              (str(tx_id),)).fetchone(); c.close()
    if not row:
        log.error(f"platega: CONFIRMED {tx_id}, но нет в pending_pays — не выдаю"); return False
    tg_id, pid = row
    amount = _num(((st.get("paymentDetails") or {}).get("amount")))
    need = int(PLANS.get(pid, {}).get("rub", 0))
    if amount is None or amount < need:
        log.error(f"platega: {tx_id} сумма {amount} < {need} для {pid} — не выдаю")
        await notify_admins(f"⚠️ Platega: платёж <code>{tx_id}</code> на {amount} ₽ меньше цены плана {pid} ({need} ₽)")
        return False
    return await fulfill_payment(tg_id, pid, "Platega", order_id=str(tx_id), amount=amount)

@dp.callback_query(F.data.startswith("plg:"))
async def cb_pay_platega(q: CallbackQuery):
    try: _, pid, m = q.data.split(":"); m = int(m)
    except Exception: await q.answer(); return
    p = PLANS.get(pid)
    if not platega_ready() or not p or pid == "trial" or m not in PLATEGA_METHODS or not price_ok(p["rub"]):
        await q.answer("Оплата сейчас недоступна", show_alert=True); return
    uid = q.from_user.id
    body = {
        "paymentMethod": m,
        "paymentDetails": {"amount": int(p["rub"]), "currency": "RUB"},
        "description": f"VAYNAH VPN — {p['title']}",
        "return": f"https://t.me/{BOT_USERNAME}",
        "failedUrl": f"https://t.me/{BOT_USERNAME}",
        "payload": f"{uid}:{pid}",
        "metadata": {"user_email": f"{uid}@telegram.org", "userId": str(uid)},
    }
    try:
        res = await platega_req("POST", "/transaction/process", body)
    except Exception as e:
        log.error(f"platega create {uid} {pid}: {e}")
        await q.answer("Платёж временно недоступен, попробуй через минуту", show_alert=True); return
    tx, url = res.get("transactionId"), res.get("redirect")
    if not tx or not url:
        log.error(f"platega create {uid} {pid}: нет ссылки: {str(res)[:300]}")
        await q.answer("Ошибка создания платежа", show_alert=True); return
    pending_add(tx, "platega", uid, pid)
    log_event(uid, "pay_create", f"platega:{pid}:{m}")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💳 Оплатить {p['rub']} ₽", url=f"https://{SUB_DOMAIN}/pay/{tx}", style="success")],
        [InlineKeyboardButton(text="🔄 Я оплатил — проверить", callback_data=f"plgchk:{tx}", style="primary")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="buy", style="primary")]])
    await q.message.edit_text(
        f"🧾 <b>{p['title']}</b>\n💰 К оплате: <b>{p['rub']} ₽</b> · {PLATEGA_METHOD_TITLES.get(m, '')}\n\n"
        f"Нажми «Оплатить». После оплаты подписка включится автоматически за минуту.", reply_markup=kb)
    await q.answer()

@dp.callback_query(F.data.startswith("plgchk:"))
async def cb_platega_check(q: CallbackQuery):
    tx = q.data.split(":", 1)[1]
    c = db(); row = c.execute("SELECT tg_id FROM pending_pays WHERE order_id=? AND provider='platega'", (tx,)).fetchone()
    paid = c.execute("SELECT 1 FROM paid_orders WHERE order_id=?", (tx,)).fetchone(); c.close()
    if not row or row[0] != q.from_user.id:
        await q.answer(); return
    if paid:
        await q.answer("✅ Оплата уже зачислена", show_alert=True); return
    try:
        ok = await platega_check(tx)
    except Exception as e:
        log.error(f"platega check {tx}: {e}"); ok = False
    await q.answer("✅ Оплата прошла!" if ok else "⏳ Оплата ещё не поступила. Если уже оплатил — подожди минуту.",
                   show_alert=not ok)

_PAY_CACHE, _H2H_LINK = {}, {}
_TX_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

async def _platega_tx(tx, ttl=5):
    hit = _PAY_CACHE.get(tx)
    if hit and time.time() - hit[0] < ttl: return hit[1]
    d = await platega_req("GET", f"/transaction/{tx}")
    _PAY_CACHE[tx] = (time.time(), d)
    return d

async def _platega_sbp_link(tx):
    """Ссылка СБП (qr.nspk.ru) — работает, только если менеджер Platega включил H2H. Иначе пусто."""
    if tx in _H2H_LINK: return _H2H_LINK[tx]
    try: u = str((await platega_req("GET", f"/h2h/{tx}")).get("qr") or "")
    except Exception: u = ""
    _H2H_LINK[tx] = u
    return u

def _qr_data_uri(text):
    b = io.BytesIO(); qrcode.make(text, box_size=8, border=1).save(b, format="PNG")
    return "data:image/png;base64," + base64.b64encode(b.getvalue()).decode()

def _pay_row(tx):
    c = db(); r = c.execute("SELECT tg_id, pid FROM pending_pays WHERE order_id=? AND provider='platega'", (tx,)).fetchone(); c.close()
    return r

def _rub(x):
    try: return f"{float(x):.2f}".replace(".", ",").replace(",00", "")
    except Exception: return str(x)

async def pay_page(request):
    tx = request.match_info.get("tx", "").lower()
    row = _pay_row(tx) if _re.fullmatch(_TX_RE, tx) else None
    if not row or not platega_ready():
        return web.Response(status=404, text="not found", headers={"Cache-Control": "no-store"})
    p = PLANS.get(row[1], {})
    try: st = await _platega_tx(tx)
    except Exception as e:
        log.error(f"pay_page {tx}: {e}"); st = {}
    amount = (st.get("paymentDetails") or {}).get("amount") or p.get("rub", 0)
    fee = st.get("comission")
    fee_txt = (f"{p.get('rub')} ₽ + комиссия платёжной системы {_rub(fee)} ₽" if fee else "Включая все комиссии")
    sbp = await _platega_sbp_link(tx)
    target = sbp or f"https://pay.platega.io/p/{tx}?mh={PLATEGA_MERCHANT_ID}"
    page = open("/opt/zpnbot/pay_page.html", encoding="utf-8").read()
    for k, v in {"__PLAN__": _html.escape(p.get("title", "Подписка")), "__AMOUNT__": _rub(amount), "__FEE__": _html.escape(fee_txt),
                 "__URL__": _html.escape(target), "__BTN__": "Открыть приложение банка" if sbp else "Оплатить по СБП",
                 "__QR__": _qr_data_uri(target),
                 "__QRHINT__": ("Отсканируй камерой телефона — откроется приложение банка" if sbp
                                else "Наведи камеру телефона — откроется страница оплаты"),
                 "__TX__": tx, "__BOT__": BOT_USERNAME}.items():
        page = page.replace(k, v)
    return web.Response(text=page, content_type="text/html",
                        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"})

async def pay_status(request):
    tx = request.match_info.get("tx", "").lower()
    row = _pay_row(tx) if _re.fullmatch(_TX_RE, tx) else None
    if not row: return web.json_response({"status": "UNKNOWN"}, status=404, headers={"Cache-Control": "no-store"})
    def paid():
        c = db(); r = c.execute("SELECT 1 FROM paid_orders WHERE order_id=?", (tx,)).fetchone(); c.close(); return bool(r)
    status = "CONFIRMED" if paid() else "PENDING"
    if status != "CONFIRMED":
        try: status = str((await _platega_tx(tx, ttl=4)).get("status") or "PENDING").upper()
        except Exception: status = "PENDING"
        if status == "CONFIRMED":
            try: await platega_check(tx)
            except Exception as e: log.error(f"pay_status check {tx}: {e}")
            if not paid(): status = "PENDING"
    out = {"status": status}
    if status == "CONFIRMED":
        u = get_user(row[0])
        if u and u.get("expires_at"): out["until"] = datetime.fromtimestamp(u["expires_at"]).strftime("%d.%m.%Y")
    return web.json_response(out, headers={"Cache-Control": "no-store"})

async def project_page(request):
    """Публичная страница о проекте (файл читается на каждый запрос — правки без перезапуска)."""
    path = "/opt/zpnbot/web/project.html"
    if not os.path.exists(path):
        return web.Response(status=404, text="not found")
    return web.FileResponse(path, headers={"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-cache",
                                           "X-Robots-Tag": "noindex, nofollow"})

async def static_v(request):
    f = request.match_info.get("f", "")
    path = f"/opt/zpnbot/web/{f}"
    if not _re.fullmatch(r"[a-z0-9_-]{1,40}\.webp", f) or not os.path.exists(path):
        return web.Response(status=404, text="not found")
    return web.FileResponse(path, headers={"Cache-Control": "public, max-age=604800", "Content-Type": "image/webp"})

async def static_p(request):
    """Баннеры авто-рассылок (jpg) — для превью в веб-админке."""
    f = request.match_info.get("f", "")
    path = f"/opt/zpnbot/push/{f}"
    if not _re.fullmatch(r"[a-z0-9_]{1,40}\.jpg", f) or not os.path.exists(path):
        return web.Response(status=404, text="not found")
    return web.FileResponse(path, headers={"Cache-Control": "public, max-age=86400", "Content-Type": "image/jpeg"})

async def platega_webhook(request):
    if not platega_ready():
        return web.Response(status=503, text="not configured")
    import hmac as _hmac
    if not (_hmac.compare_digest(request.headers.get("X-MerchantId", ""), PLATEGA_MERCHANT_ID)
            and _hmac.compare_digest(request.headers.get("X-Secret", ""), PLATEGA_SECRET)):
        return web.Response(status=401, text="unauthorized")
    try: data = await request.json()
    except Exception: return web.Response(text="ok")
    tx = str(data.get("id") or "")
    log.info(f"PLATEGA HOOK: {data.get('status')} {tx} {data.get('amount')}")
    if tx and data.get("status") in ("CONFIRMED", "CANCELED"):
        try: await platega_check(tx)
        except Exception as e:
            log.error(f"platega hook {tx}: {e}"); return web.Response(status=500, text="retry")
    elif data.get("status") in ("CHARGEBACKED", "DISPUTED", "PARTIALLY_REFUNDED"):
        await notify_admins(f"⚠️ Platega: {data.get('status')} по платежу <code>{tx}</code> ({data.get('amount')} ₽)")
    return web.Response(text="ok")


# 16.11.2026: новая концепция — «IngVertu · горная надёжность». Главная = живая карточка статуса.
TAGLINE = "Салам. Мы на связи"
def welcome_text(uid):
    u = get_user(uid)
    now = time.time()
    head = f"🏔 <b>VAYNAH VPN</b>\n<i>{TAGLINE}</i>\n"
    if u and u["expires_at"] and u["expires_at"] > now:
        left = max(0, int((u["expires_at"] - now) / 86400))
        exp = datetime.fromtimestamp(u["expires_at"]).strftime("%d.%m.%Y")
        tname = PLANS.get(u["plan"], {}).get("title", "—").split(" · ")[0]
        bar_full = 10
        filled = max(1, min(bar_full, round(left / 3))) if left else 0
        bar = "▰" * filled + "▱" * (bar_full - filled)
        warn = "\n⚠️ <b>Скоро закончится</b> — продли, чтобы не потерять доступ." if left <= 3 else ""
        body = (f"\n✅ <b>Подписка активна</b>\n"
                f"{bar}  ещё <b>{left}</b> {days_word(left)}\n"
                f"📅 до <b>{exp}</b>" + (f" · 📦 {_html.escape(str(tname))}" if tname and tname != "—" else "") + f"{warn}\n\n"
                f"🇫🇮 🇩🇪 🇳🇱 🇪🇸 · 🔒 защищённое соединение\n")
    elif u and u["expires_at"]:
        body = ("\n⛔ <b>Подписка закончилась</b>\n"
                "Продли — ключ и настройки сохранятся, всё заработает сразу.\n\n"
                "🇫🇮 🇩🇪 🇳🇱 🇪🇸 · высокая скорость\n")
    else:
        body = ("\n👋 <b>Добро пожаловать!</b>\n"
                "Быстрый и защищённый VPN с серверами в Европе.\n"
                "⚡ Подключение за 1 минуту · 📱 Happ / INCY\n\n"
                "🇫🇮 🇩🇪 🇳🇱 🇪🇸 · высокая скорость\n")
    return head + body + "\n<b>Выбери действие</b> 👇"

WELCOME = ("⚡️ <b>VAYNAH VPN</b>\n"
           "<i>Твоё соединение — под рукой</i>\n\n"
           "🔑 Подписка и подключение к VPN\n"
           "📱 Управление устройствами и поддержка\n"
           "📶 Платные тарифы: 50 ГБ на оплаченный период\n\n"
           "<b>Выбери действие ниже</b> 👇")

HELP = ("📖 <b>Как подключить VAYNAH VPN</b>\n\n"
        "1️⃣ <b>Установи Happ или INCY</b> (happ.su или incy.cc)\n"
        "2️⃣ <b>Открой «🔑 Моя подписка»</b> → выбери кнопку приложения.\n"
        "      В INCY включи отправку HWID и подтверди добавление.\n"
        "      Или скопируй ссылку → в INCY нажми «Вставить».\n"
        "3️⃣ <b>Выбери 🇫🇮 Финляндия · ⚡ Быстрый</b> и нажми кнопку включения\n\n"
        f"{APPS}\n\n"
        "💡 <b>Если что-то не так</b>\n"
        "• Не открывается сайт — выбери другую страну\n"
        "• Тормозит видео — включи в Happ <b>Fake DNS</b>\n"
        "• Список серверов устарел — обнови подписку 🔄 в приложении\n"
        "• В INCY нет серверов — включи отправку HWID и обнови подписку\n\n"
        "💬 Не получилось? Пиши в техподдержку @helpingvpn или в «💬 Поддержка» в боте")

def terms_text():
    ip = PLANS["intro"]
    ap = (f"🔥 <b>Старт:</b> {ip['days']} {days_word(ip['days'])} за {ip['rub']} ₽ — разовая оплата для новых пользователей "
          "(один раз на аккаунт), без подписок и автосписаний. Дальше — продление по обычным тарифам.\n\n") if intro_ready() else ""
    return TERMS.replace("{AUTOPAY}", ap).replace("{TRIAL}", (
        f"🎁 <b>Пробный период:</b> {trial_days()} {days_word(trial_days())} бесплатно — проверь сервис до оплаты.\n\n"
        if free_trial_visible() else ""))

TERMS = ("📄 <b>Пользовательское соглашение и политика конфиденциальности VAYNAH VPN</b>\n\n"
         "<b>1. Сервис.</b> VAYNAH VPN — платный сервис защищённого VPN-соединения. Мы шифруем трафик между вашим "
         "устройством и нашими серверами в 🇫🇮 Финляндии, 🇩🇪 Германии, 🇳🇱 Нидерландах и 🇪🇸 Испании, чтобы защитить "
         "ваши данные в публичных Wi-Fi и сетях операторов и сохранить приватность в интернете.\n\n"
         "<b>2. Доступ.</b> Доступ выдаётся по подписке на выбранный срок с лимитом трафика тарифа. "
         "Ключ и ссылка-подписка приходят в этот бот сразу после активации и предназначены только для ваших устройств "
         "в пределах лимита тарифа. Передавать доступ третьим лицам нельзя.\n\n"
         "<b>3. Оплата.</b> Оплата — за выбранный период (картой, СБП, Telegram Stars, криптовалютой). "
         "По окончании срока доступ приостанавливается и продлевается новой оплатой.\n\n"
         "{AUTOPAY}"
         "{TRIAL}"
         "<b>4. Возврат.</b> Если после оплаты сервис не работает по нашей вине и поддержка не смогла помочь — "
         "вернём деньги за неиспользованный период в течение 24 часов после обращения.\n\n"
         "<b>5. Запрещено.</b> Использовать сервис для действий, нарушающих закон; рассылки спама; атак на сети и "
         "устройства (DDoS, сканирование, взлом); распространения вредоносного ПО и материалов, нарушающих права других; "
         "торрент-раздач в промышленных объёмах. При нарушении доступ блокируется без возврата средств.\n\n"
         "<b>6. Конфиденциальность.</b> Мы <b>не ведём логи</b> посещаемых сайтов и содержимого трафика. "
         "Храним только необходимое для работы: Telegram ID и имя в Telegram, срок подписки, объём использованного "
         "трафика, число подключённых устройств и факты оплаты. Данные не продаём и не передаём третьим лицам, "
         "кроме случаев, прямо предусмотренных законом. Удалить свои данные можно через поддержку.\n\n"
         "<b>7. Ответственность.</b> Сервис предоставляется «как есть». Мы делаем всё для стабильной работы, "
         "но не отвечаем за перебои у вашего провайдера и за то, как вы используете интернет через сервис.\n\n"
         "<b>8. Изменения.</b> Условия могут обновляться — актуальная версия всегда доступна по команде /terms.\n\n"
         "💬 <b>Поддержка:</b> @helpingvpn или кнопка «💬 Поддержка» в боте.\n\n"
         "📄 Полные тексты: <a href=\"https://sub.vertuwpn.ru/terms\">Пользовательское соглашение</a> · "
         "<a href=\"https://sub.vertuwpn.ru/privacy\">Политика конфиденциальности</a> · "
         "<a href=\"https://sub.vertuwpn.ru/tariffs\">Тарифы и цены</a>")

async def issue_key(tg_id, plan):
    if not ACCESS_ISSUANCE_ENABLED:
        raise RuntimeError("VPN access issuance is disabled until the new panel and nodes are configured")
    p = PLANS[plan]
    u = get_user(tg_id)
    uuid_ = u["uuid"] if (u and u["uuid"]) else str(uuid.uuid4())
    base = max(time.time(), (u["expires_at"] if u and u["expires_at"] else 0))
    expires = int(base + p["days"] * 86400)
    failed = await asyncio.to_thread(xray_add_client, uuid_)
    upsert_user(tg_id, uuid_, plan, expires,
                trial_used=1 if plan in ("trial", "channel_trial") else None)
    db_set(tg_id, revoked=0, rem3=0, rem1=0, rem3h=0, needs_sync=1 if failed else 0)
    if plan not in ("trial", "channel_trial"):   # оплата = новые 50 ГБ (rw_sync обнулит трафик и снимет LIMITED)
        db_set(tg_id, tr_reset=1, lim_notified=0)
    if failed:
        log.error(f"issue_key: user {tg_id} НЕ добавлен на {failed} — sync_worker дожмёт")
    await asyncio.to_thread(rw_sync_now, tg_id)  # 03.11.2026: сразу создать/продлить в панели
    if plan in ("trial", "channel_trial"):
        db_set(tg_id, trial_at=int(time.time()))
    if plan not in ("trial", "channel_trial"):   # 25.11.2026: пробный по ссылке — не оплата
        c = db()
        row = c.execute("SELECT first_paid_at, pay_count FROM users WHERE tg_id=?", (tg_id,)).fetchone()
        fpa = row[0] if (row and row[0]) else int(time.time())
        pc = (row[1] if (row and row[1]) else 0) + 1
        c.execute("UPDATE users SET first_paid_at=?, pay_count=? WHERE tg_id=?", (fpa, pc, tg_id))
        c.commit(); c.close()
    return uuid_, expires


# ---------- Публичный deep-link free2: 2 дня после подписки на канал ----------
_CHANNEL_TRIAL_LOCK = asyncio.Lock()

async def maybe_issue_channel_trial(uid):
    """Выдать 48-часовой trial только пользователю, пришедшему по free2 и прошедшему gate."""
    if not onboard_done(uid):
        return False
    state = urow(uid, "COALESCE(channel_trial_requested,0), COALESCE(channel_trial_issued,0)")
    if not state or not state[0] or state[1]:
        return False
    if gate_on() and not is_admin(uid) and not await is_subscribed(uid, fresh=True):
        return False
    async with _CHANNEL_TRIAL_LOCK:
        state = urow(uid, "COALESCE(channel_trial_requested,0), COALESCE(channel_trial_issued,0)")
        if not state or not state[0] or state[1]:
            return False
        u = get_user(uid)
        if u and u.get("trial_used"):
            db_set(uid, channel_trial_issued=1)
            await bot.send_message(uid, "🎁 Пробный период уже был использован для этого аккаунта.")
            return True
        if u and u.get("expires_at") and u["expires_at"] > time.time():
            db_set(uid, channel_trial_issued=1)
            await bot.send_message(uid, "✅ У тебя уже есть активная подписка — новый trial не требуется.")
            return True
        try:
            uuid_, exp = await issue_key(uid, "channel_trial")
            db_set(uid, channel_trial_issued=1)
            log_event(uid, "channel_trial_issued", "48h")
            await deliver_key(uid, uuid_, "🎁 <b>Готово! Тебе выдан бесплатный доступ на 2 дня.</b>")
            return True
        except Exception as e:
            log.error(f"channel trial issue {uid}: {type(e).__name__}: {e}")
            await bot.send_message(uid, "⚠️ Не удалось выдать пробный доступ автоматически. Напиши в поддержку.")
            return True

# ---------- 16.11.2026: онбординг — капча «горы Кавказа» + принятие соглашения ----------
import random as _rnd
CAPTCHA_SET = [("🏔", "горы"), ("🐎", "коня"), ("🦅", "орла"), ("🌙", "луну"), ("⭐", "звезду"), ("☀️", "солнце"),
               ("🌲", "ёлку"), ("🍎", "яблоко"), ("🌊", "волну"), ("🔥", "огонь"), ("🏹", "лук"), ("🛡", "щит")]
CAPTCHA = {}   # uid -> {"t": target_idx, "fails": n, "until": ts}

def onboard_done(uid):
    if is_admin(uid): return True
    r = urow(uid, "COALESCE(captcha_ok,0), COALESCE(terms_at,0)")
    return bool(r) and bool(r[0]) and bool(r[1])

def _captcha_kb(uid):
    st = CAPTCHA.setdefault(uid, {"fails": 0, "until": 0})
    opts = _rnd.sample(range(len(CAPTCHA_SET)), 6)
    st["t"] = _rnd.choice(opts)
    rows = [[InlineKeyboardButton(text=CAPTCHA_SET[k][0], callback_data=f"cap:{k}") for k in opts[r*3:(r+1)*3]] for r in range(2)]
    return st["t"], InlineKeyboardMarkup(inline_keyboard=rows)

def _captcha_text(t, note=""):
    e, name = CAPTCHA_SET[t]
    return ("🏔 <b>VAYNAH VPN</b>\n<i>Надёжно, как башни Ингушетии</i>\n\n"
            "🤖 <b>Подтверди, что ты человек</b>\n"
            f"Нажми на кнопку, где изображено <b>{name}</b> {e}" + (f"\n\n{note}" if note else ""))

async def send_captcha(chat_id, uid, note=""):
    t, kb = _captcha_kb(uid)
    await bot.send_message(chat_id, _captcha_text(t, note), reply_markup=kb)

TERMS_SHORT = ("✅ <b>Готово, ты человек!</b>\n\n"
               "📄 <b>Перед началом — коротко о правилах</b>\n"
               "• VAYNAH VPN — сервис защищённого VPN-соединения для приватности и безопасности в сети\n"
               "• Запрещено использовать сервис для нарушения закона, спама, атак и вредоносного ПО\n"
               "• Мы не храним логи сайтов и трафика — только данные, нужные для подписки\n"
               "• Доступ — только для твоих устройств, передавать его нельзя\n\n"
               "Нажимая «Принимаю», ты соглашаешься с <a href=\"https://sub.vertuwpn.ru/terms\">Пользовательским соглашением</a> и "
               "<a href=\"https://sub.vertuwpn.ru/privacy\">Политикой конфиденциальности</a>.\n"
               "💬 Поддержка: @helpingvpn")

def terms_accept_kb(full=False):
    rows = [[InlineKeyboardButton(text="✅ Принимаю и продолжаю", callback_data="tos:ok", style="success")]]
    rows.append([InlineKeyboardButton(text="📄 Соглашение", url="https://sub.vertuwpn.ru/terms"),
                 InlineKeyboardButton(text="🔒 Конфиденциальность", url="https://sub.vertuwpn.ru/privacy")])
    rows.append([InlineKeyboardButton(text="⬅️ Кратко" if full else "📖 Условия в боте", callback_data="tos:short" if full else "tos:full")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@dp.callback_query(F.data.startswith("cap:"))
async def cb_captcha(q: CallbackQuery):
    uid = q.from_user.id
    st = CAPTCHA.setdefault(uid, {"fails": 0, "until": 0})
    if st.get("until", 0) > time.time():
        await q.answer(f"⏳ Слишком много попыток. Подожди {int(st['until'] - time.time())} сек.", show_alert=True); return
    try: k = int(q.data.split(":")[1])
    except Exception: k = -1
    if "t" in st and k == st["t"]:
        db_set(uid, captcha_ok=1); CAPTCHA.pop(uid, None); log_event(uid, "captcha_ok")
        await q.answer("✅ Верно!")
        try: await q.message.edit_text(TERMS_SHORT, reply_markup=terms_accept_kb())
        except Exception: await q.message.answer(TERMS_SHORT, reply_markup=terms_accept_kb())
        return
    st["fails"] = st.get("fails", 0) + 1
    if st["fails"] >= 5:
        st["until"] = time.time() + 60; st["fails"] = 0
    t, kb = _captcha_kb(uid)
    await q.answer("❌ Не то — попробуй ещё раз")
    try: await q.message.edit_text(_captcha_text(t, "❌ Неверно, новое задание 👆"), reply_markup=kb)
    except Exception: pass

@dp.callback_query(F.data.startswith("tos:"))
async def cb_tos(q: CallbackQuery):
    uid = q.from_user.id
    act = q.data.split(":")[1]
    if act == "full":
        await q.message.edit_text(terms_text(), reply_markup=terms_accept_kb(full=True)); await q.answer(); return
    if act == "short":
        await q.message.edit_text(TERMS_SHORT, reply_markup=terms_accept_kb()); await q.answer(); return
    if act == "ok":
        r = urow(uid, "COALESCE(captcha_ok,0)")
        if not (r and r[0]) and not is_admin(uid):
            await q.answer(); await send_captcha(q.message.chat.id, uid); return
        db_set(uid, terms_at=int(time.time())); log_event(uid, "terms_ok")
        await q.answer("Добро пожаловать! 🏔")
        try: await q.message.delete()
        except Exception: pass
        try: await bot.send_message(uid, "🏔 <b>VAYNAH VPN</b>", reply_markup=REPLY_KB)
        except Exception: pass
        await bot.send_message(uid, welcome_text(uid), reply_markup=main_menu(uid))

async def onboard_gate(chat_id, uid):
    """True = пользователь ещё не прошёл капчу/соглашение — показали нужный шаг."""
    if onboard_done(uid): return False
    r = urow(uid, "COALESCE(captcha_ok,0)")
    if r and r[0]:
        await bot.send_message(chat_id, TERMS_SHORT.replace("✅ <b>Готово, ты человек!</b>\n\n", ""), reply_markup=terms_accept_kb())
    else:
        await send_captcha(chat_id, uid)
    return True

@dp.message(Command("terms"))
async def msg_terms(m: Message):
    ensure_user(m.from_user.id)
    await m.answer(terms_text(), reply_markup=main_menu(m.from_user.id))


# ---------- 16.11.2026: требования банка/платёжки — документы всегда под рукой, лимит 10 000 ₽ ----------
MAX_TX_RUB = 10000          # лимит провайдера на одну транзакцию
DOCS_BTN = "📄 Документы"
def docs_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Пользовательское соглашение", url="https://sub.vertuwpn.ru/terms")],
        [InlineKeyboardButton(text="🔒 Политика конфиденциальности", url="https://sub.vertuwpn.ru/privacy")],
        [InlineKeyboardButton(text="💳 Тарифы и цены", url="https://sub.vertuwpn.ru/tariffs")],
        [InlineKeyboardButton(text="👤 Техподдержка @helpingvpn", url="https://t.me/helpingvpn")],
        [InlineKeyboardButton(text="🏠 Меню", callback_data="menu")]])
DOCS_TXT = ("📄 <b>Документы VAYNAH VPN</b>\n\n"
            "• Пользовательское соглашение\n• Политика конфиденциальности\n• Тарифы и цены\n\n"
            "💬 Техподдержка: @helpingvpn")

@dp.callback_query(F.data == "docs")
async def cb_docs(q: CallbackQuery):
    await q.answer(); await smart_edit(q, DOCS_TXT, docs_kb())

@dp.message(F.text == DOCS_BTN)
@dp.message(Command("docs"))
async def msg_docs(m: Message):
    await m.answer(DOCS_TXT, reply_markup=docs_kb())

def price_ok(rub):
    try: return 0 < float(rub) <= MAX_TX_RUB
    except Exception: return False


# ======================= VAYNAH-INTEGRATION (16.11.2026): персонаж VAYNAH BRO, HTML-виджеты, Rich Messages =======================
import ghal as _ghal
import random
_GHAL_LAST = {}   # uid -> ts последнего виджета (антиспам)

def _ghal_status(uid):
    u = get_user(uid); now = time.time()
    if u and u["expires_at"] and u["expires_at"] > now:
        p = PLANS.get(u["plan"], {})
        return dict(active=True, days=max(0, int((u["expires_at"] - now) / 86400)), total_days=p.get("days") or 30,
                    exp=datetime.fromtimestamp(u["expires_at"]).strftime("%d.%m.%Y"),
                    plan=(p.get("title") or "—").split(" · ")[0] + (" · " + p["title"].split(" · ")[1] if " · " in (p.get("title") or "") else ""),
                    devices=f"до {p.get('devices', 3)}")
    if u and u["expires_at"]:
        return dict(active=False, expired=True)
    return dict(active=False)

def _ghal_home_caption(uid, name):
    st = _ghal_status(uid)
    if st.get("active"): line = f"✅ Подписка активна · ещё <b>{st['days']}</b> {days_word(st['days'])}"
    elif st.get("expired"): line = "⛔ Подписка закончилась — продлим?"
    else: line = "👋 Подключись за минуту — серверы в Европе"
    return f"🏔 <b>VAYNAH VPN</b> · <i>{_ghal.SLOGAN}</i>\n{line}"

async def send_home(chat_id, uid, name):
    await bot.send_message(chat_id, welcome_text(uid), reply_markup=main_menu(uid))
async def _ghal_send(chat_id, uid, kind, name=""):
    await bot.send_message(chat_id, welcome_text(uid), reply_markup=main_menu(uid))
async def rich_plans(chat_id):
    rows = "".join(f"<tr><td>{_html.escape(p['title'].split(' · ')[0])}</td><td>{_html.escape(p['title'].split(' · ')[1]) if ' · ' in p['title'] else ''}</td>"
                   f"<td align=\"right\"><b>{p['rub']} ₽</b></td><td align=\"right\">{p.get('devices', 3)}</td></tr>"
                   for pid, p in PLANS.items() if pid not in ("trial", "intro"))
    btns = "".join(f'<tg-button type="callback_data" data="plan:{pid}" style="{"success" if pid == "1m" else "primary"}">'
                   f'{_html.escape(PLANS[pid]["title"])} — {PLANS[pid]["rub"]} ₽</tg-button>' for pid in ("1m", "3m", "12m", "fam_1m") if pid in PLANS)
    htm = (f"<h2>Тарифы VAYNAH VPN</h2><p>Салам! Любой тариф — <b>50 ГБ</b>, серверы 🇫🇮 🇩🇪 🇳🇱 🇪🇸, без логов. "
           f"Одна оплата не больше 10 000 ₽.</p><table bordered striped><tr><th>Тариф</th><th>Период</th><th>Цена</th><th>Устройств</th></tr>{rows}</table>"
           f"<hr/>{btns}<footer>Соглашение и условия возврата: sub.vertuwpn.ru/terms</footer>")
    try: await _ghal.send_rich(chat_id, htm)
    except Exception as e:
        log.error(f"rich plans: {e}"); txt, kb = buy_screen(chat_id); await bot.send_message(chat_id, txt, reply_markup=kb)

async def rich_howto(chat_id):
    htm = ("<h2>Как подключить VAYNAH VPN</h2><ol><li><b>Установи Happ</b> — App Store или Google Play.</li>"
           "<li>В боте нажми <b>«🔑 Подключить VPN»</b> → «Подключить в Happ». Подписка добавится сама.</li>"
           "<li>Выбери <b>🇫🇮 Финляндия · Быстрый</b> и включи.</li></ol>"
           "<details><summary>Не работает?</summary><ul><li>Выбери другую страну.</li><li>Обнови подписку ⟳ в Happ.</li>"
           "<li>Включи Fake DNS, если тормозит видео.</li></ul></details>"
           "<blockquote>Не переживай, брат, я рядом. Пиши @helpingvpn 😉</blockquote>"
           '<tg-button-row><tg-button type="callback_data" data="my" style="success">Подключить VPN</tg-button>'
           '<tg-button type="callback_data" data="sup:write">Написать в поддержку</tg-button></tg-button-row>')
    try: await _ghal.send_rich(chat_id, htm)
    except Exception as e: log.error(f"rich howto: {e}"); await bot.send_message(chat_id, HELP, reply_markup=main_menu(chat_id))

async def rich_history(chat_id, uid):
    c = db(); rows = c.execute("SELECT ts, pid, provider, amount_rub FROM payments WHERE tg_id=? ORDER BY ts DESC LIMIT 15", (uid,)).fetchall(); c.close()
    if rows:
        tr = "".join(f"<tr><td>{datetime.fromtimestamp(r[0]).strftime('%d.%m.%Y')}</td><td>{_html.escape(PLANS.get(r[1], {}).get('title', r[1] or ''))}</td>"
                     f"<td>{_html.escape(str(r[2] or ''))}</td><td align=\"right\"><b>{int(r[3] or 0)} ₽</b></td></tr>" for r in rows)
        body = f"<table bordered striped><tr><th>Дата</th><th>Тариф</th><th>Способ</th><th>Сумма</th></tr>{tr}</table>"
    else:
        body = "<p>Оплат пока не было. Как оформишь — всё будет тут, брат.</p>"
    htm = f"<h2>История платежей</h2>{body}<footer>Вопросы по оплате: @helpingvpn</footer>"
    try: await _ghal.send_rich(chat_id, htm)
    except Exception as e: log.error(f"rich history: {e}"); await bot.send_message(chat_id, "История платежей временно недоступна.")

GHAL_CONSENT = ("🤖 <b>MY VAYNAH — персональный VAYNAH BRO</b>\n\n"
                "Сделаю VAYNAH BRO с твоим лицом из фото профиля Telegram.\n"
                "• Возьму только текущую аватарку и сделаю маленький портрет 72×72\n"
                "• Оригинал не сохраняю, портрет виден только тебе в виджетах\n"
                "• Удалить можно в любой момент — кнопкой «Стандартный VAYNAH»\n\n"
                "Согласен на обработку фото?")

async def ghal_widget_query(wq):
    uid = wq["from"]["id"]; name = wq["from"].get("first_name") or "брат"; data = wq.get("data", ""); chat = (wq.get("chat") or {}).get("id") or uid
    ans = ""
    try:
        if data == "vpn":
            u = get_user(uid)
            if u and u["uuid"] and u["expires_at"] and u["expires_at"] > time.time():
                ans = "Держи ключ ниже 👇"; await deliver_key(chat, u["uuid"], "🟢 <b>VAYNAH VPN</b> · держи подключение, брат")
            else:
                ans = "Подписки нет — открыл магазин 👇"; await _ghal_send(chat, uid, "store")
        elif data in ("store", "sub", "prof", "ref", "help"):
            ans = {"store": "Магазин ниже 👇", "sub": "Подписка ниже 👇", "prof": "Профиль ниже 👇", "ref": "Друзья ниже 👇", "help": "Я тут 👇"}[data]
            await _ghal_send(chat, uid, data, name)
        elif data.startswith("buy:"):
            pid = data.split(":", 1)[1]
            if pid in PLANS and price_ok(PLANS[pid]["rub"]):
                p = PLANS[pid]; ans = "Вай, отличный выбор! 👇"
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"💳 Оформить · {p['rub']} ₽", callback_data=f"plan:{pid}", style="success")],
                                                           [InlineKeyboardButton(text="📋 Тарифы и условия", url="https://sub.vertuwpn.ru/tariffs")]])
                await bot.send_message(chat, f"🛍 <b>{_html.escape(p['title'])}</b>\n{p['days']} {days_word(p['days'])} · до {p.get('devices', 3)} устройств · 50 ГБ\n\nЦена: <b>{p['rub']} ₽</b>", reply_markup=kb)
        elif data == "plans":
            ans = "Все тарифы ниже 👇"; await rich_plans(chat)
        elif data == "howto":
            ans = "Инструкция ниже 👇"; await rich_howto(chat)
        elif data == "noconn":
            ans = "Вай, сейчас разберёмся 😅"; await bot.send_message(chat, "<b>🌐 Подключился, но не работает?</b>\n\n" + SUPPORT_TOPICS["noint"][1], reply_markup=support_menu())
        elif data == "tip":
            ans = random.choice(_ghal.TIPS)
        elif data == "oper":
            pending[uid] = ("support_msg",); ans = "Пиши вопрос в чат ✍️"
            await bot.send_message(chat, "✍️ <b>Напиши вопрос одним сообщением</b> — передам оператору. Или сразу: @helpingvpn")
        elif data == "refinfo":
            txt, kb = ref_screen(uid); ans = "Рассказал ниже 👇"
            if os.path.exists(REF_BANNER_PATH):
                await bot.send_photo(chat, BufferedInputFile(open(REF_BANNER_PATH, "rb").read(), "vaynah-referral.png"), caption=txt, reply_markup=kb)
            else:
                await bot.send_message(chat, txt, reply_markup=kb)
        elif data == "myghal":
            ans = "Нужно твоё согласие 👇"
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Согласен, сделай MY VAYNAH", callback_data="ghal:yes", style="success")],
                                                       [InlineKeyboardButton(text="Нет, оставь стандартного", callback_data="ghal:no")]])
            await bot.send_message(chat, GHAL_CONSENT, reply_markup=kb)
        elif data == "stdghal":
            _ghal.drop_face(uid); log_event(uid, "ghal_std"); ans = "Готово: стандартный GHAL, фото удалено"
    except Exception as e:
        log.error(f"ghal query {data}: {e}"); ans = "Вай, что-то пошло не так. Попробуй ещё раз"
    await _ghal.answer_query(wq["id"], ans)

@dp.callback_query(F.data.startswith("ghal:"))
async def cb_ghal(q: CallbackQuery):
    await q.answer("Этот раздел удалён. Открываю главное меню.", show_alert=True)
    try:
        await q.message.edit_text(welcome_text(q.from_user.id), reply_markup=main_menu(q.from_user.id))
    except Exception:
        pass
@dp.message(Command("history"))
async def msg_history(m: Message):
    await rich_history(m.chat.id, m.from_user.id)

# ---------- handlers ----------
@dp.message(CommandStart())
async def start(m: Message, command: CommandObject):
    pending.pop(m.from_user.id, None)            # /start = отмена любого незавершённого ввода
    is_new = get_user(m.from_user.id) is None
    ensure_user(m.from_user.id)
    uid = m.from_user.id
    _TOUCH.pop(uid, None)
    if (command.args or "").strip().lower() in ("free2", "trial2", "channel2"):
        db_set(uid, channel_trial_requested=1)
        log_event(uid, "channel_trial_requested")
    try: await asyncio.to_thread(touch_user, m.from_user)
    except Exception: pass
    if is_new:
        log_event(uid, "start", (command.args or "")[:64])
        if command.args and command.args.isdigit():
            set_referrer(uid, int(command.args))   # рефералка — только для НОВЫХ пользователей
        elif command.args and command.args != "buy":
            db_set(uid, src=command.args[:64])      # метка источника (реклама/посевы) для воронки
    if not onboard_done(uid):                     # 16.11.2026: капча + соглашение до всего остального
        if is_new:
            asyncio.create_task(notify_new_user(m.from_user, command.args))
        await onboard_gate(m.chat.id, uid); return
    if gate_on() and not is_admin(uid) and not await is_subscribed(uid, fresh=True):
        # Не отправляем LOGO_PATH здесь: media upload в Telegram зависал и задерживал /start.
        await m.answer(GATE_TXT, reply_markup=gate_kb())
        if is_new:
            asyncio.create_task(notify_new_user(m.from_user, command.args))
        return
    if await maybe_issue_channel_trial(uid):
        return
    if is_new and not gate_on():
        asyncio.create_task(ref_qualify(uid))
    if command.args == "buy" and not is_new:     # «Продлить» из личного кабинета → сразу тарифы
        if intro_first_only(uid):
            await m.answer(intro_text(), reply_markup=intro_kb()); return
        txt, kb = buy_screen(uid)
        await m.answer(txt, reply_markup=kb)
        return
    if command.args == "devices" and not is_new:
        r = await rw_devices(uid)
        if r:
            txt, kb = devices_screen(r[0], r[1])
            await m.answer(txt, reply_markup=kb)
        else:
            await m.answer("📲 Не удалось загрузить устройства. Открой подписку в боте и попробуй ещё раз.", reply_markup=main_menu(uid))
        return
    # Не блокируем /start загрузкой фото: при проблемном Telegram media upload
    # старый вариант зависал на 55–70 секунд. Быстрый текстовый ответ всегда первым.
    try:
        await m.answer("🏔 <b>VAYNAH VPN</b> · Салам. Мы на связи", reply_markup=REPLY_KB)
    except Exception as e:
        log.error(f"start greeting: {e}")
    await bot.send_message(m.chat.id, welcome_text(m.from_user.id), reply_markup=main_menu(m.from_user.id))
    if is_new:
        asyncio.create_task(notify_new_user(m.from_user, command.args))

async def smart_edit(q, text, reply_markup=None):
    """Правит текст сообщения; если это фото/подпись (Telegram 400) — шлёт новым сообщением.
    Нужно потому, что ключ отдаётся фото-QR, а кнопки «Меню/Как подключить» под ним ведут на edit_text."""
    try:
        await q.message.edit_text(text, reply_markup=reply_markup)
    except Exception:
        try: await q.message.answer(text, reply_markup=reply_markup)
        except Exception as e: log.error(f"smart_edit: {e}")

@dp.callback_query(F.data == "menu")
async def cb_menu(q: CallbackQuery):
    await q.answer()
    if await onboard_gate(q.message.chat.id, q.from_user.id): return
    await smart_edit(q, welcome_text(q.from_user.id), main_menu(q.from_user.id))

def buy_screen(uid=None, full=False):
    rows = [[InlineKeyboardButton(text="📦 Стандарт — до 3 устройств", callback_data="tier:std", style="primary")],
            [InlineKeyboardButton(style="primary", text="👨‍👩‍👧‍👦 Семейный — до 5 устройств", callback_data="tier:fam")],
            [InlineKeyboardButton(text="📋 Тарифы и условия", url="https://sub.vertuwpn.ru/tariffs")],
            [InlineKeyboardButton(style="primary", text="🏠 Меню", callback_data="menu")]]
    if uid and intro_ready() and intro_eligible(uid):
        ip = PLANS["intro"]
        rows.insert(0, [InlineKeyboardButton(style="primary", text=f"🔥 Старт: {ip['days']} {days_word(ip['days'])} за {ip['rub']} ₽", callback_data="intro")])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    return f"{BANNER}\n📋 <b>Выбери тариф</b> — на любом <b>50 ГБ</b> трафика, высокая скорость:", kb

@dp.callback_query(F.data == "buy")
async def cb_buy(q: CallbackQuery):
    if intro_first_only(q.from_user.id):
        log_event(q.from_user.id, "intro_view")
        await smart_edit(q, intro_text(), intro_kb()); await q.answer(); return
    txt, kb = buy_screen(q.from_user.id)
    await smart_edit(q, txt, kb); await q.answer()

@dp.callback_query(F.data.startswith("tier:"))
async def cb_tier(q: CallbackQuery):
    tier = q.data.split(":")[1]
    name = "📦 <b>Стандарт</b> · до 3 устройств" if tier == "std" else "👨‍👩‍👧‍👦 <b>Семейный</b> · до 5 устройств"
    await q.message.edit_text(f"{BANNER}\n{name}\n📋 Выбери срок — <b>50 ГБ</b> трафика на период:",
                              reply_markup=plans_menu(tier, q.from_user.id)); await q.answer()

@dp.callback_query(F.data == "help")
async def cb_help(q: CallbackQuery):
    await smart_edit(q, HELP, main_menu(q.from_user.id)); await q.answer()

@dp.callback_query(F.data == "terms")
async def cb_terms(q: CallbackQuery):
    await smart_edit(q, terms_text(), main_menu(q.from_user.id)); await q.answer()

# ---------- поддержка (структурная, как в Грамбите) ----------
SUPPORT_TOPICS = {
    "ios": ("📱 iPhone / iPad",
            "1. Установи <b>Streisand</b> или <b>Happ</b> (App Store).\n"
            "2. Скопируй ссылку-подписку («🔑 Моя подписка»).\n"
            "3. В приложении: «+» → «Добавить из буфера».\n"
            "4. Разреши VPN-профиль, когда попросит.\n"
            "5. Выбери сервер VAYNAH VPN и включи 🚀"),
    "android": ("🤖 Android",
            "1. Установи <b>v2rayNG</b> или <b>Hiddify</b>.\n"
            "2. Скопируй ссылку-подписку.\n"
            "3. «+» → «Импорт из буфера» → обнови подписку.\n"
            "4. Выбери сервер VAYNAH VPN → кнопка подключения 🚀"),
    "windows": ("🪟 Windows",
            "1. Установи <b>Hiddify</b> или <b>v2rayN</b>.\n"
            "2. Скопируй ссылку-подписку.\n"
            "3. Добавь подписку по ссылке.\n"
            "4. Выбери сервер VAYNAH VPN → Connect 🚀"),
    "mac": ("🍏 macOS",
            "1. Установи <b>V2Box</b> или <b>Streisand</b>.\n"
            "2. Скопируй ссылку-подписку.\n"
            "3. Добавь подписку → разреши VPN-профиль.\n"
            "4. Выбери сервер VAYNAH VPN → включи 🚀"),
    "noint": ("🌐 Подключился, но интернета нет",
            "Попробуй по порядку:\n"
            "1. Переключи <b>сервер</b> в приложении (🇩🇪 DE / 🇳🇱 NL / 🇫🇮 FI).\n"
            "2. Включи <b>Fake DNS</b> в настройках приложения.\n"
            "3. Переподключись (выкл → вкл).\n"
            "4. Проверь, что подписка активна («🔑 Моя подписка»)."),
    "slow": ("🐌 Медленная скорость",
            "1. Выбери сервер <b>🇫🇮 Финляндия</b> — ближе к РФ, быстрее.\n"
            "2. Проверь свой интернет без VPN.\n"
            "3. Переподключись или смени локацию.\n"
            "4. Включи <b>Fake DNS</b>."),
}

def support_menu():
    kb = [
        [InlineKeyboardButton(style="primary", text="📱 Не подключается — iPhone", callback_data="sup:ios")],
        [InlineKeyboardButton(style="primary", text="🤖 Не подключается — Android", callback_data="sup:android")],
        [InlineKeyboardButton(style="primary", text="🪟 Не подключается — Windows", callback_data="sup:windows")],
        [InlineKeyboardButton(style="primary", text="🍏 Не подключается — Mac", callback_data="sup:mac")],
        [InlineKeyboardButton(style="primary", text="🌐 Нет интернета", callback_data="sup:noint")],
        [InlineKeyboardButton(style="primary", text="🐌 Медленно", callback_data="sup:slow")],
        [InlineKeyboardButton(style="success", text="✍️ Написать в поддержку", callback_data="sup:write")],
        [InlineKeyboardButton(text="👤 Техподдержка @helpingvpn", url="https://t.me/helpingvpn")],
        [InlineKeyboardButton(style="primary", text="🏠 Меню", callback_data="menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.callback_query(F.data == "status")
async def cb_status(q: CallbackQuery):
    lines = ["<b>🟢 Статус VAYNAH VPN</b>", ""]
    if RW_API and RW_TOKEN and not NODES:
        try:
            _nodes = (await asyncio.to_thread(_rw_call, "GET", "/nodes")).get("response") or []
        except Exception:
            _nodes = []
        _flag = {"FI": "🇫🇮", "ES": "🇪🇸", "DE": "🇩🇪", "NL": "🇳🇱", "RU": "🇷🇺"}
        for n in _nodes:
            if n.get("isDisabled"): continue
            ok = n.get("isConnected") and n.get("isXrayRunning", True)
            cc = (n.get("countryCode") or "").upper()
            lines.append(f"{_flag.get(cc, '🌐')} {_html.escape(n.get('name',''))}: {'🟢 работает' if ok else '🔴 недоступен'}")
        if not _nodes:
            lines.append("⚪ статус серверов временно недоступен")
    else:
        for n in NODES:
            host = n["ssh"] or n["host"]
            up = await asyncio.to_thread(_tcp_up, host, n["port"])
            lines.append(f"{n['name']}: {'🟢 работает' if up else '🔴 недоступен'}")
    u = get_user(q.from_user.id)
    if u and u["expires_at"] and u["expires_at"] > time.time():
        left = int((u["expires_at"] - time.time()) / 86400)
        lines.append(f"\n✅ Твоя подписка активна — осталось {left} дн.")
    else:
        lines.append("\n⚠️ Нет активной подписки")
    await q.message.edit_text("\n".join(lines), reply_markup=main_menu(q.from_user.id)); await q.answer()

@dp.callback_query(F.data == "support")
async def cb_support(q: CallbackQuery):
    await q.message.edit_text("<b>🆘 Поддержка VAYNAH VPN</b>\n\nВыбери, что не так — покажу решение:",
                              reply_markup=support_menu()); await q.answer()

@dp.callback_query(F.data.startswith("sup:") & (F.data != "sup:write"))
async def cb_sup_topic(q: CallbackQuery):
    topic = q.data.split(":")[1]
    title, body = SUPPORT_TOPICS.get(topic, ("", ""))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(style="success", text="✍️ Не помогло — написать нам", callback_data="sup:write")],
        [InlineKeyboardButton(style="primary", text="⬅️ Назад", callback_data="support")]])
    await q.message.edit_text(f"<b>{title}</b>\n\n{body}", reply_markup=kb); await q.answer()


# ---------- 16.11.2026: поддержка прямо в боте (пользователь → админы, ответ реплаем) ----------
@dp.callback_query(F.data == "sup:write")
async def cb_sup_write(q: CallbackQuery):
    pending[q.from_user.id] = ("support_msg",)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✖️ Отмена", callback_data="menu")]])
    await smart_edit(q, "✍️ <b>Напиши свой вопрос одним сообщением</b>\n\n"
                        "Опиши, что не работает: устройство, приложение, что видишь на экране. "
                        "Мы ответим прямо сюда, в бот. 🏔", kb)
    await q.answer()

async def support_forward(m):
    u = m.from_user
    who = _html.escape((u.full_name or "").strip() or "без имени") + (f" @{u.username}" if u.username else "")
    sub = get_user(u.id)
    st = ("✅ активна до " + datetime.fromtimestamp(sub["expires_at"]).strftime("%d.%m.%Y")) if (sub and sub["expires_at"] and sub["expires_at"] > time.time()) else "⚪ нет подписки"
    txt = (f"🆘 <b>Обращение в поддержку</b>\n👤 {who} · <code>{u.id}</code> #u{u.id}\n📦 {st}\n\n"
           f"{_html.escape(m.text or '')}\n\n<i>Ответь реплаем на это сообщение — ответ уйдёт пользователю.</i>")
    sent = 0
    for a in admin_ids():
        try: await bot.send_message(a, txt); sent += 1
        except Exception as e: log.error(f"support fwd {a}: {e}")
    log_event(u.id, "support_msg", (m.text or "")[:64])
    return sent

async def support_admin_reply(m):
    """Админ ответил реплаем на обращение (#u<id>) → шлём ответ пользователю. True если обработано."""
    r = m.reply_to_message
    if not r or not (r.text or r.caption): return False
    mm = _re.search(r"#u(\d{3,15})", r.text or r.caption or "")
    if not mm: return False
    target = int(mm.group(1))
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✍️ Ответить", callback_data="sup:write", style="primary"),
                                                InlineKeyboardButton(text="🏠 Меню", callback_data="menu")]])
    try:
        await bot.send_message(target, f"💬 <b>Ответ поддержки VAYNAH</b>\n\n{_html.escape(m.text or '')}", reply_markup=kb)
        await m.answer("✅ Ответ отправлен пользователю.")
    except Exception as e:
        await m.answer(f"❌ Не удалось отправить: {e}")
    return True

# ---------- админ-панель (клиент рулит ценами/промо без знаний) ----------
pending = {}  # uid -> (kind, ...) — единый механизм ввода текста

async def add_days(tg_id, days, manual=False):
    """Добавить дней к подписке. Ручная выдача админа получает 50 ГБ; админы — безлимит."""
    u = get_user(tg_id)
    uuid_ = u["uuid"] if (u and u["uuid"]) else str(uuid.uuid4())
    base = max(time.time(), (u["expires_at"] if u and u["expires_at"] else 0))
    exp = int(base + days * 86400)
    failed = await asyncio.to_thread(xray_add_client, uuid_)
    current_plan = (u["plan"] if u else "promo") or "promo"
    grant_plan = "manual" if manual and not is_admin(tg_id) else current_plan
    upsert_user(tg_id, uuid_, grant_plan, exp)
    db_set(tg_id, revoked=0, rem3=0, rem1=0, rem3h=0, needs_sync=1 if failed else 0)
    await asyncio.to_thread(rw_sync_now, tg_id)  # 03.11.2026: сразу продлить в панели
    return uuid_, exp

def redeem_promo(tg_id, code):
    code = code.strip().upper()
    c = db()
    p = c.execute("SELECT days, max_uses, used FROM promos WHERE code=?", (code,)).fetchone()
    if not p: c.close(); return None, "Промокод не найден"
    days, mx, used = p
    if used >= mx: c.close(); return None, "Промокод исчерпан"
    if c.execute("SELECT 1 FROM promo_redemptions WHERE code=? AND tg_id=?", (code, tg_id)).fetchone():
        c.close(); return None, "Ты уже использовал этот промокод"
    c.execute("INSERT INTO promo_redemptions(code, tg_id) VALUES(?,?)", (code, tg_id))
    c.execute("UPDATE promos SET used=used+1 WHERE code=?", (code,))
    c.commit(); c.close()
    return days, None

def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(style="primary", text="🖥 Веб-панель (статистика, рассылки, всё)", callback_data="adm:web")],
        [InlineKeyboardButton(style="primary", text="💰 Цены тарифов", callback_data="adm:prices")],
        [InlineKeyboardButton(style="primary", text="⏱ Пробный период", callback_data="adm:trial")],
        [InlineKeyboardButton(style="primary", text="🔗 Реф-бонус", callback_data="adm:ref")],
        [InlineKeyboardButton(style="primary", text="🤝 Амбассадоры", callback_data="ambadmin:list:0")],
        [InlineKeyboardButton(style="primary", text="🎁 Промокоды", callback_data="adm:promos")],
        [InlineKeyboardButton(style="primary", text="📈 Аналитика", callback_data="adm:analytics")],
        [InlineKeyboardButton(style="primary", text="📊 Статистика", callback_data="adm:stats")],
        [InlineKeyboardButton(style="primary", text="🧭 Нагрузка / AVTO", callback_data="adm:load"),
         InlineKeyboardButton(style="primary", text="🛡 Антиабуз", callback_data="adm:abuse")],
        [InlineKeyboardButton(style="primary", text="🔁 IP РФ-входа", callback_data="adm:ruip"),
         InlineKeyboardButton(style="primary", text="👑 Админы", callback_data="adm:admins")],
        [InlineKeyboardButton(style="primary", text="🏠 Меню", callback_data="menu")]])

# ---------- амбассадоры: отдельные ссылки и приватная агрегированная статистика ----------
def ambassador_get(tg_id):
    c = db()
    try:
        return c.execute("SELECT tg_id,code,created_at,created_by FROM ambassadors WHERE tg_id=?", (tg_id,)).fetchone()
    finally:
        c.close()

def ambassador_create(tg_id, admin_id):
    c = db()
    try:
        for _ in range(5):
            code = "am_" + _amb_secrets.token_urlsafe(9)
            cur = c.execute("INSERT OR IGNORE INTO ambassadors(tg_id,code,created_at,created_by) VALUES(?,?,?,?)",
                            (tg_id, code, int(time.time()), admin_id))
            c.commit()
            record = c.execute("SELECT tg_id,code,created_at,created_by FROM ambassadors WHERE tg_id=?", (tg_id,)).fetchone()
            if record: return record, bool(cur.rowcount)
        raise RuntimeError("Не удалось создать уникальную ссылку амбассадора")
    finally:
        c.close()

def ambassador_counts(code, since=None):
    c = db()
    try:
        condition = "src=?" + (" AND created_at>=?" if since is not None else "")
        params = (code, since) if since is not None else (code,)
        return c.execute("SELECT COUNT(*), COALESCE(SUM(CASE WHEN first_paid_at IS NOT NULL THEN 1 ELSE 0 END),0) FROM users WHERE " + condition, params).fetchone()
    finally:
        c.close()

def ambassador_screen(tg_id, admin=False):
    rec = ambassador_get(tg_id)
    if not rec: return None, None
    code = rec[1]
    link = f"https://t.me/{BOT_USERNAME}?start={code}"
    total, paid = ambassador_counts(code)
    recent, recent_paid = ambassador_counts(code, int(time.time()) - 7*86400)
    conv = f"{paid * 100 / total:.1f}".replace(".", ",") if total else "0"
    who = f"\n👤 Telegram ID: <code>{tg_id}</code>" if admin else ""
    text = ("🤝 <b>Кабинет амбассадора</b>" + who +
            "\n\n🔗 <b>Персональная ссылка</b>\n" + f"<code>{link}</code>" +
            "\n\n📊 <b>За всё время</b>\n" +
            f"👥 Новых пользователей: <b>{total}</b>\n💳 Оплатили: <b>{paid}</b>\n📈 Конверсия в оплату: <b>{conv}%</b>" +
            "\n\n🗓 <b>Новые за последние 7 дней</b>\n" +
            f"👥 Пришли: <b>{recent}</b> · 💳 Из них уже оплатили: <b>{recent_paid}</b>" +
            "\n\n<i>Учитываются только новые пользователи, впервые запустившие бота по ссылке. "
            "Переходы без запуска и ранее зарегистрированные пользователи не считаются. "
            "Оплатившие — уникальные пользователи с хотя бы одной оплатой.</i>")
    rows = []
    if not admin:
        share = "https://t.me/share/url?" + urllib.parse.urlencode({"url": link})
        rows.append([InlineKeyboardButton(style="primary", text="📤 Поделиться ссылкой", url=share)])
        rows.append([InlineKeyboardButton(style="primary", text="🔄 Обновить", callback_data="amb:mine")])
        rows.append([InlineKeyboardButton(style="primary", text="🏠 Меню", callback_data="menu")])
    else:
        rows.append([InlineKeyboardButton(style="primary", text="🔄 Обновить", callback_data=f"ambadmin:view:{tg_id}")])
        rows.append([InlineKeyboardButton(style="primary", text="⬅️ К амбассадорам", callback_data="ambadmin:list:0")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)

@dp.callback_query(F.data == "amb:mine")
async def cb_amb_mine(q: CallbackQuery):
    if q.message.chat.type != "private":
        await q.answer("Открой кабинет в личном чате с ботом", show_alert=True); return
    txt, kb = ambassador_screen(q.from_user.id)
    if not txt:
        await q.answer("Кабинет недоступен", show_alert=True); return
    await smart_edit(q, txt, kb); await q.answer()

@dp.callback_query(F.data == "ambadmin:add")
async def cb_amb_admin_add(q: CallbackQuery):
    if not is_admin(q.from_user.id) or q.message.chat.type != "private":
        await q.answer("Доступно администратору в личном чате", show_alert=True); return
    pending[q.from_user.id] = ("ambassador_add",)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(style="primary", text="⬅️ Отмена", callback_data="ambadmin:cancel")]])
    await smart_edit(q, "🤝 <b>Новый амбассадор</b>\n\nПришли Telegram ID или @username человека. Он должен сначала запустить бота.\n\nЕсли он уже амбассадор, существующая ссылка сохранится.", kb)
    await q.answer()

@dp.callback_query(F.data == "ambadmin:cancel")
async def cb_amb_admin_cancel(q: CallbackQuery):
    if not is_admin(q.from_user.id) or q.message.chat.type != "private":
        await q.answer(); return
    pending.pop(q.from_user.id, None)
    await smart_edit(q, "⚙️ <b>Админка VAYNAH VPN</b>", admin_menu()); await q.answer()

@dp.callback_query(F.data.startswith("ambadmin:list:"))
async def cb_amb_admin_list(q: CallbackQuery):
    if not is_admin(q.from_user.id) or q.message.chat.type != "private":
        await q.answer("Недоступно", show_alert=True); return
    value = q.data.rsplit(":", 1)[-1]
    if not value.isdigit(): await q.answer("Некорректная страница"); return
    offset = int(value)
    if offset > 10000000: await q.answer("Некорректная страница"); return
    c = db()
    try:
        records = c.execute("SELECT a.tg_id,u.username,u.first_name FROM ambassadors a LEFT JOIN users u ON u.tg_id=a.tg_id ORDER BY a.created_at DESC,a.tg_id DESC LIMIT 11 OFFSET ?", (offset,)).fetchall()
    finally:
        c.close()
    rows = [[InlineKeyboardButton(style="primary", text="➕ Создать ссылку", callback_data="ambadmin:add")]]
    for uid, username, first_name in records[:10]:
        label = ("@" + username if username else first_name or str(uid)).replace("\n", " ")[:28]
        rows.append([InlineKeyboardButton(style="primary", text=f"👤 {label} · {uid}", callback_data=f"ambadmin:view:{uid}")])
    nav = []
    if offset: nav.append(InlineKeyboardButton(style="primary", text="⬅️", callback_data=f"ambadmin:list:{max(0,offset-10)}"))
    if len(records) > 10: nav.append(InlineKeyboardButton(style="primary", text="➡️", callback_data=f"ambadmin:list:{offset+10}"))
    if nav: rows.append(nav)
    rows.append([InlineKeyboardButton(style="primary", text="⬅️ Админка", callback_data="admin")])
    await smart_edit(q, "🤝 <b>Амбассадоры</b>\n\nСоздай персональную ссылку или выбери амбассадора, чтобы посмотреть статистику.", InlineKeyboardMarkup(inline_keyboard=rows))
    await q.answer()

@dp.callback_query(F.data.startswith("ambadmin:view:"))
async def cb_amb_admin_view(q: CallbackQuery):
    if not is_admin(q.from_user.id) or q.message.chat.type != "private":
        await q.answer("Недоступно", show_alert=True); return
    value = q.data.rsplit(":", 1)[-1]
    if not value.isdigit() or len(value)>15: await q.answer("Некорректный ID"); return
    txt, kb = ambassador_screen(int(value), admin=True)
    if not txt: await q.answer("Амбассадор не найден", show_alert=True); return
    await smart_edit(q, txt, kb); await q.answer()

@dp.callback_query(F.data == "admin")
async def cb_admin(q: CallbackQuery):
    if not is_admin(q.from_user.id): await q.answer(); return
    await q.message.edit_text("<b>⚙️ Админка VAYNAH VPN</b>\nУправляй сервисом (всё применяется сразу):",
                              reply_markup=admin_menu()); await q.answer()

@dp.callback_query(F.data == "adm:admins")
async def cb_adm_admins(q: CallbackQuery):
    if not is_admin(q.from_user.id): await q.answer(); return
    c = db(); extra = [r[0] for r in c.execute("SELECT tg_id FROM admins").fetchall()]; c.close()
    lines = ["<b>👑 Администраторы</b>\n", "Владелец/разработчик (не убираются):"]
    for a in sorted(SEED_ADMINS): lines.append(f"• <code>{a}</code>")
    if extra:
        lines.append("\nДобавленные (можно убрать):")
        for a in extra: lines.append(f"• <code>{a}</code>")
    lines.append("\nАдмин видит «⚙️ Админку» и получает уведомления о новых клиентах и оплатах.")
    kb = [[InlineKeyboardButton(style="primary", text="➕ Добавить админа", callback_data="adm:admin_add")]]
    for a in extra:
        kb.append([InlineKeyboardButton(style="primary", text=f"➖ Убрать {a}", callback_data=f"adm:admin_rm:{a}")])
    kb.append([InlineKeyboardButton(style="primary", text="⬅️ Назад", callback_data="admin")])
    await q.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await q.answer()

@dp.callback_query(F.data == "adm:admin_add")
async def cb_adm_admin_add(q: CallbackQuery):
    if not is_admin(q.from_user.id): await q.answer(); return
    pending[q.from_user.id] = ("admin_add",)
    await q.message.edit_text("Пришли <b>Telegram ID</b> нового админа числом.\n"
                              "Пусть он напишет боту @userinfobot и пришлёт тебе свой ID.\n\n⬅️ /start — отмена"); await q.answer()

@dp.callback_query(F.data.startswith("adm:admin_rm:"))
async def cb_adm_admin_rm(q: CallbackQuery):
    if not is_admin(q.from_user.id): await q.answer(); return
    tid = int(q.data.split(":")[-1])
    if tid in SEED_ADMINS:
        await q.answer("Владельца убрать нельзя", show_alert=True); return
    rm_admin(tid)
    await q.answer("Убран")
    await cb_adm_admins(q)

@dp.callback_query(F.data == "adm:prices")
async def cb_adm_prices(q: CallbackQuery):
    if not is_admin(q.from_user.id): await q.answer(); return
    kb = []
    for pid, p in PLANS.items():
        if pid in ("trial", "intro"): continue
        kb.append([InlineKeyboardButton(style="primary", text=f"{p['title']}: {p['rub']}₽ ✏️", callback_data=f"admedit:{pid}_rub"),
                   InlineKeyboardButton(style="primary", text=f"{p['stars']}⭐ ✏️", callback_data=f"admedit:{pid}_stars")])
    kb.append([InlineKeyboardButton(style="primary", text="⬅️ Назад", callback_data="admin")])
    await q.message.edit_text("<b>💰 Цены тарифов</b>\nЖми ✏️ чтобы изменить (₽ слева, ⭐ справа):",
                              reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)); await q.answer()

@dp.callback_query(F.data == "adm:trial")
async def cb_adm_trial(q: CallbackQuery):
    if not is_admin(q.from_user.id): await q.answer(); return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(style="primary", text="✏️ Изменить", callback_data="admedit:trial_days")],
        [InlineKeyboardButton(style="primary", text="⬅️ Назад", callback_data="admin")]])
    await q.message.edit_text(f"<b>⏱ Пробный период</b>\nСейчас: <b>{trial_days()} {days_word(trial_days())}</b>",
                              reply_markup=kb); await q.answer()

@dp.callback_query(F.data == "adm:ref")
async def cb_adm_ref(q: CallbackQuery):
    if not is_admin(q.from_user.id): await q.answer(); return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(style="primary", text="✏️ Дней за друга", callback_data="admedit:ref_bonus_days"),
         InlineKeyboardButton(style="primary", text="✏️ Максимум друзей", callback_data="admedit:ref_max")],
        [InlineKeyboardButton(style="primary", text="⬅️ Назад", callback_data="admin")]])
    await q.message.edit_text(f"<b>🔗 Реф-бонус</b>\nСейчас: <b>+{ref_days()} {days_word(ref_days())}</b> за друга "
                              f"(вход + подписка на канал), максимум <b>{ref_max()}</b> друзей",
                              reply_markup=kb); await q.answer()

@dp.callback_query(F.data == "adm:stats")
async def cb_adm_stats(q: CallbackQuery):
    if not is_admin(q.from_user.id): await q.answer(); return
    c = db(); tot = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    act = c.execute("SELECT COUNT(*) FROM users WHERE expires_at>?", (time.time(),)).fetchone()[0]; c.close()
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(style="primary", text="⬅️ Назад", callback_data="admin")]])
    await q.message.edit_text(f"👥 Всего: {tot}\n✅ Активных: {act}", reply_markup=kb); await q.answer()

@dp.callback_query(F.data == "adm:load")
async def cb_adm_load(q: CallbackQuery):
    if not is_admin(q.from_user.id): await q.answer(); return
    await q.answer("Опрашиваю ноды…")
    loads = await node_loads()
    auto = await cf_record(AUTO_DOMAIN)
    lines = ["<b>🧭 Нагрузка нод</b> (активных соединений на VPN-порту):\n"]
    for n in NODES:
        if n["host"] in loads:
            lines.append(f"{n['name']}: <b>{loads[n['host']]}</b>")
        else:
            lines.append(f"{n['name']}: 🔴 недоступна")
    if auto:
        lines.append(f"\nAVTO → <code>{auto['content']}</code>")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(style="primary", text="🔁 Пересчитать AVTO сейчас", callback_data="adm:reauto")],
        [InlineKeyboardButton(style="primary", text="⬅️ Назад", callback_data="admin")]])
    await q.message.edit_text("\n".join(lines), reply_markup=kb)

@dp.callback_query(F.data == "adm:reauto")
async def cb_adm_reauto(q: CallbackQuery):
    if not is_admin(q.from_user.id): await q.answer(); return
    await q.answer("Пересчитываю…")
    dom = await pick_auto_node(force=True)
    await q.message.edit_text(f"✅ AVTO пересчитан: <b>{(dom or '—').split('.')[0].upper()}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(style="primary", text="⬅️ Назад", callback_data="admin")]]))

@dp.callback_query(F.data == "adm:abuse")
async def cb_adm_abuse(q: CallbackQuery):
    if not is_admin(q.from_user.id): await q.answer(); return
    c = db()
    flags = c.execute("SELECT ts, tg_id, reason, ip FROM abuse_flags ORDER BY ts DESC LIMIT 15").fetchall()
    off = trial_ip_offenders(); c.close()
    lines = [f"<b>🛡 Антиабуз</b>\nТриалов за час: <b>{trials_last_hour()}</b>\n"
             f"Лимит триалов с одного IP: <b>{ABUSE_TRIAL_PER_IP}</b>\n"]
    if off:
        lines.append("<b>IP с превышением:</b>")
        for ip, tgs in off[:10]:
            lines.append(f"• {ip} — {len(tgs)} триалов")
        lines.append("")
    if flags:
        lines.append("<b>Последние блокировки:</b>")
        for ts, tg, reason, ip in flags:
            dt = datetime.fromtimestamp(ts).strftime("%d.%m %H:%M")
            lines.append(f"• {dt} user <code>{tg}</code> — {reason}")
    if not off and not flags:
        lines.append("✅ Нарушений не зафиксировано.")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(style="primary", text="⬅️ Назад", callback_data="admin")]])
    await q.message.edit_text("\n".join(lines), reply_markup=kb); await q.answer()

@dp.callback_query(F.data == "adm:analytics")
async def cb_adm_analytics(q: CallbackQuery):
    if not is_admin(q.from_user.id): await q.answer(); return
    now = time.time(); c = db()
    def cnt(where, args=()): return c.execute(f"SELECT COUNT(*) FROM users WHERE {where}", args).fetchone()[0]
    reg = cnt("1=1")
    trials = cnt("trial_used=1")
    paid = cnt("first_paid_at IS NOT NULL")
    renew = cnt("COALESCE(pay_count,0)>=2")
    active = cnt("expires_at>?", (now,))
    churn = cnt("first_paid_at IS NOT NULL AND expires_at<?", (now,))
    def pct(a, b): return f"{round(100*a/b)}%" if b else "—"
    def ret(days):
        cutoff = now - days * 86400
        base = cnt("first_paid_at IS NOT NULL AND first_paid_at<=?", (cutoff,))
        still = cnt("first_paid_at IS NOT NULL AND first_paid_at<=? AND expires_at>?", (cutoff, now))
        return f"{still}/{base} ({pct(still, base)})"
    r30, r60, r90 = ret(30), ret(60), ret(90)
    c.close()
    txt = (f"<b>📈 Аналитика VAYNAH VPN</b>\n\n"
           f"<b>Воронка:</b>\n"
           f"👥 Регистраций: {reg}\n"
           f"🎁 Взяли пробный: {trials}\n"
           f"💰 Оплатили: {paid} (из рег. {pct(paid, reg)})\n"
           f"🔄 Продлили (2+): {renew}\n"
           f"✅ Активных сейчас: {active}\n"
           f"📉 Отвалились: {churn}\n\n"
           f"<b>Конверсии:</b>\n"
           f"Пробный → оплата: {pct(paid, trials)}\n\n"
           f"<b>Retention (из оплативших N+ дней назад — ещё активны):</b>\n"
           f"30 дней: {r30}\n"
           f"60 дней: {r60}\n"
           f"90 дней: {r90}")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(style="primary", text="⬅️ Назад", callback_data="admin")]])
    await q.message.edit_text(txt, reply_markup=kb); await q.answer()

ADMEDIT_LABELS = {"trial_days": "Пробный период (дней)", "ref_bonus_days": "Реф-бонус (дней)",
                  "ref_max": "Максимум засчитанных друзей"}

@dp.callback_query(F.data.startswith("admedit:"))
async def cb_admedit(q: CallbackQuery):
    if not is_admin(q.from_user.id): await q.answer(); return
    key = q.data.split(":")[1]
    label = ADMEDIT_LABELS.get(key, key.replace("_", " "))
    pending[q.from_user.id] = ("setint", key, label)
    await q.message.answer(f"Введи новое значение для «<b>{label}</b>» (число):")
    await q.answer()

@dp.callback_query(F.data == "adm:promos")
async def cb_adm_promos(q: CallbackQuery):
    if not is_admin(q.from_user.id): await q.answer(); return
    c = db()
    rows = c.execute("SELECT code, days, max_uses, used FROM promos ORDER BY code").fetchall()
    lines = ["<b>🎁 Промокоды — статистика</b>", ""]
    tot_days = 0
    for code, days, mx, used in rows:
        paid = c.execute("SELECT COUNT(*) FROM promo_redemptions pr JOIN users u ON u.tg_id=pr.tg_id "
                         "WHERE pr.code=? AND u.pay_count>0", (code,)).fetchone()[0]
        tot_days += used * days
        conv = f"{round(paid / used * 100)}%" if used else "—"
        lines.append(f"• <code>{code}</code> +{days}дн · активаций {used}/{mx} · выдано {used*days}дн · оплатили {paid} ({conv})")
    if not rows: lines.append("Пока промокодов нет.")
    allred = c.execute("SELECT COUNT(*) FROM promo_redemptions").fetchone()[0]
    uniq = c.execute("SELECT COUNT(DISTINCT tg_id) FROM promo_redemptions").fetchone()[0]
    paidall = c.execute("SELECT COUNT(DISTINCT pr.tg_id) FROM promo_redemptions pr "
                        "JOIN users u ON u.tg_id=pr.tg_id WHERE u.pay_count>0").fetchone()[0]
    c.close()
    lines += ["", f"📊 <b>Итого:</b> активаций {allred} · уник. юзеров {uniq} · выдано дней {tot_days}",
              f"💰 Промо → оплата: <b>{paidall}</b> из {uniq}" + (f" ({round(paidall/uniq*100)}%)" if uniq else "")]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(style="primary", text="➕ Создать промокод", callback_data="promo_new")],
        [InlineKeyboardButton(style="primary", text="⬅️ Назад", callback_data="admin")]])
    await q.message.edit_text("\n".join(lines), reply_markup=kb); await q.answer()

@dp.callback_query(F.data == "promo_new")
async def cb_promo_new(q: CallbackQuery):
    if not is_admin(q.from_user.id): await q.answer(); return
    pending[q.from_user.id] = ("promo_new",)
    await q.message.answer("Создать промокод — введи одной строкой:\n"
                           "<code>КОД ДНИ ИСПОЛЬЗОВАНИЙ</code>\nНапример: <code>LETO 7 100</code>")
    await q.answer()

@dp.callback_query(F.data == "usepromo")
async def cb_usepromo(q: CallbackQuery):
    pending[q.from_user.id] = ("promo_use",)
    await q.message.answer("Введи промокод:")
    await q.answer()

# ---------- 04.11.2026: VPN-сводка пользователя из Remnawave (для мини-карточки админа и веб-панели) ----------
def user_vpn_sync(tg_id, days=14):
    try:
        u = _rw_call("GET", f"/users/by-username/tg{int(tg_id)}")["response"]
    except urllib.error.HTTPError as e:
        if e.code == 404: return None
        raise
    pid = u["id"]; ut = u.get("userTraffic") or {}
    try: devs = sorted((_rw_call("GET", f"/hwid/devices/{pid}")["response"].get("devices") or []), key=lambda x: x.get("createdAt") or "")
    except Exception: devs = []
    end = datetime.utcnow().date(); start = end - timedelta(days=days - 1)
    daily, nodes = [0] * days, []
    try:
        bw = _rw_call("GET", f"/bandwidth-stats/users/{pid}?start={start.isoformat()}&end={end.isoformat()}")["response"]
        cats = bw.get("categories") or []
        for s in bw.get("series") or []:
            tot = int(s.get("total") or 0)
            if tot: nodes.append({"name": s.get("name"), "cc": s.get("countryCode"), "bytes": tot, "uuid": s.get("uuid")})
            for i, v in enumerate(s.get("data") or []):
                if i < days: daily[i] += int(v or 0)
        labels = [str(x)[5:].replace("-", ".")[::-1] if False else ".".join(reversed(str(x)[5:].split("-"))) for x in cats][:days]
    except Exception as e:
        log.error(f"bw stats {tg_id}: {e}"); labels = []
    nodes.sort(key=lambda x: -x["bytes"])
    last_node = next((n["name"] for n in nodes if n["uuid"] == ut.get("lastConnectedNodeUuid")), None)
    def ts(v):
        try: return int(datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()) if v else None
        except Exception: return None
    return {"id": pid, "status": u.get("status"), "limit": u.get("hwidDeviceLimit"),
            "used": int(ut.get("usedTrafficBytes") or 0), "lifetime": int(ut.get("lifetimeUsedTrafficBytes") or 0),
            "online_at": ts(ut.get("onlineAt")), "first_at": ts(ut.get("firstConnectedAt")), "last_node": last_node,
            "sub_opened": ts(u.get("subLastOpenedAt")), "sub_ua": u.get("subLastUserAgent"),
            "daily": daily, "labels": labels, "nodes": nodes,
            "devices": [{"hwid": d.get("hwid"), "platform": d.get("platform"), "os": d.get("osVersion"), "model": d.get("deviceModel"),
                         "ua": d.get("userAgent"), "ip": d.get("requestIp"), "created": ts(d.get("createdAt")), "updated": ts(d.get("updatedAt"))}
                        for d in devs]}

async def user_vpn(tg_id):
    try: return await asyncio.to_thread(user_vpn_sync, tg_id)
    except Exception as e:
        log.error(f"user_vpn {tg_id}: {e}"); return {"error": str(e)}

def rw_device_delete(tg_id, hwid):
    u = _rw_call("GET", f"/users/by-username/tg{int(tg_id)}")["response"]
    _rw_call("POST", "/hwid/devices/delete", {"userId": u["id"], "hwid": hwid})

def fmt_bytes(b):
    b = float(b or 0)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if b < 1024 or unit == "ТБ": return (f"{b:.1f} {unit}" if unit not in ("Б", "КБ") else f"{int(b)} {unit}").replace(".0 ", " ")
        b /= 1024

def _ago_ru(ts):
    if not ts: return "никогда"
    s = time.time() - ts
    if s < 120: return "сейчас онлайн"
    if s < 3600: return f"{int(s // 60)} мин назад"
    if s < 86400: return f"{int(s // 3600)} ч назад"
    return f"{int(s // 86400)} дн назад"

def find_user_ref(text):
    """ID или @ник → tg_id (из базы бота)."""
    s = (text or "").strip()
    m = _re.search(r"(?:t\.me/|@)?([A-Za-z][A-Za-z0-9_]{3,31})$", s)
    if s.isdigit() and 5 <= len(s) <= 15:
        return int(s) if get_user(int(s)) else None
    if m:
        c = db(); r = c.execute("SELECT tg_id FROM users WHERE LOWER(username)=LOWER(?)", (m.group(1),)).fetchone(); c.close()
        return r[0] if r else None
    return None

def bypass_manual_get(tg_id):
    c = db()
    try:
        return bool(c.execute("SELECT 1 FROM bypass_grants WHERE tg_id=?", (tg_id,)).fetchone())
    finally:
        c.close()

def bypass_manual_set(tg_id, enabled, by):
    c = db()
    try:
        if enabled:
            c.execute("INSERT OR IGNORE INTO bypass_grants(tg_id, granted_by, granted_at) VALUES(?,?,?)", (tg_id, by, int(time.time())))
        else:
            c.execute("DELETE FROM bypass_grants WHERE tg_id=?", (tg_id,))
        c.commit()
    finally:
        c.close()

async def admin_card(tg_id):
    u = get_user(tg_id)
    if not u: return "Пользователь не найден", None
    c = db()
    pr = c.execute("SELECT COALESCE(SUM(amount_rub),0), COUNT(*) FROM payments WHERE tg_id=?", (tg_id,)).fetchone()
    nm = c.execute("SELECT username, first_name FROM users WHERE tg_id=?", (tg_id,)).fetchone() or (None, None)
    pay_count = (c.execute("SELECT COALESCE(pay_count,0) FROM users WHERE tg_id=?", (tg_id,)).fetchone() or [0])[0]
    c.close()
    now = time.time(); exp = u["expires_at"] or 0
    if u["revoked"]: st = "⛔ отключён"
    elif exp > now: st = f"✅ до {datetime.fromtimestamp(exp).strftime('%d.%m.%Y')} · ещё {int((exp - now) // 86400)} дн."
    elif exp: st = f"❌ истекла {datetime.fromtimestamp(exp).strftime('%d.%m.%Y')}"
    else: st = "— ключ не брал"
    name = _html.escape(nm[1] or "—") + (f" @{_html.escape(nm[0])}" if nm[0] else "")
    tname = PLANS.get(u["plan"], {}).get("title", u["plan"] or "—").split(" · ")[0]
    lines = [f"👤 <b>{name}</b>", f"<code>{tg_id}</code>", "",
             f"🔑 Подписка: {st}", f"📦 Тариф: {tname}",
             f"💰 Оплачено: <b>{int(pr[0])} ₽</b> · {pr[1]} опл.",
             "🛡 Резервные каналы: на всех тарифах" + (" (подписка не активна)" if not u["uuid"] or u["revoked"] or exp <= now else "")]
    v = await user_vpn(tg_id) if u["uuid"] else None
    rows = []
    if v and not v.get("error"):
        d = v["daily"]; today = d[-1] if d else 0; wk = sum(d[-7:]) if d else 0
        on = v["online_at"]
        dot = "🟢" if on and now - on < 300 else ("🟡" if on and now - on < 86400 else "⚪")
        lines += ["", f"📶 VPN: {dot} {_ago_ru(on)}" + (f" · {_html.escape(v['last_node'])}" if v["last_node"] else ""),
                  f"📊 Трафик: сегодня <b>{fmt_bytes(today)}</b> · 7 дн <b>{fmt_bytes(wk)}</b> · всего <b>{fmt_bytes(v['lifetime'])}</b>",
                  f"     ≈ {fmt_bytes(wk / 7)} в день" if wk else "     подключений не было" if not v["first_at"] else "     за неделю трафика нет"]
        if v["nodes"]:
            lines.append("🌍 " + " · ".join(f"{_html.escape(n['name'].replace('ZPN-', ''))} {fmt_bytes(n['bytes'])}" for n in v["nodes"][:4]))
        lim = v["limit"]
        lines += ["", f"📲 Устройства: <b>{len(v['devices'])}</b>" + (f" из {lim}" if lim else " · без лимита")]
        for i, dv in enumerate(v["devices"], 1):
            app = (dv["ua"] or "").split("/")[:2]
            lines.append(f"  {i}. {_html.escape(dv['model'] or dv['platform'] or 'Устройство')} · "
                         f"{_html.escape(' '.join(x for x in [dv['platform'] or '', dv['os'] or ''] if x))} · {_html.escape(' '.join(app))}"
                         f" · {_ago_ru(dv['updated'])}")
            rows.append([InlineKeyboardButton(style="primary", text=f"🗑 {i}. {(dv['model'] or dv['platform'] or 'устройство')[:24]}",
                                              callback_data=f"adev:{tg_id}:{str(dv['hwid'])[:40]}")])
    elif v and v.get("error"):
        lines += ["", "⚠️ Панель недоступна: " + _html.escape(v["error"][:100])]
    rows += [[InlineKeyboardButton(style="primary", text="+1 день", callback_data=f"aadd:{tg_id}:1"),
              InlineKeyboardButton(style="primary", text="+7 дней", callback_data=f"aadd:{tg_id}:7"),
              InlineKeyboardButton(style="primary", text="+30 дней", callback_data=f"aadd:{tg_id}:30")],
             [InlineKeyboardButton(style="primary", text="📲 −1", callback_data=f"adl:{tg_id}:dec"),
              InlineKeyboardButton(style="primary", text=f"Лимит: {_dl_label(tg_id)}", callback_data=f"adl:{tg_id}:noop"),
              InlineKeyboardButton(style="primary", text="📲 +1", callback_data=f"adl:{tg_id}:inc")],
             [InlineKeyboardButton(style="primary", text="♾ Без лимита", callback_data=f"adl:{tg_id}:inf"),
              InlineKeyboardButton(style="primary", text="↩️ По тарифу", callback_data=f"adl:{tg_id}:def")],
             [InlineKeyboardButton(style="primary", text="✅ Вернуть доступ" if u["revoked"] else "⛔ Отключить", callback_data=f"arev:{tg_id}"),
              InlineKeyboardButton(style="primary", text="🔄 Обновить", callback_data=f"acard:{tg_id}")],
             [InlineKeyboardButton(style="primary", text="♻️ Сменить ключ", callback_data=f"arekey:{tg_id}")],
             [InlineKeyboardButton(style="primary", text="🖥 Открыть панель бота", url=f"https://{SUB_DOMAIN}/admin/#user/{tg_id}")]]
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)

# 05.11.2026: ручной лимит устройств из карточки (users.dev_limit: NULL = по тарифу, 0 = без лимита)
def dev_limit_get(tg_id):
    if is_admin(tg_id):
        return 0, 0
    c = db(); r = c.execute("SELECT dev_limit, plan FROM users WHERE tg_id=?", (tg_id,)).fetchone(); c.close()
    if not r: return None, 3
    plan_def = int(PLANS.get(r[1], {}).get("devices", 3))
    return r[0], plan_def

def _dl_label(tg_id):
    ov, pd = dev_limit_get(tg_id)
    v = pd if ov is None else ov
    return ("♾" if v == 0 else str(v)) + ("" if ov is None else " ✋")

def dev_limit_set(tg_id, value):
    c = db(); c.execute("UPDATE users SET dev_limit=? WHERE tg_id=?", (value, tg_id)); c.commit(); c.close()

@dp.callback_query(F.data.startswith("adl:"))
async def cb_adl(q: CallbackQuery):
    if not is_admin(q.from_user.id): await q.answer(); return
    _, t, op = q.data.split(":"); t = int(t)
    if op == "noop": await q.answer("✋ — лимит задан вручную"); return
    ov, pd = dev_limit_get(t); cur = pd if ov is None else ov
    if op == "inc": new = 1 if cur == 0 else min(cur + 1, 20)
    elif op == "dec":
        if cur == 0: await q.answer("Сейчас без лимита — нажми +1, чтобы задать число"); return
        new = max(cur - 1, 1)
    elif op == "inf": new = 0
    else: new = None
    dev_limit_set(t, new); await asyncio.to_thread(rw_sync_now, t)
    log_event(t, "admin:dev_limit", f"by {q.from_user.id}: {new if new is not None else 'по тарифу'} (bot card)")
    await _acard_edit(q, t, "Лимит устройств: " + ("по тарифу" if new is None else ("без лимита" if new == 0 else str(new))))

async def _acard_edit(q, tg_id, note=None):
    txt, kb = await admin_card(tg_id)
    try: await q.message.edit_text(txt, reply_markup=kb)
    except TelegramBadRequest: pass
    if note: await q.answer(note)
    else: await q.answer()

@dp.callback_query(F.data.startswith("acard:"))
async def cb_acard(q: CallbackQuery):
    if not is_admin(q.from_user.id): await q.answer(); return
    await _acard_edit(q, int(q.data.split(":")[1]))

@dp.callback_query(F.data.startswith("aadd:"))
async def cb_aadd(q: CallbackQuery):
    if not is_admin(q.from_user.id): await q.answer(); return
    _, t, d = q.data.split(":"); t, d = int(t), int(d)
    _, exp = await add_days(t, d, manual=True)
    log_event(t, "admin:add_days", f"by {q.from_user.id}: {d} (bot card)")
    try: await bot.send_message(t, f"🎁 <b>Тебе начислено +{d} {days_word(d)} VAYNAH VPN</b>\nПодписка активна до "
                                   f"{datetime.fromtimestamp(exp).strftime('%d.%m.%Y')}.", reply_markup=main_menu(t))
    except Exception: pass
    await _acard_edit(q, t, f"+{d} дн. начислено ✅")

@dp.callback_query(F.data.startswith("abypass:"))
async def cb_abypass(q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer("Только для администраторов", show_alert=True); return
    await q.answer("Резервные каналы включены для всех тарифов автоматически", show_alert=True)

@dp.callback_query(F.data.startswith("arev:"))
async def cb_arev(q: CallbackQuery):
    if not is_admin(q.from_user.id): await q.answer(); return
    t = int(q.data.split(":")[1]); u = get_user(t)
    if not u: await q.answer("Нет пользователя"); return
    db_set(t, revoked=0 if u["revoked"] else 1); await asyncio.to_thread(rw_sync_now, t)
    log_event(t, "admin:restore" if u["revoked"] else "admin:revoke", f"by {q.from_user.id} (bot card)")
    await _acard_edit(q, t, "Доступ возвращён ✅" if u["revoked"] else "Доступ отключён ⛔")

@dp.callback_query(F.data.startswith("adev:"))
async def cb_adev(q: CallbackQuery):
    if not is_admin(q.from_user.id): await q.answer(); return
    _, t, pref = q.data.split(":", 2); t = int(t)
    v = await user_vpn(t)
    d = next((x for x in (v or {}).get("devices", []) if str(x["hwid"]).startswith(pref)), None)
    if not d: await _acard_edit(q, t, "Устройство уже удалено"); return
    try: await asyncio.to_thread(rw_device_delete, t, d["hwid"])
    except Exception as e: await q.answer(f"Ошибка: {e}"[:180], show_alert=True); return
    log_event(t, "admin:device_del", f"by {q.from_user.id}: {d['model'] or d['platform']}")
    await _acard_edit(q, t, "Устройство удалено 🗑")

# 04.11.2026: постоянная кнопка «🏠 Меню» под полем ввода
MENU_BTN = "🏠 Меню"
REPLY_KB = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=MENU_BTN), KeyboardButton(text=DOCS_BTN)]], resize_keyboard=True,
                               is_persistent=True, input_field_placeholder="Нажми «🏠 Меню»")

@dp.message(Command("help"))
async def msg_help(m: Message):
    ensure_user(m.from_user.id)
    await m.answer(HELP, reply_markup=main_menu(m.from_user.id))

@dp.message(Command("support"))
async def msg_support(m: Message):
    ensure_user(m.from_user.id)
    await m.answer("<b>🆘 Поддержка VAYNAH</b>\n\nВыбери, что не так — покажу решение, или напиши нам:", reply_markup=support_menu())

@dp.message(F.text == MENU_BTN)
@dp.message(Command("menu"))
async def msg_menu(m: Message):
    uid = m.from_user.id
    pending.pop(uid, None)
    ensure_user(uid)
    if await onboard_gate(m.chat.id, uid): return
    if gate_on() and not is_admin(uid) and not await is_subscribed(uid, fresh=True):
        await m.answer(GATE_TXT, reply_markup=gate_kb()); return
    await send_home(m.chat.id, uid, m.from_user.first_name)

@dp.message(F.text & ~F.text.startswith("/"))
async def text_input(m: Message):
    uid = m.from_user.id
    if uid not in pending:
        if is_admin(uid) and m.reply_to_message and await support_admin_reply(m):
            return
        if is_admin(uid) and m.text and len(m.text) <= 64:      # админ прислал ID / @ник → мини-карточка
            t = find_user_ref(m.text) or (m.forward_from.id if getattr(m, "forward_from", None) else None)
            if t:
                txt, kb = await admin_card(t); await m.answer(txt, reply_markup=kb)
            elif _re.fullmatch(r"@?[A-Za-z0-9_]{4,32}", m.text.strip()):
                await m.answer("🔍 Не нашёл такого пользователя в базе бота (он должен хоть раз нажать /start).")
        return
    kind = pending[uid][0]
    if kind == "support_msg":
        pending.pop(uid, None)
        n = await support_forward(m)
        await m.answer("✅ <b>Сообщение отправлено в поддержку.</b>\nОтветим прямо сюда — обычно в течение часа. 🏔" if n else
                       "⚠️ Не получилось доставить сообщение. Попробуй позже.", reply_markup=main_menu(uid))
        return
    if kind == "ambassador_add":
        if not is_admin(uid) or m.chat.type != "private":
            pending.pop(uid, None); return
        target = find_user_ref(m.text)
        if not target:
            await m.answer("Пользователь не найден. Он должен сначала запустить бота. Пришли его Telegram ID или @username ещё раз."); return
        pending.pop(uid, None)
        record, created = ambassador_create(target, uid)
        txt, kb = ambassador_screen(target, admin=True)
        await m.answer(("✅ Амбассадор добавлен.\n\n" if created else "ℹ️ Этот амбассадор уже существует; ссылка сохранена.\n\n") + txt, reply_markup=kb)
    elif kind == "setint":
        if not is_admin(uid): pending.pop(uid, None); return
        _, key, label = pending[uid]
        try: val = int(m.text.strip())
        except ValueError: await m.answer("Нужно число. Попробуй ещё раз:"); return
        if key.endswith("_rub") and not price_ok(val):
            await m.answer(f"❌ Цена должна быть от 1 до {MAX_TX_RUB} ₽ за одну транзакцию. Значение не изменено.", reply_markup=admin_menu()); return
        pending.pop(uid, None); cfg_set(key, val)
        await m.answer(f"✅ «{label}» = <b>{val}</b>\nПрименено.", reply_markup=admin_menu())
    elif kind == "promo_new":
        if not is_admin(uid): pending.pop(uid, None); return
        # 05.11.2026: терпимый ввод — «LETO 7 100», «LETO 7» (лимит 100), «leto, 7 дней, 100 раз», кириллица
        parts = [p for p in _re.split(r"[\s,;:]+", m.text.strip()) if p]
        code = _re.sub(r"[^0-9A-Za-zА-Яа-яЁё_-]", "", parts[0] if parts else "").upper()
        nums = [int(x) for x in _re.findall(r"\d+", " ".join(parts[1:]))]
        if not code or not nums or len(code) > 32:
            await m.answer("Формат: <code>КОД ДНИ ИСПОЛЬЗОВАНИЙ</code>, например <code>LETO 7 100</code>. Ещё раз:"); return
        days, uses = nums[0], (nums[1] if len(nums) > 1 else 100)
        if not 1 <= days <= 3650 or not 1 <= uses <= 100000:
            await m.answer("Дни: 1–3650, использований: 1–100000. Ещё раз:"); return
        pending.pop(uid, None)
        c = db()
        ex = c.execute("SELECT used FROM promos WHERE code=?", (code,)).fetchone()
        c.execute("INSERT OR REPLACE INTO promos(code,days,max_uses,used) VALUES(?,?,?,?)",
                  (code, days, uses, ex[0] if ex else 0)); c.commit(); c.close()
        log_event(uid, "admin:promo_new", f"{code} {days}d x{uses}")
        await m.answer(f"✅ Промокод <b>{code}</b>: +{days} дн., лимит {uses}", reply_markup=admin_menu())
    elif kind == "admin_add":
        if not is_admin(uid): pending.pop(uid, None); return
        pending.pop(uid, None)
        try: tid = int(m.text.strip())
        except ValueError: await m.answer("Нужен Telegram ID числом. Ещё раз:"); pending[uid] = ("admin_add",); return
        add_admin(tid)
        try: await bot.send_message(tid, "👑 Вам выдан доступ администратора VAYNAH VPN. Откройте бота — появится «⚙️ Админка».")
        except Exception: pass
        await m.answer(f"✅ Админ <code>{tid}</code> добавлен.", reply_markup=admin_menu())
    elif kind == "ruip":
        pending.pop(uid, None)
        if not is_admin(uid): return
        ip = m.text.strip()
        if not _ruip_ok(ip):
            await m.answer("❌ Это не публичный IPv4. Открой «🔁 IP РФ-входа» и попробуй ещё раз.",
                           reply_markup=admin_menu()); return
        ok, txt, kb = await ruip_apply(ip, uid)
        await m.answer(txt, reply_markup=kb)
    elif kind == "promo_use":
        pending.pop(uid, None)
        days, err = redeem_promo(uid, m.text)
        if err: await m.answer(f"❌ {err}", reply_markup=main_menu(uid)); return
        _, exp = await add_days(uid, days)
        expd = datetime.fromtimestamp(exp).strftime("%d.%m.%Y")
        await m.answer(f"🎉 <b>Промокод активирован!</b> +{days} дней (до {expd}).")
        u = get_user(uid)
        if u and u["uuid"]: await deliver_key(uid, u["uuid"], "🟢 <b>Доступ активен!</b>")

@dp.callback_query(F.data == "my")
async def cb_my(q: CallbackQuery):
    u = get_user(q.from_user.id)
    if not u or not u["expires_at"] or u["expires_at"] < time.time():
        await q.answer("Нет активной подписки", show_alert=True); return
    left = int((u["expires_at"] - time.time()) / 86400)
    exp = datetime.fromtimestamp(u["expires_at"]).strftime("%d.%m.%Y")
    dev_lim = PLANS.get(u['plan'], {}).get("devices", 3)
    dev_cnt = DEVICES.get(u['uuid'], 0)
    _rw = await rw_devices(q.from_user.id)
    if _rw is not None:
        dev_cnt, _l = len(_rw[1]), _rw[0]
        over = max(0, dev_cnt - _l) if _l else 0
        dev_line = (f"📱 Устройства: <b>{dev_cnt} из {_l}</b> ⚠️ превышение на {over}" if over
                    else (f"📱 Устройства: <b>{dev_cnt} из {_l}</b>" if _l else f"📱 Устройства: {dev_cnt} · без ограничений"))
    else:
        dev_line = f"📱 Устройства: до {dev_lim}"
    tname = PLANS.get(u['plan'], {}).get('title', '—').split(" · ")[0]
    if _rw is not None and _rw[0]: dev_btn = f"📲 Устройства · {dev_cnt}/{_rw[0]}"
    else: dev_btn = "📲 Устройства"
    ap_txt = autopay_line(q.from_user.id)
    txt = (f"🔑 <b>Моя подписка</b>\n\n"
           f"✅ Активна до <b>{exp}</b> · ещё {left} {days_word(left)}\n"
           f"📦 Тариф: {tname}\n"
           f"{dev_line}\n"
           + (f"{ap_txt}" if ap_txt else "") +
           f"\n{key_block(u['uuid'])}")
    _ap = autopay_get(q.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📲 Подключить устройство", url=connect_url(u['uuid']), style="primary")],
        [InlineKeyboardButton(style="primary", text=dev_btn, callback_data="devs"),
         InlineKeyboardButton(style="primary", text="📷 QR-код", callback_data="myqr")],
        [InlineKeyboardButton(style="primary", text="🖥 Кабинет", url=me_url(u['uuid'])),
         InlineKeyboardButton(style="primary", text="🔄 Продлить", callback_data="buy")],
        [InlineKeyboardButton(text="♻️ Сменить ключ", callback_data="rekey", style="danger")]]
        + ([[InlineKeyboardButton(style="primary", text="❌ Отключить автопродление", callback_data="ap_off")]] if _ap and _ap["active"] else [])
        + [[InlineKeyboardButton(style="primary", text="🏠 Меню", callback_data="menu")]])
    await q.message.edit_text(txt, reply_markup=kb); await q.answer()

# ---------- 05.11.2026: жёсткий лимит 50 ГБ — уведомление о исчерпании (флаг ставит rw_sync) ----------
async def traffic_limit_worker():
    await asyncio.sleep(30)
    while True:
        try:
            c = db(); rows = c.execute("SELECT tg_id, plan FROM users WHERE lim_notified=1 AND COALESCE(blocked,0)=0").fetchall(); c.close()
            for tg, plan in rows:
                if is_admin(tg):
                    db_set(tg, lim_notified=0)
                    continue
                db_set(tg, lim_notified=2)
                trial = (plan == "trial")
                txt = ("📶 <b>Трафик закончился</b>\n\n"
                       + ("Пробные 5 ГБ израсходованы. " if trial else "Лимит 50 ГБ на оплаченный период израсходован. ")
                       + "VPN приостановлен.\n\nЧтобы продолжить — оплатите любой тариф: трафик сразу обнулится "
                         "и снова будет 50 ГБ, а оставшиеся дни подписки сохранятся.")
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(style="primary", text="💳 Оплатить", callback_data="buy")],
                                                           [InlineKeyboardButton(text="💬 Поддержка", callback_data="sup:write")]])
                try: await bot.send_message(tg, txt, reply_markup=kb); log_event(tg, "traffic_limited", plan)
                except Exception as e: log.error(f"traffic_limit notify {tg}: {e}")
                await asyncio.sleep(0.1)
        except Exception as e:
            log.error(f"traffic_limit_worker: {e}")
        await asyncio.sleep(60)

# ---------- 05.11.2026: полная смена ключа (старая ссылка/устройства перестают работать) ----------
REKEY_COOLDOWN = 7 * 86400   # пользователь сам — не чаще раза в 7 дней (админ — без ограничений)

def _rekey_sync(tg_id):
    """Новый UUID + новый shortUuid: старого юзера в панели удаляем, новый создаёт rw_sync. -> (ok, msg)"""
    u = get_user(tg_id)
    if not u or not u["uuid"]: return False, "нет ключа"
    old, new = u["uuid"], str(uuid.uuid4())
    db_set(tg_id, uuid=new)                              # сначала БД — фоновый синк уже не вернёт старый UUID
    try:
        try: p = _rw_call("GET", f"/users/by-username/tg{int(tg_id)}").get("response") or {}
        except urllib.error.HTTPError as e:
            if e.code != 404: raise
            p = {}
        if p.get("id") is not None and p.get("vlessUuid") != new:
            _rw_call("DELETE", f"/users/{p['id']}")
    except Exception as e:
        db_set(tg_id, uuid=old)                          # откат — старый ключ продолжает работать
        log.error(f"rekey {tg_id}: {e}")
        return False, f"панель недоступна ({e})"
    rw_sync_now(tg_id)
    try: DEVICES.pop(old, None)
    except Exception: pass
    log_event(tg_id, "rekey", f"{old[:8]}→{new[:8]}")
    return True, new

def _rekey_last(tg_id):
    c = db(); r = c.execute("SELECT MAX(ts) FROM events WHERE tg_id=? AND kind='rekey'", (tg_id,)).fetchone(); c.close()
    return (r[0] or 0) if r else 0

@dp.callback_query(F.data == "rekey")
async def cb_rekey(q: CallbackQuery):
    uid = q.from_user.id; u = get_user(uid)
    if not u or not u["uuid"]: await q.answer("Ключа пока нет", show_alert=True); return
    left = _rekey_last(uid) + REKEY_COOLDOWN - time.time()
    if left > 0 and not is_admin(uid):
        await q.answer(f"Ключ можно менять раз в 7 дней. Следующая смена через {int(left // 86400) + 1} дн. "
                       f"Если ключ утёк — напишите в поддержку.", show_alert=True); return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(style="primary", text="♻️ Да, сменить ключ", callback_data="rekey_ok")],
        [InlineKeyboardButton(style="primary", text="⬅️ Отмена", callback_data="my")]])
    await q.message.answer("♻️ <b>Смена ключа</b>\n\nСтарая ссылка перестанет работать <b>на всех устройствах</b> — "
                           "если ею кто-то пользуется без вас, доступ пропадёт.\nСрок подписки сохранится.\n\n"
                           "После смены добавьте новую ссылку в Happ заново (старую подписку в приложении удалите).",
                           reply_markup=kb)
    await q.answer()

@dp.callback_query(F.data == "rekey_ok")
async def cb_rekey_ok(q: CallbackQuery):
    uid = q.from_user.id
    if _rekey_last(uid) + REKEY_COOLDOWN > time.time() and not is_admin(uid):
        await q.answer("Ключ уже меняли недавно", show_alert=True); return
    await q.answer("Меняю ключ…")
    ok, res = await asyncio.to_thread(_rekey_sync, uid)
    if not ok:
        await q.message.answer(f"❌ Не удалось сменить ключ: {res}. Попробуйте позже или напишите в поддержку."); return
    try: await q.message.delete()
    except Exception: pass
    await deliver_key(uid, res, "♻️ <b>Ключ сменён!</b> Старая ссылка больше не работает.\n"
                               "Удалите старую подписку в Happ и добавьте новую:")

@dp.callback_query(F.data.startswith("arekey:"))
async def cb_arekey(q: CallbackQuery):
    if not is_admin(q.from_user.id): await q.answer(); return
    t = int(q.data.split(":")[1])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(style="primary", text="♻️ Да, сменить ключ", callback_data=f"arekeyok:{t}")],
        [InlineKeyboardButton(style="primary", text="⬅️ Отмена", callback_data=f"acard:{t}")]])
    await q.message.answer(f"Сменить ключ пользователю <code>{t}</code>? Старая ссылка и все устройства отключатся, "
                           f"новая ссылка уйдёт пользователю в бота.", reply_markup=kb)
    await q.answer()

@dp.callback_query(F.data.startswith("arekeyok:"))
async def cb_arekeyok(q: CallbackQuery):
    if not is_admin(q.from_user.id): await q.answer(); return
    t = int(q.data.split(":")[1])
    await q.answer("Меняю ключ…")
    ok, res = await asyncio.to_thread(_rekey_sync, t)
    if not ok: await q.message.edit_text(f"❌ Не удалось: {res}"); return
    log_event(t, "admin:rekey", f"by {q.from_user.id}")
    sent = "✅ новая ссылка отправлена пользователю"
    if t != q.from_user.id:
        try: await deliver_key(t, res, "♻️ <b>Ваш ключ сменён.</b> Старая ссылка больше не работает.\n"
                                       "Удалите старую подписку в Happ и добавьте новую:")
        except Exception as e: sent = f"⚠️ пользователю не доставлено: {e}"
    else:
        await deliver_key(t, res, "♻️ <b>Ключ сменён!</b>")
    await q.message.edit_text(f"♻️ Ключ <code>{t}</code> сменён.\nНовая ссылка: <code>{sub_url(res)}</code>\n{sent}")

# ---------- Remnawave API: scoped service token from systemd environment ----------
RW_API = os.environ.get("INGVERTU_RW_API", "").rstrip("/")
RW_TOKEN = os.environ.get("INGVERTU_RW_TOKEN", "")
def _rw_call(m, p, b=None, timeout=20):
    if not RW_API or not RW_TOKEN:
        raise RuntimeError("Remnawave integration is not configured")
    r = urllib.request.Request(RW_API + p, method=m, data=json.dumps(b).encode() if b is not None else None,
                               headers={"Authorization": "Bearer " + RW_TOKEN, "Content-Type": "application/json",
                                        "Accept": "application/json", "User-Agent": "VAYNAH VPN-bot"})
    with urllib.request.urlopen(r, timeout=timeout) as f:
        return json.loads(f.read() or b"{}")

def _rw_devices_sync(tg_id):
    u = _rw_call("GET", f"/users/by-username/tg{int(tg_id)}", timeout=8)["response"]
    d = _rw_call("GET", f"/hwid/devices/{u['id']}", timeout=8)["response"]
    lim = u.get("hwidDeviceLimit")
    if lim is None: lim = 3
    devs = sorted(d.get("devices") or [], key=lambda x: x.get("createdAt") or "")
    return lim, devs, u["id"]

async def rw_devices(tg_id):
    """(лимит, [устройства], panel_user_id) или None при ошибке. Лимит 0 = без ограничений."""
    try: return await asyncio.to_thread(_rw_devices_sync, tg_id)
    except Exception as e:
        log.error(f"rw_devices {tg_id}: {e}"); return None

def _dev_title(d):
    ua = str(d.get("userAgent") or "")
    app = ua.split("/")[0] if ua else ""
    ver = ua.split("/")[1] if ua.count("/") >= 1 else ""
    model = d.get("deviceModel") or ""
    osn = " ".join(x for x in [d.get("platform") or "", d.get("osVersion") or ""] if x)
    name = model or osn or app or "Устройство"
    extra = " · ".join(x for x in [osn if model else "", f"{app} {ver}".strip()] if x)
    return _html.escape(name), _html.escape(extra)

def devices_screen(lim, devs):
    if not devs:
        body = "Пока нет подключённых устройств.\nДобавь подписку в приложение (Happ) — устройство появится здесь."
    else:
        lines = []
        for i, d in enumerate(devs, 1):
            name, extra = _dev_title(d)
            try: dt = datetime.fromisoformat(str(d.get("createdAt")).replace("Z", "+00:00")).strftime("%d.%m.%Y")
            except Exception: dt = ""
            lines.append(f"{i}. <b>{name}</b>" + (f"\n    {extra}" if extra else "") + (f"\n    добавлено {dt}" if dt else ""))
        body = "\n".join(lines)
    over = max(0, len(devs) - lim) if lim else 0
    lim_txt = (f"{len(devs)} из {lim} · ⚠️ превышение на {over}" if over
               else (f"{len(devs)} из {lim}" if lim else f"{len(devs)} (без ограничений)"))
    notice = (f"⚠️ <b>Лимит превышен на {over} устройств.</b>\n"
              f"Подключение сверх лимита не гарантируется. Удали лишние устройства ниже "
              f"или перейди на Семейный тариф до 5 устройств.\n"
              if over else "")
    txt = (f"<b>📲 Мои устройства — {lim_txt}</b>\n\n{notice}{body}\n\n"
           + (f"Можно подключить до <b>{lim}</b> устройств. Когда лимит занят, новое устройство не получит серверы — "
              "удали ненужное кнопкой ниже, или увеличь лимит. После оплаты обнови подписку в приложении — новый ключ не нужен.\n"
              "Нужно больше — тариф «Семейный» (до 5 устройств)." if lim else ""))
    rows = [[InlineKeyboardButton(style="primary", text=f"🗑 Удалить {i}. {_html.unescape(_dev_title(d)[0])[:28]}",
                                  callback_data=f"devdel:{str(d.get('hwid'))[:48]}")] for i, d in enumerate(devs, 1)]
    rows += [[InlineKeyboardButton(style="primary", text="🔄 Обновить", callback_data="devs")]]
    if lim and len(devs) >= lim:
        rows.append([InlineKeyboardButton(style="primary", text="➕ Увеличить до 5 устройств", callback_data="devmore")])
    elif lim and lim < 5:
        rows.append([InlineKeyboardButton(style="primary", text="➕ Увеличить лимит", callback_data="devmore")])
    rows.append([InlineKeyboardButton(style="primary", text="⬅️ Назад", callback_data="my")])
    return txt, InlineKeyboardMarkup(inline_keyboard=rows)

@dp.callback_query(F.data == "devmore")
async def cb_devmore(q: CallbackQuery):
    u = get_user(q.from_user.id)
    if not u or not u["uuid"] or not u["expires_at"] or u["expires_at"] < time.time():
        await q.answer("Сначала оформи подписку", show_alert=True); return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(style="primary", text="👨‍👩‍👧‍👦 Семейный — до 5 устройств", callback_data="tier:fam")],
        [InlineKeyboardButton(style="primary", text="📋 Все тарифы", callback_data="buy")],
        [InlineKeyboardButton(style="primary", text="⬅️ Мои устройства", callback_data="devs")]])
    await q.message.edit_text("➕ <b>Больше мест для устройств</b>\n\n"
        "Бро, выбирай Семейный тариф — лимит станет <b>до 5 устройств</b>.\n"
        "Ключ менять не нужно: после оплаты просто обнови подписку в Happ или INCY.\n\n"
        "Текущие устройства и срок доступа сохранятся.", reply_markup=kb)
    await q.answer()
@dp.callback_query(F.data == "devs")
async def cb_devs(q: CallbackQuery):
    r = await rw_devices(q.from_user.id)
    if r is None:
        await q.answer("Не удалось загрузить устройства, попробуй через минуту", show_alert=True); return
    txt, kb = devices_screen(r[0], r[1])
    try: await q.message.edit_text(txt, reply_markup=kb)
    except TelegramBadRequest: pass
    await q.answer()

@dp.callback_query(F.data.startswith("devdel:"))
async def cb_devdel(q: CallbackQuery):
    pref = q.data.split(":", 1)[1]
    r = await rw_devices(q.from_user.id)
    if r is None:
        await q.answer("Ошибка, попробуй ещё раз", show_alert=True); return
    lim, devs, uid = r
    d = next((x for x in devs if str(x.get("hwid") or "").startswith(pref)), None)
    if not d:
        await q.answer("Устройство уже удалено"); 
    else:
        try:
            await asyncio.to_thread(_rw_call, "POST", "/hwid/devices/delete", {"userId": uid, "hwid": d["hwid"]})
            log_event(q.from_user.id, "device_del", _dev_title(d)[0])
            await q.answer("Устройство удалено ✅")
        except Exception as e:
            log.error(f"devdel {q.from_user.id}: {e}")
            await q.answer("Не удалось удалить, попробуй позже", show_alert=True); return
    r = await rw_devices(q.from_user.id)
    if r:
        txt, kb = devices_screen(r[0], r[1])
        try: await q.message.edit_text(txt, reply_markup=kb)
        except TelegramBadRequest: pass

@dp.callback_query(F.data == "repair")
async def cb_repair(q: CallbackQuery):
    """🔧 Починить VPN в 1 клик: диагностика нод → пересборка ключа на всех нодах → выбор живого AVTO → свежий QR."""
    u = get_user(q.from_user.id)
    if not u or not u["uuid"] or not u["expires_at"] or u["expires_at"] < time.time():
        await q.answer("Нет активной подписки. Оформи подписку в меню.", show_alert=True); return
    try: await q.message.edit_text("🔧 <b>Чиню VPN…</b>\nПроверяю серверы и пересобираю ключ, 10–15 сек.")
    except Exception: pass
    await q.answer()
    # 1. диагностика нод
    up, down = [], []
    for n in NODES:
        host = n["ssh"] or n["host"]
        (up if await asyncio.to_thread(_tcp_up, host, n["port"]) else down).append(n["name"])
    # 2. убедиться что нода AVTO указывает на живой сервер (иначе — переключить сторож сам, но подтолкнём)
    try:
        auto_rec = await cf_record("example.invalid")
        if auto_rec and not await asyncio.to_thread(_tcp_up, auto_rec["content"], REALITY["port"]):
            await pick_auto_node(force=True)
    except Exception as e:
        log.error(f"repair auto: {e}")
    # 3. пересобрать ключ на всех нодах (идемпотентно, без рестарта)
    failed = await asyncio.to_thread(xray_add_client, u["uuid"])
    db_set(q.from_user.id, revoked=0, needs_sync=1 if failed else 0)
    await asyncio.to_thread(rw_sync_now, q.from_user.id)  # 03.11.2026: досинк в панель
    # 4. отдать свежий ключ + инструкцию
    status = f"🟢 Серверы онлайн: {', '.join(n.split()[-1] for n in up)}" if up else "⚠️ Идёт переключение серверов"
    if down:
        status += f"\n🔴 На обслуживании: {', '.join(n.split()[-1] for n in down)} — трафик авто-переведён"
    header = ("✅ <b>VPN переустановлен!</b>\n\n" + status +
              "\n\nЕсли не подключается:\n"
              "1. Удали старый профиль VAYNAH VPN в приложении\n"
              "2. Добавь заново по QR / ссылке ниже\n"
              "3. Выбери любой сервер VAYNAH VPN (или режим <b>«Авто»</b> в приложении) и жми «Подключить»")
    await deliver_key(q.from_user.id, u["uuid"], header)

@dp.callback_query(F.data == "myru")
async def cb_myru(q: CallbackQuery):
    u = get_user(q.from_user.id)
    if not u or not u["uuid"]:
        await q.answer("Нет подписки", show_alert=True); return
    uid = u["uuid"]; cu = conf_url(uid)
    cap = ("⚡ <b>Авто — умный (РФ-сайты напрямую)</b>\n\n"
           "🇷🇺 Банки, маркетплейсы и Госуслуги работают <b>напрямую</b>, как обычно. "
           "Всё остальное — через VPN, сервер выбирается сам. <b>Для повседневки.</b>\n\n"
           "Добавь эту ссылку в приложении («добавить по ссылке / из буфера») — <b>отдельно</b>, рядом с обычной подпиской:\n\n"
           f"<code>{cu}</code>\n\n"
           "💡 Нужен конкретный сервер вручную — переключись на обычную подписку (флажки стран).")
    try:
        await bot.send_photo(q.from_user.id, BufferedInputFile(qr_png(cu), "zpn-ru.png"), caption=cap)
    except Exception:
        await bot.send_message(q.from_user.id, cap)
    await q.answer()

@dp.callback_query(F.data == "myqr")
async def cb_myqr(q: CallbackQuery):
    u = get_user(q.from_user.id)
    if not u or not u["uuid"]:
        await q.answer("Нет подписки", show_alert=True); return
    await deliver_key(q.from_user.id, u["uuid"], "📱 <b>Твой QR для подключения</b>")
    await q.answer()

@dp.callback_query(F.data == "ref")
async def cb_ref(q: CallbackQuery):
    ensure_user(q.from_user.id)
    txt, kb = ref_screen(q.from_user.id)
    try:
        if os.path.exists(REF_BANNER_PATH):
            await q.message.answer_photo(FSInputFile(REF_BANNER_PATH), caption=txt, reply_markup=kb)
        else:
            await smart_edit(q, txt, kb)
    except Exception as e:
        log.error(f"ref visual: {e}"); await smart_edit(q, txt, kb)
    await q.answer()

@dp.callback_query(F.data.startswith("plan:"))
async def cb_plan(q: CallbackQuery):
    _pp = PLANS.get(q.data.split(":", 1)[1], {})
    if _pp.get("rub") and not price_ok(_pp["rub"]):
        await q.answer("Сумма одной оплаты не может превышать 10 000 ₽", show_alert=True); return
    pid = q.data.split(":")[1]
    if pid not in PLANS:
        await q.answer(); return
    p = PLANS[pid]
    if pid == "channel_trial" or (pid != "trial" and not p.get("rub")):
        await q.answer(); return
    if pid == "intro":
        await cb_intro(q); return
    if pid != "trial" and intro_first_only(q.from_user.id):
        await smart_edit(q, intro_text(), intro_kb()); await q.answer(); return
    if pid == "trial":
        if not free_trial_visible():
            await q.answer("Бесплатный пробный период сейчас недоступен", show_alert=True); return
        u = get_user(q.from_user.id)
        if u and u["trial_used"]:
            await q.answer("Пробный период уже использован", show_alert=True); return
        if not trial_allowed(q.from_user.id):
            await q.answer("У тебя уже есть подписка — пробный период не нужен 🙂", show_alert=True); return
        uuid_, exp = await issue_key(q.from_user.id, "trial")
        if trials_last_hour() > TRIAL_BURST and ADMIN_ID:
            try: await notify_admins(
                f"⚠️ Всплеск триалов: {trials_last_hour()} за час — возможна атака ботами.")
            except Exception: pass
        try: await q.message.edit_text(f"🎁 <b>Пробный период на {trial_days()} {days_word(trial_days())} активирован!</b>")
        except Exception: pass
        await deliver_key(q.from_user.id, uuid_, "🟢 <b>VAYNAH VPN подключён!</b>")
        await q.answer()
        return
    dev = p.get("devices", 3)
    d = plan_discount(p)
    disc = f"  🔥 выгода −{d}%" if d >= 5 else ""
    await q.message.edit_text(
        f"📅 <b>{p['days']} дней</b> · 50 ГБ трафика · до {dev} устройств{disc}\n\n"
        f"💰 Цена: <b>{p['rub']}₽</b>\n\n"
        + ("Выбери способ оплаты:" if platega_ready() else
           "Оплата временно отключена. Подключение Platega настроим позже; сейчас платежи не принимаются:"),
        reply_markup=pay_menu(pid)); await q.answer()

@dp.callback_query(F.data.startswith("pay_stars:"))
async def cb_pay_stars(q: CallbackQuery):
    if not PAYMENTS_ENABLED:
        await q.answer("Оплата временно отключена. Platega подключим отдельно; сейчас платежи не принимаются.", show_alert=True); return
    pid = q.data.split(":")[1]; p = PLANS[pid]
    if not price_ok(p.get("rub", 0)):
        await q.answer(f"Сумма одной оплаты не может превышать {MAX_TX_RUB} ₽", show_alert=True); return
    if pid == "intro" and not intro_ready():
        await q.answer("Предложение больше недоступно. Выберите обычный тариф.", show_alert=True); return
    if pid != "intro" and intro_first_only(q.from_user.id):   # первая покупка — только «Старт»
        await smart_edit(q, intro_text(), intro_kb()); await q.answer(); return
    await bot.send_invoice(
        chat_id=q.from_user.id, title=f"VAYNAH VPN · {p['title']}",
        description=f"Подписка VAYNAH VPN на {p['days']} дней",
        payload=f"plan:{pid}", currency="XTR",
        prices=[LabeledPrice(label=p["title"], amount=p["stars"])])
    await q.answer()

@dp.callback_query(F.data.startswith("pay_heleket:"))
async def cb_pay_heleket(q: CallbackQuery):
    if not PAYMENTS_ENABLED:
        await q.answer("Оплата временно отключена. Platega подключим отдельно; сейчас платежи не принимаются.", show_alert=True); return
    pid = q.data.split(":")[1]; p = PLANS[pid]
    if not price_ok(p.get("rub", 0)):
        await q.answer(f"Сумма одной оплаты не может превышать {MAX_TX_RUB} ₽", show_alert=True); return
    if pid == "intro" and not intro_ready():
        await q.answer("Предложение больше недоступно. Выберите обычный тариф.", show_alert=True); return
    if pid != "intro" and intro_first_only(q.from_user.id):   # первая покупка — только «Старт»
        await smart_edit(q, intro_text(), intro_kb()); await q.answer(); return
    if not HELEKET_API_KEY:
        await q.answer("СБП/крипта скоро — идёт подключение эквайринга 🔧", show_alert=True); return
    order_id = f"{q.from_user.id}-{pid}-{int(time.time())}"
    try:
        res = await heleket_create(p["rub"], order_id)
        url = res.get("result", {}).get("url")
        if not url:
            await q.answer("Ошибка создания платежа, попробуй позже", show_alert=True)
            log.error(f"heleket: {res}"); return
    except Exception as e:
        log.error(f"heleket create: {e}"); await q.answer("Платёж временно недоступен", show_alert=True); return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(style="primary", text="💳 Оплатить", url=url)]])
    await q.message.edit_text(f"<b>{p['title']}</b> — {p['rub']}₽\n\nНажми «Оплатить», после оплаты ключ придёт автоматически.", reply_markup=kb)
    await q.answer()
    pending_add(order_id, "heleket", q.from_user.id, pid)   # переживёт рестарт (pending_worker дожмёт)
    asyncio.create_task(heleket_watch(q.from_user.id, order_id, pid))

@dp.callback_query(F.data.startswith("pay_lava:"))
async def cb_pay_lava(q: CallbackQuery):
    if not PAYMENTS_ENABLED:
        await q.answer("Оплата временно отключена. Platega подключим отдельно; сейчас платежи не принимаются.", show_alert=True); return
    pid = q.data.split(":")[1]; p = PLANS[pid]
    if not price_ok(p.get("rub", 0)):
        await q.answer(f"Сумма одной оплаты не может превышать {MAX_TX_RUB} ₽", show_alert=True); return
    if pid == "intro" and not intro_ready():
        await q.answer("Предложение больше недоступно. Выберите обычный тариф.", show_alert=True); return
    if pid != "intro" and intro_first_only(q.from_user.id):   # первая покупка — только «Старт»
        await smart_edit(q, intro_text(), intro_kb()); await q.answer(); return
    if not LAVA_OFFERS:
        await lava_load_offers()
    offer = LAVA_OFFERS.get(pid)
    if not offer:
        await q.answer("Оплата картой скоро — идёт подключение 🔧", show_alert=True); return
    email = f"tg{q.from_user.id}@example.invalid"
    per = LAVA_PERIODICITY.get(pid, "MONTHLY")
    try:
        res = await lava_create(offer, email, per)
        url = res.get("paymentUrl") or res.get("url") or (res.get("data") or {}).get("url")
        inv_id = res.get("id") or res.get("invoiceId")
        if not url:
            await q.answer("Ошибка создания платежа", show_alert=True); log.error(f"lava: {res}"); return
    except Exception as e:
        log.error(f"lava create: {e}"); await q.answer("Платёж временно недоступен", show_alert=True); return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(style="primary", text="💳 Оплатить картой", url=url)]])
    await q.message.edit_text(f"<b>{p['title']}</b> — {p['rub']}₽\n\nКартой с автопродлением.\nНажми «Оплатить», после оплаты ключ придёт автоматически.", reply_markup=kb)
    await q.answer()
    # первая оплата — поллинг + pending_worker (переживёт рестарт); авто-продления — вебхук Lava
    pending_add(inv_id, "lava", q.from_user.id, pid)
    asyncio.create_task(lava_watch(q.from_user.id, inv_id, pid))

# ---------- Понятное ожидание оплаты СБП; индикатор не является процентом оплаты ----------
_PAY_DOTS = ("🔵 ⚪ ⚪ ⚪", "⚪ 🔵 ⚪ ⚪", "⚪ ⚪ 🔵 ⚪", "⚪ ⚪ ⚪ 🔵")

def payment_wait_text(frame):
    return ("🏦 <b>Ожидаем оплату</b>\n\n" + _PAY_DOTS[frame % len(_PAY_DOTS)] +
            "\n\nНажми «Оплатить через СБП» в сообщении выше. "
            "Когда банк подтвердит платёж, подписка активируется автоматически.\n\n"
            "<i>Индикатор показывает ожидание, а не процент оплаты.</i>")

async def payment_creating_animation(message):
    i = 1
    while True:
        await asyncio.sleep(2)
        try:
            await message.edit_text("🏦 <b>Создаём счёт СБП</b>\n\n" + _PAY_DOTS[i % 4] + "\n\nПочти готово, подожди немного…")
        except Exception: pass
        i += 1

def payment_ui_register(order_id, chat_id, message_id):
    c = db()
    try:
        c.execute("INSERT OR REPLACE INTO payment_ui(order_id,chat_id,message_id,created_at,last_edit) VALUES(?,?,?,?,0)",
                  (str(order_id), int(chat_id), int(message_id), int(time.time())))
        c.commit()
    finally: c.close()

async def payment_ui_tick():
    now = int(time.time()); c = db()
    try:
        rows = c.execute("SELECT ui.order_id,ui.chat_id,ui.message_id,ui.created_at,ui.last_edit, "
                         "EXISTS(SELECT 1 FROM paid_orders po WHERE po.order_id=ui.order_id), "
                         "p.done FROM payment_ui ui LEFT JOIN pending_pays p ON p.order_id=ui.order_id "
                         "ORDER BY ui.last_edit LIMIT 50").fetchall()
    finally: c.close()
    for order_id, chat_id, msg_id, created, last_edit, paid, done in rows:
        terminal = bool(paid or done or now-created >= 45*60 or done is None)
        interval = 12 if now-created < 120 else 30
        if not terminal and now-last_edit < interval: continue
        if paid:
            text = "✅ <b>Оплата подтверждена!</b>\n\nПодписка активирована. Подробности придут отдельным сообщением."
        elif done or done is None:
            text = ("ℹ️ <b>Проверка счёта завершена</b>\n\nЕсли деньги списались, но сообщение о подписке не пришло, "
                    "не оплачивай повторно — напиши в «💬 Поддержка» в боте.")
        elif terminal:
            text = ("⏳ <b>Ожидание занимает больше времени</b>\n\nИндикатор остановлен, но проверка платежа продолжается. "
                    "Если деньги уже списались, не оплачивай повторно. При вопросах напиши в «💬 Поддержка» в боте.")
        else: text = payment_wait_text((now // interval) % 4)
        discard = terminal
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text)
        except Exception as e:
            msg = str(e).lower()
            if any(x in msg for x in ("message to edit not found", "message can't be edited", "chat not found", "bot was blocked", "message is not modified")):
                if "message is not modified" in msg: discard = terminal
                else: discard = True
            else:
                log.warning(f"payment status display: {type(e).__name__}")
                discard = False
        c = db()
        try:
            if discard: c.execute("DELETE FROM payment_ui WHERE order_id=? AND message_id=?", (order_id,msg_id))
            else: c.execute("UPDATE payment_ui SET last_edit=? WHERE order_id=? AND message_id=?", (now,order_id,msg_id))
            c.commit()
        finally: c.close()
        await asyncio.sleep(0.05)

async def payment_ui_worker():
    while True:
        try: await payment_ui_tick()
        except Exception as e: log.warning(f"payment status worker: {type(e).__name__}")
        await asyncio.sleep(6)

@dp.callback_query(F.data.startswith("pay_sbp:"))
async def cb_pay_sbp(q: CallbackQuery):
    if not PAYMENTS_ENABLED:
        await q.answer("Оплата временно отключена. Platega подключим отдельно; сейчас платежи не принимаются.", show_alert=True); return
    pid = q.data.split(":")[1]; p = PLANS[pid]
    if not price_ok(p.get("rub", 0)):
        await q.answer(f"Сумма одной оплаты не может превышать {MAX_TX_RUB} ₽", show_alert=True); return
    if pid == "intro" and not intro_ready():
        await q.answer("Предложение больше недоступно. Выберите обычный тариф.", show_alert=True); return
    if pid != "intro" and intro_first_only(q.from_user.id):
        await smart_edit(q, intro_text(), intro_kb()); await q.answer(); return
    offer = LAVA_SBP_OFFERS.get(pid)
    if not offer:
        await q.answer("СБП для этого тарифа временно недоступен — выбери оплату картой.", show_alert=True); return
    await q.answer()
    try: await q.message.edit_text("🏦 <b>Создаём счёт СБП</b>\n\n" + _PAY_DOTS[0] + "\n\nПочти готово, подожди немного…")
    except Exception: pass
    animation = asyncio.create_task(payment_creating_animation(q.message))
    res = None; create_error = None
    try:
        res = await lava_create_sbp(offer, f"tg{q.from_user.id}@example.invalid")
        url = res.get("paymentUrl") or res.get("url") or (res.get("data") or {}).get("url")
        inv_id = res.get("id") or res.get("invoiceId")
        if not url or not inv_id: raise ValueError("payment URL or invoice ID missing")
        pending_add(inv_id, "lava", q.from_user.id, pid)
    except Exception as e:
        create_error = e
        log.error(f"lava sbp create: {type(e).__name__}")
    finally:
        animation.cancel()
        await asyncio.gather(animation, return_exceptions=True)
    if create_error is not None:
        await smart_edit(q, "⚠️ <b>Не удалось создать счёт</b>\n\nПопробуй ещё раз немного позже.",
                         InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(style="primary", text="⬅️ К тарифам", callback_data="buy")]]))
        return
    asyncio.create_task(lava_watch(q.from_user.id, inv_id, pid))
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(style="primary", text="🏦 Оплатить через СБП", url=url)]])
    await smart_edit(q, f"🏦 <b>Счёт готов</b>\n\n{p['title']} · <b>{p['rub']} ₽</b>\nРазовая оплата по СБП, без автопродления.\n\nНажми кнопку ниже, чтобы оплатить:", kb)
    try:
        status_message = await q.message.answer(payment_wait_text(0))
        payment_ui_register(inv_id, status_message.chat.id, status_message.message_id)
    except Exception as e:
        log.warning(f"payment status create: {type(e).__name__}")

async def lava_watch(tg_id, inv_id, pid):
    if not inv_id: return
    for _ in range(90):  # ~45 мин
        await asyncio.sleep(30)
        try:
            st = await lava_status(inv_id)
            status = str(st.get("status") or "").lower()
            if status in ("completed", "paid", "success", "subscription-active", "in-progress-completed"):
                await fulfill_payment(tg_id, pid, "Lava", order_id=inv_id)
                return
            if status in ("failed", "cancelled", "expired", "declined"):
                pending_done(inv_id); return
        except Exception as e:
            log.error(f"lava watch: {e}")

async def heleket_watch(tg_id, order_id, pid):
    for _ in range(60):  # ~30 мин, каждые 30с
        await asyncio.sleep(30)
        try:
            st = await heleket_status(order_id)
            status = st.get("result", {}).get("payment_status", "")
            if status in ("paid", "paid_over"):
                await fulfill_payment(tg_id, pid, "Heleket", order_id=order_id)
                return
            if status in ("cancel", "fail", "system_fail"):
                pending_done(order_id); return
        except Exception as e:
            log.error(f"heleket watch: {e}")

@dp.pre_checkout_query()
async def pre_checkout(pcq: PreCheckoutQuery):
    await pcq.answer(ok=False, error_message="Оплата сейчас недоступна. Подключение Platega готовится.")

@dp.message(F.successful_payment)
async def on_paid(m: Message):
    if not PAYMENTS_ENABLED:
        log.error("Received successful-payment update while payments are disabled; no access was issued")
        await m.answer("Платежи сейчас отключены. Если списание уже произошло, напишите в поддержку.")
        return
    pid = m.successful_payment.invoice_payload.split(":")[1]
    uuid_, exp = await issue_key(m.from_user.id, pid)
    expd = datetime.fromtimestamp(exp).strftime("%d.%m.%Y")
    await deliver_key(m.from_user.id, uuid_, f"✅ <b>Оплачено! Подписка активна до {expd}</b>")
    log_payment(m.from_user.id, pid, "Telegram Stars", PLANS.get(pid, {}).get("rub", 0),
                order_id=m.successful_payment.telegram_payment_charge_id, currency="XTR",
                stars=m.successful_payment.total_amount)
    try: await notify_payment(m.from_user.id, pid, "Telegram Stars", f"{m.successful_payment.total_amount} ⭐", exp)
    except Exception as e: log.error(f"notify_payment: {e}")
    await notify_ref_bonus(m.from_user.id)

async def notify_ref_bonus(paid_tg_id):
    if ref_mode() != "pay": return            # v2: бонус за вход+подписку на канал (ref_qualify), не за оплату
    try:
        bonus = grant_ref_bonus(paid_tg_id)
        if bonus:
            ref_id, new_exp, ruuid_to_add = bonus
            await asyncio.to_thread(rw_sync_now, ref_id)  # 03.11.2026: бонус сразу в панель
            if ruuid_to_add:                      # реактивировали реферера — ключ на ноды в ПОТОКЕ (не виснет loop)
                failed = await asyncio.to_thread(xray_add_client, ruuid_to_add)
                db_set(ref_id, needs_sync=1 if failed else 0)
            expd = datetime.fromtimestamp(new_exp).strftime("%d.%m.%Y")
            await bot.send_message(ref_id, f"🎉 Твой друг оплатил подписку — тебе <b>+{REF_BONUS_DAYS} дней</b>!\n"
                                           f"Подписка активна до {expd}.", reply_markup=main_menu(ref_id))
    except Exception as e:
        log.error(f"ref bonus: {e}")

# ---------- надёжная выдача по оплате (единая точка: дедуп → ключ → уведомления → реф) ----------
def _num(x):
    """Число из int/float/строки ('199', '199.00', '1 990,00', '199 руб') -> int рублей; иначе None."""
    if isinstance(x, bool): return None
    if isinstance(x, (int, float)): return int(round(x))
    if isinstance(x, str) and x.strip():
        s = _re.sub(r"[^0-9.,-]", "", x)          # выкинуть пробелы/nbsp/руб/буквы
        if not s or s in (".", ",", "-"): return None
        if "," in s and "." in s:                 # EU: точка=тысячи, запятая=десятичн
            s = s.replace(".", "").replace(",", ".")
        elif "," in s:                            # запятая: десятичная если <=2 цифр, иначе тысячи
            frac = s.split(",")[-1]
            s = s.replace(",", "." if len(frac) <= 2 else "")
        try: return int(round(float(s)))
        except Exception: return None
    return None

def pending_add(order_id, provider, tg_id, pid):
    if not order_id: return
    c = db(); c.execute("INSERT OR REPLACE INTO pending_pays(order_id,provider,tg_id,pid,created_at,done) "
                        "VALUES(?,?,?,?,?,0)", (str(order_id), provider, tg_id, pid, int(time.time())))
    c.commit(); c.close()

def pending_done(order_id):
    if not order_id: return
    c = db(); c.execute("UPDATE pending_pays SET done=1 WHERE order_id=?", (str(order_id),)); c.commit(); c.close()

def _lava_pid_from_payload(data, amount):
    """Определить план по офферу+периодичности (устойчиво к правке цен), затем по сумме."""
    offer = (data.get("offerId") or (data.get("offer") or {}).get("id")
             or (data.get("product") or {}).get("id") or data.get("productId"))
    tier = None
    if offer:
        for pid, oid in LAVA_OFFERS.items():
            if oid == offer:
                tier = PLANS.get(pid, {}).get("tier"); break
    per = str(data.get("periodicity") or (data.get("offer") or {}).get("periodicity")
              or data.get("period") or "").upper()
    if tier and per:
        for pid, pp in LAVA_PERIODICITY.items():
            if pp == per and PLANS.get(pid, {}).get("tier") == tier:
                return pid
    if LAVA_INTRO.get("id") and offer == LAVA_INTRO["id"]:
        return "intro"
    if LAVA_INTRO_SBP.get("id") and offer == LAVA_INTRO_SBP["id"]:
        return "intro"
    if amount:
        if LAVA_INTRO.get("id") and int(PLANS["intro"]["rub"]) == amount:
            return "intro"
        return next((k for k, p in PLANS.items()
                     if k not in ("trial", "intro") and int(p["rub"]) == amount), None)
    return None

async def fulfill_payment(tg_id, pid, provider, order_id=None, amount=None):
    """Единая выдача с ДОЛГОВЕЧНЫМ дедупом по order_id (не 600с-память, а таблица paid_orders),
    маркер ставится ТОЛЬКО ПОСЛЕ успешной выдачи → потеря/задвоение платежа исключены. True если выдал."""
    if not pid or pid not in PLANS:
        log.error(f"fulfill: bad pid {pid!r} ({provider}, user {tg_id})"); return False
    amt = amount if amount is not None else PLANS.get(pid, {}).get("rub", 0)
    if not price_ok(amt):
        log.error(f"fulfill: rejected amount above transaction limit: {amt} ({provider}, user {tg_id})"); return False
    # --- дедуп ДО выдачи (не помечаем как выданное, только проверяем) ---
    if order_id:
        c = db(); seen = c.execute("SELECT 1 FROM paid_orders WHERE order_id=?", (str(order_id),)).fetchone(); c.close()
        if seen:                          # этот платёж уже провели (ретрай вебхука/поллинга)
            pending_done(order_id); return False
    else:
        if _lava_seen(tg_id, amt):        # без order_id — мягкий дедуп по (tg,сумма) на 600с
            return False
    # --- выдача; если упадёт (напр. БД занята) — маркер НЕ ставим, pending_worker повторит ---
    try:
        uuid_, exp = await issue_key(tg_id, pid)
    except Exception as e:
        log.error(f"fulfill issue_key user {tg_id} ({provider}): {e}"); return False
    # --- успех: durable-маркер ПОСЛЕ выдачи + закрыть все pending этого (tg,pid) ---
    if order_id:
        c = db()
        c.execute("INSERT OR IGNORE INTO paid_orders(order_id,tg_id,pid,ts) VALUES(?,?,?,?)",
                  (str(order_id), tg_id, pid, int(time.time())))
        c.execute("UPDATE pending_pays SET done=1 WHERE tg_id=? AND pid=? AND done=0", (tg_id, pid))
        c.commit(); c.close()
    if pid == "intro" and order_id and str(provider).startswith("Lava") and intro_is_sub() and not intro_once_is(order_id):
        asyncio.create_task(lava_cancel_sub(order_id, f"tg{tg_id}@example.invalid"))
    log_payment(tg_id, pid, provider, amt, order_id=order_id)
    log_event(tg_id, "pay", f"{pid}:{amt}:{provider}")
    expd = datetime.fromtimestamp(exp).strftime("%d.%m.%Y")
    try:
        await bot.send_message(tg_id, f"🎉 <b>Оплата прошла!</b>\nПодписка активна до <b>{expd}</b>\n\n{key_block(uuid_)}",
                               reply_markup=main_menu(tg_id))
    except Exception as e:
        log.error(f"fulfill notify {tg_id}: {e}")
    try: await notify_payment(tg_id, pid, provider, f"{amt} ₽", exp)
    except Exception as e: log.error(f"notify_payment: {e}")
    await notify_ref_bonus(tg_id)
    return True

@dp.message(Command("stats"))
async def stats(m: Message):
    if not is_admin(m.from_user.id): return
    c = db()
    tot = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    act = c.execute("SELECT COUNT(*) FROM users WHERE expires_at>?", (time.time(),)).fetchone()[0]
    refs = c.execute("SELECT COUNT(*) FROM users WHERE referrer IS NOT NULL").fetchone()[0]
    c.close()
    lines = [f"👥 Всего юзеров: {tot}", f"✅ Активных: {act}", f"🔗 По рефералам: {refs}", "", "<b>Ноды:</b>"]
    for n in NODES:
        host = n["ssh"] or n["host"]
        up = await asyncio.to_thread(_tcp_up, host, n["port"])
        lines.append(f"{n['name']}: {'🟢 онлайн' if up else '🔴 офлайн'}")
    await m.answer("\n".join(lines))

@dp.message(Command("rotate"))
async def rotate_cmd(m: Message):
    if not is_admin(m.from_user.id): return
    kb = []; text = ["<b>Ротация IP нод</b>", "Жми запасной IP, если основной душат:"]
    for domain, ips in ROTATE_POOL.items():
        rec = await cf_record(domain)
        cur = rec["content"] if rec else "?"
        text.append(f"\n<b>{domain}</b> — сейчас <code>{cur}</code>")
        for ip in ips:
            kb.append([InlineKeyboardButton(style="primary", text=("✅ " if ip == cur else "🔄 ") + f"{domain} → {ip}",
                                            callback_data=f"rot:{domain}|{ip}")])
    await m.answer("\n".join(text), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("rot:"))
async def rotate_do(q: CallbackQuery):
    if not is_admin(q.from_user.id):
        await q.answer(); return
    domain, ip = q.data[4:].split("|")
    rec = await cf_record(domain)
    if rec:
        await cf_set_ip(rec["id"], ip)
        await q.message.edit_text(f"✅ {domain} → <code>{ip}</code>\nDNS обновлён (~1-2 мин TTL).")
    await q.answer("Готово")


# ---------- 🔁 быстрая смена IP РФ-входа (example.invalid) ----------
# Подписки клиентов (хосты Remnawave) и релей панели на FI (socat → example.invalid:2222) смотрят на ДОМЕН,
# поэтому при бане IP достаточно перевести A-запись: /ruip <IP> или Админка → «🔁 IP РФ-входа».
import html as _html, ipaddress as _ipaddress
RU_DOMAIN = ""
RU_TTL = 60
RU_NODE = "ZPN-RU"
_ruip_lock = asyncio.Lock()
_bg_tasks = set()

def _bg(coro):
    t = asyncio.create_task(coro); _bg_tasks.add(t); t.add_done_callback(_bg_tasks.discard); return t

def _ruip_ok(ip):
    try: a = _ipaddress.ip_address(str(ip).strip())
    except ValueError: return False
    return a.version == 4 and a.is_global

def _ruip_db():
    c = db()
    c.execute("CREATE TABLE IF NOT EXISTS ruip_hist(ip TEXT PRIMARY KEY, last_at INTEGER, note TEXT)")
    return c

def ruip_remember(ip, note=""):
    c = _ruip_db(); now = int(time.time())
    c.execute("INSERT OR IGNORE INTO ruip_hist(ip,last_at,note) VALUES(?,?,?)", (ip, now, note))
    c.execute("UPDATE ruip_hist SET last_at=?, note=? WHERE ip=?", (now, note, ip))
    c.commit(); c.close()

def ruip_history(limit=4):
    c = _ruip_db()
    rows = c.execute("SELECT ip, note FROM ruip_hist ORDER BY last_at DESC LIMIT ?", (limit,)).fetchall()
    c.close(); return rows

async def _ruip_tcp(host, port=443, timeout=5):
    try:
        _, w = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
        w.close(); return True
    except Exception:
        return False

async def rw_node_online(name=RU_NODE):
    """Статус ноды в панели Remnawave (те же креды, что у rw_sync). None — не удалось узнать."""
    if not RW_API or not RW_TOKEN:
        return None
    try:
        hdr = {"Authorization": "Bearer " + RW_TOKEN, "Accept": "application/json", "User-Agent": "VAYNAH VPN-bot"}
        async with aiohttp.ClientSession() as s:
            async with s.get(RW_API + "/nodes", headers=hdr, timeout=15) as r:
                d = await r.json(content_type=None)
        for n in d.get("response") or []:
            if n.get("name") == name:
                return bool(n.get("isConnected"))
    except Exception as e:
        log.error(f"rw_node_online: {e}")
    return None

def _ruip_back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(style="primary", text="🔁 К IP РФ-входа", callback_data="adm:ruip"),
        InlineKeyboardButton(style="primary", text="⬅️ Админка", callback_data="admin")]])

async def ruip_screen():
    rec = await cf_record(RU_DOMAIN)
    cur = rec["content"] if rec else "?"
    up, node = await asyncio.gather(_ruip_tcp(cur), rw_node_online())
    lines = [f"<b>🔁 IP РФ-входа</b> · <code>{RU_DOMAIN}</code>", "",
             f"Сейчас: <code>{cur}</code> (TTL {rec.get('ttl') if rec else '?'} с)",
             "Порт 443: " + ("🟢 отвечает" if up else "🔴 не отвечает") + " (проверка с DE)",
             "Нода в панели: " + {True: "🟢 online", False: "🔴 offline", None: "❔ нет данных"}[node],
             f"Подписка <code>{SUB_DOMAIN}</code> — CNAME на {RU_DOMAIN}, переключается вместе с ним "
             "(на новом сервере нужен тот же nginx: стартовая страница + подписка + сертификат).", "",
             "Если IP забанили: привяжи к серверу новый IP (или подними новый сервер с нодой) и пришли его сюда — "
             "бот проверит порт 443 и переключит DNS.",
             "У клиентов ничего менять не нужно: подписки смотрят на домен, приложения переподключатся сами за 1–3 мин.", "",
             "Быстро командой: <code>/ruip 1.2.3.4</code>"]
    kb = [[InlineKeyboardButton(style="primary", text="✏️ Ввести новый IP", callback_data="ruip:new")]]
    for ip, note in ruip_history():
        if ip != cur and len(kb) < 4:
            kb.append([InlineKeyboardButton(style="primary", text=f"↩️ Вернуть {ip}" + (f" ({note})" if note else ""),
                                            callback_data=f"ruip:set:{ip}")])
    kb.append([InlineKeyboardButton(style="primary", text="🔄 Обновить", callback_data="adm:ruip"),
               InlineKeyboardButton(style="primary", text="⬅️ Назад", callback_data="admin")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=kb)

async def ruip_apply(new_ip, by_uid, force=False):
    """Переключает A-запись example.invalid на new_ip. Возвращает (ok, text, keyboard)."""
    new_ip = str(new_ip).strip()
    if not _ruip_ok(new_ip):
        return False, (f"❌ <code>{_html.escape(new_ip[:40])}</code> — не публичный IPv4. "
                       "Пример: <code>/ruip 185.10.20.30</code>"), _ruip_back_kb()
    async with _ruip_lock:
        rec = await cf_record(RU_DOMAIN)
        if not rec:
            return False, f"❌ Не нашёл A-запись {RU_DOMAIN} в Cloudflare.", _ruip_back_kb()
        old = rec["content"]
        if old == new_ip:
            return False, f"ℹ️ {RU_DOMAIN} уже указывает на <code>{new_ip}</code>.", _ruip_back_kb()
        if not force and not await _ruip_tcp(new_ip):
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(style="primary", text="⚠️ Всё равно переключить", callback_data=f"ruip:force:{new_ip}")],
                [InlineKeyboardButton(style="primary", text="⬅️ Отмена", callback_data="adm:ruip")]])
            return False, (f"🔴 <code>{new_ip}</code>:443 не отвечает (проверка с DE).\n"
                           "IP точно привязан к серверу и nginx запущен? Если уверен — переключай."), kb
        d = await _cf(f"/zones/{CF_ZONE}/dns_records/{rec['id']}", "PATCH",
                      {"content": new_ip, "proxied": False, "ttl": RU_TTL})
        if not d.get("success"):
            return False, "❌ Cloudflare не принял изменение: " + _html.escape(str(d.get("errors"))[:300]), _ruip_back_kb()
        chk = await cf_record(RU_DOMAIN)
        ruip_remember(old, "до " + datetime.now().strftime("%d.%m %H:%M"))
        ruip_remember(new_ip)
    now_ip = chk["content"] if chk else "?"
    log.warning(f"ruip: {RU_DOMAIN} {old} -> {now_ip} by {by_uid}")
    await notify_admins(f"🔁 <b>РФ-вход переключён</b>\n<code>{RU_DOMAIN}</code>: <code>{old}</code> → <code>{now_ip}</code>\n"
                        f"Кто: <code>{by_uid}</code>\nКлиенты переподключатся сами за 1–3 мин. Через 3 мин пришлю проверку.")
    _bg(_ruip_postcheck(new_ip))
    return True, f"✅ Готово: <code>{RU_DOMAIN}</code> → <code>{now_ip}</code>", _ruip_back_kb()

async def _ruip_postcheck(ip):
    await asyncio.sleep(180)
    try:
        rec = await cf_record(RU_DOMAIN)
        if rec and rec["content"] != ip: return          # уже переключили ещё раз
        up, node = await asyncio.gather(_ruip_tcp(ip), rw_node_online())
        if up and node:
            await notify_admins(f"✅ РФ-вход <code>{ip}</code>: порт 443 отвечает, нода {RU_NODE} в панели online.")
        else:
            await notify_admins(
                f"⚠️ РФ-вход <code>{ip}</code>: порт 443 — {'🟢' if up else '🔴'}, нода {RU_NODE} — "
                f"{'🟢' if node else ('🔴' if node is False else '❔')}.\n"
                "Если сервер новый: на нём должна работать remnanode и быть открыт порт 2222 для FI-релея "
                "Node API access is restricted to the panel server." )
    except Exception as e:
        log.error(f"ruip postcheck: {e}")

@dp.message(Command("ruip"))
async def ruip_cmd(m: Message, command: CommandObject):
    if not is_admin(m.from_user.id): return
    if command.args:
        ok, txt, kb = await ruip_apply(command.args.split()[0], m.from_user.id)
        await m.answer(txt, reply_markup=kb); return
    txt, kb = await ruip_screen()
    await m.answer(txt, reply_markup=kb)

@dp.callback_query(F.data == "adm:ruip")
async def cb_adm_ruip(q: CallbackQuery):
    if not is_admin(q.from_user.id): await q.answer(); return
    await q.answer("Проверяю…")
    txt, kb = await ruip_screen()
    await smart_edit(q, txt, kb)

@dp.callback_query(F.data == "ruip:new")
async def cb_ruip_new(q: CallbackQuery):
    if not is_admin(q.from_user.id): await q.answer(); return
    pending[q.from_user.id] = ("ruip",)
    await smart_edit(q, "Пришли <b>новый IP</b> РФ-сервера одним сообщением, например <code>185.10.20.30</code>.\n\n"
                        "⬅️ /start — отмена")
    await q.answer()

@dp.callback_query(F.data.regexp(r"^ruip:(set|force):"))
async def cb_ruip_set(q: CallbackQuery):
    if not is_admin(q.from_user.id): await q.answer(); return
    _, mode, ip = q.data.split(":", 2)
    await q.answer("Переключаю…")
    ok, txt, kb = await ruip_apply(ip, q.from_user.id, force=(mode == "force"))
    await smart_edit(q, txt, kb)

# ---------- 🔔 уведомления админам: новые клиенты и оплаты ----------
_newu_ts = []

def _tg_name(u):
    name = " ".join(x for x in (getattr(u, "first_name", None), getattr(u, "last_name", None)) if x) or "без имени"
    un = getattr(u, "username", None)
    return _html.escape(name) + (f" (@{_html.escape(un)})" if un else "")

async def notify_new_user(u, args=None):
    try:
        now = time.time()
        _newu_ts[:] = [t for t in _newu_ts if now - t < 600]
        _newu_ts.append(now)
        if len(_newu_ts) > 15:                  # наплыв (боты/реклама) — не спамим, одно предупреждение
            if len(_newu_ts) == 16:
                await notify_admins("⚠️ Больше 15 новых пользователей за 10 мин — уведомления о новых временно приглушены.")
            return
        lines = ["🆕 <b>Новый клиент</b>", f"👤 {_tg_name(u)}", f"🆔 <code>{u.id}</code>"]
        if args:
            lines.append(f"🔗 Пригласил: <code>{args}</code>" if args.isdigit()
                         else f"🏷 Метка: <code>{_html.escape(args[:64])}</code>")
        c = db(); total = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]; c.close()
        lines.append(f"👥 Всего пользователей: {total}")
        await notify_admins("\n".join(lines))
    except Exception as e:
        log.error(f"notify_new_user: {e}")

async def notify_payment(tg_id, pid, provider, amount_txt, exp=None):
    p = PLANS.get(pid, {})
    try: who = _tg_name(await bot.get_chat(tg_id))
    except Exception: who = "—"
    c = db(); r = c.execute("SELECT pay_count, referrer FROM users WHERE tg_id=?", (tg_id,)).fetchone(); c.close()
    pc = (r[0] or 0) if r else 0
    lines = [f"💰 <b>Новая оплата: {amount_txt}</b> · {_html.escape(str(provider))}",
             f"👤 {who} · <code>{tg_id}</code>",
             f"📦 {_html.escape(p.get('title', str(pid)))}",
             "🆕 Первая оплата" if pc <= 1 else f"🔁 Продление (оплата №{pc})"]
    if exp: lines.append("📅 Подписка до " + datetime.fromtimestamp(exp).strftime("%d.%m.%Y"))
    if r and r[1]: lines.append(f"🔗 Пригласил: <code>{r[1]}</code>")
    await notify_admins("\n".join(lines))

# ---------- background: remove expired (only once, via revoked flag) ----------
async def expiry_worker():
    while True:
        try:
            c = db()
            rows = c.execute("SELECT tg_id,uuid FROM users WHERE expires_at<? AND uuid IS NOT NULL AND revoked=0",
                             (time.time(),)).fetchall()
            c.close()
            for tg_id, uuid_ in rows:
                await asyncio.to_thread(xray_remove_client, uuid_)
                db_set(tg_id, revoked=1)
        except Exception as e:
            log.error(f"expiry: {e}")
        await asyncio.sleep(1800)

# ---------- background: node monitoring ----------
def _tcp_up(host, port):
    import socket
    try:
        s = socket.create_connection((host, port), timeout=8); s.close(); return True
    except Exception:
        return False

async def monitor_worker():
    state = {}
    await asyncio.sleep(20)
    while True:
        for n in NODES:
            host = n["ssh"] or n["host"]
            up = await asyncio.to_thread(_tcp_up, host, n["port"])
            prev = state.get(n["name"])
            if prev is not None and prev != up and ADMIN_ID:
                msg = "✅ снова в строю" if up else "🔴 <b>ЛЕГЛА</b>"
                try: await notify_admins( f"Нода {n['name']} ({host}:{n['port']}) — {msg}")
                except Exception: pass
            state[n["name"]] = up
        await asyncio.sleep(MONITOR_INTERVAL)

# ---------- background: напоминания об оплате хостинга ----------
def _next_month(d):
    import calendar
    m, y = d.month + 1, d.year
    if m > 12: m, y = 1, y + 1
    return d.replace(year=y, month=m, day=min(d.day, calendar.monthrange(y, m)[1]))

async def bills_worker():
    await asyncio.sleep(30)
    while True:
        try:
            c = db()
            rows = c.execute("SELECT name, bill_date, r3, r1 FROM hosting_bills").fetchall()
            today = datetime.utcnow().date()
            for name, bd, r3, r1 in rows:
                try: d = datetime.strptime(bd, "%Y-%m-%d").date()
                except Exception: continue
                days = (d - today).days
                ds = d.strftime("%d.%m.%Y")
                if days == 3 and not r3 and ADMIN_ID:
                    await notify_admins( f"🔔 Через <b>3 дня</b> оплата хостинга:\n<b>{name}</b>\nСчёт: {ds}")
                    c.execute("UPDATE hosting_bills SET r3=1 WHERE name=?", (name,))
                elif days == 1 and not r1 and ADMIN_ID:
                    await notify_admins( f"🔔 <b>ЗАВТРА</b> оплата хостинга:\n<b>{name}</b>\nСчёт: {ds}")
                    c.execute("UPDATE hosting_bills SET r1=1 WHERE name=?", (name,))
                elif days < 0:
                    c.execute("UPDATE hosting_bills SET bill_date=?, r3=0, r1=0 WHERE name=?",
                              (_next_month(d).strftime("%Y-%m-%d"), name))
            c.commit(); c.close()
        except Exception as e:
            log.error(f"bills: {e}")
        await asyncio.sleep(6 * 3600)

@dp.message(Command("bills"))
async def bills_cmd(m: Message):
    if not is_admin(m.from_user.id): return
    c = db(); rows = c.execute("SELECT name, bill_date FROM hosting_bills ORDER BY bill_date").fetchall(); c.close()
    today = datetime.utcnow().date()
    lines = ["<b>💳 Оплаты хостинга:</b>"]
    for name, bd in rows:
        try:
            d = datetime.strptime(bd, "%Y-%m-%d").date(); left = (d - today).days
            lines.append(f"• {name} — <b>{d.strftime('%d.%m.%Y')}</b> (через {left} дн.)")
        except Exception: pass
    await m.answer("\n".join(lines))

async def user_reminder_worker():
    await asyncio.sleep(40)
    ren_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(style="primary", text="🔄 Продлить", callback_data="buy")]])
    while True:
        try:
            now = time.time(); c = db()
            rows = c.execute("SELECT tg_id, expires_at, rem3, rem1, rem3h, plan FROM users "
                             "WHERE expires_at>? AND COALESCE(revoked,0)=0 AND COALESCE(blocked,0)=0 "
                             "AND tg_id NOT IN (SELECT tg_id FROM autopay WHERE active=1)", (now,)).fetchall()
            for tg_id, exp, r3, r1, r3h, plan in rows:
                left = exp - now
                if plan in ("trial", "channel_trial"):
                    if left <= 3600 and not r3h:
                        await send_trial_reminder(tg_id, 1); c.execute("UPDATE users SET rem3h=1,rem1=1,rem3=1 WHERE tg_id=?", (tg_id,))
                    elif left <= 6 * 3600 and not r1:
                        await send_trial_reminder(tg_id, 6); c.execute("UPDATE users SET rem1=1,rem3=1 WHERE tg_id=?", (tg_id,))
                    continue
                async def _send(when, _tg=tg_id, _exp=exp):
                    asset = {"3 дня": "renew_3d", "1 день": "renew_1d", "3 часа": "renew_3h"}.get(when, "renew_1d")
                    expd = (datetime.utcfromtimestamp(_exp) + timedelta(hours=3)).strftime("%d.%m.%Y %H:%M")
                    cap = (f"⏰ <b>Подписка VAYNAH VPN заканчивается через {when}</b>\n\n"
                           f"Доступ активен до <b>{expd}</b> (МСК).\n"
                           "Продли заранее — VPN не отключится, ключ и настройки останутся прежними.")
                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(style="primary", text="🔄 Продлить", callback_data="buy")],
                        [InlineKeyboardButton(style="primary", text="🔑 Моя подписка", callback_data="my")]])
                    if await send_push(_tg, asset, cap, kb):
                        log_event(_tg, "push", asset)
                if left <= 3 * 3600 and not r3h:
                    await _send("3 часа"); c.execute("UPDATE users SET rem3h=1,rem1=1,rem3=1 WHERE tg_id=?", (tg_id,))
                elif left <= 86400 and not r1:
                    await _send("1 день"); c.execute("UPDATE users SET rem1=1,rem3=1 WHERE tg_id=?", (tg_id,))
                elif left <= 3 * 86400 and not r3 and plan not in ("trial", "intro"):
                    # у 3-дневного триала "осталось 3 дня" верно сразу при выдаче — не спамим, ему хватит 1д/3ч
                    await _send("3 дня"); c.execute("UPDATE users SET rem3=1 WHERE tg_id=?", (tg_id,))
            c.commit(); c.close()
        except Exception as e:
            log.error(f"user_rem: {e}")
        await asyncio.sleep(1800)

# =====================================================================================================
# 04.11.2026: УМНЫЕ АВТО-РАССЫЛКИ (картинки/анимации из /opt/zpnbot/push)
#  • nokey_gift   — зашёл в бот, но не взял ключ → дарим пробный день
#  • nokey_intro  — через 3 дня после подарка всё ещё без ключа → «Старт 7 дней за 50 ₽»
#  • noconn       — ключ есть, но ни разу не подключился → помощь в 1 клик (+1 день к пробному)
#  • renew_*      — подписка заканчивается (3 дня / 1 день / 3 часа) — в user_reminder_worker
#  • expired      — подписка закончилась (1–48 ч назад) → продлить / «Старт» после пробного
#  • winback      — закончилась 7–14 дней назад → вернуть, с личной статистикой
#  Тихие часы: шлём только 10:00–21:00 МСК. Не чаще 1 маркетингового сообщения в 20 ч на человека.
# =====================================================================================================
PUSH_DIR = "/opt/zpnbot/push"
_PUSH_FID = {}          # asset -> telegram file_id (не грузим файл повторно)

def _push_db():
    c = db()
    c.execute("CREATE TABLE IF NOT EXISTS push_log(tg_id INTEGER, camp TEXT, k TEXT, ts INTEGER, PRIMARY KEY(tg_id, camp, k))")
    return c

def push_sent(tg_id, camp, k="1"):
    c = _push_db(); r = c.execute("SELECT ts FROM push_log WHERE tg_id=? AND camp=? AND k=?", (tg_id, camp, str(k))).fetchone(); c.close()
    return r[0] if r else 0

def push_mark(tg_id, camp, k="1"):
    c = _push_db(); c.execute("INSERT OR REPLACE INTO push_log(tg_id,camp,k,ts) VALUES(?,?,?,?)", (tg_id, camp, str(k), int(time.time())))
    c.commit(); c.close()

def push_last(tg_id):
    c = _push_db(); r = c.execute("SELECT MAX(ts) FROM push_log WHERE tg_id=? AND camp NOT LIKE 'renew%'", (tg_id,)).fetchone(); c.close()
    return (r[0] or 0) if r else 0

def push_stats(days=7):
    try:
        c = _push_db(); r = c.execute("SELECT camp, COUNT(*) FROM push_log WHERE ts>? GROUP BY camp", (int(time.time()) - days * 86400,)).fetchall(); c.close()
        return dict(r)
    except Exception: return {}

def push_quiet():
    h = (datetime.utcnow() + timedelta(hours=3)).hour
    return not (10 <= h < 21)

async def send_push(tg_id, asset, caption, kb):
    """Фото/анимация + подпись + кнопки. True = доставлено."""
    mp4, jpg = f"{PUSH_DIR}/{asset}.mp4", f"{PUSH_DIR}/{asset}.jpg"
    for attempt in range(3):
        try:
            fid = _PUSH_FID.get(asset)
            if os.path.exists(mp4):
                m = await bot.send_animation(tg_id, fid or FSInputFile(mp4), caption=caption, reply_markup=kb)
                if not fid and m.animation: _PUSH_FID[asset] = m.animation.file_id
            elif os.path.exists(jpg):
                m = await bot.send_photo(tg_id, fid or FSInputFile(jpg), caption=caption, reply_markup=kb)
                if not fid and m.photo: _PUSH_FID[asset] = m.photo[-1].file_id
            else:
                await bot.send_message(tg_id, caption, reply_markup=kb)
            return True
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
        except TelegramForbiddenError:
            db_set(tg_id, blocked=1); return False
        except Exception as e:
            if fid: _PUSH_FID.pop(asset, None); continue      # протух file_id — грузим файл заново
            log.error(f"push {asset} {tg_id}: {e}"); return False
    return False

def push_banned(tg):
    """Отключён вручную (админ) или за абуз — таким маркетинг не шлём. Обычное окончание срока — не бан."""
    c = db()
    try:
        r = c.execute("SELECT kind FROM events WHERE tg_id=? AND kind IN ('admin:revoke','admin:restore') "
                      "ORDER BY ts DESC LIMIT 1", (tg,)).fetchone()
        if r and r[0] == "admin:revoke": return True
        try:
            if c.execute("SELECT 1 FROM abuse_flags WHERE tg_id=? LIMIT 1", (tg,)).fetchone(): return True
        except Exception: pass
        return False
    finally: c.close()

def funnel_buy_kb(extra_ref=True):
    p = PLANS["1m"]
    rows = [[InlineKeyboardButton(style="success", text=f"⚡ 30 дней — {p['rub']} ₽", callback_data="plan:1m")],
            [InlineKeyboardButton(style="primary", text="💳 Все тарифы", callback_data="buy")]]
    if extra_ref and ref_mode() == "join":
        rows.append([InlineKeyboardButton(style="primary", text=f"👥 +{ref_days()} {days_word(ref_days())} за друга", callback_data="ref")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def funnel_share_url(tg):
    link = f"https://t.me/{BOT_USERNAME}?start={tg}"
    return ("https://t.me/share/url?url=" + urllib.parse.quote(link) + "&text=" +
            urllib.parse.quote("🛡 VAYNAH VPN — быстрый VPN с серверами в Европе. Заходи по моей ссылке 👇"))

async def send_trial_reminder(tg, hours):
    when = "1 час" if hours == 1 else f"{hours} часов"
    cap = (f"⏳ <b>Пробный период заканчивается через {when}</b>\n\n"
           "Понравилось? Оформи подписку — VPN не отключится, ключ и настройки останутся прежними.\n\n"
           f"⚡ <b>30 дней — {PLANS['1m']['rub']} ₽</b> · оплата по СБП за минуту\n"
           + (f"👥 Или пригласи друга — <b>+{ref_days()} {days_word(ref_days())}</b> бесплатно" if ref_mode() == "join" else ""))
    if await send_push(tg, "trial_1h" if hours == 1 else "trial_6h", cap, funnel_buy_kb()):
        log_event(tg, "push", f"trial_{hours}h")

def _hi(name):
    n = _html.escape((name or "").strip().split(" ")[0][:24])
    return f"{n}, " if n else ""

def _rw_all_users():
    out, start = {}, 0
    while True:
        r = _rw_call("GET", f"/users?size=500&start={start}")["response"]
        us = r.get("users") or []
        for u in us: out[u.get("username")] = u
        start += len(us)
        if not us or start >= r.get("total", 0): return out

def _gb(b):
    try: return round(int(b or 0) / 1024**3, 1)
    except Exception: return 0

async def _push_one(tg, camp, k, asset, cap, kb, sent_box):
    if await send_push(tg, asset, cap, kb):
        push_mark(tg, camp, k); log_event(tg, "push", camp); sent_box[camp] = sent_box.get(camp, 0) + 1
    else:
        push_mark(tg, camp, k)        # не долбим недоступных
    await asyncio.sleep(0.25)

@dp.message(Command("pushtest"))
async def cmd_pushtest(m: Message):
    """Админ: прислать себе все баннеры авто-рассылок."""
    if not is_admin(m.from_user.id): return
    for asset in ("gift", "nokey_miss", "noconn", "bonus", "trial_6h", "trial_1h", "trial_over", "renew_3d", "renew_1d",
                  "renew_3h", "expired", "ref_offer", "winback", "winback2"):
        await send_push(m.from_user.id, asset, f"🧪 Превью: <b>{asset}</b>", None); await asyncio.sleep(0.4)

async def smart_push_worker():
    await asyncio.sleep(90)
    while True:
        try:
            if cfg_on("push_on", True) and not push_quiet():
                await smart_push_run()
        except Exception as e:
            log.error(f"smart_push: {e}")
        await asyncio.sleep(600)

async def smart_push_run(limit=None):
    lim = limit or cfg_int("push_batch", 40)       # сколько сообщений на кампанию за проход (каждые 10 мин)
    now = int(time.time()); sent = {}
    c = db()
    users = c.execute("SELECT tg_id, uuid, plan, expires_at, created_at, trial_used, COALESCE(pay_count,0), "
                      "COALESCE(intro_used,0), trial_at, first_paid_at, first_name, COALESCE(revoked,0) "
                      "FROM users WHERE COALESCE(blocked,0)=0").fetchall()
    try: ap = {r[0] for r in c.execute("SELECT tg_id FROM autopay WHERE active=1")}
    except Exception: ap = set()
    c.close()
    try: rw = await asyncio.to_thread(_rw_all_users)
    except Exception as e:
        log.error(f"smart_push rw: {e}"); rw = None
    adm = admin_ids()
    for (tg, uuid_, plan, exp, created, trial_used, paycnt, intro_used, trial_at, fpa, fname, rev) in users:
        if tg in adm: continue
        if now - push_last(tg) < 20 * 3600: continue
        exp = int(exp or 0); created = int(created or 0)
        hi = _hi(fname)
        # --- 1) зашёл, но ключ не брал → подарок: пробный день
        if not uuid_:
            if created and now - created > 3 * 3600 and trial_allowed(tg):
                if not push_sent(tg, "nokey_gift") and sent.get("nokey_gift", 0) < lim:
                    td = trial_days()
                    cap = (f"🎁 <b>{hi}дарим {td} {days_word(td)} VAYNAH VPN бесплатно</b>\n\n"
                           "Ты заглянул в бот, но так и не попробовал VPN. Забери подарок — без оплаты и без карты:\n\n"
                           "📶 50 ГБ трафика\n🌍 Серверы в Европе\n🇷🇺 Банки и Госуслуги работают с VPN\n\n"
                           "👇 Жми — ключ придёт сразу")
                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(style="primary", text=f"🎁 Забрать {td} {days_word(td)} бесплатно", callback_data="plan:trial")],
                        [InlineKeyboardButton(style="primary", text="🛒 Тарифы", callback_data="buy")]])
                    await _push_one(tg, "nokey_gift", "1", "gift", cap, kb, sent); continue
            g = push_sent(tg, "nokey_gift")
            if g and now - g > 3 * 86400 and trial_allowed(tg) and not push_sent(tg, "nokey_miss") \
                    and sent.get("nokey_miss", 0) < lim:
                td = trial_days()
                cap = (f"💙 <b>{hi}мы скучаем!</b>\n\n"
                       f"Твой бесплатный ключ на <b>{td} {days_word(td)}</b> всё ещё ждёт — без карты и без оплаты.\n\n"
                       "🇩🇪 🇳🇱 🇪🇸 серверы · ⚡ авто-выбор самого быстрого\n🛡 Резервные каналы, когда основной недоступен\n\n"
                       "👇 Один клик — и ключ у тебя")
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(style="success", text=f"🎁 Забрать {td} {days_word(td)} бесплатно", callback_data="plan:trial")],
                    [InlineKeyboardButton(style="primary", text="💳 Тарифы", callback_data="buy")]])
                await _push_one(tg, "nokey_miss", "1", "nokey_miss", cap, kb, sent); continue
            if (g and now - g > 3 * 86400 or (trial_used and created and now - created > 3 * 86400)) \
                    and intro_ready() and not paycnt and not intro_used and not push_sent(tg, "nokey_intro") \
                    and sent.get("nokey_intro", 0) < lim:
                ip = PLANS["intro"]
                cap = (f"🔥 <b>{hi}{ip['days']} {days_word(ip['days'])} VAYNAH VPN за {ip['rub']} ₽</b>\n\n"
                       "Специальная цена для первого раза — все серверы, 50 ГБ, до 3 устройств.\n\n"
                       "🇫🇮 🇩🇪 🇳🇱 🇪🇸 · защищённое соединение")
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(style="primary", text=f"🔥 {ip['days']} {days_word(ip['days'])} за {ip['rub']} ₽", callback_data="intro")]])
                await _push_one(tg, "nokey_intro", "1", "intro", cap, kb, sent)
            continue
        active = exp > now and not rev
        ru = (rw or {}).get(f"tg{tg}") or {}
        ut = ru.get("userTraffic") or {}
        # --- 2) ключ есть, но ни разу не подключался
        if active and rw is not None and ru and not ut.get("firstConnectedAt"):
            issued = int(trial_at or fpa or created or 0)
            if issued and 2 * 3600 < now - issued < 7 * 86400 and not push_sent(tg, "noconn", uuid_) \
                    and sent.get("noconn", 0) < lim:
                bonus = plan == "trial" and not push_sent(tg, "noconn_bonus")
                if bonus:
                    c2 = db(); c2.execute("UPDATE users SET expires_at=expires_at+86400 WHERE tg_id=?", (tg,)); c2.commit(); c2.close()
                    push_mark(tg, "noconn_bonus"); await asyncio.to_thread(rw_sync_now, tg)
                cap = ((f"🎁 <b>{hi}дарим +1 день к пробному!</b>\n\n" if bonus else f"📲 <b>{hi}VPN ещё не подключён</b>\n\n")
                       + "Мы видим, что ключ пока не используется. Подключение занимает минуту:\n\n"
                       "1️⃣ Установи <b>Happ</b> или <b>INCY</b>\n2️⃣ Нажми кнопку своего приложения ниже\n3️⃣ Выбери 🇫🇮 <b>Финляндия · ⚡ Быстрый</b> и включи\n\n"
                       "Не получается? Напиши в поддержку — поможем 💬")
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(style="primary", text="📲 Подключить устройство", url=connect_url(uuid_))],
                    [InlineKeyboardButton(style="primary", text="📖 Инструкция", callback_data="help"),
                     InlineKeyboardButton(style="primary", text="💬 Поддержка", callback_data="support")]])
                await _push_one(tg, "noconn", uuid_, "bonus" if bonus else "noconn", cap, kb, sent)
            continue
        if exp <= 0 or exp > now or tg in ap or push_banned(tg): continue
        # --- 3) подписка закончилась 1–48 ч назад
        if 3600 < now - exp < 48 * 3600 and not push_sent(tg, "expired", exp) and sent.get("expired", 0) < lim:
            if plan == "trial" and intro_ready() and not paycnt and not intro_used:
                ip = PLANS["intro"]
                cap = (f"⏳ <b>{hi}пробный период закончился</b>\n\n"
                       f"Понравилось? Продолжи со специальной ценой: <b>{ip['days']} {days_word(ip['days'])} за {ip['rub']} ₽</b>.\n"
                       "Ключ и настройки сохранены — всё заработает сразу после оплаты.")
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(style="primary", text=f"🔥 {ip['days']} {days_word(ip['days'])} за {ip['rub']} ₽", callback_data="intro")]])
                await _push_one(tg, "expired", exp, "intro", cap, kb, sent)
            elif plan in ("trial", "channel_trial") and not paycnt:
                gb = _gb(ut.get("lifetimeUsedTrafficBytes"))
                cap = (f"⏳ <b>{hi}пробный период закончился</b>\n\n"
                       + (f"За пробный ты прокачал <b>{gb} ГБ</b> 🚀\n" if gb >= 0.5 else "")
                       + "Ключ и настройки сохранены — оплати, и VPN заработает сразу, ничего не настраивая.\n\n"
                       f"⚡ <b>30 дней — {PLANS['1m']['rub']} ₽</b> · оплата по СБП\n"
                       + (f"👥 Или пригласи друга — <b>+{ref_days()} {days_word(ref_days())}</b> бесплатно" if ref_mode() == "join" else ""))
                await _push_one(tg, "expired", exp, "trial_over", cap, funnel_buy_kb(), sent)
            else:
                gb = _gb(ut.get("lifetimeUsedTrafficBytes"))
                cap = (f"🔒 <b>{hi}подписка VAYNAH VPN закончилась</b>\n\n"
                       + (f"С нами ты прокачал <b>{gb} ГБ</b> 🚀\n" if gb >= 1 else "")
                       + "Ключ и настройки сохранены — продли, и VPN заработает сразу, ничего не настраивая.")
                await _push_one(tg, "expired", exp, "expired", cap, funnel_buy_kb(), sent)
            continue
        # --- 3б) через сутки после «закончилась» — дни бесплатно за друзей
        ex_ts = push_sent(tg, "expired", exp)
        if ref_mode() == "join" and ex_ts and now - ex_ts > 24 * 3600 and now - exp < 7 * 86400 \
                and not push_sent(tg, "ref_offer", exp) and sent.get("ref_offer", 0) < lim \
                and ref_stats(tg)[1] < ref_max():
            d, mx = ref_days(), ref_max()
            cap = (f"👥 <b>{hi}VPN бесплатно — за друзей</b>\n\n"
                   f"Отправь другу свою ссылку. Как только он запустит бота и подпишется на канал — "
                   f"тебе <b>+{d} {days_word(d)}</b> VAYNAH VPN.\n\n"
                   f"До {mx} друзей — это <b>{d * mx} {days_word(d * mx)}</b> бесплатно 🔥\n\n"
                   f"Твоя ссылка:\n<code>https://t.me/{BOT_USERNAME}?start={tg}</code>")
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(style="success", text="📤 Отправить другу", url=funnel_share_url(tg))],
                [InlineKeyboardButton(style="primary", text=f"⚡ Или 30 дней — {PLANS['1m']['rub']} ₽", callback_data="plan:1m")]])
            await _push_one(tg, "ref_offer", exp, "ref_offer", cap, kb, sent)
            continue
        # --- 4) закончилась 7–14 дней назад → вернуть
        if 7 * 86400 < now - exp < 14 * 86400 and not push_sent(tg, "winback", exp) and sent.get("winback", 0) < lim:
            cap = (f"💙 <b>{hi}мы скучаем!</b>\n\n"
                   "За это время в VAYNAH VPN стало лучше:\n"
                   "🛡 Резервные серверы — стабильное соединение\n"
                   "🌍 Германия, Нидерланды, Испания, Финляндия — на выбор\n"
                   "📲 Управление устройствами прямо в боте\n\n"
                   "Продли — ключ уже настроен, всё заработает сразу.")
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(style="primary", text="🔄 Вернуться в VAYNAH VPN", callback_data="buy")]])
            await _push_one(tg, "winback", exp, "winback", cap, kb, sent)
            continue
        if 30 * 86400 < now - exp < 45 * 86400 and not push_sent(tg, "winback2", exp) and sent.get("winback2", 0) < lim:
            cap = (f"🏔 <b>{hi}возвращайся в горы!</b>\n\n"
                   "Месяц без VAYNAH VPN — пора вернуться:\n"
                   "🌍 Выбор страны в одно касание\n🛡 Стабильное соединение\n"
                   "🇩🇪 🇳🇱 🇪🇸 Европа · 50 ГБ на период\n\n"
                   f"Ключ сохранён — оплати <b>{PLANS['1m']['rub']} ₽</b>, и всё заработает сразу.")
            await _push_one(tg, "winback2", exp, "winback2", cap, funnel_buy_kb(), sent)
    if sent:
        log.info(f"smart_push: {sent}")
    return sent

# ---------- worker: мониторинг устройств + мягкое ограничение ----------
async def devices_worker():
    await asyncio.sleep(45)
    while True:
        try:
            online = await all_online_ips()      # ОДИН SSH на ноду разом (не на юзера) — без шторма
            c = db()
            rows = c.execute("SELECT tg_id, uuid, plan FROM users WHERE uuid IS NOT NULL AND expires_at>? AND COALESCE(revoked,0)=0",
                             (time.time(),)).fetchall()
            c.close()
            for tg_id, uuid_, plan in rows:
                if is_admin(tg_id):
                    DEVICES[uuid_] = len(online.get(uuid_, set()))
                    continue
                ips = online.get(uuid_, set())
                if uuid_ in online and not ips:  # онлайн, но формат не отдал IP — точечный фолбэк
                    ips = await asyncio.to_thread(device_ips, uuid_)
                cnt = len(ips)
                DEVICES[uuid_] = cnt
                if plan == "trial" and ips:
                    record_trial_ips(tg_id, ips)   # антиабуз: фиксируем IP триал-юзеров
                limit = PLANS.get(plan, {}).get("devices", 3)
                if cnt > limit and uuid_ not in _dev_notified:
                    _dev_notified.add(uuid_)
                    try:
                        await bot.send_message(tg_id, f"⚠️ <b>Превышен лимит устройств: {cnt} из {limit}</b>\n"
                                               f"Отключи лишние устройства. Нужно больше — оформи Семейный тариф (до 5).")
                    except Exception: pass
                    if ADMIN_ID:
                        try: await notify_admins( f"🚨 Превышение устройств: user {tg_id} — {cnt}/{limit} ({plan})")
                        except Exception: pass
                elif cnt <= limit:
                    _dev_notified.discard(uuid_)
            # чистим старые записи триал-IP (окно абуза 14 дней), чтобы таблица не пухла
            try:
                cc = db(); cc.execute("DELETE FROM trial_ips WHERE ts < ?", (int(time.time()) - 14 * 86400,))
                cc.commit(); cc.close()
            except Exception: pass
            # антиабуз: с одного IP наплодили триалов больше лимита -> глушим лишние (новые)
            for ip, tgs in trial_ip_offenders():
                for tg in tgs[ABUSE_TRIAL_PER_IP:]:
                    if tg in _abuse_revoked: continue
                    uu = get_user(tg)
                    if not uu or not uu["uuid"] or uu["plan"] != "trial": continue
                    _abuse_revoked.add(tg)
                    await asyncio.to_thread(xray_remove_client, uu["uuid"])
                    db_set(tg, revoked=1)
                    flag_abuse(tg, f"мульти-триал с одного IP (>{ABUSE_TRIAL_PER_IP})", ip)
                    if ADMIN_ID:
                        try: await notify_admins(
                            f"🚨 <b>Антиабуз</b>: приостановил пробный доступ user <code>{tg}</code> — "
                            f"с IP {ip} уже {len(tgs)} триал-аккаунтов")
                        except Exception: pass
        except Exception as e:
            log.error(f"devices: {e}")
        await asyncio.sleep(120)

# =====================================================================================================
# 04.11.2026 · РОСТ: обязательный канал, рефералка v2 (+3 дня за друга, до 10), воронка «3 дня за 1 ₽»
# (карта + автопродление через ЮKassa), журнал платежей/событий, рассылки, веб-админка (admin_web.py)
# =====================================================================================================
from aiogram import BaseMiddleware
from aiogram.types import ChatMemberUpdated
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter, TelegramBadRequest
import secrets as _secrets

CHANNEL_ID_DEFAULT = 0
CHANNEL_URL_DEFAULT = ""
SPECIAL_PIDS = {"trial", "intro", "channel_trial"}          # не тарифы витрины
MSK = 3 * 3600                             # бакеты аналитики по МСК

def growth_init():
    """Новые таблицы/колонки (один раз при старте)."""
    c = db()
    for col, ddl in [("username", "TEXT"), ("first_name", "TEXT"), ("last_seen", "INTEGER"),
                     ("ch_sub", "INTEGER DEFAULT 0"), ("ch_sub_at", "INTEGER"), ("intro_used", "INTEGER DEFAULT 0"),
                     ("src", "TEXT"), ("blocked", "INTEGER DEFAULT 0"),
                     ("channel_trial_requested", "INTEGER DEFAULT 0"),
                     ("channel_trial_issued", "INTEGER DEFAULT 0")]:
        try: c.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")
        except sqlite3.OperationalError: pass
    c.executescript("""
    CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, tg_id INTEGER, pid TEXT,
        provider TEXT, amount_rub REAL, currency TEXT DEFAULT 'RUB', stars INTEGER, order_id TEXT, kind TEXT);
    CREATE INDEX IF NOT EXISTS ix_pay_ts ON payments(ts);
    CREATE INDEX IF NOT EXISTS ix_pay_tg ON payments(tg_id);
    CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, tg_id INTEGER, kind TEXT, meta TEXT);
    CREATE INDEX IF NOT EXISTS ix_ev_kind ON events(kind, ts);
    CREATE TABLE IF NOT EXISTS ref_credits(invitee INTEGER PRIMARY KEY, referrer INTEGER, days INTEGER, ts INTEGER);
    CREATE INDEX IF NOT EXISTS ix_ref_r ON ref_credits(referrer);
    CREATE TABLE IF NOT EXISTS autopay(tg_id INTEGER PRIMARY KEY, provider TEXT, method_id TEXT, card TEXT, fp TEXT,
        pid TEXT, amount INTEGER, next_at INTEGER, active INTEGER DEFAULT 1, fails INTEGER DEFAULT 0,
        created_at INTEGER, last_try INTEGER DEFAULT 0, last_err TEXT, rem_at INTEGER DEFAULT 0, off_at INTEGER);
    CREATE TABLE IF NOT EXISTS broadcasts(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, by_id INTEGER, segment TEXT,
        text TEXT, photo TEXT, btn_text TEXT, btn_url TEXT, total INTEGER DEFAULT 0, pos INTEGER DEFAULT 0,
        sent INTEGER DEFAULT 0, failed INTEGER DEFAULT 0, blocked INTEGER DEFAULT 0, status TEXT, finished_at INTEGER);
    CREATE TABLE IF NOT EXISTS admin_sessions(token TEXT PRIMARY KEY, tg_id INTEGER, created_at INTEGER,
        expires_at INTEGER, ua TEXT, ip TEXT);
    CREATE TABLE IF NOT EXISTS admin_links(token TEXT PRIMARY KEY, tg_id INTEGER, expires_at INTEGER, used INTEGER DEFAULT 0);
    CREATE INDEX IF NOT EXISTS ix_users_ref ON users(referrer);
    CREATE INDEX IF NOT EXISTS ix_users_created ON users(created_at);
    """)
    c.commit()
    ov = dict(c.execute("SELECT key,value FROM settings").fetchall())
    # миграция рефералки на v2 (один раз): +3 дня за друга, максимум 10, начисление за вход+подписку на канал
    if "ref_v2" not in ov:
        for k, v in (("ref_bonus_days", "3"), ("ref_max", "10"), ("ref_mode", "join"), ("ref_v2", "1")):
            c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (k, v))
        # приглашённые ДО v2 не начисляются задним числом (days=-1 = «старая программа»)
        c.execute("INSERT OR IGNORE INTO ref_credits(invitee,referrer,days,ts) "
                  "SELECT tg_id, referrer, -1, ? FROM users WHERE referrer IS NOT NULL", (int(time.time()),))
    # бэкфилл журнала платежей из paid_orders (один раз; суммы — по текущим ценам тарифов)
    if "payments_backfilled" not in ov:
        rows = c.execute("SELECT o.order_id, o.tg_id, o.pid, o.ts, p.provider FROM paid_orders o "
                         "LEFT JOIN pending_pays p ON p.order_id=o.order_id").fetchall()
        for oid, tg, pid, ts, prov in rows:
            if c.execute("SELECT 1 FROM payments WHERE order_id=?", (oid,)).fetchone(): continue
            prov_name = {"lava": "Lava", "heleket": "Heleket"}.get(prov or "", "Lava" if "-" in str(oid) and len(str(oid)) > 30 else "—")
            c.execute("INSERT INTO payments(ts,tg_id,pid,provider,amount_rub,currency,order_id,kind) VALUES(?,?,?,?,?,?,?,?)",
                      (ts, tg, pid, prov_name, PLANS.get(pid, {}).get("rub", 0), "RUB", oid, "backfill"))
        c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('payments_backfilled','1')")
    c.commit(); c.close()
    apply_settings()

def cfg(key, default=None):
    v = CFG.get(key)
    return default if v is None or v == "" else v

def cfg_int(key, default):
    try: return int(float(CFG.get(key, default)))
    except Exception: return default

def cfg_on(key, default=True):
    v = CFG.get(key)
    return default if v is None or v == "" else str(v).lower() in ("1", "true", "on", "yes")

def log_event(tg_id, kind, meta=None):
    try:
        c = db(); c.execute("INSERT INTO events(ts,tg_id,kind,meta) VALUES(?,?,?,?)",
                            (int(time.time()), tg_id, kind, None if meta is None else str(meta)[:500]))
        c.commit(); c.close()
    except Exception as e:
        log.error(f"log_event {kind}: {e}")

def log_payment(tg_id, pid, provider, amount_rub, order_id=None, currency="RUB", stars=None):
    try:
        c = db()
        if order_id and c.execute("SELECT 1 FROM payments WHERE order_id=?", (str(order_id),)).fetchone():
            c.close(); return
        pc = (c.execute("SELECT COALESCE(pay_count,0) FROM users WHERE tg_id=?", (tg_id,)).fetchone() or [0])[0]
        kind = "intro" if pid == "intro" else ("first" if pc <= 1 else "renew")
        if pid == "intro": c.execute("UPDATE users SET intro_used=1 WHERE tg_id=?", (tg_id,))
        c.execute("INSERT INTO payments(ts,tg_id,pid,provider,amount_rub,currency,stars,order_id,kind) VALUES(?,?,?,?,?,?,?,?,?)",
                  (int(time.time()), tg_id, pid, str(provider), float(amount_rub or 0), currency, stars,
                   None if order_id is None else str(order_id), kind))
        c.commit(); c.close()
    except Exception as e:
        log.error(f"log_payment: {e}")

def urow(tg_id, cols):
    c = db(); r = c.execute(f"SELECT {cols} FROM users WHERE tg_id=?", (tg_id,)).fetchone(); c.close()
    return r

# ---------------------------------- обязательная подписка на канал ----------------------------------
def gate_on(): return cfg_on("ch_required", True)
def channel_id():
    try: return int(cfg("ch_id", CHANNEL_ID_DEFAULT))
    except Exception: return CHANNEL_ID_DEFAULT
def channel_url(): return cfg("ch_url", CHANNEL_URL_DEFAULT)

_SUB_CACHE = {}      # uid -> (ts, bool)
_CH_KNOWN = set()    # uid с ch_sub=1 (чтобы не писать в БД на каждую проверку)

def _is_inside(m):
    st = getattr(m, "status", "")
    st = getattr(st, "value", st)
    return st in ("member", "administrator", "creator") or (st == "restricted" and bool(getattr(m, "is_member", False)))

def mark_ch_sub(uid, on=True):
    """Отметить подписку. True — если это ПЕРВАЯ подписка юзера бота (для реф-начисления)."""
    if on and uid in _CH_KNOWN: return False
    c = db()
    try:
        r = c.execute("SELECT ch_sub, ch_sub_at FROM users WHERE tg_id=?", (uid,)).fetchone()
        if not r: return False
        if on:
            _CH_KNOWN.add(uid)
            if r[0] == 1: return False
            c.execute("UPDATE users SET ch_sub=1, ch_sub_at=COALESCE(ch_sub_at, ?) WHERE tg_id=?", (int(time.time()), uid))
            c.commit()
            return r[1] is None
        _CH_KNOWN.discard(uid)
        if r[0]: c.execute("UPDATE users SET ch_sub=0 WHERE tg_id=?", (uid,)); c.commit()
        return False
    finally:
        c.close()

async def is_subscribed(uid, fresh=False):
    if not fresh:
        v = _SUB_CACHE.get(uid)
        if v and time.time() - v[0] < (900 if v[1] else 15):
            return v[1]
    try:
        ok = _is_inside(await bot.get_chat_member(channel_id(), uid))
    except Exception as e:
        log.warning(f"gate check {uid}: {e}")
        return True     # fail-open: сбой Telegram API не должен ломать бота
    _SUB_CACHE[uid] = (time.time(), ok)
    if ok:
        if await asyncio.to_thread(mark_ch_sub, uid, True):
            log_event(uid, "ch_sub")
            asyncio.create_task(ref_qualify(uid))
    elif uid in _CH_KNOWN:
        await asyncio.to_thread(mark_ch_sub, uid, False)
    return ok

GATE_TXT = ("📢 <b>Подпишись на канал VAYNAH VPN</b>\n\n"
            "Бот работает для подписчиков нашего канала — там новости, статус серверов, "
            "акции и бесплатные дни 🎁\n\n"
            "1️⃣ Нажми «Подписаться на канал»\n"
            "2️⃣ Вернись сюда и нажми «✅ Я подписался»")

def gate_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(style="primary", text="📢 Подписаться на канал", url=channel_url())],
        [InlineKeyboardButton(style="primary", text="✅ Я подписался", callback_data="chk_sub")]])

GATE_FREE_CB = {"chk_sub", "terms", "support", "ap_off", "ap_off_yes", "autopay"}

async def send_gate(event):
    if isinstance(event, CallbackQuery):
        try: await event.answer("Сначала подпишись на канал 👇")
        except Exception: pass
        await smart_edit(event, GATE_TXT, gate_kb())
    else:
        await event.answer(GATE_TXT, reply_markup=gate_kb())

_TOUCH = {}
def touch_user(u):
    now = time.time()
    if now - _TOUCH.get(u.id, 0) < 600: return
    _TOUCH[u.id] = now
    c = db(); c.execute("UPDATE users SET username=?, first_name=?, last_seen=?, blocked=0 WHERE tg_id=?",
                        (u.username, (u.first_name or "")[:64], int(now), u.id)); c.commit(); c.close()

class GateMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        u = data.get("event_from_user")
        if u is None or u.is_bot:
            return await handler(event, data)
        try: await asyncio.to_thread(touch_user, u)
        except Exception: pass
        if isinstance(event, Message):
            if event.chat.type != "private" or event.successful_payment or (event.text or "").startswith("/start"):
                return await handler(event, data)
        elif isinstance(event, CallbackQuery):
            d = event.data or ""
            if d in GATE_FREE_CB or d.startswith("sup:"):
                return await handler(event, data)
        if not gate_on() or is_admin(u.id) or await is_subscribed(u.id):
            return await handler(event, data)
        await send_gate(event)
        return None

dp.message.outer_middleware(GateMiddleware())
dp.callback_query.outer_middleware(GateMiddleware())

@dp.callback_query(F.data == "chk_sub")
async def cb_chk_sub(q: CallbackQuery):
    if not await is_subscribed(q.from_user.id, fresh=True):
        await q.answer("Подписка пока не видна 🤔 Подпишись на канал и нажми ещё раз.", show_alert=True); return
    await q.answer("Спасибо за подписку! 🎉")
    if await maybe_issue_channel_trial(q.from_user.id):
        return
    await smart_edit(q, "✅ <b>Готово — доступ открыт!</b>\n\n" + WELCOME, main_menu(q.from_user.id))

@dp.chat_member()
async def on_chat_member(ev: ChatMemberUpdated):
    if ev.chat.id != channel_id(): return
    uid = ev.new_chat_member.user.id
    was, now_ = _is_inside(ev.old_chat_member), _is_inside(ev.new_chat_member)
    if was == now_: return
    _SUB_CACHE[uid] = (time.time(), now_)
    log_event(uid, "ch_join" if now_ else "ch_leave")
    if now_:
        if await asyncio.to_thread(mark_ch_sub, uid, True):
            log_event(uid, "ch_sub")
            await ref_qualify(uid)
        await maybe_issue_channel_trial(uid)
    else:
        await asyncio.to_thread(mark_ch_sub, uid, False)

# ---------------------------------- рефералка v2 ----------------------------------
def ref_days(): return max(0, cfg_int("ref_bonus_days", 3))
def ref_max(): return max(0, cfg_int("ref_max", 10))
def ref_mode(): return cfg("ref_mode", "join")

def ref_stats(ref_id):
    c = db()
    inv = c.execute("SELECT COUNT(*) FROM users WHERE referrer=?", (ref_id,)).fetchone()[0]
    cr, dd = c.execute("SELECT COUNT(*), COALESCE(SUM(days),0) FROM ref_credits WHERE referrer=? AND days>0",
                       (ref_id,)).fetchone()
    c.close()
    return inv, cr, dd

async def ref_qualify(invitee):
    """Начислить рефереру +N дней за приглашённого (новый юзер прошёл /start и подписку на канал). Лимит — ref_max."""
    if ref_mode() != "join": return
    try:
        u = get_user(invitee)
        if not u or not u["referrer"] or u["referrer"] == invitee: return
        ref = u["referrer"]
        if not get_user(ref): return
        c = db()
        try:
            if c.execute("SELECT 1 FROM ref_credits WHERE invitee=?", (invitee,)).fetchone(): return
            n = c.execute("SELECT COUNT(*) FROM ref_credits WHERE referrer=? AND days>0", (ref,)).fetchone()[0]
            days = ref_days() if n < ref_max() else 0
            c.execute("INSERT INTO ref_credits(invitee,referrer,days,ts) VALUES(?,?,?,?)",
                      (invitee, ref, days, int(time.time())))
            c.commit()
        finally:
            c.close()
        log_event(ref, "ref_credit", f"{invitee}:{days}")
        if not days: return
        db_set(invitee, ref_bonus_given=1)
        _, exp = await add_days(ref, days)
        left = ref_max() - n - 1
        expd = datetime.fromtimestamp(exp).strftime("%d.%m.%Y")
        tail = (f"Пригласи ещё {left} — это ещё <b>+{left * days} {days_word(left * days)}</b> 🔥" if left > 0
                else "Это максимум бонусов за приглашения — спасибо, что рекомендуешь VAYNAH VPN 💙")
        try:
            await bot.send_message(ref, f"🎉 <b>По твоей ссылке пришёл друг — +{days} {days_word(days)}!</b>\n"
                                        f"Подписка активна до {expd}.\n\n{tail}", reply_markup=main_menu(ref))
        except Exception: pass
    except Exception as e:
        log.error(f"ref_qualify {invitee}: {e}")

def ref_screen(uid):
    link = f"https://t.me/{BOT_USERNAME}?start={uid}"
    inv, cr, dd = ref_stats(uid)
    d, mx = ref_days(), ref_max()
    if ref_mode() == "join":
        how = (f"За каждого друга, который запустит бота по твоей ссылке и подпишется на канал, — "
               f"<b>+{d} {days_word(d)}</b> бесплатно.\nМаксимум — {mx} друзей (<b>{d * mx} {days_word(d * mx)}</b>).")
    else:
        how = f"За каждого друга, который оплатит подписку, — <b>+{REF_BONUS_DAYS} {days_word(REF_BONUS_DAYS)}</b>."
    txt = (f"<b>👥 Приглашай друзей — получай дни бесплатно</b>\n\n{how}\n\n"
           f"Твоя ссылка:\n<code>{link}</code>\n\n"
           f"Приглашено: <b>{inv}</b> · засчитано: <b>{cr}/{mx}</b> · получено: <b>+{dd} {days_word(dd)}</b>")
    share = ("https://t.me/share/url?url=" + urllib.parse.quote(link) + "&text=" +
             urllib.parse.quote("📈 VAYNAH VPN — присоединяйся по моей ссылке и получи бонусы 👇"))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(style="primary", text="📤 Отправить другу", url=share)],
        [InlineKeyboardButton(style="primary", text="🏠 Меню", callback_data="menu")]])
    return txt, kb

# ---------------------------------- ЮKassa: 1 ₽ за 3 дня + автопродление ----------------------------------
YK_API = "https://api.yookassa.ru/v3"
YK_FAIL_RU = {"insufficient_funds": "недостаточно средств", "card_expired": "истёк срок карты",
              "permission_revoked": "автоплатёж отозван в банке", "payment_method_restricted": "карта ограничена банком",
              "issuer_unavailable": "банк недоступен", "general_decline": "банк отклонил платёж",
              "expired_on_confirmation": "время оплаты истекло", "3d_secure_failed": "не пройдено подтверждение 3-D Secure",
              "fraud_suspected": "подозрение на мошенничество", "payment_method_limit_exceeded": "превышен лимит по карте",
              "call_issuer": "банк отклонил — позвоните в банк", "country_forbidden": "карта этой страны не принимается",
              "canceled_by_merchant": "отменён магазином", "internal_timeout": "технический сбой"}

def yk_ready(): return bool(cfg("yk_shop_id")) and bool(cfg("yk_secret"))
LAVA_INTRO = {}   # {"id","rub","name"} — разовый оффер Lava «Старт» (находится автоматически)
LAVA_INTRO_SBP = {}  # разовый (ONE_TIME) оффер «Старт» для СБП, если основной — подписочный (Lava не даёт СБП на подписку)
_INTRO_RX = _re.compile(r"(\d+\s*(?:дн|день)|старт|пробн|trial|intro)", _re.I)
_INTRO_DAYS_RX = _re.compile(r"(\d+)\s*(?:дн|день)", _re.I)

async def lava_find_intro():
    """Найти разовый оффер «Старт» в Lava: ID из настроек → по названию (3 дня/старт/пробный) → по цене."""
    global LAVA_INTRO, LAVA_INTRO_SBP
    try:
        data = await lava_products()
    except Exception as e:
        log.error(f"lava intro: {e}"); return LAVA_INTRO
    known = set(LAVA_SBP_OFFERS.values()) | set(LAVA_OFFERS.values())
    want = str(cfg("intro_offer", "") or "").strip()
    found, by_price = None, None
    for item in data.get("items", []):
        for off in item.get("offers", []):
            pr = next((p for p in off.get("prices", []) if p.get("currency") == "RUB"), None)
            if not pr: continue
            rec = {"id": off.get("id"), "rub": int(round(float(pr.get("amount") or 0))),
                   "name": off.get("name") or item.get("title") or "", "one_time": pr.get("periodicity") in (None, "ONE_TIME"),
                   "per": pr.get("periodicity") or "ONE_TIME"}
            if want and rec["id"] == want: found = rec; break
            if want or rec["id"] in known: continue
            if not rec["one_time"] and not _INTRO_DAYS_RX.search(rec["name"]): continue   # подписочный — только «N дней»
            if _INTRO_RX.search(rec["name"] + " " + (item.get("title") or "")): found = found or rec
            elif rec["rub"] == cfg_int("intro_rub", 10): by_price = by_price or rec
        if want and found: break
    rec = found or by_price
    if rec and rec["rub"] >= 1:
        if LAVA_INTRO.get("id") != rec["id"]: log.info(f"lava intro offer: {rec}")
        LAVA_INTRO = rec; PLANS["intro"]["rub"] = rec["rub"]
        mdays = _INTRO_DAYS_RX.search(rec["name"] or "")
        if mdays and 1 <= int(mdays.group(1)) <= 60: PLANS["intro"]["days"] = int(mdays.group(1))
        PLANS["intro"]["stars"] = max(1, round(rec["rub"] * 0.8))
        ip = PLANS["intro"]; ip["title"] = f"🔥 Старт · {ip['days']} {days_word(ip['days'])} за {ip['rub']} ₽"
    else:
        LAVA_INTRO = {}
    # СБП-двойник для подписочного «Старта»: разовый оффер с той же ценой («7 дней»/«Старт») или ID из настроек
    sbp = None
    if LAVA_INTRO and LAVA_INTRO.get("per", "ONE_TIME") != "ONE_TIME":
        want_sbp = str(cfg("intro_sbp_offer", "") or "").strip()
        for item in data.get("items", []):
            for off in item.get("offers", []):
                pr = next((x for x in off.get("prices", []) if x.get("currency") == "RUB"), None)
                if not pr or pr.get("periodicity") not in (None, "ONE_TIME"): continue
                rec = {"id": off.get("id"), "rub": int(round(float(pr.get("amount") or 0))),
                       "name": off.get("name") or item.get("title") or ""}
                if want_sbp:
                    if rec["id"] == want_sbp: sbp = rec
                elif rec["id"] not in known and rec["rub"] == LAVA_INTRO["rub"] \
                        and _INTRO_RX.search(rec["name"] + " " + (item.get("title") or "")):
                    sbp = sbp or rec
    if (sbp or {}).get("id") != LAVA_INTRO_SBP.get("id"): log.info(f"lava intro sbp offer: {sbp}")
    LAVA_INTRO_SBP = sbp or {}
    return LAVA_INTRO

async def intro_offer_worker():
    while True:
        await lava_find_intro()
        await asyncio.sleep(300 if not LAVA_INTRO else 1800)

def intro_ready(): return cfg_on("intro_enabled", True) and bool(LAVA_INTRO.get("id"))
def intro_next():
    p = cfg("intro_next_pid", "1m")
    return p if p in PLANS and p not in SPECIAL_PIDS else "1m"

def trial_allowed(tg_id):
    """Пробный — только тем, кто его не брал, ни разу не платил и сейчас без активной подписки."""
    if not free_trial_visible(): return False
    u = get_user(tg_id)
    if not u: return True
    if u.get("trial_used") or (u.get("expires_at") and u["expires_at"] > time.time()): return False
    r = urow(tg_id, "COALESCE(pay_count,0)")
    return not (r and r[0])

def free_trial_visible():
    # 16.11.2026: переключатель «Бесплатный пробный» в веб-админке теперь реально работает
    v = str(cfg("free_trial", "off"))
    if v == "on": return True
    if v == "auto": return not intro_ready()
    return False

def intro_eligible(tg_id):
    r = urow(tg_id, "COALESCE(pay_count,0), COALESCE(intro_used,0)")
    return bool(r) and not r[0] and not r[1]

def intro_first_only(tg_id):
    """Новым — витрина начинается сразу с «Старта» (по настройке)."""
    return intro_ready() and cfg_on("intro_only_first", True) and intro_eligible(tg_id)

async def yk_req(method, path, body=None, idem=None):
    hdr = {"Content-Type": "application/json"}
    if idem: hdr["Idempotence-Key"] = idem
    auth = aiohttp.BasicAuth(str(cfg("yk_shop_id")), str(cfg("yk_secret")))
    async with aiohttp.ClientSession() as s:
        async with s.request(method, YK_API + path, json=body, auth=auth, headers=hdr,
                             timeout=aiohttp.ClientTimeout(total=30)) as r:
            d = await r.json(content_type=None)
            if r.status >= 400:
                raise RuntimeError(f"yk {r.status}: {(d or {}).get('description') or d}")
            return d

def yk_receipt(tg_id, desc, amount):
    if not cfg_on("yk_receipt", False): return None
    return {"customer": {"email": cfg("yk_receipt_email") or f"tg{tg_id}@example.invalid"},
            "items": [{"description": desc[:128], "quantity": "1.00",
                       "amount": {"value": f"{float(amount):.2f}", "currency": "RUB"},
                       "vat_code": cfg_int("yk_vat_code", 1), "payment_mode": "full_payment",
                       "payment_subject": "service"}]}

def intro_text():
    p = PLANS["intro"]; d = p["days"]; m = PLANS.get("1m", {})
    return (f"🔥 <b>Старт: {d} {days_word(d)} VAYNAH VPN за {p['rub']} ₽</b>\n\n"
            "📶 50 ГБ трафика · 🇩🇪 🇳🇱 🇫🇮 🇷🇺 · до 3 устройств\n\n"
            f"Попробуй все возможности — всего за {p['rub']} ₽. Это разовая оплата: "
            "<b>никаких подписок и автосписаний</b>.\n"
            f"Понравится — продлишь по обычному тарифу (от {m.get('rub', 199)} ₽ в месяц).\n"
            "Первая покупка в VAYNAH VPN — всегда со «Старта», остальные тарифы откроются после него.\n\n"
            "Выбери способ оплаты 👇\n"
            "<i>Предложение доступно один раз — для первой оплаты.</i>")

def intro_kb():
    p = PLANS["intro"]
    rows = ([] if intro_is_sub() and not LAVA_INTRO_SBP else   # СБП на подписку Lava нельзя — нужен разовый оффер-двойник
            [[InlineKeyboardButton(style="primary", text=f"🏦 СБП — {p['rub']} ₽", callback_data="ipay:sbp")]])
    rows += [[InlineKeyboardButton(style="primary", text=f"💳 Картой — {p['rub']} ₽", callback_data="ipay:card")]]
    if p.get("stars"):
        rows.append([InlineKeyboardButton(style="primary", text=f"⭐ {p['stars']} Stars", callback_data="ipay:stars")])
    rows += [[InlineKeyboardButton(style="primary", text="🏠 Меню", callback_data="menu")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)

@dp.callback_query(F.data == "intro")
async def cb_intro(q: CallbackQuery):
    if not intro_ready() or not intro_eligible(q.from_user.id):
        if intro_ready(): await q.answer("«Старт» доступен только для первой оплаты 🙂", show_alert=True)
        txt, kb = buy_screen(q.from_user.id, full=True); await smart_edit(q, txt, kb); await q.answer(); return
    log_event(q.from_user.id, "intro_view")
    await smart_edit(q, intro_text(), intro_kb()); await q.answer()

@dp.callback_query(F.data == "tiers")
async def cb_tiers(q: CallbackQuery):
    txt, kb = buy_screen(q.from_user.id, full=True); await smart_edit(q, txt, kb); await q.answer()

@dp.callback_query(F.data.startswith("ipay:"))
async def cb_intro_pay(q: CallbackQuery):
    if not PAYMENTS_ENABLED:
        await q.answer("Оплата временно отключена. Platega подключим отдельно; сейчас платежи не принимаются.", show_alert=True); return
    uid = q.from_user.id; how = q.data.split(":")[1]; p = PLANS["intro"]
    if not price_ok(p.get("rub", 0)):
        await q.answer(f"Сумма одной оплаты не может превышать {MAX_TX_RUB} ₽", show_alert=True); return
    if not intro_ready():
        await q.answer("Предложение временно недоступно", show_alert=True); return
    if not intro_eligible(uid):
        await q.answer("«Старт» доступен только для первой оплаты 🙂", show_alert=True); return
    log_event(uid, "intro_click", how)
    if how == "stars":
        await bot.send_invoice(chat_id=uid, title=f"VAYNAH VPN · {p['title']}",
                               description=f"Доступ VAYNAH VPN на {p['days']} {days_word(p['days'])}",
                               payload="plan:intro", currency="XTR",
                               prices=[LabeledPrice(label=p["title"], amount=p["stars"])])
        await q.answer(); return
    email = f"tg{uid}@example.invalid"
    try:
        per = LAVA_INTRO.get("per") or "ONE_TIME"
        sub = per != "ONE_TIME"     # оффер внутри подписки Lava → после оплаты сразу отменяем автосписание
        res = {}
        sbp_once = False
        if how == "sbp":
            sbp_once = bool(sub and LAVA_INTRO_SBP.get("id"))
            body = {"email": email, "offerId": LAVA_INTRO_SBP["id"] if sbp_once else LAVA_INTRO["id"],
                    "paymentProvider": "PAY2ME", "currency": "RUB", "paymentMethod": "SBP"}
            if sub and not sbp_once: body["periodicity"] = per
            async with aiohttp.ClientSession() as s:
                async with s.post(f"{LAVA_API}/api/v3/invoice", json=body, headers=_lava_hdr(), timeout=20) as r:
                    res = await r.json(content_type=None)
            if not (res.get("paymentUrl") or res.get("url")):
                log.warning(f"lava intro sbp fallback: {str(res)[:300]}"); res = {}; sbp_once = False
        if not res:   # карта (или СБП недоступен для оффера) — страница Lava со всеми способами
            if sub:
                res = await lava_create(LAVA_INTRO["id"], email, per)
            else:
                body = {"email": email, "offerId": LAVA_INTRO["id"], "currency": "RUB"}
                async with aiohttp.ClientSession() as s:
                    async with s.post(f"{LAVA_API}/api/v3/invoice", json=body, headers=_lava_hdr(), timeout=20) as r:
                        res = await r.json(content_type=None)
        url = res.get("paymentUrl") or res.get("url") or (res.get("data") or {}).get("url")
        inv_id = res.get("id") or res.get("invoiceId")
    except Exception as e:
        log.error(f"lava intro create: {e}"); await q.answer("Платёж временно недоступен, попробуй через минуту", show_alert=True); return
    if not url or not inv_id:
        log.error(f"lava intro {how}: {res}"); await q.answer("Ошибка создания платежа", show_alert=True); return
    if sbp_once: intro_once_mark(inv_id)   # разовый платёж — отменять автопродление не нужно
    pending_add(inv_id, "lava", uid, "intro")
    asyncio.create_task(lava_watch(uid, inv_id, "intro"))
    lbl = "🏦 Оплатить через СБП" if how == "sbp" else "💳 Оплатить картой"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(style="primary", text=f"{lbl} — {p['rub']} ₽", url=url)],
                                               [InlineKeyboardButton(style="primary", text="⬅️ Назад", callback_data="intro")]])
    await smart_edit(q, f"<b>{p['title']}</b>\n\nРазовая оплата {p['rub']} ₽, без автосписаний.\n"
                        "Нажми кнопку ниже — после оплаты доступ откроется автоматически, ключ придёт сюда.", kb)
    await q.answer()

async def yk_watch(tg_id, pay_id):
    for _ in range(120):          # ~30 мин
        await asyncio.sleep(15)
        try:
            obj = await yk_req("GET", f"/payments/{pay_id}")
            st = obj.get("status")
            if st == "succeeded":
                await yk_on_success(obj); return
            if st == "canceled":
                pending_done(pay_id); return
        except Exception as e:
            log.error(f"yk watch: {e}")

_yk_lock = asyncio.Lock()
async def yk_on_success(obj):
    """Единая обработка успешного платежа ЮKassa (поллинг/вебхук/автосписание)."""
    async with _yk_lock:
        md = obj.get("metadata") or {}
        try: tg = int(md.get("tg_id") or 0)
        except Exception: tg = 0
        pid, kind = md.get("pid"), md.get("kind")
        if not tg or pid not in PLANS:
            log.error(f"yk success: bad metadata {md}"); return False
        amt = float((obj.get("amount") or {}).get("value") or 0)
        prov = "Автоплатёж (карта)" if kind == "renew" else "Карта · ЮKassa"
        ok = await fulfill_payment(tg, pid, prov, order_id=obj.get("id"), amount=amt)
        pm = obj.get("payment_method") or {}
        if ok and kind == "intro":
            db_set(tg, intro_used=1)
            if pm.get("saved") and pm.get("id"):
                card = pm.get("card") or {}
                card_txt = f"{card.get('card_type') or 'Карта'} •• {card.get('last4') or '????'}"
                fp = f"{card.get('first6','')}{card.get('last4','')}{card.get('expiry_month','')}{card.get('expiry_year','')}"
                nx = intro_next(); u = get_user(tg); now = int(time.time())
                nxt_at = int((u["expires_at"] if u and u["expires_at"] else now) - 3600)
                c = db()
                dup = c.execute("SELECT tg_id FROM autopay WHERE fp=? AND tg_id!=?", (fp, tg)).fetchall() if fp.strip() else []
                c.execute("INSERT OR REPLACE INTO autopay(tg_id,provider,method_id,card,fp,pid,amount,next_at,active,fails,"
                          "created_at,last_try,last_err,rem_at,off_at) VALUES(?,?,?,?,?,?,?,?,1,0,?,0,NULL,0,NULL)",
                          (tg, "yk", pm["id"], card_txt, fp, nx, PLANS[nx]["rub"], nxt_at, now))
                c.commit(); c.close()
                log_event(tg, "autopay_on", card_txt)
                if dup:
                    flag_abuse(tg, f"1₽-старт повторно с той же картой (уже у {', '.join(str(d[0]) for d in dup)})")
                    await notify_admins(f"⚠️ 1₽-старт: карта {card_txt} уже использовалась у "
                                        f"{', '.join(str(d[0]) for d in dup)} — новый аккаунт <code>{tg}</code>")
                try:
                    await bot.send_message(tg, f"🔁 <b>Автопродление подключено</b> — {_html.escape(card_txt)}\n"
                                               f"Следующее списание: <b>{datetime.fromtimestamp(nxt_at).strftime('%d.%m.%Y')}</b> — "
                                               f"{PLANS[nx]['rub']} ₽ за {PLANS[nx]['days']} дней.\n"
                                               f"Напомним за сутки. Отключить можно в «🔑 Моя подписка».")
                except Exception: pass
        if ok and kind == "renew":
            c = db(); c.execute("UPDATE autopay SET fails=0, last_err=NULL WHERE tg_id=?", (tg,)); c.commit(); c.close()
        return ok

def autopay_get(tg_id):
    c = db(); r = c.execute("SELECT tg_id,provider,method_id,card,pid,amount,next_at,active,fails,last_err "
                            "FROM autopay WHERE tg_id=?", (tg_id,)).fetchone(); c.close()
    if not r: return None
    return dict(zip(("tg_id", "provider", "method_id", "card", "pid", "amount", "next_at", "active", "fails", "last_err"), r))

def autopay_off(tg_id, by="user"):
    c = db(); c.execute("UPDATE autopay SET active=0, method_id=NULL, off_at=? WHERE tg_id=?", (int(time.time()), tg_id))
    c.commit(); c.close()
    log_event(tg_id, "autopay_off", by)

def autopay_line(tg_id):
    ap = autopay_get(tg_id)
    if not ap or not ap["active"]: return ""
    when = datetime.fromtimestamp(ap["next_at"]).strftime("%d.%m.%Y") if ap["next_at"] else "—"
    return (f"🔁 Автопродление: <b>включено</b> · {_html.escape(ap['card'] or 'карта')}\n"
            f"Следующее списание: {when} — {ap['amount']} ₽\n")

@dp.callback_query(F.data == "autopay")
async def cb_autopay(q: CallbackQuery):
    ap = autopay_get(q.from_user.id)
    if not ap or not ap["active"]:
        await q.answer("Автопродление не подключено", show_alert=True); return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(style="primary", text="❌ Отключить автопродление", callback_data="ap_off")],
        [InlineKeyboardButton(style="primary", text="🏠 Меню", callback_data="menu")]])
    await smart_edit(q, "<b>🔁 Автопродление</b>\n\n" + autopay_line(q.from_user.id), kb); await q.answer()

@dp.callback_query(F.data == "ap_off")
async def cb_ap_off(q: CallbackQuery):
    u = get_user(q.from_user.id)
    exp = datetime.fromtimestamp(u["expires_at"]).strftime("%d.%m.%Y") if u and u["expires_at"] else "—"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(style="primary", text="✅ Да, отключить", callback_data="ap_off_yes")],
        [InlineKeyboardButton(style="primary", text="⬅️ Оставить включённым", callback_data="menu")]])
    await smart_edit(q, f"<b>Отключить автопродление?</b>\n\nДоступ сохранится до <b>{exp}</b>, "
                        f"списаний больше не будет. Продлить потом можно любым способом, в том числе по СБП.", kb)
    await q.answer()

@dp.callback_query(F.data == "ap_off_yes")
async def cb_ap_off_yes(q: CallbackQuery):
    autopay_off(q.from_user.id)
    await smart_edit(q, "✅ <b>Автопродление отключено.</b>\nБольше никаких списаний. Привязка карты удалена.",
                     main_menu(q.from_user.id))
    await q.answer("Отключено")
    try: await notify_admins(f"🔕 Автопродление отключил <code>{q.from_user.id}</code>")
    except Exception: pass

@dp.message(Command("autopay"))
async def autopay_cmd(m: Message):
    ap = autopay_get(m.from_user.id)
    if not ap or not ap["active"]:
        await m.answer("🔁 Автопродление не подключено — списаний нет.", reply_markup=main_menu(m.from_user.id)); return
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(style="primary", text="❌ Отключить автопродление", callback_data="ap_off")]])
    await m.answer("<b>🔁 Автопродление</b>\n\n" + autopay_line(m.from_user.id), reply_markup=kb)

AP_BACKOFF = [0, 6 * 3600, 12 * 3600, 24 * 3600]     # повторы после неудачи
AP_MAX_FAILS = 4

async def autopay_charge(tg, ap):
    p = PLANS.get(ap["pid"]) or PLANS["1m"]
    amount = int(ap["amount"] or p["rub"])
    body = {"amount": {"value": f"{float(amount):.2f}", "currency": "RUB"}, "capture": True,
            "payment_method_id": ap["method_id"],
            "description": f"VAYNAH VPN: автопродление {p['title']}"[:128],
            "metadata": {"tg_id": str(tg), "pid": ap["pid"], "kind": "renew"}}
    rc = yk_receipt(tg, body["description"], amount)
    if rc: body["receipt"] = rc
    idem = f"zpn-renew-{tg}-{int(ap['next_at'] or 0)}-{int(ap['fails'] or 0)}"
    c = db(); c.execute("UPDATE autopay SET last_try=? WHERE tg_id=?", (int(time.time()), tg)); c.commit(); c.close()
    try:
        res = await yk_req("POST", "/payments", body, idem=idem)
    except Exception as e:
        res = {"status": "canceled", "cancellation_details": {"reason": "internal_timeout"}, "_err": str(e)}
        log.error(f"autopay {tg}: {e}")
    st = res.get("status")
    if st == "succeeded":
        await yk_on_success(res); return
    if st in ("pending", "waiting_for_capture"):
        pending_add(res.get("id"), "yk", tg, ap["pid"]); return
    reason = (res.get("cancellation_details") or {}).get("reason") or "unknown"
    fails = int(ap["fails"] or 0) + 1
    hard = reason in ("permission_revoked", "card_expired", "country_forbidden")
    c = db(); c.execute("UPDATE autopay SET fails=?, last_err=? WHERE tg_id=?", (fails, reason, tg)); c.commit(); c.close()
    log_event(tg, "autopay_fail", reason)
    off = hard or fails >= AP_MAX_FAILS
    if off: autopay_off(tg, "system:" + reason)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(style="primary", text="🔄 Продлить вручную (СБП/карта)", callback_data="buy")]])
    why = YK_FAIL_RU.get(reason, "платёж отклонён")
    tail = ("Автопродление отключено — продли вручную любым удобным способом."
            if off else "Попробуем ещё раз позже. Можно продлить вручную прямо сейчас:")
    try:
        await bot.send_message(tg, f"⚠️ <b>Не удалось продлить подписку автоматически</b> ({why}).\n{tail}", reply_markup=kb)
    except Exception: pass
    if fails == 1 or off:
        try: await notify_admins(f"💳❌ Автосписание {amount} ₽ не прошло: <code>{tg}</code> — {why}"
                                 + (" · автопродление выключено" if off else ""))
        except Exception: pass

async def autopay_worker():
    await asyncio.sleep(90)
    while True:
        try:
            if yk_ready():
                now = time.time()
                c = db()
                rows = c.execute("SELECT a.tg_id,a.provider,a.method_id,a.card,a.pid,a.amount,a.next_at,a.active,a.fails,"
                                 "a.last_err,a.last_try,a.rem_at,u.expires_at FROM autopay a JOIN users u ON u.tg_id=a.tg_id "
                                 "WHERE a.active=1 AND a.method_id IS NOT NULL").fetchall()
                c.close()
                for r in rows:
                    ap = dict(zip(("tg_id", "provider", "method_id", "card", "pid", "amount", "next_at", "active",
                                   "fails", "last_err"), r[:10]))
                    tg, last_try, rem_at, exp = r[0], r[10] or 0, r[11] or 0, r[12] or 0
                    due = int((exp or now) - 3600)          # списание за час до окончания доступа
                    if due != ap["next_at"]:
                        c = db(); c.execute("UPDATE autopay SET next_at=? WHERE tg_id=?", (due, tg)); c.commit(); c.close()
                        ap["next_at"] = due
                    if 0 < due - now <= 86400 and rem_at != due:
                        p = PLANS.get(ap["pid"]) or PLANS["1m"]
                        kb = InlineKeyboardMarkup(inline_keyboard=[
                            [InlineKeyboardButton(style="primary", text="❌ Отключить автопродление", callback_data="ap_off")]])
                        try:
                            await bot.send_message(tg, f"🔔 <b>Завтра автопродление VAYNAH VPN</b>\n"
                                                       f"Спишем {ap['amount']} ₽ с {_html.escape(ap['card'] or 'карты')} "
                                                       f"за {p['days']} дней. Ничего делать не нужно — доступ продлится сам.",
                                                   reply_markup=kb)
                        except Exception: pass
                        c = db(); c.execute("UPDATE autopay SET rem_at=? WHERE tg_id=?", (due, tg)); c.commit(); c.close()
                    if due > now: continue
                    if now - exp > 7 * 86400:               # доступ давно истёк — не списываем «вдогонку»
                        autopay_off(tg, "system:stale"); continue
                    fails = int(ap["fails"] or 0)
                    if now - last_try < AP_BACKOFF[min(fails, len(AP_BACKOFF) - 1)] or now - last_try < 600:
                        continue
                    await autopay_charge(tg, ap)
                    await asyncio.sleep(1)
        except Exception as e:
            log.error(f"autopay worker: {e}")
        await asyncio.sleep(300)

async def yk_webhook(request):
    try: data = await request.json()
    except Exception: return web.Response(text="ok")
    obj = (data or {}).get("object") or {}
    pay_id = obj.get("id")
    log.info(f"YK HOOK: {data.get('event')} {pay_id}")
    if pay_id and str(data.get("event", "")).startswith("payment."):
        try:
            real = await yk_req("GET", f"/payments/{pay_id}")    # не верим телу — перепроверяем в API
            if real.get("status") == "succeeded":
                await yk_on_success(real)
            elif real.get("status") == "canceled":
                pending_done(pay_id)
        except Exception as e:
            log.error(f"yk hook: {e}")
            return web.Response(status=500, text="retry")
    return web.Response(text="ok")

# ---------------------------------- рассылки (движок; UI — в веб-админке) ----------------------------------
BC_DIR = "/opt/zpnbot/bc"
SEGMENTS = {
    "all":        ("Все пользователи", "1=1"),
    "active":     ("С активной подпиской", "expires_at>:now AND COALESCE(revoked,0)=0"),
    "no_sub":     ("Без активной подписки", "(expires_at IS NULL OR expires_at<=:now OR COALESCE(revoked,0)=1)"),
    "expired":    ("Подписка закончилась", "expires_at IS NOT NULL AND expires_at<=:now"),
    "expiring":   ("Заканчивается в 3 дня", "expires_at>:now AND expires_at<=:now+259200"),
    "paid":       ("Платили хоть раз", "COALESCE(pay_count,0)>0"),
    "never_paid": ("Ни разу не платили", "COALESCE(pay_count,0)=0"),
    "trial_nopay": ("Брали пробный, не оплатили", "trial_used=1 AND COALESCE(pay_count,0)=0"),
    "no_channel": ("Не подписаны на канал", "COALESCE(ch_sub,0)=0"),
    "admins":     ("Только админы (тест)", "tg_id IN (:admins)"),
}

def seg_where(seg):
    w = SEGMENTS.get(seg, SEGMENTS["all"])[1]
    now = int(time.time())
    w = w.replace(":now", str(now)).replace(":admins", ",".join(str(a) for a in admin_ids()) or "0")
    return f"({w}) AND COALESCE(blocked,0)=0"

def seg_ids(seg):
    c = db(); ids = [r[0] for r in c.execute(f"SELECT tg_id FROM users WHERE {seg_where(seg)} ORDER BY tg_id").fetchall()]
    c.close(); return ids

def seg_counts():
    c = db(); out = {}
    for k, (title, _) in SEGMENTS.items():
        out[k] = {"title": title, "count": c.execute(f"SELECT COUNT(*) FROM users WHERE {seg_where(k)}").fetchone()[0]}
    c.close(); return out

_BC_RUN = {}     # bid -> task
_BC_CANCEL = set()

def bc_markup(btn_text, btn_url):
    if btn_text and btn_url:
        if btn_url.startswith(f"https://{SUB_DOMAIN}/game"):   # мини-игра — открываем как Mini App (с авторизацией Telegram)
            return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(style="primary", text=btn_text[:64], web_app=WebAppInfo(url=btn_url))]])
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(style="primary", text=btn_text[:64], url=btn_url)]])
    return None

async def bc_send_one(chat_id, text, photo, kb, file_id_box):
    if photo and photo.lower().endswith(".mp4"):   # видео-рассылка
        src = file_id_box[0] or FSInputFile(photo)
        th = photo[:-4] + ".jpg"
        extra = {} if file_id_box[0] else ({"thumbnail": FSInputFile(th)} if os.path.exists(th) else {})
        m = await bot.send_video(chat_id, src, caption=text or None, reply_markup=kb, supports_streaming=True,
                                 width=1080, height=1920, **extra)
        if not file_id_box[0] and m.video: file_id_box[0] = m.video.file_id
    elif photo:
        src = file_id_box[0] or FSInputFile(photo)
        m = await bot.send_photo(chat_id, src, caption=text or None, reply_markup=kb)
        if not file_id_box[0] and m.photo: file_id_box[0] = m.photo[-1].file_id
    else:
        await bot.send_message(chat_id, text, reply_markup=kb)

async def bc_test(by_id, text, photo, btn_text, btn_url):
    await bc_send_one(by_id, text, photo, bc_markup(btn_text, btn_url), [None])

def bc_create(by_id, seg, text, photo, btn_text, btn_url, ids=None):
    os.makedirs(BC_DIR, exist_ok=True)
    rec = ids if ids is not None else seg_ids(seg)
    c = db()
    cur = c.execute("INSERT INTO broadcasts(ts,by_id,segment,text,photo,btn_text,btn_url,total,status) VALUES(?,?,?,?,?,?,?,?,?)",
                    (int(time.time()), by_id, seg, text, photo, btn_text, btn_url, len(rec), "running"))
    bid = cur.lastrowid; c.commit(); c.close()
    json.dump(rec, open(f"{BC_DIR}/{bid}.json", "w"))
    _BC_RUN[bid] = asyncio.create_task(bc_run(bid))
    return bid, len(rec)

async def bc_run(bid):
    c = db(); r = c.execute("SELECT text,photo,btn_text,btn_url,pos,sent,failed,blocked FROM broadcasts WHERE id=?", (bid,)).fetchone(); c.close()
    if not r: return
    text, photo, bt, bu, pos, sent, failed, blocked = r
    try: rec = json.load(open(f"{BC_DIR}/{bid}.json"))
    except Exception: rec = []
    kb = bc_markup(bt, bu); fid = [None]; status = "done"
    def save(st=None):
        cc = db()
        cc.execute("UPDATE broadcasts SET pos=?,sent=?,failed=?,blocked=?" + (",status=?,finished_at=?" if st else "") + " WHERE id=?",
                   (pos, sent, failed, blocked) + ((st, int(time.time())) if st else ()) + (bid,))
        cc.commit(); cc.close()
    while pos < len(rec):
        if bid in _BC_CANCEL:
            status = "cancelled"; break
        uid = rec[pos]
        for attempt in range(3):
            try:
                await bc_send_one(uid, text, photo, kb, fid); sent += 1; break
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
            except TelegramForbiddenError:
                failed += 1; blocked += 1; db_set(uid, blocked=1); break
            except TelegramBadRequest as e:
                failed += 1
                if "chat not found" in str(e).lower() or "deactivated" in str(e).lower(): db_set(uid, blocked=1)
                break
            except Exception as e:
                if attempt == 2: failed += 1
                else: await asyncio.sleep(2)
        pos += 1
        if pos % 20 == 0: save()
        await asyncio.sleep(0.045)        # ~22 сообщ/с — ниже лимита Telegram
    save(status)
    _BC_RUN.pop(bid, None); _BC_CANCEL.discard(bid)
    try: await notify_admins(f"📣 Рассылка #{bid} {'завершена' if status == 'done' else 'остановлена'}: "
                             f"доставлено {sent}, ошибок {failed} (заблокировали бота: {blocked})")
    except Exception: pass

def bc_resume_all():
    c = db(); ids = [r[0] for r in c.execute("SELECT id FROM broadcasts WHERE status='running'").fetchall()]; c.close()
    for bid in ids:
        _BC_RUN[bid] = asyncio.create_task(bc_run(bid))

# ---------------------------------- вход в веб-админку ----------------------------------
ADMIN_WEB = f"https://{SUB_DOMAIN}/admin/"   # 16.11.2026: было пусто -> кнопка входа не работала

def admin_login_link(tg_id):
    tok = _secrets.token_urlsafe(32)
    c = db()
    c.execute("DELETE FROM admin_links WHERE expires_at<?", (int(time.time()),))
    c.execute("INSERT INTO admin_links(token,tg_id,expires_at,used) VALUES(?,?,?,0)",
              (hashlib.sha256(tok.encode()).hexdigest(), tg_id, int(time.time()) + 600))
    c.commit(); c.close()
    return f"{ADMIN_WEB}login?t={tok}"

async def send_admin_link(chat_id):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(style="primary", text="🖥 Открыть веб-панель", url=admin_login_link(chat_id))]])
    await bot.send_message(chat_id, "🖥 <b>Веб-панель VAYNAH VPN</b>\n\nКнопка ниже — личный вход, действует 10 минут и один раз. "
                                    f"После входа браузер запомнит тебя на 30 дней.\nАдрес панели: {ADMIN_WEB}",
                           reply_markup=kb)

@dp.callback_query(F.data == "adm:web")
async def cb_adm_web(q: CallbackQuery):
    await q.answer("🖥 Отправляю ссылку на веб-панель…")   # 16.11.2026: сразу снимаем «часики»
    if not is_admin(q.from_user.id): return
    await send_admin_link(q.from_user.id)

@dp.message(Command("panel"))
async def panel_cmd(m: Message):
    if not is_admin(m.from_user.id): return
    await send_admin_link(m.from_user.id)


# ---------- Lava вебхук: первая оплата + авто-продления подписки ----------
LAVA_HOOK_USER = ""
LAVA_HOOK_PASS = ""

async def lava_webhook(request):
    expected = "Basic " + base64.b64encode(f"{LAVA_HOOK_USER}:{LAVA_HOOK_PASS}".encode()).decode()
    if request.headers.get("Authorization", "") != expected:
        return web.Response(status=401, text="unauthorized")
    try:
        data = await request.json()
    except Exception:
        data = {}
    log.info(f"LAVA HOOK: {json.dumps(data, ensure_ascii=False)[:600]}")
    try:
        email = (data.get("buyer") or {}).get("email") or data.get("email") or ""
        status = str(data.get("status") or data.get("eventType") or data.get("type") or "").lower()
        amount = None
        for cand in [data.get("amount"),
                     (data.get("amountTotal") or {}).get("amount") if isinstance(data.get("amountTotal"), dict) else None,
                     (data.get("product") or {}).get("amount") if isinstance(data.get("product"), dict) else None,
                     data.get("sum"), data.get("price")]:
            amount = _num(cand)
            if amount: break
        # "paid" узко: НЕ ловим bare "active"/подписочные события — только реальная оплата
        paid = (any(w in status for w in ["complet", "paid", "success"])
                or status in ("subscription-active", "in-progress-completed"))
        if paid and isinstance(email, str) and email.startswith("tg") and "@" in email:
            tg_id = int(email[2:email.index("@")])
            pid = _lava_pid_from_payload(data, amount)   # по офферу+периодичности, затем по сумме
            _off = data.get("offerId") or (data.get("offer") or {}).get("id")
            _once = (LAVA_INTRO_SBP.get("id") and _off == LAVA_INTRO_SBP["id"]) or intro_once_is(data.get("contractId") or data.get("id"))
            if pid == "intro" and intro_is_sub() and not _once:
                parent = data.get("parentContractId") or data.get("contractId") or data.get("id")
                asyncio.create_task(lava_cancel_sub(parent, email))
                if "recurring" in status:   # «Старт» не продлевается сам — повторное списание не выдаём как «Старт»
                    log.error(f"lava hook: recurring по «Старту» {parent} — отменяю, доступ не выдан")
                    await notify_admins(f"⚠️ Lava списала «Старт» повторно у <code>{tg_id}</code> ({amount} ₽) — подписка отменена, проверь возврат")
                    pid = None
            if pid:
                order_id = data.get("id") or data.get("invoiceId") or data.get("contractId")
                await fulfill_payment(tg_id, pid, "Lava-hook", order_id=order_id, amount=amount)
            else:
                log.error(f"lava hook: не сматчил план (amount={amount}, status={status})")
    except Exception as e:
        log.error(f"lava hook: {e}")
    return web.Response(text="OK")

async def pending_worker():
    """Дожимает незакрытые оплаты (переживает рестарт бота, ловит медленные крипто-подтверждения)."""
    await asyncio.sleep(50)
    while True:
        try:
            c = db()
            rows = c.execute("SELECT order_id, provider, tg_id, pid FROM pending_pays "
                             "WHERE done=0 AND created_at>?", (int(time.time()) - 3 * 86400,)).fetchall()
            c.close()
            for order_id, provider, tg_id, pid in rows:
                try:
                    if provider == "heleket":
                        st = await heleket_status(order_id)
                        status = st.get("result", {}).get("payment_status", "")
                        if status in ("paid", "paid_over"):
                            await fulfill_payment(tg_id, pid, "Heleket", order_id=order_id)
                        elif status in ("cancel", "fail", "system_fail"):
                            pending_done(order_id)
                    elif provider == "yk":
                        if yk_ready():
                            obj = await yk_req("GET", f"/payments/{order_id}")
                            if obj.get("status") == "succeeded":
                                await yk_on_success(obj)
                            elif obj.get("status") == "canceled":
                                pending_done(order_id)
                    elif provider == "platega":
                        if platega_ready():
                            await platega_check(order_id)
                    elif provider == "lava":
                        st = await lava_status(order_id)
                        status = str(st.get("status") or "").lower()
                        if status in ("completed", "paid", "success", "subscription-active", "in-progress-completed"):
                            await fulfill_payment(tg_id, pid, "Lava", order_id=order_id)
                        elif status in ("failed", "cancelled", "expired", "declined"):
                            pending_done(order_id)
                except Exception as e:
                    log.error(f"pending {provider} {order_id}: {e}")
        except Exception as e:
            log.error(f"pending worker: {e}")
        await asyncio.sleep(120)

# ---------- фоновая досинхронизация ключей на ноды (если при выдаче нода была недоступна) ----------
async def sync_worker():
    await asyncio.sleep(70)
    while True:
        try:
            c = db()
            rows = c.execute("SELECT tg_id, uuid, COALESCE(sync_tries,0) FROM users WHERE COALESCE(needs_sync,0)=1 "
                             "AND uuid IS NOT NULL AND expires_at>? AND COALESCE(revoked,0)=0",
                             (time.time(),)).fetchall()
            c.close()
            for tg_id, uuid_, tries in rows:
                failed = await asyncio.to_thread(xray_add_client, uuid_)
                if not failed:
                    db_set(tg_id, needs_sync=0, sync_tries=0)
                    log.info(f"sync: user {tg_id} доведён на все ноды")
                elif tries + 1 >= 30:            # ~1.5ч нода мертва — не крутим вечно (юзер жив на здоровых)
                    db_set(tg_id, needs_sync=0, sync_tries=0)
                    log.error(f"sync: user {tg_id} — сдаюсь после 30 попыток, ноды {failed} мертвы")
                    if ADMIN_ID:
                        try: await notify_admins( f"⚠️ Юзер {tg_id} не доведён на {failed} (нода долго лежит). Проверь ноду.")
                        except Exception: pass
                else:
                    db_set(tg_id, sync_tries=tries + 1)
        except Exception as e:
            log.error(f"sync worker: {e}")
        await asyncio.sleep(180)

def get_user_by_uuid(uuid_):
    c = db(); r = c.execute("SELECT tg_id, plan, expires_at FROM users WHERE uuid=?", (uuid_,)).fetchone(); c.close()
    return r  # (tg_id, plan, expires_at) | None

# ---------- 🖥 личный кабинет /me/<uuid> — вёрстка в me_cabinet.py (03.11.2026) ----------
import me_cabinet
_ME_CACHE = {}
_ME_HDRS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
            "X-Robots-Tag": "noindex, nofollow", "X-Content-Type-Options": "nosniff"}

def _me_cget(key, ttl):
    v = _ME_CACHE.get(key)
    return v[1] if v and time.time() - v[0] < ttl else None

def _me_cput(key, val):
    if len(_ME_CACHE) > 3000:
        _ME_CACHE.clear()
    _ME_CACHE[key] = (time.time(), val)
    return val

def _me_db(uuid_):
    """Данные для кабинета из БД бота: подписка + рефералы."""
    c = db()
    try:
        r = c.execute("SELECT tg_id, plan, expires_at, revoked FROM users WHERE uuid=?", (uuid_,)).fetchone()
        if not r:
            return None
        inv = (c.execute("SELECT COUNT(*) FROM users WHERE referrer=?", (r[0],)).fetchone()[0],
               c.execute("SELECT COUNT(*) FROM ref_credits WHERE referrer=? AND days>0", (r[0],)).fetchone()[0])
        return {"tg_id": r[0], "plan": r[1] or "", "exp": r[2] or 0, "revoked": r[3] or 0,
                "invited": inv[0] or 0, "inv_paid": inv[1] or 0}
    finally:
        c.close()

async def _me_panel(path, timeout=4.0):
    """GET к API Remnawave (те же креды, что у rw_node_online). None — не удалось."""
    try:
        if not RW_API or not RW_TOKEN: return None
        hdr = {"Authorization": "Bearer " + RW_TOKEN, "Accept": "application/json", "User-Agent": "VAYNAH VPN-bot"}
        async with aiohttp.ClientSession() as s:
            async with s.get(RW_API + path, headers=hdr,
                             timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                if r.status != 200:
                    return None
                d = await r.json(content_type=None)
        return d.get("response") if isinstance(d, dict) else None
    except Exception as e:
        log.warning(f"me_panel {path.split('/')[1]}: {type(e).__name__}")
        return None

async def _me_nodes():
    v = _me_cget("nodes", 30)
    if v is None:
        d = await _me_panel("/nodes")
        v = _me_cput("nodes", {n.get("name"): bool(n.get("isConnected")) and not n.get("isDisabled")
                               for n in d} if isinstance(d, list) else {})
    return v

async def _me_ru():
    v = _me_cget("ru443", 30)
    if v is None:
        v = _me_cput("ru443", bool(await _ruip_tcp("ru.vertuwpn.ru", 8441, 3)))
    return v

async def _me_user(uuid_):
    short = sub_url(uuid_).rsplit("/", 1)[1]
    v = _me_cget("u:" + short, 20)
    if v is None:
        d = await _me_panel("/users/by-short-uuid/" + short)
        v = {}
        if isinstance(d, dict):
            t = d.get("userTraffic") or {}
            v = {"used": t.get("usedTrafficBytes"), "life": t.get("lifetimeUsedTrafficBytes"),
                 "online_at": t.get("onlineAt"), "first_at": t.get("firstConnectedAt"), "status": d.get("status"),
                 "limit": d.get("trafficLimitBytes")}
        v = _me_cput("u:" + short, v)
    return v

def _me_locs(nodes, ru):
    """Статус 5 локаций. Всё идёт через РФ-вход: RU → DE/FI, NL — через DE."""
    r = bool(ru)
    if nodes:
        g = lambda n: bool(nodes.get(n))
        # 16.11.2026: ноды IngVertu-FI/ES/DE/NL; RU-вход = релей ru.vertuwpn.ru
        g = lambda cc: any(v for k, v in nodes.items() if str(k).upper().endswith("-" + cc))
        fi, es, de, nl = g("FI"), g("ES"), g("DE"), g("NL")
        return {"auto": es or de or nl, "de": de, "fi": fi, "nl": nl, "es": es, "ru": r}
    return {"auto": r, "de": r, "fi": r, "nl": r, "es": r, "ru": r}

async def me_page(request):
    """🖥 Личный кабинет /me/<uuid> (и /app/<uuid>). ?fmt=json — живой статус для автообновления."""
    u = request.match_info.get("uuid", "")
    row = await asyncio.to_thread(_me_db, u) if _re.match(r'^[0-9a-fA-F-]{32,40}$', u) else None
    if not row:
        return web.Response(status=404, text=me_cabinet.not_found_html(BOT_USERNAME),
                            content_type="text/html", headers=_ME_HDRS)
    nodes, ru, pu = await asyncio.gather(_me_nodes(), _me_ru(), _me_user(u))
    p = PLANS.get(row["plan"]) or {}
    ctx = dict(row, sub=sub_url(u), bot=BOT_USERNAME, support=BOT_USERNAME,
               plan_days=p.get("days") or 30, devices=p.get("devices") or 3, tier=p.get("tier") or "std",
               trial=row["plan"] in ("trial", "intro", "channel_trial"), ref_days=ref_days(), ref_max=ref_max(),
               min_rub=min([x["rub"] for k, x in PLANS.items() if x.get("rub") and k not in ("trial", "intro")] or [199]),
               locs=_me_locs(nodes, ru), panel=pu, now=time.time())
    try:
        if request.query.get("fmt") == "json":
            return web.json_response(me_cabinet.live_json(ctx), headers=_ME_HDRS)
        html = me_cabinet.render_page(ctx)
    except Exception as e:
        log.exception(f"me_page: {e}")
        return web.Response(status=500, text="Временная ошибка — обновите страницу через минуту", headers=_ME_HDRS)
    return web.Response(text=html, content_type="text/html", headers=_ME_HDRS)

async def legacy_conf_redirect(request):
    """Keep previously copied /conf links functional by redirecting to Remnawave subscription."""
    raw_uuid = request.match_info.get("uuid", "")
    try:
        normalized = str(uuid.UUID(raw_uuid))
    except (ValueError, AttributeError):
        return web.Response(status=404, text="not found")
    return web.HTTPFound(location=sub_url(normalized))



# ---------- 16.11.2026: здоровье RU-входа (RU-сервер сам шлёт отчёт: NL↔RU напрямую режется) + заглушка на корне ----------
RELAY_HEALTH_FILE = "/opt/zpnbot/relay_health.json"
async def relay_health_hook(request):
    if request.headers.get("X-Relay-Key", "") != os.environ.get("INGVERTU_RELAY_SECRET", "~"):
        return web.Response(status=403, text="forbidden")
    try:
        d = await request.json()
        d["ts"] = int(time.time())
        with open(RELAY_HEALTH_FILE, "w") as f: json.dump(d, f)
    except Exception as e:
        return web.Response(status=400, text=str(e)[:80])
    return web.Response(text="ok")

LEGAL_BASE = "https://sub.vertuwpn.ru"   # 16.11.2026: документы для платёжного провайдера
SUPPORT_USER = "helpingvpn"
async def legal_page(request):
    slug = request.path.strip("/")
    slug = {"agreement": "terms", "policy": "privacy"}.get(slug, slug)
    try: html = open(f"/opt/zpnbot/legal/{slug}.html", encoding="utf-8").read()
    except Exception: return web.Response(status=404, text="not found")
    return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "public, max-age=300"})

async def stub_index(request):
    try: html = open("/opt/zpnbot/stub_index.html", encoding="utf-8").read()
    except Exception: html = "<!doctype html><title>Башни Кавказа</title><h1>Башни Кавказа</h1>"
    return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "public, max-age=600"})

async def start_webapp():
    app = web.Application()
    # /lava-hook отключён 2026-11-25: пустые LAVA_HOOK_USER/PASS позволяли подделать оплату
    app.router.add_get("/me/{uuid}", me_page)
    app.router.add_post("/relay-health", relay_health_hook)
    for _slug in ("terms", "privacy", "tariffs", "agreement", "policy"):
        app.router.add_get("/" + _slug, legal_page)
    app.router.add_get("/", stub_index)
    app.router.add_get("/conf/{uuid}", legacy_conf_redirect)
    app.router.add_get("/conf/{uuid}/{geo}", legacy_conf_redirect)
    app.router.add_get("/app/happ/{s}", happ_page)
    app.router.add_get("/app/incy/{s}", incy_page)
    app.router.add_get("/app/connect/{s}", connect_page)
    app.router.add_get("/app/{uuid}", me_page)
    app.router.add_post("/yk-hook", yk_webhook)
    app.router.add_post("/platega-hook", platega_webhook)
    app.router.add_get("/pay/{tx}", pay_page)
    app.router.add_get("/pay/{tx}/status", pay_status)
    app.router.add_get("/project", project_page)
    app.router.add_get("/static/v/{f}", static_v)
    app.router.add_get("/static/p/{f}", static_p)
    app.router.add_get("/yk-hook", lambda r: web.Response(text="ok"))
    try:
        import admin_web
        admin_web.setup(app, sys.modules[__name__])
    except Exception as e:
        log.exception(f"admin_web: {e}")
    try:   # 🌐 статистика сайта example.invalid + ежедневная воронка (/site/hit, /go/{tag}, /funnel)
        import site_stats
        site_stats.setup(app, sys.modules[__name__]); site_stats.start_worker()
    except Exception as e:
        log.exception(f"site_stats: {e}")
    runner = web.AppRunner(app); await runner.setup()
    await web.TCPSite(runner, WEBAPP_BIND, 8090).start()
    log.info("lava webhook on :8090")

async def main():
    os.makedirs("/opt/zpnbot", exist_ok=True)
    # Bind HTTP before synchronous DB/startup work: a slow migration must not
    # leave systemd active while Telegram polling and the admin endpoint are down.
    await start_webapp()
    db().close()
    seed_bills()
    apply_settings()
    growth_init()
    asyncio.create_task(expiry_worker())
    asyncio.create_task(traffic_limit_worker())
    asyncio.create_task(monitor_worker())
    asyncio.create_task(bills_worker())
    asyncio.create_task(user_reminder_worker())
    asyncio.create_task(devices_worker())
    asyncio.create_task(auto_worker())
    asyncio.create_task(pending_worker())
    asyncio.create_task(payment_ui_worker())
    asyncio.create_task(autopay_worker())
    asyncio.create_task(intro_offer_worker())
    asyncio.create_task(smart_push_worker())   # 16.11.2026: автоворонка; вкл/выкл — «Умные авто-рассылки» в веб-админке
    try:
        await asyncio.wait_for(bot.set_my_commands([
            BotCommand(command="menu", description="Главное меню VAYNAH"),
            BotCommand(command="start", description="Перезапустить VAYNAH")
        ]), timeout=15)
    except Exception as e: log.error(f"set_my_commands: {e}")
    bc_resume_all()
    log.info("VAYNAH VPN bot started")
    await dp.start_polling(bot, allowed_updates=sorted(set(dp.resolve_used_update_types()) | {"widget_query", "callback_query", "message"}))

if __name__ == "__main__":
    asyncio.run(main())
