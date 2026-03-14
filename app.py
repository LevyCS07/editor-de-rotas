import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from fastkml import kml
from shapely.geometry import mapping
import io

st.set_page_config(layout="wide", page_title="Editor de Rotas - Versão 1")

st.title("🗺️ Editor de Rotas - Versão 1")

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

# Adicionar rotas KML convertidas para GeoJSON
if uploaded_kmls:
    for file in uploaded_kmls:
        kml_content = file.read()
        k = kml.KML()
        k.from_string(kml_content)
        # Percorrer os elementos do KML
        for doc in k.features():
            for placemark in doc.features():
                geom = placemark.geometry
                geojson = mapping(geom)
                folium.GeoJson(geojson, name=file.name).add_to(m)

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

