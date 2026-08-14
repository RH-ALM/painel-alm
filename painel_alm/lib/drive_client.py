"""
Cliente Google Drive (via API) — ALM Contabilidade
=====================================================
Substitui a leitura de caminho local (G:\\Meu Drive\\...) por acesso via API,
pra funcionar de qualquer máquina (inclusive rodando na nuvem).

Duas formas de autenticar (use uma):

  1) Conta de serviço (recomendado se a organização permitir):
        DriveClient.via_conta_de_servico("credenciais.json")

  2) OAuth — login com sua própria conta Google (use se a política da
     organização bloquear criação de chave de conta de serviço, como
     "iam.managed.disableServiceAccountApiKeyCreation"):
        DriveClient.via_oauth("client_secret.json", "token.json")
     Na primeira vez, abre o navegador pedindo login/autorização. Da
     segunda vez em diante, usa o token salvo em "token.json" (renovado
     sozinho), sem precisar logar de novo.
"""

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials as UserCredentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import io
import os

SCOPES = ["https://www.googleapis.com/auth/drive"]


class DriveClient:
    def __init__(self, creds):
        self.service = build("drive", "v3", credentials=creds)

    @classmethod
    def via_conta_de_servico(cls, credenciais_json_path):
        creds = service_account.Credentials.from_service_account_file(
            credenciais_json_path, scopes=SCOPES
        )
        return cls(creds)

    @classmethod
    def via_oauth(cls, client_secret_json_path, token_json_path="token.json"):
        """Login com conta pessoal do Google. Na primeira vez abre o navegador
        pra autorizar; depois disso reusa (e renova sozinho) o token salvo em
        token_json_path — não precisa logar de novo toda hora.
        Use isso rodando na SUA máquina (tem navegador disponível)."""
        creds = None
        if os.path.exists(token_json_path):
            creds = UserCredentials.from_authorized_user_file(token_json_path, SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(client_secret_json_path, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(token_json_path, "w") as f:
                f.write(creds.to_json())
        return cls(creds)

    @classmethod
    def via_token_dict(cls, token_info):
        """Login a partir de um token JÁ GERADO (dict com as chaves de
        token.json), sem abrir navegador — pra rodar num servidor sem tela
        (ex: Streamlit Community Cloud). Gere o token.json uma vez na sua
        máquina com via_oauth(), e cole o conteúdo dele nos 'Secrets' do
        Streamlit Cloud. Renova sozinho quando expira, contanto que o
        refresh_token esteja presente."""
        creds = UserCredentials.from_authorized_user_info(token_info, SCOPES)
        if not creds.valid and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        return cls(creds)

    def _achar_filho(self, nome, pasta_pai_id=None, apenas_pastas=False):
        """Acha um arquivo/pasta pelo nome exato dentro de uma pasta (ou na raiz
        compartilhada, se pasta_pai_id for None)."""
        query = f"name = '{nome.replace(chr(39), chr(92)+chr(39))}' and trashed = false"
        if pasta_pai_id:
            query += f" and '{pasta_pai_id}' in parents"
        if apenas_pastas:
            query += " and mimeType = 'application/vnd.google-apps.folder'"
        resultado = self.service.files().list(
            q=query, fields="files(id, name)", pageSize=5,
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        arquivos = resultado.get("files", [])
        return arquivos[0]["id"] if arquivos else None

    def achar_pasta_por_caminho(self, caminho):
        """Navega pasta por pasta (separado por '/') a partir da raiz
        compartilhada com a conta de serviço. Retorna o ID da última pasta,
        ou None se algum nível não existir (ex: competência ainda não criada)."""
        partes = [p for p in caminho.replace("\\", "/").split("/") if p]
        pasta_id = None
        for parte in partes:
            pasta_id = self._achar_filho(parte, pasta_id, apenas_pastas=True)
            if pasta_id is None:
                return None
        return pasta_id

    def listar_pdfs(self, pasta_id):
        """Lista todos os PDFs dentro de uma pasta (não recursivo)."""
        if pasta_id is None:
            return []
        query = f"'{pasta_id}' in parents and mimeType = 'application/pdf' and trashed = false"
        resultado = self.service.files().list(
            q=query, fields="files(id, name)", pageSize=200,
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        return resultado.get("files", [])

    def achar_arquivo(self, pasta_id, nome):
        """Acha um arquivo (qualquer tipo) pelo nome exato dentro de uma pasta.
        Retorna o ID, ou None se não existir."""
        return self._achar_filho(nome, pasta_id)

    def baixar_arquivo(self, arquivo_id):
        """Baixa o conteúdo de um arquivo (qualquer tipo) como bytes."""
        request = self.service.files().get_media(fileId=arquivo_id, supportsAllDrives=True)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        concluido = False
        while not concluido:
            _, concluido = downloader.next_chunk()
        buffer.seek(0)
        return buffer.read()

    def subir_arquivo(self, pasta_id, nome, conteudo_bytes, mime_type="application/octet-stream"):
        """Sobe um arquivo (cria novo, ou sobrescreve se já existir um com o mesmo nome nessa pasta)."""
        existente_id = self._achar_filho(nome, pasta_id)
        media = MediaIoBaseUpload(io.BytesIO(conteudo_bytes), mimetype=mime_type, resumable=True)
        if existente_id:
            self.service.files().update(fileId=existente_id, media_body=media,
                                         supportsAllDrives=True).execute()
            return existente_id
        else:
            metadata = {"name": nome, "parents": [pasta_id]}
            arquivo = self.service.files().create(body=metadata, media_body=media,
                                                   fields="id", supportsAllDrives=True).execute()
            return arquivo["id"]
