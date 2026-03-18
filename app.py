import streamlit as st
import pandas as pd
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from lxml import etree
import io
from simplekml import Kml

st.set_page_config(layout="wide", page_title="Editor de Rotas - Versão 3.1")

# Estado inicial
if "colaboradores" not in st.session_state:
    st.session_state["colaboradores"] = pd.DataFrame()
if "rotas" not in st.session_state:
    st.session_state["rotas"] = {}
if "selecionado" not in st.session_state:
    st.session_state["selecionado"] = None

# --- Barra lateral ---
st.sidebar.header("⚙️ Editor de Rotas")

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

with st.sidebar.expander("🛣️ Rotas disponíveis", expanded=False):
    rotas_selecionadas = []
    if st.session_state["rotas"]:
        todas = st.checkbox("Ativar/Desativar todas", value=True)
        for nome in st.session_state["rotas"].keys():
            if todas or st.checkbox(f"Mostrar rota {nome}", value=False):
                rotas_selecionadas.append(nome)

with st.sidebar.expander("📊 Resumo por rota", expanded=False):
    if not st.session_state["colaboradores"].empty:
        resumo = st.session_state["colaboradores"].groupby("ROTA")["COLABORADORES"].count().reset_index()
        resumo.columns = ["Rota", "Qtd Colaboradores"]
        st.table(resumo)

with st.sidebar.expander("✏️ Edição de rotas", expanded=False):
    if st.session_state["selecionado"]:
        st.write(f"Colaborador selecionado: {st.session_state['selecionado']}")
        nova_rota = st.selectbox("Nova rota", list(st.session_state["rotas"].keys()))
        if st.button("Transferir"):
            idx = st.session_state["colaboradores"][st.session_state["colaboradores"]["COLABORADORES"] == st.session_state["selecionado"]].index[0]
            st.session_state["colaboradores"].at[idx, "ROTA"] = nova_rota
            st.success(f"{st.session_state['selecionado']} transferido para {nova_rota}.")
            st.session_state["selecionado"] = None

# --- Mapa ---
m = folium.Map(location=[-3.119, -60.021], zoom_start=12)

for nome in rotas_selecionadas:
    for segmento in st.session_state["rotas"][nome]:
        folium.PolyLine(segmento, color="red", weight=3, opacity=0.8).add_to(m)

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
                    popup=row["COLABORADORES"],
                    icon=folium.Icon(color="blue", icon="user")
                ).add_to(cluster)
        except:
            pass

map_data = st_folium(m, height=600, width=1000)

# Captura clique no colaborador
if map_data and map_data.get("last_object_clicked"):
    st.session_state["selecionado"] = map_data["last_object_clicked"]["popup"]

# --- Exportação ---
st.subheader("📤 Exportar arquivos editados")
if not st.session_state["colaboradores"].empty:
    buffer = io.BytesIO()
    st.session_state["colaboradores"].to_excel(buffer, index=False, engine="openpyxl")
    st.download_button("Baixar XLSX atualizado", buffer.getvalue(), file_name="colaboradores_editados.xlsx")

    kml = Kml()
    for rota, segmentos in st.session_state["rotas"].items():
        for segmento in segmentos:
            ls = kml.newlinestring(name=rota, coords=[(lon, lat) for lat, lon in segmento])
            ls.style.linestyle.color = "ff0000ff"
            ls.style.linestyle.width = 3
    kml_buffer = io.BytesIO(kml.kml().encode("utf-8"))
    st.download_button("Baixar KML atualizado", kml_buffer.getvalue(), file_name="rotas_editadas.kml")

