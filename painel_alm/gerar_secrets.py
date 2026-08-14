"""
Roda uma vez, depois que o token.json já foi gerado (via test_drive.py).
Imprime o texto exato pra colar em Streamlit Cloud > Settings > Secrets.

Como rodar:
    python gerar_secrets.py
"""
import json

with open("token.json", "r", encoding="utf-8") as f:
    token = json.load(f)

print("Copia TUDO abaixo (do [gcp_token] até o final) e cola nos Secrets do Streamlit Cloud:\n")
print("[gcp_token]")
for chave, valor in token.items():
    if isinstance(valor, list):
        lista = ", ".join(f'"{v}"' for v in valor)
        print(f'{chave} = [{lista}]')
    elif isinstance(valor, bool):
        print(f'{chave} = {str(valor).lower()}')
    elif valor is None:
        continue
    else:
        print(f'{chave} = "{valor}"')
