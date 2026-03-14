import streamlit as st
import pandas as pd
import folium
from folium.plugins import MarkerCluster
from lxml import etree

st.set_page_config(layout="wide", page_title="Editor de Rotas - Versão 2.1")

st.title("🗺️ Editor de Rotas - Versão 2.1")

uploaded_kmls = st.file_uploader("Upload dos KMLs (rotas)", type=["kml"], accept_multiple_files=True)
uploaded_xlsx = st.file_uploader("Upload da relação de colaboradores (XLSX)", type=["xlsx"])

if "colaboradores" not in st.session_state:
    st.session_state["colaboradores"] = pd.DataFrame()

if uploaded_xlsx:
    st.session_state["colaboradores"] = pd.read_excel(uploaded_xlsx, engine="openpyxl")

colaboradores = st.session_state["colaboradores"]

# Criar mapa
m = folium.Map(location=[-3.119, -60.021], zoom_start=12)

rotas = {}
if uploaded_kmls:
    for file in uploaded_kmls:
        kml_content = file.read()
        tree = etree.fromstring(kml_content)
        ns = {"kml": "http://www.opengis.net/kml/2.2"}
        coords = tree.xpath("//kml:coordinates", namespaces=ns)
        pontos = []
        for c in coords:
            coord_text = c.text.strip()
            for pair in coord_text.split():
                lon, lat, *_ = pair.split(",")
                pontos.append((float(lat), float(lon)))
        rotas[file.name.replace(".kml", "")] = pontos

# --- Controle de rotas ---
st.subheader("⚙️ Controle de rotas no mapa")
if rotas:
    todas = st.checkbox("Ativar/Desativar todas as rotas", value=True)
    rotas_selecionadas = []
    for nome in rotas.keys():
        if todas or st.checkbox(f"Mostrar rota {nome}", value=False):
            rotas_selecionadas.append(nome)

    # Adicionar apenas rotas selecionadas
    for nome in rotas_selecionadas:
        folium.PolyLine(rotas[nome], color="red", weight=3, opacity=0.8).add_to(m)

# --- Cluster de colaboradores ---
if not colaboradores.empty:
    cluster = MarkerCluster().add_to(m)
    for _, row in colaboradores.iterrows():
        try:
            lat = float(str(row["LAT"]).replace(",", "."))
            lon = float(str(row["LONG"]).replace(",", "."))
            folium.Marker(
                location=[lat, lon],
                popup=f"{row['COLABORADORES']} (Matrícula: {row['MATRÍCULA']}, Rota: {row['ROTA']})",
                icon=folium.Icon(color="blue", icon="user")
            ).add_to(cluster)
        except:
            pass

st.components.v1.html(m._repr_html_(), height=600)

# Resumo por rota
if not colaboradores.empty:
    st.subheader("📌 Resumo por rota")
    resumo = colaboradores.groupby("ROTA")["COLABORADORES"].count().reset_index()
    resumo.columns = ["Rota", "Qtd Colaboradores"]
    st.table(resumo)


