import streamlit as st
import pandas as pd
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from lxml import etree
from simplekml import Kml
import math
import io
import random

st.set_page_config(layout="wide", page_title="Editor de Rotas com Embarques")

# -----------------------------
# CORES POR ROTA
# -----------------------------
def gerar_cor():
    return "#{:06x}".format(random.randint(0, 0xFFFFFF))

# -----------------------------
# Funções auxiliares
# -----------------------------
def haversine(p1, p2):
    R = 6371
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
# MAPA
# -----------------------------
def criar_mapa():
    m = folium.Map(location=[-3.119, -60.021], zoom_start=12)

    rotas_visiveis = st.session_state.get("rotas_visiveis", [])

    for rota, dados in st.session_state["rotas"].items():
        if rota not in rotas_visiveis:
            continue

        cor = st.session_state["cores_rotas"].get(rota, "#FF0000")

        for segmento in dados["segmentos"]:
            folium.PolyLine(segmento, color=cor, weight=4).add_to(m)

    for rota, stops_dict in st.session_state["embarques"].items():
        if rota not in rotas_visiveis:
            continue

        for stop, colabs in stops_dict.items():
            folium.Marker(
                location=[stop[0], stop[1]],
                popup=f"{rota}: {', '.join(colabs)}",
                icon=folium.Icon(color="green", icon="bus")
            ).add_to(m)

    if not st.session_state["colaboradores"].empty:
        cluster = MarkerCluster().add_to(m)

        for row in st.session_state["colaboradores"].itertuples():
            if row.ROTA not in rotas_visiveis:
                continue

            folium.Marker(
                location=[row.LAT, row.LONG],
                popup=f"{row.COLABORADORES} ({row.ROTA})",
                icon=folium.Icon(color="blue")
            ).add_to(cluster)

    return m

# -----------------------------
# ESTADO
# -----------------------------
for key, default in {
    "colaboradores": pd.DataFrame(),
    "rotas": {},
    "embarques": {},
    "mapa": None,
    "mapa_atualizado": True,
    "rotas_visiveis": [],
    "cores_rotas": {},
    "modo_transferencia": False
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# -----------------------------
# SIDEBAR
# -----------------------------
st.sidebar.header("📂 Upload")

xlsx = st.sidebar.file_uploader("Colaboradores", type=["xlsx"])
kmls = st.sidebar.file_uploader("Rotas", type=["kml"], accept_multiple_files=True)

if xlsx:
    st.session_state["colaboradores"] = pd.read_excel(xlsx)
    st.session_state["mapa_atualizado"] = True

if kmls:
    rotas = {}
    cores = {}
    for f in kmls:
        nome = f.name.replace(".kml", "")
        rotas[nome] = carregar_kml(f)
        cores[nome] = gerar_cor()

    st.session_state["rotas"] = rotas
    st.session_state["cores_rotas"] = cores
    st.session_state["rotas_visiveis"] = list(rotas.keys())
    st.session_state["mapa_atualizado"] = True

# -----------------------------
# FILTRO ROTAS
# -----------------------------
st.sidebar.header("👁️ Rotas visíveis")

visiveis = st.sidebar.multiselect(
    "Rotas",
    list(st.session_state["rotas"].keys()),
    default=st.session_state["rotas_visiveis"]
)

if set(visiveis) != set(st.session_state["rotas_visiveis"]):
    st.session_state["rotas_visiveis"] = visiveis
    st.session_state["mapa_atualizado"] = True

# -----------------------------
# BOTÃO TRANSFERÊNCIA
# -----------------------------
st.sidebar.header("⚡ Modo")

if st.sidebar.button("TRANSFERÊNCIA ON/OFF"):
    st.session_state["modo_transferencia"] = not st.session_state["modo_transferencia"]

st.sidebar.write("Status:", "🟢 ON" if st.session_state["modo_transferencia"] else "🔴 OFF")

# -----------------------------
# PAINEL DE ROTAS
# -----------------------------
st.sidebar.header("📊 Ocupação das rotas")

contagem = {}
for _, row in st.session_state["colaboradores"].iterrows():
    contagem[row["ROTA"]] = contagem.get(row["ROTA"], 0) + 1

for rota, qtd in contagem.items():
    st.sidebar.write(f"{rota}: {qtd} pessoas")

# -----------------------------
# MAPA GRANDE
# -----------------------------
if st.session_state["mapa"] is None or st.session_state["mapa_atualizado"]:
    st.session_state["mapa"] = criar_mapa()
    st.session_state["mapa_atualizado"] = False

st.title("Mapa de Rotas")
map_data = st_folium(
    st.session_state["mapa"],
    width=1400,
    height=800,
    returned_objects=["last_clicked"]
)

# -----------------------------
# CLIQUE NO MAPA (BASE)
# -----------------------------
if st.session_state["modo_transferencia"] and map_data["last_clicked"]:
    lat = map_data["last_clicked"]["lat"]
    lon = map_data["last_clicked"]["lng"]

    st.write(f"📍 Clique detectado: {lat}, {lon}")
