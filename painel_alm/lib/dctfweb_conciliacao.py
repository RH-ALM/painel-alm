"""
Conciliação FGTS / DCTFWEB — ALM Contabilidade
=================================================
Lê o extrato analítico de uma competência e extrai, por empresa (via CNPJ):
  - Valor do FGTS
  - Total INSS + Valor Total do IRRF (valor esperado na guia DCTFWEB)

Depois casa cada empresa, independentemente, contra:
  - a guia FGTS (pasta "1 GRF MM.AAAA"), se já tiver sido liberada
  - a guia DCTFWEB (pasta "DCTFWEB IR MM.AAAA"), se já tiver sido liberada

Cada guia é conciliada e classificada separadamente:
  OK -> guia bate com o valor de referência do extrato
  X  -> tem guia, mas o valor diverge
  -  -> guia ainda não liberada/emitida
"""

import re
import unicodedata
from pathlib import Path
from collections import Counter
import io
import pdfplumber


def _extrair_texto(pdf_path_ou_bytes):
    """Aceita um caminho local (Path/str) ou bytes (baixado do Drive)."""
    if isinstance(pdf_path_ou_bytes, (bytes, bytearray)):
        origem = io.BytesIO(pdf_path_ou_bytes)
    else:
        origem = pdf_path_ou_bytes
    with pdfplumber.open(origem) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def _extrair_cnpj(texto):
    """Retorna o identificador 'de exibição' (CNPJ, CAEPF ou CPF) — o mais
    completo que achar no PDF, nessa ordem de prioridade."""
    completos = re.findall(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", texto)
    if completos:
        return Counter(completos).most_common(1)[0][0]
    # CAEPF (empregador pessoa física com empregado, ex: autônomo) — é o CPF
    # (3.3.3) seguido de filial de 3 dígitos + DV, aparece no Domínio como "CAEPF:"
    caepf = re.findall(r"\d{3}\.\d{3}\.\d{3}/\d{3}-\d{2}", texto)
    if caepf:
        return Counter(caepf).most_common(1)[0][0]
    # guia FGTS (GFD) só mostra a raiz do CNPJ, formatada tipo "79.402.764"
    m = re.search(r"CPF/CNPJ do Empregador.*?\n?.*?(\d{2}\.\d{3}\.\d{3})\b", texto, re.DOTALL)
    if m:
        return m.group(1)
    # CEI (empregador pessoa física, formato antigo) — número de 12 dígitos
    # sem pontuação, sempre logo depois do rótulo "CEI:"
    m = re.search(r"CEI:\s*(\d{12})\b", texto)
    if m:
        return m.group(1)
    # documento em CPF puro (ex: DARF/guia de empregador pessoa física) —
    # só usa como último recurso: num extrato com vários funcionários, o
    # CPF mais comum pode ser de um funcionário, não da empresa
    cpfs = re.findall(r"\d{3}\.\d{3}\.\d{3}-\d{2}", texto)
    if cpfs:
        return Counter(cpfs).most_common(1)[0][0]
    return None


def _extrair_nome(texto):
    """Nome da empresa/pessoa — usado como fallback de casamento quando os
    documentos não compartilham nenhum número em comum (ex: extrato com CEI
    x guia com CPF, que são identificadores totalmente diferentes, sem
    dígito compartilhado)."""
    m = re.search(r"Empresa:\s*\d+\s*-\s*([^\n]+?)\s*(?:P[áa]gina|\n)", texto)
    if m:
        return m.group(1).strip()
    m = re.search(r"(?:CPF|CNPJ)\s+Nome\s+[\d./-]+\s+([^\n]+)", texto)
    if m:
        return m.group(1).strip()
    return None


def _normalizar_nome(nome):
    """Maiúsculas, sem acento, só letras — pra comparar 'Queti Daiana Pezzi
    Buss' com 'QUETI DAIANA PEZZI BUSS' independente de formatação."""
    if not nome:
        return ""
    s = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z ]", " ", s).upper()
    return re.sub(r"\s+", " ", s).strip()


def _achar_guia(guias_dict, cnpj_norm, nome_extrato):
    """Acha a guia correspondente: primeiro por CNPJ/CPF/CEI, e se não achar
    (documentos com numeração totalmente diferente), tenta por nome."""
    guia = guias_dict.get(cnpj_norm)
    if guia is not None:
        return guia
    alvo = _normalizar_nome(nome_extrato)
    if not alvo:
        return None
    for g in guias_dict.values():
        if _normalizar_nome(g.get("nome")) == alvo:
            return g
    return None


def _chave_cnpj(cnpj_ou_texto):
    """Chave de casamento entre extrato/guia FGTS/guia DCTFWEB.
    - CNPJ normal (filial de 4 dígitos) ou raiz solta (8 dígitos): raiz de 8.
    - CAEPF (empregador pessoa física, filial de 3 dígitos) ou CPF puro:
      base de 9 dígitos do CPF — extrato (CAEPF) e guia (CPF) têm o mesmo
      CPF-base mas dígito verificador/filial diferentes no final, então
      não dá pra casar pelo número completo."""
    valor = cnpj_ou_texto or ""
    if re.fullmatch(r"\d{3}\.\d{3}\.\d{3}/\d{3}-\d{2}", valor) or re.fullmatch(r"\d{3}\.\d{3}\.\d{3}-\d{2}", valor):
        return re.sub(r"\D", "", valor)[:9]
    digitos = re.sub(r"\D", "", valor)
    if len(digitos) == 11:  # CPF sem formatação (fallback)
        return digitos[:9]
    return digitos[:8]


def _normalizar_cnpj(cnpj):
    return re.sub(r"\D", "", cnpj or "")


def _parse_valor(txt):
    return float(txt.replace(".", "").replace(",", "."))


def _extrair_valor_fgts(texto):
    """'Valor do FGTS:' (total da empresa) — não confundir com 'Valor FGTS:'
    (sem 'do'), que aparece em cada lançamento individual de empregado."""
    m = re.search(r"Valor do FGTS:\s*([\d.]+,\d{2})", texto)
    return _parse_valor(m.group(1)) if m else None


def _extrair_total_inss(texto):
    m = re.search(r"Total INSS:\s*([\d.]+,\d{2})", texto)
    return _parse_valor(m.group(1)) if m else None


def _extrair_valor_irrf(texto):
    """Pega a 2ª ocorrência (competência do pagamento), que é a que a
    DCTFWEB usa. Se só tiver uma ocorrência, usa essa.
    Retorna None (não 0.0!) se não achar nenhuma — zero de verdade só
    conta se o PDF realmente disser '0,00'."""
    matches = re.findall(r"Valor Total do IRRF:\s*([\d.]+,\d{2})", texto)
    if not matches:
        return None
    return _parse_valor(matches[-1])


def _extrair_valor_guia_dctf(texto):
    m = re.search(r"Valor Total do Documento\s+([\d.]+,\d{2})", texto)
    if m:
        return _parse_valor(m.group(1))
    m = re.search(r"Totais\s+([\d.]+,\d{2})\s+([\d.]+,\d{2})", texto)
    if m:
        return _parse_valor(m.group(2))
    return None


def _extrair_valor_guia_fgts(texto):
    """'Total FGTS:' — o valor puro de FGTS (última coluna da linha).
    NÃO usar 'Total da Guia:', que soma FGTS + Consignado quando a empresa
    tem empréstimo consignado descontado — isso dá falso divergente."""
    m = re.search(r"Total FGTS:\s*((?:[\d.]+,\d{2}\s*){1,5})", texto)
    if not m:
        return None
    numeros = re.findall(r"[\d.]+,\d{2}", m.group(1))
    return _parse_valor(numeros[-1]) if numeros else None


def montar_caminhos(base_drive, ano, mes):
    """Monta os 3 caminhos padrão (extrato, guia FGTS, guia DCTFWEB) pra uma competência."""
    base = Path(base_drive) / f"1 FOLHAS {ano}" / f"Folha {mes:02d}{ano}"
    pasta_extratos = base / f"Extrato analítico {mes:02d}.{ano}"
    pasta_guias_fgts = base / f"1 GRF {mes:02d}.{ano}"
    pasta_guias_dctfweb = base / f"DCTFWEB IR {mes:02d}.{ano}"
    return pasta_extratos, pasta_guias_fgts, pasta_guias_dctfweb


def _ler_pasta(pasta):
    """Lê todos os PDFs de uma pasta e retorna dict {cnpj_normalizado: {...}}"""
    dados = {}
    erros = []
    if not pasta.exists():
        return dados, erros
    for pdf_path in sorted(pasta.glob("*.pdf")):
        try:
            texto = _extrair_texto(pdf_path)
            cnpj = _extrair_cnpj(texto)
            if not cnpj:
                erros.append(f"{pdf_path.name}: não achei CNPJ no PDF")
                continue
            dados[_chave_cnpj(cnpj)] = {"texto": texto, "cnpj": cnpj, "arquivo": pdf_path.name, "nome": _extrair_nome(texto)}
        except Exception as e:
            erros.append(f"{pdf_path.name}: erro ao ler ({e})")
    return dados, erros


def _ler_pasta_drive(drive, pasta_id):
    """Igual a _ler_pasta, mas lê do Google Drive via API em vez do disco local."""
    dados = {}
    erros = []
    if pasta_id is None:
        return dados, erros
    for arq in drive.listar_pdfs(pasta_id):
        try:
            conteudo = drive.baixar_arquivo(arq["id"])
            texto = _extrair_texto(conteudo)
            cnpj = _extrair_cnpj(texto)
            if not cnpj:
                erros.append(f"{arq['name']}: não achei CNPJ no PDF")
                continue
            dados[_chave_cnpj(cnpj)] = {"texto": texto, "cnpj": cnpj, "arquivo": arq["name"], "nome": _extrair_nome(texto)}
        except Exception as e:
            erros.append(f"{arq['name']}: erro ao ler ({e})")
    return dados, erros


def conciliar_via_drive(drive, pasta_raiz_drive, ano, mes, clientes):
    """
    Mesma conciliação de sempre, mas lendo do Google Drive via API (não do
    disco local) — funciona rodando em qualquer máquina, inclusive na nuvem.

    `drive` = instância de DriveClient já autenticada.
    `pasta_raiz_drive` = caminho da pasta raiz no Drive, ex:
        "1000 - RH - CLIENTES ALM"
    """
    caminho_base = f"{pasta_raiz_drive}/1 FOLHAS {ano}/Folha {mes:02d}{ano}"
    avisos = []

    id_extratos = drive.achar_pasta_por_caminho(f"{caminho_base}/Extrato analítico {mes:02d}.{ano}")
    id_guias_fgts = drive.achar_pasta_por_caminho(f"{caminho_base}/1 GRF {mes:02d}.{ano}")
    id_guias_dctf = drive.achar_pasta_por_caminho(f"{caminho_base}/DCTFWEB IR {mes:02d}.{ano}")

    if id_extratos is None:
        avisos.append(f"Pasta de extratos não encontrada no Drive: {caminho_base}/Extrato analítico {mes:02d}.{ano}")
        return [], avisos
    if id_guias_fgts is None:
        avisos.append(f"Pasta de guias FGTS não encontrada no Drive (pode ser que ainda não liberou nenhuma): {caminho_base}/1 GRF {mes:02d}.{ano}")
    if id_guias_dctf is None:
        avisos.append(f"Pasta de guias DCTFWEB não encontrada no Drive (pode ser que ainda não liberou nenhuma): {caminho_base}/DCTFWEB IR {mes:02d}.{ano}")

    extratos, e1 = _ler_pasta_drive(drive, id_extratos)
    guias_fgts, e2 = _ler_pasta_drive(drive, id_guias_fgts)
    guias_dctfweb, e3 = _ler_pasta_drive(drive, id_guias_dctf)
    avisos.extend(e1); avisos.extend(e2); avisos.extend(e3)

    return _montar_resultados(extratos, guias_fgts, guias_dctfweb, clientes, avisos)


def _conciliar_guia(valor_esperado, guia, extrator_valor):
    """Concilia um valor de referência contra uma guia (se existir).
    Retorna (valor_extraido_da_guia, status, arquivo)."""
    if guia is None:
        return None, "-", None
    valor_guia = extrator_valor(guia["texto"])
    if valor_guia is None:
        return None, "?", guia["arquivo"]  # achou a guia mas não conseguiu ler o valor
    status = "OK" if abs(valor_guia - valor_esperado) < 0.01 else "X"
    return valor_guia, status, guia["arquivo"]


def _montar_resultados(extratos, guias_fgts, guias_dctfweb, clientes, avisos):
    resultados = []
    for cnpj_norm, dado in extratos.items():
        valor_fgts = _extrair_valor_fgts(dado["texto"])
        total_inss = _extrair_total_inss(dado["texto"])
        total_irrf = _extrair_valor_irrf(dado["texto"])

        if valor_fgts is None:
            avisos.append(f"❌ {dado['arquivo']}: NÃO achei 'Valor do FGTS' — confere o PDF, isso não devia faltar")
        if total_inss is None:
            avisos.append(f"❌ {dado['arquivo']}: NÃO achei 'Total INSS' — confere o PDF, isso não devia faltar")
        if total_irrf is None:
            avisos.append(f"❌ {dado['arquivo']}: NÃO achei 'Valor Total do IRRF' — confere o PDF, isso não devia faltar")

        esperado_inss = round(total_inss + total_irrf, 2) if (total_inss is not None and total_irrf is not None) else None

        empresa = next((c["empresa"] for c in clientes if _chave_cnpj(c["cnpj"]) == cnpj_norm), None)
        codigo = next((c["codigo"] for c in clientes if _chave_cnpj(c["cnpj"]) == cnpj_norm), None)
        if empresa is None and dado.get("nome"):
            alvo = _normalizar_nome(dado["nome"])
            for c in clientes:
                nome_cliente = c.get("empresa") or ""
                # nome do cliente costuma vir como "SOBRENOME, Nome" ou só o nome —
                # compara por conjunto de palavras pra pegar mesmo fora de ordem
                palavras_alvo = set(_normalizar_nome(nome_cliente).split())
                if palavras_alvo and palavras_alvo <= set(alvo.split()):
                    empresa, codigo = c["empresa"], c.get("codigo")
                    break

        if valor_fgts is not None:
            guia_fgts = _achar_guia(guias_fgts, cnpj_norm, dado.get("nome"))
            valor_guia_fgts, status_fgts, arq_fgts = _conciliar_guia(valor_fgts, guia_fgts, _extrair_valor_guia_fgts)
        else:
            valor_guia_fgts, status_fgts, arq_fgts = None, "!", None  # não dá pra conciliar sem o valor de referência

        if esperado_inss is not None:
            guia_dctf = _achar_guia(guias_dctfweb, cnpj_norm, dado.get("nome"))
            valor_guia_dctf, status_dctf, arq_dctf = _conciliar_guia(esperado_inss, guia_dctf, _extrair_valor_guia_dctf)
        else:
            valor_guia_dctf, status_dctf, arq_dctf = None, "!", None

        # nenhuma empresa é descartada — mesmo com falha de extração, ela aparece na lista com status "!" (erro)
        resultados.append({
            "codigo": codigo, "empresa": empresa or dado["cnpj"], "cnpj": dado["cnpj"],
            "valor_fgts": valor_fgts, "guia_fgts": valor_guia_fgts, "status_fgts": status_fgts,
            "total_inss": total_inss, "total_irrf": total_irrf, "esperado_inss": esperado_inss,
            "guia_dctf": valor_guia_dctf, "status_dctf": status_dctf,
            "arquivo_extrato": dado["arquivo"], "arquivo_guia_fgts": arq_fgts, "arquivo_guia_dctf": arq_dctf,
        })

    nomes_extratos = {_normalizar_nome(d.get("nome")) for d in extratos.values()} - {""}
    for cnpj_norm, guia in guias_fgts.items():
        if cnpj_norm not in extratos and _normalizar_nome(guia.get("nome")) not in nomes_extratos:
            avisos.append(f"{guia['arquivo']}: guia FGTS sem extrato correspondente (CNPJ {guia['cnpj']})")
    for cnpj_norm, guia in guias_dctfweb.items():
        if cnpj_norm not in extratos and _normalizar_nome(guia.get("nome")) not in nomes_extratos:
            avisos.append(f"{guia['arquivo']}: guia DCTFWEB sem extrato correspondente (CNPJ {guia['cnpj']})")

    resultados.sort(key=lambda r: (r["codigo"] is None, r["codigo"]))
    return resultados, avisos


def _ler_arquivos_upload(arquivos_upload):
    """Igual a _ler_pasta, mas a partir de arquivos vindos de st.file_uploader
    (objetos com .name e .getvalue() / .read())."""
    dados = {}
    erros = []
    for arq in arquivos_upload or []:
        try:
            conteudo = arq.getvalue() if hasattr(arq, "getvalue") else arq.read()
            texto = _extrair_texto(conteudo)
            cnpj = _extrair_cnpj(texto)
            if not cnpj:
                erros.append(f"{arq.name}: não achei CNPJ no PDF")
                continue
            dados[_chave_cnpj(cnpj)] = {"texto": texto, "cnpj": cnpj, "arquivo": arq.name, "nome": _extrair_nome(texto)}
        except Exception as e:
            erros.append(f"{arq.name}: erro ao ler ({e})")
    return dados, erros


def conciliar_via_upload(arquivos_extratos, arquivos_guias_fgts, arquivos_guias_dctf, clientes):
    """Mesma conciliação de sempre, a partir de arquivos enviados por upload
    (st.file_uploader), em vez de caminho local ou Drive."""
    avisos = []
    extratos, e1 = _ler_arquivos_upload(arquivos_extratos)
    guias_fgts, e2 = _ler_arquivos_upload(arquivos_guias_fgts)
    guias_dctfweb, e3 = _ler_arquivos_upload(arquivos_guias_dctf)
    avisos.extend(e1); avisos.extend(e2); avisos.extend(e3)
    if not extratos:
        avisos.append("Nenhum extrato analítico enviado.")
        return [], avisos
    return _montar_resultados(extratos, guias_fgts, guias_dctfweb, clientes, avisos)


def conciliar(base_drive, ano, mes, clientes):
    """
    Roda a conciliação completa de uma competência: extrai FGTS + INSS do
    extrato analítico de cada empresa e concilia contra a guia FGTS e a
    guia DCTFWEB, cada uma independente (uma pode estar liberada e a outra não).

    `clientes` = lista de dicts com pelo menos 'empresa' e 'cnpj' (ex: db.listar_clientes()).
    Retorna (resultados, avisos).
    """
    pasta_extratos, pasta_guias_fgts, pasta_guias_dctfweb = montar_caminhos(base_drive, ano, mes)
    avisos = []

    if not pasta_extratos.exists():
        avisos.append(f"Pasta de extratos não encontrada: {pasta_extratos}")
        return [], avisos
    if not pasta_guias_fgts.exists():
        avisos.append(f"Pasta de guias FGTS não encontrada (pode ser que ainda não liberou nenhuma): {pasta_guias_fgts}")
    if not pasta_guias_dctfweb.exists():
        avisos.append(f"Pasta de guias DCTFWEB não encontrada (pode ser que ainda não liberou nenhuma): {pasta_guias_dctfweb}")

    extratos, erros_extratos = _ler_pasta(pasta_extratos)
    guias_fgts, erros_fgts = _ler_pasta(pasta_guias_fgts)
    guias_dctfweb, erros_dctfweb = _ler_pasta(pasta_guias_dctfweb)
    avisos.extend(erros_extratos)
    avisos.extend(erros_fgts)
    avisos.extend(erros_dctfweb)

    return _montar_resultados(extratos, guias_fgts, guias_dctfweb, clientes, avisos)
