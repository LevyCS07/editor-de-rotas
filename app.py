with st.sidebar:
    st.header("⚙️ Editor de Rotas")

    # Upload
    with st.expander("📂 Upload de arquivos", expanded=True):
        uploaded_kmls = st.file_uploader("Upload dos KMLs", type=["kml"], accept_multiple_files=True)
        uploaded_xlsx = st.file_uploader("Upload da relação de colaboradores (XLSX)", type=["xlsx"])

    # Controle de rotas
    with st.expander("🛣️ Rotas disponíveis", expanded=False):
        todas = st.checkbox("Ativar/Desativar todas", value=True)
        rotas_selecionadas = []
        for nome in rotas.keys():
            if todas or st.checkbox(f"Mostrar rota {nome}", value=False):
                rotas_selecionadas.append(nome)

    # Resumo
    with st.expander("📊 Resumo por rota", expanded=False):
        if not colaboradores.empty:
            resumo = colaboradores.groupby("ROTA")["COLABORADORES"].count().reset_index()
            resumo.columns = ["Rota", "Qtd Colaboradores"]
            st.table(resumo)

    # Edição
    with st.expander("✏️ Edição de rotas", expanded=False):
        if not colaboradores.empty and rotas:
            colab_escolhido = st.selectbox("Selecione o colaborador", colaboradores["COLABORADORES"])
            nova_rota = st.selectbox("Selecione a nova rota", list(rotas.keys()))
            if st.button("Transferir"):
                idx = colaboradores[colaboradores["COLABORADORES"] == colab_escolhido].index[0]
                st.session_state["colaboradores"].at[idx, "ROTA"] = nova_rota
                st.success(f"Colaborador {colab_escolhido} transferido para rota {nova_rota}.")



