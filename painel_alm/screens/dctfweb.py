import streamlit as st
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'lib'))
import db
from dctfweb_conciliacao import conciliar_via_upload

st.title("🧾 Conciliação FGTS / DCTFWEB")
st.caption(
    "Extrai FGTS e INSS do extrato analítico e concilia contra as guias liberadas "
    "(FGTS e DCTFWEB). Envie os PDFs abaixo — não salva nada, recalcula toda vez que você clicar em Conciliar."
)

col1, col2, col3 = st.columns(3)
with col1:
    arquivos_extratos = st.file_uploader(
        "Extratos analíticos", type="pdf", accept_multiple_files=True, key="up_extratos"
    )
with col2:
    arquivos_guias_fgts = st.file_uploader(
        "Guias FGTS (GFD) — opcional, envie as que já tiver liberado",
        type="pdf", accept_multiple_files=True, key="up_fgts"
    )
with col3:
    arquivos_guias_dctf = st.file_uploader(
        "Guias DCTFWEB — opcional, envie as que já tiver liberado",
        type="pdf", accept_multiple_files=True, key="up_dctf"
    )

if st.button("🔍 Conciliar", type="primary", disabled=not arquivos_extratos):
    clientes = db.listar_clientes()
    with st.spinner("Lendo PDFs e conciliando..."):
        resultados, avisos = conciliar_via_upload(arquivos_extratos, arquivos_guias_fgts, arquivos_guias_dctf, clientes)

    if not resultados:
        st.error("Não consegui montar nenhum resultado. Confere os avisos abaixo.")
    else:
        def contar(campo):
            c = {"OK": 0, "X": 0, "-": 0, "?": 0, "!": 0}
            for r in resultados:
                c[r[campo]] = c.get(r[campo], 0) + 1
            return c

        c_fgts = contar("status_fgts")
        c_dctf = contar("status_dctf")

        st.markdown("**FGTS**")
        f1, f2, f3 = st.columns(3)
        f1.metric("✅ OK", c_fgts.get("OK", 0))
        f2.metric("❌ Divergente", c_fgts.get("X", 0))
        f3.metric("➖ Sem guia ainda", c_fgts.get("-", 0))

        st.markdown("**DCTFWEB (INSS)**")
        d1, d2, d3 = st.columns(3)
        d1.metric("✅ OK", c_dctf.get("OK", 0))
        d2.metric("❌ Divergente", c_dctf.get("X", 0))
        d3.metric("➖ Sem guia ainda", c_dctf.get("-", 0))

        st.divider()

        cor = {"OK": "d4f5dd", "X": "f8d7da", "-": "eeeeee", "?": "fff3cd", "!": "ffb3b3"}
        icone = {"OK": "✅", "X": "❌", "-": "➖", "?": "⚠️", "!": "🔴 ERRO EXTRAÇÃO"}

        def fmt(v):
            return f"{v:.2f}".replace(".", ",") if v is not None else "-"

        table_html = "<table style='width:100%; border-collapse: collapse; font-size:0.9em;'>"
        table_html += (
            "<tr style='font-weight:bold; border-bottom: 2px solid #333;'>"
            "<td style='padding:6px;'>Cód.</td><td style='padding:6px;'>Empresa</td><td style='padding:6px;'>CNPJ</td>"
            "<td style='padding:6px;'>Valor FGTS</td><td style='padding:6px;'>Guia FGTS</td>"
            "<td style='padding:6px;'>Status FGTS</td>"
            "<td style='padding:6px;'>Esperado INSS+IRRF</td><td style='padding:6px;'>Guia DCTFWEB</td>"
            "<td style='padding:6px;'>Status DCTFWEB</td></tr>"
        )
        for r in resultados:
            table_html += (
                "<tr style='border-bottom:1px solid #ddd;'>"
                f"<td style='padding:6px;'>{r['codigo'] if r['codigo'] is not None else '-'}</td>"
                f"<td style='padding:6px;'>{r['empresa']}</td>"
                f"<td style='padding:6px;'>{r['cnpj']}</td>"
                f"<td style='padding:6px;'>{fmt(r['valor_fgts'])}</td>"
                f"<td style='padding:6px;'>{fmt(r['guia_fgts'])}</td>"
                f"<td style='padding:6px; background-color:#{cor[r['status_fgts']]};'>{icone[r['status_fgts']]} {r['status_fgts']}</td>"
                f"<td style='padding:6px;'>{fmt(r['esperado_inss'])}</td>"
                f"<td style='padding:6px;'>{fmt(r['guia_dctf'])}</td>"
                f"<td style='padding:6px; background-color:#{cor[r['status_dctf']]};'>{icone[r['status_dctf']]} {r['status_dctf']}</td>"
                "</tr>"
            )
        table_html += "</table>"
        st.markdown(table_html, unsafe_allow_html=True)

        if avisos:
            st.divider()
            with st.expander(f"⚠️ Avisos ({len(avisos)})"):
                for a in avisos:
                    st.write(f"- {a}")
