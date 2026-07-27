import streamlit as st
import os

LOGO_PATH = os.path.join(os.path.dirname(__file__), '..', 'assets', 'logo.png')

st.write("")

st.markdown("<h2 style='text-align:left;'>🏢 Painel ALM Contabilidade</h2>", unsafe_allow_html=True)

st.write("")

if os.path.exists(LOGO_PATH):
    col_l, col_c, col_r = st.columns([1, 2, 1])
    with col_c:
        st.image(LOGO_PATH, use_container_width=True)

st.write("")

st.write("")
st.write("")

col1, col2, col3 = st.columns(3)
with col1:
    with st.container(border=True):
        st.page_link("screens/ferias.py", label="RH", icon="📋", use_container_width=True)
with col2:
    with st.container(border=True):
        st.page_link("screens/extratos_ofx.py", label="Contabilidade", icon="💰", use_container_width=True)
with col3:
    with st.container(border=True):
        st.page_link("screens/configuracoes.py", label="Configurações", icon="⚙️", use_container_width=True)
