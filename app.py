import uuid
import string
import random
import pandas as pd
import streamlit as st
import plotly.express as px
from datetime import date
from dateutil.relativedelta import relativedelta
from streamlit_gsheets import GSheetsConnection
import streamlit_authenticator as stauth

# ==========================================
# CONFIGURAÇÕES DA PÁGINA E CONSTANTES
# ==========================================
st.set_page_config(page_title="Finanças em Família", page_icon="💰", layout="wide")

TIPOS_LANCAMENTO = ["🔴 Despesa", "🟢 Receita", "🔵 Reserva"]

# NOVAS CATEGORIAS GRANULARES
CATEGORIAS_DESPESA = [
    "Mercado", "Farmácia", "Aluguel", "Condomínio", "Conta de Luz", 
    "Conta de Água", "Gás", "Internet / Telefone", "Transporte / Combustível", 
    "Lazer / Restaurante", "Saúde / Convênio", "Educação", "Outros"
]
CATEGORIAS_RECEITA = ["Salário", "Freelance", "Rendimentos / Juros", "Outros"]
CATEGORIAS_RESERVA = ["Cofrinho / Poupança", "Reserva de Emergência", "Investimentos"]

COLUNAS_USUARIOS = ["email", "username", "nome", "senha_hash", "is_admin"]
COLUNAS_GRUPOS = ["id_grupo", "nome_grupo", "email_criador", "data_criacao"]
COLUNAS_MEMBROS = ["id_grupo", "email_usuario", "status"]
COLUNAS_LANCAMENTOS = [
    "id_transacao", "email_usuario", "tipo", "escopo", "id_grupo",
    "descricao", "valor", "data", "parcela_atual", "total_parcelas", "categoria"
]

# ==========================================
# CAMADA DE DADOS E CONEXÃO (I/O)
# ==========================================
@st.cache_resource
def get_connection() -> GSheetsConnection:
    return st.connection("gsheets", type=GSheetsConnection)

@st.cache_data(ttl=3600)
def carregar_tabela(_conn: GSheetsConnection, nome_aba: str, colunas: list) -> pd.DataFrame:
    try:
        df = _conn.read(worksheet=nome_aba, usecols=list(range(len(colunas))))
        if df.empty or len(df.columns) == 0:
            return pd.DataFrame(columns=colunas)
        return df
    except Exception as e:
        st.error(f"Erro ao carregar a aba {nome_aba}: {e}")
        return pd.DataFrame(columns=colunas)

def salvar_dados(conn: GSheetsConnection, df: pd.DataFrame, nome_aba: str) -> None:
    try:
        conn.update(worksheet=nome_aba, data=df)
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Erro crítico ao salvar em {nome_aba}: {e}")

# ==========================================
# LÓGICA DE NEGÓCIO E SEGURANÇA (CORE)
# ==========================================
def aplicar_rls(df_lancamentos: pd.DataFrame, df_membros: pd.DataFrame, email_logado: str) -> pd.DataFrame:
    if df_lancamentos.empty:
        return df_lancamentos

    grupos_ativos = df_membros[
        (df_membros['email_usuario'] == email_logado) & 
        (df_membros['status'] == 'Ativo')
    ]['id_grupo'].tolist()

    mascara = (
        (df_lancamentos['email_usuario'] == email_logado) |
        ((df_lancamentos['escopo'] == 'Grupo') & (df_lancamentos['id_grupo'].isin(grupos_ativos)))
    )
    
    df_seguro = df_lancamentos[mascara].copy()
    df_seguro['data'] = pd.to_datetime(df_seguro['data'], errors='coerce')
    df_seguro['valor'] = pd.to_numeric(df_seguro['valor'], errors='coerce').fillna(0.0)
    
    return df_seguro

def gerar_senha_aleatoria(tamanho=8) -> str:
    caracteres = string.ascii_letters + string.digits
    return ''.join(random.choice(caracteres) for i in range(tamanho))

def registrar_novo_usuario(conn: GSheetsConnection, df_usuarios: pd.DataFrame):
    with st.expander("🆕 Não tem uma conta? Cadastre-se aqui"):
        with st.form("form_registro", clear_on_submit=True):
            novo_nome = st.text_input("Qual o seu nome?")
            # UX: Removido o campo username, focando apenas no E-mail
            novo_email = st.text_input("Seu E-mail (Este será seu login)").strip().lower()
            nova_senha = st.text_input("Crie uma Senha", type="password")
            confirmar_senha = st.text_input("Confirme a Senha", type="password")
            submit = st.form_submit_button("Criar Minha Conta", use_container_width=True)
            
            if submit:
                if not (novo_nome and novo_email and nova_senha):
                    st.warning("⚠️ Preencha todos os campos.")
                    return
                if nova_senha != confirmar_senha:
                    st.error("❌ As senhas não coincidem.")
                    return
                if novo_email in df_usuarios["email"].values:
                    st.error("❌ Este e-mail já possui cadastro.")
                    return
                
                credenciais_temp = {"usernames": {"temp": {"password": nova_senha}}}
                stauth.Hasher.hash_passwords(credenciais_temp)
                senha_criptografada = credenciais_temp["usernames"]["temp"]["password"]
                
                novo_registro = pd.DataFrame([{
                    "email": novo_email, 
                    "username": novo_email, # Preenchemos username com email para integridade da tabela
                    "nome": novo_nome,
                    "senha_hash": senha_criptografada, 
                    "is_admin": "NAO"
                }])
                
                df_final = pd.concat([df_usuarios, novo_registro], ignore_index=True)
                salvar_dados(conn, df_final, "Usuarios")
                st.success("✅ Conta criada! Suba a página e faça login com seu E-mail.")
                st.rerun()

# ==========================================
# COMPONENTES DE UI
# ==========================================
def renderizar_aba_admin(conn, df_usuarios):
    st.markdown("### 🛠️ Painel de Administração")
    st.write("#### Redefinir Senha de Usuários")
    usuario_selecionado = st.selectbox("Selecione o e-mail do usuário:", df_usuarios['email'].tolist())
    
    if st.button("Gerar Nova Senha", type="primary"):
        nova_senha = gerar_senha_aleatoria()
        credenciais_temp = {"usernames": {"temp": {"password": nova_senha}}}
        stauth.Hasher.hash_passwords(credenciais_temp)
        senha_hash = credenciais_temp["usernames"]["temp"]["password"]
        
        idx = df_usuarios.index[df_usuarios['email'] == usuario_selecionado].tolist()[0]
        df_usuarios.at[idx, 'senha_hash'] = senha_hash
        
        salvar_dados(conn, df_usuarios, "Usuarios")
        st.success(f"✅ Senha alterada com sucesso!")
        st.warning(f"Envie esta senha temporária para o usuário via WhatsApp: **{nova_senha}**")

def renderizar_aba_grupos(conn, df_grupos, df_membros, df_usuarios, email_logado):
    st.markdown("### 🏠 Minha Família e Grupos")
    col1, col2 = st.columns(2)
    
    with col1:
        st.write("#### 📥 Convites Pendentes")
        pendentes = df_membros[(df_membros['email_usuario'] == email_logado) & (df_membros['status'] == 'Pendente')]
        if pendentes.empty:
            st.info("Nenhum convite pendente.")
        else:
            for idx, row in pendentes.iterrows():
                nome_grupo = df_grupos[df_grupos['id_grupo'] == row['id_grupo']]['nome_grupo'].values[0]
                if st.button(f"Aceitar entrada no grupo: {nome_grupo}", key=f"btn_acc_{idx}", type="primary"):
                    df_membros.at[idx, 'status'] = 'Ativo'
                    salvar_dados(conn, df_membros, "Membros_Grupo")
                    st.success("Convite aceito!")
                    st.rerun()

    with col2:
        st.write("#### ➕ Criar Novo Cofre Compartilhado")
        with st.form("form_novo_grupo", clear_on_submit=True):
            nome_novo_grupo = st.text_input("Nome (ex: Despesas de Casa)")
            if st.form_submit_button("Criar Cofre"):
                if not nome_novo_grupo: return
                novo_id = str(uuid.uuid4())
                novo_grupo = pd.DataFrame([{"id_grupo": novo_id, "nome_grupo": nome_novo_grupo, "email_criador": email_logado, "data_criacao": str(date.today())}])
                novo_membro = pd.DataFrame([{"id_grupo": novo_id, "email_usuario": email_logado, "status": "Ativo"}])
                
                salvar_dados(conn, pd.concat([df_grupos, novo_grupo], ignore_index=True), "Grupos")
                salvar_dados(conn, pd.concat([df_membros, novo_membro], ignore_index=True), "Membros_Grupo")
                st.success("Cofre criado!")
                st.rerun()

    st.divider()
    st.write("#### ✉️ Convidar Membro para seu Cofre")
    meus_grupos_ids = df_grupos[df_grupos['email_criador'] == email_logado]['id_grupo'].tolist()
    if meus_grupos_ids:
        meus_grupos_nomes = df_grupos[df_grupos['id_grupo'].isin(meus_grupos_ids)]['nome_grupo'].tolist()
        grupo_sel = st.selectbox("Selecione o cofre", meus_grupos_nomes)
        id_grupo_sel = df_grupos[df_grupos['nome_grupo'] == grupo_sel]['id_grupo'].values[0]
        
        email_convidado = st.selectbox("E-mail do familiar", df_usuarios[df_usuarios['email'] != email_logado]['email'].tolist())
        
        if st.button("Enviar Convite"):
            existe = df_membros[(df_membros['id_grupo'] == id_grupo_sel) & (df_membros['email_usuario'] == email_convidado)]
            if not existe.empty:
                st.warning("Usuário já foi convidado ou é membro.")
            else:
                novo_convite = pd.DataFrame([{"id_grupo": id_grupo_sel, "email_usuario": email_convidado, "status": "Pendente"}])
                salvar_dados(conn, pd.concat([df_membros, novo_convite], ignore_index=True), "Membros_Grupo")
                st.success("Convite enviado!")
                st.rerun()
    else:
        st.info("Você precisa criar um cofre primeiro para convidar alguém.")

def renderizar_aba_lancamento(conn, df_lancamentos, df_grupos, df_membros, email_logado):
    st.markdown("### 📝 Registrar Movimentação")
    
    grupos_ativos_ids = df_membros[(df_membros['email_usuario'] == email_logado) & (df_membros['status'] == 'Ativo')]['id_grupo'].tolist()
    grupos_ativos_df = df_grupos[df_grupos['id_grupo'].isin(grupos_ativos_ids)]

    with st.form("form_lancamento", clear_on_submit=True):
        tipo_selecionado = st.radio("Tipo:", TIPOS_LANCAMENTO, horizontal=True)
        tipo = tipo_selecionado.split(" ")[1]
        
        col_escopo, col_grupo = st.columns(2)
        with col_escopo:
            escopo = st.radio("De onde saiu/entrou este dinheiro?", ["👤 Meu Dinheiro (Privado)", "🏠 Dinheiro da Casa (Cofre Compartilhado)"])
            escopo = "Privado" if "Meu Dinheiro" in escopo else "Grupo"
            
        with col_grupo:
            id_grupo_selecionado = ""
            if escopo == "Grupo":
                if grupos_ativos_df.empty:
                    st.error("Você não pertence a nenhum grupo. Vá em 'Grupos & Família' primeiro.")
                else:
                    nome_grupo_sel = st.selectbox("Para qual Cofre?", grupos_ativos_df['nome_grupo'].tolist())
                    id_grupo_selecionado = grupos_ativos_df[grupos_ativos_df['nome_grupo'] == nome_grupo_sel]['id_grupo'].values[0]

        col_cat, col_desc = st.columns(2)
        with col_cat:
            categoria_lista = CATEGORIAS_DESPESA if tipo == "Despesa" else CATEGORIAS_RECEITA if tipo == "Receita" else CATEGORIAS_RESERVA
            categoria = st.selectbox("Categoria", categoria_lista)
        with col_desc:
            descricao = st.text_input("Descrição Específica", placeholder="Ex: Compras no Carrefour, Conta referente a Maio...")
        
        col1, col2, col3 = st.columns(3)
        with col1: valor = st.number_input("Valor Total (R$)", min_value=0.01, format="%.2f")
        with col2: data_compra = st.date_input("Data do Ocorrido", format="DD/MM/YYYY")
        with col3: parcelas = st.number_input("Dividir em Parcelas?", min_value=1, max_value=48, value=1)
        
        if st.form_submit_button("Salvar Registro", use_container_width=True):
            if not descricao:
                st.warning("Preencha a descrição específica.")
                return
            if escopo == "Grupo" and not id_grupo_selecionado:
                st.warning("Selecione um cofre válido.")
                return

            registros = []
            valor_parcela = round(valor / parcelas, 2)
            for i in range(parcelas):
                registros.append({
                    "id_transacao": str(uuid.uuid4()), "email_usuario": email_logado,
                    "tipo": tipo, "escopo": escopo, "id_grupo": id_grupo_selecionado,
                    "descricao": f"{descricao} ({i+1}/{parcelas})" if parcelas > 1 else descricao,
                    "valor": valor_parcela, "data": data_compra + relativedelta(months=i),
                    "parcela_atual": i + 1, "total_parcelas": parcelas, "categoria": categoria
                })
            
            df_final = pd.concat([df_lancamentos, pd.DataFrame(registros)], ignore_index=True)
            salvar_dados(conn, df_final, "Lancamentos")
            st.success("✅ Registrado com sucesso!")
            st.rerun()

def renderizar_aba_dashboard(df_visivel: pd.DataFrame, df_grupos: pd.DataFrame, df_membros: pd.DataFrame, email_logado: str):
    st.markdown("### 📊 Inteligência Financeira")
    
    if df_visivel.empty:
        st.info("Nenhuma movimentação registrada no seu escopo de visão.")
        return

    df_visivel['mes_ano'] = df_visivel['data'].dt.strftime('%m/%Y')
    meses_disponiveis = df_visivel.sort_values('data', ascending=False)['mes_ano'].unique().tolist()
    mapa_grupos = dict(zip(df_grupos['id_grupo'], df_grupos['nome_grupo']))
    
    # FILTROS
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        mes_filtro = st.selectbox("📅 Período:", ["Todos os Meses"] + meses_disponiveis)
    with col_f2:
        escopo_filtro = st.selectbox("👁️ Visão de Escopo:", ["Geral (Tudo)", "Apenas Meu Dinheiro (Privado)", "Apenas Dinheiro da Casa (Cofres)"])

    df_filtrado = df_visivel.copy()
    if mes_filtro != "Todos os Meses":
        df_filtrado = df_filtrado[df_filtrado['mes_ano'] == mes_filtro]
        
    if escopo_filtro == "Apenas Meu Dinheiro (Privado)":
        df_filtrado = df_filtrado[(df_filtrado['escopo'] == 'Privado') & (df_filtrado['email_usuario'] == email_logado)]
    elif escopo_filtro == "Apenas Dinheiro da Casa (Cofres)":
        df_filtrado = df_filtrado[df_filtrado['escopo'] == 'Grupo']

    if df_filtrado.empty:
        st.warning("Nenhum dado encontrado para esta combinação de filtros.")
        return

    # KPIS
    t_rec = df_filtrado[df_filtrado['tipo'] == 'Receita']['valor'].sum()
    t_desp = df_filtrado[df_filtrado['tipo'] == 'Despesa']['valor'].sum()
    t_res = df_filtrado[df_filtrado['tipo'] == 'Reserva']['valor'].sum()
    saldo = t_rec - t_desp

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Entradas", f"R$ {t_rec:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    c2.metric("Saídas", f"R$ {t_desp:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    c3.metric("Saldo Líquido", f"R$ {saldo:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    c4.metric("Guardado", f"R$ {t_res:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    
    st.divider()

    # GRÁFICOS
    col_g1, col_g2 = st.columns(2)
    
    with col_g1:
        st.markdown("**Despesas por Categoria (Visão Granular)**")
        df_desp = df_filtrado[df_filtrado['tipo'] == 'Despesa']
        if not df_desp.empty:
            df_cat = df_desp.groupby("categoria", as_index=False)["valor"].sum()
            fig_pie = px.pie(df_cat, values='valor', names='categoria', hole=0.4, 
                             color_discrete_sequence=px.colors.sequential.RdBu)
            fig_pie.update_layout(margin=dict(t=0, b=0, l=0, r=0))
            st.plotly_chart(fig_pie, use_container_width=True)
        else:
            st.info("Sem despesas registradas.")

    with col_g2:
        st.markdown("**Fluxo de Caixa no Tempo**")
        df_fluxo = df_filtrado[df_filtrado['tipo'].isin(['Receita', 'Despesa'])]
        if not df_fluxo.empty:
            df_tempo = df_fluxo.groupby(["mes_ano", "tipo"], as_index=False)["valor"].sum()
            fig_bar = px.bar(df_tempo, x='mes_ano', y='valor', color='tipo', barmode='group',
                             color_discrete_map={'Receita': '#2ca02c', 'Despesa': '#d62728'})
            fig_bar.update_layout(margin=dict(t=0, b=0, l=0, r=0), yaxis_title="R$", xaxis_title="", legend_title=None)
            st.plotly_chart(fig_bar, use_container_width=True)
        else:
            st.info("Sem fluxo registrado.")

    # TABELA DE DADOS
    with st.expander("🔎 Ver Histórico Detalhado (Tabela)"):
        df_display = df_filtrado[["data", "tipo", "escopo", "descricao", "categoria", "valor", "id_grupo"]].sort_values("data", ascending=False)
        df_display['data'] = df_display['data'].dt.strftime('%d/%m/%Y')
        df_display['valor'] = df_display.apply(lambda r: f"+ R$ {r['valor']:.2f}" if r['tipo'] in ['Receita', 'Reserva'] else f"- R$ {r['valor']:.2f}", axis=1)
        df_display['Cofre'] = df_display['id_grupo'].map(mapa_grupos).fillna("Privado")
        
        st.dataframe(df_display[["data", "tipo", "escopo", "Cofre", "categoria", "descricao", "valor"]], 
                     hide_index=True, use_container_width=True)

# ==========================================
# FLUXO PRINCIPAL DO APP
# ==========================================
def main():
    conn = get_connection()
    df_usuarios = carregar_tabela(conn, "Usuarios", COLUNAS_USUARIOS)
    
    credentials = {"usernames": {}}
    for _, row in df_usuarios.iterrows():
        # ARQUITETURA: Mapeando o e-mail como a chave mestre de login para o Authenticator
        credentials["usernames"][row["email"]] = {
            "name": row["nome"], "email": row["email"], "password": row["senha_hash"]
        }

    try:
        cookie_cfg = st.secrets["cookie"].to_dict()
    except KeyError:
        st.error("Configure os secrets do Streamlit (.streamlit/secrets.toml) para o cookie.")
        st.stop()

    authenticator = stauth.Authenticate(
        credentials=credentials, cookie_name=cookie_cfg['name'],
        key=cookie_cfg['key'], cookie_expiry_days=cookie_cfg['expiry_days']
    )

    # Injeção de dica de UI para avisar o usuário que o Username é o Email
    st.markdown("<style>#login-form label:first-of-type { visibility: hidden; position: relative; } #login-form label:first-of-type::after { visibility: visible; position: absolute; top: 0; left: 0; content: 'E-mail (Seu Login)'; color: #fafafa; }</style>", unsafe_allow_html=True)
    
    authenticator.login(location="main")

    if st.session_state.get("authentication_status"):
        email_logado = st.session_state["username"] # Agora recebe o e-mail
        user_info = df_usuarios[df_usuarios["email"] == email_logado].iloc[0]
        is_admin = str(user_info.get("is_admin", "NAO")).strip().upper() == "SIM"

        df_grupos = carregar_tabela(conn, "Grupos", COLUNAS_GRUPOS)
        df_membros = carregar_tabela(conn, "Membros_Grupo", COLUNAS_MEMBROS)
        df_lancamentos = carregar_tabela(conn, "Lancamentos", COLUNAS_LANCAMENTOS)
        
        df_lancamentos_seguro = aplicar_rls(df_lancamentos, df_membros, email_logado)

        # ==========================================
        # NOVO MENU LATERAL RESPONSIVO (SIDEBAR)
        # ==========================================
        st.sidebar.success(f"👋 Olá, {user_info['nome']}!")
        authenticator.logout("Sair", "sidebar")
        st.sidebar.markdown("---")
        
        abas_disponiveis = ["📝 Lançamentos", "📊 Dashboard", "🏠 Grupos & Família"]
        if is_admin:
            abas_disponiveis.append("🛠️ Admin")
            
        menu_selecionado = st.sidebar.radio("Menu de Navegação", abas_disponiveis)

        if menu_selecionado == "📝 Lançamentos":
            renderizar_aba_lancamento(conn, df_lancamentos, df_grupos, df_membros, email_logado)
        elif menu_selecionado == "📊 Dashboard":
            renderizar_aba_dashboard(df_lancamentos_seguro, df_grupos, df_membros, email_logado)
        elif menu_selecionado == "🏠 Grupos & Família":
            renderizar_aba_grupos(conn, df_grupos, df_membros, df_usuarios, email_logado)
        elif menu_selecionado == "🛠️ Admin" and is_admin:
            renderizar_aba_admin(conn, df_usuarios)

    elif st.session_state.get("authentication_status") is False:
        st.error("❌ E-mail ou senha incorretos.")
        registrar_novo_usuario(conn, df_usuarios)
    elif st.session_state.get("authentication_status") is None:
        st.warning("🔒 Digite seu E-mail e Senha para entrar.")
        registrar_novo_usuario(conn, df_usuarios)

if __name__ == "__main__":
    main()