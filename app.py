import streamlit as st
import pandas as pd
import numpy as np
import openrouteservice
import geopandas as gpd
from shapely.geometry import Point
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from lxml import etree
import folium
from streamlit_folium import st_folium
import io
import requests
import time
import math
import os

# ============================================================
# CONFIGURAÇÕES
# ============================================================
ORS_API_KEY    = st.secrets["ORS_API_KEY"]
GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]

TAXA_MINIMA   = 0.60   # 60% de ocupação mínima por rota
MAX_TEMPO_MIN = 90     # minutos máximos por rota
MAX_WAYPOINTS = 48     # limite seguro da API ORS

# Caminho fixo no repositório (raiz do projeto)
GEOJSON_PATH = os.path.join(os.path.dirname(__file__), "BAIRROS_MANAUS.geojson")

st.set_page_config(page_title="Roteamento Inteligente", page_icon="🚌", layout="wide")

# ============================================================
# ESTILO
# ============================================================
st.markdown("""
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
""", unsafe_allow_html=True)

# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi    = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def dist_bairros(gdf, id_a, id_b):
    ca = gdf.loc[id_a].geometry.centroid
    cb = gdf.loc[id_b].geometry.centroid
    return haversine(ca.y, ca.x, cb.y, cb.x)


@st.cache_data(show_spinner=False)
def carregar_bairros():
    gdf = gpd.read_file(GEOJSON_PATH)
    gdf = gdf.set_crs("EPSG:4326") if gdf.crs is None else gdf.to_crs("EPSG:4326")
    return gdf


def atribuir_bairro(lat, lon, gdf):
    """Point-in-polygon; fallback ao centróide mais próximo."""
    pt = Point(lon, lat)
    for idx, row in gdf.iterrows():
        if row.geometry.contains(pt):
            nome = row.get("NM_BAIRRO") or row.get("nome") or row.get("name") or f"B{idx}"
            return idx, str(nome)
    dists   = gdf.geometry.centroid.apply(lambda c: haversine(lat, lon, c.y, c.x))
    idx_prx = dists.idxmin()
    row     = gdf.loc[idx_prx]
    nome    = row.get("NM_BAIRRO") or row.get("nome") or row.get("name") or f"B{idx_prx}"
    return idx_prx, str(nome)


def estimar_tempo_ors(client, waypoints, destino):
    coords = [[w[1], w[0]] for w in waypoints]
    coords.append([destino[1], destino[0]])
    try:
        res = client.directions(
            coordinates=coords, profile='driving-car',
            optimize_waypoints=True, format='geojson'
        )
        return res['features'][0]['properties']['summary']['duration'] / 60, True
    except Exception:
        return None, False


@st.cache_data(show_spinner=False)
def obter_endereco_google(lat: float, lon: float):
    url    = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"latlng": f"{lat},{lon}", "key": GOOGLE_API_KEY}
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data["results"]:
                comps = data["results"][0]["address_components"]
                rua = bairro = ""
                for c in comps:
                    if "route" in c["types"]:         rua   = c["long_name"]
                    if "sublocality" in c["types"] or "neighborhood" in c["types"]:
                        bairro = c["long_name"]
                return rua, bairro
    except Exception:
        pass
    return "Não encontrado", "Não encontrado"


def gerar_kml(grupo_df, coords_rota, destino_final, nome_rota, tipo):
    kml_root = etree.Element('kml', xmlns="http://www.opengis.net/kml/2.2")
    doc      = etree.SubElement(kml_root, 'Document')
    etree.SubElement(doc, 'name').text = f"{nome_rota} ({tipo})"

    col_lat = 'LAT E' if tipo == "Entrada" else 'LAT S'
    col_lon = 'LONG E' if tipo == "Entrada" else 'LONG S'

    for _, row in grupo_df.iterrows():
        pm = etree.SubElement(doc, 'Placemark')
        etree.SubElement(pm, 'name').text = str(row['COLABORADOR'])
        pt = etree.SubElement(pm, 'Point')
        etree.SubElement(pt, 'coordinates').text = f"{row[col_lon]},{row[col_lat]},0"

    pm_d = etree.SubElement(doc, 'Placemark')
    etree.SubElement(pm_d, 'name').text = "Destino Final"
    etree.SubElement(etree.SubElement(pm_d, 'Point'), 'coordinates').text = \
        f"{destino_final[1]},{destino_final[0]},0"

    linha  = etree.SubElement(doc, 'Placemark')
    etree.SubElement(linha, 'name').text = f"Trajeto {nome_rota} ({tipo})"
    style  = etree.SubElement(linha, 'Style')
    ls     = etree.SubElement(style, 'LineStyle')
    etree.SubElement(ls, 'color').text = 'ff0000ff'
    etree.SubElement(ls, 'width').text = '4'
    ls_str = etree.SubElement(linha, 'LineString')
    etree.SubElement(ls_str, 'tessellate').text = '1'
    etree.SubElement(ls_str, 'coordinates').text = \
        " ".join([f"{c[0]},{c[1]},0" for c in coords_rota])

    buf = io.BytesIO()
    etree.ElementTree(kml_root).write(buf, pretty_print=True,
                                      xml_declaration=True, encoding="UTF-8")
    buf.seek(0)
    return buf


# ============================================================
# ALGORITMO: AGRUPAMENTO POR BAIRROS + AFUNILAMENTO
# ============================================================

def _nome_rota(bairros, idx):
    if not bairros:
        return f"ROTA_{idx+1:02d}"
    return f"ROTA_{idx+1:02d} — {' / '.join(bairros[:2])}"


def clusterizar_por_bairros(df, destino, capacidades, client, gdf):
    """
    Etapa 1 — Point-in-polygon:
      Cada colaborador é mapeado ao polígono real do seu bairro.

    Etapa 2 — Agrupamento de bairros em rotas:
      Bairros pequenos (< min_grupo) são mesclados com o vizinho
      mais próximo. Bairros grandes demais são divididos via K-Means
      interno. O resultado são grupos geograficamente coesos.

    Etapa 3 — Afunilamento interno:
      Dentro de cada grupo-rota, colaboradores ordenados do mais
      distante ao destino para o mais próximo.

    Etapa 4 — Validação de tempo ORS:
      Pontos que excedam 90 min são sinalizados para decisão manual.
    """
    df      = df.copy().reset_index(drop=True)
    n_rotas = len(capacidades)
    alertas = []

    # ── Etapa 1: bairro de cada colaborador ──────────────────
    b_idxs, b_nomes = [], []
    for _, row in df.iterrows():
        bi, bn = atribuir_bairro(float(row['LAT E']), float(row['LONG E']), gdf)
        b_idxs.append(bi)
        b_nomes.append(bn)

    df['BAIRRO_IDX']  = b_idxs
    df['BAIRRO_NOME'] = b_nomes
    df['DIST_KM']     = df.apply(
        lambda r: haversine(r['LAT E'], r['LONG E'], destino[0], destino[1]), axis=1
    )

    # ── Etapa 2: monta grupos de bairros ─────────────────────
    contagem    = df.groupby('BAIRRO_IDX').size().to_dict()
    cap_ref     = int(np.mean(capacidades))
    min_grupo   = max(1, int(cap_ref * TAXA_MINIMA))

    # Cada bairro começa como grupo próprio
    grupos = [[b] for b in contagem]

    def tam(g):
        return sum(contagem.get(b, 0) for b in g)

    def dist_g(g1, g2):
        d = []
        for a in g1:
            for b in g2:
                try:   d.append(dist_bairros(gdf, a, b))
                except: d.append(999.0)
        return min(d) if d else 999.0

    # Mescla bairros pequenos iterativamente
    for _ in range(100):
        pequenos = [g for g in grupos if tam(g) < min_grupo]
        if not pequenos:
            break
        g_p   = pequenos[0]
        outros = [g for g in grupos if g is not g_p]
        if not outros:
            break
        # Escolhe o vizinho mais próximo que não gere super-grupo (>1.5× cap_ref)
        candidatos = [g for g in outros if tam(g) + tam(g_p) <= cap_ref * 1.5]
        alvo = min(candidatos or outros, key=lambda g: dist_g(g_p, g))
        grupos = [g for g in grupos if g is not g_p and g is not alvo]
        grupos.append(g_p + alvo)

    # Reduz até n_rotas grupos mesclando os mais próximos entre si
    while len(grupos) > n_rotas:
        menor_d, par = float('inf'), (0, 1)
        for i in range(len(grupos)):
            for j in range(i+1, len(grupos)):
                d = dist_g(grupos[i], grupos[j])
                if d < menor_d:
                    menor_d, par = d, (i, j)
        i, j   = par
        merged = grupos[i] + grupos[j]
        grupos = [g for k, g in enumerate(grupos) if k not in (i, j)]
        grupos.append(merged)

    # Completa com grupos vazios se necessário
    while len(grupos) < n_rotas:
        grupos.append([])

    # Mapeia colaboradores para grupo-rota
    df['GRUPO_ROTA'] = -1
    for ri, grupo in enumerate(grupos):
        df.loc[df['BAIRRO_IDX'].isin(grupo), 'GRUPO_ROTA'] = ri

    # ── Sub-divisão de grupos grandes via K-Means ─────────────
    df['CLUSTER_FINAL'] = df['GRUPO_ROTA'].copy()
    proximos_clusters   = len(grupos)  # contador para novos clusters

    for ri, cap in enumerate(capacidades):
        idxs_grupo = df[df['GRUPO_ROTA'] == ri].index.tolist()
        if len(idxs_grupo) <= cap:
            continue

        n_sub = math.ceil(len(idxs_grupo) / cap)
        coords_s  = df.loc[idxs_grupo, ['LAT E', 'LONG E']].values
        scaler    = StandardScaler()
        km        = KMeans(n_clusters=n_sub, random_state=42, n_init=10)
        sub_labels = km.fit_predict(scaler.fit_transform(coords_s))

        # Primeiro sub-cluster mantém o id original
        for sub_id in range(n_sub):
            sub_idxs = [idxs_grupo[k] for k, s in enumerate(sub_labels) if s == sub_id]
            novo_id  = ri if sub_id == 0 else proximos_clusters
            if sub_id > 0:
                proximos_clusters += 1
            df.loc[sub_idxs, 'CLUSTER_FINAL'] = novo_id

    # ── Etapa 3 + 4: afunilamento + validação ORS ────────────
    rotas      = []
    atribuidos = set()

    clusters_ids = sorted([c for c in df['CLUSTER_FINAL'].unique() if c >= 0])

    # Mapeia cluster_id → capacidade (herda do grupo-rota original)
    cap_map = {}
    for c in clusters_ids:
        rota_orig = df[df['CLUSTER_FINAL'] == c]['GRUPO_ROTA'].mode()
        ri        = int(rota_orig.iloc[0]) if not rota_orig.empty else 0
        cap_map[c] = capacidades[ri] if ri < len(capacidades) else capacidades[-1]

    for cluster_id in clusters_ids:
        cap        = cap_map[cluster_id]
        cluster_df = df[df['CLUSTER_FINAL'] == cluster_id].copy()
        if cluster_df.empty:
            continue

        nomes_bairros = cluster_df['BAIRRO_NOME'].unique().tolist()

        # Afunilamento: mais distante ao destino primeiro
        cluster_df = cluster_df.sort_values('DIST_KM', ascending=False)

        membros_idx    = []
        membros_coords = []

        for idx, row in cluster_df.iterrows():
            if len(membros_idx) >= cap:
                break

            coord_nova   = (float(row['LAT E']), float(row['LONG E']))
            teste_coords = membros_coords + [coord_nova]

            if len(teste_coords) >= 2:
                t, ok = estimar_tempo_ors(client, teste_coords, destino)
                if ok and t is not None and t > MAX_TEMPO_MIN:
                    alertas.append({
                        'tipo': 'tempo', 'rota': cluster_id + 1,
                        'colaborador': row['COLABORADOR'], 'tempo_est': round(t, 1)
                    })
                    df.loc[idx, 'CLUSTER_FINAL'] = -99
                    continue

            membros_idx.append(idx)
            membros_coords.append(coord_nova)
            atribuidos.add(idx)

        taxa = len(membros_idx) / cap if cap > 0 else 0

        if taxa < TAXA_MINIMA and len(membros_idx) > 0:
            alertas.append({
                'tipo': 'taxa', 'rota': cluster_id + 1,
                'membros': len(membros_idx), 'capacidade': cap,
                'taxa': round(taxa * 100, 1), 'bairros': nomes_bairros
            })

        # Sinaliza colaboradores únicos no bairro (podem ser mal encaixados)
        for bairro in nomes_bairros:
            colab_bairro = cluster_df[cluster_df['BAIRRO_NOME'] == bairro]
            if len(colab_bairro) == 1:
                alertas.append({
                    'tipo': 'isolado_bairro',
                    'colaborador': colab_bairro['COLABORADOR'].values[0],
                    'bairro': bairro
                })

        if membros_idx:
            rotas.append({
                'rota_id':   cluster_id + 1,
                'indices':   membros_idx,
                'capacidade': cap,
                'ocupacao':  len(membros_idx),
                'taxa':      round(taxa * 100, 1),
                'bairros':   nomes_bairros,
                'nome_rota': _nome_rota(nomes_bairros, cluster_id)
            })

    nao_atribuidos = df[~df.index.isin(atribuidos)]
    return rotas, nao_atribuidos, alertas, df


# ============================================================
# INTERFACE
# ============================================================

st.title("🚌 Roteamento Inteligente de Colaboradores")
st.caption("Agrupamento automático por bairros de Manaus + afunilamento ao destino")

# Verifica e carrega GeoJSON
if not os.path.exists(GEOJSON_PATH):
    st.error(
        f"Arquivo `BAIRROS_MANAUS.geojson` não encontrado em `{GEOJSON_PATH}`. "
        "Certifique-se de que está na raiz do repositório."
    )
    st.stop()

with st.spinner("Carregando mapa de bairros..."):
    gdf_bairros = carregar_bairros()

# Sidebar
with st.sidebar:
    st.header("⚙️ Configurações")
    modo = st.radio("Modo de operação",
                    ["Apenas capacidade", "Capacidade + quantidade de rotas"])
    st.divider()

    if modo == "Apenas capacidade":
        cap_unica = st.number_input("Capacidade do veículo", min_value=5,
                                    max_value=100, value=22, step=1)
        st.info(f"Mínimo por rota: **{math.ceil(cap_unica * TAXA_MINIMA)}** passageiros")
        capacidades_config = None
    else:
        n_rotas_total = st.number_input("Quantidade de rotas", min_value=1,
                                        max_value=20, value=5, step=1)
        caps_lista = []
        for i in range(int(n_rotas_total)):
            c = st.number_input(f"Rota {i+1}", min_value=5, max_value=100,
                                value=22, step=1, key=f"cap_{i}")
            caps_lista.append(c)
        capacidades_config = caps_lista

    st.divider()
    st.caption(f"⏱️ Tempo máximo: **{MAX_TEMPO_MIN} min**")
    st.caption(f"📊 Ocupação mínima: **{int(TAXA_MINIMA*100)}%**")
    st.caption(f"🗺️ Bairros: **{len(gdf_bairros)}**")

# Upload
col1, col2 = st.columns([2, 1])
with col1:
    uploaded_file = st.file_uploader("📂 Planilha (.xlsx)", type=["xlsx"])
with col2:
    st.markdown("**Colunas obrigatórias:**")
    st.markdown("- `COLABORADOR`\n- `LAT E` / `LONG E`\n- `LAT S` / `LONG S`")

# Mapa destino
st.subheader("📍 Selecione o destino final")
m        = folium.Map(location=[-3.119, -60.021], zoom_start=12)
map_data = st_folium(m, height=380, width=None, key="mapa_destino")

destino_final = None
if map_data and map_data.get("last_clicked"):
    destino_final = (map_data["last_clicked"]["lat"], map_data["last_clicked"]["lng"])
    st.success(f"✅ Destino: {destino_final[0]:.5f}, {destino_final[1]:.5f}")
else:
    st.info("Clique no mapa para definir o destino.")

# ── Botão principal ──────────────────────────────────────────
processar = st.button("🚀 Gerar Rotas", type="primary",
                      disabled=not (uploaded_file and destino_final))

if processar and uploaded_file and destino_final:

    try:
        df = pd.read_excel(uploaded_file, sheet_name="BD")
    except Exception as e:
        st.error(f"Erro ao ler a planilha: {e}"); st.stop()

    colunas_obrig = ['COLABORADOR', 'LAT E', 'LONG E', 'LAT S', 'LONG S']
    faltando = [c for c in colunas_obrig if c not in df.columns]
    if faltando:
        st.error(f"Colunas ausentes: {', '.join(faltando)}"); st.stop()

    for col in ['LAT E', 'LONG E', 'LAT S', 'LONG S']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna(subset=['LAT E', 'LONG E', 'LAT S', 'LONG S']).reset_index(drop=True)
    n_total = len(df)
    st.info(f"📋 {n_total} colaboradores carregados.")

    client = openrouteservice.Client(key=ORS_API_KEY)

    if modo == "Apenas capacidade":
        cap          = int(cap_unica)
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
            df, destino_final, capacidades, client, gdf_bairros
        )

    # ── Alertas ──────────────────────────────────────────────
    a_tempo    = [a for a in alertas if a['tipo'] == 'tempo']
    a_taxa     = [a for a in alertas if a['tipo'] == 'taxa']
    a_isolados = [a for a in alertas if a['tipo'] == 'isolado_bairro']

    if any([a_tempo, a_taxa, a_isolados, not nao_atribuidos.empty]):
        st.subheader("⚠️ Atenção")

        if a_isolados:
            nomes = ", ".join({a['colaborador'] for a in a_isolados})
            bairros_iso = ", ".join({a['bairro'] for a in a_isolados})
            st.markdown(
                f'<div class="alerta-box">📍 Colaboradores únicos no bairro '
                f'({bairros_iso}) — incluídos na rota mais próxima, verifique: '
                f'<b>{nomes}</b></div>', unsafe_allow_html=True
            )

        for a in a_tempo:
            st.markdown(
                f'<div class="alerta-box">🕐 <b>{a["colaborador"]}</b> geraria '
                f'{a["tempo_est"]} min na Rota {a["rota"]} — excluído. '
                f'Decida manualmente.</div>', unsafe_allow_html=True
            )

        for a in a_taxa:
            bairros_str = ", ".join(a.get('bairros', []))
            st.markdown(
                f'<div class="alerta-box">📉 Rota {a["rota"]} ({bairros_str}): '
                f'{a["membros"]}/{a["capacidade"]} ({a["taxa"]}% ocupação).</div>',
                unsafe_allow_html=True
            )

        if not nao_atribuidos.empty:
            st.markdown(
                f'<div class="erro-box">🔴 <b>{len(nao_atribuidos)} sem rota</b> '
                f'(tempo excedido ou rotas lotadas).</div>', unsafe_allow_html=True
            )
            with st.expander("Ver colaboradores sem rota"):
                cols_show = [c for c in ['COLABORADOR', 'BAIRRO_NOME', 'DIST_KM']
                             if c in nao_atribuidos.columns]
                st.dataframe(nao_atribuidos[cols_show].reset_index(drop=True))

    # ── Resumo das rotas ─────────────────────────────────────
    st.subheader("📊 Resumo das Rotas")
    n_cols = min(len(rotas_resultado), 4)
    if n_cols:
        cols_res = st.columns(n_cols)
        for i, r in enumerate(rotas_resultado):
            with cols_res[i % n_cols]:
                label = " / ".join(r['bairros'][:2]) or f"Rota {r['rota_id']}"
                cor   = "🟢" if r['taxa'] >= 60 else "🟡"
                st.metric(label, f"{r['ocupacao']}/{r['capacidade']}",
                          f"{cor} {r['taxa']}%")

    # ── Geocodificação ───────────────────────────────────────
    cache_key = f"end_{uploaded_file.name}_{n_total}"
    if cache_key not in st.session_state:
        ruas, bairros_g = [], []
        with st.spinner("Buscando endereços..."):
            prog = st.progress(0)
            for i, (_, row) in enumerate(df.iterrows()):
                rua, bairro = obter_endereco_google(float(row['LAT E']), float(row['LONG E']))
                ruas.append(rua); bairros_g.append(bairro)
                time.sleep(0.05)
                prog.progress((i+1) / n_total)
        st.session_state[cache_key] = (ruas, bairros_g)

    ruas, bairros_g = st.session_state[cache_key]
    df['ENDERECO'] = ruas

    # ── KMLs ─────────────────────────────────────────────────
    kml_files      = []
    relatorio_rows = []

    with st.spinner("Gerando KMLs..."):
        for r in rotas_resultado:
            grupo_df  = df.loc[r['indices']].copy()
            nome_rota = r['nome_rota']

            for tipo, col_lat, col_lon in [
                ("Entrada", "LAT E", "LONG E"),
                ("Saída",   "LAT S", "LONG S")
            ]:
                wpts  = list(zip(grupo_df[col_lat], grupo_df[col_lon]))
                c_ors = [[w[1], w[0]] for w in wpts]
                c_ors.append([destino_final[1], destino_final[0]])

                try:
                    res = client.directions(
                        coordinates=c_ors, profile='driving-car',
                        optimize_waypoints=True, format='geojson'
                    )
                    coords_kml = res['features'][0]['geometry']['coordinates']
                except Exception as e:
                    st.warning(f"Erro ORS {nome_rota} {tipo}: {e}")
                    coords_kml = [[lon, lat] for lat, lon in wpts] + \
                                 [[destino_final[1], destino_final[0]]]

                kml_files.append((
                    f"{nome_rota}_{tipo.lower()}",
                    gerar_kml(grupo_df, coords_kml, destino_final, nome_rota, tipo)
                ))

            for _, row in grupo_df.iterrows():
                relatorio_rows.append({
                    'ROTA':       nome_rota,
                    'COLABORADOR': row['COLABORADOR'],
                    'BAIRRO':     row.get('BAIRRO_NOME', ''),
                    'ENDERECO':   row.get('ENDERECO', ''),
                    'LAT E':      row['LAT E'],
                    'LONG E':     row['LONG E'],
                    'OCUPACAO':   f"{r['ocupacao']}/{r['capacidade']}",
                    'TAXA_%':     r['taxa'],
                })

    st.session_state["kmls"]         = kml_files
    st.session_state["df_relatorio"] = pd.DataFrame(relatorio_rows)
    st.success("✅ Rotas geradas com sucesso!")

# ── Downloads ────────────────────────────────────────────────
if "kmls" in st.session_state:
    st.subheader("📥 KMLs")
    cols_kml = st.columns(4)
    for i, (nome, kml) in enumerate(st.session_state["kmls"]):
        with cols_kml[i % 4]:
            st.download_button(f"⬇️ {nome}", kml.getvalue(),
                               f"{nome}.kml",
                               "application/vnd.google-earth.kml+xml",
                               key=f"dl_{nome}")

    st.subheader("📋 Relatório")
    df_rel = st.session_state["df_relatorio"]
    st.dataframe(df_rel, use_container_width=True)

    output = io.BytesIO()
    df_rel.to_excel(output, index=False)
    output.seek(0)
    st.download_button("📥 Baixar Excel", output.getvalue(),
                       "relatorio_rotas.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
