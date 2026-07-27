"""
Script de teste — roda uma vez só, pra confirmar que o login com o Google
e o acesso à pasta "Painel ALM - Dados" estão funcionando.

Como rodar (no CMD, dentro da pasta do projeto):
    pip install google-api-python-client google-auth google-auth-oauthlib --break-system-packages
    python test_drive.py

Na primeira vez vai abrir o navegador pedindo pra você logar com a conta
Google e autorizar o acesso ao Drive. Depois disso, salva um token.json e
não pede login de novo.
"""

import sys
sys.path.insert(0, "lib")
from drive_client import DriveClient

print("Abrindo o navegador pra login/autorização (se for a primeira vez)...")
drive = DriveClient.via_oauth("client_secret.json", "token.json")
print("Login OK!\n")

NOME_PASTA = "Painel ALM - Dados"
print(f"Procurando a pasta '{NOME_PASTA}'...")
pasta_id = drive.achar_pasta_por_caminho(NOME_PASTA)

if pasta_id is None:
    print(f"❌ Não achei a pasta '{NOME_PASTA}'. Confere se o nome está exatamente igual "
          f"(maiúsculas/minúsculas e espaços importam) e se ela está na raiz do seu Drive "
          f"(não dentro de outra pasta).")
    sys.exit(1)

print(f"✅ Achei a pasta! ID: {pasta_id}\n")

print("Testando escrita (subindo um arquivo de teste)...")
drive.subir_arquivo(pasta_id, "teste_conexao.txt", b"Se voce esta vendo isso, a conexao funcionou!", "text/plain")
print("✅ Consegui escrever na pasta! Confere no Drive se apareceu um arquivo 'teste_conexao.txt' — "
      "pode apagar ele depois, era só teste.")

print("\nTudo funcionando! 🎉")
