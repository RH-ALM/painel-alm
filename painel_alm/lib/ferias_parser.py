import re
import subprocess
import tempfile
import os
from datetime import datetime

DATE_RE = r'\d{2}/\d{2}/\d{4}'

STATUS_LABEL = {
    'DUPLICIDADE': 'Duplicidade (risco pgto dobro)',
    'VENCIDA': 'Vencida',
    'MATURADA': 'Maturada - dentro do prazo',
    'A_VENCER': 'A vencer (ainda acumulando)',
}

STATUS_ORDER = {'DUPLICIDADE': 0, 'VENCIDA': 1, 'MATURADA': 2, 'A_VENCER': 3}

STATUS_COLOR = {
    'DUPLICIDADE': 'FFC7CE',  # vermelho
    'VENCIDA': 'FFC7CE',      # vermelho
    'MATURADA': 'FFEB9C',     # amarelo
    'A_VENCER': 'FFFFFF',     # branco
}


def _pdate(s):
    return datetime.strptime(s, '%d/%m/%Y')


def extract_text_from_pdf(pdf_bytes):
    """Extrai texto do PDF preservando layout, usando pdfplumber (Python puro,
    funciona em qualquer sistema operacional sem depender de binário externo)."""
    import pdfplumber

    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_pdf:
        tmp_pdf.write(pdf_bytes)
        tmp_pdf_path = tmp_pdf.name

    try:
        page_texts = []
        with pdfplumber.open(tmp_pdf_path) as pdf:
            for page in pdf.pages:
                page_texts.append(page.extract_text() or '')
        # junta as páginas com \x0c (form feed), mesmo separador usado
        # para dividir "um bloco por empresa" no restante do código
        text = '\x0c'.join(page_texts)
    finally:
        if os.path.exists(tmp_pdf_path):
            os.remove(tmp_pdf_path)
    return text


def parse_ferias(text, reference_date=None):
    """
    Parseia o texto extraído do PDF 'Programação de Férias' (Domínio Folha)
    e classifica cada vínculo em: DUPLICIDADE, VENCIDA, MATURADA, A_VENCER.

    Regra (mesma usada nas análises manuais anteriores):
    - Usa o campo "Fer." que o próprio Domínio já calcula (não recalcula na mão).
    - Fer >= 2  -> DUPLICIDADE (2+ períodos vencidos, risco de pagamento em dobro CLT art. 137)
    - Fer == 1  -> checa a data "Limite p/ gozo" desse período:
                   já passou -> VENCIDA / ainda não passou -> MATURADA
    - Fer == 0 ou linha de continuação sem Fer -> A_VENCER (ainda no aquisitivo)
    """
    if reference_date is None:
        reference_date = datetime.now()

    blocks = text.split('\x0c')
    emp_rows = {}
    order = []
    audit = []  # (empresa, total_declarado, total_parseado)

    for block in blocks:
        lines = block.split('\n')
        if not lines or not lines[0].strip():
            continue
        company = re.split(r'\s{2,}', lines[0].strip())[0].strip()

        tot_match = re.search(r'Total de empregados:\s*(\d+)', block)
        total_declared = int(tot_match.group(1)) if tot_match else None

        current_emp = None
        emp_codes_in_block = set()

        for line in lines:
            if 'Código Empregado' in line or 'PROGRAMAÇÃO' in line or 'Data base' in line:
                continue
            dates = re.findall(DATE_RE, line)
            if len(dates) < 3:
                continue
            first_date_pos = line.index(dates[0])
            prefix = line[:first_date_pos].strip()
            m = re.match(r'^(\d+)\s+(.+)$', prefix)
            is_new_emp = bool(m)
            if is_new_emp:
                code = m.group(1)
                name = m.group(2).strip()
                current_emp = (company, code, name)
                emp_codes_in_block.add(code)
                if current_emp not in emp_rows:
                    emp_rows[current_emp] = []
                    order.append(current_emp)

            if current_emp is None:
                continue

            rest = line[first_date_pos:]
            toks = rest.split()
            all_dates_in_rest = re.findall(DATE_RE, rest)
            limite = all_dates_in_rest[-1] if all_dates_in_rest else None

            fer_val = None
            if is_new_emp and len(toks) > 2 and re.match(r'^\d+([,.]\d+)?$', toks[2]):
                fer_val = toks[2]

            emp_rows[current_emp].append({'limite': limite, 'fer': fer_val})

        if total_declared is not None:
            audit.append((company, total_declared, len(emp_codes_in_block)))

    results = []
    for emp in order:
        company, code, name = emp
        rws = emp_rows[emp]
        fer_digit_rows = [r for r in rws if r['fer'] is not None]
        max_fer = max(
            (int(float(r['fer'].replace(',', '.'))) for r in fer_digit_rows),
            default=0
        )

        if max_fer >= 2:
            status = 'DUPLICIDADE'
            limites = [_pdate(r['limite']) for r in fer_digit_rows if r['limite']]
            ref = min(limites) if limites else None
        elif max_fer == 1:
            r1 = [r for r in fer_digit_rows if r['fer'] == '1']
            ref = _pdate(r1[0]['limite']) if r1 and r1[0]['limite'] else None
            status = 'VENCIDA' if ref and ref < reference_date else 'MATURADA'
        else:
            status = 'A_VENCER'
            limites = [_pdate(r['limite']) for r in rws if r['limite']]
            ref = min(limites) if limites else None

        results.append({
            'empresa': company,
            'codigo': code,
            'nome': name,
            'status': status,
            'status_label': STATUS_LABEL[status],
            'limite': ref,
        })

    results.sort(key=lambda r: (STATUS_ORDER[r['status']], r['limite'] or datetime(2100, 1, 1)))

    audit_ok = all(decl == parsed for _, decl, parsed in audit)

    return results, audit, audit_ok
