import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import io
from fpdf import FPDF

# --- CONFIGURACIÓN DEPOSITARIA ---
EMPLEADOS = [
    "Edgar Galli",  # <-- AGREGADO
    "Federico Hernandez",
    "Luciano Carucci",
    "Mario Javier Salvo",
    "Melina Luxen",
    "Veronica Marasi"
]
ADMINS = ["Veronica Marasi"]
PASSWORD_ADMIN = "mariva2026" 

st.set_page_config(page_title="Sistema de Guardias - Depositaria", layout="wide")

# --- CONEXIÓN ---
conn = st.connection("gsheets", type=GSheetsConnection)

def cargar_datos():
    try:
        return conn.read(ttl="0")
    except:
        return pd.DataFrame(columns=["Empleado", "Fecha", "Tipo", "Horas", "Estado"])

df = cargar_datos()

# --- LÓGICA DE SALDOS ---
def obtener_resumen(nombre):
    user_df = df[(df["Empleado"] == nombre) & (df["Estado"] == "Aprobado")]
    h_ganadas = user_df[user_df["Tipo"] == "Guardia"]["Horas"].sum()
    d_usados = len(user_df[user_df["Tipo"] == "Día Tomado"])
    
    balance = h_ganadas - (d_usados * 8)
    return h_ganadas, d_usados, (balance // 8), (balance % 8)

# --- FUNCIÓN PARA GENERAR PDF REPORTE DETALLADO ---
def clean_txt(text):
    replacements = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n", "Ñ": "N", "Á": "A", "É": "E", "Í": "I", "Ó": "O", "Ú": "U"}
    for search, replace in replacements.items():
        text = text.replace(search, replace)
    return text.encode('latin-1', 'ignore').decode('latin-1')

def generar_reporte_pdf():
    pdf = FPDF()
    pdf.add_page()
    
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(20, 50, 100) 
    pdf.cell(0, 10, clean_txt("REPORTE DE GUARDIAS - SECTOR DEPOSITARIA"), ln=True, align="C")
    
    pdf.set_font("Helvetica", "I", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, f"Fecha de emision: {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True, align="C")
    pdf.ln(10)
    
    for emp in EMPLEADOS:
        if emp == "Edgar Galli": continue  # No procesamos al auditor en el PDF analítico
        h_tot, d_uso, d_disp, h_rem = obtener_resumen(emp)
        emp_df = df[(df["Empleado"] == emp) & (df["Estado"] == "Aprobado")]
        
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(20, 50, 100)
        pdf.cell(0, 10, clean_txt(f"Empleado: {emp}"), ln=True)
        
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(0, 0, 0)
        pdf.set_fill_color(240, 245, 250)
        pdf.cell(45, 6, clean_txt("Dias Disponibles"), border=1, fill=True, align="C")
        pdf.cell(45, 6, clean_txt("Horas Acumuladas"), border=1, fill=True, align="C")
        pdf.cell(45, 6, clean_txt("Dias Tomados"), border=1, fill=True, align="C")
        pdf.cell(45, 6, clean_txt("Total Horas Extra"), border=1, fill=True, align="C")
        pdf.ln()
        
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(45, 6, str(int(d_disp)), border=1, align="C")
        pdf.cell(45, 6, f"{int(h_rem)}/8 hs", border=1, align="C")
        pdf.cell(45, 6, str(int(d_uso)), border=1, align="C")
        pdf.cell(45, 6, f"{int(h_tot)} hs", border=1, align="C")
        pdf.ln(8)
        
        guardias = emp_df[emp_df["Tipo"] == "Guardia"]
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(0, 6, clean_txt("   > Detalle de Guardias Realizadas:"), ln=True)
        
        if not guardias.empty:
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_fill_color(235, 235, 235)
            pdf.cell(10, 6, "", ln=False) 
            pdf.cell(60, 6, clean_txt("Fecha de la Guardia"), border=1, fill=True, align="C")
            pdf.cell(60, 6, clean_txt("Horas Computadas"), border=1, fill=True, align="C")
            pdf.ln()
            
            pdf.set_font("Helvetica", "", 9)
            for _, row in guardias.iterrows():
                pdf.cell(10, 6, "", ln=False)
                pdf.cell(60, 6, clean_txt(row["Fecha"]), border=1, align="C")
                pdf.cell(60, 6, f"+{row['Horas']} hs", border=1, align="C")
                pdf.ln()
        else:
            pdf.set_font("Helvetica", "I", 9)
            pdf.set_text_color(130, 130, 130)
            pdf.cell(10, 6, "", ln=False)
            pdf.cell(0, 6, clean_txt("No registra guardias aprobadas."), ln=True)
            pdf.set_text_color(0, 0, 0)
            
        pdf.ln(4)
        
        dias_tomados = emp_df[emp_df["Tipo"] == "Día Tomado"]
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(0, 6, clean_txt("   > Detalle de Dias Compensatorios Tomados:"), ln=True)
        
        if not dias_tomados.empty:
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_fill_color(235, 235, 235)
            pdf.cell(10, 6, "", ln=False)
            pdf.cell(60, 6, clean_txt("Fecha del Franco"), border=1, fill=True, align="C")
            pdf.cell(60, 6, clean_txt("Concepto"), border=1, fill=True, align="C")
            pdf.ln()
            
            pdf.set_font("Helvetica", "", 9)
            for _, row in dias_tomados.iterrows():
                pdf.cell(10, 6, "", ln=False)
                pdf.cell(60, 6, clean_txt(row["Fecha"]), border=1, align="C")
                pdf.cell(60, 6, clean_txt(row["Tipo"]), border=1, align="C")
                pdf.ln()
        else:
            pdf.set_font("Helvetica", "I", 9)
            pdf.set_text_color(130, 130, 130)
            pdf.cell(10, 6, "", ln=False)
            pdf.cell(0, 6, clean_txt("No registra dias tomados hasta la fecha."), ln=True)
            pdf.set_text_color(0, 0, 0)
            
        pdf.ln(6)
        pdf.set_draw_color(210, 210, 210)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y()) 
        pdf.ln(4)
        
    return bytes(pdf.output())

# --- INTERFAZ STREAMLIT ---
st.title("🏦 Control de Guardias y Compensatorios - Depositaria")
st.markdown("---")

user_sel = st.selectbox("Identificate para continuar:", ["Seleccionar..."] + sorted(EMPLEADOS))

if user_sel != "Seleccionar...":
    es_admin = user_sel in ADMINS
    es_auditor = user_sel == "Edgar Galli"
    
    if "admin_logueado" not in st.session_state:
        st.session_state["admin_logueado"] = False
        
    if not es_admin:
        st.session_state["admin_logueado"] = False

    if es_admin and not st.session_state["admin_logueado"]:
        with st.expander("🔐 Administrador", expanded=True):
            pass_input = st.text_input("Contraseña de seguridad:", type="password")
            if st.button("Ingresar Sistema"):
                if pass_input == PASSWORD_ADMIN:
                    st.session_state["admin_logueado"] = True
                    st.success("Acceso concedido.")
                    st.rerun()
                else:
                    st.error("Contraseña incorrecta.")
                    
    auth_admin = st.session_state["admin_logueado"] if es_admin else False

    if auth_admin:
        if st.button("🔒 Salir de Modo Administrador"):
            st.session_state["admin_logueado"] = False
            st.rerun()

    h_tot, d_uso, d_disp, h_rem = obtener_resumen(user_sel)
    
    st.markdown(f"### Estado de {user_sel}")
    
    if not es_auditor:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Días Disponibles", f"{int(d_disp)}")
        c2.metric("Horas p/ Próximo Día", f"{int(h_rem)}/8 hs")
        c3.metric("Total Horas (Aprobadas)", f"{int(h_tot)} hs")
        c4.metric("Días Ya Tomados", f"{int(d_uso)}")

    if es_auditor:
        pest_nombres = ["📊 Resumen General del Sector"]
    else:
        pest_nombres = ["➕ Cargar Movimientos", "📜 Mi Historial"]
        if auth_admin:
            pest_nombres.insert(1, "📩 Validaciones Pendientes")
            pest_nombres.append("📊 Reporte General")
    
    tabs = st.tabs(pest_nombres)

    # LÓGICA PARA EDGAR GALLI
    if es_auditor:
        with tabs[0]:
            st.subheader("📋 Resumen Consolidado de todo el Sector Depositaria")
            st.write("A continuación se muestra el estado actual y aprobado de cada integrante:")
            
            resumen_data = []
            for emp in EMPLEADOS:
                if emp == "Edgar Galli": continue
                h_t, d_u, d_d, h_r = obtener_resumen(emp)
                resumen_data.append({
                    "Empleado": emp,
                    "Días Disponibles": int(d_d),
                    "Horas para próximo día": f"{int(h_r)}/8 hs",
                    "Días ya Usados": int(d_u),
                    "Total Horas Extra": f"{int(h_t)} hs"
                })
            resumen_df = pd.DataFrame(resumen_data)
            st.dataframe(resumen_df, use_container_width=True, hide_index=True)
            
    else:
        with tabs[0]:
            col_g, col_d = st.columns(2)
            with col_g:
                st.subheader("Registrar Guardia")
                st.write("Suma +2 horas extras para aprobación.")
                f_g = st.date_input("Fecha de la guardia:", datetime.now(), key="fecha_guardia")
                if st.button("Enviar Guardia para Revisión"):
                    nueva = pd.DataFrame([{"Empleado": user_sel, "Fecha": f_g.strftime("%d/%m/%Y"), "Tipo": "Guardia", "Horas": 2, "Estado": "Pendiente"}])
                    conn.update(data=pd.concat([df, nueva], ignore_index=True))
                    st.toast("Guardia enviada.")
                    st.rerun()
            
            with col_d:
                st.subheader("Tomar Día Compensatorio")
                if d_disp >= 1:
                    st.write(f"Tenés {int(d_disp)} días disponibles.")
                    f_d = st.date_input("Fecha del día que te tomás:", datetime.now(), key="fecha_dia")
                    if st.button("✅ Registrar Día Tomado (-8hs)"):
                        nueva = pd.DataFrame([{"Empleado": user_sel, "Fecha": f_d.strftime("%d/%m/%Y"), "Tipo": "Día Tomado", "Horas": 0, "Estado": "Aprobado"}])
                        conn.update(data=pd.concat([df, nueva], ignore_index=True))
                        st.success(f"Día registrado para el {f_d.strftime('%d/%m/%Y')}")
                        st.rerun()
                else:
                    st.warning("No tenés saldo suficiente (mínimo 8hs aprobadas).")

        if auth_admin:
            with tabs[1]:
                st.subheader("Trámites esperando resolución")
                pendientes = df[df["Estado"].isin(["Pendiente", "Baja Pendiente"])].copy()
                
                if not pendientes.empty:
                    for idx, row in pendientes.iterrows():
                        with st.container(border=True):
                            col_info, col_btn = st.columns([3, 1])
                            accion = "ALTA" if row['Estado'] == "Pendiente" else "ELIMINACIÓN"
                            col_info.write(f"**{row['Empleado']}** | {row['Fecha']} | {row['Tipo']} | Solicitud de **{accion}**")
                            
                            if row['Estado'] == "Pendiente":
                                if col_btn.button(f"Aprobar Alta", key=f"app_{idx}"):
                                    df.at[idx, "Estado"] = "Aprobado"
                                    conn.update(data=df)
                                    st.rerun()
                            else: 
                                if col_btn.button(f"Confirmar Borrado", key=f"del_{idx}"):
                                    conn.update(data=df.drop(idx))
                                    st.rerun()
                            
                            if col_btn.button(f"Rechazar", key=f"rej_{idx}"):
                                df.at[idx, "Estado"] = "Aprobado" if row['Estado'] == "Baja Pendiente" else "Rechazado"
                                conn.update(data=df)
                                st.rerun()
                else:
                    st.info("No hay solicitudes pendientes.")

        hist_idx = 2 if auth_admin else 1
        with tabs[hist_idx]:
            st.write("Tus movimientos registrados:")
            u_df = df[df["Empleado"] == user_sel].copy()
            if not u_df.empty:
                st.dataframe(u_df[["Fecha", "Tipo", "Horas", "Estado"]], use_container_width=True)
                u_df['ID'] = u_df.index
                opciones = u_df.apply(lambda x: f"ID:{x['ID']} | {x['Fecha']} | {x['Tipo']} ({x['Estado']})", axis=1).tolist()
                st.markdown("---")
                borrar = st.selectbox("Seleccioná un registro para anular:", opciones)
                
                if st.button("🗑️ Solicitar Eliminación"):
                    idx_sel = int(borrar.split("|")[0].replace("ID:", "").strip())
                    if auth_admin:
                        conn.update(data=df.drop(idx_sel))
                        st.rerun()
                    else:
                        df.at[idx_sel, "Estado"] = "Baja Pendiente"
                        conn.update(data=df)
                        st.warning("Solicitud de eliminación enviada.")
                        st.rerun()

        if auth_admin:
            with tabs[-1]:
                st.subheader("Descargar Informes del Sector")
                
                col_down1, col_down2 = st.columns(2)
                with col_down1:
                    buffer = io.BytesIO()
                    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                        df.to_excel(writer, index=False)
                    st.download_button("📥 Descargar Reporte en Excel (Completo)", buffer.getvalue(), "reporte_guardias.xlsx", use_container_width=True)
                
                with col_down2:
                    pdf_data = generar_reporte_pdf()
                    st.download_button("📄 Descargar Reporte en PDF (Presentable)", pdf_data, f"reporte_guardias_{datetime.now().strftime('%d/%m/%Y')}.pdf", "application/pdf", use_container_width=True)
                
                st.markdown("---")
                st.write("Vista previa global de la base de datos:")
                st.dataframe(df, use_container_width=True)
