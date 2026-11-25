# -*- coding: utf-8 -*-
"""VAYNAH VPN — личный кабинет /me/<uuid>.

Вёрстка, стили и скрипты — без внешних ресурсов (никаких CDN/шрифтов: страница
открывается быстро). Адаптив под мобильные, заставка-анимация,
живой статус локаций (?fmt=json), копирование с запасным вариантом, QR в SVG.

API для bot.py:  render_page(ctx) -> str,  live_json(ctx) -> dict,  not_found_html(bot) -> str
ctx: tg_id, plan, exp, revoked, invited, inv_paid, sub, bot, support, plan_days, devices,
     tier, trial, ref_days, min_rub, locs{auto,de,fi,nl,ru: bool}, panel{used,life,online_at,first_at}, now
"""
import html as _html
import json as _json
import re as _re
import time as _time
import urllib.parse as _up
from datetime import datetime, timezone, timedelta

try:
    import qrcode as _qrcode
except Exception:          # без qrcode страница работает, просто без QR
    _qrcode = None

MSK = timezone(timedelta(hours=3))
_MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля",
           "августа", "сентября", "октября", "ноября", "декабря")

LOCS = [  # id, название, подпись
    ("auto", "Авто", "Сам выберет самый быстрый"),
    ("de", "Германия", "Франкфурт · стабильный"),
    ("nl", "Нидерланды", "Амстердам · быстрый"),
    ("es", "Испания", "Мадрид · запасной выход"),
]

FLAGS = {
    "auto": '<svg viewBox="0 0 30 30"><defs><linearGradient id="fA" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#39ff83"/><stop offset="1" stop-color="#b6ffd3"/></linearGradient></defs><rect width="30" height="30" fill="url(#fA)"/><path d="M16.8 5.5 9.2 16.3h5.4l-1.3 8.2 7.6-10.9h-5.5l1.4-8.1z" fill="#fff"/></svg>',
    "de": '<svg viewBox="0 0 30 30"><rect width="30" height="10" fill="#141414"/><rect y="10" width="30" height="10" fill="#dd0000"/><rect y="20" width="30" height="10" fill="#ffce00"/></svg>',
    "fi": '<svg viewBox="0 0 30 30"><rect width="30" height="30" fill="#fff"/><rect x="8" width="6.5" height="30" fill="#003580"/><rect y="11.75" width="30" height="6.5" fill="#003580"/></svg>',
    "es": '<svg viewBox="0 0 30 30"><rect width="30" height="30" fill="#aa151b"/><rect y="7.5" width="30" height="15" fill="#f1bf00"/></svg>',
    "nl": '<svg viewBox="0 0 30 30"><rect width="30" height="10" fill="#ae1c28"/><rect y="10" width="30" height="10" fill="#fff"/><rect y="20" width="30" height="10" fill="#21468b"/></svg>',
    "ru": '<svg viewBox="0 0 30 30"><rect width="30" height="10" fill="#fff"/><rect y="10" width="30" height="10" fill="#0039a6"/><rect y="20" width="30" height="10" fill="#d52b1e"/></svg>',
}

IC = {
    "plus": '<svg class="ic" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
    "dl": '<svg class="ic" viewBox="0 0 24 24"><path d="M12 3.5v11.5m0 0-4.5-4.5m4.5 4.5 4.5-4.5"/><path d="M4.5 20h15"/></svg>',
    "copy": '<svg class="ic" viewBox="0 0 24 24"><rect x="9" y="9" width="12" height="12" rx="2.5"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>',
    "qr": '<svg class="ic" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><path d="M14 14h3v3h-3zM20.5 14v.01M14 20.5h.01M17.5 17.5h3v3h-3z"/></svg>',
    "bolt": '<svg class="ic" viewBox="0 0 24 24"><path d="M13.5 2 4.5 13.6h6.4L9.8 22l9.3-12h-6.6L13.5 2z"/></svg>',
    "card": '<svg class="ic" viewBox="0 0 24 24"><rect x="2.5" y="5" width="19" height="14" rx="3"/><path d="M2.5 10h19M6.5 15h4"/></svg>',
    "arrow": '<svg class="ic" viewBox="0 0 24 24"><path d="M5 12h14m-5.5-5.5L19 12l-5.5 5.5"/></svg>',
    "clock": '<svg class="ic" viewBox="0 0 24 24" style="width:15px;height:15px;display:inline-block;vertical-align:-2px;margin-right:5px"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
}

HAPP_IOS = "https://apps.apple.com/us/app/happ-proxy-utility/id6504287215"
HAPP_TF = "https://testflight.apple.com/join/XMls6Ckd"
HAPP_APK = "https://github.com/Happ-proxy/happ-android/releases/latest/download/Happ.apk"
HAPP_WIN = "https://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x64.exe"
HAPP_DMG = "https://github.com/Happ-proxy/happ-desktop/releases/latest/download/Happ.macOS.universal.dmg"
HAPP_DEB = "https://github.com/Happ-proxy/happ-desktop/releases/latest/download/Happ.linux.x64.deb"
HAPP_RPM = "https://github.com/Happ-proxy/happ-desktop/releases/latest/download/Happ.linux.x64.rpm"
HAPP_SITE = "https://www.happ.su/main"
STREISAND_IOS = "https://apps.apple.com/us/app/streisand/id6450534064"
V2RAYTUN_GP = "https://play.google.com/store/apps/details?id=com.v2raytun.android"
V2RAYNG_GH = "https://github.com/2dust/v2rayNG/releases/latest"
V2RAYN_GH = "https://github.com/2dust/v2rayN/releases/latest"


def esc(s):
    return _html.escape("" if s is None else str(s), quote=True)


def plural(n, forms):
    n = abs(int(n)) % 100
    m = n % 10
    if 10 < n < 20:
        return forms[2]
    if m == 1:
        return forms[0]
    if 2 <= m <= 4:
        return forms[1]
    return forms[2]


def fmt_bytes(b):
    try:
        b = float(b or 0)
    except (TypeError, ValueError):
        b = 0.0
    if b <= 0:
        return "0 ГБ"
    if b < 1024 ** 2:
        return "< 1 МБ"
    for unit, k in (("ТБ", 1024 ** 4), ("ГБ", 1024 ** 3), ("МБ", 1024 ** 2)):
        if b >= k:
            v = b / k
            s = (f"{v:.1f}".rstrip("0").rstrip(".")) if v < 100 else f"{v:.0f}"
            return s.replace(".", ",") + " " + unit
    return "0 ГБ"


def parse_ts(v):
    if v in (None, "", 0):
        return None
    if isinstance(v, (int, float)):
        return float(v) / (1000.0 if v > 1e11 else 1.0)
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def ago(ts, now):
    d = max(0, now - ts)
    if d < 90:
        return "только что"
    m = int(d // 60)
    if m < 60:
        return f"{m} {plural(m, ('минуту', 'минуты', 'минут'))} назад"
    h = int(d // 3600)
    if h < 24:
        return f"{h} {plural(h, ('час', 'часа', 'часов'))} назад"
    dd = int(d // 86400)
    if dd < 31:
        return f"{dd} {plural(dd, ('день', 'дня', 'дней'))} назад"
    return datetime.fromtimestamp(ts, MSK).strftime("%d.%m.%Y")


def date_ru(ts, with_time=False):
    d = datetime.fromtimestamp(ts, MSK)
    s = f"{d.day} {_MONTHS[d.month - 1]} {d.year}"
    if with_time:
        s += f", {d:%H:%M} МСК"
    return s


def left_text(sec):
    if sec <= 0:
        return ""
    d, h, m = int(sec // 86400), int(sec % 86400 // 3600), int(sec % 3600 // 60)
    if d >= 3:
        return f"{d} {plural(d, ('день', 'дня', 'дней'))}"
    if d > 0:
        return f"{d} {plural(d, ('день', 'дня', 'дней'))} {h} ч"
    if h > 0:
        return f"{h} ч {m} мин"
    return f"{max(1, m)} мин"


def online_state(panel, now):
    panel = panel or {}
    on = parse_ts(panel.get("online_at"))
    first = parse_ts(panel.get("first_at"))
    if on and now - on < 180:
        return "ok", "В сети сейчас"
    if on:
        return "dim", "Активность " + ago(on, now)
    if first:
        return "dim", "Подключались " + ago(first, now)
    if panel:
        return "warn", "Ещё не подключались"
    return "dim", "Статус уточняется"


def traffic_info(panel):
    """(крупно, подпись, процент полоски) — сколько осталось из лимита периода."""
    panel = panel or {}
    used = float(panel.get("used") or 0)
    lim = float(panel.get("limit") or 0)
    if lim <= 0:
        life = panel.get("life") or used
        return "∞", (fmt_bytes(life) + " за всё время") if life else "без ограничений", 100
    left = max(0.0, lim - used)
    pct = max(0, min(100, round(left / lim * 100)))
    return fmt_bytes(left) if left > 0 else "0 ГБ", f"осталось из {fmt_bytes(lim)}", pct


def traffic_text(panel):
    return traffic_info(panel)[1]


def qr_svg(data, uid="a"):
    """QR подписки в SVG (чёткий на любом экране) с логотипом по центру (коррекция Q)."""
    if not _qrcode or not data:
        return ""
    q = _qrcode.QRCode(error_correction=_qrcode.constants.ERROR_CORRECT_Q, border=0, box_size=1)
    q.add_data(data)
    q.make(fit=True)
    m = q.get_matrix()
    n = len(m)
    hole = max(5, (n // 5) | 1)
    c0, c1 = (n - hole) // 2, (n - hole) // 2 + hole
    parts = []
    for y, row in enumerate(m):
        x = 0
        while x < n:
            if row[x] and not (c0 <= x < c1 and c0 <= y < c1):
                s = x
                while x < n and row[x] and not (c0 <= x < c1 and c0 <= y < c1):
                    x += 1
                parts.append(f"M{s} {y}h{x - s}v1h-{x - s}z")
            else:
                x += 1
    pad = 1
    vb = f"{-pad} {-pad} {n + 2 * pad} {n + 2 * pad}"
    lg = hole - 1.2
    lx = c0 + 0.6
    return (f'<svg viewBox="{vb}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="QR-код подписки">'
            f'<defs><linearGradient id="qg{uid}" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#39ff83"/>'
            f'<stop offset="1" stop-color="#b6ffd3"/></linearGradient></defs>'
            f'<rect x="{-pad}" y="{-pad}" width="{n + 2 * pad}" height="{n + 2 * pad}" fill="#fff"/>'
            f'<path d="{"".join(parts)}" fill="#0b1124" shape-rendering="crispEdges"/>'
            f'<rect x="{lx:.2f}" y="{lx:.2f}" width="{lg:.2f}" height="{lg:.2f}" rx="{lg * 0.28:.2f}" fill="url(#qg{uid})"/>'
            f'<svg x="{lx:.2f}" y="{lx:.2f}" width="{lg:.2f}" height="{lg:.2f}" viewBox="0 0 24 24">'
            f'<path d="M13.5 3.5 5.6 13.8h5.6L10.2 20.5l8.2-10.6h-5.8l.9-6.4z" fill="#fff"/></svg></svg>')


def _apps(sub):
    happ = "happ://add/" + sub
    a_add = lambda href, label="Добавить": (f'<a class="p" href="{esc(href)}" data-dl="1">{IC["plus"]}{label}</a>')
    a_dl = lambda href, label: f'<a href="{esc(href)}">{IC["dl"]}{esc(label)}</a>'
    b_copy = f'<button type="button" class="p" data-copy="sub">{IC["copy"]}Скопировать ссылку</button>'
    H = ("H", "linear-gradient(135deg,#0fae55,#39ff83)")

    def app(name, icon, desc, btns, rec=False):
        tag = '<span class="tag">рекомендуем</span>' if rec else ""
        return (f'<div class="app{" rec" if rec else ""}"><span class="ai" style="background:{icon[1]}">{icon[0]}</span>'
                f'<div><div class="an">{esc(name)}{tag}</div><div class="ad">{desc}</div>'
                f'<div class="ab">{"".join(btns)}</div></div></div>')

    panes = {
        "ios": [
            app("Happ", H, "Всё уже настроено: все серверы и российские сайты напрямую",
                [a_add(happ), a_dl(HAPP_IOS, "App Store"), a_dl(HAPP_TF, "TestFlight")], rec=True),
            app("Streisand", ("S", "linear-gradient(135deg,#fb923c,#ef4444)"), "Запасной вариант для iPhone и iPad",
                [a_add("streisand://import/" + sub), a_dl(STREISAND_IOS, "App Store")]),
            f'<div class="note">В российском App Store VPN-приложений нет. Войдите в Apple ID другой страны или '
            f'установите Happ через <a href="{HAPP_TF}">TestFlight</a>. Все способы — на <a href="{HAPP_SITE}">happ.su</a>.</div>',
        ],
        "android": [
            app("Happ", H, "Всё уже настроено: все серверы и российские сайты напрямую",
                [a_add(happ), a_dl(HAPP_APK, "Скачать APK")], rec=True),
            app("v2RayTun", ("V2", "linear-gradient(135deg,#d99a3c,#b6ffd3)"), "Есть в Google Play",
                [a_add("v2raytun://import/" + sub), a_dl(V2RAYTUN_GP, "Google Play")]),
            app("v2rayNG", ("NG", "linear-gradient(135deg,#10b981,#047857)"), "Классический клиент для Android",
                [a_add("v2rayng://install-config?name=VAYNAH%20VPN&url=" + sub), a_dl(V2RAYNG_GH, "GitHub")]),
            '<div class="note">APK ставится в пару касаний: откройте файл и разрешите «Установку из неизвестных источников».</div>',
        ],
        "win": [
            app("Happ", H, "Для Windows 10 и 11 — подключение в один клик",
                [a_add(happ), a_dl(HAPP_WIN, "Скачать для Windows")], rec=True),
            app("v2rayN", ("N", "linear-gradient(135deg,#64748b,#1e293b)"),
                "Скопируйте ссылку → «Подписки» → «Добавить» → «Обновить»",
                [b_copy, a_dl(V2RAYN_GH, "GitHub")]),
            f'<div class="note">Linux: Happ в форматах <a href="{HAPP_DEB}">.deb</a> и <a href="{HAPP_RPM}">.rpm</a>, '
            f'остальные версии — на <a href="{HAPP_SITE}">happ.su</a>.</div>',
        ],
        "mac": [
            app("Happ", H, "Для Mac на Apple Silicon и Intel",
                [a_add(happ), a_dl(HAPP_DMG, "Скачать .dmg"), a_dl(HAPP_IOS, "App Store")], rec=True),
            app("v2rayN", ("N", "linear-gradient(135deg,#64748b,#1e293b)"),
                "Скопируйте ссылку → «Подписки» → «Добавить»", [b_copy, a_dl(V2RAYN_GH, "GitHub")]),
            '<div class="note">Если App Store не открывает приложение с российским Apple ID — скачайте .dmg: это та же программа.</div>',
        ],
    }
    return "".join(f'<div class="pane" data-p="{k}" role="tabpanel">{"".join(v)}</div>' for k, v in panes.items())


def _locs_html(locs):
    out = []
    for i, (k, name, desc) in enumerate(LOCS):
        up = bool((locs or {}).get(k))
        out.append(f'<div class="loc li" data-loc="{k}" style="--d:2;--i:{i}"><span class="flag">{FLAGS[k]}</span>'
                   f'<span><b>{esc(name)}</b><small>{esc(desc)}</small></span>'
                   f'<span class="st {"on" if up else "off"}"><span class="dot"></span>{"онлайн" if up else "недоступна"}</span></div>')
    return "".join(out)


def _state(ctx):
    now = ctx.get("now") or _time.time()
    exp = int(ctx.get("exp") or 0)
    if ctx.get("revoked") and exp <= now:
        return "expired"
    if not exp:
        return "none"
    if exp <= now:
        return "expired"
    return "trial" if ctx.get("trial") else "active"


def live_json(ctx):
    now = ctx.get("now") or _time.time()
    locs = ctx.get("locs") or {}
    cls, txt = online_state(ctx.get("panel"), now)
    tv, ts_, tp = traffic_info(ctx.get("panel"))
    return {"locs": {k: bool(locs.get(k)) for k, _, _ in LOCS}, "onl": {"cls": cls, "txt": txt},
            "traffic": ts_, "traf_v": tv, "traf_pct": tp, "ts": int(now)}


def render_page(ctx):
    now = ctx.get("now") or _time.time()
    sub = ctx.get("sub") or ""
    bot = ctx.get("bot") or "MyVainakhBot"
    support = ctx.get("support") or "MyVainakhBot"
    exp = int(ctx.get("exp") or 0)
    st = _state(ctx)
    tier = ctx.get("tier") or "std"
    plan = ctx.get("plan") or ""
    devices = int(ctx.get("devices") or 3)
    renew_url = f"https://t.me/{bot}?start=buy"
    device_url = f"https://t.me/{bot}?start=devices"
    device_cta = (f'<a class="more" href="{esc(device_url)}">📲 Места заняты? Увеличить лимит до 5 устройств →</a>'
                  if st in ("active", "trial") and devices < 5 else "")
    min_rub = int(ctx.get("min_rub") or 199)
    left = max(0, exp - now)

    # --- заголовок и статус ---
    if st == "trial":
        title, pill = "Пробный период", '<span class="pill tr"><span class="dot"></span>Пробный доступ</span>'
    elif st == "active":
        title = {"fam": "Семейный", "std": "Стандарт"}.get(tier, "Стандарт")
        if plan == "promo":
            title = "Промо-доступ"
        pill = '<span class="pill ok"><span class="dot"></span>Подписка активна</span>'
    elif st == "expired":
        title, pill = "Подписка закончилась", '<span class="pill bad"><span class="dot"></span>Подписка истекла</span>'
    else:
        title, pill = "Нет подписки", '<span class="pill bad"><span class="dot"></span>Не активна</span>'
    subtitle = f"до {devices} {plural(devices, ('устройства', 'устройств', 'устройств'))} · 50 ГБ трафика"
    if st == "expired":
        subtitle = "Продлите — и VPN заработает сразу, без переустановки"
    elif st == "none":
        subtitle = "Оформите подписку — подключение займёт минуту"

    # --- кольцо ---
    if left >= 86400:
        rnum, runit = int(left // 86400), plural(int(left // 86400), ("день", "дня", "дней"))
    elif left >= 3600:
        rnum, runit = int(left // 3600), plural(int(left // 3600), ("час", "часа", "часов"))
    elif left > 0:
        rnum, runit = max(1, int(left // 60)), plural(max(1, int(left // 60)), ("минута", "минуты", "минут"))
    else:
        rnum, runit = 0, "дней"
    total = max(float(ctx.get("plan_days") or 30) * 86400, left, 1)
    frac = 0 if left <= 0 else min(1.0, max(0.03, left / total))
    ring_off = f"{314.16 * (1 - frac):.2f}"
    ring_label = f"Осталось {rnum} {runit}"

    # --- даты ---
    if st in ("active", "trial"):
        exp_line = f'Действует до <b>{date_ru(exp, with_time=left < 3 * 86400)}</b>'
        left_line = f'<div class="left">{IC["clock"]}Осталось <b id="leftT">{left_text(left)}</b></div>' if left < 3 * 86400 else ""
    elif st == "expired":
        exp_line = f'Закончилась <b>{date_ru(exp)}</b>'
        left_line = ""
    else:
        exp_line = 'Выберите тариф в боте — это пара касаний'
        left_line = ""

    onl_cls, onl_txt = online_state(ctx.get("panel"), now)
    onl = (f'<div class="onl {onl_cls}" id="onl"><span class="dot"></span><span id="onlT">{esc(onl_txt)}</span></div>'
           if st in ("active", "trial") else "")
    locs = ctx.get("locs") or {}
    loc_on = sum(1 for k, _, _ in LOCS if locs.get(k))

    # --- главная кнопка ---
    happ = "happ://add/" + sub
    sec_row = (f'<div class="row2"><button type="button" class="btn btn-sec rp" data-copy="sub">{IC["copy"]}<span class="t">Скопировать</span></button>'
               f'<button type="button" class="btn btn-sec rp" data-qr="1">{IC["qr"]}<span class="t">QR-код</span></button></div>')
    if st in ("active", "trial"):
        cta = (f'<a class="btn btn-main" id="cta" href="{esc(happ)}" data-dl="1">{IC["bolt"]}<span class="t">Подключить в 1 клик'
               f'<small>откроется приложение Happ</small></span></a>{sec_row}')
        if st == "trial":
            cta += (f'<div class="promo"><span class="pe">🎁</span><span><b>Понравилось? Оставайтесь с нами</b>'
                    f'<p>Подписка — от {min_rub} ₽ в месяц, 50 ГБ трафика и до 5 устройств</p></span>'
                    f'<a class="btn btn-gold rp" href="{esc(renew_url)}">{IC["card"]}<span class="t">Выбрать тариф</span></a></div>')
        else:
            cta += f'<a class="more" href="{esc(renew_url)}">Продлить или сменить тариф {IC["arrow"]}</a>'
        dock = (f'<a class="btn btn-main" href="{esc(happ)}" data-dl="1">{IC["bolt"]}<span class="t">Подключить</span></a>'
                f'<button type="button" class="sq rp" data-copy="sub" aria-label="Скопировать ссылку">{IC["copy"]}</button>')
    else:
        cta = (f'<a class="btn btn-gold" id="cta" href="{esc(renew_url)}">{IC["card"]}<span class="t">'
               f'{"Продлить подписку" if st == "expired" else "Оформить подписку"}<small>от {min_rub} ₽ в месяц · 50 ГБ</small></span></a>'
               + ('<div class="warnbox">После оплаты всё заработает само: ссылка и настройки в приложении останутся прежними.</div>'
                  if st == "expired" else '<div class="warnbox">Оплата в боте занимает минуту — подписка включится сразу.</div>'))
        dock = (f'<a class="btn btn-gold" href="{esc(renew_url)}">{IC["card"]}<span class="t">'
                f'{"Продлить" if st == "expired" else "Оформить"} — от {min_rub} ₽</span></a>'
                f'<a class="sq rp" href="https://t.me/{esc(support)}" aria-label="Поддержка"><svg class="ic" viewBox="0 0 24 24"><path d="M21 11.5a8.4 8.4 0 0 1-12.3 7.5L3 21l2-5.3A8.5 8.5 0 1 1 21 11.5z"/></svg></a>')

    # --- рефералка ---
    tg = ctx.get("tg_id") or ""
    ref = f"https://t.me/{bot}?start={tg}"
    ref_text = "VAYNAH VPN — быстрый и защищённый VPN с серверами в Европе. Попробуй 👇"
    ref_share = "https://t.me/share/url?" + _up.urlencode({"url": ref, "text": ref_text}, quote_via=_up.quote)
    ref_days = int(ctx.get("ref_days") if ctx.get("ref_days") is not None else 3)
    ref_max = int(ctx.get("ref_max") or 10)

    data = {"sub": sub, "ref": ref, "refText": ref_text, "exp": exp, "now": int(now),
            "active": st in ("active", "trial")}
    data_js = _json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")

    vals = {
        "state_cls": "s-" + st,
        "pill": pill, "title": esc(title), "subtitle": esc(subtitle),
        "ring_num": str(rnum), "ring_unit": esc(runit), "ring_off": ring_off, "ring_label": esc(ring_label),
        "exp_line": exp_line, "left_line": left_line,
        "onl": onl,
        "traffic": esc(traffic_info(ctx.get("panel"))[1]), "traf_v": esc(traffic_info(ctx.get("panel"))[0]),
        "traf_pct": str(traffic_info(ctx.get("panel"))[2]), "devices": str(devices),
        "loc_on": str(loc_on), "loc_total": str(len(LOCS)), "cnt_cls": "" if loc_on == len(LOCS) else "bad",
        "cta": cta, "device_cta": device_cta, "dock": dock,
        "sub": esc(sub), "qr1": qr_svg(sub, "1"), "qr2": qr_svg(sub, "2"),
        "apps": _apps(sub), "locs": _locs_html(locs),
        "ref_days": str(ref_days), "ref_max": str(ref_max), "ref_inv": str(int(ctx.get("invited") or 0)),
        "ref_bonus": str(int(ctx.get("inv_paid") or 0) * ref_days),
        "ref_link": esc(ref), "ref_share": esc(ref_share),
        "renew_url": esc(renew_url if st != "none" else f"https://t.me/{bot}?start=menu"),
        "renew_title": "Продлить подписку" if st in ("active", "trial", "expired") else "Оформить подписку",
        "min_price": str(min_rub), "bot": esc(bot), "support": esc(support),
        "data": data_js,
    }
    return _re.sub(r"\{%(\w+)%\}", lambda mm: vals[mm.group(1)], TPL_ME)


def not_found_html(bot="MyVainakhBot"):
    return TPL_NF.replace("{%bot%}", esc(bot))


TPL_ME = r'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#020a06">
<meta name="color-scheme" content="dark">
<meta name="referrer" content="no-referrer">
<meta name="robots" content="noindex,nofollow">
<meta name="format-detection" content="telephone=no">
<title>VAYNAH VPN — Личный кабинет</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Cdefs%3E%3ClinearGradient id='g' x1='0' y1='0' x2='1' y2='1'%3E%3Cstop offset='0' stop-color='%2339ff83'/%3E%3Cstop offset='1' stop-color='%23b6ffd3'/%3E%3C/linearGradient%3E%3C/defs%3E%3Crect width='64' height='64' rx='18' fill='url(%23g)'/%3E%3Cpath d='M36 9 17 35h13l-3 20 20-27H34z' fill='%23fff'/%3E%3C/svg%3E">
<script>document.documentElement.className+=' js loading'</script>
<style>
:root{--bg:#020a06;--tx:#f2fff7;--tx2:#cfe8d9;--mut:#93b8a2;--mut2:#6c8f7a;--line:rgba(57,255,131,.13);--line2:rgba(57,255,131,.22);
--a1:#39ff83;--a2:#b6ffd3;--a3:#0fae55;--ok:#34d399;--okt:#6ee7b7;--okb:rgba(52,211,153,.12);--bad:#fb7185;--badt:#fda4af;--badb:rgba(251,113,133,.12);
--wt:#fcd34d;--wb:rgba(251,191,36,.1);--grad:linear-gradient(135deg,#39ff83,#b6ffd3);--r:24px;--sb:env(safe-area-inset-bottom,0px);--st:env(safe-area-inset-top,0px)}
*{box-sizing:border-box;margin:0;padding:0}
html{background:var(--bg);color-scheme:dark;-webkit-text-size-adjust:100%;text-size-adjust:100%}
body{min-height:100vh;min-height:100dvh;background:var(--bg);color:var(--tx);font:15px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,"Noto Sans","Helvetica Neue",Arial,sans-serif;-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;overflow-x:hidden;-webkit-tap-highlight-color:transparent}
a{color:inherit;text-decoration:none}
button{font:inherit;color:inherit;background:none;border:0;cursor:pointer;-webkit-appearance:none;appearance:none}
svg{display:block}
:focus-visible{outline:2px solid #39ff83;outline-offset:2px}
.ic{width:20px;height:20px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;flex:none}
.defs{position:absolute;width:0;height:0;overflow:hidden}
/* ---------- фон ---------- */
.bg{position:fixed;inset:0;z-index:0;overflow:hidden;pointer-events:none}
.bg i{position:absolute;border-radius:50%;will-change:transform}
.bg .b1{width:680px;height:680px;left:-260px;top:-300px;background:radial-gradient(closest-side,rgba(57,255,131,.42),transparent);animation:d1 22s ease-in-out infinite alternate}
.bg .b2{width:600px;height:600px;right:-280px;top:18%;background:radial-gradient(closest-side,rgba(15,174,85,.30),transparent);animation:d2 27s ease-in-out infinite alternate}
.bg .b3{width:560px;height:560px;left:15%;bottom:-320px;background:radial-gradient(closest-side,rgba(182,255,211,.22),transparent);animation:d3 31s ease-in-out infinite alternate}
.bg .grid{position:absolute;inset:0;background-image:linear-gradient(rgba(57,255,131,.055) 1px,transparent 1px),linear-gradient(90deg,rgba(57,255,131,.055) 1px,transparent 1px);background-size:46px 46px;-webkit-mask-image:radial-gradient(ellipse 90% 60% at 50% 0,#000 20%,transparent 72%);mask-image:radial-gradient(ellipse 90% 60% at 50% 0,#000 20%,transparent 72%)}
.bg .stars{position:absolute;inset:0;background-image:radial-gradient(1.2px 1.2px at 8% 22%,#fff9,transparent 60%),radial-gradient(1px 1px at 22% 68%,#fff7,transparent 60%),radial-gradient(1.4px 1.4px at 37% 12%,#c8ffe0,transparent 60%),radial-gradient(1px 1px at 52% 44%,#fff6,transparent 60%),radial-gradient(1.3px 1.3px at 68% 18%,#fff8,transparent 60%),radial-gradient(1px 1px at 78% 62%,#b6ffd3,transparent 60%),radial-gradient(1.2px 1.2px at 90% 32%,#fff8,transparent 60%),radial-gradient(1px 1px at 14% 88%,#fff6,transparent 60%),radial-gradient(1.2px 1.2px at 61% 84%,#a9ffd0,transparent 60%),radial-gradient(1px 1px at 95% 90%,#fff6,transparent 60%);animation:tw 5s ease-in-out infinite alternate}
@keyframes d1{to{transform:translate(140px,110px) scale(1.15)}}
@keyframes d2{to{transform:translate(-120px,80px) scale(1.1)}}
@keyframes d3{to{transform:translate(90px,-120px) scale(1.2)}}
@keyframes tw{from{opacity:.45}to{opacity:1}}
@keyframes spin{to{transform:rotate(360deg)}}
/* ---------- шапка / сетка ---------- */
.top{position:relative;z-index:2;max-width:1120px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:calc(14px + var(--st)) 16px 4px}
.brand{display:flex;align-items:center;gap:10px;font-weight:800;font-size:17px;letter-spacing:.4px}
.brand em{font-style:normal;color:var(--mut);font-weight:700}
.logo{width:36px;height:36px;border-radius:12px;display:grid;place-items:center;background:var(--grad);box-shadow:0 8px 22px -6px rgba(57,255,131,.75),inset 0 1px 0 rgba(255,255,255,.3)}
.logo svg{width:19px;height:19px;fill:#fff}
.chip{display:inline-flex;align-items:center;gap:8px;padding:9px 14px;border-radius:999px;background:rgba(255,255,255,.045);box-shadow:inset 0 0 0 1px var(--line2);font-size:13.5px;font-weight:650;color:var(--tx2);transition:background .2s}
.chip:hover{background:rgba(255,255,255,.08)}
.chip .ic{width:17px;height:17px}
.wrap{position:relative;z-index:1;max-width:1120px;margin:0 auto;padding:10px 14px calc(104px + var(--sb));display:grid;gap:14px}
.col{display:grid;gap:14px;min-width:0;align-content:start}
@media(min-width:600px) and (max-width:959px){.wrap{max-width:660px}}
@media(min-width:960px){.wrap{grid-template-columns:minmax(0,1.06fr) minmax(0,.94fr);align-items:start;gap:20px;padding:18px 24px 56px}.col{gap:20px}.top{padding:22px 24px 6px}}
/* ---------- карточки ---------- */
.card{position:relative;border-radius:var(--r);padding:18px;background:linear-gradient(180deg,rgba(8,30,19,.88),rgba(3,14,8,.92)) padding-box,linear-gradient(150deg,rgba(57,255,131,.34),rgba(57,255,131,.06) 40%,rgba(15,174,85,.24)) border-box;border:1px solid transparent;box-shadow:0 24px 60px -28px rgba(0,0,0,.75)}
@media(min-width:400px){.card{padding:20px}}
@media(min-width:960px){.card{padding:24px}}
.hd{display:flex;align-items:center;gap:11px;margin-bottom:15px}
.hd h2{flex:1;font-size:16.5px;font-weight:780;letter-spacing:.1px;line-height:1.25}
.hd h2 small{display:block;font-size:12.5px;font-weight:500;color:var(--mut);margin-top:2px;letter-spacing:0}
.hi{width:36px;height:36px;border-radius:12px;display:grid;place-items:center;flex:none;background:rgba(57,255,131,.13);color:#b6ffd3;box-shadow:inset 0 0 0 1px rgba(57,255,131,.22)}
.hi .ic{width:19px;height:19px}
.hi.v{background:rgba(15,174,85,.14);color:#b6ffd3;box-shadow:inset 0 0 0 1px rgba(15,174,85,.28)}
.hi.c{background:rgba(182,255,211,.12);color:#b6ffd3;box-shadow:inset 0 0 0 1px rgba(182,255,211,.24)}
.hi.g{background:rgba(52,211,153,.12);color:var(--okt);box-shadow:inset 0 0 0 1px rgba(52,211,153,.24)}
/* ---------- hero ---------- */
.hero{overflow:hidden}
.hero::before{content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;background:radial-gradient(460px 240px at 92% -12%,rgba(57,255,131,.30),transparent 70%),radial-gradient(320px 220px at -12% 112%,rgba(182,255,211,.13),transparent 70%)}
.s-expired .hero::before,.s-none .hero::before{background:radial-gradient(460px 240px at 92% -12%,rgba(251,113,133,.22),transparent 70%),radial-gradient(320px 220px at -12% 112%,rgba(251,191,36,.10),transparent 70%)}
.s-trial .hero::before{background:radial-gradient(460px 240px at 92% -12%,rgba(251,191,36,.20),transparent 70%),radial-gradient(320px 220px at -12% 112%,rgba(182,255,211,.13),transparent 70%)}
.h-top{position:relative;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:14px;align-items:center}
.pill{display:inline-flex;align-items:center;gap:8px;padding:6px 12px 6px 10px;border-radius:999px;font-size:12.5px;font-weight:750;letter-spacing:.2px;white-space:nowrap}
.pill.ok{background:var(--okb);color:var(--okt);box-shadow:inset 0 0 0 1px rgba(52,211,153,.3)}
.pill.bad{background:var(--badb);color:var(--badt);box-shadow:inset 0 0 0 1px rgba(251,113,133,.32)}
.pill.tr{background:var(--wb);color:var(--wt);box-shadow:inset 0 0 0 1px rgba(251,191,36,.3)}
.dot{position:relative;width:8px;height:8px;border-radius:50%;background:currentColor;flex:none}
.dot::after{content:"";position:absolute;inset:0;border-radius:50%;background:currentColor;animation:ping 2s cubic-bezier(0,0,.2,1) infinite}
.bad .dot::after,.off .dot::after,.dim .dot::after{display:none}
@keyframes ping{75%,100%{transform:scale(2.7);opacity:0}}
.h-title{font-size:27px;line-height:1.12;font-weight:850;letter-spacing:-.5px;margin:12px 0 5px}
.h-sub{color:var(--mut);font-size:13.5px}
.ring{position:relative;width:108px;height:108px;flex:none}
.ring svg{width:100%;height:100%;transform:rotate(-90deg);filter:drop-shadow(0 0 8px rgba(182,255,211,.35))}
.ring circle{fill:none;stroke-width:9}
.ring .trk{stroke:rgba(255,255,255,.07)}
.ring .bar{stroke:url(#gRing);stroke-linecap:round;stroke-dasharray:314.16;stroke-dashoffset:314.16;transition:stroke-dashoffset 1.9s cubic-bezier(.22,1,.36,1) .2s}
html:not(.js) .ring .bar{stroke-dashoffset:var(--off)}
.s-expired .ring .bar,.s-none .ring .bar{stroke:url(#gBad)}
.s-trial .ring .bar{stroke:url(#gTr)}
.ring .c{position:absolute;inset:0;display:grid;place-content:center;text-align:center}
.ring .n{font-size:32px;font-weight:850;line-height:1;font-variant-numeric:tabular-nums;letter-spacing:-1px;background:linear-gradient(135deg,#eafff2,#b6ffd3);-webkit-background-clip:text;background-clip:text;color:transparent}
.s-expired .ring .n,.s-none .ring .n{background:linear-gradient(135deg,#fda4af,#fcd34d);-webkit-background-clip:text;background-clip:text}
.s-trial .ring .n{background:linear-gradient(135deg,#fde68a,#b6ffd3);-webkit-background-clip:text;background-clip:text}
.ring .u{font-size:11.5px;color:var(--mut);margin-top:5px;font-weight:600}
@media(min-width:400px){.ring{width:124px;height:124px}.ring .n{font-size:36px}.h-title{font-size:29px}}
.h-meta{position:relative;display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px 14px;margin-top:14px;font-size:14px;color:var(--tx2)}
.h-meta b{color:var(--tx);font-weight:700}
.onl{display:inline-flex;align-items:center;gap:7px;font-size:12.5px;font-weight:650;color:var(--mut)}
.onl.ok{color:var(--okt)}.onl.warn{color:var(--wt)}
.onl.dim .dot{opacity:.6}
.stats{position:relative;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:16px 0}
.stat{padding:11px 10px;border-radius:15px;background:rgba(255,255,255,.035);box-shadow:inset 0 0 0 1px var(--line)}
.stat .k{display:flex;align-items:center;gap:6px;color:var(--mut);font-size:11.5px;font-weight:650;white-space:nowrap}
.stat .k .ic{width:14px;height:14px}
.stat .v{font-size:19px;font-weight:850;margin-top:3px;line-height:1.2;font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.stat .v.inf{font-size:25px;line-height:1.1;font-weight:700}
.stat .s{font-size:11px;color:var(--mut2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.left{position:relative;font-size:13px;color:var(--mut);margin-top:-6px;margin-bottom:14px}
.left b{color:var(--tx2)}
@media(max-width:359px){.card{padding:16px}.wrap{padding-left:10px;padding-right:10px}.ring{width:94px;height:94px}.ring .n{font-size:27px}.h-title{font-size:23px}.stat{padding:10px 8px}.stat .k{font-size:10.5px}.stat .k .ic{display:none}.stat .v{font-size:16.5px}.stat .v.inf{font-size:21px}.tabs button{font-size:11.5px;letter-spacing:-.1px}.btn{font-size:15.5px}.hd h2{font-size:15.5px}.app{padding:11px;gap:10px;grid-template-columns:40px minmax(0,1fr)}.ai{width:40px;height:40px;font-size:13.5px}}
/* ---------- кнопки ---------- */
.btn{position:relative;overflow:hidden;display:flex;align-items:center;justify-content:center;gap:10px;width:100%;min-height:56px;padding:12px 18px;border-radius:17px;font-size:16.5px;font-weight:780;letter-spacing:.1px;text-align:center;line-height:1.2;transition:transform .16s ease,box-shadow .25s ease,background .25s;-webkit-user-select:none;user-select:none;isolation:isolate}
.btn:active{transform:scale(.975)}
.btn .t small{display:block;font-size:11.5px;font-weight:600;opacity:.82;margin-top:2px;letter-spacing:.1px}
.btn-main{color:#fff;background:linear-gradient(135deg,#39ff83 0%,#13d36a 45%,#0fae55 100%);box-shadow:0 16px 36px -14px rgba(19,211,106,.85),inset 0 1px 0 rgba(255,255,255,.28)}
.btn-main::after,.btn-gold::after{content:"";position:absolute;z-index:-1;top:0;bottom:0;left:0;width:42%;background:linear-gradient(100deg,transparent,rgba(255,255,255,.4),transparent);transform:translateX(-150%) skewX(-18deg);animation:shine 4.6s ease-in-out 2.6s infinite}
@keyframes shine{0%{transform:translateX(-150%) skewX(-18deg)}24%,100%{transform:translateX(360%) skewX(-18deg)}}
.btn-main .ic,.btn-gold .ic{width:22px;height:22px;stroke-width:2.3}
.btn-gold{color:#1d1303;background:linear-gradient(135deg,#fde68a,#fbbf24 55%,#f59e0b);box-shadow:0 16px 36px -14px rgba(245,158,11,.75),inset 0 1px 0 rgba(255,255,255,.5)}
.btn-sec{min-height:48px;font-size:14.5px;font-weight:680;color:var(--tx);background:rgba(255,255,255,.05);box-shadow:inset 0 0 0 1px var(--line2)}
.btn-sec:hover{background:rgba(255,255,255,.085)}
.btn-sec .ic{width:18px;height:18px}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:8px}
.more{display:flex;align-items:center;justify-content:center;gap:6px;margin-top:14px;font-size:13.5px;font-weight:650;color:#eafff2}
.more .ic{width:16px;height:16px;transition:transform .2s}
.more:hover .ic{transform:translateX(3px)}
.rpl{position:absolute;z-index:-1;border-radius:50%;pointer-events:none;background:rgba(255,255,255,.32);transform:scale(0);animation:rpl .65s ease-out forwards}
@keyframes rpl{to{transform:scale(1);opacity:0}}
.promo{position:relative;display:grid;grid-template-columns:auto 1fr;gap:12px;align-items:center;margin-top:14px;padding:13px 14px;border-radius:16px;background:linear-gradient(135deg,rgba(251,191,36,.12),rgba(245,158,11,.04));box-shadow:inset 0 0 0 1px rgba(251,191,36,.28)}
.promo .pe{font-size:24px;line-height:1}
.promo b{display:block;font-size:14px}.promo p{font-size:12.5px;color:var(--tx2)}
.promo a{grid-column:1/-1}
.warnbox{position:relative;margin-top:12px;font-size:13px;color:var(--tx2);padding:11px 13px;border-radius:14px;background:rgba(255,255,255,.035);box-shadow:inset 0 0 0 1px var(--line)}
/* ---------- шаги / ссылка / QR ---------- */
.cgrid{display:grid;gap:16px}
.steps{display:grid;gap:14px}
.step{position:relative;display:grid;grid-template-columns:34px minmax(0,1fr);gap:12px;align-items:start}
.step:not(:last-child)::before{content:"";position:absolute;left:16.5px;top:40px;bottom:-12px;width:1px;background:linear-gradient(rgba(57,255,131,.45),rgba(57,255,131,0))}
.no{width:34px;height:34px;border-radius:11px;display:grid;place-items:center;font-weight:850;font-size:14px;color:#fff;background:var(--grad);box-shadow:0 8px 18px -8px rgba(182,255,211,.8)}
.step b{display:block;font-size:14.5px;font-weight:720;padding-top:6px}
.step p{color:var(--mut);font-size:13px;margin-top:3px}
.step p a{color:#eafff2}
.linkbox{display:flex;align-items:center;gap:10px;width:100%;margin-top:10px;padding:9px 9px 9px 13px;border-radius:14px;text-align:left;background:rgba(1,10,5,.6);box-shadow:inset 0 0 0 1px var(--line2);transition:box-shadow .2s,background .2s,transform .15s}
.linkbox:hover{box-shadow:inset 0 0 0 1px rgba(57,255,131,.5)}
.linkbox:active{transform:scale(.99)}
.linkbox code{flex:1;min-width:0;font:12.5px/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;color:#a9ffd0;word-break:break-all}
.lb-ic{flex:none;width:38px;height:38px;border-radius:11px;display:grid;place-items:center;background:rgba(57,255,131,.17);color:#b6ffd3;transition:background .25s,color .25s}
.lb-ic .ic{width:17px;height:17px}
.i2{display:none}
.copied .i1{display:none}.copied .i2{display:block}
.copied .lb-ic{background:rgba(52,211,153,.18);color:var(--okt)}
.secret{display:flex;gap:8px;align-items:flex-start;margin-top:10px;font-size:12px;color:var(--mut2)}
.secret .ic{width:15px;height:15px;margin-top:1px}
.qrbox{display:none;text-align:center}
.qr{background:#fff;border-radius:20px;padding:12px;box-shadow:0 0 0 6px rgba(255,255,255,.04),0 22px 44px -20px rgba(182,255,211,.55)}
.qr svg{width:100%;height:auto}
.qrbox p{font-size:12px;color:var(--mut);margin-top:12px;line-height:1.4}
@media(min-width:960px){.cgrid{grid-template-columns:minmax(0,1fr) 188px;align-items:start}.qrbox{display:block}.qr-m{display:none}}
/* ---------- приложения ---------- */
.tabs{position:relative;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));padding:4px;margin-bottom:14px;border-radius:15px;background:rgba(1,10,5,.55);box-shadow:inset 0 0 0 1px var(--line)}
.tabs button{position:relative;z-index:1;padding:9px 2px;border-radius:11px;font-size:13px;font-weight:720;color:var(--mut);transition:color .3s;white-space:nowrap}
.tabs button.on{color:#fff}
.tabs .ind{position:absolute;z-index:0;top:4px;bottom:4px;left:4px;width:calc((100% - 8px)/4);border-radius:11px;background:linear-gradient(135deg,#39ff83,#13d36a);box-shadow:0 8px 20px -8px rgba(57,255,131,.9),inset 0 1px 0 rgba(255,255,255,.22);transition:transform .45s cubic-bezier(.3,1.25,.5,1)}
.pane{display:none}
.pane.on{display:grid;gap:10px;animation:pane .45s cubic-bezier(.2,.8,.2,1) both}
@keyframes pane{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
html:not(.js) .pane{display:grid;gap:10px;margin-bottom:12px}
.app{display:grid;grid-template-columns:46px minmax(0,1fr);gap:12px;padding:13px;border-radius:17px;background:rgba(255,255,255,.03);box-shadow:inset 0 0 0 1px var(--line)}
.app.rec{background:linear-gradient(135deg,rgba(57,255,131,.12),rgba(182,255,211,.035));box-shadow:inset 0 0 0 1px rgba(57,255,131,.38)}
.ai{width:46px;height:46px;border-radius:14px;display:grid;place-items:center;font-weight:850;font-size:15px;color:#fff;letter-spacing:-.4px;box-shadow:inset 0 1px 0 rgba(255,255,255,.3),0 8px 18px -10px rgba(0,0,0,.8)}
.an{display:flex;align-items:center;flex-wrap:wrap;gap:6px 8px;font-weight:780;font-size:15.5px;line-height:1.3}
.tag{font-size:10px;font-weight:850;letter-spacing:.5px;text-transform:uppercase;padding:3px 7px;border-radius:7px;background:rgba(52,211,153,.15);color:var(--okt)}
.ad{font-size:12.5px;color:var(--mut);margin-top:2px;line-height:1.4}
.ab{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.ab a,.ab button{display:inline-flex;align-items:center;gap:6px;padding:8px 12px;border-radius:11px;font-size:12.5px;font-weight:720;background:rgba(255,255,255,.06);box-shadow:inset 0 0 0 1px var(--line2);transition:background .2s,transform .15s}
.ab a:active,.ab button:active{transform:scale(.96)}
.ab .p{color:#fff;background:var(--grad);box-shadow:0 8px 18px -10px rgba(182,255,211,.9)}
.ab .ic{width:15px;height:15px}
.note{font-size:12.5px;color:var(--tx2);line-height:1.5;padding:11px 13px;border-radius:14px;background:rgba(251,191,36,.06);box-shadow:inset 0 0 0 1px rgba(251,191,36,.18)}
.note a{color:#eafff2;text-decoration:underline;text-underline-offset:2px}
/* ---------- локации ---------- */
.cnt{font-size:12.5px;font-weight:750;padding:5px 11px;border-radius:999px;background:var(--okb);color:var(--okt);white-space:nowrap}
.cnt.bad{background:var(--badb);color:var(--badt)}
.locs{display:grid}
.loc{display:grid;grid-template-columns:40px minmax(0,1fr) auto;gap:12px;align-items:center;padding:11px 2px;border-bottom:1px solid var(--line)}
.loc:last-child{border-bottom:0}
.flag{position:relative;width:40px;height:40px;border-radius:50%;overflow:hidden;box-shadow:0 0 0 2px rgba(255,255,255,.08),0 8px 16px -8px rgba(0,0,0,.8)}
.flag svg{width:100%;height:100%}
.flag::after{content:"";position:absolute;inset:0;border-radius:50%;background:linear-gradient(155deg,rgba(255,255,255,.38),rgba(255,255,255,0) 46%,rgba(0,0,0,.22))}
.loc b{display:block;font-size:14.5px;font-weight:720;line-height:1.3}
.loc small{display:block;font-size:12px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.st{display:inline-flex;align-items:center;gap:7px;padding:5px 10px;border-radius:999px;font-size:12px;font-weight:750;white-space:nowrap;transition:background .4s,color .4s}
.st.on{background:var(--okb);color:var(--okt)}
.st.off{background:var(--badb);color:var(--badt)}
.st.flash{animation:flash .9s ease}
@keyframes flash{30%{transform:scale(1.08)}}
.lfoot{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:12px;font-size:12px;color:var(--mut2)}
.rf{display:inline-flex;align-items:center;gap:7px;padding:8px 12px;border-radius:11px;font-size:12.5px;font-weight:700;color:var(--tx2);background:rgba(255,255,255,.05);box-shadow:inset 0 0 0 1px var(--line)}
.rf .ic{width:15px;height:15px}
.rf.spin .ic{animation:spin .8s linear infinite}
/* ---------- рефералка / советы / действия ---------- */
.ref{overflow:hidden}
.ref::before{content:"";position:absolute;right:-70px;top:-80px;width:230px;height:230px;border-radius:50%;background:radial-gradient(closest-side,rgba(15,174,85,.32),transparent);pointer-events:none}
.rbig{position:relative;font-size:21px;font-weight:850;letter-spacing:-.3px;line-height:1.2}
.rbig em{font-style:normal;background:linear-gradient(135deg,#b6ffd3,#b6ffd3);-webkit-background-clip:text;background-clip:text;color:transparent}
.ref p.d{position:relative;font-size:13px;color:var(--mut);margin-top:6px}
.rstats{position:relative;display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:14px 0 4px}
.rstats .stat .v{font-size:21px}
.tips{display:grid;gap:10px}
@media(min-width:520px) and (max-width:959px){.tips{grid-template-columns:1fr 1fr}}
.tip{display:grid;grid-template-columns:38px minmax(0,1fr);gap:11px;align-items:start;padding:12px;border-radius:16px;background:rgba(255,255,255,.03);box-shadow:inset 0 0 0 1px var(--line)}
.te{width:38px;height:38px;border-radius:12px;display:grid;place-items:center;font-size:19px;background:rgba(57,255,131,.1)}
.tip b{display:block;font-size:13.5px;font-weight:720;line-height:1.3}
.tip p{font-size:12.5px;color:var(--mut);margin-top:2px;line-height:1.4}
.acts{display:grid;gap:8px}
.act{display:grid;grid-template-columns:42px minmax(0,1fr) 18px;gap:12px;align-items:center;padding:12px;border-radius:17px;background:rgba(255,255,255,.03);box-shadow:inset 0 0 0 1px var(--line);transition:background .2s,transform .15s}
.act:hover{background:rgba(255,255,255,.06)}
.act:active{transform:scale(.985)}
.act b{display:block;font-size:14.5px;font-weight:720}
.act small{display:block;font-size:12px;color:var(--mut)}
.act .arr{width:18px;height:18px;color:var(--mut2)}
.foot{text-align:center;color:var(--mut2);font-size:12px;line-height:1.7;padding:6px 0 0}
.foot a{color:var(--mut)}
/* ---------- док (моб.) / тост / шторка ---------- */
.dock{position:fixed;z-index:30;left:10px;right:10px;bottom:calc(10px + var(--sb));display:grid;grid-template-columns:minmax(0,1fr) 52px;gap:8px;padding:7px;border-radius:22px;background:rgba(3,16,9,.82);-webkit-backdrop-filter:blur(18px) saturate(1.5);backdrop-filter:blur(18px) saturate(1.5);box-shadow:0 20px 44px -14px rgba(0,0,0,.85),inset 0 0 0 1px var(--line2);transform:translateY(150%);transition:transform .5s cubic-bezier(.2,.9,.25,1.1);max-width:560px;margin:0 auto}
.dock.show{transform:none}
.dock .btn{min-height:50px;font-size:15.5px;border-radius:16px}
.dock .sq{display:grid;place-items:center;border-radius:16px;background:rgba(255,255,255,.07);box-shadow:inset 0 0 0 1px var(--line2)}
.dock .sq .ic{width:21px;height:21px}
@media(min-width:960px){.dock{display:none}}
.toast{position:fixed;z-index:70;left:50%;bottom:calc(86px + var(--sb));display:flex;align-items:center;gap:10px;width:max-content;max-width:calc(100vw - 28px);padding:12px 16px 12px 12px;border-radius:16px;background:rgba(5,24,14,.96);box-shadow:0 20px 44px -12px rgba(0,0,0,.8),inset 0 0 0 1px rgba(52,211,153,.35);font-size:14px;font-weight:650;opacity:0;transform:translate(-50%,26px) scale(.96);transition:transform .4s cubic-bezier(.2,.9,.3,1.25),opacity .25s;pointer-events:none}
.toast.on{opacity:1;transform:translate(-50%,0)}
.toast .ti{width:26px;height:26px;border-radius:50%;display:grid;place-items:center;flex:none;background:rgba(52,211,153,.18);color:var(--okt)}
.toast .ti .ic{width:15px;height:15px;stroke-width:2.6}
.toast.warn{box-shadow:0 20px 44px -12px rgba(0,0,0,.8),inset 0 0 0 1px rgba(251,191,36,.4)}
.toast.warn .ti{background:rgba(251,191,36,.16);color:var(--wt)}
@media(min-width:960px){.toast{bottom:32px}}
.sheet.on~.toast{bottom:auto;top:calc(14px + var(--st));transform:translate(-50%,-26px) scale(.96)}
.sheet.on~.toast.on{transform:translate(-50%,0)}
.sheet{position:fixed;inset:0;z-index:60;display:flex;align-items:flex-end;justify-content:center;visibility:hidden;transition:visibility 0s linear .5s}
.sheet.on{visibility:visible;transition-delay:0s}
.sheet .ov{position:absolute;inset:0;background:rgba(2,4,10,.7);opacity:0;transition:opacity .35s}
.sheet.on .ov{opacity:1}
.sheet .pn{position:relative;width:100%;max-width:430px;margin:0 8px calc(8px + var(--sb));padding:22px 20px 20px;border-radius:28px;text-align:center;background:linear-gradient(180deg,#0a2a18,#04140b);box-shadow:0 -10px 60px -10px rgba(0,0,0,.8),inset 0 0 0 1px var(--line2);transform:translateY(112%);transition:transform .5s cubic-bezier(.2,.9,.25,1.04)}
.sheet.on .pn{transform:none}
@media(min-width:600px){.sheet{align-items:center}.sheet .pn{margin:0;transform:translateY(24px) scale(.94);opacity:0;transition:transform .4s cubic-bezier(.2,.9,.3,1.2),opacity .3s}.sheet.on .pn{transform:none;opacity:1}}
.grab{width:42px;height:5px;border-radius:9px;background:rgba(255,255,255,.18);margin:-8px auto 14px}
.sheet h3{font-size:18px;font-weight:800}
.sheet p{font-size:13px;color:var(--mut);margin-top:4px}
.sheet .qr{width:min(76vw,280px);margin:16px auto 16px}
.x{position:absolute;right:12px;top:12px;width:36px;height:36px;border-radius:50%;display:grid;place-items:center;background:rgba(255,255,255,.07)}
.x .ic{width:18px;height:18px}
/* ---------- появление ---------- */
.js .rv{opacity:0;transform:translateY(24px) scale(.985);animation:rvf 0s 6s forwards}
.js.ready .rv{animation:rv .9s cubic-bezier(.16,1,.3,1) forwards;animation-delay:calc(var(--d,0) * 85ms)}
.js .li{opacity:0;transform:translateX(-10px);animation:rvf 0s 6s forwards}
.js.ready .li{animation:rv .7s cubic-bezier(.16,1,.3,1) forwards;animation-delay:calc(var(--d,0) * 85ms + var(--i,0) * 70ms + 220ms)}
@keyframes rv{to{opacity:1;transform:none}}
@keyframes rvf{to{opacity:1;transform:none}}
/* ---------- заставка ---------- */
#sp{position:fixed;inset:0;z-index:100;display:grid;place-items:center;overflow:hidden;background:radial-gradient(900px 700px at 50% 42%,#073a20 0%,#03140b 45%,#010604 100%);transition:opacity .75s ease .08s,visibility 0s linear .9s;animation:spf .6s ease 6.5s forwards;touch-action:none}
html:not(.js) #sp{display:none}
#sp.out{opacity:0;visibility:hidden}
@keyframes spf{to{opacity:0;visibility:hidden}}
#sp .aur{position:absolute;inset:-20%;background:radial-gradient(40% 30% at 30% 35%,rgba(57,255,131,.22),transparent 70%),radial-gradient(35% 30% at 72% 62%,rgba(15,174,85,.2),transparent 70%),radial-gradient(30% 25% at 55% 30%,rgba(182,255,211,.14),transparent 70%);animation:aur 7s ease-in-out infinite alternate}
@keyframes aur{to{transform:rotate(14deg) scale(1.12)}}
#sp .in{position:relative;display:grid;justify-items:center;transition:transform .75s cubic-bezier(.7,0,.3,1),opacity .55s ease}
#sp.out .in{transform:scale(1.14);opacity:0}
.orb{position:relative;width:200px;height:200px}
.orb>*{position:absolute;border-radius:50%}
.orb .r1{inset:0;border:1px dashed rgba(57,255,131,.33);animation:spin 22s linear infinite}
.orb .r2{inset:17px;border:2px solid transparent;border-top-color:#39ff83;border-right-color:rgba(57,255,131,.28);animation:spin 2.4s cubic-bezier(.55,.15,.45,.85) infinite}
.orb .r3{inset:34px;border:2px solid transparent;border-bottom-color:#b6ffd3;border-left-color:rgba(182,255,211,.28);animation:spin 1.7s linear infinite reverse}
.orb .rad{inset:6px;background:conic-gradient(from 0deg,rgba(182,255,211,0) 0deg,rgba(182,255,211,.2) 70deg,rgba(182,255,211,0) 71deg);-webkit-mask:radial-gradient(circle,transparent 52%,#000 53%);mask:radial-gradient(circle,transparent 52%,#000 53%);animation:spin 3s linear infinite}
.orb .sat{inset:0;animation:spin 3.4s linear infinite}
.orb .sat::before{content:"";position:absolute;top:-4px;left:50%;width:8px;height:8px;margin-left:-4px;border-radius:50%;background:#b6ffd3;box-shadow:0 0 14px 4px rgba(182,255,211,.75)}
.orb .s2{inset:17px;animation-duration:5s;animation-direction:reverse}
.orb .s2::before{background:#b6ffd3;box-shadow:0 0 14px 4px rgba(15,174,85,.75)}
.orb .s3{inset:34px;animation-duration:2.6s}
.orb .s3::before{width:6px;height:6px;margin-left:-3px;top:-3px;background:#eafff2;box-shadow:0 0 12px 3px rgba(57,255,131,.8)}
.orb .wv{inset:56px;border:1.5px solid rgba(182,255,211,.55);animation:wave 2.8s cubic-bezier(.2,.6,.3,1) infinite}
.orb .w2{animation-delay:1.4s}
@keyframes wave{0%{transform:scale(.75);opacity:.95}100%{transform:scale(2.15);opacity:0}}
.orb .core{inset:56px;display:grid;place-items:center;background:radial-gradient(circle at 34% 28%,#0d4a2c,#04160c 72%);box-shadow:0 0 0 1px rgba(57,255,131,.35),0 0 44px rgba(57,255,131,.5),inset 0 0 22px rgba(182,255,211,.28);animation:breathe 2.6s ease-in-out infinite}
@keyframes breathe{50%{box-shadow:0 0 0 1px rgba(57,255,131,.5),0 0 76px rgba(57,255,131,.75),inset 0 0 28px rgba(182,255,211,.45)}}
.core svg{width:46px;height:46px;overflow:visible}
.core .bs{fill:none;stroke:url(#gBolt);stroke-width:2.4;stroke-linejoin:round;stroke-dasharray:170;stroke-dashoffset:170;animation:draw 1.15s cubic-bezier(.6,0,.2,1) .15s forwards}
.core .bf{fill:url(#gBolt);opacity:0;animation:fill .7s ease 1.05s forwards}
@keyframes draw{to{stroke-dashoffset:0}}
@keyframes fill{to{opacity:1}}
.orb .burst{inset:62px;border:2px solid rgba(57,255,131,.9);opacity:0}
#sp.out .burst{animation:burst .8s cubic-bezier(.1,.6,.3,1) forwards}
@keyframes burst{0%{opacity:.9;transform:scale(.7)}100%{opacity:0;transform:scale(7)}}
.spn{display:flex;gap:3px;margin-top:28px;font-size:25px;font-weight:850;letter-spacing:5px;color:#eaf2ff;text-shadow:0 0 22px rgba(57,255,131,.55)}
.spn span{display:inline-block;opacity:0;transform:translateY(14px);filter:blur(6px);animation:lt .7s cubic-bezier(.2,.8,.2,1) forwards;animation-delay:calc(.25s + var(--i) * 70ms)}
.spn .g{color:#b6ffd3}
.spn .gap{width:10px}
@keyframes lt{to{opacity:1;transform:none;filter:blur(0)}}
.spm{height:20px;margin-top:10px;font-size:13px;color:var(--mut);letter-spacing:.3px;transition:opacity .2s}
.spb{width:190px;height:3px;margin-top:16px;border-radius:3px;overflow:hidden;background:rgba(255,255,255,.08)}
.spb i{display:block;width:0;height:100%;border-radius:inherit;background:linear-gradient(90deg,#39ff83,#b6ffd3,#eafff2);box-shadow:0 0 12px rgba(182,255,211,.85);transition:width .4s ease}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01ms!important;animation-iteration-count:1!important;animation-delay:0s!important;transition-duration:.01ms!important}}

/* ===== 16.11.2026 · концепция «Кавказ / Ингушетия»: ночные горы, золото орнамента, снег ===== */
:root{--bg:#020a06;--tx:#f2fff7;--tx2:#cfe8d9;--mut:#93b8a2;--mut2:#6c8f7a;--line:rgba(57,255,131,.13);--line2:rgba(57,255,131,.24);
--a1:#39ff83;--a2:#b6ffd3;--a3:#0fae55;--grad:linear-gradient(135deg,#b6ffd3,#39ff83 55%,#0fae55)}
.bg .b1{background:radial-gradient(closest-side,rgba(57,255,131,.20),transparent)!important}
.bg .b2{background:radial-gradient(closest-side,rgba(20,150,100,.22),transparent)!important}
.bg .b3{background:radial-gradient(closest-side,rgba(15,174,85,.16),transparent)!important}
body::after{content:"";position:fixed;left:0;right:0;bottom:0;height:34vh;max-height:300px;z-index:0;pointer-events:none;opacity:.9;
background:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1200 260' preserveAspectRatio='none'%3E%3Cpath d='M0 260 L0 170 L120 90 L210 150 L330 40 L430 130 L520 80 L640 160 L760 60 L880 140 L980 70 L1090 150 L1200 100 L1200 260Z' fill='%230b2a1a'/%3E%3Cpath d='M330 40 L360 62 L345 60 L330 72 L312 58 L300 62Z M760 60 L788 82 L772 80 L760 90 L744 78 L732 82Z M980 70 L1004 90 L990 88 L980 96 L966 86 L956 90Z' fill='%23d8ffe8' opacity='.55'/%3E%3Cpath d='M0 260 L0 210 L160 160 L300 200 L470 150 L620 205 L800 165 L960 210 L1100 175 L1200 200 L1200 260Z' fill='%23061a10'/%3E%3Cg fill='%23041109'%3E%3Cpath d='M250 205 L256 150 L262 140 L268 150 L274 205Z'/%3E%3Cpath d='M282 205 L286 168 L290 160 L294 168 L298 205Z'/%3E%3Cpath d='M860 200 L867 138 L874 126 L881 138 L888 200Z'/%3E%3Cpath d='M1040 205 L1044 170 L1048 162 L1052 170 L1056 205Z'/%3E%3C/g%3E%3C/svg%3E") bottom/100% 100% no-repeat}
body::before{content:"";position:fixed;left:0;right:0;top:0;height:6px;z-index:5;pointer-events:none;
background:repeating-linear-gradient(135deg,#39ff83 0 6px,transparent 6px 12px),linear-gradient(#0a5a2e,#0a5a2e);opacity:.85}
.card{background:linear-gradient(180deg,rgba(8,30,19,.9),rgba(3,14,8,.94)) padding-box,linear-gradient(150deg,rgba(57,255,131,.42),rgba(57,255,131,.06) 40%,rgba(15,174,85,.30)) border-box!important}
.hero::before{background:radial-gradient(460px 240px at 92% -12%,rgba(57,255,131,.24),transparent 70%),radial-gradient(320px 220px at -12% 112%,rgba(20,150,100,.18),transparent 70%)!important}
.logo{background:var(--grad)!important;box-shadow:0 8px 22px -6px rgba(57,255,131,.7),inset 0 1px 0 rgba(255,255,255,.4)!important;color:#032112}
.ring .n{background:linear-gradient(135deg,#eafff2,#39ff83)!important;-webkit-background-clip:text!important;background-clip:text!important}
.btn-main{color:#032112!important;background:linear-gradient(135deg,#8dffbc 0%,#39ff83 50%,#13d36a 100%)!important;box-shadow:0 16px 36px -14px rgba(57,255,131,.75),inset 0 1px 0 rgba(255,255,255,.45)!important}
.tabs .ind{background:linear-gradient(135deg,#39ff83,#0fae55)!important;box-shadow:0 8px 20px -8px rgba(57,255,131,.9),inset 0 1px 0 rgba(255,255,255,.3)!important}
.no{background:var(--grad)!important;color:#032112!important;box-shadow:0 8px 18px -8px rgba(57,255,131,.8)!important}
.step:not(:last-child)::before{background:linear-gradient(rgba(57,255,131,.5),rgba(57,255,131,0))!important}
.lb-ic{background:rgba(57,255,131,.16)!important;color:#b6ffd3!important}
.hi{background:rgba(57,255,131,.12)!important;color:#b6ffd3!important;box-shadow:inset 0 0 0 1px rgba(57,255,131,.24)!important}
.app.rec{background:linear-gradient(135deg,rgba(57,255,131,.13),rgba(15,174,85,.04))!important;box-shadow:inset 0 0 0 1px rgba(57,255,131,.38)!important}
.qr{box-shadow:0 0 0 6px rgba(57,255,131,.12),0 22px 44px -20px rgba(57,255,131,.5)!important}
.chip{box-shadow:inset 0 0 0 1px var(--line2)!important}
/* ===== 25.11.2026 · VAYNAH neon green ===== */
img.logo{width:38px;height:38px;border-radius:50%;object-fit:cover;background:none!important;box-shadow:0 0 0 1px rgba(57,255,131,.5),0 0 18px rgba(57,255,131,.55)!important;animation:lgb 3.2s ease-in-out infinite}
@keyframes lgb{50%{box-shadow:0 0 0 1px rgba(57,255,131,.8),0 0 30px rgba(57,255,131,.85)}}
.brand em{color:#39ff83!important;text-shadow:0 0 12px rgba(57,255,131,.6)}
body::after{background:url(/static/v/mountains.webp) center bottom/cover no-repeat!important;height:46vh!important;max-height:440px!important;opacity:.32!important;filter:hue-rotate(40deg) saturate(1.2);-webkit-mask-image:linear-gradient(to top,#000 35%,transparent);mask-image:linear-gradient(to top,#000 35%,transparent)}
body::before{background:linear-gradient(90deg,transparent,#39ff83 30%,#b6ffd3 50%,#39ff83 70%,transparent)!important;height:2px!important;opacity:.8!important;box-shadow:0 0 14px #39ff83}
.tbar{height:5px;border-radius:5px;background:rgba(255,255,255,.08);margin-top:7px;overflow:hidden}
.tbar i{display:block;height:100%;border-radius:5px;background:linear-gradient(90deg,#13d36a,#39ff83);box-shadow:0 0 10px #39ff83;transition:width 1.4s cubic-bezier(.22,1,.36,1)}
.btn-main{color:#032112!important;background:linear-gradient(135deg,#8dffbc 0%,#39ff83 45%,#13d36a 100%)!important;box-shadow:0 16px 40px -12px rgba(57,255,131,.75),inset 0 1px 0 rgba(255,255,255,.5)!important}
.btn-main .t small{opacity:.75}
.no{color:#032112!important}
.ab .p{color:#032112!important}
.ring svg{filter:drop-shadow(0 0 10px rgba(57,255,131,.55))!important}
.card{-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px)}
</style>
</head>
<body class="{%state_cls%}">
<svg class="defs" aria-hidden="true" focusable="false"><defs>
<linearGradient id="gRing" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#39ff83"/><stop offset="1" stop-color="#b6ffd3"/></linearGradient>
<linearGradient id="gBad" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fb7185"/><stop offset="1" stop-color="#fbbf24"/></linearGradient>
<linearGradient id="gTr" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fbbf24"/><stop offset="1" stop-color="#b6ffd3"/></linearGradient>
<linearGradient id="gBolt" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#eafff2"/><stop offset=".55" stop-color="#b6ffd3"/><stop offset="1" stop-color="#eafff2"/></linearGradient>
</defs></svg>

<div id="sp" role="status" aria-label="Загрузка личного кабинета">
  <div class="aur"></div>
  <div class="in">
    <div class="orb" aria-hidden="true">
      <i class="rad"></i><i class="r1"></i><i class="r2"></i><i class="r3"></i>
      <i class="sat"></i><i class="sat s2"></i><i class="sat s3"></i>
      <i class="wv"></i><i class="wv w2"></i><i class="burst"></i>
      <div class="core"><img src="/static/v/logo.webp" alt="" style="width:100%;height:100%;border-radius:50%"></div>
    </div>
    <div class="spn" aria-hidden="true"><span style="--i:0">V</span><span style="--i:1">A</span><span style="--i:2">Y</span><span style="--i:3">N</span><span style="--i:4">A</span><span class="gap"></span><span class="g" style="--i:5">V</span><span class="g" style="--i:6">P</span><span class="g" style="--i:7">N</span></div>
    <div class="spm" id="spm">Шифруем соединение…</div>
    <div class="spb"><i id="spb"></i></div>
  </div>
</div>

<div class="bg" aria-hidden="true"><i class="b1"></i><i class="b2"></i><i class="b3"></i><div class="grid"></div><div class="stars"></div></div>

<header class="top rv" style="--d:0">
  <div class="brand"><img class="logo" src="/static/v/logo.webp" alt=""><span>VAYNAH <em>VPN</em></span></div>
  <a class="chip" href="https://t.me/{%support%}"><svg class="ic" viewBox="0 0 24 24"><path d="M21 11.5a8.4 8.4 0 0 1-12.3 7.5L3 21l2-5.3A8.5 8.5 0 1 1 21 11.5z"/></svg>Поддержка</a>
</header>

<main class="wrap">
 <div class="col">

  <section class="card hero rv" style="--d:1">
    <div class="h-top">
      <div>
        {%pill%}
        <h1 class="h-title">{%title%}</h1>
        <div class="h-sub">{%subtitle%}</div>
      </div>
      <div class="ring" aria-label="{%ring_label%}">
        <svg viewBox="0 0 120 120"><circle class="trk" cx="60" cy="60" r="50"/><circle class="bar" id="ringBar" cx="60" cy="60" r="50" style="--off:{%ring_off%}"/></svg>
        <div class="c"><div class="n" id="ringN" data-to="{%ring_num%}">{%ring_num%}</div><div class="u">{%ring_unit%}</div></div>
      </div>
    </div>
    <div class="h-meta">
      <div>{%exp_line%}</div>
      {%onl%}
    </div>
    <div class="stats">
      <div class="stat"><div class="k"><svg class="ic" viewBox="0 0 24 24"><path d="M7 8.5C4.5 8.5 3 10 3 12s1.5 3.5 4 3.5c3.5 0 6.5-7 10-7 2.5 0 4 1.5 4 3.5s-1.5 3.5-4 3.5c-3.5 0-6.5-7-10-7z"/></svg>Трафик</div><div class="v" id="trv">{%traf_v%}</div><div class="s" id="trf">{%traffic%}</div><div class="tbar"><i id="trb" style="width:{%traf_pct%}%"></i></div></div>
      <div class="stat"><div class="k"><svg class="ic" viewBox="0 0 24 24"><rect x="2" y="4" width="14" height="11" rx="2"/><rect x="17.5" y="8" width="4.5" height="12" rx="1.3"/><path d="M6 19h6"/></svg>Устройства</div><div class="v">до {%devices%}</div><div class="s">одновременно</div></div>
      <div class="stat"><div class="k"><svg class="ic" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.6 2.7 3.9 5.7 3.9 9s-1.3 6.3-3.9 9c-2.6-2.7-3.9-5.7-3.9-9S9.4 5.7 12 3z"/></svg>Локации</div><div class="v"><span id="locN">{%loc_on%}</span>/{%loc_total%}</div><div class="s">онлайн</div></div>
    </div>
    {%left_line%}
    {%cta%}
    {%device_cta%}
  </section>

  <section class="card rv" style="--d:2" id="connect">
    <div class="hd"><span class="hi c"><svg class="ic" viewBox="0 0 24 24"><path d="M13.5 2 4.5 13.6h6.4L9.8 22l9.3-12h-6.6L13.5 2z"/></svg></span><h2>Подключение за минуту<small>Три шага — и защищённое соединение готово</small></h2></div>
    <div class="cgrid">
      <div class="steps">
        <div class="step"><span class="no">1</span><div><b>Установите приложение</b><p>Рекомендуем <b style="display:inline;padding:0">Happ</b> — ссылки для вашей системы <a href="#apps" data-scroll="apps">ниже ↓</a></p></div></div>
        <div class="step"><span class="no">2</span><div><b>Добавьте подписку</b><p>Кнопка «Подключить» добавит её сама. Или скопируйте ссылку и в приложении нажмите <b style="display:inline;padding:0">＋ → Вставить из буфера</b>.</p>
          <button type="button" class="linkbox" data-copy="sub" aria-label="Скопировать ссылку-подписку"><code id="subTxt">{%sub%}</code><span class="lb-ic"><svg class="ic i1" viewBox="0 0 24 24"><rect x="9" y="9" width="12" height="12" rx="2.5"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg><svg class="ic i2" viewBox="0 0 24 24"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg></span></button>
          <div class="secret"><svg class="ic" viewBox="0 0 24 24"><rect x="4" y="10" width="16" height="11" rx="2.5"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></svg><span>Это ваш личный ключ — не публикуйте его и не передавайте посторонним.</span></div>
        </div></div>
        <div class="step"><span class="no">3</span><div><b>Включите VPN</b><p>Выберите страну, например <b style="display:inline;padding:0">🇩🇪 Германия</b>. Если не подключается — выберите другую страну. Российские сайты при этом работают напрямую.</p></div></div>
      </div>
      <div class="qrbox"><div class="qr">{%qr1%}</div><p>Откройте кабинет на компьютере — и отсканируйте QR телефоном в Happ</p></div>
    </div>
  </section>

  <section class="card rv" style="--d:3" id="apps">
    <div class="hd"><span class="hi v"><svg class="ic" viewBox="0 0 24 24"><rect x="6" y="2.5" width="12" height="19" rx="3"/><path d="M11 18.5h2"/></svg></span><h2>Приложения<small>Выберите систему — покажем, что установить</small></h2></div>
    <div class="tabs" role="tablist"><i class="ind" id="ind"></i>
      <button type="button" role="tab" data-p="ios">iPhone</button><button type="button" role="tab" data-p="android">Android</button><button type="button" role="tab" data-p="win">Windows</button><button type="button" role="tab" data-p="mac">Mac</button>
    </div>
    {%apps%}
  </section>

 </div>
 <div class="col">

  <section class="card rv" style="--d:2" id="locs">
    <div class="hd"><span class="hi g"><svg class="ic" viewBox="0 0 24 24"><path d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.6"/></svg></span><h2>Локации<small>Статус серверов в реальном времени</small></h2><span class="cnt {%cnt_cls%}" id="locCnt">{%loc_on%} из {%loc_total%}</span></div>
    <div class="locs">{%locs%}</div>
    <div class="lfoot"><span id="upd">Обновлено только что</span><button type="button" class="rf" id="rf"><svg class="ic" viewBox="0 0 24 24"><path d="M20.5 12a8.5 8.5 0 1 1-2.6-6.1L20.5 8"/><path d="M20.5 3v5h-5"/></svg>Обновить</button></div>
  </section>

  <section class="card ref rv" style="--d:3">
    <div class="hd"><span class="hi v"><svg class="ic" viewBox="0 0 24 24"><rect x="3" y="8" width="18" height="4.5" rx="1.2"/><path d="M12 8v13M5 12.5V21h14v-8.5M12 8S10.6 3 7.6 3a2.5 2.5 0 0 0 0 5M12 8s1.4-5 4.4-5a2.5 2.5 0 0 1 0 5"/></svg></span><h2>Приглашайте друзей</h2></div>
    <div class="rbig">+{%ref_days%} дней <em>за каждого друга</em></div>
    <p class="d">Друг запустит бота по вашей ссылке и подпишется на канал — вам автоматически добавится {%ref_days%} дн. Засчитываем до {%ref_max%} друзей.</p>
    <div class="rstats">
      <div class="stat"><div class="k">Приглашено</div><div class="v">{%ref_inv%}</div></div>
      <div class="stat"><div class="k">Бонус получен</div><div class="v">+{%ref_bonus%} дн.</div></div>
    </div>
    <button type="button" class="linkbox" data-copy="ref" aria-label="Скопировать реферальную ссылку"><code>{%ref_link%}</code><span class="lb-ic"><svg class="ic i1" viewBox="0 0 24 24"><rect x="9" y="9" width="12" height="12" rx="2.5"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg><svg class="ic i2" viewBox="0 0 24 24"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg></span></button>
    <a class="btn btn-sec rp" style="margin-top:10px" id="refShare" href="{%ref_share%}"><svg class="ic" viewBox="0 0 24 24"><path d="M21.5 4.5 2.8 11.3c-.9.3-.9 1.6 0 1.9l4.7 1.6 1.8 5.6c.3.8 1.3 1 1.9.4l2.6-2.5 4.8 3.6c.7.5 1.6.1 1.8-.7l3-15.3c.2-.9-.7-1.7-1.9-1.4z"/><path d="m7.5 14.8 10-7.3"/></svg><span class="t">Отправить другу в Telegram</span></a>
  </section>

  <section class="card rv" style="--d:4">
    <div class="hd"><span class="hi"><svg class="ic" viewBox="0 0 24 24"><path d="M12 3 5 6v6c0 4.4 3 8 7 9 4-1 7-4.6 7-9V6l-7-3z"/><path d="m9 12 2 2 4-4"/></svg></span><h2>Как это работает</h2></div>
    <div class="tips">
      <div class="tip"><span class="te">🇷🇺</span><div><b>Российские сайты — напрямую</b><p>Банки, Госуслуги, Озон, Wildberries работают без отключения VPN</p></div></div>
      <div class="tip"><span class="te">🌍</span><div><b>Остальное — через VPN</b><p>Трафик шифруется и идёт через сервер выбранной страны</p></div></div>
      <div class="tip"><span class="te">🛡</span><div><b>Современное шифрование</b><p>Протокол VLESS и TLS 1.3 — ваши данные защищены в любой сети</p></div></div>
      <div class="tip"><span class="te">♾</span><div><b>50 ГБ и без логов</b><p>50 ГБ трафика на оплаченный период, высокая скорость, мы не храним историю посещений</p></div></div>
    </div>
  </section>

  <section class="card rv" style="--d:5">
    <div class="acts">
      <a class="act" href="{%renew_url%}"><span class="hi" style="width:42px;height:42px;background:rgba(251,191,36,.12);color:#fcd34d;box-shadow:inset 0 0 0 1px rgba(251,191,36,.26)"><svg class="ic" viewBox="0 0 24 24"><rect x="2.5" y="5" width="19" height="14" rx="3"/><path d="M2.5 10h19M6.5 15h4"/></svg></span><span><b>{%renew_title%}</b><small>Тарифы от {%min_price%} ₽ · Стандарт и Семейный</small></span><svg class="ic arr" viewBox="0 0 24 24"><path d="m9 6 6 6-6 6"/></svg></a>
      <a class="act" href="https://t.me/{%support%}"><span class="hi c" style="width:42px;height:42px"><svg class="ic" viewBox="0 0 24 24"><path d="M21 11.5a8.4 8.4 0 0 1-12.3 7.5L3 21l2-5.3A8.5 8.5 0 1 1 21 11.5z"/></svg></span><span><b>Поддержка 24/7</b><small>@{%support%} — поможем подключиться</small></span><svg class="ic arr" viewBox="0 0 24 24"><path d="m9 6 6 6-6 6"/></svg></a>
      <a class="act" href="https://t.me/{%bot%}"><span class="hi" style="width:42px;height:42px"><svg class="ic" viewBox="0 0 24 24"><path d="M21.5 4.5 2.8 11.3c-.9.3-.9 1.6 0 1.9l4.7 1.6 1.8 5.6c.3.8 1.3 1 1.9.4l2.6-2.5 4.8 3.6c.7.5 1.6.1 1.8-.7l3-15.3c.2-.9-.7-1.7-1.9-1.4z"/></svg></span><span><b>Открыть бота</b><small>@{%bot%} — подписка, промокоды, статус</small></span><svg class="ic arr" viewBox="0 0 24 24"><path d="m9 6 6 6-6 6"/></svg></a>
    </div>
  </section>

  <footer class="foot rv" style="--d:6">⚡ VAYNAH VPN — быстрый VPN без границ<br>Страница обновляется сама · <a href="https://t.me/{%bot%}">@{%bot%}</a></footer>
 </div>
</main>

<div class="dock" id="dock">{%dock%}</div>

<div class="sheet" id="qrs" role="dialog" aria-modal="true" aria-label="QR-код подписки">
  <div class="ov" data-close="1"></div>
  <div class="pn">
    <div class="grab"></div>
    <button type="button" class="x" data-close="1" aria-label="Закрыть"><svg class="ic" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg></button>
    <h3>QR-код подписки</h3>
    <p>Откройте Happ на другом устройстве → «＋» → «Сканировать QR»</p>
    <div class="qr">{%qr2%}</div>
    <button type="button" class="btn btn-sec rp" data-copy="sub"><svg class="ic" viewBox="0 0 24 24"><rect x="9" y="9" width="12" height="12" rx="2.5"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg><span class="t">Скопировать ссылку</span></button>
  </div>
</div>

<div class="toast" id="toast" role="status" aria-live="polite"><span class="ti"><svg class="ic" viewBox="0 0 24 24"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg></span><span id="toastT">Скопировано</span></div>

<script type="application/json" id="zd">{%data%}</script>
<script>
(function(){
var D={};try{D=JSON.parse(document.getElementById('zd').textContent)}catch(e){}
var H=document.documentElement,doc=document;
function $(id){return doc.getElementById(id)}
function all(s){return Array.prototype.slice.call(doc.querySelectorAll(s))}
var reduce=false;try{reduce=window.matchMedia('(prefers-reduced-motion: reduce)').matches}catch(e){}
var skew=(D.now?D.now*1000-Date.now():0);function now(){return Date.now()+skew}

/* ---------- заставка ---------- */
var sp=$('sp'),spm=$('spm'),spb=$('spb'),t0=Date.now(),seen=false,done=false;
try{seen=sessionStorage.getItem('iv_sp')==='1';sessionStorage.setItem('iv_sp','1')}catch(e){}
var minT=reduce?120:(seen?400:1100);
var msgs=['Шифруем соединение…','Проверяем серверы…','Загружаем подписку…','Готово'],mi=0,prog=6;
function msg(i){if(!spm)return;spm.style.opacity=0;setTimeout(function(){spm.textContent=msgs[i];spm.style.opacity=1},170)}
var pt=setInterval(function(){prog=Math.min(93,prog+(100-prog)*.14+Math.random()*3);if(spb)spb.style.width=prog+'%'},150);
var mt=setInterval(function(){if(mi<msgs.length-2){mi++;msg(mi)}},Math.max(260,minT/3.3));
function finish(){
  if(done)return;done=true;clearInterval(pt);clearInterval(mt);
  if(spb)spb.style.width='100%';msg(msgs.length-1);
  setTimeout(function(){
    if(sp)sp.classList.add('out');
    H.classList.add('ready');H.classList.remove('loading');
    try{startUI()}catch(e){}
    setTimeout(function(){if(sp&&sp.parentNode)sp.parentNode.removeChild(sp)},1100);
  },reduce?0:330);
}
function ready(){setTimeout(finish,Math.max(0,minT-(Date.now()-t0)))}
if(doc.readyState==='complete')ready();else window.addEventListener('load',ready);
setTimeout(finish,5000);
if(sp){sp.addEventListener('click',finish);sp.addEventListener('touchmove',function(e){e.preventDefault()},{passive:false})}

/* ---------- тост ---------- */
var tt;function toast(t,kind){var el=$('toast');if(!el)return;$('toastT').textContent=t;el.className='toast'+(kind==='warn'?' warn':'');void el.offsetWidth;el.classList.add('on');clearTimeout(tt);tt=setTimeout(function(){el.classList.remove('on')},kind==='warn'?3600:2000)}

/* ---------- копирование ---------- */
function copy(text,okMsg,el){
  function ok(){toast(okMsg||'Скопировано');try{navigator.vibrate&&navigator.vibrate(12)}catch(e){}
    if(el){var t=el.querySelector('.t'),o=t&&t.textContent;el.classList.add('copied');if(t)t.textContent='Скопировано';clearTimeout(el._ct);el._ct=setTimeout(function(){el.classList.remove('copied');if(t)t.textContent=o},1700)}}
  function fb(){var ta=doc.createElement('textarea');ta.value=text;ta.setAttribute('readonly','');ta.style.cssText='position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;font-size:16px';doc.body.appendChild(ta);ta.focus();ta.select();try{ta.setSelectionRange(0,text.length)}catch(e){}var r=false;try{r=doc.execCommand('copy')}catch(e){}doc.body.removeChild(ta);if(r)ok();else{try{window.prompt('Скопируйте ссылку:',text)}catch(e){}}}
  if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(text).then(ok,fb)}else fb();
}
doc.addEventListener('click',function(e){
  var t=e.target;if(!t.closest)return;
  var c=t.closest('[data-copy]');
  if(c){e.preventDefault();var k=c.getAttribute('data-copy');copy(k==='ref'?D.ref:D.sub,k==='ref'?'Реферальная ссылка скопирована':'Ссылка-подписка скопирована',c);return}
  var q=t.closest('[data-qr]');if(q){e.preventDefault();openQR();return}
  var x=t.closest('[data-close]');if(x){closeQR();return}
  var s=t.closest('[data-scroll]');if(s){var el=$(s.getAttribute('data-scroll'));if(el){e.preventDefault();el.scrollIntoView({behavior:reduce?'auto':'smooth',block:'start'})}return}
  var dl=t.closest('a[data-dl]');
  if(dl){var gone=false;var g=function(){gone=true};window.addEventListener('blur',g);doc.addEventListener('visibilitychange',g);
    setTimeout(function(){window.removeEventListener('blur',g);doc.removeEventListener('visibilitychange',g);if(!gone&&!doc.hidden)toast('Не открылось? Установите приложение — ссылки ниже','warn')},1900)}
});

/* ---------- рябь на кнопках ---------- */
doc.addEventListener('pointerdown',function(e){
  var b=e.target.closest&&e.target.closest('.btn,.rp');if(!b||reduce)return;
  var r=b.getBoundingClientRect(),d=Math.max(r.width,r.height)*2.2,s=doc.createElement('span');
  s.className='rpl';s.style.width=s.style.height=d+'px';s.style.left=(e.clientX-r.left-d/2)+'px';s.style.top=(e.clientY-r.top-d/2)+'px';
  b.appendChild(s);setTimeout(function(){s.parentNode&&s.parentNode.removeChild(s)},700);
});

/* ---------- QR-шторка ---------- */
var qs=$('qrs');
function openQR(){if(qs){qs.classList.add('on');doc.body.style.overflow='hidden'}}
function closeQR(){if(qs){qs.classList.remove('on');doc.body.style.overflow=''}}
doc.addEventListener('keydown',function(e){if(e.key==='Escape')closeQR()});

/* ---------- платформы ---------- */
var tabs=all('.tabs button'),ind=$('ind');
function setTab(p){tabs.forEach(function(b,i){var on=b.getAttribute('data-p')===p;b.classList.toggle('on',on);b.setAttribute('aria-selected',on?'true':'false');if(on&&ind)ind.style.transform='translateX('+(i*100)+'%)'});
  all('.pane').forEach(function(x){x.classList.toggle('on',x.getAttribute('data-p')===p)})}
tabs.forEach(function(b){b.addEventListener('click',function(){setTab(b.getAttribute('data-p'))})});
var ua=navigator.userAgent||'',plat='android';
if(/iPhone|iPad|iPod/i.test(ua)||(/Macintosh/i.test(ua)&&navigator.maxTouchPoints>1))plat='ios';
else if(/Android/i.test(ua))plat='android';else if(/Windows/i.test(ua))plat='win';else if(/Mac OS X|Macintosh/i.test(ua))plat='mac';else if(/Linux|CrOS/i.test(ua))plat='win';
if(ind){ind.style.transition='none';setTab(plat);void ind.offsetWidth;ind.style.transition=''}else setTab(plat);

/* ---------- кольцо, счётчик, обратный отсчёт ---------- */
function plural(n,f){n=Math.abs(n)%100;var m=n%10;if(n>10&&n<20)return f[2];if(m>1&&m<5)return f[1];if(m===1)return f[0];return f[2]}
function countUp(el,to,dur){if(!el)return;if(reduce||to<=1){el.textContent=to;return}var st=null;el.textContent='0';
  function f(ts){if(!st)st=ts;var p=Math.min(1,(ts-st)/dur),v=1-Math.pow(1-p,3);el.textContent=Math.round(to*v);if(p<1)requestAnimationFrame(f)}requestAnimationFrame(f)}
function leftText(sec){if(sec<=0)return '';var d=Math.floor(sec/86400),h=Math.floor(sec%86400/3600),m=Math.floor(sec%3600/60);
  if(d>=3)return d+' '+plural(d,['день','дня','дней']);if(d>0)return d+' '+plural(d,['день','дня','дней'])+' '+h+' ч';if(h>0)return h+' ч '+m+' мин';return Math.max(1,m)+' мин'}
function tick(){var el=$('leftT');if(!el||!D.exp)return;var s=Math.floor(D.exp-now()/1000);if(s<=0){if(D.active){D.active=false;setTimeout(function(){location.reload()},1500)}return}el.textContent=leftText(s)}

/* ---------- живой статус ---------- */
var busy=false,last=Date.now();
function hhmm(){var d=new Date();return ('0'+d.getHours()).slice(-2)+':'+('0'+d.getMinutes()).slice(-2)}
function apply(j){
  if(!j||!j.locs)return;var on=0,tot=0;
  for(var k in j.locs){if(!j.locs.hasOwnProperty(k))continue;tot++;var up=!!j.locs[k];if(up)on++;
    var el=doc.querySelector('[data-loc="'+k+'"] .st');if(!el)continue;var cls='st '+(up?'on':'off');
    if(el.className.replace(' flash','')!==cls){el.className=cls+' flash'}else el.className=cls;
    el.lastChild.textContent=up?'онлайн':'недоступна'}
  var c=$('locCnt');if(c){c.textContent=on+' из '+tot;c.className='cnt'+(on<tot?' bad':'')}
  var n=$('locN');if(n)n.textContent=on;
  if(j.onl){var o=$('onl');if(o)o.className='onl '+(j.onl.cls||'');var ot=$('onlT');if(ot)ot.textContent=j.onl.txt}
  if(j.traffic){var tr=$('trf');if(tr)tr.textContent=j.traffic}
  if(j.traf_v){var tv=$('trv');if(tv)tv.textContent=j.traf_v}
  if(j.traf_pct!=null){var tb=$('trb');if(tb)tb.style.width=j.traf_pct+'%'}
  var u=$('upd');if(u)u.textContent='Обновлено в '+hhmm();
}
function refresh(manual){
  if(busy)return;busy=true;var b=$('rf');if(b)b.classList.add('spin');var t1=Date.now();
  var x=new XMLHttpRequest();x.open('GET',location.pathname+'?fmt=json&_='+Date.now(),true);x.timeout=12000;
  function end(ok){setTimeout(function(){busy=false;if(b)b.classList.remove('spin')},Math.max(0,600-(Date.now()-t1)));last=Date.now();if(manual)toast(ok?'Статус обновлён':'Нет связи — попробуйте позже',ok?'':'warn')}
  x.onload=function(){var ok=false;if(x.status===200){try{apply(JSON.parse(x.responseText));ok=true}catch(e){}}end(ok)};
  x.onerror=x.ontimeout=function(){end(false)};x.send();
}

/* ---------- док снизу (моб.) ---------- */
function dock(){var d=$('dock'),cta=$('cta');if(!d||!cta||!('IntersectionObserver' in window))return;
  new IntersectionObserver(function(es){es.forEach(function(en){d.classList.toggle('show',!en.isIntersecting&&en.boundingClientRect.top<0)})},{threshold:0}).observe(cta)}

function startUI(){
  var bar=$('ringBar');if(bar){var off=parseFloat(bar.style.getPropertyValue('--off'))||0;requestAnimationFrame(function(){bar.style.strokeDashoffset=off})}
  var n=$('ringN');if(n)countUp(n,parseInt(n.getAttribute('data-to'),10)||0,1300);
  tick();setInterval(tick,30000);dock();
  var rf=$('rf');if(rf)rf.addEventListener('click',function(){refresh(true)});
  setInterval(function(){if(!doc.hidden)refresh(false)},60000);
  doc.addEventListener('visibilitychange',function(){if(!doc.hidden&&Date.now()-last>30000)refresh(false)});
  var rs=$('refShare');if(rs&&navigator.share)rs.addEventListener('click',function(e){e.preventDefault();navigator.share({title:'VAYNAH VPN',text:D.refText,url:D.ref}).catch(function(){})});
}
})();
</script>
</body>
</html>
'''

TPL_NF = r'''<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#020a06">
<meta name="color-scheme" content="dark">
<meta name="referrer" content="no-referrer">
<meta name="robots" content="noindex,nofollow">
<title>VAYNAH VPN — кабинет не найден</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;background:#05080f;color:#eef2ff;font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Noto Sans",Arial,sans-serif;-webkit-font-smoothing:antialiased}
body{display:grid;place-items:center;padding:24px;overflow:hidden;background:radial-gradient(800px 600px at 50% 30%,#0e1a3a,#05080f 70%)}
.c{position:relative;width:100%;max-width:400px;text-align:center;padding:34px 24px 26px;border-radius:28px;background:linear-gradient(180deg,rgba(19,28,54,.9),rgba(10,16,33,.92)) padding-box,linear-gradient(150deg,rgba(57,255,131,.36),rgba(57,255,131,.06) 40%,rgba(15,174,85,.26)) border-box;border:1px solid transparent;box-shadow:0 30px 80px -30px #000;animation:in .9s cubic-bezier(.16,1,.3,1) both}
@keyframes in{from{opacity:0;transform:translateY(24px) scale(.97)}}
.o{position:relative;width:104px;height:104px;margin:0 auto 20px}
.o i{position:absolute;inset:0;border-radius:50%;border:2px solid transparent;border-top-color:#39ff83;border-right-color:rgba(57,255,131,.3);animation:s 2.4s linear infinite}
.o i+i{inset:12px;border-top-color:transparent;border-bottom-color:#b6ffd3;border-left-color:rgba(182,255,211,.3);animation-duration:1.7s;animation-direction:reverse}
.o b{position:absolute;inset:26px;border-radius:50%;display:grid;place-items:center;background:radial-gradient(circle at 34% 28%,#0d4a2c,#04160c 72%);box-shadow:0 0 0 1px rgba(57,255,131,.35),0 0 40px rgba(57,255,131,.5);font-size:24px}
@keyframes s{to{transform:rotate(360deg)}}
h1{font-size:22px;font-weight:850;letter-spacing:-.3px}
p{color:#8b99c2;font-size:14px;margin:10px 0 22px}
p b{color:#c9d3f2}
a{display:flex;align-items:center;justify-content:center;min-height:54px;border-radius:17px;color:#fff;text-decoration:none;font-weight:780;font-size:16px;background:linear-gradient(135deg,#39ff83,#13d36a 45%,#0fae55);box-shadow:0 16px 36px -14px rgba(19,211,106,.85)}
small{display:block;margin-top:16px;color:#5f6d96;font-size:12px}
@media(prefers-reduced-motion:reduce){*{animation:none!important}}
</style>
</head>
<body>
<div class="c">
  <div class="o"><i></i><i></i><b>⚡</b></div>
  <h1>Кабинет не найден</h1>
  <p>Ссылка устарела или скопирована не полностью. Откройте кабинет заново в боте: <b>«🔑 Моя подписка» → «🖥 Личный кабинет»</b>.</p>
  <a href="https://t.me/{%bot%}">Открыть @{%bot%}</a>
  <small>VAYNAH VPN — быстрый VPN без границ</small>
</div>
</body>
</html>
'''
