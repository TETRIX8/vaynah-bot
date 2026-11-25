"""05.11.2026: статистика сайта example.invalid + ежедневный отчёт воронки в бот.
Маршруты (через nginx NL example.invalid): POST /site/hit (beacon), GET /go/{tag} (клик в бот -> t.me/?start=site_tag),
POST /site/crawl (ночная сводка роботов от NL). Отчёт — каждый день в 09:00 МСК всем админам, команда /funnel."""
import asyncio, hashlib, json, time, re, os, urllib.parse
from datetime import datetime, timedelta, timezone
from aiohttp import web
B = None
MSK = timezone(timedelta(hours=3))
BOT_USER = "MyVainakhBot"
CRAWL_KEY_FILE = "/opt/zpnbot/.crawl_key"
BOTS_RE = re.compile(r"bot|crawl|spider|slurp|preview|headless|python|curl|wget|lighthouse|monitor", re.I)

def db():
    c = B.db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS site_hits(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, day TEXT, path TEXT, src TEXT, ref TEXT, vid TEXT, mob INTEGER);
    CREATE INDEX IF NOT EXISTS ix_sh_day ON site_hits(day);
    CREATE TABLE IF NOT EXISTS site_clicks(id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, day TEXT, tag TEXT, vid TEXT);
    CREATE INDEX IF NOT EXISTS ix_sc_day ON site_clicks(day);
    CREATE TABLE IF NOT EXISTS site_crawl(day TEXT, bot TEXT, hits INTEGER, PRIMARY KEY(day, bot));
    """)
    return c

def day_of(ts=None): return datetime.fromtimestamp(ts or time.time(), MSK).strftime("%Y-%m-%d")

def _ip(req): return (req.headers.get("X-Real-IP") or req.remote or "").split(",")[0].strip()

def _vid(req):
    ua = req.headers.get("User-Agent", "")
    return hashlib.sha256(f"{_ip(req)}|{ua}|{day_of()}|zpn".encode()).hexdigest()[:16]

def classify(ref):
    if not ref: return "Прямые"
    h = (urllib.parse.urlparse(ref).hostname or "").lower()
    if not h or h.endswith("example.invalid"): return "Внутренние"
    if "yandex" in h or h.startswith("ya.") or h == "ya.ru": return "Яндекс"
    if "google" in h: return "Google"
    if h.endswith("t.me") or "telegram" in h: return "Telegram"
    if "vk.com" in h or "vk.ru" in h: return "VK"
    if "bing" in h or "duckduckgo" in h or "mail.ru" in h: return "Другие поисковики"
    return "Другие сайты"

async def hit(req):
    try:
        ua = req.headers.get("User-Agent", "")
        if BOTS_RE.search(ua): return web.Response(status=204)
        try: d = json.loads(await req.text() or "{}")
        except Exception: d = {}
        path = str(d.get("p") or "/")[:120]; ref = str(d.get("r") or "")[:300]
        src = classify(ref)
        mob = 1 if re.search(r"Mobi|Android|iPhone", ua) else 0
        c = db(); c.execute("INSERT INTO site_hits(ts,day,path,src,ref,vid,mob) VALUES(?,?,?,?,?,?,?)",
                            (int(time.time()), day_of(), path, src, (urllib.parse.urlparse(ref).hostname or "")[:80], _vid(req), mob))
        c.commit(); c.close()
    except Exception as e:
        B.log.error(f"site hit: {e}")
    return web.Response(status=204, headers={"Cache-Control": "no-store"})

async def go(req):
    tag = re.sub(r"[^A-Za-z0-9_]", "", req.match_info.get("tag", ""))[:40] or "x"
    try:
        if not BOTS_RE.search(req.headers.get("User-Agent", "")):
            c = db(); c.execute("INSERT INTO site_clicks(ts,day,tag,vid) VALUES(?,?,?,?)", (int(time.time()), day_of(), tag, _vid(req)))
            c.commit(); c.close()
    except Exception as e:
        B.log.error(f"site go: {e}")
    raise web.HTTPFound(f"https://t.me/{BOT_USER}?start=site_{tag}"[:96], headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex"})

async def crawl(req):
    try: key = open(CRAWL_KEY_FILE).read().strip()
    except Exception: key = None
    if not key or req.headers.get("X-Key") != key: return web.Response(status=403)
    d = await req.json()
    c = db()
    for bot_, n in (d.get("bots") or {}).items():
        c.execute("INSERT OR REPLACE INTO site_crawl(day,bot,hits) VALUES(?,?,?)", (d["day"], bot_[:40], int(n)))
    c.commit(); c.close()
    return web.json_response({"ok": True})

# ---------------------------------------------------------------- отчёт
def _bounds(day):
    s = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=MSK); return int(s.timestamp()), int((s + timedelta(days=1)).timestamp())

def _pct(a, b): return f"{(100 * a / b):.0f}%" if b else "—"

def _delta(a, b):
    if b == 0: return "" if a == 0 else " 🆕"
    d = a - b
    return f" ({'+' if d >= 0 else ''}{d})"

def stats(day):
    t0, t1 = _bounds(day); c = db(); q = lambda sql, *a: c.execute(sql, a).fetchone()[0] or 0
    s = {}
    s["views"] = q("SELECT COUNT(*) FROM site_hits WHERE day=?", day)
    s["visitors"] = q("SELECT COUNT(DISTINCT vid) FROM site_hits WHERE day=?", day)
    s["mob"] = q("SELECT COUNT(DISTINCT vid) FROM site_hits WHERE day=? AND mob=1", day)
    s["src"] = c.execute("SELECT src, COUNT(DISTINCT vid) FROM site_hits WHERE day=? AND src!='Внутренние' GROUP BY src ORDER BY 2 DESC", (day,)).fetchall()
    s["pages"] = c.execute("SELECT path, COUNT(*) FROM site_hits WHERE day=? GROUP BY path ORDER BY 2 DESC LIMIT 5", (day,)).fetchall()
    s["clicks"] = q("SELECT COUNT(DISTINCT vid) FROM site_clicks WHERE day=?", day)
    s["crawl"] = c.execute("SELECT bot, hits FROM site_crawl WHERE day=? ORDER BY hits DESC", (day,)).fetchall()
    s["new"] = q("SELECT COUNT(*) FROM users WHERE created_at>=? AND created_at<?", t0, t1)
    s["new_site"] = q("SELECT COUNT(*) FROM users WHERE created_at>=? AND created_at<? AND src LIKE 'site_%'", t0, t1)
    s["new_ref"] = q("SELECT COUNT(*) FROM users WHERE created_at>=? AND created_at<? AND referrer IS NOT NULL", t0, t1)
    s["new_tag"] = q("SELECT COUNT(*) FROM users WHERE created_at>=? AND created_at<? AND src IS NOT NULL AND src!='' AND src NOT LIKE 'site_%' AND referrer IS NULL", t0, t1)
    s["trial"] = q("SELECT COUNT(*) FROM users WHERE trial_at>=? AND trial_at<?", t0, t1)
    s["trial_site"] = q("SELECT COUNT(*) FROM users WHERE trial_at>=? AND trial_at<? AND src LIKE 'site_%'", t0, t1)
    s["first"] = q("SELECT COUNT(*) FROM users WHERE first_paid_at>=? AND first_paid_at<?", t0, t1)
    s["first_site"] = q("SELECT COUNT(*) FROM users WHERE first_paid_at>=? AND first_paid_at<? AND src LIKE 'site_%'", t0, t1)
    s["pays"] = q("SELECT COUNT(*) FROM payments WHERE ts>=? AND ts<?", t0, t1)
    s["rub"] = round(q("SELECT SUM(amount_rub) FROM payments WHERE ts>=? AND ts<?", t0, t1))
    s["renew"] = max(0, s["pays"] - s["first"])
    now = int(time.time())
    s["active"] = q("SELECT COUNT(*) FROM users WHERE expires_at>? AND COALESCE(revoked,0)=0", now)
    s["active_paid"] = q("SELECT COUNT(*) FROM users WHERE expires_at>? AND COALESCE(revoked,0)=0 AND COALESCE(pay_count,0)>0", now)
    s["total"] = q("SELECT COUNT(*) FROM users")
    try: s["game"] = q("SELECT COUNT(DISTINCT tg_id) FROM game_runs WHERE started>=? AND started<?", t0, t1)
    except Exception: s["game"] = None
    c.close(); return s

def report_text(day, title=None):
    s = stats(day)
    prev = stats((datetime.strptime(day, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d"))
    dd = datetime.strptime(day, "%Y-%m-%d").strftime("%d.%m.%Y")
    L = [f"📊 <b>{title or 'Воронка IngVertuVpn'} · {dd}</b>", "",
         "🌐 <b>Сайт example.invalid</b>",
         f"Посетители: <b>{s['visitors']}</b>{_delta(s['visitors'], prev['visitors'])} · просмотры {s['views']} · с телефона {_pct(s['mob'], s['visitors'])}",
         f"Нажали «в бот»: <b>{s['clicks']}</b> ({_pct(s['clicks'], s['visitors'])} от посетителей)"]
    if s["src"]: L.append("Откуда: " + " · ".join(f"{k} {v}" for k, v in s["src"]))
    if s["pages"]: L.append("Страницы: " + " · ".join(f"{p} {n}" for p, n in s["pages"][:4]))
    if s["crawl"]: L.append("🕷 Роботы: " + " · ".join(f"{b} {n}" for b, n in s["crawl"]))
    L += ["", "🤖 <b>Бот</b>",
          f"Новые: <b>{s['new']}</b>{_delta(s['new'], prev['new'])} — с сайта {s['new_site']} · по приглашению {s['new_ref']} · по меткам {s['new_tag']} · прочие {max(0, s['new'] - s['new_site'] - s['new_ref'] - s['new_tag'])}",
          f"Взяли пробный: <b>{s['trial']}</b>{_delta(s['trial'], prev['trial'])}",
          f"Первая оплата: <b>{s['first']}</b>{_delta(s['first'], prev['first'])} · продления {s['renew']}",
          f"💰 Выручка: <b>{s['rub']} ₽</b>{_delta(s['rub'], prev['rub'])} ({s['pays']} опл.)"]
    if s["game"] is not None: L.append(f"🎮 Играли: {s['game']}")
    L += ["", "🔻 <b>Воронка сайта</b>",
          f"{s['visitors']} посетили → {s['clicks']} нажали → {s['new_site']} запустили бота → {s['trial_site']} пробный → {s['first_site']} оплатили",
          f"Конверсия сайт → оплата: {_pct(s['first_site'], s['visitors'])}",
          "", f"📦 Сейчас: активных подписок <b>{s['active']}</b> (платных {s['active_paid']}) · всего в боте {s['total']}"]
    return "\n".join(L)

async def send_daily(day=None):
    day = day or (datetime.now(MSK) - timedelta(days=1)).strftime("%Y-%m-%d")
    txt = report_text(day)
    for a in B.admin_ids():
        try: await B.bot.send_message(a, txt, disable_web_page_preview=True)
        except Exception as e: B.log.error(f"funnel report {a}: {e}")

async def worker():
    while True:
        try:
            now = datetime.now(MSK); yday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
            c = db(); r = c.execute("SELECT value FROM settings WHERE key='funnel_sent'").fetchone()
            if now.hour >= 9 and (r[0] if r else None) != yday:
                c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('funnel_sent',?)", (yday,)); c.commit(); c.close()
                await send_daily(yday)
            else: c.close()
        except Exception as e:
            B.log.error(f"funnel worker: {e}")
        await asyncio.sleep(300)

async def cmd_funnel(m):
    if not B.is_admin(m.from_user.id): return
    arg = (m.text or "").split()[1:]
    if arg and arg[0] in ("вчера", "y", "yesterday"):
        day = (datetime.now(MSK) - timedelta(days=1)).strftime("%Y-%m-%d"); t = None
    else:
        day = day_of(); t = "Сегодня (на текущий момент)"
    await m.answer(report_text(day, t), disable_web_page_preview=True)

def setup(app, mod):
    global B
    B = mod
    db().close()
    app.router.add_post("/site/hit", hit)
    app.router.add_post("/site/crawl", crawl)
    app.router.add_get("/go/{tag}", go)
    from aiogram.filters import Command
    B.dp.message.register(cmd_funnel, Command("funnel"))

def start_worker():
    asyncio.create_task(worker())
