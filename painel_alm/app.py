import streamlit as st
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), 'lib'))
from auth import check_login, logout_button

st.set_page_config(page_title="Painel ALM", page_icon="🏢", layout="wide")

if not check_login():
    st.stop()

pages = {
    " ": [
        st.Page("screens/home.py", title="HOME", icon="🏠"),
    ],
    "RH": [
        st.Page("screens/ferias.py", title="Férias", icon="📋"),
        st.Page("screens/dctfweb.py", title="Conciliação FGTS/DCTFWEB", icon="🧾"),
    ],
    "Contabilidade": [
        st.Page("screens/extratos_ofx.py", title="Extratos OFX", icon="💰"),
    ],
    "  ": [
        st.Page("screens/configuracoes.py", title="Configurações", icon="⚙️"),
    ],
}

pg = st.navigation(pages, position="hidden")

with st.sidebar:
    st.markdown("""
        <style>
        [data-testid="stSidebar"] div[data-testid="stButton"] button {
            border: none;
            background: transparent;
            box-shadow: none;
            justify-content: flex-start;
            padding-left: 0.5rem;
            font-weight: 400;
        }
        [data-testid="stSidebar"] div[data-testid="stButton"] button p {
            text-align: left;
        }
        [data-testid="stSidebar"] div[data-testid="stButton"] button:hover {
            background: rgba(151, 166, 195, 0.15);
            color: inherit;
        }
        </style>
    """, unsafe_allow_html=True)

    st.page_link("screens/home.py", label="HOME", icon="🏠")

    if "show_rh" not in st.session_state:
        st.session_state.show_rh = False
    if "show_contab" not in st.session_state:
        st.session_state.show_contab = False

    seta_rh = "▾" if st.session_state.show_rh else "▸"
    if st.button(f"{seta_rh} RH", key="btn_rh", use_container_width=True):
        st.session_state.show_rh = not st.session_state.show_rh
        st.rerun()
    if st.session_state.show_rh:
        _, col_indent = st.columns([0.15, 0.85])
        with col_indent:
            st.page_link("screens/ferias.py", label="Férias", icon="📋")
            st.page_link("screens/dctfweb.py", label="Conciliação FGTS/DCTFWEB", icon="🧾")

    seta_contab = "▾" if st.session_state.show_contab else "▸"
    if st.button(f"{seta_contab} Contabilidade", key="btn_contab", use_container_width=True):
        st.session_state.show_contab = not st.session_state.show_contab
        st.rerun()
    if st.session_state.show_contab:
        _, col_indent = st.columns([0.15, 0.85])
        with col_indent:
            st.page_link("screens/extratos_ofx.py", label="Extratos OFX", icon="💰")

    st.page_link("screens/configuracoes.py", label="Configurações", icon="⚙️")

    st.divider()
    logout_button()

pg.run()




