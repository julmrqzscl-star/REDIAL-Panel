import json
import re
from datetime import date
import streamlit as st
import streamlit.components.v1 as components
from core import clean_record,import_csv_text,eligible
from store import connect,get,list_contacts
from campaign import setup,classify


PIPER_VOICES = {
    "es-MX": {"Ald": "es_MX-ald-medium", "Claude": "es_MX-claude-high"},
    "es-ES": {"Dave": "es_ES-davefx-medium", "Carl": "es_ES-carlfm-x_low", "Sharvard": "es_ES-sharvard-medium", "MLS 10246": "es_ES-mls_10246-low"},
    "en-US": {"Lessac": "en_US-lessac-medium", "Amy": "en_US-amy-medium"},
}

PIPER_STYLES = {
    "Natural": {"noise_scale": 0.667, "noise_w_scale": 0.8, "pace": 1.0},
    "Conversación": {"noise_scale": 0.75, "noise_w_scale": 0.9, "pace": 1.03},
    "Formal": {"noise_scale": 0.55, "noise_w_scale": 0.7, "pace": 0.96},
}

@st.cache_resource(show_spinner=False, max_entries=2)
def _piper_voice(lang, voice_name):
    import subprocess, sys, tempfile
    from pathlib import Path
    from piper import PiperVoice
    name = PIPER_VOICES[lang][voice_name]
    directory = Path(tempfile.gettempdir()) / "redial-piper-voices"
    directory.mkdir(parents=True, exist_ok=True)
    model = directory / (name + ".onnx")
    if not model.is_file() or not (directory / (name + ".onnx.json")).is_file():
        subprocess.run([sys.executable, "-m", "piper.download_voices", "--data-dir", str(directory), name],
                       check=True, capture_output=True, timeout=240)
    return PiperVoice.load(str(model))

def generate_piper_preview(text, lang, rate, voice_name=None, strength=4.5, style="Natural"):
    import io, wave
    from piper import SynthesisConfig
    output = io.BytesIO()
    preset = PIPER_STYLES[style]
    config = SynthesisConfig(length_scale=1.0 / (float(rate) * preset["pace"]), noise_scale=preset["noise_scale"], noise_w_scale=preset["noise_w_scale"])
    with wave.open(output, "wb") as wav:
        _piper_voice(lang, voice_name or next(iter(PIPER_VOICES[lang]))).synthesize_wav(text, wav, syn_config=config)
    import array, math, sys
    with wave.open(io.BytesIO(output.getvalue()), "rb") as wav:
        params = wav.getparams()
        if params.sampwidth != 2 or params.nframes < params.framerate // 10:
            raise ValueError("La voz generada está vacía o tiene un formato incompatible.")
        samples = array.array("h")
        samples.frombytes(wav.readframes(params.nframes))
    if sys.byteorder != "little":
        samples.byteswap()
    peak = max((abs(int(sample)) for sample in samples), default=0)
    if peak < 100:
        raise ValueError("El motor generó una señal demasiado baja.")
    # Boost quieter speech while limiting peaks to avoid hard digital clipping.
    strength = max(3.0, min(6.0, float(strength)))
    scale = strength / 32768.0
    normalizer = math.tanh(strength)
    for index, sample in enumerate(samples):
        samples[index] = round(30000 * math.tanh(sample * scale) / normalizer)
    if sys.byteorder != "little":
        samples.byteswap()
    result = io.BytesIO()
    with wave.open(result, "wb") as wav:
        wav.setparams(params)
        wav.writeframes(samples.tobytes())
    return result.getvalue()

def settings_and_list():
    with connect() as db:
        setup(db)
        rules=[dict(r) for r in db.execute("SELECT * FROM line_rules ORDER BY length(prefix) DESC")]
    source=st.radio("Base de campaña",["CSV","Pegar números","Contactos guardados"],horizontal=True)
    rows=[]
    try:
        if source=="CSV":
            file=st.file_uploader("Archivo de contactos",type=["csv"])
            if file: rows=import_csv_text(file.getvalue().decode("utf-8-sig"))
        elif source=="Pegar números":
            values=st.text_area("Números separados por salto de línea, coma o punto y coma")
            rows=[clean_record({"phone":v}) for v in re.split(r"[,;\n]+",values) if v.strip()]
        else: rows=list_contacts(100000)
    except (UnicodeError,ValueError) as exc: st.error(str(exc))
    entries={}
    stored={r["phone"]:r for r in list_contacts(100000)} if rows and source!="Contactos guardados" else {}
    for row in rows:
        if row["format_valid"]:
            phone="+"+row["phone"]
            if phone not in entries:
                saved=stored.get(row["phone"]) or {}
                combined=dict(saved if source=="Pegar números" and saved else row)
                for field, missing in (("line_type","unknown"),("carrier","")):
                    if combined[field]==missing and saved.get(field):
                        for suffix in ("","_source","_checked_at"):
                            combined[field+suffix]=saved[field+suffix]
                entries[phone]=classify(combined,rules)
                entries[phone]["nombre"] = str(combined.get("name") or saved.get("name") or "").strip()
                if entries[phone]["tipo"]=="MÓVIL":
                    combined["line_type"]="mobile"
                for channel in ("sms","whatsapp"):
                    entries[phone][channel]=eligible(combined,channel)
    if rows:
        st.caption(f"{len(entries)} números únicos · {sum(not r['format_valid'] for r in rows)} inválidos")
        counts=[sum(m["tipo"]==t for m in entries.values()) for t in ("MÓVIL","FIJO","Desconocido")]
        for col,title,count in zip(st.columns(3),("Móviles","Fijos","Sin verificar"),counts): col.metric(title,count)
        st.dataframe([{"Número":n,**m} for n,m in entries.items()],hide_index=True)
    name=st.text_input("Nombre de campaña",value="Campaña "+str(date.today()))
    with st.expander("Redial y horario · Ciudad de México"):
        retries=st.number_input("Reintentos por número",0,10,0)
        interval=st.number_input("Espera entre reintentos (minutos)",1,1440,10)
        st.caption("Horas iguales habilitan el día completo.")
        a,b=st.columns(2)
        start=a.time_input("Desde",value=__import__("datetime").time(0))
        end=b.time_input("Hasta",value=__import__("datetime").time(0))
    with st.expander("Mensaje de campaña"):
        body=st.text_area("Texto del mensaje",max_chars=2000,help="Usa {nombre} para insertar el nombre de cada contacto.")
        st.caption("Personaliza con {nombre}: por ejemplo, Hola {nombre}. Los contactos sin nombre quedarán para revisión.")
        sample_name=next((entry.get("nombre") for entry in entries.values() if entry.get("nombre")),"María")
        preview_body=body.replace("{nombre}",sample_name)
        if "{nombre}" in body:
            st.caption("Ejemplo de vista previa: " + preview_body)
        lang=st.selectbox("Idioma",["es-MX","es-ES","en-US"])
        engine=st.radio("Motor de vista previa",["Piper","Narración","Speechify"],horizontal=True,help="Speechify genera audio en línea; Piper y Narración se ejecutan en el servidor.")
        if engine=="Narración" and not lang.startswith("es"):
            st.info("Las voces de narración están disponibles para español.")
        speechify_key = str(st.secrets.get("SPEECHIFY_API_KEY", "")).strip() if engine=="Speechify" else ""
        speechify_voices = []
        if engine=="Speechify":
            st.caption("Al generar la vista previa se envía el texto, incluido el nombre personalizado, a Speechify. Usa una cuenta API del plan Free y comprueba sus límites en Speechify.")
            if not speechify_key:
                st.info("Falta configurar SPEECHIFY_API_KEY en los secretos de Streamlit. No escribas la clave en el chat.")
            if st.button("Cargar voces de Speechify", disabled=not speechify_key):
                try:
                    import speechify_client
                    st.session_state["speechify_voices"] = speechify_client.list_voices(speechify_key)
                except Exception as exc:
                    st.session_state.pop("speechify_voices", None)
                    st.error(str(exc))
            speechify_voices = st.session_state.get("speechify_voices", [])
            options = list(range(len(speechify_voices)))
            if options:
                choice = st.selectbox("Voz de la vista previa",options,format_func=lambda i: f'{speechify_voices[i]["name"]} · {speechify_voices[i]["locale"]} · {speechify_voices[i]["id"]}',key="speechify_preview_voice")
                voice_name = speechify_voices[choice]["id"]
            else:
                voice_name = ""
                st.caption("Carga el catálogo para elegir una voz disponible en tu cuenta.")
        else:
            options=list(PIPER_VOICES[lang]) if engine=="Piper" else ["Dora","Alex","Santa"]
            voice_name=st.selectbox("Voz de la vista previa",options,key="preview_voice")
        style=st.selectbox("Estilo de voz Piper",list(PIPER_STYLES),key="piper_style")
        st.caption("El estilo ajusta el ritmo y la variación de la voz en esta vista previa; el resultado depende del modelo elegido.")
        rate=st.slider("Velocidad",0.5,2.0,1.0)
        pitch=st.slider("Tono",0.5,2.0,1.0)
        strength=st.select_slider("Intensidad de voz Piper", options=[3.0, 4.5, 6.0], value=4.5, format_func=lambda x: {3.0:"Normal", 4.5:"Alta", 6.0:"Muy alta"}[x])
        st.caption("Una intensidad mayor eleva las partes suaves y puede modificar el timbre. Se aplica al reproductor y al WAV descargado.")
        auto=st.checkbox("Reproducir localmente al conectar")
        voice=dict(text=body,lang=lang,rate=rate,pitch=pitch,auto=auto)
        st.caption("La primera generación de una voz puede tardar unos minutos mientras se descarga su modelo.")
        if engine=="Narración": st.caption("Narración ofrece voces adicionales en español; el estilo y la intensidad Piper no se aplican a este motor.")
        if engine=="Speechify": st.caption("Los controles de velocidad, tono, estilo e intensidad no afectan la vista previa de Speechify. El audio de Speechify no se transmite automáticamente durante las llamadas.")
        st.caption("La voz elegida y la velocidad se aplican a esta vista previa. El teléfono usa sus propias voces; el tono corresponde a Android.")
        st.caption("También puedes escuchar las voces instaladas en tu navegador; esas voces se reproducen en este dispositivo.")
        browser_settings=json.dumps(dict(text=preview_body,lang=lang,rate=rate,pitch=pitch),ensure_ascii=True).replace("<", "\\u003c")
        components.html("""
        <div style="font:14px sans-serif;color:#eee;background:#19191b;padding:12px;border-radius:8px">
          <label for="browser-voices">Voces del navegador</label><br>
          <select id="browser-voices" style="max-width:100%;padding:8px;margin:6px 0"></select>
          <button id="speak" style="padding:8px">Escuchar voz del navegador</button>
          <button id="stop" style="padding:8px">Detener</button>
          <div id="voice-status" role="status"></div>
        </div>
        <script>
        const settings = SETTINGS;
        const select = document.getElementById('browser-voices');
        const status = document.getElementById('voice-status');
        function refreshVoices() {
          const prior=select.value; select.replaceChildren();
          const all=window.speechSynthesis ? speechSynthesis.getVoices() : [];
          const matches=all.filter(v => v.lang.toLowerCase().startsWith(settings.lang.slice(0,2).toLowerCase()));
          for (const voice of matches) { const o=document.createElement('option'); o.value=voice.voiceURI; o.textContent=voice.name+' ('+voice.lang+')'; select.appendChild(o); }
          if ([...select.options].some(o=>o.value===prior)) select.value=prior;
          status.textContent=matches.length ? '' : 'No hay voces disponibles para este idioma en el navegador.';
        }
        if (window.speechSynthesis) { speechSynthesis.onvoiceschanged=refreshVoices; refreshVoices(); }
        else status.textContent='Este navegador no ofrece síntesis de voz.';
        document.getElementById('speak').onclick=()=>{
          if (!settings.text.trim()) { status.textContent='Escribe un mensaje antes de escucharlo.'; return; }
          const chosen=speechSynthesis.getVoices().find(v=>v.voiceURI===select.value);
          if (!chosen) { status.textContent='No hay una voz disponible.'; return; }
          speechSynthesis.cancel();
          const u=new SpeechSynthesisUtterance(settings.text); u.voice=chosen; u.lang=chosen.lang;
          u.rate=settings.rate; u.pitch=settings.pitch;
          u.onstart=()=>status.textContent='Reproduciendo…';
          u.onend=()=>status.textContent='Reproducción terminada.';
          u.onerror=()=>status.textContent='No se pudo reproducir la voz en este navegador.';
          speechSynthesis.speak(u);
        };
        document.getElementById('stop').onclick=()=>{ if(window.speechSynthesis) speechSynthesis.cancel(); };
        </script>
        """.replace("SETTINGS",browser_settings),height=135)

        signature=(preview_body,lang,rate,voice_name,strength,style,engine)
        if st.button("Generar vista previa",disabled=not body.strip() or (engine=="Narración" and not lang.startswith("es")) or (engine=="Speechify" and (not speechify_key or not voice_name)),key="generate_voice"):
            try:
                with st.spinner("Preparando voz y generando audio…"):
                    if engine=="Narración":
                        import narrator
                        audio = narrator.generate(preview_body,voice_name,rate)
                    elif engine=="Speechify":
                        import speechify_client
                        audio = speechify_client.synthesize(speechify_key,preview_body,voice_name,lang)
                    else:
                        audio = generate_piper_preview(preview_body, lang, rate, voice_name, strength, style)
                st.session_state.redial_voice_preview=(signature,audio)
            except Exception as exc:
                st.session_state.pop("redial_voice_preview",None)
                st.error("No se pudo generar la voz. Comprueba la conexión del servidor e inténtalo otra vez.")
                st.exception(exc)
        preview=st.session_state.get("redial_voice_preview")
        if preview and preview[0]==signature:
            st.audio(preview[1],format="audio/wav")
            st.download_button("Descargar voz WAV",preview[1],file_name="REDIAL_voz.wav",mime="audio/wav",key="download_voice")

    return entries,name,dict(retries=int(retries),interval=int(interval)*60,start=start.strftime("%H:%M"),end=end.strftime("%H:%M"),voice=voice)

def results():
    with connect() as db:
        setup(db)
        rows=[dict(r) for r in db.execute("""SELECT c.name campaña,j.phone número,j.state estado,j.attempt intentos,
        json_extract(j.meta,'$.tipo') tipo,json_extract(j.meta,'$.compania') compañía,
        a.result último_resultado FROM jobs j JOIN campaigns c ON c.id=j.campaign LEFT JOIN attempts a ON a.token=j.token
        ORDER BY c.created DESC,j.id""")]
    if rows: st.dataframe(rows,hide_index=True)
    else: st.caption("Aún no hay resultados de campaña.")
    return rows

def rules_editor():
    with st.expander("Asignaciones de numeración"):
        st.caption("Prefijo nacional de 2 a 10 dígitos. Una coincidencia de prefijo es una asignación documentada y puede cambiar por portabilidad.")
        with st.form("prefix_rule"):
            prefix=st.text_input("Número nacional o prefijo")
            kind=st.selectbox("Tipo asignado",["Desconocido","MÓVIL","FIJO"])
            carrier=st.text_input("Compañía asignada")
            provenance=st.text_input("Fuente de la asignación")
            submit=st.form_submit_button("Guardar asignación")
        if submit:
            if re.fullmatch(r"[0-9]{2,10}",prefix) and provenance.strip():
                with connect() as db:
                    setup(db)
                    db.execute("INSERT OR REPLACE INTO line_rules VALUES(?,?,?,?,?)",(prefix,kind,carrier,provenance,str(date.today())))
                st.success("Asignación guardada")
            else: st.error("Revisa el prefijo y la fuente.")

def export_panel(channel):
    records={}
    with connect() as db:
        setup(db)
        rules=[dict(r) for r in db.execute("SELECT * FROM line_rules ORDER BY length(prefix) DESC")]
        jobs=db.execute("""SELECT phone,meta,state FROM jobs ORDER BY id""").fetchall()
    for job in jobs:
        meta=json.loads(job["meta"])
        if meta.get(channel) and meta["tipo"]=="MÓVIL":
            records[job["phone"]]=(meta["compania"],job["state"])
        else: records.pop(job["phone"],None)
    for row in list_contacts(100000):
        phone="+"+row["phone"]
        meta=classify(row,rules)
        if meta["tipo"]=="MÓVIL" and eligible(dict(row,line_type="mobile"),channel):
            records[phone]=(meta["compania"],records.get(phone,("","Sin campaña"))[1])
        else: records.pop(phone,None)
    carrier=st.multiselect("Filtrar por compañía",sorted({v[0] for v in records.values()}))
    status=st.multiselect("Filtrar por estatus",sorted({v[1] for v in records.values()}))
    table=[{"Incluir":True,"Número":n,"Compañía":v[0],"Estado":v[1]} for n,v in records.items()
           if (not carrier or v[0] in carrier) and (not status or v[1] in status)]
    if not table:
        st.caption("Sin móviles elegibles para este canal y estos filtros.")
        return
    selected=st.data_editor(table,disabled=["Número","Compañía","Estado"],hide_index=True,key="segment_"+channel)
    phones=[r["Número"] for r in selected if r["Incluir"]]
    st.download_button("CSV de números","phone\n"+"\n".join(phones),"moviles.csv","text/csv",disabled=not phones)
    st.download_button("JSON",json.dumps(phones),"moviles.json","application/json",disabled=not phones)
    if phones: st.code("\n".join(phones),language=None)

def collections_desk():
    from campaign import COLLECTION_RESULTS
    from html import escape
    with connect() as db:
        setup(db)
        rows=[dict(r) for r in db.execute("""SELECT c.name AS campaña, j.phone AS teléfono,
               j.state AS resultado, j.attempt AS intentos FROM jobs j JOIN campaigns c ON c.id=j.campaign
               ORDER BY j.id DESC""")]
    pending=sum(r["resultado"] in ("Pendiente","Programada","Entregada") for r in rows)
    promises=sum(r["resultado"]=="Promesa de pago" for r in rows)
    review=sum(r["resultado"] in ("Sin confirmar","Aclaración solicitada","Pago reportado","Revisar nombre") for r in rows)
    columns=st.columns(3)
    for col,title,count in zip(columns,("En cola","Promesas de pago","Por revisar"),(pending,promises,review)):
        col.metric(title,count,border=True)
    with st.expander("Buscar una gestión",expanded=False):
        query=st.text_input("Buscar por número o campaña").strip().casefold()
        outcome=st.selectbox("Resultado",["Todos"]+sorted({r["resultado"] for r in rows} | COLLECTION_RESULTS))
        selected=[r for r in rows if (outcome=="Todos" or r["resultado"]==outcome) and
                  (query in r["teléfono"] or query in r["campaña"].casefold())]
        if selected: st.dataframe(selected,hide_index=True,use_container_width=True)
        else: st.caption("Sin gestiones que coincidan con la búsqueda.")

