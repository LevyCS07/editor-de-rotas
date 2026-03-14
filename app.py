import streamlit as st
import pandas as pd
import folium
from lxml import etree

st.set_page_config(layout="wide", page_title="Editor de Rotas - Versão 2")

st.title("🗺️ Editor de Rotas - Versão 2")

uploaded_kmls = st.file_uploader("Upload dos KMLs (rotas)", type=["kml"], accept_multiple_files=True)
uploaded_xlsx = st.file_uploader("Upload da relação de colaboradores (XLSX)", type=["xlsx"])

# Estado persistente
if "colaboradores" not in st.session_state:
    st.session_state["colaboradores"] = pd.DataFrame()

if uploaded_xlsx:
    st.session_state["colaboradores"] = pd.read_excel(uploaded_xlsx, engine="openpyxl")

colaboradores = st.session_state["colaboradores"]

if not colaboradores.empty:
    st.subheader("📊 Relação de colaboradores")
    st.dataframe(colaboradores)

# Criar mapa
st.subheader("🗺️ Visualização no mapa")
m = folium.Map(location=[-3.119, -60.021], zoom_start=12)

# Adicionar rotas KML
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
                points.append((float(lat), float(lon)))
            folium.PolyLine(points, color="red", weight=3, opacity=0.8).add_to(m)
        rotas.append(file.name.replace(".kml", ""))

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

st.components.v1.html(m._repr_html_(), height=600)

# Resumo por rota
if not colaboradores.empty:
    st.subheader("📌 Resumo por rota")
    resumo = colaboradores.groupby("ROTA")["COLABORADORES"].count().reset_index()
    resumo.columns = ["Rota", "Qtd Colaboradores"]
    st.table(resumo)

# --- Transferência de colaboradores ---
if not colaboradores.empty and rotas:
    st.subheader("🔄 Transferência de colaboradores entre rotas")

    colab_escolhido = st.selectbox("Selecione o colaborador", colaboradores["COLABORADORES"])
    nova_rota = st.selectbox("Selecione a nova rota", rotas)

    if st.button("Transferir"):
        idx = colaboradores[colaboradores["COLABORADORES"] == colab_escolhido].index[0]
        st.session_state["colaboradores"].at[idx, "ROTA"] = nova_rota
        st.success(f"Colaborador {colab_escolhido} transferido para rota {nova_rota}.")

