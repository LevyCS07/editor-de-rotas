import streamlit as st
import pandas as pd
import folium
from folium.plugins import MarkerCluster
from lxml import etree
from simplekml import Kml
import math
import io
import json

st.set_page_config(layout="wide", page_title="Editor de Rotas com Embarques")

# -----------------------------
# Funções auxiliares
# -----------------------------
def distancia(p1, p2):
    return math.sqrt((p1[0]-p2[0])**2 + (p1[1]-p2[1])**2)

def ponto_mais_proximo(colab_coord, stops):
    menor = None
    menor_dist = float("inf")
    for stop in stops:
        d = distancia(colab_coord, stop)
        if d < menor_dist:
            menor = stop
            menor_dist = d
    return menor

def carregar_kml(file):
    tree = etree.fromstring(file.read())
    ns = {"kml": "http://www.opengis.net/kml/2.2"}
    coords = tree.xpath("//kml:Point/kml:coordinates", namespaces=ns)
    stops = []
    for c in coords:
        lon, lat, *_ = c.text.strip().split(",")
        stops.append((float(lat), float(lon)))
    return stops

# -----------------------------
# Estado inicial
# -----------------------------
if "colaboradores" not in st.session_state:
    st.session_state["colaboradores"] = pd.DataFrame()
if "rotas" not in st.session_state:
    st.session_state["rotas"] = {}
if "embarques" not in st.session_state:
    st.session_state["embarques"] = {}
if "selecionado" not in st.session_state:
    st.session_state["selecionado"] = None

# -----------------------------
# Upload
# -----------------------------
st.sidebar.header("📂 Upload de arquivos")
uploaded_xlsx = st.sidebar.file_uploader("Upload XLSX (colaboradores)", type=["xlsx"])
uploaded_kmls = st.sidebar.file_uploader("Upload KMLs (rotas)", type=["kml"], accept_multiple_files=True)

if uploaded_xlsx:
    st.session_state["colaboradores"] = pd.read_excel(uploaded_xlsx, engine="openpyxl")

if uploaded_kmls:
    rotas = {}
    for file in uploaded_kmls:
        stops = carregar_kml(file)
        rotas[file.name.replace(".kml", "")] = {"stops": stops}
    st.session_state["rotas"] = rotas

# -----------------------------
# Correlação inicial
# -----------------------------
if not st.session_state["colaboradores"].empty and st.session_state["rotas"]:
    embarques = {}
    for _, row in st.session_state["colaboradores"].iterrows():
        rota_nome = row["ROTA"]
        colab_coord = (float(row["LAT"]), float(row["LONG"]))
        stops = st.session_state["rotas"][rota_nome]["stops"]
        embarque = ponto_mais_proximo(colab_coord, stops)
        if rota_nome not in embarques:
            embarques[rota_nome] = {}
        if embarque not in embarques[rota_nome]:
            embarques[rota_nome][embarque] = []
        embarques[rota_nome][embarque].append(row["COLABORADORES"])
    st.session_state["embarques"] = embarques

# -----------------------------
# Mapa
# -----------------------------
m = folium.Map(location=[-3.119, -60.021], zoom_start=12)

# Mostrar pontos de parada e embarques
for rota, stops_dict in st.session_state["embarques"].items():
    for stop, colabs in stops_dict.items():
        folium.Marker(
            location=[stop[0], stop[1]],
            popup=f"{rota}: {', '.join(colabs)}",
            icon=folium.Icon(color="green", icon="bus")
        ).add_to(m)

# Mostrar colaboradores
if not st.session_state["colaboradores"].empty:
    cluster = MarkerCluster().add_to(m)
    for _, row in st.session_state["colaboradores"].iterrows():
        lat, lon = float(row["LAT"]), float(row["LONG"])
        folium.Marker(
            location=[lat, lon],
            popup=row["COLABORADORES"],
            icon=folium.Icon(color="blue", icon="user")
        ).add_to(cluster)

map_data = st.map_input_widgets(m, key="mapa")

# -----------------------------
# Transferência
# -----------------------------
st.sidebar.header("✏️ Transferência de colaboradores")
if not st.session_state["colaboradores"].empty:
    colab_nome = st.sidebar.selectbox("Selecione colaborador", st.session_state["colaboradores"]["COLABORADORES"])
    nova_rota = st.sidebar.selectbox("Nova rota", list(st.session_state["rotas"].keys()))
    if st.sidebar.button("Transferir"):
        idx = st.session_state["colaboradores"][st.session_state["colaboradores"]["COLABORADORES"] == colab_nome].index[0]
        colab_coord = (float(st.session_state["colaboradores"].at[idx, "LAT"]),
                       float(st.session_state["colaboradores"].at[idx, "LONG"]))
        stops = st.session_state["rotas"][nova_rota]["stops"]
        embarque = ponto_mais_proximo(colab_coord, stops)

        if nova_rota not in st.session_state["embarques"]:
            st.session_state["embarques"][nova_rota] = {}
        if embarque not in st.session_state["embarques"][nova_rota]:
            st.session_state["embarques"][nova_rota][embarque] = []
        st.session_state["embarques"][nova_rota][embarque].append(colab_nome)

        st.session_state["colaboradores"].at[idx, "ROTA"] = nova_rota
        st.success(f"{colab_nome} transferido para {nova_rota}, embarque em {embarque}")

# -----------------------------
# Exportação
# -----------------------------
st.subheader("📤 Exportar arquivos editados")
if not st.session_state["colaboradores"].empty:
    buffer = io.BytesIO()
    st.session_state["colaboradores"].to_excel(buffer, index=False, engine="openpyxl")
    st.download_button("Baixar XLSX atualizado", buffer.getvalue(), file_name="colaboradores_editados.xlsx")

    kml = Kml()
    for rota, stops_dict in st.session_state["embarques"].items():
        for stop, colabs in stops_dict.items():
            pnt = kml.newpoint(name=f"{rota} - {', '.join(colabs)}", coords=[(stop[1], stop[0])])
            pnt.style.iconstyle.color = "ff0000ff"
    kml_buffer = io.BytesIO(kml.kml().encode("utf-8"))
    st.download_button("Baixar KML atualizado", kml_buffer.getvalue(), file_name="rotas_editadas.kml")
