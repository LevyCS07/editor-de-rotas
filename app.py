import streamlit as st
import pandas as pd
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from lxml import etree
import io
from simplekml import Kml, Color
from datetime import datetime
import re

st.set_page_config(layout="wide", page_title="Editor de Rotas - Versão 4.1 Estável")

# Estado inicial
if "colaboradores" not in st.session_state:
    st.session_state["colaboradores"] = pd.DataFrame()
if "colaboradores_backup" not in st.session_state:
    st.session_state["colaboradores_backup"] = pd.DataFrame()
if "rotas" not in st.session_state:
    st.session_state["rotas"] = {}
if "selecionado" not in st.session_state:
    st.session_state["selecionado"] = None
if "historico" not in st.session_state:
    st.session_state["historico"] = []
if "ultima_acao" not in st.session_state:
    st.session_state["ultima_acao"] = None
if "erros_validacao" not in st.session_state:
    st.session_state["erros_validacao"] = []
if "avisos_validacao" not in st.session_state:
    st.session_state["avisos_validacao"] = []

# Paleta de cores para as rotas
CORES_ROTAS = ['red', 'blue', 'green', 'purple', 'orange', 'darkred', 
               'lightred', 'darkblue', 'darkgreen', 'cadetblue', 
               'darkpurple', 'pink', 'lightblue', 'lightgreen', 
               'gray', 'black']

# Mapeamento de cores para hexadecimal (usado no KML)
CORES_HEX = {
    'red': 'ff0000ff',
    'blue': 'ffff0000',
    'green': 'ff00ff00',
    'purple': 'ff800080',
    'orange': 'ff00a5ff',
    'darkred': 'ff00008b',
    'lightred': 'ff8080ff',
    'darkblue': 'ff8b0000',
    'darkgreen': 'ff006400',
    'cadetblue': 'ffa09e5f',
    'darkpurple': 'ff800080',
    'pink': 'ffc0cbfe',
    'lightblue': 'ffe0d6ad',
    'lightgreen': 'ff90ee90',
    'gray': 'ff808080',
    'black': 'ff000000'
}

# Função para carregar KML
def carregar_kml(file):
    try:
        file_content = file.read()
        tree = etree.fromstring(file_content)
        ns = {"kml": "http://www.opengis.net/kml/2.2"}
        segmentos = []
        coords = tree.xpath("//kml:coordinates", namespaces=ns)
        for c in coords:
            coord_text = c.text.strip()
            pontos = []
            for pair in coord_text.split():
                lon, lat, *_ = pair.split(",")
                pontos.append((float(lat), float(lon)))
            if pontos:
                segmentos.append(pontos)
        return segmentos
    except Exception as e:
        st.error(f"Erro ao carregar KML: {str(e)}")
        return []

# Função de validação
def validar_colaboradores(df):
    erros = []
    avisos = []
    
    if df.empty:
        erros.append("❌ Nenhum colaborador encontrado")
        return erros, avisos
    
    # Verificar colunas obrigatórias
    colunas_obrigatorias = ["COLABORADORES", "LAT", "LONG", "ROTA"]
    for col in colunas_obrigatorias:
        if col not in df.columns:
            erros.append(f"❌ Coluna obrigatória '{col}' não encontrada")
    
    if erros:
        return erros, avisos
    
    # Validar dados
    if df["COLABORADORES"].isnull().any():
        erros.append("❌ Existem colaboradores sem nome")
    
    # Validar coordenadas
    coords_invalidas = 0
    for idx, row in df.iterrows():
        try:
            lat = float(str(row["LAT"]).replace(",", "."))
            lon = float(str(row["LONG"]).replace(",", "."))
            if lat < -90 or lat > 90 or lon < -180 or lon > 180:
                coords_invalidas += 1
        except:
            coords_invalidas += 1
    
    if coords_invalidas > 0:
        erros.append(f"❌ {coords_invalidas} colaborador(es) com coordenadas inválidas")
    
    # Verificar duplicatas
    duplicatas = df["COLABORADORES"].duplicated().sum()
    if duplicatas > 0:
        avisos.append(f"⚠️ {duplicatas} colaborador(es) duplicados encontrados")
    
    return erros, avisos

# Função para adicionar ao histórico
def adicionar_ao_historico(acao, colaborador, rota_antiga, rota_nova):
    st.session_state["historico"].append({
        "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
        "acao": acao,
        "colaborador": colaborador,
        "rota_antiga": rota_antiga,
        "rota_nova": rota_nova
    })
    st.session_state["ultima_acao"] = f"✅ {colaborador} transferido para {rota_nova}"

# Interface principal
st.title("🗺️ Editor de Rotas")
st.caption("Versão estável - compatível com Python 3.14")

# Sidebar
with st.sidebar:
    st.header("⚙️ Controles")
    
    # Upload de arquivos
    with st.expander("📂 Upload", expanded=True):
        uploaded_kmls = st.file_uploader("Arquivos KML (rotas)", type=["kml"], accept_multiple_files=True)
        uploaded_xlsx = st.file_uploader("Planilha de colaboradores (XLSX)", type=["xlsx"])
        
        # Carregar planilha
        if uploaded_xlsx and st.button("📥 Carregar Planilha", use_container_width=True):
            try:
                df_novo = pd.read_excel(uploaded_xlsx, engine="openpyxl")
                erros, avisos = validar_colaboradores(df_novo)
                
                if avisos:
                    st.session_state["avisos_validacao"] = avisos
                
                if not erros:
                    st.session_state["colaboradores"] = df_novo
                    st.session_state["colaboradores_backup"] = df_novo.copy()
                    st.session_state["erros_validacao"] = []
                    st.success("✅ Planilha carregada!")
                    st.rerun()
                else:
                    st.session_state["erros_validacao"] = erros
                    st.error("❌ Erros na validação")
            except Exception as e:
                st.error(f"Erro: {str(e)}")
        
        # Carregar KMLs
        if uploaded_kmls and st.button("🗺️ Carregar Rotas", use_container_width=True):
            with st.spinner("Processando KMLs..."):
                rotas = {}
                for file in uploaded_kmls:
                    segmentos = carregar_kml(file)
                    if segmentos:
                        nome_rota = file.name.replace(".kml", "")
                        rotas[nome_rota] = segmentos
                st.session_state["rotas"] = rotas
                st.success(f"✅ {len(rotas)} rotas carregadas!")
    
    # Mensagens de validação
    if st.session_state["erros_validacao"]:
        with st.expander("❌ Erros", expanded=True):
            for erro in st.session_state["erros_validacao"]:
                st.error(erro)
    
    if st.session_state["avisos_validacao"]:
        with st.expander("⚠️ Avisos", expanded=True):
            for aviso in st.session_state["avisos_validacao"]:
                st.warning(aviso)
    
    # Seleção de rotas
    if st.session_state["rotas"]:
        with st.expander("🛣️ Rotas", expanded=True):
            rotas_selecionadas = []
            todas = st.checkbox("Selecionar todas", value=True, key="todas_rotas")
            
            for i, nome in enumerate(st.session_state["rotas"].keys()):
                cor = CORES_ROTAS[i % len(CORES_ROTAS)]
                if todas or st.checkbox(f"{nome}", key=f"rota_{nome}"):
                    rotas_selecionadas.append((nome, cor))
    
    # Resumo
    if not st.session_state["colaboradores"].empty:
        with st.expander("📊 Resumo", expanded=False):
            resumo = st.session_state["colaboradores"].groupby("ROTA").size().reset_index()
            resumo.columns = ["Rota", "Qtd"]
            st.dataframe(resumo, use_container_width=True)
            
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Total Colab.", len(st.session_state["colaboradores"]))
            with col2:
                st.metric("Total Rotas", len(st.session_state["rotas"]))
    
    # Edição
    if st.session_state["selecionado"]:
        with st.expander("✏️ Editar", expanded=True):
            colaborador_info = st.session_state["colaboradores"][
                st.session_state["colaboradores"]["COLABORADORES"] == st.session_state["selecionado"]
            ].iloc[0]
            
            st.info(f"**Selecionado:** {st.session_state['selecionado']}")
            st.info(f"**Rota atual:** {colaborador_info['ROTA']}")
            
            if st.session_state["rotas"]:
                nova_rota = st.selectbox("Nova rota", list(st.session_state["rotas"].keys()))
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("✅ Transferir", use_container_width=True):
                        idx = st.session_state["colaboradores"][
                            st.session_state["colaboradores"]["COLABORADORES"] == st.session_state["selecionado"]
                        ].index[0]
                        
                        rota_antiga = st.session_state["colaboradores"].at[idx, "ROTA"]
                        st.session_state["colaboradores"].at[idx, "ROTA"] = nova_rota
                        
                        adicionar_ao_historico("Transferência", st.session_state["selecionado"], 
                                             rota_antiga, nova_rota)
                        
                        st.session_state["selecionado"] = None
                        st.rerun()
                
                with col2:
                    if st.button("❌ Cancelar", use_container_width=True):
                        st.session_state["selecionado"] = None
                        st.rerun()
    
    # Histórico
    if st.session_state["historico"]:
        with st.expander("📜 Histórico", expanded=False):
            for item in reversed(st.session_state["historico"][-5:]):
                st.caption(f"🕐 {item['timestamp']}")
                st.write(f"**{item['colaborador']}**")
                st.write(f"{item['rota_antiga']} → {item['rota_nova']}")
                st.divider()
            
            if st.button("Limpar histórico", use_container_width=True):
                st.session_state["historico"] = []
                st.rerun()

# Mapa
m = folium.Map(location=[-3.119, -60.021], zoom_start=12)

# Adicionar rotas
if 'rotas_selecionadas' in locals() and rotas_selecionadas:
    for nome, cor in rotas_selecionadas:
        for segmento in st.session_state["rotas"][nome]:
            folium.PolyLine(
                segmento,
                color=cor,
                weight=3,
                opacity=0.8,
                popup=f"Rota: {nome}",
                tooltip=nome
            ).add_to(m)

# Adicionar colaboradores
if not st.session_state["colaboradores"].empty:
    marker_cluster = MarkerCluster().add_to(m)
    
    for _, row in st.session_state["colaboradores"].iterrows():
        try:
            lat = float(str(row["LAT"]).replace(",", "."))
            lon = float(str(row["LONG"]).replace(",", "."))
            nome = row["COLABORADORES"]
            rota = row["ROTA"]
            
            folium.Marker(
                [lat, lon],
                popup=nome,
                tooltip=nome,
                icon=folium.Icon(color='blue', icon='info-sign')
            ).add_to(marker_cluster)
        except:
            continue

# Renderizar mapa
map_data = st_folium(m, height=600, width=None, key="mapa")

# Capturar clique
if map_data and map_data.get("last_object_clicked"):
    if map_data["last_object_clicked"].get("popup"):
        st.session_state["selecionado"] = map_data["last_object_clicked"]["popup"]
        st.rerun()

# Exportação
if not st.session_state["colaboradores"].empty:
    st.divider()
    col1, col2 = st.columns(2)
    
    with col1:
        buffer = io.BytesIO()
        st.session_state["colaboradores"].to_excel(buffer, index=False, engine="openpyxl")
        st.download_button(
            "📥 Baixar XLSX",
            buffer.getvalue(),
            "colaboradores_editados.xlsx",
            use_container_width=True
        )
    
    with col2:
        if st.session_state["rotas"]:
            kml = Kml()
            for i, (nome, segmentos) in enumerate(st.session_state["rotas"].items()):
                cor = CORES_ROTAS[i % len(CORES_ROTAS)]
                cor_hex = CORES_HEX.get(cor, 'ff0000ff')
                
                for segmento in segmentos:
                    ls = kml.newlinestring(
                        name=nome,
                        coords=[(lon, lat) for lat, lon in segmento]
                    )
                    ls.style.linestyle.color = cor_hex
                    ls.style.linestyle.width = 3
            
            kml_buffer = io.BytesIO()
            kml_buffer.write(kml.kml().encode('utf-8'))
            kml_buffer.seek(0)
            
            st.download_button(
                "🗺️ Baixar KML",
                kml_buffer.getvalue(),
                "rotas_editadas.kml",
                use_container_width=True
            )
