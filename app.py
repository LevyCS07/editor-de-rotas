import streamlit as st
import pandas as pd
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
from lxml import etree
import io
from simplekml import Kml
from datetime import datetime
import plotly.express as px
import numpy as np

st.set_page_config(layout="wide", page_title="Editor de Rotas - Versão 4.0 Melhorada")

# Estado inicial com novas variáveis
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

# Paleta de cores para as rotas
CORES_ROTAS = ['red', 'blue', 'green', 'purple', 'orange', 'darkred', 
               'lightred', 'beige', 'darkblue', 'darkgreen', 'cadetblue', 
               'darkpurple', 'white', 'pink', 'lightblue', 'lightgreen', 
               'gray', 'black', 'lightgray']

# Função robusta para carregar KML
def carregar_kml(file):
    try:
        tree = etree.fromstring(file.read())
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

# Função de validação de colaboradores
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
    
    # Verificar rotas sem colaboradores
    if not st.session_state["rotas"].empty:
        rotas_sem_colab = set(st.session_state["rotas"].keys()) - set(df["ROTA"].unique())
        if rotas_sem_colab:
            avisos.append(f"⚠️ Rotas sem colaboradores: {', '.join(rotas_sem_colab)}")
    
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
    st.session_state["ultima_acao"] = f"✅ {colaborador} transferido de '{rota_antiga}' para '{rota_nova}'"

# --- Barra lateral ---
st.sidebar.header("⚙️ Editor de Rotas")

# Status e alertas
if st.session_state["ultima_acao"]:
    st.sidebar.success(st.session_state["ultima_acao"])

# Mostrar erros de validação
if st.session_state["erros_validacao"]:
    with st.sidebar.expander("❌ Erros de Validação", expanded=True):
        for erro in st.session_state["erros_validacao"]:
            st.error(erro)

with st.sidebar.expander("📂 Upload de arquivos", expanded=True):
    uploaded_kmls = st.file_uploader("Upload dos KMLs", type=["kml"], accept_multiple_files=True)
    uploaded_xlsx = st.file_uploader("Upload da relação de colaboradores (XLSX)", type=["xlsx"])

    col1, col2 = st.columns(2)
    with col1:
        if uploaded_xlsx and st.button("📥 Carregar Planilha"):
            try:
                df_novo = pd.read_excel(uploaded_xlsx, engine="openpyxl")
                erros, avisos = validar_colaboradores(df_novo)
                
                if avisos:
                    for aviso in avisos:
                        st.warning(aviso)
                
                if not erros:
                    st.session_state["colaboradores"] = df_novo
                    st.session_state["colaboradores_backup"] = df_novo.copy()
                    st.session_state["erros_validacao"] = []
                    st.success("✅ Planilha carregada com sucesso!")
                    st.rerun()
                else:
                    st.session_state["erros_validacao"] = erros
                    st.rerun()
            except Exception as e:
                st.error(f"Erro ao carregar planilha: {str(e)}")

    with col2:
        if st.button("🔄 Restaurar Backup"):
            if not st.session_state["colaboradores_backup"].empty:
                st.session_state["colaboradores"] = st.session_state["colaboradores_backup"].copy()
                st.success("✅ Backup restaurado!")
                st.rerun()
            else:
                st.warning("⚠️ Nenhum backup disponível")

    if uploaded_kmls:
        with st.spinner("Carregando KMLs..."):
            rotas = {}
            for file in uploaded_kmls:
                segmentos = carregar_kml(file)
                if segmentos:
                    rotas[file.name.replace(".kml", "")] = segmentos
            st.session_state["rotas"] = rotas
            st.success(f"✅ {len(rotas)} rotas carregadas!")

with st.sidebar.expander("🛣️ Rotas disponíveis", expanded=False):
    rotas_selecionadas = []
    if st.session_state["rotas"]:
        # Criar dicionário de cores para cada rota
        cores_rotas_dict = {}
        for i, nome in enumerate(st.session_state["rotas"].keys()):
            cores_rotas_dict[nome] = CORES_ROTAS[i % len(CORES_ROTAS)]
        
        todas = st.checkbox("Ativar/Desativar todas", value=True)
        for nome in st.session_state["rotas"].keys():
            col1, col2 = st.columns([1, 4])
            with col1:
                # Indicador de cor
                st.markdown(f"🟦" if cores_rotas_dict[nome] in ['blue', 'darkblue', 'cadetblue'] else f"🟥")
            with col2:
                if todas or st.checkbox(f"Mostrar rota {nome}", value=False, key=f"rota_{nome}"):
                    rotas_selecionadas.append(nome)

with st.sidebar.expander("📊 Resumo por rota", expanded=False):
    if not st.session_state["colaboradores"].empty:
        resumo = st.session_state["colaboradores"].groupby("ROTA")["COLABORADORES"].count().reset_index()
        resumo.columns = ["Rota", "Qtd Colaboradores"]
        
        # Adicionar gráfico de barras
        fig = px.bar(resumo, x="Rota", y="Qtd Colaboradores", 
                     title="Distribuição por Rota",
                     color="Rota", color_discrete_sequence=px.colors.qualitative.Set3)
        fig.update_layout(showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
        
        st.table(resumo)

with st.sidebar.expander("✏️ Edição de rotas", expanded=False):
    if st.session_state["selecionado"]:
        colaborador_info = st.session_state["colaboradores"][
            st.session_state["colaboradores"]["COLABORADORES"] == st.session_state["selecionado"]
        ].iloc[0]
        
        st.success(f"👤 Colaborador selecionado: **{st.session_state['selecionado']}**")
        st.info(f"📍 Rota atual: **{colaborador_info['ROTA']}**")
        
        nova_rota = st.selectbox("Nova rota", list(st.session_state["rotas"].keys()))
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ Transferir", use_container_width=True):
                idx = st.session_state["colaboradores"][
                    st.session_state["colaboradores"]["COLABORADORES"] == st.session_state["selecionado"]
                ].index[0]
                
                rota_antiga = st.session_state["colaboradores"].at[idx, "ROTA"]
                st.session_state["colaboradores"].at[idx, "ROTA"] = nova_rota
                
                # Adicionar ao histórico
                adicionar_ao_historico("Transferência", st.session_state["selecionado"], 
                                      rota_antiga, nova_rota)
                
                st.session_state["selecionado"] = None
                st.rerun()
        
        with col2:
            if st.button("❌ Cancelar", use_container_width=True):
                st.session_state["selecionado"] = None
                st.rerun()
    else:
        st.info("👆 Clique em um colaborador no mapa para editar")

with st.sidebar.expander("📜 Histórico de Alterações", expanded=False):
    if st.session_state["historico"]:
        for item in reversed(st.session_state["historico"][-10:]):  # Últimas 10 alterações
            st.text(f"🕐 {item['timestamp']}")
            st.text(f"👤 {item['colaborador']}")
            st.text(f"🔄 {item['rota_antiga']} → {item['rota_nova']}")
            st.divider()
        
        if st.button("Limpar Histórico"):
            st.session_state["historico"] = []
            st.rerun()
    else:
        st.info("Nenhuma alteração realizada ainda")

# --- Mapa ---
st.title("🗺️ Editor de Rotas - Visualização Interativa")

# Criar mapa base
m = folium.Map(location=[-3.119, -60.021], zoom_start=12)

# Dicionário para armazenar cores das rotas ativas
cores_ativas = {}

# Rotas com cores diferentes
if rotas_selecionadas:
    for i, nome in enumerate(rotas_selecionadas):
        cor = CORES_ROTAS[i % len(CORES_ROTAS)]
        cores_ativas[nome] = cor
        
        for segmento in st.session_state["rotas"][nome]:
            # Criar popup com informações da rota
            popup_text = f"""
            <b>Rota:</b> {nome}<br>
            <b>Cor:</b> {cor}<br>
            <b>Pontos:</b> {len(segmento)}
            """
            
            folium.PolyLine(
                segmento, 
                color=cor, 
                weight=4, 
                opacity=0.8,
                popup=popup_text,
                tooltip=f"Rota: {nome}"
            ).add_to(m)

# Colaboradores com cluster
if not st.session_state["colaboradores"].empty:
    cluster = MarkerCluster().add_to(m)
    
    for _, row in st.session_state["colaboradores"].iterrows():
        try:
            lat = float(str(row["LAT"]).replace(",", "."))
            lon = float(str(row["LONG"]).replace(",", "."))
            rota = row["ROTA"]
            colaborador = row["COLABORADORES"]
            
            # Verificar se deve mostrar (se a rota está selecionada ou nenhuma rota selecionada)
            if not rotas_selecionadas or rota in rotas_selecionadas:
                # Definir cor do marcador baseado na rota
                cor_marcador = cores_ativas.get(rota, 'blue')
                
                # Mapear cores do folium
                cor_folium = cor_marcador if cor_marcador in ['red', 'blue', 'green', 'purple', 
                                                             'orange', 'darkred', 'darkblue', 
                                                             'darkgreen', 'cadetblue'] else 'blue'
                
                # Criar popup rico
                popup_html = f"""
                <div style="font-family: Arial; padding: 5px;">
                    <b>👤 {colaborador}</b><br>
                    <b>📍 Rota:</b> {rota}<br>
                    <b>📌 Coordenadas:</b><br>
                    Lat: {lat:.6f}<br>
                    Lon: {lon:.6f}
                </div>
                """
                
                folium.Marker(
                    location=[lat, lon],
                    popup=folium.Popup(popup_html, max_width=300),
                    tooltip=colaborador,
                    icon=folium.Icon(color=cor_folium, icon="user", prefix="fa")
                ).add_to(cluster)
        except Exception as e:
            continue

# Adicionar legenda personalizada
legend_html = '''
<div style="position: fixed; bottom: 50px; left: 50px; z-index: 1000; background-color: white; padding: 10px; border-radius: 5px; border: 2px solid grey;">
    <p><b>Legenda</b></p>
'''
for rota, cor in cores_ativas.items():
    legend_html += f'<p><span style="color:{cor};">⬤</span> {rota}</p>'
legend_html += '</div>'

m.get_root().html.add_child(folium.Element(legend_html))

# ⚡ Renderizar mapa
map_data = st_folium(m, height=600, width=None, key="mapa")

# Capturar clique no colaborador
if map_data and map_data.get("last_object_clicked"):
    if map_data["last_object_clicked"].get("popup"):
        # Extrair nome do colaborador do popup
        popup_content = map_data["last_object_clicked"]["popup"]
        try:
            # Tentar extrair nome do HTML
            import re
            match = re.search(r'👤 (.*?)<br>', popup_content)
            if match:
                colaborador_nome = match.group(1)
                st.session_state["selecionado"] = colaborador_nome
                st.rerun()
        except:
            pass

# --- Exportação ---
st.divider()
col1, col2, col3 = st.columns(3)

with col1:
    st.subheader("📤 Exportar arquivos")
    if not st.session_state["colaboradores"].empty:
        buffer = io.BytesIO()
        st.session_state["colaboradores"].to_excel(buffer, index=False, engine="openpyxl")
        st.download_button(
            "📥 Baixar XLSX atualizado", 
            buffer.getvalue(), 
            file_name="colaboradores_editados.xlsx",
            use_container_width=True
        )

with col2:
    if st.session_state["rotas"]:
        kml = Kml()
        for i, (rota, segmentos) in enumerate(st.session_state["rotas"].items()):
            cor_hex = {'red': 'ff0000ff', 'blue': 'ff0000ff', 'green': 'ff00ff00'}.get(
                CORES_ROTAS[i % len(CORES_ROTAS)], 'ff0000ff'
            )
            for segmento in segmentos:
                ls = kml.newlinestring(name=rota, coords=[(lon, lat) for lat, lon in segmento])
                ls.style.linestyle.color = cor_hex
                ls.style.linestyle.width = 3
        kml_buffer = io.BytesIO(kml.kml().encode("utf-8"))
        st.download_button(
            "🗺️ Baixar KML atualizado", 
            kml_buffer.getvalue(), 
            file_name="rotas_editadas.kml",
            use_container_width=True
        )

with col3:
    if st.session_state["historico"]:
        # Criar relatório de alterações
        df_historico = pd.DataFrame(st.session_state["historico"])
        buffer_hist = io.BytesIO()
        df_historico.to_excel(buffer_hist, index=False, engine="openpyxl")
        st.download_button(
            "📊 Baixar Histórico", 
            buffer_hist.getvalue(), 
            file_name="historico_alteracoes.xlsx",
            use_container_width=True
        )

# Estatísticas rápidas no rodapé
if not st.session_state["colaboradores"].empty:
    st.divider()
    st.subheader("📊 Estatísticas Rápidas")
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Colaboradores", len(st.session_state["colaboradores"]))
    with col2:
        st.metric("Total Rotas", len(st.session_state["rotas"]))
    with col3:
        media_por_rota = len(st.session_state["colaboradores"]) / max(len(st.session_state["rotas"]), 1)
        st.metric("Média por Rota", f"{media_por_rota:.1f}")
    with col4:
        st.metric("Alterações Hoje", len([h for h in st.session_state["historico"] 
                                        if h['timestamp'].startswith(datetime.now().strftime("%d/%m/%Y"))]))
    
