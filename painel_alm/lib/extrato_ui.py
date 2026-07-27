import streamlit as st
import os
import re
import tempfile
from datetime import datetime
from collections import defaultdict

import bank_parsers as bp
from ofx_builder import build_ofx
from ocr_reader import has_extractable_text, ocr_extract_lines
from clientes_data import find_empresa_by_cnpj
import db

MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
         'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']
MESES_ABREV = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez']


def detect_bank(text):
    t = text or ''
    if 'Lançamentos do período' in t and 'CNPJ' in t and 'Agência' in t:
        return 'itau'
    if 'Stone Instituição de Pagamento' in t or ('Stone' in t and 'Instituição' in t):
        return 'stone'
    if 'SICOOB' in t.upper() or 'SISBR' in t.upper():
        return 'sicoob'
    if 'bradesco' in t.lower() or 'net empresa' in t.lower():
        return 'bradesco'
    return None


def save_temp(pdf_bytes, suffix='.pdf'):
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, 'wb') as f:
        f.write(pdf_bytes)
    return path


def donut_html(percentual, meses_feitos, meses_devidos, size=90):
    """Rosca (donut) de % de completude, feita só com CSS (conic-gradient) — leve
    o bastante pra desenhar dezenas delas na mesma página sem travar."""
    if percentual is None:
        return (
            f"<div style='width:{size}px; height:{size}px; border-radius:50%; "
            f"background:#eee; display:flex; align-items:center; justify-content:center; "
            f"font-size:0.75em; color:#999;'>—</div>"
        )

    # verde (120) quando 100%, passando por amarelo/laranja até vermelho (0) quando 0%
    hue = int(120 * (percentual / 100))
    cor = f'hsl({hue}, 70%, 45%)'
    ang = percentual * 3.6

    return f"""
    <div style='display:flex; flex-direction:column; align-items:center; width:{size+20}px;'>
      <div style='width:{size}px; height:{size}px; border-radius:50%;
                  background: conic-gradient({cor} 0deg {ang}deg, #e0e0e0 {ang}deg 360deg);
                  display:flex; align-items:center; justify-content:center;'>
        <div style='width:{int(size*0.68)}px; height:{int(size*0.68)}px; border-radius:50%;
                    background:white; display:flex; align-items:center; justify-content:center;
                    font-weight:bold; font-size:{size*0.2}px; color:#333;'>
          {percentual}%
        </div>
      </div>
      <div style='font-size:0.7em; color:#888; margin-top:4px;'>{meses_feitos}/{meses_devidos} meses</div>
    </div>
    """


def month_status_html(status_dict):
    """Monta uma barra HTML com os 12 meses coloridos por status."""
    colors = {'confirmado': '#4caf50', 'extraido': '#ffc107', 'sem_dados': '#e0e0e0'}
    labels = {'confirmado': 'confirmado no Domínio', 'extraido': 'extraído, falta confirmar', 'sem_dados': 'sem dados'}
    cells = []
    for m in range(1, 13):
        s = status_dict.get(m, 'sem_dados')
        color = colors[s]
        text_color = '#fff' if s != 'sem_dados' else '#888'
        cells.append(
            f"<div title='{MESES[m-1]}: {labels[s]}' style='flex:1; text-align:center; padding:6px 2px; "
            f"background:{color}; color:{text_color}; font-size:0.75em; border-radius:3px; margin:1px;'>"
            f"{MESES_ABREV[m-1]}</div>"
        )
    return f"<div style='display:flex; width:100%;'>{''.join(cells)}</div>"


def render_empresa_panel(empresa, cnpj, key_prefix, ano_dashboard=None):
    """Renderiza upload + tabela de lançamentos + seleção de período + download + confirmação,
    tudo escopado pra uma única empresa. Usado tanto no dashboard quanto na página avulsa."""

    transacoes_salvas = db.carregar_transacoes(empresa)
    if transacoes_salvas:
        st.caption(f"📂 {len(transacoes_salvas)} lançamentos já salvos dessa empresa.")

    uploaded_files = st.file_uploader(
        "Extratos em PDF (só se tiver arquivo novo)", type=["pdf"],
        accept_multiple_files=True, key=f"{key_prefix}_upload"
    )

    for uf in (uploaded_files or []):
        pdf_bytes = uf.read()

        if not has_extractable_text(pdf_bytes):
            with st.expander(f"🔍 {uf.name} — precisa de OCR/conferência manual"):
                if st.button("Rodar OCR", key=f"{key_prefix}_ocr_{uf.name}"):
                    with st.spinner("Lendo via OCR..."):
                        lines = ocr_extract_lines(pdf_bytes)
                    st.session_state[f"{key_prefix}_ocrlines_{uf.name}"] = lines
                lines = st.session_state.get(f"{key_prefix}_ocrlines_{uf.name}")
                if lines:
                    st.text_area("Texto lido (confira contra o PDF original)", '\n'.join(lines),
                                 height=200, key=f"{key_prefix}_ocrtext_{uf.name}")
                    st.info("Esse arquivo ainda não entra automaticamente no OFX — me chama pra montar o parser desse banco.")
            continue

        tmp_path = save_temp(pdf_bytes)
        try:
            import pdfplumber
            with pdfplumber.open(tmp_path) as pdf:
                full_text = '\n'.join((p.extract_text() or '') for p in pdf.pages)
            bank = detect_bank(full_text)
            if bank is None:
                st.warning(f"'{uf.name}': banco não reconhecido.")
                continue
            if bank == 'itau':
                info = bp.get_itau_header_info(tmp_path); tx = bp.parse_itau_empresarial(tmp_path)
            elif bank == 'stone':
                info = bp.get_stone_header_info(tmp_path); tx = bp.parse_stone(tmp_path)
            elif bank == 'bradesco':
                info = bp.get_bradesco_header_info(tmp_path); tx = bp.parse_bradesco(tmp_path)
            elif bank == 'sicoob':
                info = bp.get_sicoob_header_info(tmp_path)
                year_hint = (info or {}).get('year_hint') or str(datetime.now().year)
                tx = bp.parse_sicoob(tmp_path, year_hint)
            else:
                info, tx = None, []
        except Exception as e:
            st.error(f"Erro lendo {uf.name}: {e}")
            continue
        finally:
            os.remove(tmp_path)

        if not info:
            st.warning(f"'{uf.name}' — não consegui achar agência/conta ({bank}).")
            continue

        pdf_cnpj = re.sub(r'\D', '', info.get('cnpj') or '')
        empresa_cnpj_digits = re.sub(r'\D', '', cnpj or '')
        if pdf_cnpj and empresa_cnpj_digits and pdf_cnpj != empresa_cnpj_digits:
            empresa_real = find_empresa_by_cnpj(db.listar_clientes(), info.get('cnpj')) or info.get('empresa')
            st.warning(f"⚠️ '{uf.name}' parece ser de **{empresa_real}**, não de {empresa}. Confere o arquivo.")
            continue

        novas, duplicadas = db.salvar_transacoes(
            empresa, cnpj, tx, bank, info.get('agencia'), info.get('conta'), uf.name
        )
        st.write(f"✅ **{uf.name}** — `{bank}` — {len(tx)} lidos ({novas} novos, {duplicadas} já existiam)")

    all_transactions = db.carregar_transacoes(empresa)
    if not all_transactions:
        st.info("Nenhum lançamento ainda pra essa empresa.")
        return

    all_transactions.sort(key=lambda t: t['date'], reverse=True)

    table_html = "<table style='width:100%; border-collapse: collapse; font-size:0.85em;'>"
    table_html += (
        "<tr style='font-weight:bold; border-bottom:2px solid #333;'>"
        "<td style='padding:3px;'>Data</td><td style='padding:3px;'>Descrição</td>"
        "<td style='padding:3px;'>Valor</td><td style='padding:3px;'>Banco</td></tr>"
    )
    for t in all_transactions[:200]:
        cor = '#c6efce' if t['value'] >= 0 else '#ffc7ce'
        table_html += (
            f"<tr style='background-color:{cor};'>"
            f"<td style='padding:3px;'>{t['date'].strftime('%d/%m/%Y')}</td>"
            f"<td style='padding:3px;'>{t['desc']}</td>"
            f"<td style='padding:3px;'>{t['value']:.2f}</td>"
            f"<td style='padding:3px;'>{t['bank']}</td></tr>"
        )
    table_html += "</table>"
    st.markdown(table_html, unsafe_allow_html=True)
    if len(all_transactions) > 200:
        st.caption(f"Mostrando 200 de {len(all_transactions)} lançamentos (os mais recentes).")

    groups = defaultdict(list)
    for t in all_transactions:
        key = (t['bank'], t['agencia'], t['conta'], t['date'].year, t['date'].month)
        groups[key].append(t)

    periodo_labels = {}
    for key in sorted(groups.keys(), key=lambda k: (k[3], k[4]), reverse=True):
        bank, agencia, conta, year, month = key
        label = f"{MESES[month-1]}/{year} — {bank} (ag {agencia}/conta {conta}) — {len(groups[key])} lanç."
        periodo_labels[label] = key

    periodo_escolhido = st.selectbox("Período", list(periodo_labels.keys()), key=f"{key_prefix}_periodo")
    key = periodo_labels[periodo_escolhido]
    bank, agencia, conta, year, month = key
    txs = groups[key]

    total_credito = sum(t['value'] for t in txs if t['value'] > 0)
    total_debito = sum(t['value'] for t in txs if t['value'] < 0)
    c1, c2, c3 = st.columns(3)
    c1.metric("Lançamentos", len(txs))
    c2.metric("Créditos", f"R$ {total_credito:,.2f}")
    c3.metric("Débitos", f"R$ {total_debito:,.2f}")

    ofx_text = build_ofx(txs, bank, agencia, conta, year, month)
    safe_empresa = re.sub(r'[^\w-]', '_', empresa)[:40]
    fname = f'{safe_empresa}_{month:02d}_{year}.ofx'

    col1, col2 = st.columns([2, 2])
    with col1:
        st.download_button(f"📥 Baixar OFX", data=ofx_text, file_name=fname,
                            mime="application/octet-stream", key=f"{key_prefix}_dl")
    with col2:
        if st.button("🗑️ Apagar este período", key=f"{key_prefix}_del"):
            apagados = db.apagar_periodo(empresa, bank, agencia, conta, year, month)
            st.success(f"{apagados} lançamentos apagados.")
            st.rerun()

    st.divider()
    st.caption("Confirme aqui, conta por conta e mês por mês, o que já foi de fato importado no Domínio:")
    periodos = db.listar_periodos(empresa)
    for p in periodos:
        label = (f"{MESES[p['mes']-1]}/{p['ano']} — {p['banco']} "
                 f"(ag {p['agencia']}/conta {p['conta']}) — {p['qtd']} lanç.")
        confirmado = st.checkbox(
            label, value=p['confirmado'],
            key=f"{key_prefix}_confirma_{p['banco']}_{p['agencia']}_{p['conta']}_{p['ano']}_{p['mes']}"
        )
        if confirmado != p['confirmado']:
            db.set_confirmado(empresa, p['banco'], p['agencia'], p['conta'], p['ano'], p['mes'], confirmado)
            st.rerun()
