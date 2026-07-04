"""
assessment_api.py
=================
API HTTP para receber dados do Google Forms (via Apps Script) e disparar
o fluxo: preencher PDF → enviar ao Clicksign.

Deploy gratuito sugerido: Render.com (render.yaml incluído)

Endpoints:
    POST /processar   — corpo JSON com dados do cliente
    GET  /saude       — healthcheck
"""

import os
import json
import tempfile
from pathlib import Path
from flask import Flask, request, jsonify

# O fill_assessment.py deve estar na mesma pasta
import sys
sys.path.insert(0, str(Path(__file__).parent))
from fill_assessment import preencher_pdf, enviar_clicksign, SOCIOS_LEGADUS

app = Flask(__name__)

# Chave secreta para proteger o endpoint (configure no Render como variável de ambiente)
API_SECRET = os.environ.get("ASSESSMENT_API_SECRET", "")


def autorizado(req):
    """Verifica Bearer token no header Authorization."""
    if not API_SECRET:
        return True  # sem segredo configurado, aceita tudo (não recomendado em produção)
    auth = req.headers.get("Authorization", "")
    return auth == f"Bearer {API_SECRET}"


@app.route("/saude", methods=["GET"])
def saude():
    return jsonify({"status": "ok", "socios": list(SOCIOS_LEGADUS.keys())}), 200


@app.route("/processar", methods=["POST"])
def processar():
    if not autorizado(request):
        return jsonify({"erro": "Não autorizado"}), 401

    dados = request.get_json(force=True, silent=True)
    if not dados:
        return jsonify({"erro": "Corpo JSON inválido ou vazio"}), 400

    # Validações mínimas
    nome_cliente = dados.get("nome_contratante", "").strip()
    email_cliente = dados.get("email_contratante", "").strip()
    if not nome_cliente:
        return jsonify({"erro": "nome_contratante é obrigatório"}), 400
    if not email_cliente:
        return jsonify({"erro": "email_contratante é obrigatório"}), 400

    try:
        from datetime import date
        hoje = date.today().strftime("%Y%m%d")
        nome_safe = nome_cliente.replace(" ", "_")

        # Gera PDF em arquivo temporário
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / f"Assessment_{nome_safe}_{hoje}.pdf"
            preencher_pdf(dados, output_path)

            apenas_pdf = dados.get("_apenas_pdf", False)
            if apenas_pdf:
                # Retorna confirmação sem enviar ao Clicksign (útil para testes)
                return jsonify({
                    "status": "pdf_gerado",
                    "arquivo": output_path.name,
                    "mensagem": "PDF gerado com sucesso (modo apenas-pdf)"
                }), 200

            doc_key = enviar_clicksign(output_path, dados)

        return jsonify({
            "status": "enviado",
            "clicksign_key": doc_key,
            "cliente": nome_cliente,
            "email": email_cliente,
        }), 200

    except ValueError as e:
        return jsonify({"erro": str(e)}), 400
    except Exception as e:
        app.logger.error(f"Erro ao processar {nome_cliente}: {e}", exc_info=True)
        return jsonify({"erro": f"Erro interno: {str(e)}"}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
