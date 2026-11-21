from __future__ import annotations

import csv
import io

import streamlit as st

from core import build_export, import_csv_text
from store import import_records, list_contacts, metrics, upsert

st.set_page_config(page_title="REDIAL Intelligence v2.0", page_icon="📡", layout="wide",initial_sidebar_state="auto")
import hmac
import hashlib

def require_access():
    try:
        password = st.secrets.get("REDIAL_PANEL_PASSWORD", "")
    except Exception:
        password = ""
    if not password:
        st.info("Configura REDIAL_PANEL_PASSWORD en los secretos de Streamlit para habilitar el panel.")
        st.stop()
    digest = hashlib.sha256(password.encode()).hexdigest()
    if st.session_state.get("session_key") != digest:
        with st.form("access"):
            entered = st.text_input("Contraseña del panel REDIAL", type="password")
            submit = st.form_submit_button("Entrar")
        if submit and hmac.compare_digest(entered.encode(), password.encode()):
            st.session_state.session_key = digest
            st.rerun()
        if submit:
            st.error("Contraseña incorrecta")
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
</style>""",unsafe_allow_html=True)
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
st.markdown(f'<div class="cover" role="img" aria-label="Seda negra y fragmentos de plata" style="background-image:url(data:image/jpeg;base64,{cover()})"></div>',unsafe_allow_html=True)
require_access()
if menu == "Web Pad":
    import secrets, sqlite3, time, re, hashlib, json
    from store import DB_PATH, connect
    st.subheader("Web Pad")
    if pairing:
        mode = "Teléfono"
    else:
        mode=st.radio("Usar este dispositivo como",["PC · dirigir campaña","Teléfono · recibir campaña"],horizontal=True)
    with connect() as db:
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
        if "pad_code" not in st.session_state or st.button("Renovar código"):
            old=st.session_state.get("pad_code")
            code=secrets.token_hex(4).upper()
            with connect() as db:
                if old: db.execute("DELETE FROM pad WHERE key=?",(padkey(old),))
                db.execute("INSERT INTO pad VALUES (?,?,?)",(padkey(code),"",int(time.time())+1800))
            st.session_state.pad_code=code
        if "pad_code" in st.session_state:
            st.code(st.session_state.pad_code)
            st.caption("Escribe este código en el Web Pad de la PC. Válido durante 30 minutos. Mantén esta vista abierta.")
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
                        db.execute("INSERT OR REPLACE INTO dial_status VALUES(?,?,?,?,?,?)",(padkey(st.session_state.pad_code),report["phase"],pos,total,str(report.get("id",""))[:32],int(time.time())))
                    st.session_state.dial_tick=report.get("tick")
            @st.fragment(run_every="3s")
            def receive():
                with connect() as db:
                    r=db.execute("SELECT number FROM pad WHERE key=? AND expires>?",(padkey(st.session_state.pad_code),int(time.time()))).fetchone()
                    if r:
                        db.execute("INSERT OR REPLACE INTO pad_presence VALUES (?,?)",(padkey(st.session_state.pad_code),int(time.time())))
                    batch=db.execute("SELECT batch_id,payload FROM dial_batch WHERE device=?",(padkey(st.session_state.pad_code),)).fetchone()
                if r:
                    st.markdown(f'<span id="redial-pulse" data-pulse="{time.time_ns()}"></span>',unsafe_allow_html=True)
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
        with st.expander("Campaña de marcación", expanded=True):
            device_col, base_col = st.columns([1,1.4])
            device_code=device_col.text_input("Código del APK",key="batch_device",placeholder="Código del teléfono")
            upload = base_col.file_uploader("Base que se va a marcar (CSV)",type=["csv"],key="campaign_csv")
            numbers=[]
            if upload:
                try:
                    rows=import_csv_text(upload.getvalue().decode("utf-8-sig"))
                    numbers=list(dict.fromkeys("+"+r["phone"] for r in rows if r["format_valid"]))
                    st.caption(f"{len(numbers)} números válidos y únicos para esta campaña.")
                except (UnicodeError,ValueError) as exc:
                    st.error(str(exc))
            if device_code:
                @st.fragment(run_every="5s")
                def connection_status():
                    with connect() as db:
                        row=db.execute("SELECT p.expires,h.seen AS web_seen,s.phase,s.position,s.total,s.seen FROM pad p LEFT JOIN pad_presence h ON h.device=p.key LEFT JOIN dial_status s ON s.device=p.key WHERE p.key=?",(padkey(device_code),)).fetchone()
                    now=int(time.time())
                    if not row or row["expires"]<=now:
                        st.caption("Código incorrecto o caducado")
                    elif row["seen"] and now-row["seen"]<20:
                        st.success("APK vinculado · "+row["phase"])
                        if row["total"]:
                            st.progress(row["position"]/row["total"],text=f'Posición de campaña · {row["position"]} de {row["total"]}')
                    elif row["seen"]:
                        st.warning(f'Sin señal del APK · última señal hace {now-row["seen"]} segundos')
                    elif row["web_seen"] and now-row["web_seen"]<20:
                        st.caption("Receptor web en línea · esperando estado del APK")
                    else:
                        st.caption("Esperando conexión")
                connection_status()
            private=st.toggle("Solicitar número oculto",help="La disponibilidad depende de la SIM y del operador.")
            if st.button("Iniciar campaña en el teléfono",disabled=not numbers or not device_code):
                device_id=padkey(device_code)
                batch_id=secrets.token_hex(16)
                payload=json.dumps(dict(id=batch_id,private=private,numbers=numbers),separators=(",",":"))
                with connect() as db:
                    active=db.execute("SELECT 1 FROM pad WHERE key=? AND expires>?",(device_id,int(time.time()))).fetchone()
                    if active:
                        db.execute("INSERT OR REPLACE INTO dial_batch VALUES(?,?,?)",(device_id,batch_id,payload))
                if active: st.success("Campaña preparada para el APK. El progreso aparece en el teléfono.")
                else: st.error("Código incorrecto o caducado.")
        st.divider()
        st.markdown("**Marcación individual**")
        with st.form("pad_send"):
            code=st.text_input("Código del teléfono")
            number=st.text_input("Número para el marcador")
            send=st.form_submit_button("Pasar al teléfono")
        if send:
            number=re.sub(r"[ ()-]","",number)
            if not re.fullmatch(r"[+]?[0-9]{2,20}",number): st.error("Revisa el número.")
            else:
                with connect() as db:
                    changed=db.execute("UPDATE pad SET number=? WHERE key=? AND expires>?",(number,padkey(code),int(time.time()))).rowcount
                if changed: st.success("Número disponible en el teléfono. Confirma la llamada desde REDIAL.")
                else: st.error("Código incorrecto o caducado.")
if menu == "Resumen":
    st.info("La validación es gratuita y local. No comprueba si la línea está activa ni consulta operador actual de terceros. Fijo/móvil y operador quedan desconocidos salvo que se importen con procedencia documentada.")
    m = metrics()
    cols = st.columns(6)
    for col, label, key in zip(cols, ["Contactos", "Formato válido", "Móviles confirmados", "Fijos confirmados", "Tipo desconocido", "Opt-in SMS"], ["total", "valid", "mobile", "fixed", "unknown", "sms_optin"]):
        col.metric(label, m.get(key, 0))
    st.metric("Opt-in WhatsApp", m.get("whatsapp_optin", 0))
    st.caption("Los contadores de consentimiento son informativos. La exportación aplica filtros estrictos, incluyendo evidencia y fecha de consentimiento.")

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
    export = build_export(list_contacts(100000), key)
    count = max(0, sum(1 for _ in csv.DictReader(io.StringIO(export))))
    st.write(f"Contactos elegibles: **{count}**")
    st.caption("Solo incluye formato telefónico México válido, móvil confirmado, consentimiento del canal, fecha y fuente. No se envía ningún mensaje.")
    st.download_button(f"Descargar CSV autorizado para {channel}", export, file_name=f"redial_{key}_autorizados.csv", mime="text/csv", disabled=count == 0, type="primary")

if menu == "Android y actualizaciones":
    st.subheader("Cliente Android y actualizaciones")
    st.link_button("Descargar REDIAL 2.0.8", "https://github.com/julmrqzscl-star/REDIAL-Panel/raw/refs/heads/main/REDIAL-2.0.8.apk")
    st.write("La app Kotlin se conecta a la API del PC para ver métricas, ejecutar validaciones de formato y solicitar una exportación autorizada.")
    st.write("El endpoint `/api/v1/mobile/release` sirve `release.json`. Publicar una versión nueva en el servidor actualiza el panel web; Android avisa y abre la descarga del APK con confirmación del usuario.")
    st.code("python -m uvicorn api:app --host 127.0.0.1 --port 8765", language="powershell")
    st.warning("Para Android, la API necesita ser accesible desde la misma red local. El prototipo no cifra tráfico HTTP; usa solo una red de confianza y no publiques puertos en Internet.")

st.divider()
st.caption("REDIAL Intelligence v2.0 · Prototipo local · No envía SMS/WhatsApp · Validación de actividad y operador actual no disponible sin fuente autorizada.")



