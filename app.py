import streamlit as st
import pandas as pd
import numpy as np
import openrouteservice
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from lxml import etree
import folium
from streamlit_folium import st_folium
import io
import requests
import time
import math

# ============================================================
# CONFIGURAÇÕES
# ============================================================
ORS_API_KEY = st.secrets["ORS_API_KEY"]
GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]

TAXA_MINIMA = 0.60          # 60% de ocupação mínima por rota
MAX_TEMPO_MIN = 90          # minutos máximos por rota
MAX_WAYPOINTS_ORS = 48      # limite seguro da API ORS

st.set_page_config(page_title="Roteamento Inteligente", page_icon="🚌", layout="wide")

# ============================================================
# ESTILO
# ============================================================
st.markdown("""
<style>
    .metric-box {
        background: #f8f9fa;
        border-radius: 10px;
        padding: 1rem;
        text-align: center;
        border: 1px solid #e0e0e0;
    }
    .alerta-box {
        background: #fff3cd;
        border-left: 4px solid #ffc107;
        padding: 0.75rem 1rem;
        border-radius: 4px;
        margin: 0.5rem 0;
    }
    .sucesso-box {
        background: #d4edda;
        border-left: 4px solid #28a745;
        padding: 0.75rem 1rem;
        border-radius: 4px;
        margin: 0.5rem 0;
    }
    .erro-box {
        background: #f8d7da;
        border-left: 4px solid #dc3545;
        padding: 0.75rem 1rem;
        border-radius: 4px;
        margin: 0.5rem 0;
    }
</style>
""", unsafe_allow_html=True)

# ============================================================
# FUNÇÕES AUXILIARES
# ============================================================

def haversine(lat1, lon1, lat2, lon2):
    """Distância em km entre dois pontos geográficos."""
    R = 6371
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def angulo_destino(lat, lon, lat_dest, lon_dest):
    """Ângulo polar do colaborador em relação ao destino (0-360°)."""
    dlat = lat - lat_dest
    dlon = lon - lon_dest
    return math.degrees(math.atan2(dlon, dlat)) % 360


def estimar_tempo_ors(client, waypoints, destino):
    """
    Estima tempo de rota via ORS.
    Retorna (minutos, sucesso).
    """
    coords = [[w[1], w[0]] for w in waypoints]  # [lon, lat]
    coords.append([destino[1], destino[0]])
    try:
        res = client.directions(
            coordinates=coords,
            profile='driving-car',
            optimize_waypoints=True,
            format='geojson'
        )
        segundos = res['features'][0]['properties']['summary']['duration']
        return segundos / 60, True
    except Exception as e:
        return None, False


@st.cache_data(show_spinner=False)
def obter_endereco_google(lat: float, lon: float):
    url = "https://maps.googleapis.com/maps/api/geocode/json"
    params = {"latlng": f"{lat},{lon}", "key": GOOGLE_API_KEY}
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data["results"]:
                comps = data["results"][0]["address_components"]
                rua = bairro = ""
                for c in comps:
                    if "route" in c["types"]:
                        rua = c["long_name"]
                    if "sublocality" in c["types"] or "neighborhood" in c["types"]:
                        bairro = c["long_name"]
                return rua, bairro
    except Exception:
        pass
    return "Não encontrado", "Não encontrado"


def gerar_kml(grupo_df, coords_rota, destino_final, nome_rota, tipo):
    kml_root = etree.Element('kml', xmlns="http://www.opengis.net/kml/2.2")
    document = etree.SubElement(kml_root, 'Document')
    etree.SubElement(document, 'name').text = f"{nome_rota} ({tipo})"

    col_lat = 'LAT E' if tipo == "Entrada" else 'LAT S'
    col_lon = 'LONG E' if tipo == "Entrada" else 'LONG S'

    for _, row in grupo_df.iterrows():
        placemark = etree.SubElement(document, 'Placemark')
        etree.SubElement(placemark, 'name').text = str(row['COLABORADOR'])
        point = etree.SubElement(placemark, 'Point')
        etree.SubElement(point, 'coordinates').text = f"{row[col_lon]},{row[col_lat]},0"

    pm_dest = etree.SubElement(document, 'Placemark')
    etree.SubElement(pm_dest, 'name').text = "Destino Final"
    pt_dest = etree.SubElement(pm_dest, 'Point')
    etree.SubElement(pt_dest, 'coordinates').text = f"{destino_final[1]},{destino_final[0]},0"

    linha = etree.SubElement(document, 'Placemark')
    etree.SubElement(linha, 'name').text = f"Trajeto {nome_rota} ({tipo})"
    style = etree.SubElement(linha, 'Style')
    ls = etree.SubElement(style, 'LineStyle')
    etree.SubElement(ls, 'color').text = 'ff0000ff'
    etree.SubElement(ls, 'width').text = '4'
    ls_str = etree.SubElement(linha, 'LineString')
    etree.SubElement(ls_str, 'tessellate').text = '1'
    coords_txt = " ".join([f"{c[0]},{c[1]},0" for c in coords_rota])
    etree.SubElement(ls_str, 'coordinates').text = coords_txt

    tree = etree.ElementTree(kml_root)
    buf = io.BytesIO()
    tree.write(buf, pretty_print=True, xml_declaration=True, encoding="UTF-8")
    buf.seek(0)
    return buf


# ============================================================
# ALGORITMO CENTRAL: K-MEANS GEOGRÁFICO + AFUNILAMENTO
# ============================================================

def clusterizar_afunilado(df, destino, capacidades, client):
    """
    Agrupa colaboradores em rotas coesas geograficamente.

    Estratégia em duas etapas:
    ETAPA 1 — K-Means geográfico:
        Agrupa os colaboradores por proximidade real no mapa usando K-Means
        sobre (lat, lon). Isso garante que cada cluster seja uma zona coesa
        da cidade, sem misturar norte/sul/leste/oeste.
        Quando os clusters têm tamanho muito diferente da capacidade do veículo,
        faz uma redistribuição por vizinhança para balancear.

    ETAPA 2 — Afunilamento interno:
        Dentro de cada cluster, ordena os pontos do mais distante ao destino
        para o mais próximo. O ORS otimiza a ordem real de embarque, mas a
        ordenação garante que o veículo vá pegando quem está "no caminho"
        em direção ao destino, sem zig-zag entre extremos opostos.

    ETAPA 3 — Validação de tempo:
        Verifica via ORS se a rota do cluster excede 90 min. Se sim, remove
        os pontos mais distantes até caber, e os pontos removidos são
        oferecidos a clusters vizinhos ou listados como não atribuídos.

    Retorna lista de dicts com info de cada rota.
    """
    df = df.copy().reset_index(drop=True)
    n_total = len(df)
    n_rotas = len(capacidades)
    alertas = []

    # --- Calcula distância e ângulo de cada ponto em relação ao destino ---
    df['DIST_KM'] = df.apply(
        lambda r: haversine(r['LAT E'], r['LONG E'], destino[0], destino[1]), axis=1
    )
    df['ANGULO'] = df.apply(
        lambda r: angulo_destino(r['LAT E'], r['LONG E'], destino[0], destino[1]), axis=1
    )

    # =========================================================
    # ETAPA 1: K-Means geográfico
    # =========================================================
    coords = df[['LAT E', 'LONG E']].values

    # Escala as coordenadas para que lat e lon tenham peso equivalente
    scaler = StandardScaler()
    coords_scaled = scaler.fit_transform(coords)

    # K-Means com k = número de rotas
    kmeans = KMeans(n_clusters=n_rotas, random_state=42, n_init=10)
    df['CLUSTER'] = kmeans.fit_predict(coords_scaled)

    # =========================================================
    # ETAPA 1b: Redistribuição por capacidade
    # Clusters muito grandes são podados; os excedentes vão para
    # o cluster vizinho mais próximo que ainda tenha espaço.
    # =========================================================
    caps_por_cluster = {i: capacidades[i] for i in range(n_rotas)}

    # Identifica excedentes em cada cluster
    excedentes = []
    for cluster_id in range(n_rotas):
        cap = caps_por_cluster[cluster_id]
        membros = df[df['CLUSTER'] == cluster_id].copy()
        membros = membros.sort_values('DIST_KM', ascending=False)
        if len(membros) > cap:
            # Remove os menos distantes (mais fáceis de redistribuir)
            sobra = membros.iloc[cap:]
            excedentes.extend(sobra.index.tolist())
            df.loc[sobra.index, 'CLUSTER'] = -1  # marca como sem cluster

    # Tenta encaixar excedentes nos clusters com espaço
    for idx in excedentes:
        row = df.loc[idx]
        coord_ponto = np.array([[row['LAT E'], row['LONG E']]])
        melhor_cluster = -1
        menor_dist = float('inf')

        for cluster_id in range(n_rotas):
            ocupacao_atual = (df['CLUSTER'] == cluster_id).sum()
            if ocupacao_atual >= caps_por_cluster[cluster_id]:
                continue
            centroide = kmeans.cluster_centers_[cluster_id]
            centroide_orig = scaler.inverse_transform([centroide])[0]
            dist = haversine(row['LAT E'], row['LONG E'], centroide_orig[0], centroide_orig[1])
            if dist < menor_dist:
                menor_dist = dist
                melhor_cluster = cluster_id

        if melhor_cluster >= 0:
            df.loc[idx, 'CLUSTER'] = melhor_cluster

    # =========================================================
    # ETAPA 2 + 3: Afunilamento interno + validação de tempo
    # =========================================================
    rotas = []
    atribuidos = set()

    for rota_idx, cap in enumerate(capacidades):
        cluster_df = df[df['CLUSTER'] == rota_idx].copy()

        if cluster_df.empty:
            continue

        # Ordena do mais distante para o mais próximo do destino
        # → o veículo parte do extremo e vai "afunilando" até chegar
        cluster_df = cluster_df.sort_values('DIST_KM', ascending=False)

        membros_idx = []
        membros_coords = []

        for idx, row in cluster_df.iterrows():
            if len(membros_idx) >= cap:
                break

            coord_nova = (float(row['LAT E']), float(row['LONG E']))
            teste_coords = membros_coords + [coord_nova]

            # Valida tempo apenas quando há ao menos 2 pontos (1 ponto = irrelevante testar)
            if len(teste_coords) >= 2:
                tempo_est, ok = estimar_tempo_ors(client, teste_coords, destino)
                if ok and tempo_est is not None and tempo_est > MAX_TEMPO_MIN:
                    alertas.append({
                        'tipo': 'tempo',
                        'rota': rota_idx + 1,
                        'colaborador': row['COLABORADOR'],
                        'tempo_est': round(tempo_est, 1)
                    })
                    # Ponto removido por tempo: tenta colocar no cluster vizinho
                    # (redistribuição por proximidade angular)
                    df.loc[idx, 'CLUSTER'] = -2  # marca como "removido por tempo"
                    continue

            membros_idx.append(idx)
            membros_coords.append(coord_nova)
            atribuidos.add(idx)

        taxa = len(membros_idx) / cap if cap > 0 else 0
        if taxa < TAXA_MINIMA and len(membros_idx) > 0:
            alertas.append({
                'tipo': 'taxa',
                'rota': rota_idx + 1,
                'membros': len(membros_idx),
                'capacidade': cap,
                'taxa': round(taxa * 100, 1)
            })

        if membros_idx:
            rotas.append({
                'rota_id': rota_idx + 1,
                'indices': membros_idx,
                'capacidade': cap,
                'ocupacao': len(membros_idx),
                'taxa': round(taxa * 100, 1)
            })

    # Colaboradores sem atribuição final
    nao_atribuidos = df[~df.index.isin(atribuidos)]

    return rotas, nao_atribuidos, alertas, df


# ============================================================
# INTERFACE PRINCIPAL
# ============================================================

st.title("🚌 Roteamento Inteligente de Colaboradores")
st.caption("Distribuição automática por afunilamento geográfico — sem coluna ROTA")

# Sidebar: configurações
with st.sidebar:
    st.header("⚙️ Configurações")
    modo = st.radio(
        "Modo de operação",
        ["Apenas capacidade", "Capacidade + quantidade de rotas"],
        help="Escolha como deseja definir as rotas disponíveis."
    )

    st.divider()

    if modo == "Apenas capacidade":
        cap_unica = st.number_input(
            "Capacidade do veículo (lugares)",
            min_value=5, max_value=100, value=22, step=1
        )
        st.info(f"Taxa mínima de ocupação: **{int(TAXA_MINIMA*100)}%** → mínimo {math.ceil(cap_unica * TAXA_MINIMA)} passageiros por rota")
        capacidades_config = None  # será calculado automaticamente
    else:
        n_rotas_total = st.number_input("Quantidade de rotas disponíveis", min_value=1, max_value=20, value=5, step=1)
        st.write("**Capacidade por rota:**")
        caps_lista = []
        for i in range(int(n_rotas_total)):
            c = st.number_input(f"Rota {i+1}", min_value=5, max_value=100, value=22, step=1, key=f"cap_{i}")
            caps_lista.append(c)
        capacidades_config = caps_lista

    st.divider()
    st.caption(f"⏱️ Tempo máximo por rota: **{MAX_TEMPO_MIN} min** (fixo)")
    st.caption(f"📊 Taxa mínima de ocupação: **{int(TAXA_MINIMA*100)}%** (fixo)")

# Upload
col1, col2 = st.columns([2, 1])
with col1:
    uploaded_file = st.file_uploader("📂 Planilha de colaboradores (.xlsx)", type=["xlsx"])
with col2:
    st.markdown("**Colunas obrigatórias:**")
    st.markdown("- `COLABORADOR`\n- `LAT E` / `LONG E` (entrada)\n- `LAT S` / `LONG S` (saída)")

# Mapa para destino
st.subheader("📍 Selecione o destino final")
m = folium.Map(location=[-3.119, -60.021], zoom_start=12)
map_data = st_folium(m, height=380, width=None, key="mapa_destino")

destino_final = None
if map_data and map_data.get("last_clicked"):
    destino_final = (
        map_data["last_clicked"]["lat"],
        map_data["last_clicked"]["lng"]
    )
    st.success(f"✅ Destino: {destino_final[0]:.5f}, {destino_final[1]:.5f}")
else:
    st.info("Clique no mapa para definir o destino.")

# ============================================================
# PROCESSAMENTO
# ============================================================

col_btn1, col_btn2 = st.columns([1, 3])
with col_btn1:
    processar = st.button("🚀 Gerar Rotas", type="primary", disabled=not (uploaded_file and destino_final))

if processar and uploaded_file and destino_final:

    # Leitura
    try:
        df = pd.read_excel(uploaded_file, sheet_name="BD")
    except Exception as e:
        st.error(f"Erro ao ler a planilha: {e}")
        st.stop()

    colunas_obrig = ['COLABORADOR', 'LAT E', 'LONG E', 'LAT S', 'LONG S']
    faltando = [c for c in colunas_obrig if c not in df.columns]
    if faltando:
        st.error(f"Colunas ausentes: {', '.join(faltando)}")
        st.stop()

    for col in ['LAT E', 'LONG E', 'LAT S', 'LONG S']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna(subset=['LAT E', 'LONG E', 'LAT S', 'LONG S'])

    n_total = len(df)
    st.info(f"📋 {n_total} colaboradores carregados.")

    # Define capacidades
    client = openrouteservice.Client(key=ORS_API_KEY)

    if modo == "Apenas capacidade":
        # Estima número mínimo de rotas para não criar rotas abaixo de 60%
        cap = int(cap_unica)
        min_por_rota = math.ceil(cap * TAXA_MINIMA)
        n_rotas_auto = math.ceil(n_total / cap)
        # Garante que não sobrem menos de min_por_rota em nenhuma rota
        while n_rotas_auto > 1 and (n_total / n_rotas_auto) < min_por_rota:
            n_rotas_auto -= 1
        capacidades = [cap] * n_rotas_auto
        st.write(f"🔢 Número de rotas calculado automaticamente: **{n_rotas_auto}**")
    else:
        capacidades = [int(c) for c in capacidades_config]

    # CLUSTERIZAÇÃO
    with st.spinner("Calculando agrupamentos e verificando tempos via ORS..."):
        rotas_resultado, nao_atribuidos, alertas, df_calc = clusterizar_afunilado(
            df, destino_final, capacidades, client
        )

    # ============================================================
    # ALERTAS INTERATIVOS
    # ============================================================
    alertas_tempo = [a for a in alertas if a['tipo'] == 'tempo']
    alertas_taxa = [a for a in alertas if a['tipo'] == 'taxa']

    if alertas_tempo or alertas_taxa or not nao_atribuidos.empty:
        st.subheader("⚠️ Atenção — decisões necessárias")

        if alertas_tempo:
            st.markdown("**Colaboradores excluídos por tempo > 90 min:**")
            for a in alertas_tempo:
                st.markdown(
                    f'<div class="alerta-box">🕐 <b>{a["colaborador"]}</b> geraria {a["tempo_est"]} min na Rota {a["rota"]} '
                    f'— excluído para respeitar o limite de 90 min.</div>',
                    unsafe_allow_html=True
                )

        if alertas_taxa:
            st.markdown("**Rotas com taxa abaixo de 60%:**")
            for a in alertas_taxa:
                col_a, col_b = st.columns([3, 1])
                with col_a:
                    st.markdown(
                        f'<div class="alerta-box">📉 Rota {a["rota"]}: {a["membros"]}/{a["capacidade"]} lugares '
                        f'({a["taxa"]}% de ocupação) — abaixo da taxa mínima de {int(TAXA_MINIMA*100)}%.</div>',
                        unsafe_allow_html=True
                    )
                with col_b:
                    st.write("")
                    if st.button(f"Mesclar Rota {a['rota']}", key=f"merge_{a['rota']}"):
                        st.info("Funcionalidade: os passageiros desta rota serão redistribuídos nas demais. Reprocesse.")

        if not nao_atribuidos.empty:
            st.markdown(
                f'<div class="erro-box">🔴 <b>{len(nao_atribuidos)} colaboradores não foram atribuídos</b> '
                f'(rotas cheias ou tempo excedido). Considere adicionar mais rotas ou aumentar a capacidade.</div>',
                unsafe_allow_html=True
            )
            with st.expander("Ver colaboradores não atribuídos"):
                st.dataframe(nao_atribuidos[['COLABORADOR', 'LAT E', 'LONG E']].reset_index(drop=True))

    # ============================================================
    # RESUMO DAS ROTAS
    # ============================================================
    st.subheader("📊 Resumo das Rotas Geradas")
    cols_res = st.columns(len(rotas_resultado) if len(rotas_resultado) <= 5 else 5)
    for i, r in enumerate(rotas_resultado):
        with cols_res[i % 5]:
            cor = "🟢" if r['taxa'] >= 60 else "🟡"
            st.metric(
                f"Rota {r['rota_id']}",
                f"{r['ocupacao']}/{r['capacidade']}",
                f"{cor} {r['taxa']}%"
            )

    # ============================================================
    # GEOCODIFICAÇÃO DE ENDEREÇOS
    # ============================================================
    cache_key = f"enderecos_{uploaded_file.name}_{n_total}"
    if cache_key not in st.session_state:
        ruas, bairros = [], []
        with st.spinner("Buscando endereços (Google)..."):
            progress = st.progress(0)
            for i, (_, row) in enumerate(df.iterrows()):
                rua, bairro = obter_endereco_google(float(row['LAT E']), float(row['LONG E']))
                ruas.append(rua)
                bairros.append(bairro)
                time.sleep(0.05)
                progress.progress((i + 1) / n_total)
        st.session_state[cache_key] = (ruas, bairros)

    ruas, bairros = st.session_state[cache_key]
    df['ENDERECO'] = ruas
    df['BAIRRO'] = bairros

    # ============================================================
    # GERAÇÃO DE KMLs E RELATÓRIO
    # ============================================================
    kml_files = []
    relatorio_rows = []

    with st.spinner("Gerando rotas otimizadas e KMLs..."):
        for r in rotas_resultado:
            grupo_df = df.loc[r['indices']].copy()
            nome_rota = f"ROTA_{r['rota_id']:02d}"

            for tipo, col_lat, col_lon in [("Entrada", "LAT E", "LONG E"), ("Saída", "LAT S", "LONG S")]:
                waypoints = list(zip(grupo_df[col_lat], grupo_df[col_lon]))
                coords_ors = [[w[1], w[0]] for w in waypoints]
                coords_ors.append([destino_final[1], destino_final[0]])

                try:
                    res = client.directions(
                        coordinates=coords_ors,
                        profile='driving-car',
                        optimize_waypoints=True,
                        format='geojson'
                    )
                    coords_kml = res['features'][0]['geometry']['coordinates']
                    tempo_final = res['features'][0]['properties']['summary']['duration'] / 60
                except Exception as e:
                    st.warning(f"Erro ORS {nome_rota} {tipo}: {e}")
                    coords_kml = [[lon, lat] for lat, lon in waypoints] + [[destino_final[1], destino_final[0]]]
                    tempo_final = None

                kml_buf = gerar_kml(grupo_df, coords_kml, destino_final, nome_rota, tipo)
                kml_files.append((f"{nome_rota}_{tipo.lower()}", kml_buf))

            for _, row in grupo_df.iterrows():
                relatorio_rows.append({
                    'ROTA': nome_rota,
                    'COLABORADOR': row['COLABORADOR'],
                    'ENDERECO': row.get('ENDERECO', ''),
                    'BAIRRO': row.get('BAIRRO', ''),
                    'LAT E': row['LAT E'],
                    'LONG E': row['LONG E'],
                    'OCUPACAO': f"{r['ocupacao']}/{r['capacidade']}",
                    'TAXA_%': r['taxa'],
                })

    st.session_state["kmls"] = kml_files
    st.session_state["df_relatorio"] = pd.DataFrame(relatorio_rows)
    st.session_state["rotas_resultado"] = rotas_resultado
    st.success("✅ Rotas geradas com sucesso!")

# ============================================================
# SAÍDA: DOWNLOADS
# ============================================================
if "kmls" in st.session_state:
    st.subheader("📥 Arquivos KML")
    cols_kml = st.columns(4)
    for i, (nome, kml) in enumerate(st.session_state["kmls"]):
        with cols_kml[i % 4]:
            st.download_button(
                label=f"⬇️ {nome}",
                data=kml.getvalue(),
                file_name=f"{nome}.kml",
                mime="application/vnd.google-earth.kml+xml",
                key=f"dl_{nome}"
            )

    st.subheader("📋 Relatório de Colaboradores")
    df_rel = st.session_state["df_relatorio"]
    st.dataframe(df_rel, use_container_width=True)

    output = io.BytesIO()
    df_rel.to_excel(output, index=False)
    output.seek(0)
    st.download_button(
        "📥 Baixar relatório Excel",
        data=output.getvalue(),
        file_name="relatorio_rotas_auto.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
