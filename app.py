import streamlit as st
import pandas as pd
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from lxml import etree
import io
from simplekml import Kml
from datetime import datetime
import re

st.set_page_config(layout="wide", page_title="Editor de Rotas")

# Estado inicial
if "colaboradores" not in st.session_state:
    st.session_state["colaboradores"] = pd.DataFrame()
if "colaboradores_backup" not in st.session_state:
    st.session_state["colaboradores_backup"] = pd.DataFrame()
if "rotas" not in st.session_state:
    st.session_state["rotas"] = {}
if "selecionado" not in st.session_state:
    st.session_state["selecionado"] = None
if "historico" not in st.session_state:
    st.session_state["historico"] = []
if "ultima_acao" not in st.session_state:
    st.session_state["ultima_acao"] = None
if "erros_validacao" not in st.session_state:
    st.session_state["erros_validacao"] = []

# Cores para as rotas
CORES_ROTAS = ['red', 'blue', 'green', 'purple', 'orange', 'darkred', 
               'darkblue', 'darkgreen', 'cadetblue', 'pink']

# Função para carregar KML
def carregar_kml(file):
    try:
        tree = etree.fromstring(file.read())
        ns = {"kml": "http://www.opengis.net/kml/2.2"}
        segmentos = []
        coords = tree.xpath("//kml:coordinates", namespaces=ns)
        for c in coords:
            coord_text = c.text.strip()
            pontos = []
            for pair in coord_text.split():
                lon, lat, *_ = pair.split(",")
                pontos.append((float(lat), float(lon)))
            if pontos:
                segmentos.append(pontos)
        return segmentos
    except Exception as e:
        st.error(f"Erro no KML: {str(e)}")
        return []

# Função de validação
def validar_colaboradores(df):
    erros = []
    
    if df.empty:
        erros.append("Nenhum colaborador encontrado")
        return erros
    
    colunas_obrigatorias = ["COLABORADORES", "LAT", "LONG", "ROTA"]
    for col in colunas_obrigatorias:
        if col not in df.columns:
            erros.append(f"Coluna '{col}' não encontrada")
    
    return erros

# Interface principal
st.title("🗺️ Editor de Rotas")

# Sidebar
with st.sidebar:
    st.header("⚙️ Controles")
    
    # Upload
    uploaded_kmls = st.file_uploader("KMLs", type=["kml"], accept_multiple_files=True)
    uploaded_xlsx = st.file_uploader("Planilha", type=["xlsx"])
    
    # Carregar planilha
    if uploaded_xlsx and st.button("Carregar Planilha"):
        try:
            df_novo = pd.read_excel(uploaded_xlsx, engine="openpyxl")
            erros = validar_colaboradores(df_novo)
            
            if not erros:
                st.session_state["colaboradores"] = df_novo
                st.session_state["colaboradores_backup"] = df_novo.copy()
                st.success("Planilha carregada!")
                st.rerun()
            else:
                for erro in erros:
                    st.error(erro)
        except Exception as e:
            st.error(f"Erro: {str(e)}")
    
    # Carregar KMLs
    if uploaded_kmls and st.button("Carregar Rotas"):
        rotas = {}
        for file in uploaded_kmls:
            segmentos = carregar_kml(file)
            if segmentos:
                nome = file.name.replace(".kml", "")
                rotas[nome] = segmentos
        st.session_state["rotas"] = rotas
        st.success(f"{len(rotas)} rotas carregadas!")
        st.rerun()
    
    # Selecionar rotas
    rotas_selecionadas = []
    if st.session_state["rotas"]:
        st.divider()
        st.subheader("Rotas disponíveis")
        todas = st.checkbox("Todas", value=True)
        
        for i, nome in enumerate(st.session_state["rotas"].keys()):
            cor = CORES_ROTAS[i % len(CORES_ROTAS)]
            if todas or st.checkbox(nome, key=f"rota_{nome}"):
                rotas_selecionadas.append((nome, cor))
    
    # Resumo
    if not st.session_state["colaboradores"].empty:
        st.divider()
        st.subheader("Resumo")
        resumo = st.session_state["colaboradores"].groupby("ROTA").size()
        for rota, qtd in resumo.items():
            st.text(f"{rota}: {qtd} colaboradores")
    
    # Edição
    if st.session_state["selecionado"]:
        st.divider()
        st.subheader("Edição")
        st.info(f"Selecionado: {st.session_state['selecionado']}")
        
        colaborador = st.session_state["colaboradores"][
            st.session_state["colaboradores"]["COLABORADORES"] == st.session_state["selecionado"]
        ].iloc[0]
        
        st.text(f"Rota atual: {colaborador['ROTA']}")
        
        if st.session_state["rotas"]:
            nova_rota = st.selectbox("Nova rota", list(st.session_state["rotas"].keys()))
            
            if st.button("Transferir"):
                idx = st.session_state["colaboradores"][
                    st.session_state["colaboradores"]["COLABORADORES"] == st.session_state["selecionado"]
                ].index[0]
                
                rota_antiga = st.session_state["colaboradores"].at[idx, "ROTA"]
                st.session_state["colaboradores"].at[idx, "ROTA"] = nova_rota
                
                # Histórico
                st.session_state["historico"].append({
                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                    "colaborador": st.session_state["selecionado"],
                    "de": rota_antiga,
                    "para": nova_rota
                })
                
                st.session_state["selecionado"] = None
                st.success("Transferido!")
                st.rerun()

# Mapa
m = folium.Map(location=[-3.119, -60.021], zoom_start=12)

# Adicionar rotas
if 'rotas_selecionadas' in locals():
    for nome, cor in rotas_selecionadas:
        for segmento in st.session_state["rotas"][nome]:
            folium.PolyLine(
                segmento,
                color=cor,
                weight=3,
                opacity=0.8,
                popup=nome
            ).add_to(m)

# Adicionar colaboradores
if not st.session_state["colaboradores"].empty:
    cluster = MarkerCluster().add_to(m)
    
    for _, row in st.session_state["colaboradores"].iterrows():
        try:
            lat = float(str(row["LAT"]).replace(",", "."))
            lon = float(str(row["LONG"]).replace(",", "."))
            nome = row["COLABORADORES"]
            
            folium.Marker(
                [lat, lon],
                popup=nome,
                tooltip=nome,
                icon=folium.Icon(color='blue', icon='user', prefix='fa')
            ).add_to(cluster)
        except:
            continue

# Renderizar mapa
map_data = st_folium(m, height=600, width=None, key="mapa")

# Capturar clique
if map_data and map_data.get("last_object_clicked"):
    popup = map_data["last_object_clicked"].get("popup")
    if popup:
        st.session_state["selecionado"] = popup
        st.rerun()

# Exportação
if not st.session_state["colaboradores"].empty:
    st.divider()
    col1, col2 = st.columns(2)
    
    with col1:
        buffer = io.BytesIO()
        st.session_state["colaboradores"].to_excel(buffer, index=False, engine="openpyxl")
        st.download_button(
            "📥 Download XLSX",
            buffer.getvalue(),
            "colaboradores_editados.xlsx",
            use_container_width=True
        )
    
    with col2:
        if st.session_state["rotas"]:
            kml = Kml()
            for i, (nome, segmentos) in enumerate(st.session_state["rotas"].items()):
                for segmento in segmentos:
                    ls = kml.newlinestring(
                        name=nome,
                        coords=[(lon, lat) for lat, lon in segmento]
                    )
                    ls.style.linestyle.width = 3
            kml_buffer = io.BytesIO(kml.kml().encode('utf-8'))
            st.download_button(
                "🗺️ Download KML",
                kml_buffer.getvalue(),
                "rotas_editadas.kml",
                use_container_width=True
            )
        
