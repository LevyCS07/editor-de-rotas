import html
import io
import json
import math
import os
import urllib.parse

import folium
import numpy as np
import openrouteservice
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from lxml import etree
from shapely.geometry import Point, shape
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from streamlit_folium import st_folium


# ============================================================
# CONFIGURACOES
# ============================================================
TAXA_MINIMA = 0.60
MAX_TEMPO_MIN = 90
MAX_WAYPOINTS = 48
VELOCIDADE_MEDIA_KMH = 28

GEOJSON_PATH = os.path.join(os.path.dirname(__file__), "BAIRROS_MANAUS.geojson")

st.set_page_config(page_title="Roteamento Inteligente", page_icon="🚌", layout="wide")

ORS_API_KEY = st.secrets.get("ORS_API_KEY")
if not ORS_API_KEY:
    st.error("Configure `ORS_API_KEY` em `st.secrets` antes de gerar rotas.")
    st.stop()


# ============================================================
# ESTILO
# ============================================================
st.markdown(
    """
<style>
.alerta-box {
    background:#fff3cd;border-left:4px solid #ffc107;
    padding:.75rem 1rem;border-radius:4px;margin:.4rem 0;
}
.erro-box {
    background:#f8d7da;border-left:4px solid #dc3545;
    padding:.75rem 1rem;border-radius:4px;margin:.4rem 0;
}
</style>
""",
    unsafe_allow_html=True,
)


# ============================================================
# FUNCOES AUXILIARES
# ============================================================
def htxt(value):
    return html.escape(str(value), quote=True)


def colunas_tipo(tipo_rota):
    return ("LAT E", "LONG E") if tipo_rota == "Entrada" else ("LAT S", "LONG S")


def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def dist_bairros(bairros, id_a, id_b):
    ba = bairros[id_a]
    bb = bairros[id_b]
    return haversine(
        ba["centroid_lat"],
        ba["centroid_lon"],
        bb["centroid_lat"],
        bb["centroid_lon"],
    )


def estimar_tempo_local_min(waypoints, destino):
    if not waypoints:
        return 0
    total_km = 0
    anterior = waypoints[0]
    for coord in waypoints[1:]:
        total_km += haversine(anterior[0], anterior[1], coord[0], coord[1])
        anterior = coord
    total_km += haversine(anterior[0], anterior[1], destino[0], destino[1])
    return total_km / VELOCIDADE_MEDIA_KMH * 60


@st.cache_data(show_spinner=False)
def carregar_bairros():
    with open(GEOJSON_PATH, "r", encoding="utf-8") as f:
        geojson = json.load(f)
    bairros = []
    for feat in geojson["features"]:
        props = feat.get("properties", {})
        nome = props.get("NM_BAIRRO") or props.get("nome") or props.get("name") or f"B{len(bairros)}"
        geom = shape(feat["geometry"])
        centroid = geom.centroid
        bairros.append(
            {
                "idx": len(bairros),
                "nome": str(nome),
                "geometry": geom,
                "centroid_lat": centroid.y,
                "centroid_lon": centroid.x,
            }
        )
    return bairros


def atribuir_bairro(lat, lon, bairros):
    pt = Point(lon, lat)
    for b in bairros:
        if b["geometry"].contains(pt):
            return b["idx"], b["nome"]
    melhor = min(bairros, key=lambda b: haversine(lat, lon, b["centroid_lat"], b["centroid_lon"]))
    return melhor["idx"], melhor["nome"]


def estimar_tempo_ors(client, waypoints, destino):
    coords = [[w[1], w[0]] for w in waypoints]
    coords.append([destino[1], destino[0]])
    if len(coords) > MAX_WAYPOINTS:
        return None, False, "limite_waypoints"
    try:
        res = client.directions(
            coordinates=coords,
            profile="driving-car",
            optimize_waypoints=True,
            format="geojson",
        )
        return res["features"][0]["properties"]["summary"]["duration"] / 60, True, None
    except Exception as exc:
        return None, False, str(exc)


def gerar_kml(grupo_df, coords_rota, destino_final, nome_rota, tipo):
    kml_root = etree.Element("kml", xmlns="http://www.opengis.net/kml/2.2")
    doc = etree.SubElement(kml_root, "Document")
    etree.SubElement(doc, "name").text = f"{nome_rota} ({tipo})"

    col_lat, col_lon = colunas_tipo(tipo)

    for _, row in grupo_df.iterrows():
        pm = etree.SubElement(doc, "Placemark")
        etree.SubElement(pm, "name").text = str(row["COLABORADOR"])
        pt = etree.SubElement(pm, "Point")
        etree.SubElement(pt, "coordinates").text = f"{row[col_lon]},{row[col_lat]},0"

    pm_d = etree.SubElement(doc, "Placemark")
    etree.SubElement(pm_d, "name").text = "Destino Final"
    etree.SubElement(etree.SubElement(pm_d, "Point"), "coordinates").text = (
        f"{destino_final[1]},{destino_final[0]},0"
    )

    linha = etree.SubElement(doc, "Placemark")
    etree.SubElement(linha, "name").text = f"Trajeto {nome_rota} ({tipo})"
    style = etree.SubElement(linha, "Style")
    ls = etree.SubElement(style, "LineStyle")
    etree.SubElement(ls, "color").text = "ff0000ff"
    etree.SubElement(ls, "width").text = "4"
    ls_str = etree.SubElement(linha, "LineString")
    etree.SubElement(ls_str, "tessellate").text = "1"
    etree.SubElement(ls_str, "coordinates").text = " ".join([f"{c[0]},{c[1]},0" for c in coords_rota])

    buf = io.BytesIO()
    etree.ElementTree(kml_root).write(buf, pretty_print=True, xml_declaration=True, encoding="UTF-8")
    buf.seek(0)
    return buf


# ============================================================
# ALGORITMO
# ============================================================
def _nome_rota(bairros_nomes, idx):
    if not bairros_nomes:
        return f"ROTA_{idx + 1:02d}"
    return f"ROTA_{idx + 1:02d} - {' / '.join(bairros_nomes[:2])}"


def clusterizar_por_bairros(df, destino, capacidades, client, bairros, tipo_rota):
    df = df.copy().reset_index(drop=True)
    n_rotas = len(capacidades)
    alertas = []
    lat_col, lon_col = colunas_tipo(tipo_rota)

    df["STATUS_ROTA"] = "pendente"
    df["MOTIVO_SEM_ROTA"] = ""

    b_idxs, b_nomes = [], []
    for _, row in df.iterrows():
        bi, bn = atribuir_bairro(float(row[lat_col]), float(row[lon_col]), bairros)
        b_idxs.append(bi)
        b_nomes.append(bn)

    df["BAIRRO_IDX"] = b_idxs
    df["BAIRRO_NOME"] = b_nomes
    df["DIST_KM"] = df.apply(lambda r: haversine(r[lat_col], r[lon_col], destino[0], destino[1]), axis=1)

    contagem = df.groupby("BAIRRO_IDX").size().to_dict()
    cap_ref = int(np.mean(capacidades))
    min_grupo = max(1, int(cap_ref * TAXA_MINIMA))
    grupos = [[b] for b in contagem]

    def tam(g):
        return sum(contagem.get(b, 0) for b in g)

    def dist_g(g1, g2):
        dists = []
        for a in g1:
            for b in g2:
                try:
                    dists.append(dist_bairros(bairros, a, b))
                except Exception:
                    dists.append(999.0)
        return min(dists) if dists else 999.0

    for _ in range(100):
        pequenos = [g for g in grupos if tam(g) < min_grupo]
        if not pequenos:
            break
        g_p = pequenos[0]
        outros = [g for g in grupos if g is not g_p]
        if not outros:
            break
        candidatos = [g for g in outros if tam(g) + tam(g_p) <= cap_ref * 1.5]
        alvo = min(candidatos or outros, key=lambda g: dist_g(g_p, g))
        grupos = [g for g in grupos if g is not g_p and g is not alvo]
        grupos.append(g_p + alvo)

    while len(grupos) > n_rotas:
        menor_d, par = float("inf"), (0, 1)
        for i in range(len(grupos)):
            for j in range(i + 1, len(grupos)):
                d = dist_g(grupos[i], grupos[j])
                if d < menor_d:
                    menor_d, par = d, (i, j)
        i, j = par
        merged = grupos[i] + grupos[j]
        grupos = [g for k, g in enumerate(grupos) if k not in (i, j)]
        grupos.append(merged)

    while len(grupos) < n_rotas:
        grupos.append([])

    df["GRUPO_ROTA"] = -1
    for ri, grupo in enumerate(grupos):
        df.loc[df["BAIRRO_IDX"].isin(grupo), "GRUPO_ROTA"] = ri

    df["CLUSTER_FINAL"] = df["GRUPO_ROTA"].copy()
    proximos_clusters = len(grupos)
    criou_rota_extra = False

    for ri, cap in enumerate(capacidades):
        idxs_grupo = df[df["GRUPO_ROTA"] == ri].index.tolist()
        if len(idxs_grupo) <= cap:
            continue
        n_sub = math.ceil(len(idxs_grupo) / cap)
        coords_s = df.loc[idxs_grupo, [lat_col, lon_col]].values
        scaler = StandardScaler()
        km = KMeans(n_clusters=n_sub, random_state=42, n_init=10)
        sub_labels = km.fit_predict(scaler.fit_transform(coords_s))

        for sub_id in range(n_sub):
            sub_idxs = [idxs_grupo[k] for k, s in enumerate(sub_labels) if s == sub_id]
            novo_id = ri if sub_id == 0 else proximos_clusters
            if sub_id > 0:
                criou_rota_extra = True
                proximos_clusters += 1
            df.loc[sub_idxs, "CLUSTER_FINAL"] = novo_id

    if criou_rota_extra:
        alertas.append({"tipo": "rota_extra"})

    rotas = []
    atribuidos = set()
    clusters_ids = sorted([c for c in df["CLUSTER_FINAL"].unique() if c >= 0])

    cap_map = {}
    for c in clusters_ids:
        rota_orig = df[df["CLUSTER_FINAL"] == c]["GRUPO_ROTA"].mode()
        ri = int(rota_orig.iloc[0]) if not rota_orig.empty else 0
        cap_map[c] = capacidades[ri] if ri < len(capacidades) else capacidades[-1]

    for cluster_id in clusters_ids:
        cap = cap_map[cluster_id]
        cluster_df = df[df["CLUSTER_FINAL"] == cluster_id].copy()
        if cluster_df.empty:
            continue

        nomes_bairros = cluster_df["BAIRRO_NOME"].unique().tolist()
        cluster_df = cluster_df.sort_values("DIST_KM", ascending=False)
        membros_idx = []
        membros_coords = []

        for idx, row in cluster_df.iterrows():
            if len(membros_idx) >= cap:
                df.loc[idx, ["STATUS_ROTA", "MOTIVO_SEM_ROTA"]] = ["sem_rota", "excedeu_capacidade"]
                continue

            coord_nova = (float(row[lat_col]), float(row[lon_col]))
            teste_coords = membros_coords + [coord_nova]

            if len(teste_coords) >= 2:
                tempo_local = estimar_tempo_local_min(teste_coords, destino)
                if tempo_local > MAX_TEMPO_MIN * 1.35:
                    df.loc[idx, ["STATUS_ROTA", "MOTIVO_SEM_ROTA"]] = ["sem_rota", "tempo_estimado_local"]
                    alertas.append(
                        {
                            "tipo": "tempo",
                            "rota": cluster_id + 1,
                            "colaborador": row["COLABORADOR"],
                            "tempo_est": round(tempo_local, 1),
                            "fonte": "estimativa local",
                        }
                    )
                    continue

                t, ok, motivo = estimar_tempo_ors(client, teste_coords, destino)
                if motivo == "limite_waypoints":
                    df.loc[idx, ["STATUS_ROTA", "MOTIVO_SEM_ROTA"]] = ["sem_rota", "limite_waypoints_ors"]
                    alertas.append({"tipo": "waypoints", "rota": cluster_id + 1, "limite": MAX_WAYPOINTS})
                    continue
                if ok and t is not None and t > MAX_TEMPO_MIN:
                    df.loc[idx, ["STATUS_ROTA", "MOTIVO_SEM_ROTA"]] = ["sem_rota", "excedeu_tempo_ors"]
                    alertas.append(
                        {
                            "tipo": "tempo",
                            "rota": cluster_id + 1,
                            "colaborador": row["COLABORADOR"],
                            "tempo_est": round(t, 1),
                            "fonte": "ORS",
                        }
                    )
                    continue

            membros_idx.append(idx)
            membros_coords.append(coord_nova)
            atribuidos.add(idx)
            df.loc[idx, ["STATUS_ROTA", "MOTIVO_SEM_ROTA"]] = ["atribuido", ""]

        taxa = len(membros_idx) / cap if cap > 0 else 0

        if taxa < TAXA_MINIMA and membros_idx:
            alertas.append(
                {
                    "tipo": "taxa",
                    "rota": cluster_id + 1,
                    "membros": len(membros_idx),
                    "capacidade": cap,
                    "taxa": round(taxa * 100, 1),
                    "bairros": nomes_bairros,
                }
            )

        for bairro in nomes_bairros:
            colab_bairro = cluster_df[cluster_df["BAIRRO_NOME"] == bairro]
            if len(colab_bairro) == 1:
                alertas.append(
                    {
                        "tipo": "isolado_bairro",
                        "colaborador": colab_bairro["COLABORADOR"].values[0],
                        "bairro": bairro,
                    }
                )

        if membros_idx:
            rotas.append(
                {
                    "rota_id": cluster_id + 1,
                    "indices": membros_idx,
                    "capacidade": cap,
                    "ocupacao": len(membros_idx),
                    "taxa": round(taxa * 100, 1),
                    "bairros": nomes_bairros,
                    "nome_rota": _nome_rota(nomes_bairros, cluster_id),
                }
            )

    nao_atribuidos = df[df["STATUS_ROTA"] != "atribuido"]
    return rotas, nao_atribuidos, alertas, df


def gerar_rota_ors_ou_linha(client, grupo_df, destino_final, tipo):
    col_lat, col_lon = colunas_tipo(tipo)
    wpts = list(zip(grupo_df[col_lat], grupo_df[col_lon]))
    c_ors = [[w[1], w[0]] for w in wpts]
    c_ors.append([destino_final[1], destino_final[0]])
    if len(c_ors) > MAX_WAYPOINTS:
        return [[lon, lat] for lat, lon in wpts] + [[destino_final[1], destino_final[0]]], "limite_waypoints"
    try:
        res = client.directions(
            coordinates=c_ors,
            profile="driving-car",
            optimize_waypoints=True,
            format="geojson",
        )
        return res["features"][0]["geometry"]["coordinates"], None
    except Exception as exc:
        return [[lon, lat] for lat, lon in wpts] + [[destino_final[1], destino_final[0]]], str(exc)


# ============================================================
# INTERFACE
# ============================================================
st.title("🚌 Roteamento Inteligente de Colaboradores")
st.caption("Agrupamento automatico por bairros de Manaus + afunilamento ao destino")

if not os.path.exists(GEOJSON_PATH):
    st.error(
        f"Arquivo `BAIRROS_MANAUS.geojson` nao encontrado em `{GEOJSON_PATH}`. "
        "Certifique-se de que esta na raiz do repositorio."
    )
    st.stop()

with st.spinner("Carregando mapa de bairros..."):
    gdf_bairros = carregar_bairros()

with st.sidebar:
    st.header("⚙️ Configurações")
    tipo_rota_calc = st.radio("Tipo de rota para calcular", ["Entrada", "Saída"])
    modo = st.radio("Modo de operação", ["Apenas capacidade", "Capacidade + quantidade de rotas"])
    st.divider()

    if modo == "Apenas capacidade":
        cap_unica = st.number_input("Capacidade do veículo", min_value=5, max_value=100, value=22, step=1)
        st.info(f"Mínimo por rota: **{math.ceil(cap_unica * TAXA_MINIMA)}** passageiros")
        capacidades_config = None
    else:
        n_rotas_total = st.number_input("Quantidade de rotas", min_value=1, max_value=20, value=5, step=1)
        caps_lista = []
        for i in range(int(n_rotas_total)):
            c = st.number_input(f"Rota {i + 1}", min_value=5, max_value=100, value=22, step=1, key=f"cap_{i}")
            caps_lista.append(c)
        capacidades_config = caps_lista
        st.caption("Rotas extras podem ser criadas se algum grupo exceder a capacidade.")

    st.divider()
    st.caption(f"⏱️ Tempo máximo: **{MAX_TEMPO_MIN} min**")
    st.caption(f"📊 Ocupação mínima: **{int(TAXA_MINIMA * 100)}%**")
    st.caption(f"🧭 Waypoints ORS: **{MAX_WAYPOINTS}**")
    st.caption(f"🗺️ Bairros: **{len(gdf_bairros)}**")

col1, col2 = st.columns([2, 1])
with col1:
    uploaded_file = st.file_uploader("📂 Planilha (.xlsx)", type=["xlsx"])
with col2:
    st.markdown("**Colunas obrigatórias:**")
    st.markdown("- `COLABORADOR`\n- `LAT E` / `LONG E`\n- `LAT S` / `LONG S`")

st.subheader("📍 Selecione o destino final")
m = folium.Map(location=[-3.119, -60.021], zoom_start=12)
map_data = st_folium(m, height=380, width=None, key="mapa_destino")

destino_final = None
if map_data and map_data.get("last_clicked"):
    destino_final = (map_data["last_clicked"]["lat"], map_data["last_clicked"]["lng"])
    st.success(f"✅ Destino: {destino_final[0]:.5f}, {destino_final[1]:.5f}")
else:
    st.info("Clique no mapa para definir o destino.")

processar = st.button("🚀 Gerar Rotas", type="primary", disabled=not (uploaded_file and destino_final))

if processar and uploaded_file and destino_final:
    try:
        df = pd.read_excel(uploaded_file, sheet_name="BD")
    except Exception as e:
        st.error(f"Erro ao ler a planilha: {e}")
        st.stop()

    colunas_obrig = ["COLABORADOR", "LAT E", "LONG E", "LAT S", "LONG S"]
    faltando = [c for c in colunas_obrig if c not in df.columns]
    if faltando:
        st.error(f"Colunas ausentes: {', '.join(faltando)}")
        st.stop()

    for col in ["LAT E", "LONG E", "LAT S", "LONG S"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["LAT E", "LONG E", "LAT S", "LONG S"]).reset_index(drop=True)
    n_total = len(df)
    st.info(f"📋 {n_total} colaboradores carregados.")

    client = openrouteservice.Client(key=ORS_API_KEY)

    if modo == "Apenas capacidade":
        cap = int(cap_unica)
        min_por_rota = math.ceil(cap * TAXA_MINIMA)
        n_rotas_auto = math.ceil(n_total / cap)
        while n_rotas_auto > 1 and (n_total / n_rotas_auto) < min_por_rota:
            n_rotas_auto -= 1
        capacidades = [cap] * n_rotas_auto
        st.write(f"🔢 Rotas calculadas: **{n_rotas_auto}**")
    else:
        capacidades = [int(c) for c in capacidades_config]

    with st.spinner("Atribuindo bairros e montando rotas..."):
        rotas_resultado, nao_atribuidos, alertas, df_calc = clusterizar_por_bairros(
            df, destino_final, capacidades, client, gdf_bairros, tipo_rota_calc
        )

    a_tempo = [a for a in alertas if a["tipo"] == "tempo"]
    a_taxa = [a for a in alertas if a["tipo"] == "taxa"]
    a_isolados = [a for a in alertas if a["tipo"] == "isolado_bairro"]
    a_waypoints = [a for a in alertas if a["tipo"] == "waypoints"]
    a_rota_extra = [a for a in alertas if a["tipo"] == "rota_extra"]

    if any([a_tempo, a_taxa, a_isolados, a_waypoints, a_rota_extra, not nao_atribuidos.empty]):
        st.subheader("⚠️ Atenção")

        if a_rota_extra:
            st.markdown(
                '<div class="alerta-box">➕ Foram criadas rotas extras porque um ou mais grupos excediam a capacidade.</div>',
                unsafe_allow_html=True,
            )

        if a_isolados:
            nomes = ", ".join({htxt(a["colaborador"]) for a in a_isolados})
            bairros_iso = ", ".join({htxt(a["bairro"]) for a in a_isolados})
            st.markdown(
                f'<div class="alerta-box">📍 Colaboradores únicos no bairro ({bairros_iso}) '
                f'foram incluídos na rota mais próxima. Verifique: <b>{nomes}</b></div>',
                unsafe_allow_html=True,
            )

        for a in a_waypoints:
            st.markdown(
                f'<div class="alerta-box">🧭 Rota {a["rota"]} excedeu o limite de '
                f'{a["limite"]} pontos aceito para uma chamada ORS.</div>',
                unsafe_allow_html=True,
            )

        for a in a_tempo:
            st.markdown(
                f'<div class="alerta-box">🕐 <b>{htxt(a["colaborador"])}</b> geraria '
                f'{a["tempo_est"]} min na Rota {a["rota"]} ({htxt(a.get("fonte", ""))}) '
                f'e foi excluído. Decida manualmente.</div>',
                unsafe_allow_html=True,
            )

        for a in a_taxa:
            bairros_str = ", ".join(htxt(b) for b in a.get("bairros", []))
            st.markdown(
                f'<div class="alerta-box">📉 Rota {a["rota"]} ({bairros_str}): '
                f'{a["membros"]}/{a["capacidade"]} ({a["taxa"]}% ocupação).</div>',
                unsafe_allow_html=True,
            )

        if not nao_atribuidos.empty:
            st.markdown(
                f'<div class="erro-box">🔴 <b>{len(nao_atribuidos)} sem rota</b>. '
                f'Veja o motivo na tabela.</div>',
                unsafe_allow_html=True,
            )
            with st.expander("Ver colaboradores sem rota"):
                cols_show = [
                    c
                    for c in ["COLABORADOR", "BAIRRO_NOME", "DIST_KM", "MOTIVO_SEM_ROTA"]
                    if c in nao_atribuidos.columns
                ]
                st.dataframe(nao_atribuidos[cols_show].reset_index(drop=True))

    st.session_state["rotas_resultado"] = rotas_resultado
    st.session_state["df_base"] = df_calc
    st.session_state["capacidades"] = capacidades
    st.session_state["destino_final"] = destino_final
    st.session_state["client"] = client
    st.session_state["tipo_rota_calc"] = tipo_rota_calc
    atribuicao = {}
    for r in rotas_resultado:
        for idx in r["indices"]:
            atribuicao[idx] = r["rota_id"]
    st.session_state["atribuicao"] = atribuicao
    st.session_state["kmls"] = None


# ============================================================
# EDITOR INTERATIVO
# ============================================================
qp = st.query_params
if "atrib" in qp:
    try:
        decoded = urllib.parse.unquote(qp["atrib"])
        atrib_from_url = {int(k): int(v) for k, v in json.loads(decoded).items()}
        st.session_state["atribuicao"] = atrib_from_url
        st.query_params.clear()
        st.rerun()
    except Exception as e:
        st.warning(f"Erro ao ler edições do mapa: {e}")

if "atribuicao" in st.session_state and st.session_state.get("atribuicao") is not None:
    with st.expander("Aplicar edições manualmente", expanded=False):
        st.caption(
            "Use isto somente se o botão Confirmar edições do mapa ficar preso em Aguarde. "
            "Cole aqui o código JSON exibido no painel do mapa."
        )
        atrib_manual = st.text_area("Código das edições", key="atrib_manual_json", height=100)
        if st.button("Aplicar código de edições"):
            try:
                st.session_state["atribuicao"] = {
                    int(k): int(v) for k, v in json.loads(atrib_manual).items()
                }
                st.success("Edições aplicadas.")
                st.rerun()
            except Exception as e:
                st.error(f"Não consegui aplicar esse código: {e}")

    df_base = st.session_state["df_base"]
    atribuicao = st.session_state["atribuicao"]
    rotas_orig = st.session_state["rotas_resultado"]
    destino_final = st.session_state["destino_final"]
    tipo_rota_calc = st.session_state.get("tipo_rota_calc", "Entrada")
    lat_col, lon_col = colunas_tipo(tipo_rota_calc)

    if not atribuicao:
        st.warning("Nenhum colaborador foi atribuído às rotas. Revise os alertas acima.")
        st.stop()

    rota_info = {r["rota_id"]: {"nome": r["nome_rota"], "cap": r["capacidade"]} for r in rotas_orig}

    st.subheader("🗺️ Editor de Itinerários")
    st.caption(
        "Clique em um marcador para transferi-lo de rota. "
        "As linhas do editor são aproximações visuais; os KMLs finais usam rota por ruas via ORS quando possível."
    )

    CORES = [
        "#e6194b",
        "#3cb44b",
        "#4363d8",
        "#f58231",
        "#911eb4",
        "#42d4f4",
        "#f032e6",
        "#bfef45",
        "#fabed4",
        "#469990",
        "#dcbeff",
        "#9A6324",
        "#fffac8",
        "#800000",
        "#aaffc3",
        "#808000",
        "#ffd8b1",
        "#000075",
        "#a9a9a9",
        "#ffffff",
    ]

    pontos_js = []
    for df_idx, rota_id in atribuicao.items():
        row = df_base.loc[df_idx]
        pontos_js.append(
            {
                "df_idx": int(df_idx),
                "nome": str(row["COLABORADOR"]),
                "bairro": str(row.get("BAIRRO_NOME", "")),
                "lat": float(row[lat_col]),
                "lon": float(row[lon_col]),
                "rota_id": int(rota_id),
            }
        )

    cap_map = {int(r["rota_id"]): int(r["capacidade"]) for r in rotas_orig}

    def calcular_metricas(atrib, cap_map):
        contagem = {rid: 0 for rid in cap_map}
        for rota_id in atrib.values():
            contagem[int(rota_id)] = contagem.get(int(rota_id), 0) + 1
        return {
            rid: {
                "ocupacao": contagem.get(rid, 0),
                "cap": cap_map[rid],
                "taxa": round(contagem.get(rid, 0) / cap_map[rid] * 100, 1),
            }
            for rid in cap_map
        }

    metricas = calcular_metricas(atribuicao, cap_map)

    opcoes_rotas = [
        {
            "rota_id": int(rid),
            "label": (
                f"Rota {rid} - {rota_info[rid]['nome']} "
                f"({metricas[rid]['ocupacao']}/{metricas[rid]['cap']})"
            ),
        }
        for rid in sorted(rota_info)
    ]

    class NumpyEncoder(json.JSONEncoder):
        def default(self, o):
            if isinstance(o, np.integer):
                return int(o)
            if isinstance(o, np.floating):
                return float(o)
            if isinstance(o, np.ndarray):
                return o.tolist()
            return super().default(o)

    def safe_json(obj):
        return json.dumps(obj, cls=NumpyEncoder)

    centro_lat = sum(p["lat"] for p in pontos_js) / len(pontos_js)
    centro_lon = sum(p["lon"] for p in pontos_js) / len(pontos_js)

    pontos_json = safe_json(pontos_js)
    opcoes_json = safe_json(opcoes_rotas)
    cores_json = safe_json(CORES)
    capmap_json = safe_json({str(int(k)): int(v) for k, v in cap_map.items()})

    html_editor = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css"/>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<style>
* {{ box-sizing:border-box; margin:0; padding:0; font-family:sans-serif; font-size:13px; }}
body {{ display:flex; height:640px; overflow:hidden; }}
#map {{ flex:1; height:100%; }}
#painel {{ width:290px; height:100%; background:#1a1a1a; color:#ddd; display:flex; flex-direction:column; border-left:1px solid #333; }}
#painel-header {{ padding:10px 12px; background:#111; font-weight:600; font-size:11px; letter-spacing:.06em; color:#888; text-transform:uppercase; }}
#toggles {{ flex:1; overflow-y:auto; padding:8px; }}
.rota-toggle {{ background:#242424; border-radius:7px; padding:8px 10px; margin-bottom:6px; border-left:4px solid #555; cursor:pointer; user-select:none; }}
.rota-toggle.oculta {{ opacity:.35; }}
.rota-top {{ display:flex; align-items:center; gap:7px; margin-bottom:5px; }}
.rota-nome {{ font-weight:600; font-size:12px; color:#eee; flex:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.toggle-btn {{ font-size:10px; padding:2px 7px; border-radius:4px; border:none; background:#333; color:#aaa; cursor:pointer; flex-shrink:0; }}
.toggle-btn:hover {{ background:#444; }}
.rota-bar-wrap {{ background:#3a3a3a; border-radius:3px; height:5px; margin:3px 0; }}
.rota-bar {{ height:5px; border-radius:3px; transition:width .3s; }}
.rota-nums {{ font-size:11px; color:#888; }}
#confirmar-wrap {{ padding:10px 12px; border-top:1px solid #333; background:#111; }}
#btn-confirmar {{ width:100%; padding:10px; background:#16a34a; color:#fff; border:none; border-radius:7px; font-size:13px; font-weight:700; cursor:pointer; }}
#btn-confirmar:hover {{ background:#15803d; }}
#status-msg {{ font-size:11px; color:#6ee7b7; margin-top:5px; text-align:center; min-height:15px; }}
#fallback-payload {{ display:none; width:100%; height:72px; margin-top:8px; resize:none; border-radius:5px; border:1px solid #444; background:#222; color:#ddd; padding:6px; font-size:10px; }}
#popup-overlay {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,.55); z-index:9999; align-items:center; justify-content:center; }}
#popup-overlay.ativo {{ display:flex; }}
#popup-box {{ background:#fff; border-radius:10px; padding:20px 24px; min-width:290px; box-shadow:0 8px 32px rgba(0,0,0,.35); }}
#popup-box h3 {{ font-size:15px; color:#111; margin-bottom:3px; }}
.popup-sub {{ font-size:12px; color:#666; margin-bottom:14px; }}
#popup-box label {{ font-size:12px; font-weight:600; color:#333; }}
#popup-box select {{ width:100%; margin:6px 0 14px; padding:7px 10px; border:1px solid #ccc; border-radius:6px; font-size:13px; }}
.btn-row {{ display:flex; gap:8px; }}
.btn {{ flex:1; padding:8px; border:none; border-radius:6px; font-size:13px; font-weight:600; cursor:pointer; }}
.btn-ok {{ background:#3b82f6; color:#fff; }}
.btn-ok:hover {{ background:#2563eb; }}
.btn-cancel {{ background:#e5e7eb; color:#333; }}
</style>
</head>
<body>
<div id="map"></div>
<div id="painel"><div id="painel-header">🗂 Rotas</div><div id="toggles"></div><div id="confirmar-wrap"><button id="btn-confirmar" onclick="confirmar()">✅ Confirmar edições</button><div id="status-msg"></div><textarea id="fallback-payload" readonly></textarea></div></div>
<div id="popup-overlay"><div id="popup-box"><h3 id="popup-nome"></h3><div class="popup-sub" id="popup-sub"></div><label>Transferir para:</label><select id="popup-select"></select><div class="btn-row"><button class="btn btn-cancel" onclick="fecharPopup()">Cancelar</button><button class="btn btn-ok" onclick="transferir()">Transferir</button></div></div></div>
<script>
const PONTOS = {pontos_json};
const OPCOES = {opcoes_json};
const CORES = {cores_json};
const CAP_MAP = {capmap_json};
const DESTINO = [{destino_final[0]}, {destino_final[1]}];
let atribuicao = {{}};
PONTOS.forEach(p => {{ atribuicao[p.df_idx] = p.rota_id; }});
const map = L.map('map').setView([{centro_lat}, {centro_lon}], 12);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{ attribution:'© OpenStreetMap' }}).addTo(map);
L.marker(DESTINO, {{ icon: L.divIcon({{ html:'<div style="background:#111;color:#fff;border-radius:4px;padding:3px 7px;font-size:11px;font-weight:700;white-space:nowrap;box-shadow:0 1px 4px rgba(0,0,0,.5)">🏁 Destino</div>', iconAnchor:[40,10], className:'' }}) }}).addTo(map);
function corRota(rid) {{ return CORES[(rid-1) % CORES.length]; }}
function criarIcone(rid) {{ const cor = corRota(rid); return L.divIcon({{ html:`<div style="width:13px;height:13px;border-radius:50%;background:${{cor}};border:2px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,.5);cursor:pointer"></div>`, iconAnchor:[6,6], className:'' }}); }}
let markers = {{}};
PONTOS.forEach(p => {{ const mk = L.marker([p.lat, p.lon], {{icon: criarIcone(p.rota_id)}}).addTo(map).bindTooltip(p.nome, {{permanent:false, direction:'top', offset:[0,-8]}}).on('click', () => abrirPopup(p.df_idx)); markers[p.df_idx] = mk; }});
let polylines = {{}};
let rotasVisiveis = {{}};
function pontosOrdenadosPorRota(rid) {{ const pts = PONTOS.filter(p => atribuicao[p.df_idx] === rid); pts.sort((a,b) => Math.hypot(b.lat-DESTINO[0], b.lon-DESTINO[1]) - Math.hypot(a.lat-DESTINO[0], a.lon-DESTINO[1])); return pts; }}
function atualizarLinhas() {{ Object.values(polylines).forEach(pl => map.removeLayer(pl)); polylines = {{}}; const rota_ids = [...new Set(Object.values(atribuicao))].sort((a,b)=>a-b); rota_ids.forEach(rid => {{ if (!rotasVisiveis[rid]) return; const pts = pontosOrdenadosPorRota(rid); if (pts.length < 2) return; const latlngs = pts.map(p => [p.lat, p.lon]); latlngs.push(DESTINO); polylines[rid] = L.polyline(latlngs, {{ color: corRota(rid), weight:3, opacity:.75, dashArray:'6,4' }}).addTo(map); }}); }}
function atualizarTogglesPainel() {{ const rota_ids = [...new Set(Object.values(atribuicao))].sort((a,b)=>a-b); rota_ids.forEach(rid => {{ if (rotasVisiveis[rid] === undefined) rotasVisiveis[rid] = true; }}); const div = document.getElementById('toggles'); div.innerHTML = ''; rota_ids.forEach(rid => {{ const cap = parseInt(CAP_MAP[String(rid)] || 1); const ocup = Object.values(atribuicao).filter(r => r === rid).length; const taxa = Math.round(ocup/cap*100); const cor = corRota(rid); const barCor = taxa>=60?'#22c55e':taxa>=40?'#f59e0b':'#ef4444'; const vis = rotasVisiveis[rid]; const card = document.createElement('div'); card.className = 'rota-toggle' + (vis?'':' oculta'); card.id = `toggle-${{rid}}`; card.innerHTML = `<div class="rota-top"><div style="width:10px;height:10px;border-radius:50%;background:${{cor}};flex-shrink:0"></div><div class="rota-nome">Rota ${{rid}}</div><button class="toggle-btn" onclick="toggleRota(${{rid}},event)">${{vis?'Ocultar':'Mostrar'}}</button></div><div class="rota-bar-wrap"><div class="rota-bar" style="width:${{Math.min(100,taxa)}}%;background:${{barCor}}"></div></div><div class="rota-nums">${{ocup}}/${{cap}} &nbsp;·&nbsp; ${{taxa}}%</div>`; div.appendChild(card); }}); }}
function toggleRota(rid, e) {{ e.stopPropagation(); rotasVisiveis[rid] = !rotasVisiveis[rid]; Object.keys(atribuicao).forEach(idx => {{ if (atribuicao[idx] === rid) {{ if (rotasVisiveis[rid]) markers[idx].addTo(map); else map.removeLayer(markers[idx]); }} }}); atualizarLinhas(); atualizarTogglesPainel(); }}
function atualizar() {{ atualizarLinhas(); atualizarTogglesPainel(); }}
let popupDfIdx = null;
function abrirPopup(dfIdx) {{ popupDfIdx = dfIdx; const p = PONTOS.find(x => x.df_idx === dfIdx); const rid = atribuicao[dfIdx]; document.getElementById('popup-nome').textContent = p.nome; document.getElementById('popup-sub').textContent = (p.bairro ? p.bairro + ' - ' : '') + `atualmente na Rota ${{rid}}`; const sel = document.getElementById('popup-select'); sel.innerHTML = ''; OPCOES.forEach(op => {{ const opt = document.createElement('option'); opt.value = op.rota_id; opt.textContent = op.label; if (op.rota_id === rid) opt.selected = true; sel.appendChild(opt); }}); document.getElementById('popup-overlay').classList.add('ativo'); }}
function fecharPopup() {{ document.getElementById('popup-overlay').classList.remove('ativo'); popupDfIdx = null; }}
function transferir() {{ if (popupDfIdx === null) return; const novaRota = parseInt(document.getElementById('popup-select').value); atribuicao[popupDfIdx] = novaRota; markers[popupDfIdx].setIcon(criarIcone(novaRota)); if (rotasVisiveis[novaRota] === false) markers[popupDfIdx].addTo(map); fecharPopup(); atualizar(); }}
document.getElementById('popup-overlay').addEventListener('click', function(e) {{ if (e.target === this) fecharPopup(); }});
function confirmar() {{
  const status = document.getElementById('status-msg');
  const fallback = document.getElementById('fallback-payload');
  const raw = JSON.stringify(atribuicao);
  const payload = encodeURIComponent(raw);
  status.textContent = 'Aguarde...';
  fallback.style.display = 'none';
  fallback.value = raw;

  let targetUrl = '?atrib=' + payload;
  try {{
    const parentPath = window.parent.location.pathname || window.top.location.pathname || '/';
    targetUrl = parentPath + '?atrib=' + payload;
  }} catch (err) {{}}

  try {{
    window.open(targetUrl, '_top');
  }} catch (err) {{
    try {{ window.top.location.href = targetUrl; }} catch (err2) {{}}
  }}

  setTimeout(() => {{
    status.textContent = 'Se não recarregar, copie o código abaixo e aplique fora do mapa.';
    fallback.style.display = 'block';
    fallback.select();
  }}, 1500);
}}
atualizar();
</script>
</body>
</html>"""

    components.html(html_editor, height=650, scrolling=False)

    st.markdown("---")
    col_btn, col_info = st.columns([1, 3])
    with col_btn:
        gerar_kmls = st.button("🗂️ Gerar KMLs", type="primary")
    with col_info:
        st.caption("Confirme as edições no mapa e depois gere os arquivos.")

    if gerar_kmls:
        atrib_editada = {int(k): int(v) for k, v in st.session_state["atribuicao"].items()}
        df_base = st.session_state["df_base"]
        rotas_orig = st.session_state["rotas_resultado"]
        destino_final = st.session_state["destino_final"]
        client = st.session_state["client"]
        cap_map_local = {r["rota_id"]: r["capacidade"] for r in rotas_orig}
        nomes_orig = {r["rota_id"]: r["nome_rota"] for r in rotas_orig}

        grupos_editados = {}
        for df_idx, rota_id in atrib_editada.items():
            grupos_editados.setdefault(rota_id, []).append(df_idx)

        kml_files = []
        relatorio_rows = []

        with st.spinner("Gerando KMLs com itinerários confirmados..."):
            for rota_id, indices in sorted(grupos_editados.items()):
                grupo_df = df_base.loc[indices].copy()
                cap = cap_map_local.get(rota_id, max(cap_map_local.values()))
                nome_rota = nomes_orig.get(rota_id, f"ROTA_{rota_id:02d}")

                for tipo in ["Entrada", "Saída"]:
                    coords_kml, erro_rota = gerar_rota_ors_ou_linha(client, grupo_df, destino_final, tipo)
                    if erro_rota:
                        st.warning(
                            f"{nome_rota} {tipo}: ORS indisponível ou limite excedido; "
                            "o KML foi gerado com linha aproximada."
                        )
                    kml_files.append(
                        (
                            f"{nome_rota}_{tipo.lower()}",
                            gerar_kml(grupo_df, coords_kml, destino_final, nome_rota, tipo),
                        )
                    )

                taxa = round(len(indices) / cap * 100, 1)
                for _, row in grupo_df.iterrows():
                    relatorio_rows.append(
                        {
                            "ROTA": nome_rota,
                            "COLABORADOR": row["COLABORADOR"],
                            "BAIRRO": row.get("BAIRRO_NOME", ""),
                            "TIPO_CALCULO": tipo_rota_calc,
                            "LAT E": row["LAT E"],
                            "LONG E": row["LONG E"],
                            "LAT S": row["LAT S"],
                            "LONG S": row["LONG S"],
                            "OCUPACAO": f"{len(indices)}/{cap}",
                            "TAXA_%": taxa,
                        }
                    )

        st.session_state["kmls"] = kml_files
        st.session_state["df_relatorio"] = pd.DataFrame(relatorio_rows)
        st.success("✅ KMLs gerados com sucesso!")


if st.session_state.get("kmls"):
    st.subheader("📥 KMLs")
    cols_kml = st.columns(4)
    for i, (nome, kml) in enumerate(st.session_state["kmls"]):
        with cols_kml[i % 4]:
            st.download_button(
                f"⬇️ {nome}",
                kml.getvalue(),
                f"{nome}.kml",
                "application/vnd.google-earth.kml+xml",
                key=f"dl_{nome}",
            )

    st.subheader("📋 Relatório")
    df_rel = st.session_state["df_relatorio"]
    st.dataframe(df_rel, use_container_width=True)

    output = io.BytesIO()
    df_rel.to_excel(output, index=False)
    output.seek(0)
    st.download_button(
        "📥 Baixar Excel",
        output.getvalue(),
        "relatorio_rotas.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
