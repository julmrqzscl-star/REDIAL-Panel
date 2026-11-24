"""Account-scoped campaign queue. Call dispatch and record_result inside a write transaction."""
import json
import re
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("America/Mexico_City")
COLLECTION_RESULTS = {"Contacto efectivo","Promesa de pago","Pago reportado","Aclaración solicitada","Número equivocado"}
OUTCOMES = COLLECTION_RESULTS | {"Conectada", "No contestó", "Ocupado", "Buzón", "Reintentar", "Omitida", "Sin confirmar"}
RETRYABLE = {"No contestó", "Ocupado", "Reintentar"}

def setup(db):
    for ddl in (
        "CREATE TABLE IF NOT EXISTS campaigns(id TEXT PRIMARY KEY, device TEXT,name TEXT,settings TEXT,created INTEGER)",
        "CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY,campaign TEXT,phone TEXT,meta TEXT,attempt INTEGER DEFAULT 0,due INTEGER,state TEXT DEFAULT 'Pendiente',token TEXT UNIQUE)",
        "CREATE INDEX IF NOT EXISTS jobs_ready ON jobs(campaign,state,due)",
        "CREATE TABLE IF NOT EXISTS attempts(token TEXT PRIMARY KEY,job INTEGER,result TEXT,finished INTEGER)",
        "CREATE TABLE IF NOT EXISTS line_rules(prefix TEXT PRIMARY KEY,kind TEXT,carrier TEXT,source TEXT,checked TEXT)",
        "CREATE TABLE IF NOT EXISTS dial_control(device TEXT PRIMARY KEY,running INTEGER NOT NULL)",
        "CREATE TABLE IF NOT EXISTS receivers(device TEXT PRIMARY KEY,version INTEGER,last_seen INTEGER)"
    ):
        db.execute(ddl)

def classify(record,rules):
    national=record["phone"][-10:]
    match=next((r for r in rules if national.startswith(r["prefix"])),None)
    kind={"fixed":"FIJO","mobile":"MÓVIL"}.get(record["line_type"])
    return dict(tipo=kind or (match["kind"] if match else "Desconocido"),
                compania=record["carrier"] or (match["carrier"] if match else "") or "Sin verificar",
                fuente_tipo=record["line_type_source"] if kind else (match["source"] if match else ""),
                fuente_compania=record["carrier_source"] if record["carrier"] else (match["source"] if match else ""))

def enqueue(db,device,name,settings,entries,now):
    campaign=secrets.token_hex(12)
    db.execute("INSERT INTO campaigns VALUES(?,?,?,?,?)",(campaign,device,name,json.dumps(settings),now))
    needs_name = "{nombre}" in settings.get("voice", {}).get("text", "")
    db.executemany("INSERT INTO jobs(campaign,phone,meta,due,state) VALUES(?,?,?,?,?)",
                   ((campaign,phone,json.dumps(meta,ensure_ascii=False),now,
                     "Revisar nombre" if needs_name and not str(meta.get("nombre") or "").strip() else "Pendiente")
                    for phone,meta in entries.items()))
    return campaign

def in_window(now,start,end):
    minute=datetime.fromtimestamp(now,ZONE).strftime("%H:%M")
    if start==end: return True
    if start<end: return start<=minute<end
    return minute>=start or minute<end

def queue_running(db,device):
    row=db.execute("SELECT running FROM dial_control WHERE device=?",(device,)).fetchone()
    return bool(row and row[0])

def set_running(db,device,running):
    db.execute("INSERT OR REPLACE INTO dial_control(device,running) VALUES(?,?)",(device,int(running)))

def dispatch(db,device,now):
    setup(db)
    if not queue_running(db,device): return None
    sql="""SELECT j.*,c.settings FROM jobs j JOIN campaigns c ON c.id=j.campaign
           WHERE c.device=? AND j.state IN ('Pendiente','Programada','Entregada')
           ORDER BY (j.state='Entregada') DESC,j.due,j.id"""
    for job in db.execute(sql,(device,)):
        settings=json.loads(job["settings"])
        if job["due"]>now or not in_window(now,settings["start"],settings["end"]):
            if job["state"]=="Entregada": return None
            continue
        meta=json.loads(job["meta"])
        voice=dict(settings.get("voice") or {})
        template=str(voice.get("text") or "")
        name=str(meta.get("nombre") or "").strip()
        if "{nombre}" in template and not name:
            if job["state"] == "Entregada":
                return None
            db.execute("UPDATE jobs SET state='Revisar nombre' WHERE id=?", (job["id"],))
            continue
        voice["text"]=template.replace("{nombre}", name)
        token=job["token"]
        if job["state"]!="Entregada":
            token=secrets.token_hex(16)
            db.execute("UPDATE jobs SET token=?,state='Entregada',attempt=attempt+1 WHERE id=?",(token,job["id"]))
        return dict(batch_id=token,payload=json.dumps(dict(id=token,managed=True,numbers=[job["phone"]],meta=meta,voice=voice,start=settings["start"],end=settings["end"])))
    return None

def record_result(db,device,token,outcome,now):
    if outcome not in OUTCOMES: return
    row=db.execute("""SELECT j.*,c.settings FROM jobs j JOIN campaigns c ON c.id=j.campaign
                      WHERE c.device=? AND j.token=? AND j.state='Entregada'""",(device,token)).fetchone()
    if not row: return
    settings=json.loads(row["settings"])
    retry=outcome in RETRYABLE and row["attempt"]<=settings["retries"]
    db.execute("INSERT INTO attempts VALUES(?,?,?,?)",(token,row["id"],outcome,now))
    db.execute("UPDATE jobs SET state=?,due=? WHERE id=?",("Programada" if retry else outcome,now+settings["interval"],row["id"]))
