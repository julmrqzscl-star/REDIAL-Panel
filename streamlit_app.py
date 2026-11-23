from __future__ import annotations

import csv
import io

import streamlit as st

import campaign
import campaign_ui
from core import build_export, import_csv_text
from store import import_records, list_contacts, metrics, upsert

st.set_page_config(page_title="REDIAL · Gestión de cobranza", page_icon="📡", layout="wide",initial_sidebar_state="auto")
import hmac
import hashlib

import re
import secrets
import sqlite3
import time
from contextlib import closing
from store import DATA_DIR, select_account

def require_access():
    password = str(st.secrets.get("REDIAL_PANEL_PASSWORD", ""))
    master=str(st.secrets.get("REDIAL_MASTER_USER","")).strip().lower()
    verifier=str(st.secrets.get("REDIAL_MASTER_VERIFIER",""))
    stamp=hashlib.sha256(verifier.encode()).hexdigest()
    if master and verifier and hmac.compare_digest(st.session_state.get("master_stamp",""),stamp):
        select_account(None)
        return
    user = st.session_state.get("operator")
    if user:
        select_account(user)
        return
    digest = hashlib.sha256(password.encode()).hexdigest()
    if password and st.session_state.get("session_key") == digest:
        select_account(None)
        return
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(DATA_DIR/"accounts.sqlite3",timeout=10)) as auth:
        auth.execute("CREATE TABLE IF NOT EXISTS accounts(user TEXT PRIMARY KEY,salt BLOB NOT NULL,verifier BLOB NOT NULL, failures INTEGER DEFAULT 0, until INTEGER DEFAULT 0)")
        if master and re.fullmatch(r"[0-9a-f]{32}:[0-9a-f]{64}",verifier):
            salt_hex,hash_hex=verifier.split(":")
            auth.execute("INSERT INTO accounts(user,salt,verifier) VALUES(?,?,?) ON CONFLICT(user) DO UPDATE SET salt=excluded.salt,verifier=excluded.verifier WHERE accounts.verifier!=excluded.verifier",(master,bytes.fromhex(salt_hex),bytes.fromhex(hash_hex)))
            auth.commit()
        with st.form("account_login"):
            name = st.text_input("Usuario").strip().lower()
            pin = st.text_input("PIN",type="password",max_chars=12)
            login = st.form_submit_button("Conectar",type="primary")
        if login:
            auth.execute("BEGIN IMMEDIATE")
            row=auth.execute("SELECT salt,verifier,failures,until FROM accounts WHERE user=?",(name,)).fetchone()
            now=int(time.time())
            if row and row[3]<=now:
                check=hashlib.pbkdf2_hmac("sha256",pin.encode(),row[0],600000)
                if hmac.compare_digest(check,row[1]):
                    auth.execute("UPDATE accounts SET failures=0,until=0 WHERE user=?",(name,))
                    auth.commit()
                    if master and name==master:
                        st.session_state.master_stamp=stamp
                    else:
                        st.session_state.operator=name
                    st.rerun()
                attempts=(0 if row[3] else row[2])+1
                auth.execute("UPDATE accounts SET failures=?,until=? WHERE user=?",(attempts,now+900 if attempts>=5 else 0,name))
            auth.commit()
            st.error("Acceso no disponible. Revisa tus datos o vuelve a intentar más tarde.")
        if not pairing:
            with st.expander("Crear usuario"):
                with st.form("new_account",clear_on_submit=True):
                    new=st.text_input("Nuevo usuario").strip().lower()
                    secret=st.text_input("Nuevo PIN (6 a 12 dígitos)",type="password",max_chars=12)
                    admin=st.text_input("Contraseña actual del panel",type="password")
                    create=st.form_submit_button("Crear y conectar")
                if create:
                    if not password or not hmac.compare_digest(admin.encode(),password.encode()):
                        st.error("Comprueba la contraseña actual del panel.")
                    elif not re.fullmatch(r"[a-z0-9_.-]{3,40}",new) or not re.fullmatch(r"[0-9]{6,12}",secret):
                        st.error("Usa un usuario de 3 a 40 caracteres y un PIN de 6 a 12 dígitos.")
                    else:
                        salt=secrets.token_bytes(16)
                        verifier=hashlib.pbkdf2_hmac("sha256",secret.encode(),salt,600000)
                        try:
                            auth.execute("INSERT INTO accounts(user,salt,verifier) VALUES(?,?,?)",(new,salt,verifier))
                            auth.commit()
                        except sqlite3.IntegrityError:
                            st.error("Ese usuario ya existe.")
                        else:
                            st.session_state.operator=new
                            st.rerun()
        with st.expander("Acceso al espacio anterior"):
            with st.form("legacy"):
                entered=st.text_input("Contraseña del panel REDIAL",type="password")
                submit=st.form_submit_button("Entrar al espacio anterior")
            if submit and password and hmac.compare_digest(entered.encode(),password.encode()):
                st.session_state.session_key=digest
                st.rerun()
            if submit:
                st.error("Contraseña incorrecta.")
    st.stop()

import base64
from pathlib import Path

@st.cache_data
def cover():
    return base64.b64encode(Path(__file__).with_name("seda.jpg").read_bytes()).decode()

pairing = st.query_params.get("vista") == "vincular"
st.markdown("""
<style>
.stApp,[data-testid="stMain"],[data-testid="stSidebar"]{background:#090909;color:#f5f3ed}
[data-testid="stHeader"]{background:transparent}
[data-testid="stSidebar"]{border-right:1px solid #393939}
.brand{font:900 clamp(32px,3vw,52px)/1 Arial,sans-serif;letter-spacing:-.05em;color:#fff}
.brand span{display:block;font:600 10px/2 Arial,sans-serif;letter-spacing:.48em;padding-left:4px}
.cover{height:clamp(120px,22vh,240px);background-size:cover;background-position:50% 52%;border-radius:9px 9px 0 0}
.block-container{max-width:1380px;padding:3.7rem clamp(18px,3vw,48px) 2rem}
[data-testid="stMain"] h3{font:750 clamp(34px,5vw,66px)/1 Arial,sans-serif;letter-spacing:-.055em;color:#fff}
[data-testid="stMain"] :is([data-testid="stWidgetLabel"],[data-testid="stCaptionContainer"],[data-testid="stMetricValue"]),[data-testid="stSidebar"] label{color:#edeae2}
[data-testid="stSidebar"] button{justify-content:flex-start;border:0;background:transparent;color:#eceae6;padding:.7rem 1rem}
[data-testid="stSidebar"] button[kind="primary"],[data-testid="stSidebar"] button:hover{background:#262626;color:#fff}
[data-testid="stMain"] :is(.stButton,.stFormSubmitButton) button{background:#efeae0;color:#111;border:1px solid #d6d1c8;font-weight:650}
[data-testid="stMain"] :is(.stButton,.stFormSubmitButton) button p{color:#111}
@media(max-width:700px){.cover{height:100px}.block-container{padding-top:3.5rem}}
[data-testid="stMain"] [data-testid="stExpander"]{background:#151518;border:1px solid #444148;border-radius:14px} [data-testid="stRadio"] label p,[data-testid="stExpander"] summary p{color:#f7f3ec!important}
.cover{display:flex;flex-direction:column;justify-content:flex-end;padding:22px 30px;box-sizing:border-box;background-color:#111;background-blend-mode:lighten;border:1px solid #434345;border-radius:18px;color:#fff;text-shadow:0 2px 10px #000}
.cover strong{font:800 clamp(30px,5vw,64px)/1 Arial;letter-spacing:-.065em}.cover span{font:600 10px/2 sans-serif;letter-spacing:.42em}
[data-testid="stMetric"]{background:#202124;border-color:#47484c;border-radius:16px}
[data-testid="stMetricValue"]{font-variant-numeric:tabular-nums;font-weight:650}
[data-testid="stMain"] h3{font-size:clamp(27px,4vw,48px)}
</style>""",unsafe_allow_html=True)
@st.cache_data
def display_fonts():
    def encoded(name):
        return base64.b64encode(Path(__file__).with_name(name).read_bytes()).decode()
    return "".join("@font-face{font-family:"+family+";font-display:swap;src:url(data:font/otf;base64,"+encoded(file)+") format('opentype')}" for family,file in [("Creato","CreatoDisplay-Regular.otf"),("Stretch","StretchPro.otf")])
st.markdown("<style>"+display_fonts()+"""
.stApp, .stApp :is(p,label,input,textarea,button,h1,h2,h3),.brand span{font-family:Creato,sans-serif!important}
.cover strong,.brand{font-family:Stretch,sans-serif!important;font-weight:400;letter-spacing:.015em}
[data-testid="stMetric"]{background:linear-gradient(125deg,rgba(57,57,60,.90),rgba(21,21,23,.97)),url(data:image/jpeg;base64,ART);background-position:center;background-size:cover;padding:clamp(12px,2vw,24px);min-width:0}
[data-testid="stMetricValue"]{font-size:clamp(28px,3vw,36px)}
[data-testid="stMetricLabel"] p{font-size:clamp(14px,1.2vw,16px)}
[data-testid="stDataFrame"]{background:#161618}
.cover{overflow:hidden}.cover strong{font-size:clamp(26px,5vw,58px)}
</style>""".replace("ART",cover()),unsafe_allow_html=True)
brand = '<div class="brand">REDIAL<span>INTELLIGENCE</span></div>'
pages = ["Web Pad","Resumen","Importar","Contactos","Exportar","Android y actualizaciones"]
menu = st.session_state.get("section","Web Pad")
if not pairing:
    with st.sidebar:
        st.markdown(brand,unsafe_allow_html=True)
        st.divider()
        for page,icon in zip(pages,["desktop_windows","dashboard","upload_file","contacts","download","smartphone"]):
            if st.button(page,icon=f":material/{icon}:",use_container_width=True,type="primary" if page==menu else "secondary"):
                st.session_state.section = page
                st.rerun()
else:
    menu = "Web Pad"
st.markdown(f'<div class="cover" role="img" aria-label="Seda negra y fragmentos de plata" style="background-image:url(data:image/jpeg;base64,{cover()})"><strong>REDIAL</strong><span>INTELLIGENCE</span></div>',unsafe_allow_html=True)
require_access()
if st.session_state.get("operator") or st.session_state.get("master_stamp") or st.session_state.get("session_key"):
    with st.sidebar:
        st.caption(str(st.secrets.get("REDIAL_MASTER_USER",""))+" · Maestro" if st.session_state.get("master_stamp") else st.session_state.get("operator","Espacio anterior"))
        if st.button("Cerrar sesión"):
            st.session_state.clear()
            st.rerun()
if menu == "Web Pad":
    import secrets, sqlite3, time, re, hashlib, json
    from store import DB_PATH, connect
    st.subheader("Vincular teléfono" if pairing else "Mesa de cobranza")
    if pairing:
        mode = "Teléfono"
    else:
        mode="PC"
    with connect() as db:
        campaign.setup(db)
        db.execute("CREATE TABLE IF NOT EXISTS pad (key TEXT PRIMARY KEY, number TEXT, expires INTEGER)")
        db.execute("CREATE TABLE IF NOT EXISTS dial_batch (device TEXT PRIMARY KEY, batch_id TEXT NOT NULL, payload TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS pad_presence (device TEXT PRIMARY KEY, seen INTEGER NOT NULL)")
        db.execute("DELETE FROM pad_presence WHERE seen < ?",(int(time.time())-1800,))
        db.execute("DELETE FROM dial_batch WHERE device NOT IN (SELECT key FROM pad WHERE expires>?)",(int(time.time()),))
        db.execute("DELETE FROM pad WHERE expires < ?",(int(time.time()),))
    def padkey(value):
        return hashlib.sha256(value.strip().upper().encode()).hexdigest()
    states={"En pausa","En llamada","Revisar intento","Listo para marcar","Marcando campaña","Finalizada"}
    with connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS dial_status(device TEXT PRIMARY KEY, phase TEXT, position INTEGER, total INTEGER, batch TEXT, seen INTEGER)")
        db.execute("DELETE FROM dial_status WHERE seen<?",(int(time.time())-86400,))
    if mode.startswith("Teléfono"):
        if "pad_code" not in st.session_state:
            old=st.session_state.get("pad_code")
            code=secrets.token_hex(4).upper()
            with connect() as db:
                if old: db.execute("DELETE FROM pad WHERE key=?",(padkey(old),))
                db.execute("INSERT INTO pad VALUES (?,?,?)",(padkey(code),"",int(time.time())+1800))
            st.session_state.pad_code=code
        if "pad_code" in st.session_state:
            st.success("Teléfono conectado al Web Pad")
            st.caption("Este teléfono aparece en la PC como REDIAL "+padkey(st.session_state.pad_code)[:4].upper()+". Mantén abierta esta pantalla para recibir la campaña.")
            from streamlit.components.v2 import component
            reporter=component("redial_status", js="""
            export default function({setStateValue}) {
                let last="", sent=0;
                const receive=e=>{
                    const value=JSON.stringify(e.detail), now=Date.now();
                    if(value===last && now-sent<8000) return;
                    last=value; sent=now;
                    setStateValue("report",{...e.detail,tick:now});
                };
                window.addEventListener("redial-status",receive);
                return ()=>window.removeEventListener("redial-status",receive);
            }
            """)
            update=reporter(key="dialstatus",on_report_change=lambda:None)
            report=getattr(update,"report",None)
            if isinstance(report,dict) and report.get("phase") in states and report.get("tick")!=st.session_state.get("dial_tick"):
                pos,total=report.get("index"),report.get("total")
                if isinstance(pos,int) and isinstance(total,int) and 0<=pos<=total:
                    with connect() as db:
                        device=padkey(st.session_state.pad_code)
                        db.execute("INSERT OR REPLACE INTO receivers VALUES(?,?,?)",(device,int(report.get("protocol",0)),int(time.time())))
                        campaign.record_result(db,device,str(report.get("resultId","")),str(report.get("result","")),int(time.time()))
                        db.execute("INSERT OR REPLACE INTO dial_status VALUES(?,?,?,?,?,?)",(padkey(st.session_state.pad_code),report["phase"],pos,total,str(report.get("id",""))[:32],int(time.time())))
                    st.session_state.dial_tick=report.get("tick")
            @st.fragment(run_every="3s")
            def receive():
                select_account(st.session_state.get("operator"))
                with connect() as db:
                    db.execute("INSERT INTO pad(key,number,expires) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET expires=excluded.expires",(padkey(st.session_state.pad_code),"",int(time.time())+1800))
                    r=db.execute("SELECT number FROM pad WHERE key=? AND expires>?",(padkey(st.session_state.pad_code),int(time.time()))).fetchone()
                    if r:
                        db.execute("INSERT OR REPLACE INTO pad_presence VALUES (?,?)",(padkey(st.session_state.pad_code),int(time.time())))
                    batch=db.execute("SELECT batch_id,payload FROM dial_batch WHERE device=?",(padkey(st.session_state.pad_code),)).fetchone()
                    receiver=db.execute("SELECT version FROM receivers WHERE device=?",(padkey(st.session_state.pad_code),)).fetchone()
                    if receiver and receiver[0]>=210:
                        batch=campaign.dispatch(db,padkey(st.session_state.pad_code),int(time.time()))
                    allow=int(campaign.queue_running(db,padkey(st.session_state.pad_code)))
                if r:
                    st.markdown(f'<span id="redial-pulse" data-running="{allow}" data-pulse="{time.time_ns()}"></span>',unsafe_allow_html=True)
                if r and batch:
                    import base64
                    encoded=base64.urlsafe_b64encode(batch["payload"].encode()).decode()
                    st.markdown(f'<div id="redial-campaign" data-batch="{encoded}">Campaña disponible en el marcador Android.</div>',unsafe_allow_html=True)
                    st.caption("El marcador inicia las llamadas si la recepción automática está habilitada en este teléfono.")
                if not r: st.info("El vínculo caducó. Vuelve a vincular el teléfono.")
                elif not r[0] and not batch: st.caption("Esperando número de la PC…")
                elif r[0]:
                    st.write("Número recibido",r[0])
                    st.markdown(f'<a href="tel:{r[0]}" target="_self">Abrir en el marcador</a>',unsafe_allow_html=True)
            receive()
    else:
        def available_devices():
            with connect() as db:
                return [r[0] for r in db.execute("SELECT p.key FROM pad p JOIN pad_presence h ON h.device=p.key WHERE h.seen>=? AND p.expires>? ORDER BY p.key",(int(time.time())-90,int(time.time())))]
        devices=available_devices()
        previous=st.session_state.get("selected_pad")
        options=sorted(set(devices+([previous] if previous else [])))
        if len(options)==1 and previous is None:
            st.session_state.selected_pad=options[0]
        def device_label(key):
            return "REDIAL "+key[:4].upper()+(" · conectado" if key in devices else " · sin señal")
        @st.fragment(run_every="4s")
        def discover():
            select_account(st.session_state.get("operator"))
            if available_devices()!=devices:
                st.rerun()
        discover()
        @st.fragment(run_every="8s")
        def desk():
            select_account(st.session_state.get("operator"))
            campaign_ui.collections_desk()
        desk()

        with st.container(border=True):
            if len(options)>1:
                selected=st.selectbox("Teléfono para esta campaña",options,index=options.index(previous) if previous in options else None,key="pad_choice",on_change=lambda: st.session_state.update(selected_pad=st.session_state.pad_choice),format_func=device_label,placeholder="Selecciona un teléfono")
            else:
                selected=st.session_state.get("selected_pad")
                if selected and selected in devices: st.success(device_label(selected))
                elif selected: st.warning(device_label(selected))
                else: st.info("En REDIAL para Android, toca Vincular con Web Pad. Tu teléfono aparecerá aquí.")
            device_id=selected if selected in devices else None
            st.markdown("### Control de llamadas")
            @st.fragment(run_every="4s")
            def dial_controls():
                select_account(st.session_state.get("operator"))
                with connect() as db:
                    running=campaign.queue_running(db,selected)
                    count=db.execute("SELECT count(*) FROM jobs JOIN campaigns ON campaigns.id=jobs.campaign WHERE device=? AND state IN ('Pendiente','Programada','Entregada')",(selected,)).fetchone()[0]
                    online=selected in available_devices()
                    left,right=st.columns(2)
                    if left.button("Iniciar / reanudar llamadas",icon=":material/play_arrow:",type="primary",disabled=not online or not count or running,use_container_width=True):
                        campaign.set_running(db,selected,True)
                        running=True
                    if right.button("Pausar llamadas",icon=":material/pause:",disabled=not running,use_container_width=True):
                        campaign.set_running(db,selected,False)
                        running=False
                st.caption(("Cola habilitada" if running else "Cola en pausa")+" · "+str(count)+" registros pendientes")
                if not online: st.caption("Vincula el teléfono para iniciar.")
                elif not count: st.caption("Agrega una campaña abajo para habilitar el inicio.")
                else: st.caption("En el teléfono, activa las llamadas de campaña. La pausa detiene nuevas entregas y permite terminar el turno ya enviado.")
            dial_controls()
            st.markdown("### Preparar campaña")
            entries,campaign_name,settings=campaign_ui.settings_and_list()
            if selected:
                @st.fragment(run_every="5s")
                def connection_status():
                    select_account(st.session_state.get("operator"))
                    with connect() as db:
                        row=db.execute("SELECT p.expires,h.seen AS web_seen,s.phase,s.position,s.total,s.seen FROM pad p LEFT JOIN pad_presence h ON h.device=p.key LEFT JOIN dial_status s ON s.device=p.key WHERE p.key=?",(selected,)).fetchone()
                    now=int(time.time())
                    if not row or row["expires"]<=now:
                        st.caption("Teléfono desconectado")
                    elif row["seen"] and now-row["seen"]<20:
                        st.success("APK vinculado · "+row["phase"])
                        if row["total"]:
                            st.progress(row["position"]/row["total"],text=f'Posición de campaña · {row["position"]} de {row["total"]}')
                    elif row["seen"] and now-row["seen"]<90:
                        st.caption("Reconectando con el teléfono · se conserva la cola")
                    elif row["seen"]:
                        st.warning(f'Sin señal del APK · última señal hace {now-row["seen"]} segundos')
                    elif row["web_seen"] and now-row["web_seen"]<20:
                        st.caption("Receptor web en línea · esperando estado del APK")
                    else:
                        st.caption("Esperando conexión")
                connection_status()
            if st.button("Agregar campaña a la cola",disabled=not entries or not device_id or not campaign_name.strip()):
                with connect() as db:
                    db.execute("BEGIN IMMEDIATE")
                    receiver=db.execute("SELECT version,last_seen FROM receivers WHERE device=?",(device_id,)).fetchone()
                    if receiver and receiver["version"]>=210 and int(time.time())-receiver["last_seen"]<90:
                        campaign.enqueue(db,device_id,campaign_name,settings,entries,int(time.time()))
                        st.success("Campaña en cola. El APK respetará el horario y la SIM predeterminada.")
                    else: st.warning("Abre el receptor en REDIAL 2.1.0 y espera su señal.")
            with st.expander("Cola y resultados"):
                @st.fragment(run_every="5s")
                def show_results():
                    select_account(st.session_state.get("operator"))
                    campaign_ui.results()
                show_results()
        st.divider()
        st.markdown("**Marcación individual**")
        with st.form("pad_send"):
            number=st.text_input("Número para el marcador")
            send=st.form_submit_button("Pasar al teléfono",disabled=not device_id)
        if send:
            number=re.sub(r"[ ()-]","",number)
            if not re.fullmatch(r"[+]?[0-9]{2,20}",number): st.error("Revisa el número.")
            else:
                with connect() as db:
                    changed=db.execute("UPDATE pad SET number=? WHERE key=? AND expires>?",(number,device_id,int(time.time()))).rowcount
                if changed: st.success("Número disponible en el teléfono. Confirma la llamada desde REDIAL.")
                else: st.error("Teléfono desconectado.")
if menu == "Resumen":
    m = metrics()
    cols = st.columns(6)
    for col, label, key in zip(cols, ["Contactos", "Formato válido", "Móviles confirmados", "Fijos confirmados", "Tipo desconocido", "Opt-in SMS"], ["total", "valid", "mobile", "fixed", "unknown", "sms_optin"]):
        col.metric(label, m.get(key, 0))
    st.metric("Opt-in WhatsApp", m.get("whatsapp_optin", 0))

if menu == "Importar":
    st.subheader("Importar una lista CSV")
    st.caption("Se conserva el mínimo necesario. Teléfonos duplicados se actualizan por número normalizado.")
    upload = st.file_uploader("Selecciona CSV", type=["csv"], key="csv")
    if upload:
        try:
            parsed = import_csv_text(upload.getvalue().decode("utf-8-sig"))
            st.write(f"Registros listos: **{len(parsed)}**")
            st.dataframe(parsed[:12], use_container_width=True, hide_index=True)
            if st.button("Importar registros", type="primary"):
                st.success(import_records(parsed))
        except Exception as exc:
            st.error(str(exc))
    st.download_button("Descargar plantilla CSV", data="phone,name,line_type,line_type_source,line_type_checked_at,sms_consent,sms_consent_at,sms_consent_source,whatsapp_consent,whatsapp_consent_at,whatsapp_consent_source,carrier,carrier_source,carrier_checked_at\n", file_name="redial_plantilla.csv", mime="text/csv")

if menu == "Contactos":
    st.subheader("Contactos")
    campaign_ui.rules_editor()
    data = list_contacts(5000)
    if data:
        search = st.text_input("Filtrar por nombre o número")
        channel = st.selectbox("Vista", ["Todos", "SMS con consentimiento", "WhatsApp con consentimiento", "Móvil", "Fijo", "Desconocido"])
        if search:
            data = [r for r in data if search.lower() in r["name"].lower() or search in r["phone"]]
        if channel == "SMS con consentimiento": data = [r for r in data if r["sms_consent"]]
        elif channel == "WhatsApp con consentimiento": data = [r for r in data if r["whatsapp_consent"]]
        elif channel == "Móvil": data = [r for r in data if r["line_type"] == "mobile"]
        elif channel == "Fijo": data = [r for r in data if r["line_type"] == "fixed"]
        elif channel == "Desconocido": data = [r for r in data if r["line_type"] == "unknown"]
        editable_fields = ["phone", "name", "line_type", "line_type_source", "line_type_checked_at", "sms_consent", "sms_consent_at", "sms_consent_source", "whatsapp_consent", "whatsapp_consent_at", "whatsapp_consent_source", "carrier", "carrier_source", "carrier_checked_at"]
        edited = st.data_editor(
            [{k: (bool(row.get(k)) if k.endswith("_consent") else row.get(k)) for k in editable_fields} for row in data],
            key="contact_editor", use_container_width=True, hide_index=True,
            disabled=["phone"],
            column_config={
                "line_type": st.column_config.SelectboxColumn("Tipo", options=["mobile", "fixed", "unknown"]),
                "sms_consent": st.column_config.CheckboxColumn("Consentimiento SMS"),
                "whatsapp_consent": st.column_config.CheckboxColumn("Consentimiento WhatsApp"),
            },
        )
        if st.button("Guardar cambios de consentimiento y clasificación"):
            original = {r["phone"]: r for r in data}
            for edit in edited:
                base = original.get(edit["phone"], {})
                merged = {**base, **edit}
                upsert(merged)
            st.success("Cambios guardados.")
    else:
        st.caption("Aún no hay contactos. Importa un CSV para comenzar.")

if menu == "Exportar":
    st.subheader("Preparar lista autorizada")
    channel = st.radio("Canal de destino", ["SMS", "WhatsApp"], horizontal=True)
    key = channel.lower()
    campaign_ui.export_panel(key)

if menu == "Android y actualizaciones":
    st.subheader("Cliente Android y actualizaciones")
    apk=Path(__file__).with_name("REDIAL-2.1.4.apk")
    if apk.is_file():
        st.download_button("Descargar REDIAL 2.1.4",apk.read_bytes(),file_name=apk.name,mime="application/vnd.android.package-archive")
    else:
        st.warning("El instalador 2.1.4 aún no está disponible en este servidor.")
    st.write("La app Kotlin se conecta a la API del PC para ver métricas, ejecutar validaciones de formato y solicitar una exportación autorizada.")
    st.write("El endpoint `/api/v1/mobile/release` sirve `release.json`. Publicar una versión nueva en el servidor actualiza el panel web; Android avisa y abre la descarga del APK con confirmación del usuario.")
    st.code("python -m uvicorn api:app --host 127.0.0.1 --port 8765", language="powershell")
    st.warning("Para Android, la API necesita ser accesible desde la misma red local. El prototipo no cifra tráfico HTTP; usa solo una red de confianza y no publiques puertos en Internet.")




