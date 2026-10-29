"""Vale Alimentação / Reembolso — conciliação automática e geração de recibos.

Entrada: PDFs da relação do Domínio e dos recibos de pagamento (folha).
Regras (cláusulas da CCT de Transportes de Joinville):
  - Reembolso (viagem fora do domicílio): R$ 93,00 por dia.
  - Vale alimentação (escritório, cláusula sétima): R$ 25,30 por dia.
  - Dias = dias úteis (seg a sex) do mês, sem feriados e sem afastamentos.
  - Mês cheio sem afastamento: dias do acordo (padrão 26).
"""
import re
import io
import zipfile
import unicodedata
import datetime as dt
from collections import defaultdict

UNIT_REEMB = 93.00
UNIT_VALE = 25.30
DIAS_MES_CHEIO = 26


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).upper().strip()


def _tokens(s):
    stop = {"LTDA", "ME", "EPP", "DE", "DA", "DO", "E", "TRANSPORTES", "TRANSPORTE"}
    return {t for t in re.split(r"[^A-Z0-9]+", norm(s)) if len(t) > 2 and t not in stop}


def brl_to_float(s):
    return float(s.replace(".", "").replace(",", "."))


def extrair_texto(pdf_bytes):
    import pdfplumber
    paginas = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for p in pdf.pages:
            paginas.append(p.extract_text() or "")
    return "\n".join(paginas)


# ---------------------------------------------------------------- relação
RE_EMP = re.compile(r"^Empresa:\s*(.+?)\s+P[áa]gina")
RE_ID = re.compile(r"^(CNPJ|CEI|CAEPF|CPF):\s*(\S+)")
RE_LINHA_REL = re.compile(r"^(\d+)\s+(.+?)\s+(\d{1,3}(?:\.\d{3})*,\d{2})\b")


def parse_relacao(texto):
    """Retorna lista de empresas: {empresa, tipo_id, id, linhas:[{codigo,nome,valor}]}."""
    empresas, cur = [], None
    for linha in texto.splitlines():
        linha = linha.strip()
        m = RE_EMP.match(linha)
        if m:
            cur = {"empresa": m.group(1).strip(), "tipo_id": None, "id": None, "linhas": []}
            empresas.append(cur)
            continue
        if cur is None:
            continue
        m = RE_ID.match(linha)
        if m and cur["id"] is None:
            cur["tipo_id"], cur["id"] = m.group(1), m.group(2)
            continue
        m = RE_LINHA_REL.match(linha)
        if m and not linha.startswith("Total"):
            cur["linhas"].append({"codigo": m.group(1), "nome": m.group(2).strip(),
                                  "valor": brl_to_float(m.group(3))})
    return empresas


# ---------------------------------------------------------------- recibos
RE_ID_REC = re.compile(r"^(CNPJ|CEI|CAEPF|CPF):\s*(\S+)")
RE_FUNC = re.compile(r"^(\d+)\s+(.+?)\s+(\d{4,6})\s+\d+\s+\d+\s*$")
RE_ADM = re.compile(r"Admiss\S*:\s*(\d{2}/\d{2}/\d{4})")


def parse_recibo(texto, nome_arquivo=""):
    """Um PDF de recibos (folha de um mês) → {empresa, id, funcionarios:{(codigo,nome):{...}}}."""
    linhas = [l.strip() for l in texto.splitlines()]
    empresa, tipo_id, id_ = None, None, None
    for i, l in enumerate(linhas):
        m = RE_ID_REC.match(l)
        if m:
            tipo_id, id_ = m.group(1), m.group(2)
            j = i - 1
            while j >= 0 and not linhas[j]:
                j -= 1
            empresa = linhas[j] if j >= 0 else None
            break
    funcs = {}
    for i, l in enumerate(linhas):
        m = RE_FUNC.match(l)
        if not m:
            continue
        codigo, nome = m.group(1), m.group(2).strip()
        bloco = linhas[i:i + 25]
        adm = None
        for b in bloco[:4]:
            ma = RE_ADM.search(b)
            if ma:
                adm = ma.group(1)
                break
        pro_labore = any("PRO-LABORE" in b.upper() for b in bloco)
        key = (codigo, norm(nome))
        if key not in funcs:
            funcs[key] = {"codigo": codigo, "nome": nome, "adm": adm,
                          "pro_labore": pro_labore, "ferias": any("HORAS FERIAS" in b for b in bloco)}
        elif adm and not funcs[key]["adm"]:
            funcs[key]["adm"] = adm
    return {"arquivo": nome_arquivo, "empresa": empresa, "tipo_id": tipo_id, "id": id_,
            "funcionarios": funcs}


def casar_empresa(emp_rel, recibos):
    """Escolhe o recibo da empresa: pelo CNPJ/CEI quando bate, senão pelo nome."""
    dig_rel = re.sub(r"\D", "", emp_rel["id"] or "")
    melhor, melhor_score = None, 0.0
    for r in recibos:
        if re.sub(r"\D", "", r["id"] or "") == dig_rel and dig_rel:
            return r
        t_rel, t_rec = _tokens(emp_rel["empresa"]), _tokens(r["empresa"] or "")
        if not t_rel or not t_rec:
            continue
        score = len(t_rel & t_rec) / len(t_rel)
        if score > melhor_score:
            melhor, melhor_score = r, score
    return melhor if melhor_score >= 0.5 else None


def achar_funcionario(nome, funcs):
    partes = [p for p in norm(nome).split() if len(p) > 2]
    if not partes:
        return None
    for f in funcs.values():
        p2 = [p for p in norm(f["nome"]).split() if len(p) > 2]
        if p2 and p2[0] == partes[0] and p2[-1] == partes[-1]:
            return f
    return None


# ---------------------------------------------------------------- dias
def _competencia(comp):
    """'10/2026' -> (primeiro dia, ultimo dia)."""
    mes, ano = (int(x) for x in comp.split("/"))
    ini = dt.date(ano, mes, 1)
    prox = dt.date(ano + (mes == 12), (mes % 12) + 1, 1)
    return ini, prox - dt.timedelta(days=1)


def _excluido(d, afastamentos):
    for af in afastamentos:
        if af["tipo"] == "Rescisão":
            if d > af["inicio"]:
                return True
        elif af["inicio"] <= d <= af["fim"]:
            return True
    return False


def calcular_dias(adm, afastamentos, ini, fim, feriados):
    """Dias uteis (seg a sex, sem feriado, sem afastamento) e se o mes e cheio.
    Retorna (dias_uteis, mes_cheio)."""
    inicio, admitido_no_mes = ini, False
    if adm:
        a = dt.datetime.strptime(adm, "%d/%m/%Y").date()
        if a > ini:
            inicio, admitido_no_mes = a, True
    uteis, afastado = 0, False
    d = inicio
    while d <= fim:
        if d.weekday() < 5 and d not in feriados:
            if _excluido(d, afastamentos):
                afastado = True
            else:
                uteis += 1
        d += dt.timedelta(days=1)
    return uteis, (not admitido_no_mes and not afastado)


def verba_da_linha(valor):
    """Vale R$25,30 quando o valor e multiplo de 25,30 e nao de 93."""
    cents = round(valor * 100)
    if cents % 9300 != 0 and cents % 2530 == 0:
        return "Vale", UNIT_VALE
    return "Reembolso", UNIT_REEMB


def achar_nome(a, b):
    pa = [p for p in norm(a).split() if len(p) > 2]
    pb = [p for p in norm(b).split() if len(p) > 2]
    return bool(pa and pb and pa[0] == pb[0] and pa[-1] == pb[-1])


# ---------------------------------------------------------------- conciliacao
def conciliar(relacao, recibos, afastamentos, competencia, feriados):
    """Compara cada linha da relacao com o recibo. Retorna lista de dicts."""
    ini, fim = _competencia(competencia)
    resultado = []
    for emp in relacao:
        rec = casar_empresa(emp, recibos)
        for l in emp["linhas"]:
            verba, unit = verba_da_linha(l["valor"])
            base = {"empresa": emp["empresa"], "tipo_id": emp["tipo_id"], "id": emp["id"],
                    "codigo": l["codigo"], "funcionario": l["nome"], "verba": verba,
                    "unit": unit, "valor_relacao": round(l["valor"], 2),
                    "arquivo_recibo": rec["arquivo"] if rec else None}
            f = achar_funcionario(l["nome"], rec["funcionarios"]) if rec else None
            afs = [a for a in afastamentos
                   if norm(a["empresa"]) == norm(emp["empresa"]) and achar_nome(a["funcionario"], l["nome"])]
            if f is None and afs:
                # desligado ou sem recibo na folha, mas com afastamento informado
                f = {"adm": None, "pro_labore": False}
            if f is None or f["pro_labore"]:
                base.update({"dias": None, "devido": None, "diferenca": None,
                             "status": "NÃO", "obs": "Sem recibo"})
                resultado.append(base)
                continue
            uteis, cheio = calcular_dias(f["adm"], afs, ini, fim, feriados)
            if verba == "Reembolso" and cheio:
                dias, obs = DIAS_MES_CHEIO, "mes cheio (acordo)"
            else:
                dias, obs = uteis, "dias uteis"
            devido = round(dias * unit, 2)
            dif = round(l["valor"] - devido, 2)
            base.update({"dias": dias, "devido": devido, "diferenca": dif,
                         "status": "OK" if abs(dif) < 0.01 else "NÃO", "obs": obs})
            resultado.append(base)
    return resultado


# ---------------------------------------------------------------- recibos PDF
def gerar_recibos_zip(linhas, competencia, recibos_pdfs_info=None):
    """Gera um PDF por empresa (2 recibos por página) e devolve bytes de um ZIP."""
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import os

    fonte, fonte_b = "Helvetica", "Helvetica-Bold"
    for cand in ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                 "/usr/share/fonts/dejavu/DejaVuSans.ttf",
                 r"C:\Windows\Fonts\arial.ttf"]:
        if os.path.exists(cand):
            try:
                pdfmetrics.registerFont(TTFont("DV", cand))
                negrito = cand.replace("DejaVuSans.ttf", "DejaVuSans-Bold.ttf").replace("arial.ttf", "arialbd.ttf")
                pdfmetrics.registerFont(TTFont("DVB", negrito))
                fonte, fonte_b = "DV", "DVB"
                break
            except Exception:
                continue

    def brl(v):
        return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    ini, fim = _competencia(competencia)
    periodo = f"{ini.strftime('%d/%m/%Y')} a {fim.strftime('%d/%m/%Y')}"
    t_title = ParagraphStyle("t", fontName=fonte_b, fontSize=10, alignment=TA_CENTER, spaceAfter=8)
    t_body = ParagraphStyle("b", fontName=fonte, fontSize=9, leading=12, alignment=TA_LEFT)
    t_center = ParagraphStyle("c", fontName=fonte, fontSize=9, alignment=TA_CENTER)

    def bloco(emp, cod, nome, dias, unit, valor, verba):
        if verba == "Vale":
            cab, rotulo, clausula = "* * * RECIBO DE VALE ALIMENTAÇÃO * * *", "Vale Alimentação", "cláusula sétima"
        else:
            cab, rotulo, clausula = "* * * RECIBO DE REEMBOLSO DE ALIMENTAÇÃO * * *", "Reembolso de despesas para Alimentação", "cláusula sexta"
        tipo, idnum = emp["tipo_id"] or "CNPJ", emp["id"] or ""
        txt = (f"Recebi da Empresa {emp['empresa'].upper()}, {tipo} {idnum}, a importancia de R$ {brl(valor)} "
               f"ref. ao {rotulo}, conforme {clausula} da C.C.T. do Sind. dos Cond. de Veiculos e Trabalhadores "
               f"em Transp. Rodov. de Cargas de Joinville, ref. ao periodo de {periodo}, conforme discriminacao abaixo:")
        t = Table([["QTDE", "VLR.UNITÁRIO", "VALOR TOTAL"], [str(dias), brl(unit), brl(valor)]], colWidths=[70, 90, 90])
        t.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), fonte, 9), ("FONT", (0, 0), (-1, 0), fonte_b, 9),
                               ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black)]))
        inner = [Paragraph(cab, t_title), Paragraph(txt, t_body), Spacer(1, 8), t, Spacer(1, 22),
                 Paragraph("_" * 60, t_center), Paragraph(f"{cod} - {nome.upper()}", t_center)]
        box = Table([[inner]], colWidths=[500])
        box.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.8, colors.black),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                                 ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10)]))
        return box

    grupos = defaultdict(list)
    for l in linhas:
        if l["devido"] is None or not l["dias"]:
            continue
        grupos[l["empresa"]].append(l)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for empresa, itens in grupos.items():
            story = []
            for i, l in enumerate(itens):
                story.append(bloco({"empresa": empresa, "tipo_id": itens[0]["tipo_id"], "id": itens[0]["id"]},
                                   l["codigo"], l["funcionario"], l["dias"], l["unit"], l["devido"], l["verba"]))
                story.append(Spacer(1, 18))
                if i % 2 == 1 and i != len(itens) - 1:
                    story.append(PageBreak())
            pdf_buf = io.BytesIO()
            doc = SimpleDocTemplate(pdf_buf, pagesize=A4, leftMargin=50, rightMargin=50, topMargin=50, bottomMargin=40)
            doc.build(story)
            nome = f"{empresa.upper()} - RECIBOS {competencia.replace('/', '.')}.pdf"
            z.writestr(nome, pdf_buf.getvalue())
    return buf.getvalue(), len(grupos)


def gerar_planilha(linhas, competencia):
    """Lista completa da conciliação em Excel (todas as linhas, sem filtro)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Conferência"
    cab = ["Empresa", "CNPJ/CEI", "Código", "Funcionário", "Verba", "Dias devidos",
           "Valor devido (R$)", "Valor na relação (R$)", "Diferença (R$)", "OK / NÃO",
           "Observação", "Recibo (arquivo)"]
    ws.append(cab)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3A5F")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 32

    red = PatternFill("solid", fgColor="F8D7DA")
    green = PatternFill("solid", fgColor="D8F0DC")
    for l in linhas:
        ws.append([
            l["empresa"], l.get("id") or "", l["codigo"], l["funcionario"], l["verba"],
            l["dias"], l["devido"], l["valor_relacao"], l["diferenca"], l["status"],
            l.get("obs") or "", l.get("arquivo_recibo") or "",
        ])
        r = ws.max_row
        for col in (7, 8, 9):
            ws.cell(r, col).number_format = '#,##0.00'
        ws.cell(r, 10).fill = green if l["status"] == "OK" else red

    widths = [34, 20, 9, 34, 16, 13, 18, 22, 16, 11, 40, 50]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
