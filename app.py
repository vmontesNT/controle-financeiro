import uuid
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
st.set_page_config(page_title="Nosso Controle", page_icon="💰", layout="centered")

# Novas Listas de Categorias
TIPOS_LANCAMENTO = ["🔴 Despesa (Gastei)", "🟢 Receita (Ganhei)", "🔵 Reserva (Guardei)"]
CATEGORIAS_DESPESA = ["Mercado", "Farmácia", "Casa", "Lazer", "Contas Fixas (Água/Luz)", "Empréstimo (Para Alguém)", "Outros"]
CATEGORIAS_RECEITA = ["Salário", "Freelance / Bicos", "Pagamento de Empréstimo (Recebi)", "Rendimentos", "Outros"]

# ATENÇÃO: Nova coluna 'tipo' adicionada na 3ª posição
COLUNAS_LANCAMENTOS = ["id", "email", "tipo", "descricao", "valor", "data", "parcela_atual", "total_parcelas", "categoria"]
COLUNAS_USUARIOS = ["username", "email", "nome", "senha_hash", "compartilhado_com"]

# ==========================================
# CAMADA DE DADOS E CONEXÃO
# ==========================================
@st.cache_resource
def get_connection() -> GSheetsConnection:
    return st.connection("gsheets", type=GSheetsConnection)

def carregar_tabela(conn: GSheetsConnection, nome_aba: str, colunas: list) -> pd.DataFrame:
    try:
        df = conn.read(worksheet=nome_aba, usecols=list(range(len(colunas))))
        if df.empty or len(df.columns) == 0:
            return pd.DataFrame(columns=colunas)
        
        if 'compartilhado_com' in df.columns:
            df['compartilhado_com'] = df['compartilhado_com'].fillna("")
            
        return df
    except Exception as e:
        st.error(f"Erro ao carregar a aba {nome_aba}. Detalhe técnico: {e}")
        return pd.DataFrame(columns=colunas)

def salvar_dados(conn: GSheetsConnection, df: pd.DataFrame, nome_aba: str) -> None:
    try:
        conn.update(worksheet=nome_aba, data=df)
        st.cache_data.clear() # Invalida o cache
    except Exception as e:
        st.error(f"Erro ao salvar informações: {e}")

# ==========================================
# LÓGICA DE NEGÓCIO E COMPONENTES
# ==========================================
def registrar_novo_usuario(conn: GSheetsConnection, df_usuarios: pd.DataFrame):
    with st.expander("🆕 Não tem uma conta? Cadastre-se aqui"):
        with st.form("form_registro", clear_on_submit=True):
            novo_nome = st.text_input("Qual o seu nome?")
            novo_email = st.text_input("Seu E-mail").strip().lower()
            novo_username = st.text_input("Escolha um Nome de Usuário (ex: maria123)").strip().lower()
            nova_senha = st.text_input("Crie uma Senha", type="password")
            confirmar_senha = st.text_input("Confirme a Senha", type="password")
            submit = st.form_submit_button("Criar Minha Conta", use_container_width=True)
            
            if submit:
                if not (novo_nome and novo_email and novo_username and nova_senha):
                    st.warning("⚠️ Preencha todos os campos.")
                    return
                if nova_senha != confirmar_senha:
                    st.error("❌ As senhas não coincidem.")
                    return
                if novo_username in df_usuarios["username"].values:
                    st.error("❌ Nome de usuário já existe.")
                    return
                if novo_email in df_usuarios["email"].values:
                    st.error("❌ E-mail já cadastrado.")
                    return
                
                credenciais_temp = {"usernames": {"temp": {"password": nova_senha}}}
                stauth.Hasher.hash_passwords(credenciais_temp)
                senha_criptografada = credenciais_temp["usernames"]["temp"]["password"]
                
                novo_registro = pd.DataFrame([{
                    "username": novo_username, "email": novo_email, "nome": novo_nome,
                    "senha_hash": senha_criptografada, "compartilhado_com": ""
                }])
                df_final = pd.concat([df_usuarios, novo_registro], ignore_index=True)
                salvar_dados(conn, df_final, "Usuarios")
                st.success("✅ Conta criada! Você já pode fazer login.")
                st.rerun()

def calcular_parcelas(email: str, tipo: str, descricao: str, valor_total: float, 
                      data_compra: date, parcelas: int, categoria: str) -> pd.DataFrame:
    registros = []
    valor_parcela = round(valor_total / parcelas, 2)
    for i in range(parcelas):
        data_parcela = data_compra + relativedelta(months=i)
        registros.append({
            "id": str(uuid.uuid4()), "email": email, "tipo": tipo,
            "descricao": f"{descricao} (Parcela {i+1} de {parcelas})" if parcelas > 1 else descricao,
            "valor": valor_parcela, "data": data_parcela,
            "parcela_atual": i + 1, "total_parcelas": parcelas, "categoria": categoria
        })
    return pd.DataFrame(registros)

def renderizar_aba_lancamento(conn: GSheetsConnection, df_atual: pd.DataFrame, email_usuario: str):
    st.markdown("### 📝 O que vamos anotar hoje?")
    
    # Seleção Dinâmica do Tipo de Lançamento
    tipo_selecionado = st.radio("Selecione o tipo:", TIPOS_LANCAMENTO, horizontal=True)
    tipo_limpo = tipo_selecionado.split(" ")[1] # Extrai apenas "Despesa", "Receita" ou "Reserva"
    
    with st.form("form_novo_gasto", clear_on_submit=True):
        descricao = st.text_input("Qual a descrição?", placeholder="Ex: Salário, Supermercado, Poupança...")
        
        # Filtra as categorias com base no tipo
        if tipo_limpo == "Despesa":
            categoria = st.selectbox("Categoria", CATEGORIAS_DESPESA)
        elif tipo_limpo == "Receita":
            categoria = st.selectbox("Categoria", CATEGORIAS_RECEITA)
        else:
            categoria = st.selectbox("Categoria", ["Reserva de Emergência"])
            
        col1, col2 = st.columns(2)
        with col1: valor = st.number_input("Valor total (R$)", min_value=0.01, format="%.2f")
        with col2: data_compra = st.date_input("Data")
            
        # Reservas raramente são parceladas, mas deixamos a opção livre
        parcelas = st.number_input("Dividir em quantas vezes?", min_value=1, max_value=48, value=1)
        submit = st.form_submit_button("Salvar Registro", use_container_width=True)
        
        if submit:
            if not descricao:
                st.warning("Informe a descrição.")
                return
            df_novas = calcular_parcelas(email_usuario, tipo_limpo, descricao, valor, data_compra, parcelas, categoria)
            df_final = pd.concat([df_atual, df_novas], ignore_index=True)
            salvar_dados(conn, df_final, "Lancamentos")
            st.success(f"✅ {tipo_limpo} registrada com sucesso!")
            st.rerun()

def renderizar_aba_dashboard(df: pd.DataFrame, email_filtro: str, titulo: str = "Painel Financeiro"):
    st.markdown(f"### 📊 {titulo}")
    
    # Tratamento de tipagem
    df['data'] = pd.to_datetime(df['data'], errors='coerce')
    df['valor'] = pd.to_numeric(df['valor'], errors='coerce').fillna(0.0)
    
    df_user = df[df["email"] == email_filtro].copy()
    if df_user.empty:
        st.info("Nenhum registro encontrado neste perfil.")
        return

    # CRIANDO DATAS NO PADRÃO BRASILEIRO E ORDENAÇÃO
    df_user['periodo_ordenacao'] = df_user['data'].dt.to_period('M') # Usado para o código não se perder na ordem
    df_user['mes_ano_br'] = df_user['data'].dt.strftime('%m/%Y')     # Usado para mostrar na tela (Ex: 04/2026)
    
    # === O NOVO FILTRO DE MÊS ===
    # Descobre os meses únicos e organiza do mais recente para o mais antigo
    meses_disponiveis = df_user['periodo_ordenacao'].drop_duplicates().sort_values(ascending=False)
    lista_meses_opcoes = [p.strftime('%m/%Y') for p in meses_disponiveis if pd.notnull(p)]
    
    mes_selecionado = st.selectbox("📅 Escolha o mês que deseja visualizar:", ["Todos os Meses"] + lista_meses_opcoes)
    
    # Aplica o filtro no banco de dados se não for "Todos"
    if mes_selecionado != "Todos os Meses":
        df_filtrado = df_user[df_user['mes_ano_br'] == mes_selecionado]
        st.markdown(f"**Visualizando o resumo de: {mes_selecionado}**")
    else:
        df_filtrado = df_user
        st.markdown("**Visualizando o histórico completo**")
    # ==============================
    
    # Cálculos Inteligentes AGORA USAM O DF FILTRADO
    total_receitas = df_filtrado[df_filtrado['tipo'] == 'Receita']['valor'].sum()
    total_despesas = df_filtrado[df_filtrado['tipo'] == 'Despesa']['valor'].sum()
    total_reservas = df_filtrado[df_filtrado['tipo'] == 'Reserva']['valor'].sum()
    saldo_livre = total_receitas - total_despesas

    # Exibição de Métricas (Grade 2x2 responsiva e sem cortar números)
    col1, col2 = st.columns(2)
    col1.metric("Entradas 🟢", f"R$ {total_receitas:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    col2.metric("Saídas 🔴", f"R$ {total_despesas:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    
    col3, col4 = st.columns(2)
    col3.metric("Saldo do Mês ⚖️", f"R$ {saldo_livre:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    col4.metric("Reservas 🔵", f"R$ {total_reservas:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    
    st.divider()

    col_graf1, col_graf2 = st.columns(2)
    with col_graf1:
        st.markdown("**Despesas por Categoria**")
        df_despesas = df_filtrado[df_filtrado['tipo'] == 'Despesa']
        if not df_despesas.empty:
            df_cat = df_despesas.groupby("categoria", as_index=False)["valor"].sum()
            fig_pizza = px.pie(df_cat, values='valor', names='categoria', hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
            fig_pizza.update_layout(margin=dict(t=0, b=0, l=0, r=0))
            st.plotly_chart(fig_pizza, use_container_width=True)
        else:
            st.info("Sem despesas para este período.")

    with col_graf2:
        st.markdown("**Fluxo de Caixa (Entradas vs Saídas)**")
        df_fluxo = df_filtrado[df_filtrado['tipo'].isin(['Receita', 'Despesa'])]
        if not df_fluxo.empty:
            # Agrupa usando a ordenação real, mas plota com o texto brasileiro
            df_mes = df_fluxo.groupby(["periodo_ordenacao", "mes_ano_br", "tipo"], as_index=False)["valor"].sum()
            df_mes = df_mes.sort_values("periodo_ordenacao")
            
            fig_barras = px.bar(df_mes, x='mes_ano_br', y='valor', color='tipo', barmode='group',
                                color_discrete_map={'Receita': '#2ca02c', 'Despesa': '#d62728'})
            
            fig_barras.update_xaxes(type='category') # Força o eixo X a respeitar o texto limpo
            fig_barras.update_layout(margin=dict(t=0, b=0, l=0, r=0), yaxis_title=None, xaxis_title=None, legend_title=None)
            st.plotly_chart(fig_barras, use_container_width=True)
        else:
            st.info("Sem fluxo para este período.")

    st.markdown("**Histórico de Movimentações**")
    df_view = df_filtrado[["data", "tipo", "descricao", "categoria", "valor"]].sort_values("data", ascending=False)
    # Formata a data de cada linha para o padrão do Brasil (DD/MM/YYYY)
    df_view['data'] = df_view['data'].dt.strftime('%d/%m/%Y')
    df_view['valor'] = df_view.apply(lambda row: f"+ R$ {row['valor']:.2f}" if row['tipo'] in ['Receita', 'Reserva'] else f"- R$ {row['valor']:.2f}", axis=1)
    
    st.dataframe(df_view, hide_index=True, use_container_width=True)

def renderizar_configuracoes(conn: GSheetsConnection, df_usuarios: pd.DataFrame, username_logado: str):
    st.markdown("### ⚙️ Quem pode ver seus dados?")
    st.write("Escolha membros da família para permitir que eles acompanhem seus gastos.")
    user_idx = df_usuarios.index[df_usuarios['username'] == username_logado].tolist()[0]
    string_compartilhamento = str(df_usuarios.at[user_idx, 'compartilhado_com'])
    lista_atual = [u.strip() for u in string_compartilhamento.split(',')] if string_compartilhamento else []
    
    outros_usuarios = df_usuarios[df_usuarios['username'] != username_logado]
    opcoes = outros_usuarios['username'].tolist()
    nomes_map = dict(zip(outros_usuarios['username'], outros_usuarios['nome']))
    
    selecionados = st.multiselect(
        "Membros autorizados:", options=opcoes, default=[u for u in lista_atual if u in opcoes],
        format_func=lambda x: nomes_map.get(x, x)
    )
    
    if st.button("Salvar Permissões", use_container_width=True):
        df_usuarios.at[user_idx, 'compartilhado_com'] = ",".join(selecionados)
        salvar_dados(conn, df_usuarios, "Usuarios")
        st.success("✅ Permissões atualizadas com sucesso!")

# ==========================================
# FLUXO PRINCIPAL (MAIN)
# ==========================================
def main():
    conn = get_connection()
    df_usuarios = carregar_tabela(conn, "Usuarios", COLUNAS_USUARIOS)
    
    credentials = {"usernames": {}}
    for _, row in df_usuarios.iterrows():
        credentials["usernames"][row["username"]] = {
            "name": row["nome"], "email": row["email"], "password": row["senha_hash"]
        }

    try: cookie_cfg = st.secrets["cookie"].to_dict()
    except KeyError: st.stop()

    authenticator = stauth.Authenticate(
        credentials=credentials, cookie_name=cookie_cfg['name'],
        key=cookie_cfg['key'], cookie_expiry_days=cookie_cfg['expiry_days']
    )

    authenticator.login(location="main")

    if st.session_state["authentication_status"]:
        username_logado = st.session_state["username"]
        email_usuario = credentials["usernames"][username_logado]["email"]
        nome_usuario = credentials["usernames"][username_logado]["name"]
        
        authenticator.logout("Sair", "sidebar")
        st.sidebar.success(f"👋 Olá, {nome_usuario}!")
        
        df_lancamentos = carregar_tabela(conn, "Lancamentos", COLUNAS_LANCAMENTOS)

        usuarios_que_compartilharam = []
        for _, row in df_usuarios.iterrows():
            compartilhamentos = [u.strip() for u in str(row['compartilhado_com']).split(',')] if pd.notna(row['compartilhado_com']) else []
            if username_logado in compartilhamentos:
                usuarios_que_compartilharam.append({"nome": row["nome"], "email": row["email"]})

        tabs_names = ["Lançar Dados", "Meu Dashboard"]
        if usuarios_que_compartilharam: tabs_names.append("Visualizar Família")
        tabs_names.append("⚙️ Configurações")

        tabs = st.tabs(tabs_names)

        with tabs[0]: renderizar_aba_lancamento(conn, df_lancamentos, email_usuario)
        with tabs[1]: renderizar_aba_dashboard(df_lancamentos, email_usuario)
        
        aba_atual = 2
        if usuarios_que_compartilharam:
            with tabs[aba_atual]:
                st.info("Estas pessoas liberaram o acesso para você.")
                opcoes_map = {u["nome"]: u["email"] for u in usuarios_que_compartilharam}
                pessoa_selecionada = st.selectbox("De quem você quer ver os dados?", list(opcoes_map.keys()))
                if pessoa_selecionada:
                    st.divider()
                    renderizar_aba_dashboard(df_lancamentos, opcoes_map[pessoa_selecionada], f"Visão Geral: {pessoa_selecionada}")
            aba_atual += 1
            
        with tabs[aba_atual]: renderizar_configuracoes(conn, df_usuarios, username_logado)
            
    elif st.session_state["authentication_status"] is False:
        st.error("❌ Usuário ou senha incorretos.")
        registrar_novo_usuario(conn, df_usuarios)
        
    elif st.session_state["authentication_status"] is None:
        st.warning("🔒 Digite seu usuário e senha para entrar.")
        registrar_novo_usuario(conn, df_usuarios)

if __name__ == "__main__":
    main()