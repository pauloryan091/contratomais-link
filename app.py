from flask import Flask, request, jsonify, session, send_from_directory
from flask_cors import CORS
from datetime import datetime, timedelta
import os
import smtplib
import sqlite3
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps
import logging
import hashlib

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
DATA_DIR = os.path.join(BASE_DIR, "data")

os.makedirs(PUBLIC_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder=None)

# Ajuste origins em produção (domínio real). Em localhost fica ok assim.
CORS(
    app,
    supports_credentials=True,
    origins=[
        "http://localhost:5000",
        "http://127.0.0.1:5000",
    ],
)

app.config["SECRET_KEY"] = "contrato-mais-secret-key-2024-super-seguro"
app.config["SESSION_COOKIE_NAME"] = "contrato_mais_session"
app.config["SESSION_COOKIE_SECURE"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=5)
app.config["SESSION_REFRESH_EACH_REQUEST"] = False

EMAIL_CONFIG = {
    "smtp_server": "smtp.gmail.com",
    "smtp_port": 587,
    "sender_email": "contratomais.suporte1@gmail.com",
    "sender_password": "hsri smmy tyea sgac",
    "use_tls": True,
}

DATABASE = os.path.join(DATA_DIR, "contratos.db")

RESET_CODE = "19192425"


def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def hash_senha(senha: str) -> str:
    return hashlib.sha256(senha.encode()).hexdigest()


def verificar_senha(senha: str, senha_hash: str) -> bool:
    return hash_senha(senha) == senha_hash


def criar_tabelas():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS usuario (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_completo TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            senha_hash TEXT NOT NULL,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS contrato (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            descricao TEXT,
            data_inicio TIMESTAMP NOT NULL,
            data_fim TIMESTAMP NOT NULL,
            status TEXT DEFAULT 'ativo',
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            usuario_id INTEGER NOT NULL,
            FOREIGN KEY (usuario_id) REFERENCES usuario (id)
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS notificacao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contrato_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            assunto TEXT NOT NULL,
            mensagem TEXT,
            email_destino TEXT NOT NULL,
            status TEXT DEFAULT 'pendente',
            data_envio TIMESTAMP,
            criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (contrato_id) REFERENCES contrato (id)
        )
        """
    )

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_contrato_usuario ON contrato(usuario_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_notificacao_contrato ON notificacao(contrato_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_contrato_data_fim ON contrato(data_fim)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_usuario_email ON usuario(email)")

    # Garante admin
    cursor.execute("SELECT COUNT(*) as total FROM usuario WHERE email = ?", ("admin@contratomais.com",))
    total = cursor.fetchone()[0]
    if total == 0:
        senha_hash = hash_senha("admin123")
        cursor.execute(
            "INSERT INTO usuario (nome_completo, email, senha_hash) VALUES (?, ?, ?)",
            ("Administrador", "admin@contratomais.com", senha_hash),
        )

    conn.commit()
    conn.close()


def resetar_banco_completo():
    # Reset literal: apaga o arquivo do SQLite e recria tudo do zero
    try:
        if os.path.exists(DATABASE):
            os.remove(DATABASE)
    except Exception as e:
        logger.error(f"Falha ao remover banco: {str(e)}")
        raise

    criar_tabelas()


def calcular_dias_restantes(data_fim):
    try:
        if isinstance(data_fim, str):
            try:
                data_fim_obj = datetime.fromisoformat(data_fim.replace("Z", "+00:00"))
            except Exception:
                data_fim_obj = datetime.strptime(data_fim, "%Y-%m-%d %H:%M:%S")
        else:
            data_fim_obj = data_fim

        hoje = datetime.utcnow()
        diferenca = data_fim_obj - hoje
        return diferenca.days
    except Exception:
        return None


def formatar_data_brasil(data):
    if isinstance(data, str):
        try:
            data = datetime.fromisoformat(data.replace("Z", "+00:00"))
        except Exception:
            data = datetime.strptime(data, "%Y-%m-%d %H:%M:%S")
    return data.strftime("%d/%m/%Y %H:%M")


def criar_template_email(assunto, titulo, mensagem, tipo_notificacao=None, contrato=None):
    if contrato:
        data_inicio = formatar_data_brasil(contrato["data_inicio"])
        data_fim = formatar_data_brasil(contrato["data_fim"])

        hoje = datetime.utcnow()
        try:
            data_fim_obj = datetime.fromisoformat(str(contrato["data_fim"]).replace("Z", "+00:00"))
        except Exception:
            data_fim_obj = datetime.strptime(str(contrato["data_fim"]), "%Y-%m-%d %H:%M:%S")

        dias_restantes = (data_fim_obj - hoje).days

        if tipo_notificacao == "urgente":
            cor_primaria = "#dc2626"
        elif tipo_notificacao == "aviso":
            cor_primaria = "#f59e0b"
        else:
            cor_primaria = "#10b981"

        detalhes_contrato = f"""
        <div style="background:#f8fafc;border-radius:8px;padding:20px;margin:20px 0;border-left:4px solid {cor_primaria};">
            <h3 style="margin-top:0;color:#1e293b;">Detalhes do Contrato</h3>
            <table style="width:100%;border-collapse:collapse;">
                <tr>
                    <td style="padding:8px 0;border-bottom:1px solid #e2e8f0;"><strong>Nome:</strong></td>
                    <td style="padding:8px 0;border-bottom:1px solid #e2e8f0;">{contrato["nome"]}</td>
                </tr>
                <tr>
                    <td style="padding:8px 0;border-bottom:1px solid #e2e8f0;"><strong>Descrição:</strong></td>
                    <td style="padding:8px 0;border-bottom:1px solid #e2e8f0;">{contrato["descricao"] or "Não informada"}</td>
                </tr>
                <tr>
                    <td style="padding:8px 0;border-bottom:1px solid #e2e8f0;"><strong>Data Início:</strong></td>
                    <td style="padding:8px 0;border-bottom:1px solid #e2e8f0;">{data_inicio}</td>
                </tr>
                <tr>
                    <td style="padding:8px 0;border-bottom:1px solid #e2e8f0;"><strong>Data Término:</strong></td>
                    <td style="padding:8px 0;border-bottom:1px solid #e2e8f0;">{data_fim}</td>
                </tr>
                <tr>
                    <td style="padding:8px 0;"><strong>Dias Restantes:</strong></td>
                    <td style="padding:8px 0;">
                        <span style="background: {'#fee2e2' if dias_restantes < 7 else '#fef3c7' if dias_restantes < 30 else '#d1fae5'};
                              color: {'#991b1b' if dias_restantes < 7 else '#92400e' if dias_restantes < 30 else '#065f46'};
                              padding:4px 12px;border-radius:20px;font-weight:bold;">
                            {dias_restantes} dias
                        </span>
                    </td>
                </tr>
            </table>
        </div>
        """
    else:
        detalhes_contrato = ""
        cor_primaria = "#2563eb"

    html = f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{assunto}</title>
    </head>
    <body style="font-family:Arial,sans-serif;padding:20px;background:#f1f5f9;">
        <div style="max-width:700px;margin:0 auto;background:white;border-radius:12px;overflow:hidden;box-shadow:0 10px 25px rgba(0,0,0,.08)">
            <div style="background:{cor_primaria};color:white;padding:18px 22px;">
                <div style="font-size:22px;font-weight:800;">CONTRATO<span style="color:#fbbf24;">+</span></div>
                <div style="opacity:.9">Sistema de Gerenciamento</div>
            </div>
            <div style="padding:22px;">
                <h2 style="margin:0 0 8px 0;">{titulo}</h2>
                <div style="display:inline-block;background:{cor_primaria}22;color:{cor_primaria};padding:8px 14px;border-radius:999px;font-weight:700;margin-bottom:14px;">
                    {(tipo_notificacao or "notificacao").upper()}
                </div>
                <div style="color:#0f172a;line-height:1.6;">{mensagem}</div>
                {detalhes_contrato}
                <div style="text-align:center;margin-top:18px;">
                    <a href="http://localhost:5000/dashboard.html" style="background:{cor_primaria};color:white;padding:12px 22px;border-radius:999px;text-decoration:none;display:inline-block;font-weight:800;">
                        Acessar Dashboard
                    </a>
                </div>
            </div>
            <div style="padding:16px 22px;border-top:1px solid #e2e8f0;color:#64748b;font-size:12px;text-align:center;">
                © 2026 CONTRATO+ · Mensagem automática.
            </div>
        </div>
    </body>
    </html>
    """
    return html


def enviar_email(destinatarios, assunto, corpo_html, corpo_texto=None):
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = assunto
        msg["From"] = f'CONTRATO+ <{EMAIL_CONFIG["sender_email"]}>'

        if isinstance(destinatarios, list):
            msg["To"] = ", ".join(destinatarios)
            to_list = destinatarios
        else:
            msg["To"] = destinatarios
            to_list = [destinatarios]

        if corpo_texto:
            msg.attach(MIMEText(corpo_texto, "plain"))
        msg.attach(MIMEText(corpo_html, "html"))

        server = smtplib.SMTP(EMAIL_CONFIG["smtp_server"], EMAIL_CONFIG["smtp_port"])
        server.ehlo()
        if EMAIL_CONFIG["use_tls"]:
            server.starttls()

        server.login(EMAIL_CONFIG["sender_email"], EMAIL_CONFIG["sender_password"])
        server.send_message(msg)
        server.quit()

        logger.info(f"Email enviado para {to_list}")
        return True
    except Exception as e:
        logger.error(f"Erro ao enviar email: {str(e)}")
        return False


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "usuario_id" not in session:
            return jsonify({"authenticated": False, "message": "Não autenticado"}), 401
        return f(*args, **kwargs)

    return decorated_function


# ========== ROTAS HTML ==========
@app.route("/")
def index():
    return send_from_directory(PUBLIC_DIR, "index.html")


@app.route("/dashboard.html")
def dashboard():
    return send_from_directory(PUBLIC_DIR, "dashboard.html")


@app.route("/contratos.html")
def contratos():
    return send_from_directory(PUBLIC_DIR, "contratos.html")


@app.route("/notificacoes.html")
def notificacoes():
    return send_from_directory(PUBLIC_DIR, "notificacoes.html")


@app.route("/configuracoes.html")
def configuracoes():
    return send_from_directory(PUBLIC_DIR, "configuracoes.html")


@app.route("/<path:filename>")
def serve_file(filename):
    file_path = os.path.join(PUBLIC_DIR, filename)
    if not os.path.exists(file_path):
        return "Arquivo não encontrado", 404
    return send_from_directory(PUBLIC_DIR, filename)


# ========== API - AUTH ==========
@app.route("/api/auth/admin-login", methods=["POST"])
def admin_login():
    try:
        data = request.json or {}
        senha = (data.get("senha") or "").strip()
        if not senha:
            return jsonify({"success": False, "message": "Senha obrigatória"}), 400

        conn = get_db_connection()
        admin = conn.execute(
            "SELECT id, nome_completo, email, senha_hash FROM usuario WHERE email = ?",
            ("admin@contratomais.com",),
        ).fetchone()
        conn.close()

        if not admin:
            return jsonify({"success": False, "message": "Usuário admin não encontrado"}), 500

        if not verificar_senha(senha, admin["senha_hash"]):
            return jsonify({"success": False, "message": "Senha inválida"}), 401

        session.permanent = True
        session["usuario_id"] = admin["id"]
        session["usuario_nome"] = admin["nome_completo"]
        session["usuario_email"] = admin["email"]

        return jsonify(
            {
                "success": True,
                "message": "Login realizado",
                "user": {
                    "id": admin["id"],
                    "nome_completo": admin["nome_completo"],
                    "email": admin["email"],
                },
            }
        )
    except Exception as e:
        logger.exception("Erro no admin-login")
        return jsonify({"success": False, "message": f"Erro no login: {str(e)}"}), 500


@app.route("/api/auth/logout", methods=["POST", "GET"])
def logout():
    session.clear()
    resp = jsonify({"success": True, "message": "Logout realizado com sucesso"})
    # garante remoção do cookie de sessão (melhora consistência em mobile)
    resp.delete_cookie(app.config["SESSION_COOKIE_NAME"])
    return resp


@app.route("/api/auth/check", methods=["GET"])
def check_auth():
    if "usuario_id" in session:
        return jsonify(
            {
                "authenticated": True,
                "user": {
                    "id": session["usuario_id"],
                    "nome_completo": session.get("usuario_nome"),
                    "email": session.get("usuario_email"),
                },
            }
        )
    return jsonify({"authenticated": False})


# ========== API - USUÁRIO ==========
@app.route("/api/usuario", methods=["GET"])
@login_required
def get_usuario():
    try:
        conn = get_db_connection()
        usuario = conn.execute(
            "SELECT id, nome_completo, email, criado_em FROM usuario WHERE id = ?",
            (session["usuario_id"],),
        ).fetchone()
        conn.close()

        if not usuario:
            return jsonify({"success": False, "message": "Usuário não encontrado"}), 404

        return jsonify(
            {
                "success": True,
                "usuario": {
                    "id": usuario["id"],
                    "nome_completo": usuario["nome_completo"],
                    "email": usuario["email"],
                    "criado_em": usuario["criado_em"],
                },
            }
        )
    except Exception as e:
        logger.error(f"Erro ao obter usuário: {str(e)}")
        return jsonify({"success": False, "message": "Erro ao obter usuário"}), 500


# ========== API - RESET DO SISTEMA (TOTAL) ==========
@app.route("/api/system/reset", methods=["POST"])
@login_required
def system_reset():
    """
    Reset total do sistema:
    - exige code = 19192425
    - apaga o banco inteiro (arquivo sqlite) e recria tabelas (inclui admin)
    - encerra a sessão atual
    """
    try:
        data = request.json or {}
        code = (data.get("code") or "").strip()

        if code != RESET_CODE:
            return jsonify({"success": False, "message": "Código inválido"}), 403

        # encerra sessão antes
        session.clear()

        # reset literal do banco
        resetar_banco_completo()

        return jsonify({"success": True, "message": "Sistema resetado com sucesso"})
    except Exception as e:
        logger.error(f"Erro ao resetar sistema: {str(e)}")
        return jsonify({"success": False, "message": "Erro ao resetar sistema"}), 500


# ========== API - CONTRATOS ==========
@app.route("/api/contratos", methods=["GET"])
@login_required
def listar_contratos():
    try:
        usuario_id = session["usuario_id"]
        conn = get_db_connection()

        contratos = conn.execute(
            """
            SELECT * FROM contrato
            WHERE usuario_id = ?
            ORDER BY atualizado_em DESC, id DESC
            """,
            (usuario_id,),
        ).fetchall()

        conn.close()

        contratos_json = []
        for contrato in contratos:
            contratos_json.append(
                {
                    "id": contrato["id"],
                    "nome": contrato["nome"],
                    "descricao": contrato["descricao"],
                    "data_inicio": contrato["data_inicio"],
                    "data_fim": contrato["data_fim"],
                    "status": contrato["status"],
                    "criado_em": contrato["criado_em"],
                    "atualizado_em": contrato["atualizado_em"],
                    "dias_restantes": calcular_dias_restantes(contrato["data_fim"]),
                }
            )

        return jsonify({"success": True, "contratos": contratos_json})
    except Exception as e:
        logger.error(f"Erro ao listar contratos: {str(e)}")
        return jsonify({"success": False, "message": "Erro ao listar contratos"}), 500


@app.route("/api/contratos/<int:id>", methods=["GET"])
@login_required
def obter_contrato(id):
    try:
        usuario_id = session["usuario_id"]
        conn = get_db_connection()

        contrato = conn.execute(
            "SELECT * FROM contrato WHERE id = ? AND usuario_id = ?",
            (id, usuario_id),
        ).fetchone()
        conn.close()

        if not contrato:
            return jsonify({"success": False, "message": "Contrato não encontrado"}), 404

        return jsonify(
            {
                "success": True,
                "contrato": {
                    "id": contrato["id"],
                    "nome": contrato["nome"],
                    "descricao": contrato["descricao"],
                    "data_inicio": contrato["data_inicio"],
                    "data_fim": contrato["data_fim"],
                    "status": contrato["status"],
                    "criado_em": contrato["criado_em"],
                    "atualizado_em": contrato["atualizado_em"],
                    "dias_restantes": calcular_dias_restantes(contrato["data_fim"]),
                },
            }
        )
    except Exception as e:
        logger.error(f"Erro ao obter contrato: {str(e)}")
        return jsonify({"success": False, "message": "Erro ao obter contrato"}), 500


@app.route("/api/contratos", methods=["POST"])
@login_required
def criar_contrato():
    try:
        usuario_id = session["usuario_id"]
        data = request.json or {}

        for field in ["nome", "data_inicio", "data_fim"]:
            if not data.get(field):
                return jsonify({"success": False, "message": f"Campo {field} é obrigatório"}), 400

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO contrato (nome, descricao, data_inicio, data_fim, status, usuario_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                data["nome"],
                data.get("descricao", ""),
                data["data_inicio"],
                data["data_fim"],
                data.get("status", "ativo"),
                usuario_id,
            ),
        )

        contrato_id = cursor.lastrowid
        conn.commit()

        contrato = conn.execute("SELECT * FROM contrato WHERE id = ?", (contrato_id,)).fetchone()
        conn.close()

        return jsonify(
            {
                "success": True,
                "message": "Contrato criado com sucesso",
                "contrato": {
                    "id": contrato["id"],
                    "nome": contrato["nome"],
                    "descricao": contrato["descricao"],
                    "data_inicio": contrato["data_inicio"],
                    "data_fim": contrato["data_fim"],
                    "status": contrato["status"],
                    "dias_restantes": calcular_dias_restantes(contrato["data_fim"]),
                },
            }
        )
    except Exception as e:
        logger.error(f"Erro ao criar contrato: {str(e)}")
        return jsonify({"success": False, "message": "Erro ao criar contrato"}), 500


@app.route("/api/contratos/<int:id>", methods=["PUT"])
@login_required
def atualizar_contrato(id):
    try:
        usuario_id = session["usuario_id"]
        data = request.json or {}

        conn = get_db_connection()
        contrato = conn.execute(
            "SELECT * FROM contrato WHERE id = ? AND usuario_id = ?",
            (id, usuario_id),
        ).fetchone()

        if not contrato:
            conn.close()
            return jsonify({"success": False, "message": "Contrato não encontrado"}), 404

        updates = []
        params = []
        for campo in ["nome", "descricao", "data_inicio", "data_fim", "status"]:
            if campo in data:
                updates.append(f"{campo} = ?")
                params.append(data[campo])

        updates.append("atualizado_em = CURRENT_TIMESTAMP")

        query = f'UPDATE contrato SET {", ".join(updates)} WHERE id = ? AND usuario_id = ?'
        params.extend([id, usuario_id])

        conn.execute(query, params)
        conn.commit()

        contrato = conn.execute("SELECT * FROM contrato WHERE id = ?", (id,)).fetchone()
        conn.close()

        return jsonify(
            {
                "success": True,
                "message": "Contrato atualizado com sucesso",
                "contrato": {
                    "id": contrato["id"],
                    "nome": contrato["nome"],
                    "descricao": contrato["descricao"],
                    "data_inicio": contrato["data_inicio"],
                    "data_fim": contrato["data_fim"],
                    "status": contrato["status"],
                    "dias_restantes": calcular_dias_restantes(contrato["data_fim"]),
                },
            }
        )
    except Exception as e:
        logger.error(f"Erro ao atualizar contrato: {str(e)}")
        return jsonify({"success": False, "message": "Erro ao atualizar contrato"}), 500


@app.route("/api/contratos/<int:id>", methods=["DELETE"])
@login_required
def excluir_contrato(id):
    try:
        usuario_id = session["usuario_id"]
        conn = get_db_connection()

        contrato = conn.execute(
            "SELECT * FROM contrato WHERE id = ? AND usuario_id = ?",
            (id, usuario_id),
        ).fetchone()

        if not contrato:
            conn.close()
            return jsonify({"success": False, "message": "Contrato não encontrado"}), 404

        conn.execute("DELETE FROM notificacao WHERE contrato_id = ?", (id,))
        conn.execute("DELETE FROM contrato WHERE id = ? AND usuario_id = ?", (id, usuario_id))
        conn.commit()
        conn.close()

        return jsonify({"success": True, "message": "Contrato excluído com sucesso"})
    except Exception as e:
        logger.error(f"Erro ao excluir contrato: {str(e)}")
        return jsonify({"success": False, "message": "Erro ao excluir contrato"}), 500


# ========== API - NOTIFICAÇÕES ==========
@app.route("/api/notificacoes", methods=["GET"])
@login_required
def listar_notificacoes():
    try:
        usuario_id = session["usuario_id"]
        conn = get_db_connection()

        notificacoes = conn.execute(
            """
            SELECT n.*, c.nome as contrato_nome
            FROM notificacao n
            JOIN contrato c ON n.contrato_id = c.id
            WHERE c.usuario_id = ?
            ORDER BY n.criado_em DESC
            """,
            (usuario_id,),
        ).fetchall()

        conn.close()

        notificacoes_json = []
        for notif in notificacoes:
            notificacoes_json.append(
                {
                    "id": notif["id"],
                    "contrato_id": notif["contrato_id"],
                    "contrato_nome": notif["contrato_nome"],
                    "tipo": notif["tipo"],
                    "assunto": notif["assunto"],
                    "mensagem": notif["mensagem"],
                    "email_destino": notif["email_destino"],
                    "status": notif["status"],
                    "data_envio": notif["data_envio"],
                    "criado_em": notif["criado_em"],
                }
            )

        return jsonify({"success": True, "notificacoes": notificacoes_json})
    except Exception as e:
        logger.error(f"Erro ao listar notificações: {str(e)}")
        return jsonify({"success": False, "message": "Erro ao listar notificações"}), 500


@app.route("/api/contratos/<int:contrato_id>/notificar", methods=["POST"])
@login_required
def enviar_notificacao(contrato_id):
    try:
        usuario_id = session["usuario_id"]
        data = request.json or {}

        conn = get_db_connection()
        contrato = conn.execute(
            "SELECT * FROM contrato WHERE id = ? AND usuario_id = ?",
            (contrato_id, usuario_id),
        ).fetchone()

        if not contrato:
            conn.close()
            return jsonify({"success": False, "message": "Contrato não encontrado"}), 404

        emails = data.get("emails")
        tipo = data.get("tipo")
        assunto = data.get("assunto", "Notificação de Contrato - CONTRATO+")
        mensagem_customizada = data.get("mensagem_customizada")

        if not emails or not tipo:
            conn.close()
            return jsonify({"success": False, "message": "Emails e tipo são obrigatórios"}), 400

        if isinstance(emails, str):
            emails_list = [email.strip() for email in emails.split(",") if email.strip()]
        elif isinstance(emails, list):
            emails_list = [e.strip() for e in emails if str(e).strip()]
        else:
            conn.close()
            return jsonify({"success": False, "message": "Formato de emails inválido"}), 400

        for email in emails_list:
            if "@" not in email or "." not in email:
                conn.close()
                return jsonify({"success": False, "message": f"Email inválido: {email}"}), 400

        if tipo == "lembrete_diario":
            tipo_design = "urgente"
            titulo = "Contrato vence amanhã"
            mensagem = mensagem_customizada or f"O contrato <strong>{contrato['nome']}</strong> está prestes a vencer."
        elif tipo == "lembrete_semanal":
            tipo_design = "aviso"
            titulo = "Contrato próximo do vencimento"
            mensagem = mensagem_customizada or f"O contrato <strong>{contrato['nome']}</strong> vencerá em 7 dias."
        elif tipo == "lembrete_mensal":
            tipo_design = "info"
            titulo = "Lembrete de contrato"
            mensagem = mensagem_customizada or f"O contrato <strong>{contrato['nome']}</strong> vencerá em 30 dias."
        else:
            tipo_design = "info"
            titulo = assunto
            mensagem = mensagem_customizada or f"Notificação referente ao contrato <strong>{contrato['nome']}</strong>."

        html_content = criar_template_email(
            assunto=assunto,
            titulo=titulo,
            mensagem=mensagem,
            tipo_notificacao=tipo_design,
            contrato=contrato,
        )

        data_fim_formatada = formatar_data_brasil(contrato["data_fim"])
        texto_simples = f"""CONTRATO+ - {assunto}

{titulo}

{mensagem}

Contrato: {contrato['nome']}
Data de Término: {data_fim_formatada}
Status: {contrato['status']}

Acesse: http://localhost:5000/dashboard.html
"""

        enviado = enviar_email(emails_list, assunto, html_content, texto_simples)

        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO notificacao (contrato_id, tipo, assunto, mensagem, email_destino, status, data_envio)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                contrato_id,
                tipo,
                assunto,
                mensagem,
                ",".join(emails_list),
                "enviado" if enviado else "erro",
                datetime.utcnow().isoformat() if enviado else None,
            ),
        )
        conn.commit()
        conn.close()

        if enviado:
            return jsonify(
                {
                    "success": True,
                    "message": f"Notificação enviada para {len(emails_list)} email(s)",
                    "enviados": len(emails_list),
                }
            )

        return jsonify({"success": False, "message": "Erro ao enviar notificação"}), 500

    except Exception as e:
        logger.error(f"Erro ao enviar notificação: {str(e)}")
        return jsonify({"success": False, "message": f"Erro ao enviar notificação: {str(e)}"}), 500


# ========== API - DASHBOARD ==========
@app.route("/api/dashboard/stats", methods=["GET"])
@login_required
def get_dashboard_stats():
    try:
        usuario_id = session["usuario_id"]
        conn = get_db_connection()

        total_contratos = conn.execute(
            "SELECT COUNT(*) as total FROM contrato WHERE usuario_id = ?",
            (usuario_id,),
        ).fetchone()["total"]

        contratos_ativos = conn.execute(
            'SELECT COUNT(*) as total FROM contrato WHERE usuario_id = ? AND status = "ativo"',
            (usuario_id,),
        ).fetchone()["total"]

        hoje_dt = datetime.now()
        hoje = hoje_dt.strftime("%Y-%m-%d %H:%M:%S")

        data_limite_7 = (hoje_dt + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        contratos_proximos_7 = conn.execute(
            """
            SELECT COUNT(*) as total
            FROM contrato
            WHERE usuario_id = ?
            AND status = "ativo"
            AND data_fim BETWEEN ? AND ?
            """,
            (usuario_id, hoje, data_limite_7),
        ).fetchone()["total"]

        contratos_vencidos = conn.execute(
            """
            SELECT COUNT(*) as total
            FROM contrato
            WHERE usuario_id = ?
            AND data_fim < ?
            AND status = "ativo"
            """,
            (usuario_id, hoje),
        ).fetchone()["total"]

        contratos_recentes = conn.execute(
            """
            SELECT id, nome, data_inicio, data_fim, status, atualizado_em
            FROM contrato
            WHERE usuario_id = ?
            ORDER BY atualizado_em DESC, id DESC
            LIMIT 6
            """,
            (usuario_id,),
        ).fetchall()

        conn.close()

        recentes_json = []
        for c in contratos_recentes:
            recentes_json.append(
                {
                    "id": c["id"],
                    "nome": c["nome"],
                    "data_inicio": c["data_inicio"],
                    "data_fim": c["data_fim"],
                    "status": c["status"],
                    "dias_restantes": calcular_dias_restantes(c["data_fim"]),
                    "atualizado_em": c["atualizado_em"],
                }
            )

        return jsonify(
            {
                "success": True,
                "stats": {
                    "total_contratos": total_contratos,
                    "contratos_ativos": contratos_ativos,
                    "contratos_vencendo_7dias": contratos_proximos_7,
                    "contratos_vencidos": contratos_vencidos,
                    "contratos_recentes": recentes_json,
                    "atualizado_em": datetime.now().isoformat(),
                },
            }
        )
    except Exception as e:
        logger.error(f"Erro ao obter estatísticas: {str(e)}")
        return jsonify({"success": False, "message": "Erro ao obter estatísticas"}), 500


# ========== API - TESTE ==========
@app.route("/api/teste/conexao", methods=["GET"])
def teste_conexao():
    return jsonify(
        {
            "success": True,
            "message": "Conexão estabelecida",
            "servidor": "CONTRATO+",
            "versao": "1.0",
            "timestamp": datetime.now().isoformat(),
        }
    )


if __name__ == "__main__":
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        criar_tabelas()
    except Exception as e:
        logger.exception("Falha ao inicializar banco: %s", e)

    print("Servidor iniciado em: http://localhost:5000")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True, threaded=True)
