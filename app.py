import streamlit as st
import xml.etree.ElementTree as ET
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

st.set_page_config(page_title="Recepción de Mercancía SICAR", layout="wide")

st.markdown("""
    <style>
    .big-font { font-size:28px !important; font-weight: bold; }
    .success-text { color: #a3cfbb; background-color: #051b11; padding: 15px; border-radius: 10px; font-size: 20px; border: 1px solid #a3cfbb;}
    .offline-warning { color: #842029; background-color: #f8d7da; padding: 15px; border-radius: 10px; font-size: 20px; border: 1px solid #f5c2c7; font-weight: bold;}
    .duplicate-warning { color: #ffffff; background-color: #dc3545; padding: 20px; border-radius: 10px; font-size: 24px; font-weight: bold; text-align: center;}
    
    div[data-testid="stCodeBlock"] {
        background-color: #1e1e1e !important;
        border: 2px solid #00ff88 !important;
        border-radius: 8px;
    }
    button[title="Copy to clipboard"] {
        opacity: 1 !important;
        transform: scale(1.5) !important;
        background-color: #00ff88 !important;
        border-radius: 4px;
    }
    button[title="Copy to clipboard"] svg {
        fill: #000000 !important;
    }
    </style>
""", unsafe_allow_html=True)

def conectar_sheets():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    
    # Leer credenciales desde los secretos de Streamlit (Bóveda segura)
    credenciales_dict = dict(st.secrets["gcp_service_account"])
    credenciales = Credentials.from_service_account_info(credenciales_dict, scopes=scopes)
    
    cliente = gspread.authorize(credenciales)
    return cliente.open("Control_Ingresos_SICAR")

def procesar_factura(archivo_xml):
    tree = ET.parse(archivo_xml)
    root = tree.getroot()
    ns = {'cfdi': 'http://www.sat.gob.mx/cfd/4'}
    ns_tfd = {'tfd': 'http://www.sat.gob.mx/TimbreFiscalDigital'}
    
    folio = root.get('Folio', 'Sin Folio')
    emisor = root.find('.//cfdi:Emisor', ns)
    proveedor = emisor.get('Nombre') if emisor is not None else "Proveedor Desconocido"
    
    # Extraer el UUID (Folio Fiscal único)
    complemento = root.find('.//cfdi:Complemento', ns)
    if complemento is not None:
        timbre = complemento.find('.//tfd:TimbreFiscalDigital', ns_tfd)
        uuid = timbre.get('UUID') if timbre is not None else "SIN-UUID"
    else:
        uuid = "SIN-UUID"
    
    articulos = []
    for concepto in root.findall('.//cfdi:Concepto', ns):
        articulos.append({
            'Código': concepto.get('NoIdentificacion', 'N/A'),
            'Descripción': concepto.get('Descripcion', ''),
            'Cantidad': float(concepto.get('Cantidad', 0)),
            'Precio Unitario': float(concepto.get('ValorUnitario', 0))
        })
    return folio, proveedor, uuid, pd.DataFrame(articulos)

def es_factura_duplicada(doc, uuid_factura):
    try:
        hoja_resumen = doc.worksheet("Resumen_Facturas")
        # Obtenemos todos los valores de la columna C (donde estará el UUID)
        uuids_registrados = hoja_resumen.col_values(3)
        return uuid_factura in uuids_registrados
    except Exception:
        # Si no hay internet para validar, devolvemos un error para que no siga a ciegas
        return "ERROR_CONEXION"

# --- MEMORIA DEL SISTEMA ---
if 'factura_procesada' not in st.session_state:
    st.session_state.factura_procesada = False
if 'datos_actuales' not in st.session_state:
    st.session_state.datos_actuales = None
if 'mensaje_exito' not in st.session_state:
    st.session_state.mensaje_exito = False

# --- INTERFAZ ---
st.markdown('<p class="big-font">📦 Ingreso de Mercancía a SICAR</p>', unsafe_allow_html=True)

if st.session_state.mensaje_exito:
    st.markdown('<p class="success-text">✅ ¡Artículos registrados exitosamente! Pantalla lista para la siguiente factura.</p>', unsafe_allow_html=True)
    st.session_state.mensaje_exito = False 

if not st.session_state.factura_procesada:
    archivo_subido = st.file_uploader("📂 Selecciona o arrastra el archivo XML de la factura aquí", type=['xml'])
    
    if archivo_subido is not None:
        try:
            with st.spinner('Analizando XML y verificando duplicados...'):
                folio, proveedor, uuid, df_articulos = procesar_factura(archivo_subido)
                doc = conectar_sheets()
                
                # Validar duplicidad
                estado_duplicado = es_factura_duplicada(doc, uuid)
                
                if estado_duplicado == True:
                    st.markdown(f'<div class="duplicate-warning">🚨 ¡ALTO! Esta factura ya fue ingresada al sistema previamente.<br>Folio: {folio} | Proveedor: {proveedor}</div>', unsafe_allow_html=True)
                elif estado_duplicado == "ERROR_CONEXION":
                    st.markdown('<div class="offline-warning">📡 SIN CONEXIÓN. No se puede verificar si la factura es duplicada. Revisa tu internet.</div>', unsafe_allow_html=True)
                else:
                    # Si no es duplicada, guardamos en memoria y avanzamos
                    st.session_state.datos_actuales = {
                        'folio': folio, 'proveedor': proveedor, 'uuid': uuid, 
                        'dataframe': df_articulos, 'total_articulos': len(df_articulos)
                    }
                    st.session_state.factura_procesada = True
                    st.rerun()
                    
        except Exception as e:
            st.error(f"Error al procesar el archivo. Revisa tu conexión. Detalle: {e}")

else:
    datos = st.session_state.datos_actuales
    st.markdown("---")
    st.subheader(f"🧾 Factura: {datos['folio']} | Proveedor: {datos['proveedor']}")
    st.info("Da clic en el botón verde de la esquina de cada recuadro para copiar. Marca la casilla ✅ al ingresarlo a SICAR.")
    
    df = datos['dataframe']
    todos_listos = True

    for i, row in df.iterrows():
        st.markdown("---")
        col_chk, col_cod, col_desc, col_cant, col_precio = st.columns([1, 2, 4, 1, 1.5])
        
        with col_chk:
            st.write("") 
            ingresado = st.checkbox("✅ Ingresado", key=f"chk_{i}")
            if not ingresado:
                todos_listos = False
                
        with col_cod:
            st.caption("CÓDIGO")
            st.code(row['Código'], language="text")
            
        with col_desc:
            st.caption("DESCRIPCIÓN")
            st.code(row['Descripción'], language="text")
            
        with col_cant:
            st.caption("PIEZAS")
            st.code(str(row['Cantidad']), language="text")
            
        with col_precio:
            st.caption("PRECIO UNITARIO")
            st.code(f"{row['Precio Unitario']:.2f}", language="text")

    st.markdown("---")
    
    if not todos_listos:
        st.warning("⚠️ Debes marcar todas las casillas como 'Ingresado' para poder finalizar.")
        
    if st.button("🚀 Confirmar Entrada Total", type="primary", use_container_width=True, disabled=not todos_listos):
        try:
            with st.spinner('Guardando datos en la nube...'):
                doc = conectar_sheets()
                hoja_resumen = doc.worksheet("Resumen_Facturas")
                hoja_detalle = doc.worksheet("Detalle_Articulos")
                fecha_actual = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                
                # OJO: Se agregó el UUID (datos['uuid']) en la posición 3 para coincidir con la Columna C
                hoja_resumen.append_row([fecha_actual, datos['folio'], datos['uuid'], datos['proveedor'], datos['total_articulos'], "🟢 Completado"])
                
                filas_detalle = []
                for _, row in df.iterrows():
                    filas_detalle.append([
                        fecha_actual, 
                        datos['folio'], 
                        row['Código'], 
                        row['Descripción'], 
                        row['Cantidad'], 
                        row['Precio Unitario']
                    ])
                hoja_detalle.append_rows(filas_detalle)
                
                st.session_state.factura_procesada = False
                st.session_state.datos_actuales = None
                for key in list(st.session_state.keys()):
                    if key.startswith('chk_'):
                        del st.session_state[key]
                        
                st.session_state.mensaje_exito = True
                st.rerun()
                
        except gspread.exceptions.APIError:
             st.markdown('<p class="offline-warning">❌ Error de permisos en Google. Verifica que el robot tenga acceso de Editor.</p>', unsafe_allow_html=True)
        except Exception as e:
            st.markdown(f'<p class="offline-warning">📡 SIN CONEXIÓN A INTERNET. <br>Los datos de esta factura NO se han borrado de tu pantalla. Revisa tu conexión y vuelve a presionar el botón de Confirmar Entrada.</p>', unsafe_allow_html=True)