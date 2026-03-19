import streamlit as st
import pandas as pd
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from lxml import etree
from simplekml import Kml
import math
import io

st.set_page_config(layout="wide", page_title="Editor de Rotas com Embarques")

# -----------------------------
# Funções auxiliares
# -----------------------------
def haversine(p1, p2):
    R = 6371  # km
    lat1, lon1 = map(math.radians, p1)
    lat2, lon2 = map(math.radians, p2)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def ponto_mais_proximo(colab_coord, stops):
    menor = None
    menor_dist = float("inf")
    for stop in stops:
        d = haversine(colab_coord, stop)
        if d < menor_dist:
            menor = stop
            menor_dist = d
    return menor

def carregar_kml(file):
    parser = etree.XMLParser(resolve_entities=False)
    tree = etree.parse(file, parser)
    root = tree.getroot()

    ns = {"kml": "http://www.opengis.net/kml/2.2"}
    
    coords_points = root.xpath("//kml:Point/kml:coordinates", namespaces=ns)
    stops = []
    for c in coords_points:
        lon, lat, *_ = c.text.strip().split(",")
        stops.append((float(lat), float(lon)))
    
    coords_lines = root.xpath("//kml:LineString/kml:coordinates", namespaces=ns)
    segmentos = []
    for c in coords_lines:
        pontos = []
        for pair in c.text.strip().split():
            lon, lat, *_ = pair.split(",")
            pontos.append((float(lat), float(lon)))
        segmentos.append(pontos)
    
    return {"stops": stops, "segmentos": segmentos}

def remover_colaborador(nome):
    for rota, stops in st.session_state["embarques"].items():
        for stop in stops:
            if nome in stops[stop]:
                stops[stop].remove(nome)

# -----------------------------
# Estado inicial
# -----------------------------
if "colaboradores" not in st.session_state:
    st.session_state["colaboradores"] = pd.DataFrame()
if "rotas" not in st.session_state:
    st.session_state["rotas"] = {}
if "embarques" not in st.session_state:
    st.session_state["embarques"] = {}

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
        dados = carregar_kml(file)
        nome = file.name.replace(".kml", "")
        rotas[nome] = dados
    st.session_state["rotas"] = rotas

# -----------------------------
# Correlação inicial
# -----------------------------
if not st.session_state["colaboradores"].empty and st.session_state["rotas"]:
    embarques = {}

    for row in st.session_state["colaboradores"].itertuples():
        rota_nome = getattr(row, "ROTA")
        
        if rota_nome not in st.session_state["rotas"]:
            continue

        colab_coord = (float(getattr(row, "LAT")), float(getattr(row, "LONG")))
        stops = st.session_state["rotas"][rota_nome]["stops"]

        if not stops:
            continue

        embarque = ponto_mais_proximo(colab_coord, stops)

        embarques.setdefault(rota_nome, {})
        embarques[rota_nome].setdefault(embarque, [])
        embarques[rota_nome][embarque].append(getattr(row, "COLABORADORES"))

    st.session_state["embarques"] = embarques

# -----------------------------
# Mapa
# -----------------------------
m = folium.Map(location=[-3.119, -60.021], zoom_start=12)

for rota, dados in st.session_state["rotas"].items():
    for segmento in dados["segmentos"]:
        folium.PolyLine(segmento, color="red", weight=3).add_to(m)

for rota, stops_dict in st.session_state["embarques"].items():
    for stop, colabs in stops_dict.items():
        folium.Marker(
            location=[stop[0], stop[1]],
            popup=f"{rota}: {', '.join(colabs)}",
            icon=folium.Icon(color="green", icon="bus")
        ).add_to(m)

if not st.session_state["colaboradores"].empty:
    cluster = MarkerCluster().add_to(m)
    for row in st.session_state["colaboradores"].itertuples():
        lat, lon = float(row.LAT), float(row.LONG)
        folium.Marker(
            location=[lat, lon],
            popup=row.COLABORADORES,
            icon=folium.Icon(color="blue")
        ).add_to(cluster)

st.title("Mapa de Rotas e Embarques")
st_folium(m, width=1000, height=600)

# -----------------------------
# Transferência
# -----------------------------
st.sidebar.header("✏️ Transferência de colaboradores")

if not st.session_state["colaboradores"].empty:
    nomes = st.session_state["colaboradores"]["COLABORADORES"].tolist()

    colab_nome = st.sidebar.selectbox("Selecione colaborador", nomes)
    nova_rota = st.sidebar.selectbox("Nova rota", list(st.session_state["rotas"].keys()))

    if st.sidebar.button("Transferir"):
        df = st.session_state["colaboradores"]
        idx_list = df[df["COLABORADORES"] == colab_nome].index

        if len(idx_list) == 0:
            st.warning("Colaborador não encontrado")
        else:
            idx = idx_list[0]

            colab_coord = (float(df.at[idx, "LAT"]), float(df.at[idx, "LONG"]))
            stops = st.session_state["rotas"][nova_rota]["stops"]

            if not stops:
                st.warning("Rota sem pontos de parada")
            else:
                remover_colaborador(colab_nome)

                embarque = ponto_mais_proximo(colab_coord, stops)

                st.session_state["embarques"].setdefault(nova_rota, {})
                st.session_state["embarques"][nova_rota].setdefault(embarque, [])
                st.session_state["embarques"][nova_rota][embarque].append(colab_nome)

                df.at[idx, "ROTA"] = nova_rota

                st.success(f"{colab_nome} transferido para {nova_rota}")

# -----------------------------
# Exportação
# -----------------------------
st.subheader("📤 Exportar arquivos editados")

if not st.session_state["colaboradores"].empty:
    buffer = io.BytesIO()
    st.session_state["colaboradores"].to_excel(buffer, index=False, engine="openpyxl")

    st.download_button(
        "Baixar XLSX atualizado",
        buffer.getvalue(),
        file_name="colaboradores_editados.xlsx"
    )

    kml = Kml()

    for rota, stops_dict in st.session_state["embarques"].items():
        for stop, colabs in stops_dict.items():
            kml.newpoint(
                name=f"{rota} - {', '.join(colabs)}",
                coords=[(stop[1], stop[0])]
            )

    kml_buffer = io.BytesIO(kml.kml().encode("utf-8"))

    st.download_button(
        "Baixar KML atualizado",
        kml_buffer.getvalue(),
        file_name="rotas_editadas.kml"
    )
