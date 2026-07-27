import streamlit as st
import sys
import os
from datetime import datetime

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'lib'))
from clientes_data import SEED_CLIENTES
import db
from extrato_ui import render_empresa_panel, donut_html

db.seed_clientes_se_vazio([
    {'codigo': c[0], 'empresa': c[1], 'nome': c[2], 'cnpj': c[3]} for c in SEED_CLIENTES
])
CLIENTES = db.listar_clientes()

st.title("💰 Extratos bancários - OFX")
st.caption(
    "Cada rosca mostra quantos meses já deveriam estar importados (até o mês anterior, "
    "o corrente ainda não conta) já foram feitos. 🟢 perto de 100% = em dia, 🔴 = atrasado."
)

ano_atual = datetime.now().year
ano = st.selectbox("Ano", list(range(ano_atual + 1, ano_atual - 4, -1)), index=1)

st.divider()

busca = st.text_input("🔎 Filtrar empresa", "")

for idx, c in enumerate(CLIENTES):
    codigo, empresa, nome, cnpj = c['codigo'], c['empresa'], c['nome'] or '', c['cnpj']
    if busca and busca.lower() not in empresa.lower() and busca.lower() not in nome.lower():
        continue

    percentual, feitos, devidos = db.percentual_completude(empresa, ano)

    col_donut, col_info = st.columns([1, 5])
    with col_donut:
        st.markdown(donut_html(percentual, feitos, devidos), unsafe_allow_html=True)
    with col_info:
        st.markdown(f"**{codigo} — {empresa}** <span style='color:#888; font-size:0.85em;'>({nome})</span>",
                    unsafe_allow_html=True)
        with st.expander("▶ Ver lançamentos / importar PDF"):
            render_empresa_panel(empresa, cnpj, key_prefix=f"emp_{idx}")

    st.write("")
