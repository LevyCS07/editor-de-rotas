import streamlit as st
import pandas as pd
import folium
from folium.plugins import MarkerCluster
from lxml import etree
import requests
import io

st.set_page_config(layout="wide", page_title="Editor de Rotas - Versão 3")

ORS_API_KEY = st.secrets.get("ORS_API_KEY", "")

# Função para recalcular rota via ORS
def recalcular_rota(pontos):
    url = "https://api.openrouteservice.org/v2/directions/driving-car"
    headers = {"Authorization": ORS_API_KEY, "Content-Type": "application/json"}
    body = {"coordinates": pontos}
    resp = requests.post(url, json=body, headers=headers)
    if resp.status_code == 200:
        return resp.json()
    else:
        st.error(f"Erro ao recalcular rota na ORS: {resp.text}")
        return None

# Estado inicial
if "colaboradores" not in st.session_state:
    st.session_state["colaboradores"] = pd.DataFrame()
if "rotas" not in st.session_state:
    st.session_state["rotas"] = {}

# --- Barra lateral ---
st.sidebar.header("⚙️ Editor de Rotas")

# Upload
with st.sidebar.expander("📂 Upload de arquivos", expanded=True):
    uploaded_kmls = st.file_uploader("Upload dos KMLs", type=["kml"], accept_multiple_files=True)
    uploaded_xlsx = st.file_uploader("Upload da relação de colaboradores (XLSX)", type=["xlsx"])

    if uploaded_xlsx:
        st.session_state["colaboradores"] = pd.read_excel(uploaded_xlsx, engine="openpyxl")

    if uploaded_kmls:
        rotas = {}
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
        st.session_state["rotas"] = rotas

# Controle de rotas
with st.sidebar.expander("🛣️ Rotas disponíveis", expanded=False):
    rotas_selecionadas = []
    if st.session_state["rotas"]:
        todas = st.checkbox("Ativar/Desativar todas", value=True)
        for nome in st.session_state["rotas"].keys():
            if todas or st.checkbox(f"Mostrar rota {nome}", value=False):
                rotas_selecionadas.append(nome)

# Resumo
with st.sidebar.expander("📊 Resumo por rota", expanded=False):
    if not st.session_state["colaboradores"].empty:
        resumo = st.session_state["colaboradores"].groupby("ROTA")["COLABORADORES"].count().reset_index()
        resumo.columns = ["Rota", "Qtd Colaboradores"]
        st.table(resumo)

# Edição
with st.sidebar.expander("✏️ Edição de rotas", expanded=False):
    if not st.session_state["colaboradores"].empty and st.session_state["rotas"]:
        colab_escolhido = st.selectbox("Selecione o colaborador", st.session_state["colaboradores"]["COLABORADORES"])
        nova_rota = st.selectbox("Selecione a nova rota", list(st.session_state["rotas"].keys()))
        if st.button("Transferir"):
            idx = st.session_state["colaboradores"][st.session_state["colaboradores"]["COLABORADORES"] == colab_escolhido].index[0]
            st.session_state["colaboradores"].at[idx, "ROTA"] = nova_rota
            st.success(f"Colaborador {colab_escolhido} transferido para rota {nova_rota}.")

# --- Mapa ---
m = folium.Map(location=[-3.119, -60.021], zoom_start=12)

# Rotas
for nome in rotas_selecionadas:
    for segmento in st.session_state["rotas"][nome]:
        folium.PolyLine(segmento, color="red", weight=3, opacity=0.8).add_to(m)

# Colaboradores com cluster
if not st.session_state["colaboradores"].empty:
    cluster = MarkerCluster().add_to(m)
    for _, row in st.session_state["colaboradores"].iterrows():
        try:
            lat = float(str(row["LAT"]).replace(",", "."))
            lon = float(str(row["LONG"]).replace(",", "."))
            rota = row["ROTA"]
            if rota in rotas_selecionadas or (rotas_selecionadas == []):
                folium.Marker(
                    location=[lat, lon],
                    popup=f"{row['COLABORADORES']} (Matrícula: {row['MATRÍCULA']}, Rota: {rota})",
                    icon=folium.Icon(color="blue", icon="user")
                ).add_to(cluster)
        except:
            pass

st.components.v1.html(m._repr_html_(), height=600)

# --- Exportação ---
st.subheader("📤 Exportar arquivos editados")
if not st.session_state["colaboradores"].empty:
    # Exportar XLSX
    buffer = io.BytesIO()
    st.session_state["colaboradores"].to_excel(buffer, index=False, engine="openpyxl")
    st.download_button("Baixar XLSX atualizado", buffer.getvalue(), file_name="colaboradores_editados.xlsx")

    # Exportar KML (simplificado)
    from simplekml import Kml
    kml = Kml()
    for rota, segmentos in st.session_state["rotas"].items():
        for segmento in segmentos:
            ls = kml.newlinestring(name=rota, coords=[(lon, lat) for lat, lon in segmento])
            ls.style.linestyle.color = "ff0000ff"
            ls.style.linestyle.width = 3
    kml_buffer = io.BytesIO(kml.kml().encode("utf-8"))
    st.download_button("Baixar KML atualizado", kml_buffer.getvalue(), file_name="rotas_editadas.kml")
