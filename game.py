# VAYNAH VPN — бэкенд мини-игры (Telegram Mini App). Подключается из bot.py: game.setup(app, module)
import asyncio, hashlib, hmac, json, os, random, sqlite3, time, urllib.parse, uuid as _uuid
from aiohttp import web

B = None
STATIC = "/opt/zpnbot/game"
E_BASE, E_MAX_FRIEND, E_MAX_SUB, E_REGEN = 5, 7, 10, 1800   # энергия: база / с другом-VPN / с подпиской / 30 мин
KEYS_PER_DAY, DAYS_MONTH_CAP = 500, 7                       # обмен ключей на дни VPN
FRIENDS_PER_DAY = 10                                         # сколько друзей в сутки засчитываем
WORLDS = [  # (код, название, флаг, уровни)
    ("ru", "Россия", "🇷🇺", range(1, 11)),
    ("nl", "Нидерланды", "🇳🇱", range(11, 26)),
    ("de", "Германия", "🇩🇪", range(26, 41)),
    ("fi", "Финляндия", "🇫🇮", range(41, 61)),
]
MAX_LEVEL = 60
INF = 0          # level=0 — бесконечный режим
MSK = 3 * 3600

def now(): return int(time.time())
def log(): return B.log

# ------------------------------------------------------------------ db
def db():
    c = B.db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS game_players(tg_id INTEGER PRIMARY KEY, name TEXT, energy INTEGER, energy_ts INTEGER,
        keys INTEGER DEFAULT 0, keys_total INTEGER DEFAULT 0, best INTEGER DEFAULT 0, stars TEXT DEFAULT '{}',
        inf_until INTEGER DEFAULT 0, emax_bonus INTEGER DEFAULT 0, best_inf INTEGER DEFAULT 0,
        red_month TEXT, red_days INTEGER DEFAULT 0, created INTEGER);
    CREATE TABLE IF NOT EXISTS game_runs(id TEXT PRIMARY KEY, tg_id INTEGER, level INTEGER, seed INTEGER,
        started INTEGER, finished INTEGER, done INTEGER, keys INTEGER, dist REAL, stars INTEGER);
    CREATE INDEX IF NOT EXISTS ix_grun_tg ON game_runs(tg_id, finished);
    CREATE TABLE IF NOT EXISTS game_refs(friend_id INTEGER PRIMARY KEY, ref_id INTEGER, stage INTEGER DEFAULT 0,
        counted INTEGER DEFAULT 0, hwid TEXT, ts INTEGER, checked INTEGER DEFAULT 0);
    CREATE INDEX IF NOT EXISTS ix_gref ON game_refs(ref_id);
    CREATE TABLE IF NOT EXISTS game_prizes(week TEXT, tg_id INTEGER, place INTEGER, days INTEGER, PRIMARY KEY(week, place));
    """)
    return c

def player(c, tg_id, name=None):
    r = c.execute("SELECT * FROM game_players WHERE tg_id=?", (tg_id,)).fetchone()
    if not r:
        c.execute("INSERT INTO game_players(tg_id,name,energy,energy_ts,created) VALUES(?,?,?,?,?)",
                  (tg_id, name or "", E_BASE, now(), now())); c.commit()
        r = c.execute("SELECT * FROM game_players WHERE tg_id=?", (tg_id,)).fetchone()
    elif name and name != r[1]:
        c.execute("UPDATE game_players SET name=? WHERE tg_id=?", (name, tg_id)); c.commit()
    cols = [d[0] for d in c.execute("SELECT * FROM game_players LIMIT 0").description]
    p = dict(zip(cols, r)); p["stars"] = json.loads(p["stars"] or "{}"); return p

def save(c, p):
    c.execute("UPDATE game_players SET energy=?,energy_ts=?,keys=?,keys_total=?,best=?,stars=?,inf_until=?,emax_bonus=?,"
              "best_inf=?,red_month=?,red_days=? WHERE tg_id=?",
              (p["energy"], p["energy_ts"], p["keys"], p["keys_total"], p["best"], json.dumps(p["stars"]), p["inf_until"],
               p["emax_bonus"], p["best_inf"], p["red_month"], p["red_days"], p["tg_id"])); c.commit()

def sub_active(tg_id):
    u = B.get_user(tg_id); return bool(u and u["expires_at"] and u["expires_at"] > now())

def emax(p, sub):
    return E_MAX_SUB if sub else (E_MAX_FRIEND if p["emax_bonus"] else E_BASE)

def regen(p, sub):
    m = emax(p, sub); t = now()
    if p["energy"] >= m: p["energy_ts"] = t; return
    n = (t - p["energy_ts"]) // E_REGEN
    if n > 0:
        p["energy"] = min(m, p["energy"] + n); p["energy_ts"] += n * E_REGEN
        if p["energy"] >= m: p["energy_ts"] = t

def infinite(p): return p["inf_until"] > now()

def friends(c, tg_id):
    rows = c.execute("SELECT stage FROM game_refs WHERE ref_id=? AND counted=1", (tg_id,)).fetchall()
    st = [r[0] for r in rows]
    return {"started": sum(1 for s in st if s >= 1), "vpn": sum(1 for s in st if s >= 2), "paid": sum(1 for s in st if s >= 3)}

def world_open(i, p, fr, sub):
    if i == 0: return True
    if i == 1: return fr["started"] >= 1 or sum(p["stars"].values()) >= 20
    if i == 2: return fr["started"] >= 3
    if i == 3: return fr["paid"] >= 1
    return False

def world_of(level):
    for i, w in enumerate(WORLDS):
        if level in w[3]: return i
    return None

def level_open(level, p, fr, sub):
    if level == INF: return sub
    wi = world_of(level)
    if wi is None or not world_open(wi, p, fr, sub): return False
    return level == 1 or p["best"] >= level - 1

# ------------------------------------------------------------------ генератор уровней (детерминированный)
LANES = 3
def gen_level(level, seed):
    rnd = random.Random(seed * 7919 + level)
    inf = level == INF
    L = level if not inf else 12
    speed = 15.0 + L * 0.38
    length = 6000.0 if inf else 450.0 + L * 22
    gap = max(8.0, 15.5 - L * 0.13)
    objs, keys = [], 0
    z = 32.0
    types = ["wall"] * 6 + (["low"] * 3 if L >= 2 else []) + (["high"] * 3 if L >= 4 else []) + \
            (["cap"] * 2 if L >= 6 else []) + (["ad"] * 1 if L >= 3 else []) + (["gate"] * 2 if L >= 8 else [])
    last_boost = 0.0
    while z < length - 20:
        stage = min(1.0, z / 1500.0) if inf else 0
        t = rnd.choice(types) if not inf or z > 60 else "wall"
        if t == "wall":
            nb = 1 if (L < 5 and rnd.random() < .7) else 2
            lanes = sorted(rnd.sample(range(LANES), nb)); objs.append({"t": "wall", "z": round(z, 1), "l": lanes})
            free = [x for x in range(LANES) if x not in lanes]
        elif t == "gate":
            g = rnd.randrange(LANES); lanes = [x for x in range(LANES) if x != g]
            objs.append({"t": "wall", "z": round(z, 1), "l": lanes}); free = [g]
        elif t in ("low", "high"):
            objs.append({"t": t, "z": round(z, 1)}); free = list(range(LANES))
        else:   # cap / ad — в одной полосе, не смертельно
            ln = rnd.randrange(LANES); objs.append({"t": t, "z": round(z, 1), "l": [ln]})
            free = [x for x in range(LANES) if x != ln]
        # ключи между препятствиями
        if rnd.random() < 0.75 and free:
            ln = rnd.choice(free); n = rnd.randint(3, 5)
            for k in range(n):
                kz = z + 2.2 + k * 1.3
                if kz < z + gap - 1.5:
                    objs.append({"t": "key", "z": round(kz, 1), "l": [ln]}); keys += 1
        if z - last_boost > 110 and rnd.random() < 0.35 and free:
            objs.append({"t": rnd.choice(["shield", "magnet", "boost"]), "z": round(z + gap / 2, 1), "l": [rnd.choice(free)]})
            last_boost = z
        z += gap * (1.0 - 0.35 * stage) * rnd.uniform(0.85, 1.2)
    return {"level": level, "seed": seed, "speed": round(speed, 2), "length": length, "objs": objs, "keys": keys,
            "accel": 0.012 if inf else 0.0, "vmax": round(speed * (2.0 if inf else 1.0), 2)}

def min_time(lv):
    # быстрее нельзя даже с «ускорением» всю дорогу
    return lv["length"] / (lv["vmax"] * 1.5) * 0.9

def stars_for(lv, keys):
    if not lv["keys"]: return 3
    r = keys / lv["keys"]
    return 3 if r >= 0.85 else 2 if r >= 0.5 else 1

# ------------------------------------------------------------------ Telegram initData
def check_init(init):
    try:
        q = dict(urllib.parse.parse_qsl(init, keep_blank_values=True))
        h = q.pop("hash", "")
        dcs = "\n".join(f"{k}={q[k]}" for k in sorted(q))
        secret = hmac.new(b"WebAppData", B.TOKEN.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest(), h): return None
        if now() - int(q.get("auth_date", 0)) > 7 * 86400: return None
        u = json.loads(q.get("user", "{}"))
        return {"id": int(u["id"]), "name": (u.get("first_name") or "") + (" " + u["last_name"] if u.get("last_name") else "")}
    except Exception:
        return None

def auth(req):
    return check_init(req.headers.get("X-Init-Data", "") or req.query.get("init", ""))

def J(d, s=200): return web.json_response(d, status=s, headers={"Cache-Control": "no-store"})

# ------------------------------------------------------------------ state
def week_key(ts=None):
    t = (ts or now()) + MSK; d = time.gmtime(t)
    monday = t - (d.tm_wday * 86400) - (t % 86400)
    return time.strftime("%Y-%m-%d", time.gmtime(monday)), monday - MSK

def state_dict(c, p, sub, device_info=None):
    fr = friends(c, p["tg_id"])
    worlds = []
    for i, (code, title, flag, rng) in enumerate(WORLDS):
        worlds.append({"code": code, "title": title, "flag": flag, "from": rng.start, "to": rng.stop - 1,
                       "open": world_open(i, p, fr, sub)})
    m = emax(p, sub)
    nxt = 0 if p["energy"] >= m else max(0, E_REGEN - (now() - p["energy_ts"]))
    month = time.strftime("%Y-%m", time.gmtime(now() + MSK))
    red = p["red_days"] if p["red_month"] == month else 0
    return {"me": {"id": p["tg_id"], "name": p["name"]}, "energy": p["energy"], "emax": m, "next": nxt,
            "infinite": infinite(p), "inf_until": p["inf_until"], "keys": p["keys"], "best": p["best"],
            "stars": p["stars"], "best_inf": p["best_inf"], "sub": sub, "worlds": worlds, "friends": fr,
            "devices": device_info or {"count": 0, "limit": None},
            "redeem": {"rate": KEYS_PER_DAY, "left": max(0, DAYS_MONTH_CAP - red), "cap": DAYS_MONTH_CAP},
            "ref_link": f"https://t.me/{B.BOT_USERNAME}?start={p['tg_id']}", "bot": B.BOT_USERNAME}

async def api_state(req):
    u = auth(req)
    if not u: return J({"error": "auth"}, 401)
    sub = sub_active(u["id"]); c = db()
    try:
        p = player(c, u["id"], u["name"]); regen(p, sub); save(c, p)
        device_info = {"count": 0, "limit": None}
        try:
            lim, devs, _ = await asyncio.to_thread(B._rw_devices_sync, u["id"])
            device_info = {"count": len(devs), "limit": lim}
        except Exception:
            pass
        return J(state_dict(c, p, sub, device_info))
    finally: c.close()

async def api_start(req):
    u = auth(req)
    if not u: return J({"error": "auth"}, 401)
    body = await req.json(); level = int(body.get("level", 1))
    if level < 0 or level > MAX_LEVEL: return J({"error": "level"}, 400)
    sub = sub_active(u["id"]); c = db()
    try:
        p = player(c, u["id"], u["name"]); regen(p, sub)
        fr = friends(c, u["id"])
        if not level_open(level, p, fr, sub): return J({"error": "locked"}, 403)
        if not infinite(p):
            if p["energy"] <= 0: return J({"error": "energy", "next": max(0, E_REGEN - (now() - p["energy_ts"]))}, 403)
            if p["energy"] >= emax(p, sub): p["energy_ts"] = now()
            p["energy"] -= 1
        save(c, p)
        rid, seed = _uuid.uuid4().hex, random.randrange(1, 2**31)
        c.execute("INSERT INTO game_runs(id,tg_id,level,seed,started) VALUES(?,?,?,?,?)", (rid, u["id"], level, seed, now()))
        c.commit()
        B.log_event(u["id"], "game_start", str(level))
        lv = gen_level(level, seed); lv["run"] = rid
        return J({"run": lv, "energy": p["energy"]})
    finally: c.close()

async def api_finish(req):
    u = auth(req)
    if not u: return J({"error": "auth"}, 401)
    b = await req.json(); rid = str(b.get("run", ""))
    c = db()
    try:
        r = c.execute("SELECT tg_id,level,seed,started,finished FROM game_runs WHERE id=?", (rid,)).fetchone()
        if not r or r[0] != u["id"]: return J({"error": "run"}, 404)
        if r[4]: return J({"error": "dup"}, 409)
        level, seed, started = r[1], r[2], r[3]
        lv = gen_level(level, seed); el = max(0.0, time.time() - started + 1.0)
        dist = max(0.0, min(float(b.get("dist") or 0), lv["length"]))
        done = bool(b.get("done")) and level != INF
        keys = max(0, min(int(b.get("keys") or 0), lv["keys"]))
        flag = None
        # античит: быстрее физически возможного — не засчитываем
        vcap = lv["vmax"] * 1.5
        if dist > el * vcap * 1.15 + 15: flag = "speed"; dist = el * vcap; done = False
        if done and el < min_time(lv): flag = "fast"; done = False
        kmax = sum(1 for o in lv["objs"] if o["t"] == "key" and o["z"] <= dist + 6)
        keys = min(keys, kmax)
        sub = sub_active(u["id"]); p = player(c, u["id"], u["name"]); regen(p, sub)
        st = stars_for(lv, keys) if done else 0
        p["keys"] += keys; p["keys_total"] += keys
        new_best = False
        if done:
            k = str(level)
            if st > p["stars"].get(k, 0): p["stars"][k] = st
            if level > p["best"]: p["best"] = level; new_best = True
        if level == INF and int(dist) > p["best_inf"]: p["best_inf"] = int(dist); new_best = True
        save(c, p)
        c.execute("UPDATE game_runs SET finished=?,done=?,keys=?,dist=?,stars=? WHERE id=?",
                  (now(), int(done), keys, dist, st, rid)); c.commit()
        if flag: log().warning(f"game anticheat {u['id']} lvl{level}: {flag} el={el:.1f} dist={dist:.0f}")
        B.log_event(u["id"], "game_finish", f"{level}:{int(done)}:{keys}")
        out = state_dict(c, p, sub); out["result"] = {"done": done, "keys": keys, "stars": st, "dist": int(dist),
                                                        "new_best": new_best, "flag": flag, "level": level}
        return J(out)
    finally: c.close()

async def api_redeem(req):
    u = auth(req)
    if not u: return J({"error": "auth"}, 401)
    b = await req.json(); days = int(b.get("days", 1))
    c = db()
    try:
        sub = sub_active(u["id"]); p = player(c, u["id"], u["name"])
        month = time.strftime("%Y-%m", time.gmtime(now() + MSK))
        if p["red_month"] != month: p["red_month"], p["red_days"] = month, 0
        left = DAYS_MONTH_CAP - p["red_days"]
        if days < 1 or days > left: return J({"error": "cap", "left": left}, 403)
        if p["keys"] < days * KEYS_PER_DAY: return J({"error": "keys"}, 403)
        p["keys"] -= days * KEYS_PER_DAY; p["red_days"] += days; save(c, p)
    finally: c.close()
    try:
        _, exp = await B.add_days(u["id"], days)
    except Exception as e:
        log().error(f"game redeem {u['id']}: {e}")
        c = db(); p = player(c, u["id"]); p["keys"] += days * KEYS_PER_DAY; p["red_days"] -= days; save(c, p); c.close()
        return J({"error": "vpn"}, 500)
    B.log_event(u["id"], "game_redeem", str(days))
    c = db()
    try:
        p = player(c, u["id"]); out = state_dict(c, p, sub_active(u["id"]))
        out["redeemed"] = {"days": days, "until": exp}; return J(out)
    finally: c.close()

async def api_top(req):
    u = auth(req)
    if not u: return J({"error": "auth"}, 401)
    wk, start = week_key(); c = db()
    try:
        rows = c.execute("""SELECT r.tg_id, COALESCE(p.name,''), SUM(r.keys) s FROM game_runs r LEFT JOIN game_players p
                            ON p.tg_id=r.tg_id WHERE r.finished>=? GROUP BY r.tg_id ORDER BY s DESC LIMIT 10""", (start,)).fetchall()
        mine = c.execute("SELECT COALESCE(SUM(keys),0) FROM game_runs WHERE tg_id=? AND finished>=?", (u["id"], start)).fetchone()[0]
        place = c.execute("""SELECT COUNT(*)+1 FROM (SELECT tg_id, SUM(keys) s FROM game_runs WHERE finished>=? GROUP BY tg_id)
                             WHERE s>?""", (start, mine)).fetchone()[0]
        def nm(n, i): n = (n or "").strip() or f"Игрок {str(i)[-4:]}"; return n[:18]
        return J({"week": wk, "ends": start + 7 * 86400, "prizes": [7, 3, 1],
                  "top": [{"name": nm(n, i), "keys": s, "me": i == u["id"]} for i, n, s in rows],
                  "me": {"keys": mine, "place": place if mine else None}})
    finally: c.close()

# ------------------------------------------------------------------ друзья: стадии и награды
def _rw_friend(fid):
    """(трафик_байт, hwid|None) из Remnawave."""
    try:
        u = B._rw_call("GET", f"/users/by-username/tg{int(fid)}")["response"]
    except Exception:
        return 0, None
    used = int(((u.get("userTraffic") or {}).get("lifetimeUsedTrafficBytes")) or 0)
    hw = None
    try:
        d = B._rw_call("GET", f"/hwid/devices/{u['uuid']}")["response"].get("devices") or []
        if d: hw = d[0].get("hwid")
    except Exception: pass
    return used, hw

async def notify(tg_id, text):
    try:
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎮 Открыть игру", web_app=WebAppInfo(url=game_url()))]])
        await B.bot.send_message(tg_id, text, reply_markup=kb)
    except Exception: pass

def game_url(): return f"https://{B.SUB_DOMAIN}/game/"

async def refs_tick():
    c = db()
    try:
        # новые приглашённые (users.referrer) → game_refs
        c.execute("""INSERT OR IGNORE INTO game_refs(friend_id, ref_id, stage, ts)
                     SELECT tg_id, referrer, 0, COALESCE(created_at, ?) FROM users WHERE referrer IS NOT NULL AND referrer!=tg_id""", (now(),))
        c.commit()
        rows = c.execute("""SELECT g.friend_id, g.ref_id, g.stage, g.counted, g.checked, u.pay_count, u.first_paid_at
                            FROM game_refs g JOIN users u ON u.tg_id=g.friend_id WHERE g.stage<3""").fetchall()
    finally: c.close()
    day = now() - 86400
    for fid, rid, stage, counted, checked, paycnt, fpa in rows:
        new = max(stage, 1)
        if (paycnt or 0) > 0 or fpa: new = 3
        hw = None
        if new < 2 and now() - (checked or 0) > 1200:
            used, hw = await asyncio.to_thread(_rw_friend, fid)
            if used > 50 * 1024 * 1024 and hw: new = 2
            c = db(); c.execute("UPDATE game_refs SET checked=? WHERE friend_id=?", (now(), fid)); c.commit(); c.close()
        if new <= stage and counted: continue
        c = db()
        try:
            if hw and c.execute("SELECT 1 FROM game_refs WHERE hwid=? AND friend_id!=?", (hw, fid)).fetchone():
                new = min(new, 1)    # устройство уже засчитано за другого друга
            if not counted:
                n = c.execute("SELECT COUNT(*) FROM game_refs WHERE ref_id=? AND counted=1 AND ts>=?", (rid, day)).fetchone()[0]
                if n >= FRIENDS_PER_DAY: continue
            if new <= stage and counted: continue
            p = player(c, rid); msgs = []
            if stage < 1 <= new: p["energy"] += 3; msgs.append("+3 ⚡ энергии")
            if stage < 2 <= new:
                p["energy"] += 10; p["emax_bonus"] = 1; msgs.append("+10 ⚡ и максимум энергии 7")
            if stage < 3 <= new:
                p["inf_until"] = max(now(), p["inf_until"]) + 7 * 86400; msgs.append("бесконечная энергия на 7 дней ♾")
            save(c, p)
            c.execute("UPDATE game_refs SET stage=?, counted=1, ts=CASE WHEN counted=0 THEN ? ELSE ts END, hwid=COALESCE(?,hwid) WHERE friend_id=?",
                      (new, now(), hw, fid)); c.commit()
            fr = friends(c, rid)
            if new == 3 and fr["paid"] >= 5 and p["inf_until"] < now() + 3650 * 86400:
                p["inf_until"] = now() + 3650 * 86400; save(c, p); msgs.append("5 друзей оплатили — бесконечная энергия навсегда 🏆")
        finally: c.close()
        what = {1: "пришёл в бот", 2: "подключил VPN", 3: "оплатил VAYNAH VPN"}[new]
        extra = ""
        if new == 2: extra = "\n🌍 Открылся новый мир!" if fr["started"] in (1, 3) else ""
        if new == 3 and fr["paid"] == 1: extra = "\n🇫🇮 Открыт мир «Финляндия»!"
        if new == 1 and fr["started"] in (1, 3): extra = "\n🌍 Открылся новый мир!"
        await notify(rid, f"🎮 <b>VAYNAH VPN</b>: твой друг {what} — " + ", ".join(msgs) + extra)

async def prizes_tick():
    wk, start = week_key(); prev_start = start - 7 * 86400
    prev_wk = time.strftime("%Y-%m-%d", time.gmtime(prev_start + MSK))
    c = db()
    try:
        if c.execute("SELECT 1 FROM game_prizes WHERE week=?", (prev_wk,)).fetchone(): return
        rows = c.execute("""SELECT tg_id, SUM(keys) s FROM game_runs WHERE finished>=? AND finished<? GROUP BY tg_id
                            HAVING s>=100 ORDER BY s DESC LIMIT 3""", (prev_start, start)).fetchall()
        for place, (tg, s) in enumerate(rows, 1):
            c.execute("INSERT OR IGNORE INTO game_prizes VALUES(?,?,?,?)", (prev_wk, tg, place, [7, 3, 1][place - 1]))
        if not rows: c.execute("INSERT OR IGNORE INTO game_prizes VALUES(?,?,?,?)", (prev_wk, 0, 0, 0))
        c.commit()
    finally: c.close()
    for place, (tg, s) in enumerate(rows, 1):
        d = [7, 3, 1][place - 1]
        try:
            await B.add_days(tg, d)
            await notify(tg, f"🏆 <b>VAYNAH VPN</b>: {place} место в недельном рейтинге ({s} 🔑) — тебе <b>+{d} {B.days_word(d)} VPN</b>!")
        except Exception as e: log().error(f"game prize {tg}: {e}")

async def worker():
    await asyncio.sleep(20)
    while True:
        try:
            if str(B.cfg("game_enabled", "1")) != "0":
                await refs_tick(); await prizes_tick()
        except Exception as e:
            log().exception(f"game worker: {e}")
        await asyncio.sleep(120)

# ------------------------------------------------------------------ static
async def static(req):
    name = req.match_info.get("f") or "index.html"
    if "/" in name or ".." in name: raise web.HTTPNotFound()
    path = os.path.join(STATIC, name)
    if not os.path.isfile(path): raise web.HTTPNotFound()
    cache = "no-cache" if name.endswith(".html") else "public, max-age=86400"
    return web.FileResponse(path, headers={"Cache-Control": cache})
async def static_asset(req):
    name = req.match_info.get("f") or ""
    if not name or "/" in name or "\\" in name or ".." in name: raise web.HTTPNotFound()
    path = os.path.join(STATIC, "assets", name)
    if not os.path.isfile(path): raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})

def setup(app, mod):
    global B
    B = mod
    app.router.add_get("/game", lambda r: web.HTTPFound("/game/"))
    app.router.add_get("/game/", static)
    app.router.add_get("/game/api/state", api_state)
    app.router.add_post("/game/api/start", api_start)
    app.router.add_post("/game/api/finish", api_finish)
    app.router.add_post("/game/api/redeem", api_redeem)
    app.router.add_get("/game/api/top", api_top)
    app.router.add_get("/game/assets/{f}", static_asset)
    for _asset in ("vaynah-raven-runner.png", "vaynah-raven-referral.png", "vaynah-referral-banner.png"):
        async def _serve_asset(req, _asset=_asset):
            return web.FileResponse(os.path.join(STATIC, "assets", _asset), headers={"Cache-Control": "public, max-age=86400"})
        app.router.add_get("/game/assets/" + _asset, _serve_asset)
    app.router.add_get("/game/{f}", static)

def start_worker():
    asyncio.create_task(worker())
