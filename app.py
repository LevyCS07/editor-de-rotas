import streamlit as st
import pandas as pd
import folium
from folium.plugins import MarkerCluster
from lxml import etree
import requests

st.set_page_config(layout="wide", page_title="Editor de Rotas - Versão 2.3")

ORS_API_KEY = st.secrets["ORS_API_KEY"]

def recalcular_rota(pontos):
    """Chama a API da ORS para recalcular rota com base nos pontos"""
    url = "https://api.openrouteservice.org/v2/directions/driving-car"
    headers = {"Authorization": ORS_API_KEY, "Content-Type": "application/json"}
    body = {"coordinates": pontos}
    resp = requests.post(url, json=body, headers=headers)
    if resp.status_code == 200:
        return resp.json()
    else:
        st.error(f"Erro ao recalcular rota na ORS: {resp.text}")
        return None

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
        lines = tree.xpath("//kml:LineString/kml:coordinates", namespaces=ns)
        segmentos = []
        for line in lines:
            coord_text = line.text.strip()
            pontos = []
            for pair in coord_text.split():
                lon, lat, *_ = pair.split(",")
                pontos.append((float(lat), float(lon)))
            segmentos.append(pontos)
        rotas[file.name.replace(".kml", "")] = segmentos

# --- Controle de rotas ---
st.subheader("⚙️ Controle de rotas no mapa")
rotas_selecionadas = []
if rotas:
    todas = st.checkbox("Ativar/Desativar todas as rotas", value=True)
    for nome in rotas.keys():
        if todas or st.checkbox(f"Mostrar rota {nome}", value=False):
            rotas_selecionadas.append(nome)

    for nome in rotas_selecionadas:
        for segmento in rotas[nome]:
            folium.PolyLine(segmento, color="red", weight=3, opacity=0.8).add_to(m)

# --- Cluster de colaboradores ---
if not colaboradores.empty:
    cluster = MarkerCluster().add_to(m)
    for _, row in colaboradores.iterrows():
        try:
            lat = float(str(row["LAT"]).replace(",", "."))
            lon = float(str(row["LONG"]).replace(",", "."))
            rota = row["ROTA"]

            if rota in rotas_selecionadas or todas:
                folium.Marker(
                    location=[lat, lon],
                    popup=f"{row['COLABORADORES']} (Matrícula: {row['MATRÍCULA']}, Rota: {rota})",
                    icon=folium.Icon(color="blue", icon="user")
                ).add_to(cluster)
        except:
            pass

st.components.v1.html(m._repr_html_(), height=600)

# --- Transferência de colaboradores ---
if not colaboradores.empty and rotas:
    st.sidebar.subheader("🔄 Transferência de colaboradores")
    colab_escolhido = st.sidebar.selectbox("Selecione o colaborador", colaboradores["COLABORADORES"])
    nova_rota = st.sidebar.selectbox("Selecione a nova rota", list(rotas.keys()))

    if st.sidebar.button("Transferir"):
        idx = colaboradores[colaboradores["COLABORADORES"] == colab_escolhido].index[0]
        st.session_state["colaboradores"].at[idx, "ROTA"] = nova_rota
        st.success(f"Colaborador {colab_escolhido} transferido para rota {nova_rota}.")

# --- Resumo atualizado ---
if not colaboradores.empty:
    st.subheader("📌 Resumo por rota")
    resumo = colaboradores.groupby("ROTA")["COLABORADORES"].count().reset_index()
    resumo.columns = ["Rota", "Qtd Colaboradores"]
    st.table(resumo)



