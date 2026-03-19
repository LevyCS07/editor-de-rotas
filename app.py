import streamlit as st
import pandas as pd
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from lxml import etree
import math
import random

st.set_page_config(layout="wide", page_title="Visualizador de Rotas")

# -----------------------------
# UTIL
# -----------------------------
def gerar_cor():
    return "#{:06x}".format(random.randint(0, 0xFFFFFF))

def haversine(p1, p2):
    R = 6371
    lat1, lon1 = map(math.radians, p1)
    lat2, lon2 = map(math.radians, p2)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))

def ponto_mais_proximo(coord, stops):
    return min(stops, key=lambda s: haversine(coord, s)) if stops else None

def carregar_kml(file):
    parser = etree.XMLParser(resolve_entities=False)
    tree = etree.parse(file, parser)
    root = tree.getroot()

    ns = {"kml": "http://www.opengis.net/kml/2.2"}

    stops = []
    for c in root.xpath("//kml:Point/kml:coordinates", namespaces=ns):
        lon, lat, *_ = c.text.strip().split(",")
        stops.append((float(lat), float(lon)))

    segmentos = []
    for c in root.xpath("//kml:LineString/kml:coordinates", namespaces=ns):
        pontos = []
        for pair in c.text.strip().split():
            lon, lat, *_ = pair.split(",")
            pontos.append((float(lat), float(lon)))
        segmentos.append(pontos)

    return {"stops": stops, "segmentos": segmentos}

# -----------------------------
# MAPA
# -----------------------------
def criar_mapa():
    m = folium.Map(location=[-3.119, -60.021], zoom_start=12)
    visiveis = st.session_state["rotas_visiveis"]

    # LINHAS DAS ROTAS
    for rota, dados in st.session_state["rotas"].items():
        if rota not in visiveis:
            continue

        cor = st.session_state["cores_rotas"][rota]

        for seg in dados["segmentos"]:
            folium.PolyLine(seg, color=cor, weight=4).add_to(m)

    # COLABORADORES
    cluster = MarkerCluster().add_to(m)

    for _, row in st.session_state["colaboradores"].iterrows():
        if row["ROTA"] not in visiveis:
            continue

        folium.Marker(
            location=[row["LAT"], row["LONG"]],
            popup=f"{row['COLABORADORES']} ({row['ROTA']})",
            icon=folium.Icon(color="blue")
        ).add_to(cluster)

    return m

# -----------------------------
# STATE
# -----------------------------
defaults = {
    "colaboradores": pd.DataFrame(),
    "rotas": {},
    "cores_rotas": {},
    "rotas_visiveis": [],
    "mapa": None,
    "mapa_atualizado": True,
    "dados_processados": False
}

for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# -----------------------------
# UPLOAD
# -----------------------------
st.sidebar.header("📂 Upload")

xlsx = st.sidebar.file_uploader("Colaboradores", type=["xlsx"])
kmls = st.sidebar.file_uploader("Rotas (KML)", type=["kml"], accept_multiple_files=True)

if xlsx:
    st.session_state["colaboradores"] = pd.read_excel(xlsx)
    st.session_state["mapa_atualizado"] = True

if kmls:
    for f in kmls:
        nome = f.name.replace(".kml", "")
        st.session_state["rotas"][nome] = carregar_kml(f)

        if nome not in st.session_state["cores_rotas"]:
            st.session_state["cores_rotas"][nome] = gerar_cor()

    st.session_state["rotas_visiveis"] = list(st.session_state["rotas"].keys())
    st.session_state["mapa_atualizado"] = True

# -----------------------------
# FILTRO DE ROTAS
# -----------------------------
st.sidebar.header("👁️ Rotas visíveis")

vis = st.sidebar.multiselect(
    "Selecione rotas",
    list(st.session_state["rotas"].keys()),
    default=st.session_state["rotas_visiveis"]
)

if set(vis) != set(st.session_state["rotas_visiveis"]):
    st.session_state["rotas_visiveis"] = vis
    st.session_state["mapa_atualizado"] = True

# -----------------------------
# PAINEL DE CONTAGEM
# -----------------------------
st.sidebar.header("📊 Ocupação das rotas")

cont = {}
for _, r in st.session_state["colaboradores"].iterrows():
    cont[r["ROTA"]] = cont.get(r["ROTA"], 0) + 1

for r, q in cont.items():
    st.sidebar.write(f"{r}: {q} pessoas")

# -----------------------------
# MAPA
# -----------------------------
if st.session_state["mapa"] is None or st.session_state["mapa_atualizado"]:
    st.session_state["mapa"] = criar_mapa()
    st.session_state["mapa_atualizado"] = False

st.title("🗺️ Visualizador de Rotas")

st_folium(
    st.session_state["mapa"],
    width=1400,
    height=800,
    returned_objects=[]
)
