import streamlit as st

try:
    USUARIO = st.secrets["usuario"]
    SENHA = st.secrets["senha"]
except Exception:
    USUARIO = "RH.ALM"
    SENHA = "123456"


def check_login():
    if "logado" not in st.session_state:
        st.session_state.logado = False

    if st.session_state.logado:
        return True

    st.title("🏢 Painel ALM Contabilidade")
    st.subheader("Login")
    with st.form("login_form"):
        usuario = st.text_input("Usuário")
        senha = st.text_input("Senha", type="password")
        entrar = st.form_submit_button("Entrar")

    if entrar:
        if usuario == USUARIO and senha == SENHA:
            st.session_state.logado = True
            st.rerun()
        else:
            st.error("Usuário ou senha incorretos.")
    return False


def logout_button():
    if st.sidebar.button("Sair"):
        st.session_state.logado = False
        st.rerun()
