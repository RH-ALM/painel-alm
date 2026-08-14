import sqlite3
import os
import sys
import hashlib
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'extratos.db')

# --- Sincronização opcional com o Google Drive ---------------------------
# Se existir client_secret.json na raiz do projeto, o banco passa a viver
# na pasta "Painel ALM - Dados" do Drive: baixa uma vez por sessão (não
# baixa de novo a cada rerun do Streamlit, senão sobrescreveria mudanças
# recentes) e sobe depois de cada escrita. Se não existir client_secret.json,
# funciona 100% local, do jeito que sempre funcionou.
DRIVE_PASTA_NOME = "Painel ALM - Dados"
DRIVE_ARQUIVO_NOME = "extratos.db"
_CLIENT_SECRET_PATH = os.path.join(os.path.dirname(__file__), '..', 'client_secret.json')
_TOKEN_PATH = os.path.join(os.path.dirname(__file__), '..', 'token.json')

_drive_client = None
_drive_pasta_id = None
_ja_baixou_do_drive = False


def _drive_habilitado():
    if os.path.exists(_CLIENT_SECRET_PATH):
        return True
    try:
        import streamlit as st
        return hasattr(st, "secrets") and "gcp_token" in st.secrets
    except Exception:
        return False


def _get_drive():
    global _drive_client, _drive_pasta_id
    if not _drive_habilitado():
        return None
    if _drive_client is None:
        sys.path.append(os.path.dirname(__file__))
        from drive_client import DriveClient
        try:
            import streamlit as st
            tem_secrets = hasattr(st, "secrets") and "gcp_token" in st.secrets
        except Exception:
            tem_secrets = False

        if tem_secrets:
            # rodando no Streamlit Cloud: usa o token já pronto guardado nos Secrets
            _drive_client = DriveClient.via_token_dict(dict(st.secrets["gcp_token"]))
        else:
            # rodando localmente: usa os arquivos client_secret.json / token.json
            _drive_client = DriveClient.via_oauth(_CLIENT_SECRET_PATH, _TOKEN_PATH)

        _drive_pasta_id = _drive_client.achar_pasta_por_caminho(DRIVE_PASTA_NOME)
        if _drive_pasta_id is None:
            raise RuntimeError(
                f"Pasta '{DRIVE_PASTA_NOME}' não encontrada no Drive dessa conta. "
                f"Confere se o nome está exatamente igual."
            )
    return _drive_client


def _baixar_db_do_drive_se_precisar():
    """Baixa o banco do Drive só na primeira vez que o processo do Streamlit
    sobe (não em todo rerun), pra não sobrescrever escritas recentes ainda
    não subidas — e nunca sobrescreve se o download falhar."""
    global _ja_baixou_do_drive
    if _ja_baixou_do_drive or not _drive_habilitado():
        return
    drive = _get_drive()
    arquivo_id = drive.achar_arquivo(_drive_pasta_id, DRIVE_ARQUIVO_NOME)
    if arquivo_id:
        conteudo = drive.baixar_arquivo(arquivo_id)
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        with open(DB_PATH, "wb") as f:
            f.write(conteudo)
    # se não achou arquivo no Drive ainda, deixa seguir e cria um banco novo
    # local — a primeira escrita vai subir ele pro Drive.
    _ja_baixou_do_drive = True


def _subir_db_pro_drive():
    """Sobe o banco local pro Drive depois de cada escrita. Silenciosamente
    ignora se o Drive não estiver configurado (uso 100% local)."""
    if not _drive_habilitado():
        return
    try:
        drive = _get_drive()
        with open(DB_PATH, "rb") as f:
            conteudo = f.read()
        drive.subir_arquivo(_drive_pasta_id, DRIVE_ARQUIVO_NOME, conteudo, "application/x-sqlite3")
    except Exception as e:
        # não derruba a operação do usuário por causa de um problema de rede/Drive —
        # só avisa. O dado já está salvo localmente de qualquer forma.
        print(f"[aviso] Não consegui sincronizar o banco com o Drive agora: {e}")


def _connect():
    _baixar_db_do_drive_se_precisar()
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS transacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa TEXT NOT NULL,
            cnpj TEXT,
            banco TEXT NOT NULL,
            agencia TEXT,
            conta TEXT,
            data DATE NOT NULL,
            descricao TEXT,
            valor REAL NOT NULL,
            arquivo_origem TEXT,
            importado_em TIMESTAMP,
            dedup_key TEXT UNIQUE
        )
    ''')

    # confirmacoes: granularidade por empresa+banco+agencia+conta+ano+mes
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='confirmacoes'")
    existe = cur.fetchone() is not None
    if existe:
        cols = [r[1] for r in conn.execute('PRAGMA table_info(confirmacoes)')]
        if 'banco' not in cols:
            # migração: tabela antiga só tinha empresa+ano+mes. Preserva os dados
            # antigos como confirmações "genéricas" (sem conta específica).
            conn.execute('ALTER TABLE confirmacoes RENAME TO confirmacoes_old')
            conn.execute('''
                CREATE TABLE confirmacoes (
                    empresa TEXT NOT NULL,
                    banco TEXT NOT NULL DEFAULT '',
                    agencia TEXT NOT NULL DEFAULT '',
                    conta TEXT NOT NULL DEFAULT '',
                    ano INTEGER NOT NULL,
                    mes INTEGER NOT NULL,
                    confirmado INTEGER NOT NULL DEFAULT 0,
                    confirmado_em TIMESTAMP,
                    PRIMARY KEY (empresa, banco, agencia, conta, ano, mes)
                )
            ''')
            conn.execute('''
                INSERT INTO confirmacoes (empresa, banco, agencia, conta, ano, mes, confirmado, confirmado_em)
                SELECT empresa, '', '', '', ano, mes, confirmado, confirmado_em FROM confirmacoes_old
            ''')
            conn.execute('DROP TABLE confirmacoes_old')
    else:
        conn.execute('''
            CREATE TABLE confirmacoes (
                empresa TEXT NOT NULL,
                banco TEXT NOT NULL DEFAULT '',
                agencia TEXT NOT NULL DEFAULT '',
                conta TEXT NOT NULL DEFAULT '',
                ano INTEGER NOT NULL,
                mes INTEGER NOT NULL,
                confirmado INTEGER NOT NULL DEFAULT 0,
                confirmado_em TIMESTAMP,
                PRIMARY KEY (empresa, banco, agencia, conta, ano, mes)
            )
        ''')
    # clientes: migrado de lista fixa no código pra dado editável
    conn.execute('''
        CREATE TABLE IF NOT EXISTS clientes (
            codigo INTEGER,
            empresa TEXT NOT NULL,
            nome TEXT,
            cnpj TEXT NOT NULL UNIQUE
        )
    ''')
    conn.commit()
    return conn


def _dedup_key(empresa, banco, agencia, conta, data, descricao, valor):
    raw = f'{empresa}|{banco}|{agencia}|{conta}|{data}|{descricao}|{valor:.2f}'
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def salvar_transacoes(empresa, cnpj, transacoes, banco, agencia, conta, arquivo_origem):
    """Salva transações no banco, ignorando duplicatas (mesma empresa/banco/conta/data/desc/valor)."""
    conn = _connect()
    novas = 0
    duplicadas = 0
    agora = datetime.now().isoformat()
    for t in transacoes:
        key = _dedup_key(empresa, banco, agencia, conta, t['date'].isoformat(), t['desc'], t['value'])
        try:
            conn.execute(
                'INSERT INTO transacoes (empresa, cnpj, banco, agencia, conta, data, descricao, valor, '
                'arquivo_origem, importado_em, dedup_key) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (empresa, cnpj, banco, agencia, conta, t['date'].isoformat(), t['desc'], t['value'],
                 arquivo_origem, agora, key)
            )
            novas += 1
        except sqlite3.IntegrityError:
            duplicadas += 1
    conn.commit()
    conn.close()
    _subir_db_pro_drive()
    return novas, duplicadas


def carregar_transacoes(empresa):
    """Carrega todas as transações já salvas dessa empresa."""
    from datetime import datetime as dt
    conn = _connect()
    cur = conn.execute(
        'SELECT banco, agencia, conta, data, descricao, valor, arquivo_origem FROM transacoes WHERE empresa = ? ORDER BY data DESC',
        (empresa,)
    )
    rows = cur.fetchall()
    conn.close()
    result = []
    for banco, agencia, conta, data, descricao, valor, arquivo in rows:
        result.append({
            'date': dt.strptime(data, '%Y-%m-%d').date(),
            'desc': descricao,
            'value': valor,
            'bank': banco,
            'agencia': agencia,
            'conta': conta,
            'arquivo': arquivo,
        })
    return result


def apagar_periodo(empresa, banco, agencia, conta, year, month):
    """Apaga os lançamentos de uma empresa/banco/conta num mês específico (pra corrigir e reprocessar)."""
    conn = _connect()
    cur = conn.execute(
        "DELETE FROM transacoes WHERE empresa=? AND banco=? AND agencia=? AND conta=? "
        "AND strftime('%Y', data)=? AND strftime('%m', data)=?",
        (empresa, banco, agencia, conta, str(year), f'{month:02d}')
    )
    conn.commit()
    apagados = cur.rowcount
    conn.close()
    _subir_db_pro_drive()
    return apagados


def listar_empresas_salvas():
    conn = _connect()
    cur = conn.execute('SELECT DISTINCT empresa FROM transacoes ORDER BY empresa')
    result = [r[0] for r in cur.fetchall()]
    conn.close()
    return result


def set_confirmado(empresa, banco, agencia, conta, ano, mes, confirmado):
    conn = _connect()
    agora = datetime.now().isoformat() if confirmado else None
    conn.execute(
        'INSERT INTO confirmacoes (empresa, banco, agencia, conta, ano, mes, confirmado, confirmado_em) '
        'VALUES (?,?,?,?,?,?,?,?) '
        'ON CONFLICT(empresa, banco, agencia, conta, ano, mes) '
        'DO UPDATE SET confirmado=excluded.confirmado, confirmado_em=excluded.confirmado_em',
        (empresa, banco, agencia, conta, ano, mes, 1 if confirmado else 0, agora)
    )
    conn.commit()
    conn.close()
    _subir_db_pro_drive()


def is_confirmado(empresa, banco, agencia, conta, ano, mes):
    conn = _connect()
    cur = conn.execute(
        'SELECT confirmado FROM confirmacoes WHERE empresa=? AND banco=? AND agencia=? AND conta=? AND ano=? AND mes=?',
        (empresa, banco, agencia, conta, ano, mes)
    )
    row = cur.fetchone()
    conn.close()
    return bool(row and row[0])


def listar_periodos(empresa):
    """Lista cada combinação (banco, agencia, conta, ano, mes) que tem lançamentos
    dessa empresa, com contagem e se já foi confirmada."""
    conn = _connect()
    cur = conn.execute(
        "SELECT banco, agencia, conta, CAST(strftime('%Y',data) AS INTEGER), CAST(strftime('%m',data) AS INTEGER), "
        "COUNT(*) FROM transacoes WHERE empresa=? GROUP BY banco, agencia, conta, strftime('%Y',data), strftime('%m',data) "
        "ORDER BY strftime('%Y',data) DESC, strftime('%m',data) DESC",
        (empresa,)
    )
    rows = cur.fetchall()
    conn.close()
    result = []
    for banco, agencia, conta, ano, mes, qtd in rows:
        result.append({
            'banco': banco, 'agencia': agencia, 'conta': conta, 'ano': ano, 'mes': mes,
            'qtd': qtd, 'confirmado': is_confirmado(empresa, banco, agencia, conta, ano, mes),
        })
    return result


def status_do_ano(empresa, ano):
    """
    Retorna, pra cada mês (1-12) do ano: 'confirmado' só se TODAS as contas/bancos
    daquele mês já foram confirmadas; 'extraido' se tem dado mas falta confirmar
    alguma conta; 'sem_dados' se não tem nada extraído.
    """
    periodos = listar_periodos(empresa)
    por_mes = {}
    for p in periodos:
        if p['ano'] != ano:
            continue
        por_mes.setdefault(p['mes'], []).append(p['confirmado'])

    status = {}
    for m in range(1, 13):
        confirmacoes = por_mes.get(m)
        if not confirmacoes:
            status[m] = 'sem_dados'
        elif all(confirmacoes):
            status[m] = 'confirmado'
        else:
            status[m] = 'extraido'
    return status


def anos_com_dados(empresa):
    """Anos em que essa empresa tem dados extraídos OU confirmação manual."""
    conn = _connect()
    cur = conn.execute("SELECT DISTINCT CAST(strftime('%Y', data) AS INTEGER) FROM transacoes WHERE empresa=?", (empresa,))
    anos = {r[0] for r in cur.fetchall()}
    cur = conn.execute('SELECT DISTINCT ano FROM confirmacoes WHERE empresa=?', (empresa,))
    anos |= {r[0] for r in cur.fetchall()}
    conn.close()
    return anos


def listar_clientes():
    conn = _connect()
    cur = conn.execute('SELECT codigo, empresa, nome, cnpj FROM clientes ORDER BY codigo')
    rows = cur.fetchall()
    conn.close()
    return [{'codigo': r[0], 'empresa': r[1], 'nome': r[2], 'cnpj': r[3]} for r in rows]


def salvar_clientes(lista):
    """Substitui TODA a lista de clientes pela fornecida (usado pela tela de Configurações,
    que edita/adiciona/apaga linhas numa tabela e salva tudo de uma vez)."""
    conn = _connect()
    conn.execute('DELETE FROM clientes')
    for c in lista:
        cnpj = (c.get('cnpj') or '').strip()
        empresa = (c.get('empresa') or '').strip()
        if not empresa or not cnpj:
            continue
        conn.execute(
            'INSERT OR IGNORE INTO clientes (codigo, empresa, nome, cnpj) VALUES (?,?,?,?)',
            (c.get('codigo'), empresa, c.get('nome') or '', cnpj)
        )
    conn.commit()
    conn.close()
    _subir_db_pro_drive()


def seed_clientes_se_vazio(lista_inicial):
    """Na primeira vez que o app roda, popula a tabela de clientes com a lista inicial
    (evita começar do zero, mas depois disso quem manda é o banco, não o código)."""
    conn = _connect()
    cur = conn.execute('SELECT COUNT(*) FROM clientes')
    total = cur.fetchone()[0]
    conn.close()
    if total == 0:
        salvar_clientes(lista_inicial)


def percentual_completude(empresa, ano):
    """
    % de meses 'em dia' (extraído ou confirmado) sobre os meses que já deveriam
    estar fechados. O mês corrente nunca conta como devido, porque ainda não fechou.
    Retorna (percentual, meses_feitos, meses_devidos).
    """
    hoje = datetime.now()
    if ano < hoje.year:
        meses_devidos = 12
    elif ano == hoje.year:
        meses_devidos = hoje.month - 1  # até o mês anterior, o corrente não conta
    else:
        meses_devidos = 0

    if meses_devidos <= 0:
        return None, 0, 0

    status = status_do_ano(empresa, ano)
    meses_feitos = sum(1 for m in range(1, meses_devidos + 1) if status.get(m) in ('confirmado', 'extraido'))
    percentual = round(100 * meses_feitos / meses_devidos)
    return percentual, meses_feitos, meses_devidos
