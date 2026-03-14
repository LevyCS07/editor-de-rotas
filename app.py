import streamlit as st
import pandas as pd
import folium
import requests
from lxml import etree

st.set_page_config(layout="wide", page_title="Editor de Rotas - Versão 2")

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

rotas = []
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
                points.append([float(lon), float(lat)])
            folium.PolyLine([(lat, lon) for lon, lat in points], color="red").add_to(m)
        rotas.append(file.name.replace(".kml", ""))

# Adicionar colaboradores com popup interativo
if not colaboradores.empty:
    for _, row in colaboradores.iterrows():
        try:
            lat = float(str(row["LAT"]).replace(",", "."))
            lon = float(str(row["LONG"]).replace(",", "."))
            rota_atual = row["ROTA"]

            # Popup HTML com select de rotas
            html_popup = f"""
            <b>{row['COLABORADORES']}</b><br>
            Matrícula: {row['MATRÍCULA']}<br>
            Rota atual: {rota_atual}<br>
            <form action="" method="get">
                <label>Transferir para:</label><br>
                <select name="rota">
                    {''.join([f'<option value="{r}">{r}</option>' for r in rotas])}
                </select><br><br>
                <input type="submit" value="Transferir">
            </form>
            """

            folium.Marker(
                location=[lat, lon],
                popup=folium.Popup(html_popup, max_width=250),
                icon=folium.Icon(color="blue", icon="user")
            ).add_to(m)
        except:
            pass

st.components.v1.html(m._repr_html_(), height=600)

# Resumo atualizado
if not colaboradores.empty:
    st.subheader("📌 Resumo por rota")
    resumo = colaboradores.groupby("ROTA")["COLABORADORES"].count().reset_index()
    resumo.columns = ["Rota", "Qtd Colaboradores"]
    st.table(resumo)

