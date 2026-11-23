import json
import re
from datetime import date
import streamlit as st
import streamlit.components.v1 as components
from core import clean_record,import_csv_text,eligible
from store import connect,get,list_contacts
from campaign import setup,classify

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
        body=st.text_area("Texto del mensaje",max_chars=2000)
        lang=st.selectbox("Idioma",["es-MX","es-ES","en-US"])
        rate=st.slider("Velocidad",0.5,2.0,1.0)
        pitch=st.slider("Tono",0.5,2.0,1.0)
        auto=st.checkbox("Reproducir localmente al conectar")
        voice=dict(text=body,lang=lang,rate=rate,pitch=pitch,auto=auto)
        if body:
            data=json.dumps(voice).replace("<","\\u003c")
            components.html("""<style>body{margin:0;background:#151518;color:#eee;font:14px sans-serif}button{background:#edeae3;color:#111;border:0;border-radius:8px;padding:10px 16px;cursor:pointer}span{margin-left:12px}</style>
            <label for="voices">Voz de esta computadora</label><br><select id="voices" style="width:100%;background:#29292b;color:#fff;padding:9px;margin:6px 0 10px;border:1px solid #555;border-radius:7px"></select><br><button id="preview">Escuchar vista previa</button> <button id="stop">Detener</button> <button id="test">Probar sonido</button><span id="msg" role="status"></span><script>
            const p=PARAM, msg=document.getElementById('msg'), button=document.getElementById('preview'), select=document.getElementById('voices');
            document.getElementById('test').addEventListener('click',async()=>{
                try{const context=new (window.AudioContext||window.webkitAudioContext)();await context.resume();const oscillator=context.createOscillator(), gain=context.createGain();oscillator.frequency.value=660;gain.gain.value=0.12;oscillator.connect(gain);gain.connect(context.destination);oscillator.start();oscillator.stop(context.currentTime+0.35);oscillator.onended=()=>context.close();msg.textContent='Prueba de sonido enviada al navegador'}
                catch(e){msg.textContent='El navegador bloqueó la prueba de sonido'}
            });
            function refreshVoices(){
                const voices=speechSynthesis.getVoices(), previous=select.value;
                select.replaceChildren();
                const relevant=voices.filter(v=>v.lang.toLowerCase().startsWith(p.lang.slice(0,2).toLowerCase()));
                for(const v of relevant){const o=document.createElement('option');o.value=v.voiceURI;o.textContent=v.name+' · '+v.lang;select.appendChild(o)}
                if(previous && relevant.some(v=>v.voiceURI===previous)) select.value=previous;
                if(!relevant.length){const o=document.createElement('option');o.textContent='Sin voces instaladas para este idioma';select.appendChild(o)}
            }
            if('speechSynthesis' in window){refreshVoices();speechSynthesis.onvoiceschanged=refreshVoices}
            document.getElementById('stop').addEventListener('click',()=>{speechSynthesis.cancel();msg.textContent='Reproducción detenida'});
            button.addEventListener('click',()=>{
                if(!('speechSynthesis' in window)){msg.textContent='Este navegador no admite voz';return}
                try{
                    speechSynthesis.cancel();speechSynthesis.resume();
                    const u=new SpeechSynthesisUtterance(p.text);u.lang=p.lang;u.rate=p.rate;u.pitch=p.pitch;
                    const voices=speechSynthesis.getVoices();u.voice=voices.find(v=>v.voiceURI===select.value)||voices.find(v=>v.lang.toLowerCase()===p.lang.toLowerCase())||voices.find(v=>v.lang.toLowerCase().startsWith(p.lang.slice(0,2).toLowerCase()))||null;
                    u.onstart=()=>msg.textContent='Reproduciendo en esta computadora';
                    u.onend=()=>msg.textContent='El navegador terminó la lectura';
                    u.onerror=()=>msg.textContent='No se pudo reproducir. Revisa el audio y la voz del navegador';
                    msg.textContent='Preparando voz';speechSynthesis.speak(u);
                }catch(e){msg.textContent='No se pudo iniciar la voz'}
            });</script>""".replace("PARAM",data),height=125)

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
    review=sum(r["resultado"] in ("Sin confirmar","Aclaración solicitada","Pago reportado") for r in rows)
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
