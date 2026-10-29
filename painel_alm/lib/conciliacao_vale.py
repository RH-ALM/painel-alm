"""Conciliação Vale Alimentação / Reembolso — folha 10/2026.

Lê data/conciliacao_vale_10-2026.csv (separador ';') gerado a partir da relação
do Domínio e dos recibos da pasta. Não usa o SQLite.
"""
import os
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "..", "data", "conciliacao_vale_10-2026.csv")


def carregar():
    df = pd.read_csv(CSV, sep=";", encoding="utf-8-sig", dtype=str)
    for c in ["Dias_trabalhados", "Valor_devido", "Valor_relacao", "Diferenca"]:
        df[c] = pd.to_numeric(df[c].str.replace(",", ".", regex=False), errors="coerce")
    return df
