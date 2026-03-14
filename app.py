import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium

st.set_page_config(layout="wide", page_title="Editor de Rotas - Versão 1")

st.title("🗺️ Editor de Rotas - Versão 1")

# Upload dos arquivos
uploaded_kmls = st.file_uploader("Upload dos KMLs (rotas)", type=["kml"], accept_multiple_files=True)
uploaded_xlsx = st.file_uploader("Upload da relação de colaboradores (XLSX)", type=["xlsx"])

colaboradores = pd.DataFrame()
rotas = {}

if uploaded_xlsx:
    colaboradores = pd.read_excel(uploaded_xlsx)
    st.subheader("📊 Relação de colaboradores")
    st.dataframe(colaboradores)

if uploaded_kmls:
    st.subheader("📍 Rotas carregadas")
    for file in uploaded_kmls:
        st.write(f"- {file.name}")
        rotas[file.name] = file

# Mapa
st.subheader("🗺️ Visualização no mapa")
m = folium.Map(location=[-3.119, -60.021], zoom_start=12)

# Exibir colaboradores no mapa
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

st_folium(m, width=900, height=600)

# Resumo por rota
if not colaboradores.empty:
    st.subheader("📌 Resumo por rota")
    resumo = colaboradores.groupby("ROTA")["COLABORADORES"].count().reset_index()
    resumo.columns = ["Rota", "Qtd Colaboradores"]
    st.table(resumo)
