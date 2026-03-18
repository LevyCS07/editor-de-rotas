import streamlit as st
import pandas as pd
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from lxml import etree
import io
from simplekml import Kml

st.set_page_config(layout="wide", page_title="Editor de Rotas")

# Estado inicial
if "colaboradores" not in st.session_state:
    st.session_state["colaboradores"] = pd.DataFrame()
if "rotas" not in st.session_state:
    st.session_state["rotas"] = {}
if "selecionado" not in st.session_state:
    st.session_state["selecionado"] = None

# Cores para rotas
CORES = ['red', 'blue', 'green', 'purple', 'orange', 'darkred', 'darkblue', 'darkgreen']

# Função para carregar KML
def carregar_kml(file):
    try:
        tree = etree.fromstring(file.read())
        ns = {"kml": "http://www.opengis.net/kml/2.2"}
        segmentos = []
        coords = tree.xpath("//kml:coordinates", namespaces=ns)
        for c in coords:
            pontos = []
            for par in c.text.strip().split():
                lon, lat, _ = par.split(",")[:3]
                pontos.append((float(lat), float(lon)))
            if pontos:
                segmentos.append(pontos)
        return segmentos
    except:
        return []

# Título
st.title("🗺️ Editor de Rotas")

# Sidebar
with st.sidebar:
    st.header("📁 Arquivos")
    
    # Upload KMLs
    kmls = st.file_uploader("KMLs", type=["kml"], accept_multiple_files=True)
    if kmls:
        rotas = {}
        for f in kmls:
            nome = f.name.replace(".kml", "")
            segmentos = carregar_kml(f)
            if segmentos:
                rotas[nome] = segmentos
        st.session_state["rotas"] = rotas
        st.success(f"{len(rotas)} rotas carregadas")
    
    # Upload Planilha
    xlsx = st.file_uploader("Planilha", type=["xlsx"])
    if xlsx:
        try:
            df = pd.read_excel(xlsx, engine="openpyxl")
            st.session_state["colaboradores"] = df
            st.success("Planilha carregada")
        except:
            st.error("Erro ao carregar planilha")
    
    # Seleção de rotas
    rotas_ativas = []
    if st.session_state["rotas"]:
        st.divider()
        st.header("🛣️ Rotas")
        todas = st.checkbox("Todas", value=True)
        for i, nome in enumerate(st.session_state["rotas"].keys()):
            cor = CORES[i % len(CORES)]
            if todas or st.checkbox(f"{nome}", key=f"rota_{nome}"):
                rotas_ativas.append((nome, cor))
    
    # Editor
    if st.session_state["selecionado"]:
        st.divider()
        st.header("✏️ Editar")
        st.info(f"Selecionado: {st.session_state['selecionado']}")
        
        if st.session_state["rotas"]:
            nova = st.selectbox("Nova rota", list(st.session_state["rotas"].keys()))
            if st.button("Transferir"):
                idx = st.session_state["colaboradores"][
                    st.session_state["colaboradores"]["COLABORADORES"] == st.session_state["selecionado"]
                ].index[0]
                st.session_state["colaboradores"].at[idx, "ROTA"] = nova
                st.session_state["selecionado"] = None
                st.rerun()

# Mapa
m = folium.Map(location=[-3.119, -60.021], zoom_start=12)

# Desenhar rotas
for nome, cor in rotas_ativas:
    for seg in st.session_state["rotas"][nome]:
        folium.PolyLine(seg, color=cor, weight=3, popup=nome).add_to(m)

# Desenhar colaboradores
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
                icon=folium.Icon(color="blue")
            ).add_to(cluster)
        except:
            continue

# Mostrar mapa
mapa = st_folium(m, height=600, width=None, key="mapa")

# Capturar clique
if mapa and mapa.get("last_object_clicked"):
    popup = mapa["last_object_clicked"].get("popup")
    if popup:
        st.session_state["selecionado"] = popup
        st.rerun()

# Exportação
if not st.session_state["colaboradores"].empty:
    st.divider()
    col1, col2 = st.columns(2)
    
    # Exportar XLSX
    with col1:
        buffer = io.BytesIO()
        st.session_state["colaboradores"].to_excel(buffer, index=False)
        st.download_button(
            "📥 Download XLSX",
            buffer.getvalue(),
            "colaboradores_editados.xlsx"
        )
    
    # Exportar KML
    with col2:
        if st.session_state["rotas"]:
            kml = Kml()
            for nome, segs in st.session_state["rotas"].items():
                for seg in segs:
                    coords = [(lon, lat) for lat, lon in seg]
                    kml.newlinestring(name=nome, coords=coords)
            kml_buffer = io.BytesIO(kml.kml().encode("utf-8"))
            st.download_button(
                "🗺️ Download KML",
                kml_buffer.getvalue(),
                "rotas_editadas.kml"
            )
