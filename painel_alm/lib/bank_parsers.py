import re
from datetime import datetime

from table_parser import extract_banded_rows

MONEY_TAIL_RE = re.compile(r'(?:(\d+)\s+)?(-?[\d.]+,\d{2})\s+([\d.]+,\d{2})\s*$')
MONEY_FULL_RE = re.compile(r'^(?:(\d+)\s+)?(-?[\d.]+,\d{2})\s+([\d.]+,\d{2})\s*$')
DATE_BR_RE = re.compile(r'^(\d{2}/\d{2}/\d{4})\b\s*(.*)$')
DATE_BR_SHORT_RE = re.compile(r'^(\d{2}/\d{2})\b\s*(.*)$')


def _to_float(s):
    return float(s.replace('.', '').replace(',', '.'))


def clean_text(s):
    return re.sub(r'[\ue000-\uf8ff]', '-', s).strip()


# ---------------------------------------------------------------------------
# ITAÚ (extrato "empresas" com colunas Data / Lançamentos / Razão Social / CNPJ/CPF / Valor / Saldo)
# ---------------------------------------------------------------------------
def parse_itau_empresarial(pdf_path):
    header_labels = ['data', 'lancamentos', 'razao', 'cnpj', 'valor', 'saldo']
    header_x = [35.1, 91.4, 227.9, 364.4, 463.0, 520.7, 1000]
    rows = extract_banded_rows(pdf_path, header_labels, header_x,
                                value_cols=['valor', 'saldo'], min_top_after_header=208,
                                stop_markers=['Saldo da conta corrente', 'Lançamentos futuros do período'])

    transactions = []
    for r in rows:
        date_txt = r['data'].strip()
        if not re.match(r'^\d{2}/\d{2}/\d{4}', date_txt):
            continue
        date_txt = date_txt[:10]
        date = datetime.strptime(date_txt, '%d/%m/%Y').date()
        desc_parts = [r['lancamentos'], r['razao'], r['cnpj']]
        desc = ' '.join(p for p in desc_parts if p).strip()
        desc = re.sub(r'\s+', ' ', desc)
        valor_txt = r['valor'].strip()
        saldo_txt = r['saldo'].strip()
        if valor_txt and MONEY_FULL_RE.match(valor_txt) is None and not re.fullmatch(r'-?[\d.]+,\d{2}', valor_txt):
            continue
        if saldo_txt and not re.fullmatch(r'-?[\d.]+,\d{2}', saldo_txt):
            continue
        if valor_txt:
            valor = _to_float(valor_txt)
        elif saldo_txt:
            valor = _to_float(saldo_txt)
        else:
            continue
        transactions.append({'date': date, 'desc': clean_text(desc), 'value': valor})
    return transactions


def get_itau_header_info(pdf_path):
    """Extrai nome da empresa, CNPJ, agência e conta do cabeçalho do extrato Itaú."""
    import pdfplumber
    with pdfplumber.open(pdf_path) as pdf:
        text = pdf.pages[0].extract_text() or ''
    m = re.search(r'^(.*?)\s+CNPJ\s+([\d./-]+)\s+Agência\s+(\d+)\s+Conta\s+([\d.-]+)', text)
    if not m:
        return None
    return {
        'empresa': m.group(1).strip(),
        'cnpj': m.group(2).strip(),
        'agencia': m.group(3).strip(),
        'conta': m.group(4).strip(),
    }


# ---------------------------------------------------------------------------
# STONE (extrato de conta corrente: DATA / TIPO / DESCRIÇÃO / VALOR / SALDO / CONTRAPARTE)
# ---------------------------------------------------------------------------
def parse_stone(pdf_path):
    header_labels = ['data', 'tipo', 'descricao', 'valor', 'saldo', 'contraparte']
    header_x = [26.0, 75.5, 120.1, 284.3, 360.8, 427.8, 1000]
    rows = extract_banded_rows(pdf_path, header_labels, header_x,
                                value_cols=['valor'], min_top_after_header=245)

    transactions = []
    for r in rows:
        date_txt = r['data'].strip()
        m = re.match(r'^(\d{2}/\d{2}/\d{2})$', date_txt)
        if not m:
            continue
        date = datetime.strptime(m.group(1), '%d/%m/%y').date()
        valor_txt = re.sub(r'[Rr]\$', '', r['valor']).strip()
        valor_txt = valor_txt.replace(' ', '')
        if not valor_txt:
            continue
        valor = _to_float(valor_txt)
        desc = clean_text(f"{r['tipo']} {r['descricao']}".strip())
        desc = re.sub(r'\s+', ' ', desc)
        transactions.append({'date': date, 'desc': desc, 'value': valor})
    return transactions


def get_stone_header_info(pdf_path):
    import pdfplumber
    with pdfplumber.open(pdf_path) as pdf:
        text = pdf.pages[0].extract_text() or ''
    text = clean_text(text)
    m_empresa = re.search(r'Nome\s+Documento\s*\n(.*?)\s+([\d.]+/[\d-]+)\s*\n', text)
    m_conta = re.search(r'Instituição\s+de\s+Pagamento\s+S\.A\.\s+(\d+)\s+([\d-]+)', text)
    if not m_empresa or not m_conta:
        return None
    return {
        'empresa': m_empresa.group(1).strip(),
        'cnpj': m_empresa.group(2).strip(),
        'agencia': m_conta.group(1).strip(),
        'conta': m_conta.group(2).strip(),
    }


# ---------------------------------------------------------------------------
# BRADESCO (Extrato Mensal / Por Período: Data / Lançamento / Dcto. / Crédito / Débito / Saldo)
# ---------------------------------------------------------------------------
def parse_bradesco(pdf_path):
    import pdfplumber
    with pdfplumber.open(pdf_path) as pdf:
        full_text = '\n'.join((p.extract_text() or '') for p in pdf.pages)

    SKIP_MARKERS = ('Total', 'Últimos Lançamentos', 'Saldos Invest', 'SALDO INVEST',
                    'Extrato Mensal', 'Nome do usuário', 'Folha', 'Agência | Conta',
                    'Extrato de:', 'Data Lançamento', 'Os dados acima')

    lines = [l for l in full_text.split('\n')]
    transactions = []
    current_date = None
    pending_prefix = []
    i = 0
    n = len(lines)

    def emit(date, desc, valor_saldo_tuple):
        dcto, valor, saldo = valor_saldo_tuple
        if date is None:
            return
        transactions.append({
            'date': date,
            'desc': clean_text(re.sub(r'\s+', ' ', desc)).strip(),
            'value': _to_float(valor),
        })

    while i < n:
        raw_line = lines[i].strip()
        if not raw_line or any(raw_line.startswith(s) or s in raw_line for s in SKIP_MARKERS):
            i += 1
            continue

        line = raw_line
        m_date = DATE_BR_RE.match(line)
        if m_date:
            current_date = datetime.strptime(m_date.group(1), '%d/%m/%Y').date()
            line = m_date.group(2).strip()
            if line.upper() == 'SALDO ANTERIOR' or not line:
                i += 1
                continue

        m_tail = MONEY_TAIL_RE.search(line)
        if m_tail and line[:m_tail.start()].strip():
            # linha (com ou sem data) que já contém descrição + dcto/valor/saldo inline
            desc = (' '.join(pending_prefix) + ' ' + line[:m_tail.start()].strip()).strip()
            emit(current_date, desc, m_tail.groups())
            pending_prefix = []
            i += 1
            continue

        m_full = MONEY_FULL_RE.match(line)
        if m_full:
            # linha "solta" só com dcto/valor/saldo -> descrição vem do prefixo acumulado
            # e possivelmente de uma linha de sufixo logo em seguida
            desc_prefix = ' '.join(pending_prefix)
            j = i + 1
            suffix = []
            while j < n and lines[j].strip() and not DATE_BR_RE.match(lines[j].strip()) \
                    and not MONEY_FULL_RE.match(lines[j].strip()) \
                    and not MONEY_TAIL_RE.search(lines[j].strip()) \
                    and not any(s in lines[j] for s in SKIP_MARKERS):
                suffix.append(lines[j].strip())
                j += 1
            desc = (desc_prefix + ' ' + ' '.join(suffix)).strip()
            emit(current_date, desc, m_full.groups())
            pending_prefix = []
            i = j
            continue

        pending_prefix.append(line)
        i += 1

    return transactions


def get_bradesco_header_info(pdf_path):
    import pdfplumber
    with pdfplumber.open(pdf_path) as pdf:
        full_text = '\n'.join((p.extract_text() or '') for p in pdf.pages)
    m_empresa = re.search(r'^(.*?)\s*\|\s*CNPJ:\s*([\d./-]+)', full_text, re.MULTILINE)
    m_conta = re.search(r'Ag:\s*(\d+)\s*\|\s*CC:\s*([\d-]+)', full_text)
    if not m_conta:
        return None
    return {
        'empresa': m_empresa.group(1).strip() if m_empresa else None,
        'cnpj': m_empresa.group(2).strip() if m_empresa else None,
        'agencia': m_conta.group(1).strip(),
        'conta': m_conta.group(2).strip(),
    }


# ---------------------------------------------------------------------------
# SICOOB (Extrato de Conta Corrente: Data / Documento / Histórico / Valor com sufixo C/D)
# ---------------------------------------------------------------------------
SICOOB_LINE_RE = re.compile(
    r'^(\d{2}/\d{2})\s+(\S+)?\s*(.*?)\s+R\$\s*([\d.]+,\d{2})([CD])\s*$'
)


def parse_sicoob(pdf_path, year_hint):
    import pdfplumber
    with pdfplumber.open(pdf_path) as pdf:
        full_text = '\n'.join((p.extract_text() or '') for p in pdf.pages)

    lines = full_text.split('\n')
    transactions = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].strip()
        m = re.match(r'^(\d{2}/\d{2})\s+(.*)$', line)
        if not m:
            i += 1
            continue
        day_month = m.group(1)
        rest = m.group(2).strip()
        val_m = re.search(r'R\$\s*([\d.]+,\d{2})([CD])\s*$', rest)
        if not val_m:
            i += 1
            continue
        desc_and_doc = rest[:val_m.start()].strip()
        # remove documento numérico do início, se houver (ex: '37117588 TRANSF...')
        doc_m = re.match(r'^(\d{4,})\s+(.*)$', desc_and_doc)
        if doc_m:
            desc = doc_m.group(2).strip()
        else:
            desc = desc_and_doc.strip()
        if desc.upper() in ('SALDO DO DIA', 'SALDO ANTERIOR', 'SALDO BLOQUEADO ANTERIOR'):
            i += 1
            # ainda assim é útil manter como "saldo" informativo? mantemos como transação neutra
            valor = _to_float(val_m.group(1))
            if val_m.group(2) == 'D':
                valor = -valor
            date = datetime.strptime(f'{day_month}/{year_hint}', '%d/%m/%Y').date()
            transactions.append({'date': date, 'desc': clean_text(desc), 'value': valor})
            continue

        # olha a próxima linha: se não for uma nova transação (não começa com dd/mm e não é vazia),
        # é a continuação da descrição (ex: 'FAV.: SERGIO LUIZ RICHS Transferência Pix ...')
        j = i + 1
        suffix = []
        while j < n and lines[j].strip() and not re.match(r'^\d{2}/\d{2}\s', lines[j].strip()) \
                and 'RESUMO' not in lines[j] and 'HISTÓRICO DE MOVIMENTAÇÃO' not in lines[j]:
            suffix.append(lines[j].strip())
            j += 1
        full_desc = (desc + ' ' + ' '.join(suffix)).strip()

        valor = _to_float(val_m.group(1))
        if val_m.group(2) == 'D':
            valor = -valor
        date = datetime.strptime(f'{day_month}/{year_hint}', '%d/%m/%Y').date()
        transactions.append({'date': date, 'desc': clean_text(re.sub(r'\s+', ' ', full_desc)), 'value': valor})
        i = j
    return transactions


def get_sicoob_header_info(pdf_path):
    import pdfplumber
    with pdfplumber.open(pdf_path) as pdf:
        text = pdf.pages[0].extract_text() or ''
    m_conta = re.search(r'Conta:\s*([\d.-]+)\s*/\s*(.*)', text)
    m_coop = re.search(r'Cooperativa:\s*([\d-]+)', text)
    m_periodo = re.search(r'Periodo:\s*\d{2}/\d{2}/(\d{4})', text)
    if not m_conta or not m_coop:
        return None
    return {
        'empresa': m_conta.group(2).strip(),
        'cnpj': None,
        'agencia': m_coop.group(1).strip(),
        'conta': m_conta.group(1).strip(),
        'year_hint': m_periodo.group(1) if m_periodo else None,
    }
