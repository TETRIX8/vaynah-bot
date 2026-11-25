#!/usr/bin/env python3
"""Sync IngVertuVpn bot users to Remnawave using a scoped API token."""
import sqlite3, json, time, datetime, sys, urllib.request, urllib.error, logging, os
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s"); log=logging.getLogger("ingvertu-rwsync")
DB = os.environ.get("INGVERTU_DB", "/opt/zpnbot/ingvertuvpn.sqlite3")
API = os.environ.get("INGVERTU_RW_API", "").rstrip("/")
TOK = os.environ.get("INGVERTU_RW_TOKEN", "")
SQUAD = os.environ.get("INGVERTU_RW_SQUAD", "")
SQUAD_PAID = os.environ.get("INGVERTU_RW_SQUAD_PAID", "")
def dev_limit(plan, admin):
    """04.11.2026: лимит устройств (HWID) по тарифу: Семейный 5, остальные 3; админам 0 = без лимита."""
    if admin: return 0
    return 5 if str(plan or "").startswith("fam") else 3
GB=1024**3
def traffic_limit(plan, admin):
    """05.11.2026: лимит трафика. Пробный — 5 ГБ на весь период; остальные тарифы — 50 ГБ, сброс каждые 30 дней; админам без лимита."""
    if admin: return 0, "NO_RESET"
    if str(plan or "") == "trial": return 5*GB, "NO_RESET"
    return 50*GB, "NO_RESET"   # 05.11.2026: жёстко 50 ГБ на оплаченный период; обнуление — только при новой оплате (tr_reset)
def short_of(u): return u.replace("-","")[:16]
def api(m,p,b=None):
    if not API or not TOK: raise RuntimeError("Remnawave API integration is not configured")
    r=urllib.request.Request(API+p,method=m,data=json.dumps(b).encode() if b is not None else None,
        headers={"Authorization":"Bearer "+TOK,"Content-Type":"application/json","Accept":"application/json","User-Agent":"IngVertuVpn-sync"})
    try:
        with urllib.request.urlopen(r,timeout=30) as f: return f.status, json.loads(f.read() or b"{}")
    except urllib.error.HTTPError as e: return e.code, e.read().decode()[:300]
def ts(v):
    try: return float(v)
    except Exception:
        try: return datetime.datetime.fromisoformat(str(v)).timestamp()
        except Exception: return 0
def iso(t): return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
def panel_users():
    out={}; start=0
    while True:
        s,r=api("GET",f"/users?size=500&start={start}")
        if s!=200: raise RuntimeError(f"list users {s} {r}")
        us=r["response"]["users"]
        for u in us: out[u["vlessUuid"]]=u
        start+=len(us)
        if not us or start>=r["response"]["total"]: return out
def sync(only=None):
    c=sqlite3.connect(DB); now=time.time()
    try: rows=c.execute("select tg_id,uuid,plan,expires_at,revoked,coalesce(pay_count,0),dev_limit,coalesce(tr_reset,0),coalesce(lim_notified,0) from users where uuid is not null and uuid!=''").fetchall()
    except sqlite3.OperationalError:
        rows=[r+(None,0,0) for r in c.execute("select tg_id,uuid,plan,expires_at,revoked,coalesce(pay_count,0) from users where uuid is not null and uuid!=''").fetchall()]
    try: admins={r[0] for r in c.execute("select tg_id from admins")}
    except Exception: admins=set()
    # Seed administrators from environment are admins too; they may not be in the extra-admin table.
    for raw in os.environ.get("INGVERTU_ADMIN_ID", "").replace(";", ",").split(","):
        if raw.strip().isdigit(): admins.add(int(raw.strip()))
    c.close()
    pu=panel_users(); made=upd=0
    flags=[]   # (sql, args) — пишем в БД бота после цикла
    for tg,u,plan,exp,rev,paycnt,dlo,trr,limn in rows:
        if only and tg!=only: continue
        try:   # 03.11.2026: ошибка одного юзера больше не останавливает синк всех остальных
            e=ts(exp); active = e>now and not rev
            p=pu.get(u)
            if p is None:
                if not active: continue
                s,r=api("POST","/users",{"username":f"tg{tg}","vlessUuid":u,"shortUuid":short_of(u),"expireAt":iso(e),
                    "trafficLimitBytes":traffic_limit(plan, tg in admins)[0],"trafficLimitStrategy":traffic_limit(plan, tg in admins)[1],"status":"ACTIVE","telegramId":int(tg),
                    "activeInternalSquads":list(dict.fromkeys(x for x in (SQUAD,SQUAD_PAID) if x)),"description":f"IngVertuVpn plan={plan}",
                    "hwidDeviceLimit":(0 if tg in admins else (int(dlo) if dlo is not None else dev_limit(plan, False)))})
                if s in (200,201):
                    made+=1; log.info(f"created tg{tg} plan={plan} until {iso(e)}")
                    if trr: flags.append(("update users set tr_reset=0 where tg_id=?",(tg,)))
                else: log.error(f"create tg{tg}: {s} {r}")
                continue
            patch={}
            pe=datetime.datetime.fromisoformat(str(p["expireAt"]).replace("Z","+00:00")).timestamp() if p.get("expireAt") else 0
            if e>0 and abs(pe-e)>60: patch["expireAt"]=iso(e)
            if rev and p["status"] not in ("DISABLED","EXPIRED"): patch["status"]="DISABLED"
            tl,tst=traffic_limit(plan, tg in admins)
            used=float(((p.get("userTraffic") or {}).get("usedTrafficBytes")) or 0)
            reset=bool(trr)   # оплата -> обнулить трафик
            if trr and p["status"]=="LIMITED" and not rev and e>now: patch["status"]="ACTIVE"
            if p["status"]=="LIMITED" and not trr and limn==0 and tg not in admins: flags.append(("update users set lim_notified=1 where tg_id=? and coalesce(lim_notified,0)=0",(tg,)))
            if p.get("trafficLimitBytes")!=tl or p.get("trafficLimitStrategy")!=tst:
                patch["trafficLimitBytes"]=tl; patch["trafficLimitStrategy"]=tst
                # пробный -> платный: трафик пробного не засчитываем в платный лимит
                if p.get("trafficLimitBytes")==5*GB and tl!=5*GB: reset=True
            if not rev and e>now and p["status"] in ("DISABLED","EXPIRED"): patch["status"]="ACTIVE"
            # LIMITED (исчерпан трафик) снимаем, только если лимит теперь позволяет
            if not rev and e>now and p["status"]=="LIMITED" and (tl==0 or reset or used<tl): patch["status"]="ACTIVE"
            cur={(q.get("uuid") if isinstance(q,dict) else q) for q in (p.get("activeInternalSquads") or [])}
            want=set(cur)
            if SQUAD_PAID: want.add(SQUAD_PAID)
            elif SQUAD: want.add(SQUAD)
            if want!=cur: patch["activeInternalSquads"]=sorted(want)
            dl=0 if tg in admins else (int(dlo) if dlo is not None else dev_limit(plan, False))   # админы всегда без лимита; ручной override — только для обычных пользователей
            if p.get("hwidDeviceLimit")!=dl: patch["hwidDeviceLimit"]=dl
            if p.get("description")!=f"IngVertuVpn plan={plan}": patch["description"]=f"IngVertuVpn plan={plan}"   # 25.11.2026: метка плана после оплаты
            if patch:
                # Remnawave v3: юзер обновляется по числовому id (или username); поля uuid больше нет
                ident={"id":p["id"]} if p.get("id") is not None else {"uuid":p["uuid"]}
                s,r=api("PATCH","/users",dict(ident,**patch))
                if s==200: upd+=1; log.info(f"updated tg{tg} {patch}")
                if s==200 and reset:
                    s2,r2=api("POST",f"/users/{p.get('id')}/actions/reset-traffic")
                    log.info(f"reset-traffic tg{tg}: {s2}")
                    if s2 in (200,201) and trr: flags.append(("update users set tr_reset=0, lim_notified=0 where tg_id=?",(tg,)))
                elif s!=200: log.error(f"update tg{tg}: {s} {r}")
            elif trr:
                s2,r2=api("POST",f"/users/{p.get('id')}/actions/reset-traffic")
                log.info(f"reset-traffic (paid) tg{tg}: {s2}")
                if s2 in (200,201): flags.append(("update users set tr_reset=0, lim_notified=0 where tg_id=?",(tg,)))
        except Exception as ex:
            log.error(f"sync tg{tg}: {ex!r}")
    if flags:
        c=sqlite3.connect(DB, timeout=20)
        for q,a in flags:
            try: c.execute(q,a)
            except Exception as ex: log.error(f"flag {q}: {ex}")
        c.commit(); c.close()
    return made,upd
if __name__=="__main__":
    only=int(sys.argv[sys.argv.index("--only")+1]) if "--only" in sys.argv else None
    if "--once" in sys.argv or only: print(sync(only)); sys.exit(0)
    while True:
        try: sync()
        except Exception as ex: log.error(f"sync error: {ex}")
        time.sleep(20)
