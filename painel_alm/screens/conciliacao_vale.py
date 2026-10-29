import streamlit as st
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'lib'))
from conciliacao_vale import carregar, CSV

st.title("🍽️ Conciliação Vale Alimentação / Reembolso")
st.caption("Folha 10/2026 — relação do Domínio contra o valor devido pelos dias trabalhados.")

if not os.path.exists(CSV):
    st.error(f"Arquivo não encontrado: {CSV}")
    st.stop()

df = carregar()

c1, c2, c3 = st.columns(3)
c1.metric("Linhas", len(df))
c2.metric("OK", int((df["OK_NAO"] == "OK").sum()))
c3.metric("NÃO", int((df["OK_NAO"] == "NÃO").sum()))

filtro = st.radio("Mostrar", ["Todos", "Só NÃO", "Só OK"], horizontal=True)
empresa = st.selectbox("Empresa", ["Todas"] + sorted(df["Empresa"].unique()))

v = df.copy()
if filtro == "Só NÃO":
    v = v[v["OK_NAO"] == "NÃO"]
elif filtro == "Só OK":
    v = v[v["OK_NAO"] == "OK"]
if empresa != "Todas":
    v = v[v["Empresa"] == empresa]

st.dataframe(
    v.style.format({
        "Dias_trabalhados": "{:.0f}",
        "Valor_devido": "R$ {:,.2f}",
        "Valor_relacao": "R$ {:,.2f}",
        "Diferenca": "R$ {:,.2f}",
    }),
    use_container_width=True,
    hide_index=True,
)
st.caption(f"Diferença total no filtro: R$ {v['Diferenca'].sum():,.2f}")
