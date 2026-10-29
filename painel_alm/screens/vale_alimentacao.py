import streamlit as st
import sys
import os
import datetime as dt
import pandas as pd

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'lib'))
import vale_calc as V

st.title("🍽️ Vale Alimentação / Reembolso")
st.caption(
    "Suba a relação do Domínio e os recibos da folha do mês. A conciliação e os recibos "
    "são recalculados a cada clique — nada é salvo."
)

c1, c2 = st.columns(2)
competencia = c1.text_input("Competência", value="10/2026", help="mês/ano, ex.: 10/2026", key="va_comp")
feriados_txt = c2.text_input("Feriados (dd/mm/aaaa, separados por vírgula)", value="12/10/2026", key="va_fer")
try:
    feriados = {dt.datetime.strptime(x.strip(), "%d/%m/%Y").date() for x in feriados_txt.split(",") if x.strip()}
    mes, ano = (int(x) for x in competencia.split("/"))
except Exception:
    st.error("Confira a competência (mm/aaaa) e os feriados (dd/mm/aaaa).")
    st.stop()

u1, u2 = st.columns(2)
rel_files = u1.file_uploader("Relação de Vale Alimentação (PDF do Domínio)", type="pdf", accept_multiple_files=True, key="va_rel")
rec_files = u2.file_uploader("Recibos de pagamento da folha (PDF)", type="pdf", accept_multiple_files=True, key="va_rec")

st.subheader("Férias, rescisões e afastamentos")
st.caption("Só o que não é mês cheio. Empresa e funcionário como aparecem na relação.")
af_df = st.data_editor(
    pd.DataFrame(columns=["empresa", "funcionario", "tipo", "inicio", "fim"]),
    num_rows="dynamic",
    hide_index=True,
    column_config={
        "empresa": st.column_config.TextColumn("Empresa", required=True),
        "funcionario": st.column_config.TextColumn("Funcionário", required=True),
        "tipo": st.column_config.SelectboxColumn("Tipo", options=["Férias", "Rescisão", "Afastamento"], required=True),
        "inicio": st.column_config.DateColumn("Início (rescisão: data da rescisão)", format="DD/MM/YYYY", required=True),
        "fim": st.column_config.DateColumn("Fim", format="DD/MM/YYYY"),
    },
    key="afastamentos",
)

if st.button("Conciliar", type="primary", disabled=not (rel_files and rec_files)):
    try:
        relacao = []
        for f in rel_files:
            relacao += V.parse_relacao(V.extrair_texto(f.getvalue()))
        recibos = [V.parse_recibo(V.extrair_texto(f.getvalue()), f.name) for f in rec_files]
        afs = []
        for _, r in af_df.dropna(subset=["empresa", "funcionario", "tipo", "inicio"]).iterrows():
            fim = r["fim"] if pd.notna(r["fim"]) else r["inicio"]
            afs.append({"empresa": str(r["empresa"]), "funcionario": str(r["funcionario"]),
                        "tipo": r["tipo"], "inicio": r["inicio"], "fim": fim})
        st.session_state["vale_resultado"] = V.conciliar(relacao, recibos, afs, competencia, feriados)
        st.session_state["vale_recibos"] = recibos
    except Exception as e:
        st.error(f"Não consegui ler os arquivos: {e}")

res = st.session_state.get("vale_resultado")
if res:
    df = pd.DataFrame(res)
    n_ok = int((df["status"] == "OK").sum())
    n_nao = int((df["status"] == "NÃO").sum())
    m1, m2, m3 = st.columns(3)
    m1.metric("Linhas", len(df))
    m2.metric("OK", n_ok)
    m3.metric("NÃO", n_nao)

    filtro = st.radio("Mostrar", ["Todos", "Só NÃO", "Só OK"], horizontal=True, key="va_filtro")
    emp = st.selectbox("Empresa", ["Todas"] + sorted(df["empresa"].unique()), key="va_emp")
    v = df.copy()
    if filtro == "Só NÃO":
        v = v[v["status"] == "NÃO"]
    elif filtro == "Só OK":
        v = v[v["status"] == "OK"]
    if emp != "Todas":
        v = v[v["empresa"] == emp]
    st.dataframe(
        v[["empresa", "codigo", "funcionario", "verba", "dias", "devido", "valor_relacao", "diferenca", "status", "obs"]].rename(
            columns={"valor_relacao": "valor_relacao (R$)", "devido": "devido (R$)", "diferenca": "diferença (R$)"}),
        hide_index=True,
    )

    st.subheader("Recibos")
    if st.button("Gerar recibos (ZIP com um PDF por empresa)"):
        data, n = V.gerar_recibos_zip(res, competencia)
        st.session_state["vale_zip"] = (data, n)
    if st.session_state.get("vale_zip"):
        data, n = st.session_state["vale_zip"]
        st.download_button(f"Baixar recibos ({n} empresas)", data=data,
                           file_name=f"Recibos {competencia.replace('/', '.')}.zip", mime="application/zip")
