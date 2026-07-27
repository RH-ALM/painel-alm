import re
import pdfplumber

MONEY_RE = re.compile(r'^-?[\d.]+,\d{2}$')


def extract_banded_rows(pdf_path, header_labels, header_x_positions, value_cols,
                         min_top_after_header=0, stop_markers=None):
    """
    Extrai linhas de uma tabela em PDF com layout proporcional (colunas por posição x,
    não largura fixa), usando os valores monetários como âncora de cada linha lógica.
    Isso resolve o problema de células com texto quebrado em 2+ linhas físicas, cuja
    posição vertical (top) fica intercalada com a linha de valor/data (comum em
    extratos bancários gerados a partir de HTML/tabela responsiva).

    header_labels: lista de nomes de coluna, ex ['data','lancamentos','razao','cnpj','valor','saldo']
    header_x_positions: x0 de cada coluna (mesma ordem), pego da linha de cabeçalho do PDF
    value_cols: quais colunas (por nome) contêm valores monetários que servem de âncora de linha
    stop_markers: lista de textos que, se encontrados no início de uma palavra/linha, indicam
        o fim da tabela de lançamentos (ex: 'Saldo da conta corrente', 'Lançamentos futuros').
        Tudo a partir dali (na mesma página) é ignorado.
    """
    stop_markers = stop_markers or []
    rows_all = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            words = page.extract_words()

            # acha o topo do primeiro marcador de parada nesta página (se houver)
            page_text = page.extract_text() or ''
            cutoff_top = None
            for marker in stop_markers:
                idx = page_text.find(marker)
                if idx != -1:
                    marker_first_word = marker.split()[0]
                    for w in words:
                        if w['text'] == marker_first_word:
                            # confere se a frase completa do marcador aparece perto (mesma linha)
                            same_line = [ww for ww in words if abs(ww['top'] - w['top']) < 2]
                            same_line_text = ' '.join(ww['text'] for ww in sorted(same_line, key=lambda x: x['x0']))
                            if marker in same_line_text:
                                if cutoff_top is None or w['top'] < cutoff_top:
                                    cutoff_top = w['top']
                                break
            if cutoff_top is not None:
                words = [w for w in words if w['top'] < cutoff_top]

            def col_for_x(x0):
                for i in range(len(header_x_positions) - 1):
                    if header_x_positions[i] <= x0 < header_x_positions[i + 1]:
                        return header_labels[i]
                return header_labels[-1]

            anchors = []
            for w in words:
                if w['top'] <= min_top_after_header:
                    continue
                if MONEY_RE.match(w['text']) and col_for_x(w['x0']) in value_cols:
                    anchors.append(w)
            anchors.sort(key=lambda w: w['top'])

            for i, anchor in enumerate(anchors):
                start = min_top_after_header if i == 0 else (anchors[i - 1]['top'] + anchor['top']) / 2
                end = 1e9 if i == len(anchors) - 1 else (anchor['top'] + anchors[i + 1]['top']) / 2
                cell = {c: [] for c in header_labels}
                for w in words:
                    if start <= w['top'] < end and w['top'] > min_top_after_header:
                        c = col_for_x(w['x0'])
                        cell[c].append((w['top'], w['x0'], w['text']))
                row = {c: ' '.join(t for _, _, t in sorted(cell[c])) for c in header_labels}
                rows_all.append(row)
    return rows_all


def get_header_positions(pdf_path, header_line_contains):
    """Acha a posição x0 de cada palavra de cabeçalho na primeira ocorrência da linha
    que contém todos os textos em header_line_contains (na mesma altura/top)."""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            tops = {}
            for w in words:
                tops.setdefault(round(w['top'], 1), []).append(w)
            for top, ws in tops.items():
                texts = [w['text'] for w in ws]
                if all(any(h in t for t in texts) for h in header_line_contains):
                    return top, ws
    return None, None
