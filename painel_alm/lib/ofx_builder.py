import re
from datetime import date, datetime
from collections import defaultdict

BANK_CODES = {
    'itau': '0341',
    'bradesco': '0237',
    'sicoob': '0756',
    'c6': '0336',
    'stone': '0197',
}


def build_acctid(agencia, conta):
    """Replica a regra observada no OFX real: agência + número da conta sem zeros
    à esquerda (mantendo o dígito verificador). Ex: ag=7424, conta='0099319-9' -> '7424993199'.
    Se a conta não tiver hífen (ex: C6 Bank), usa agência+conta direto."""
    agencia = re.sub(r'\D', '', agencia or '')
    conta = (conta or '').replace('.', '')
    if '-' in conta:
        main, dv = conta.rsplit('-', 1)
        main = re.sub(r'\D', '', main).lstrip('0') or '0'
        dv = re.sub(r'\D', '', dv)
        return f'{agencia}{main}{dv}'
    conta_digits = re.sub(r'\D', '', conta)
    return f'{agencia}{conta_digits}'


def _fmt_dt(d, hour='100000'):
    return f'{d.strftime("%Y%m%d")}{hour}[-03:EST]'


def group_by_month(transactions):
    """Agrupa transações por (ano, mês). Retorna dict {(ano,mes): [tx...]}"""
    buckets = defaultdict(list)
    for tx in transactions:
        key = (tx['date'].year, tx['date'].month)
        buckets[key].append(tx)
    return buckets


def build_ofx(transactions, bank_key, agencia, conta, year, month,
              current_balance=None, balance_date=None):
    """Monta o texto OFX pra um (empresa+conta) num mês específico, no formato
    exato observado no arquivo de exemplo do Domínio."""
    bank_id = BANK_CODES.get(bank_key, '0000')
    acct_id = build_acctid(agencia, conta)

    # ordena por data desc (mais recente primeiro), como no exemplo original,
    # e dentro do mesmo dia mantém a ordem em que vieram do PDF
    txs_sorted = sorted(transactions, key=lambda t: t['date'], reverse=True)

    first_day = date(year, month, 1)
    if month == 12:
        last_day = date(year, 12, 31)
    else:
        last_day = date(year, month + 1, 1)
        last_day = date(last_day.year, last_day.month, last_day.day - last_day.day + 1)
        # último dia do mês
    import calendar
    last_day = date(year, month, calendar.monthrange(year, month)[1])

    lines = []
    lines.append('OFXHEADER:100')
    lines.append('DATA:OFXSGML')
    lines.append('VERSION:102')
    lines.append('SECURITY:NONE')
    lines.append('ENCODING:USASCII')
    lines.append('CHARSET:1252')
    lines.append('COMPRESSION:NONE')
    lines.append('OLDFILEUID:NONE')
    lines.append('NEWFILEUID:NONE')
    lines.append('')
    lines.append('<OFX>')
    lines.append('<SIGNONMSGSRSV1>')
    lines.append('<SONRS>')
    lines.append('<STATUS>')
    lines.append('<CODE>0')
    lines.append('<SEVERITY>INFO')
    lines.append('</STATUS>')
    lines.append(f'<DTSERVER>{_fmt_dt(balance_date or last_day)}')
    lines.append('<LANGUAGE>POR')
    lines.append('</SONRS>')
    lines.append('</SIGNONMSGSRSV1>')
    lines.append('<BANKMSGSRSV1>')
    lines.append('<STMTTRNRS>')
    lines.append('<TRNUID>1001')
    lines.append('<STATUS>')
    lines.append('<CODE>0')
    lines.append('<SEVERITY>INFO')
    lines.append('</STATUS>')
    lines.append('<STMTRS>')
    lines.append('<CURDEF>BRL')
    lines.append('<BANKACCTFROM>')
    lines.append(f'<BANKID>{bank_id}')
    lines.append(f'<ACCTID>{acct_id}')
    lines.append('<ACCTTYPE>CHECKING')
    lines.append('</BANKACCTFROM>')
    lines.append('<BANKTRANLIST>')
    lines.append(f'<DTSTART>{_fmt_dt(first_day)}')
    lines.append(f'<DTEND>{_fmt_dt(last_day)}')

    day_seq = defaultdict(int)
    for tx in txs_sorted:
        d = tx['date']
        day_seq[d] += 1
        seq = day_seq[d]
        fitid = f'{d.strftime("%Y%m%d")}{seq:03d}'
        trntype = 'CREDIT' if tx['value'] >= 0 else 'DEBIT'
        memo = tx['desc'].strip() or '(sem descrição)'
        lines.append('<STMTTRN>')
        lines.append(f'<TRNTYPE>{trntype}')
        lines.append(f'<DTPOSTED>{_fmt_dt(d)}')
        lines.append(f'<TRNAMT>{tx["value"]:.2f}')
        lines.append(f'<FITID>{fitid}')
        lines.append(f'<CHECKNUM>{fitid}')
        lines.append(f'<MEMO>{memo}')
        lines.append('</STMTTRN>')

    lines.append('</BANKTRANLIST>')
    lines.append('<LEDGERBAL>')
    bal = current_balance if current_balance is not None else (txs_sorted[0]['running_balance'] if txs_sorted and 'running_balance' in txs_sorted[0] else 0)
    lines.append(f'<BALAMT>{bal:.2f}' if isinstance(bal, (int, float)) else f'<BALAMT>{bal}')
    lines.append(f'<DTASOF>{_fmt_dt(balance_date or last_day)}')
    lines.append('</LEDGERBAL>')
    lines.append('</STMTRS>')
    lines.append('</STMTTRNRS>')
    lines.append('</BANKMSGSRSV1>')
    lines.append('</OFX>')

    return '\n'.join(lines)
