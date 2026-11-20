from __future__ import annotations

import csv
import io

import streamlit as st

from core import build_export, import_csv_text
from store import import_records, list_contacts, metrics, upsert

st.set_page_config(page_title="REDIAL Intelligence v2.0", page_icon="📡", layout="wide")
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

require_access()
st.markdown("""<style>
html,body,[class*="css"]{font-family:Arial,sans-serif} h1,h2,h3{font-family:Arial,sans-serif}
.hero{padding:24px 28px;border-radius:18px;background:linear-gradient(120deg,#0b1e31,#123b53 65%,#0d766e);color:white;margin-bottom:20px}
.muted{color:#64748b;font-size:14px}
</style>""", unsafe_allow_html=True)

st.markdown('<div class="hero"><h1>REDIAL Intelligence <span style="color:#55ddd0">v2.0</span></h1><div>Validación local, consentimiento por canal y listas autorizadas.</div></div>', unsafe_allow_html=True)
st.info("La validación es gratuita y local. No comprueba si la línea está activa ni consulta operador actual de terceros. Fijo/móvil y operador quedan desconocidos salvo que se importen con procedencia documentada.")

tab_overview, tab_import, tab_contacts, tab_export, tab_mobile = st.tabs(["Resumen", "Importar", "Contactos", "Exportar", "Android y actualizaciones"])

with tab_overview:
    m = metrics()
    cols = st.columns(6)
    for col, label, key in zip(cols, ["Contactos", "Formato válido", "Móviles confirmados", "Fijos confirmados", "Tipo desconocido", "Opt-in SMS"], ["total", "valid", "mobile", "fixed", "unknown", "sms_optin"]):
        col.metric(label, m.get(key, 0))
    st.metric("Opt-in WhatsApp", m.get("whatsapp_optin", 0))
    st.caption("Los contadores de consentimiento son informativos. La exportación aplica filtros estrictos, incluyendo evidencia y fecha de consentimiento.")

with tab_import:
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

with tab_contacts:
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

with tab_export:
    st.subheader("Preparar lista autorizada")
    channel = st.radio("Canal de destino", ["SMS", "WhatsApp"], horizontal=True)
    key = channel.lower()
    export = build_export(list_contacts(100000), key)
    count = max(0, sum(1 for _ in csv.DictReader(io.StringIO(export))))
    st.write(f"Contactos elegibles: **{count}**")
    st.caption("Solo incluye formato telefónico México válido, móvil confirmado, consentimiento del canal, fecha y fuente. No se envía ningún mensaje.")
    st.download_button(f"Descargar CSV autorizado para {channel}", export, file_name=f"redial_{key}_autorizados.csv", mime="text/csv", disabled=count == 0, type="primary")

with tab_mobile:
    st.subheader("Cliente Android y actualizaciones")
    st.write("La app Kotlin se conecta a la API del PC para ver métricas, ejecutar validaciones de formato y solicitar una exportación autorizada.")
    st.write("El endpoint `/api/v1/mobile/release` sirve `release.json`. Publicar una versión nueva en el servidor actualiza el panel web; Android avisa y abre la descarga del APK con confirmación del usuario.")
    st.code("python -m uvicorn api:app --host 127.0.0.1 --port 8765", language="powershell")
    st.warning("Para Android, la API necesita ser accesible desde la misma red local. El prototipo no cifra tráfico HTTP; usa solo una red de confianza y no publiques puertos en Internet.")

st.divider()
st.caption("REDIAL Intelligence v2.0 · Prototipo local · No envía SMS/WhatsApp · Validación de actividad y operador actual no disponible sin fuente autorizada.")



