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
        company = re.sub(r'\s*Página:\s*\d+\s*/\s*\d+\s*$', '', company).strip()

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

            # "dias" (dias de férias a que o empregado tem direito) fica 3 posições
            # antes do token de 'Limite p/ gozo', contando de trás pra frente -
            # isso funciona tanto pra linha principal (com código+nome) quanto
            # pra linha de continuação, porque a data de limite é sempre o
            # último token relevante da linha, independente do que vem antes.
            dias_val = None
            limite_idx = None
            for i in range(len(toks) - 1, -1, -1):
                if toks[i] == limite:
                    limite_idx = i
                    break
            if limite_idx is not None and limite_idx - 3 >= 0:
                dias_tok = toks[limite_idx - 3]
                if re.match(r'^\d+([,.]\d+)?$', dias_tok):
                    dias_val = float(dias_tok.replace(',', '.'))

            emp_rows[current_emp].append({'limite': limite, 'fer': fer_val, 'dias': dias_val})

        if total_declared is not None:
            audit.append((company, total_declared, len(emp_codes_in_block)))

    results = []
    company_order = []
    seen_companies = set()
    for emp in order:
        company, code, name = emp
        if company not in seen_companies:
            seen_companies.add(company)
            company_order.append(company)

        rws = emp_rows[emp]
        fer_digit_rows = [r for r in rws if r['fer'] is not None]
        max_fer = max(
            (int(float(r['fer'].replace(',', '.'))) for r in fer_digit_rows),
            default=0
        )

        if max_fer >= 2:
            status = 'DUPLICIDADE'
            datado = [(r['limite'], r['dias']) for r in fer_digit_rows if r['limite']]
            if datado:
                ref_str, dias_val = min(datado, key=lambda x: _pdate(x[0]))
                ref = _pdate(ref_str)
            else:
                ref, dias_val = None, None
        elif max_fer == 1:
            r1 = [r for r in fer_digit_rows if r['fer'] == '1']
            ref = _pdate(r1[0]['limite']) if r1 and r1[0]['limite'] else None
            dias_val = r1[0]['dias'] if r1 else None
            status = 'VENCIDA' if ref and ref < reference_date else 'MATURADA'
        else:
            status = 'A_VENCER'
            datado = [(r['limite'], r['dias']) for r in rws if r['limite']]
            if datado:
                ref_str, dias_val = min(datado, key=lambda x: _pdate(x[0]))
                ref = _pdate(ref_str)
            else:
                ref, dias_val = None, None

        results.append({
            'empresa': company,
            'codigo': code,
            'nome': name,
            'status': status,
            'status_label': STATUS_LABEL[status],
            'limite': ref,
            'dias': dias_val,
        })

    results.sort(key=lambda r: (STATUS_ORDER[r['status']], r['limite'] or datetime(2100, 1, 1)))

    audit_ok = all(decl == parsed for _, decl, parsed in audit)

    return results, audit, audit_ok, company_order


def format_dias(dias):
    """Formata o número de dias sem casas decimais desnecessárias (30.0 -> '30')."""
    if dias is None:
        return '-'
    if float(dias).is_integer():
        return str(int(dias))
    txt = f"{dias:.2f}".rstrip('0').rstrip('.')
    return txt


def build_whatsapp_texts(results, company_order):
    """
    Monta, por empresa (na ordem em que aparecem no PDF), o texto pronto pra
    colar no WhatsApp - SOMENTE funcionários com direito a 30 dias cheios
    (período completo, sem proporcionalidade). Mantém a ordem de urgência
    já presente em 'results' (mais vencidos primeiro) dentro de cada empresa.
    """
    from collections import OrderedDict

    by_empresa = OrderedDict((empresa, []) for empresa in company_order)
    for r in results:
        if r['dias'] is None or abs(r['dias'] - 30) > 0.001:
            continue
        by_empresa.setdefault(r['empresa'], []).append(r)

    texts = {}
    for empresa, emps in by_empresa.items():
        if not emps:
            continue
        linhas = ["Segue relação de férias dos empregados:"]
        for r in emps:
            lim_fmt = r['limite'].strftime('%d/%m/%Y') if r['limite'] else '-'
            linhas.append(f"{r['nome']} tem {format_dias(r['dias'])} dias - Limite de início do gozo: {lim_fmt}")
        texts[empresa] = "\n".join(linhas)

    return texts
