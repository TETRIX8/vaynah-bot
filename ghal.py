"""VAYNAH VPN — персонаж VAYNAH BRO, HTML-виджеты (Bot API 10.4 sendWidget) и Rich Messages (sendRichMessage).
Лимиты виджета: html <= 32768 байт и <= 4096 байт после zlib(level 9); без сети; картинки только data:.
Фото пользователя используется ТОЛЬКО после явного согласия (режим MY VAYNAH), хранится уменьшенная копия 72px,
оригинал не сохраняется; удаление — кнопкой «Стандартный VAYNAH»."""
import os, io, re, json, zlib, time, base64, html as _h, random, sqlite3, asyncio
import aiohttp

TOKEN = os.environ.get("BOT_TOKEN", "")
API = f"https://api.telegram.org/bot{TOKEN}"
FACES = "/opt/zpnbot/ghal_faces"
os.makedirs(FACES, exist_ok=True)
SLOGAN = "Салам. Мы на связи."
BRAND = "VAYNAH VPN"

async def tg(method, **params):
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{API}/{method}", json={k: v for k, v in params.items() if v is not None},
                          timeout=aiohttp.ClientTimeout(total=30)) as r:
            d = await r.json(content_type=None)
            if not d.get("ok"): raise RuntimeError(f"{method}: {d.get('description')}")
            return d["result"]

# ------------------------------------------------------------------ avatar / MY VAYNAH
def face_path(uid): return f"{FACES}/{int(uid)}.webp"

def face_data_uri(uid):
    p = face_path(uid)
    if not os.path.exists(p): return None
    return "data:image/webp;base64," + base64.b64encode(open(p, "rb").read()).decode()

async def make_face(uid):
    """Скачивает фото профиля, делает аккуратный портрет 72px (кроп по центру-верху, мягкий голубой свет). -> bool"""
    from PIL import Image, ImageEnhance, ImageOps
    ph = await tg("getUserProfilePhotos", user_id=int(uid), limit=1)
    if not ph.get("total_count") or not ph.get("photos"): return False
    sizes = sorted(ph["photos"][0], key=lambda x: x.get("width", 0))
    pick = next((x for x in sizes if x.get("width", 0) >= 320), sizes[-1])
    f = await tg("getFile", file_id=pick["file_id"])
    async with aiohttp.ClientSession() as s:
        async with s.get(f"https://api.telegram.org/file/bot{TOKEN}/{f['file_path']}", timeout=aiohttp.ClientTimeout(total=30)) as r:
            raw = await r.read()
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    w, h = im.size; side = int(min(w, h) * 0.78)          # лицо обычно в центре-верху аватарки
    left = (w - side) // 2; top = max(0, int((h - side) * 0.32))
    base = im.crop((left, top, left + side, top + side))
    data = None
    for px, q in ((72, 50), (64, 44), (60, 38), (56, 32), (48, 28)):     # ужимаем, пока влезает в бюджет виджета
        im2 = base.resize((px, px), Image.LANCZOS)
        im2 = ImageEnhance.Contrast(im2).enhance(1.06)
        im2 = Image.blend(im2, Image.new("RGB", im2.size, (22, 133, 255)), 0.10)   # согласованное голубое освещение
        buf = io.BytesIO(); im2.save(buf, "WEBP", quality=q, method=6); data = buf.getvalue()
        if len(data) <= 950: break
    del raw
    open(face_path(uid), "wb").write(data)
    return True

def drop_face(uid):
    try: os.remove(face_path(uid))
    except FileNotFoundError: pass

# ------------------------------------------------------------------ design system (компактно — лимит 4 КБ сжатия)
CSS = ("*{box-sizing:border-box;margin:0}"
"body{font:14px/1.35 system-ui,sans-serif;color:#fff}"
".w{position:relative;padding:14px;border-radius:20px;overflow:hidden;background:radial-gradient(120% 90% at 0 0,#16467e 0,#081426 60%);"
"border:1px solid rgba(83,216,255,.25)}"
".w:before{content:'';position:absolute;left:0;right:0;bottom:0;height:46px;opacity:.5;"
"background:linear-gradient(135deg,transparent 46%,#102B50 46% 54%,transparent 54%) 0 100%/60px 46px repeat-x}"
".r{display:flex;gap:12px;align-items:center;position:relative}"
".t{font-size:19px;font-weight:800}.m{color:#A8BAD1;font-size:12.5px}"
".c{background:rgba(16,43,80,.62);backdrop-filter:blur(8px);border:1px solid rgba(83,216,255,.18);border-radius:14px;padding:9px 11px}"
".pb{height:7px;border-radius:9px;background:#0b1d36;overflow:hidden;margin-top:6px}"
".pb i{display:block;height:100%;background:linear-gradient(90deg,#1685FF,#53D8FF);animation:gx 1.2s ease both;transform-origin:left}"
"@keyframes gx{from{transform:scaleX(0)}}"
".b{display:flex;flex-wrap:wrap;gap:7px;margin-top:11px;position:relative}"
"button{flex:1 1 30%;border:0;border-radius:12px;padding:9px 6px;font:700 12.5px system-ui;color:#fff;background:rgba(22,133,255,.18);"
"border:1px solid rgba(83,216,255,.28);transition:transform .15s}"
"button:active{transform:scale(.95)}button.p{background:linear-gradient(135deg,#1685FF,#53D8FF);color:#04122a;border:0}"
".ok{color:#53D8FF}.bad{color:#ff8a8a}"
# --- GHAL
".g{position:relative;width:108px;height:124px;flex:none;animation:fl 4s ease-in-out infinite}"
".g svg,.g img{position:absolute;left:0;top:0}"
".g img{left:33px;top:25px;width:42px;height:46px;border-radius:50%/54%}"
"@keyframes fl{50%{transform:translateY(-4px)}}"
".ey{animation:bl 4.5s infinite;transform-origin:center;transform-box:fill-box}@keyframes bl{0%,94%,100%{transform:none}97%{transform:scaleY(.1)}}"
".ar{transform-origin:84px 100px;transform-box:view-box;transition:transform .5s}"
".hd{transform-origin:54px 60px;transform-box:view-box;transition:transform .5s}"
".s-greet .ar{animation:wv .9s ease-in-out 3}@keyframes wv{50%{transform:rotate(-38deg)}}"
".s-explain .ar{transform:rotate(-62deg)}.s-think .hd{transform:rotate(-9deg)}"
".s-happy{animation:hp .6s ease 3}@keyframes hp{50%{transform:translateY(-10px)}}"
".s-surp .hd{transform:scale(1.08)}.s-help .ar{transform:rotate(-25deg)}"
".s-cele .cf{opacity:1}.cf{opacity:0;transition:opacity .4s}.cf i{position:absolute;width:5px;height:9px;border-radius:2px;animation:cf 1.6s linear infinite}"
"@keyframes cf{from{transform:translateY(-10px) rotate(0)}to{transform:translateY(120px) rotate(360deg)}}"
".th{position:absolute;right:-4px;top:4px;opacity:0;transition:opacity .3s;font-size:18px}.s-think .th{opacity:1}"
"@media (prefers-reduced-motion:reduce){*{animation:none!important}}")

def _svg_body():
    return ('<svg width="108" height="124" viewBox="0 0 108 124">'
            '<defs><radialGradient id="L"><stop offset="0" stop-color="#53D8FF" stop-opacity=".55"/><stop offset="1" stop-color="#1685FF" stop-opacity="0"/></radialGradient></defs>'
            '<circle cx="54" cy="58" r="52" fill="url(#L)"/>'
            '<path d="M8 124c2-30 18-44 46-44s44 14 46 44z" fill="#102B50" stroke="#1685FF" stroke-width="1.5"/>'
            '<path d="M47 84v14M61 84v14" stroke="#53D8FF" stroke-width="1.6" stroke-linecap="round"/>'
            '<text x="54" y="114" text-anchor="middle" font-size="7" font-weight="800" fill="#53D8FF" font-family="system-ui">VAYNAH</text>'
            '<g class="ar"><path d="M86 104c8-6 14-20 12-32" fill="none" stroke="#1685FF" stroke-width="12" stroke-linecap="round"/>'
            '<path d="M86 104c8-6 14-20 12-32" fill="none" stroke="#1b4a85" stroke-width="9" stroke-linecap="round"/>'
            '<circle cx="98" cy="70" r="6" fill="#e3b892"/></g></svg>')

def _svg_head(personal):
    face = ('' if personal else
            '<circle cx="54" cy="48" r="20" fill="#e3b892"/>'
            '<ellipse class="ey" cx="46" cy="46" rx="2.4" ry="3" fill="#0b1d36"/><ellipse class="ey" cx="62" cy="46" rx="2.4" ry="3" fill="#0b1d36"/>'
            '<path d="M41 40l9-2M58 38l9 2" stroke="#2a1a10" stroke-width="2" stroke-linecap="round"/>'
            '<path d="M36 52c2 14 9 20 18 20s16-6 18-20c-3 6-9 9-18 9s-15-3-18-9z" fill="#2a1a10"/>'
            '<path d="M47 57c4 3 10 3 14 0" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/>')
    return ('<svg class="hd" width="108" height="124" viewBox="0 0 108 124">' + face +
            '<path d="M26 56c0-22 12-36 28-36s28 14 28 36c0 9-3 16-7 21l-3-15c-1-15-8-24-18-24s-17 9-18 24l-3 15c-4-5-7-12-7-21z" '
            'fill="#0d2342" stroke="#1685FF" stroke-width="1.6"/></svg>')

NOFACE = set()   # uid, для которых фото временно не влезло в лимит виджета
def ghal_html(uid=None, state="idle"):
    img = face_data_uri(uid) if (uid and uid not in NOFACE) else None
    conf = '<div class="cf">' + "".join(f'<i style="left:{x}px;top:{y}px;background:{c};animation-delay:{d}s"></i>'
           for x, y, c, d in ((10, 0, "#53D8FF", 0), (40, 6, "#1685FF", .4), (70, 0, "#fff", .8), (92, 8, "#53D8FF", 1.2))) + '</div>'
    return (f'<div class="g s-{state}" id="G" aria-label="VAYNAH BRO" onclick="tap()">' + _svg_body() +
            (f'<img src="{img}">' if img else '') + _svg_head(bool(img)) + conf + '<div class="th">…</div></div>')

JS_BASE = ("const TW=window.TelegramWidget,G=document.getElementById('G'),S=['greet','happy','surp','explain','cele'];"
           "function st(s){G.className='g s-'+s}"
           "function tap(){st(S[Math.floor(Math.random()*S.length)]);try{TW.HapticFeedback.impactOccurred('light')}catch(e){}"
           "setTimeout(()=>st('idle'),2600)}"
           "function go(a){try{TW.HapticFeedback.selectionChanged()}catch(e){}st('think');TW.request(a).then(r=>{st('happy');"
           "if(r&&r.result){const e=document.getElementById('msg');if(e)e.textContent=r.result}}).catch(()=>st('surp'))"
           ".finally(()=>setTimeout(()=>st('idle'),2400))}"
           "setTimeout(()=>st('idle'),3000);")

def page(body, state="greet", extra_js=""):
    return (f'<style>{CSS}</style><div class="w">{body}</div><script>{JS_BASE}{extra_js}</script>')

def size_ok(htm):
    b = htm.encode()
    return len(b) <= 32768 and len(zlib.compress(b, 9)) <= 4096, len(b), len(zlib.compress(b, 9))

def esc(s): return _h.escape(str(s or ""))

def ghal_id(uid): return "GH-" + format((int(uid) * 2654435761) % 0xFFFFFFF, "07X")

# ------------------------------------------------------------------ widgets
def w_home(uid, name, st):
    """st: dict(active, days, total_days, exp, plan, devices)"""
    if st.get("active"):
        pct = max(4, min(100, round(100 * st["days"] / max(1, st.get("total_days") or 30))))
        status = (f'<div class="c" style="margin-top:8px"><b class="ok">● Подписка активна</b> · ещё <b>{st["days"]}</b> дн.'
                  f'<div class="pb"><i style="width:{pct}%"></i></div></div>')
        hi = "Машаллах, всё работает!" if st["days"] > 3 else "Брат, подписка заканчивается."
    elif st.get("expired"):
        status = '<div class="c" style="margin-top:8px"><b class="bad">● Подписка закончилась</b></div>'; hi = "Не переживай, я рядом — продлим."
    else:
        status = '<div class="c" style="margin-top:8px"><b>Подключись за минуту</b> · Европа 🇫🇮🇩🇪🇳🇱🇪🇸</div>'; hi = "Вай, давай подключу тебя."
    body = (f'<div class="r">{ghal_html(uid, "greet")}<div style="min-width:0">'
            f'<div class="m">{BRAND}</div><div class="t">Салам, {esc(name)}!</div><div class="m" id="msg">{hi}</div>{status}</div></div>'
            '<div class="b"><button class="p" onclick="go(\'vpn\')">Подключить</button><button onclick="go(\'store\')">Магазин</button>'
            '<button onclick="go(\'sub\')">Подписка</button><button onclick="go(\'prof\')">Профиль</button>'
            '<button onclick="go(\'ref\')">Друзья</button><button onclick="go(\'help\')">VAYNAH BRO, помоги</button></div>')
    return page(body)

def w_profile(uid, name, st, bonus_days):
    body = (f'<div class="r">{ghal_html(uid, "happy")}<div style="min-width:0"><div class="m">Профиль</div><div class="t">{esc(name)}</div>'
            f'<div class="m">ID: <b class="ok">{ghal_id(uid)}</b></div></div></div>'
            f'<div class="c" style="margin-top:10px"><div class="r" style="justify-content:space-between"><span class="m">Тариф</span><b>{esc(st.get("plan") or "—")}</b></div>'
            f'<div class="r" style="justify-content:space-between;margin-top:5px"><span class="m">Действует до</span><b>{esc(st.get("exp") or "—")}</b></div>'
            f'<div class="r" style="justify-content:space-between;margin-top:5px"><span class="m">Бонусы</span><b class="ok">+{bonus_days} дн.</b></div></div>'
            '<div class="b"><button onclick="go(\'myghal\')">MY VAYNAH из фото</button><button onclick="go(\'stdghal\')">Стандартный VAYNAH</button>'
            '<button class="p" onclick="go(\'sub\')">Моя подписка</button></div><div class="m" id="msg" style="margin-top:8px;position:relative">Фото берём только с твоего согласия.</div>')
    return page(body, extra_js="")

STORE = [("start", "START", "1m", "3 устройства", 199), ("pro", "PRO", "12m", "3 устройства · год", 1590), ("family", "FAMILY", "fam_1m", "5 устройств", 299)]
def w_store(uid, prices):
    cards = "".join(
        f'<div class="c" id="k{i}" onclick="pk({i})" style="flex:1;text-align:center;transition:transform .25s,border-color .25s">'
        f'<div style="font-weight:800;letter-spacing:.5px">{t}</div><div class="t" style="font-size:17px">{prices.get(pid, rub)} ₽</div>'
        f'<div class="m" style="font-size:11px">{d}</div></div>' for i, (k, t, pid, d, rub) in enumerate(STORE))
    js = ("let K=0;const P=" + json.dumps([s[2] for s in STORE]) + ";function pk(i){K=i;for(let j=0;j<3;j++){const e=document.getElementById('k'+j);"
          "e.style.transform=j==i?'scale(1.06)':'none';e.style.borderColor=j==i?'#53D8FF':''}st('explain');try{TW.HapticFeedback.selectionChanged()}catch(e){}}pk(0);")
    body = (f'<div class="r">{ghal_html(uid, "explain")}<div><div class="m">Магазин</div><div class="t">Выбирай, брат</div>'
            '<div class="m" id="msg">50 ГБ, серверы в Европе, без логов</div></div></div>'
            f'<div class="r" style="margin-top:10px;gap:7px;align-items:stretch">{cards}</div>'
            '<div class="b"><button class="p" onclick="go(\'buy:\'+P[K])">Оформить</button><button onclick="go(\'plans\')">Все тарифы</button></div>')
    return page(body, extra_js=js)

def w_sub(uid, st):
    if not st.get("active"):
        return page(f'<div class="r">{ghal_html(uid, "surp")}<div><div class="t">Подписки нет</div><div class="m" id="msg">Вай, исправим — выбери тариф.</div></div></div>'
                    '<div class="b"><button class="p" onclick="go(\'store\')">Магазин</button><button onclick="go(\'help\')">Помощь</button></div>')
    pct = max(4, min(100, round(100 * st["days"] / max(1, st.get("total_days") or 30))))
    body = (f'<div class="r">{ghal_html(uid, "happy")}<div><div class="m">Моя подписка</div><div class="t">{esc(st.get("plan") or "")}</div>'
            f'<div class="m">до {esc(st["exp"])}</div></div></div>'
            f'<div class="c" style="margin-top:10px"><div class="r" style="justify-content:space-between"><span>Осталось</span><b class="ok">{st["days"]} дн.</b></div>'
            f'<div class="pb"><i style="width:{pct}%"></i></div>'
            f'<div class="r" style="justify-content:space-between;margin-top:7px"><span class="m">Устройства</span><b>{esc(st.get("devices") or "до 3")}</b></div></div>'
            '<div class="b"><button class="p" onclick="go(\'vpn\')">Подключить</button><button onclick="go(\'store\')">Продлить</button></div>'
            '<div class="m" id="msg" style="margin-top:8px;position:relative"></div>')
    return page(body)

def w_ref(uid, link, invited, bonus, rmax):
    pct = max(3, min(100, round(100 * invited / max(1, rmax))))
    body = (f'<div class="r">{ghal_html(uid, "cele")}<div><div class="m">Друзья</div><div class="t">Зови своих</div>'
            '<div class="m" id="msg">Красавчик, каждый друг — бонусные дни!</div></div></div>'
            f'<div class="c" style="margin-top:10px"><div class="r" style="justify-content:space-between"><span>Приглашено</span><b class="ok">{invited} / {rmax}</b></div>'
            f'<div class="pb"><i style="width:{pct}%"></i></div><div class="r" style="justify-content:space-between;margin-top:7px"><span class="m">Начислено</span><b>+{bonus} дн.</b></div></div>'
            f'<div class="b"><button class="p" onclick="TW.copyText({json.dumps(link)});st(\'happy\')">Скопировать ссылку</button>'
            '<button onclick="go(\'refinfo\')">Как это работает</button></div>')
    return page(body)

def build(fn, uid, *a):
    """Собирает виджет; если с фото не влезает в 4 КБ — собирает со стандартным GHAL."""
    h = fn(uid, *a)
    if size_ok(h)[0]: return h
    NOFACE.add(uid)
    try: h = fn(uid, *a)
    finally: NOFACE.discard(uid)
    return h

async def send_widget(chat_id, htm, caption, reply_markup=None, height=None):
    return await tg("sendWidget", chat_id=chat_id, html=htm, caption=caption, parse_mode="HTML",
                    allow_queries=True, height=height, reply_markup=reply_markup)

async def send_rich(chat_id, rich_html, reply_markup=None):
    return await tg("sendRichMessage", chat_id=chat_id, rich_message={"html": rich_html}, reply_markup=reply_markup)

async def answer_query(qid, data=""):
    try: await tg("answerWidgetQuery", widget_query_id=qid, data=(data or "")[:1000])
    except Exception: pass

TIPS = ["Не грузит? Выбери другую страну в Happ.", "Включи Fake DNS, если видео тормозит.", "Обнови подписку кнопкой ⟳ в Happ.",
        "Ключ персональный — не делись им."]
def w_assist(uid):
    body = (f'<div class="r">{ghal_html(uid, "help")}<div><div class="m">VAYNAH BRO</div><div class="t">Чем помочь, брат?</div>'
            f'<div class="m" id="msg">{random.choice(TIPS)}</div></div></div>'
            '<div class="b"><button class="p" onclick="go(\'howto\')">Как подключить</button><button onclick="go(\'noconn\')">Не работает</button>'
            '<button onclick="go(\'tip\')">Совет</button><button onclick="go(\'oper\')">Оператор</button></div>')
    return page(body)
