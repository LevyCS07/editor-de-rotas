import streamlit as st
import pandas as pd
import folium
from lxml import etree

st.set_page_config(layout="wide", page_title="Editor de Rotas - Versão 1")

st.title("🗺️ Editor de Rotas - Versão 1")

# Upload dos arquivos
uploaded_kmls = st.file_uploader("Upload dos KMLs (rotas)", type=["kml"], accept_multiple_files=True)
uploaded_xlsx = st.file_uploader("Upload da relação de colaboradores (XLSX)", type=["xlsx"])

colaboradores = pd.DataFrame()

if uploaded_xlsx:
    colaboradores = pd.read_excel(uploaded_xlsx, engine="openpyxl")
    st.subheader("📊 Relação de colaboradores")
    st.dataframe(colaboradores)

# Criar mapa
st.subheader("🗺️ Visualização no mapa")
m = folium.Map(location=[-3.119, -60.021], zoom_start=12)

# Adicionar rotas KML ao mapa
if uploaded_kmls:
    for file in uploaded_kmls:
        kml_content = file.read()
        tree = etree.fromstring(kml_content)
        ns = {"kml": "http://www.opengis.net/kml/2.2"}
        coords = tree.xpath("//kml:coordinates", namespaces=ns)
        for c in coords:
            coord_text = c.text.strip()
            points = []
            for pair in coord_text.split():
                lon, lat, *_ = pair.split(",")
                points.append((float(lat), float(lon)))
            folium.PolyLine(points, color="red", weight=3, opacity=0.8).add_to(m)

# Adicionar colaboradores
if not colaboradores.empty:
    for _, row in colaboradores.iterrows():
        try:
            lat = float(str(row["LAT"]).replace(",", "."))
            lon = float(str(row["LONG"]).replace(",", "."))
            folium.Marker(
                location=[lat, lon],
                popup=f"{row['COLABORADORES']} (Matrícula: {row['MATRÍCULA']}, Rota: {row['ROTA']})",
                icon=folium.Icon(color="blue", icon="user")
            ).add_to(m)
        except:
            pass

# Renderizar mapa sem recarregar a cada movimento
st.components.v1.html(m._repr_html_(), height=600)

# Resumo por rota
if not colaboradores.empty:
    st.subheader("📌 Resumo por rota")
    resumo = colaboradores.groupby("ROTA")["COLABORADORES"].count().reset_index()
    resumo.columns = ["Rota", "Qtd Colaboradores"]
    st.table(resumo)

