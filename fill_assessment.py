"""
fill_assessment.py
==================
Recebe dados coletados via Google Forms, preenche o PDF template do
Assessment Legadus e envia o envelope via Clicksign:
  - Signatário: cliente (assina)
  - Cópia:      sócio responsável (recebe documento finalizahdo)

Uso:
    python fill_assessment.py --dados dados_cliente.json
    python fill_assessment.py --apenas-pdf --dados dados_cliente.json
    python fill_assessment.py --socios

Dependências:
    pip install pymupdf requests
"""

import argparse
import json
import os
import sys
import requests
import fitz  # PyMuPDF
from datetime import date, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# CONFIGURAÇÕES
# ---------------------------------------------------------------------------

TEMPLATE_PDF = Path(__file__).parent / "Assessment_Template_Legadus.pdf"

CLICKSIGN_TOKEN = os.environ.get("CLICKSIGN_TOKEN", "SEU_TOKEN_AQUI")   # substitua pelo token da conta Legadus
CLICKSIGN_BASE  = "https://app.clicksign.com/api/v1"

PRAZO_DIAS = 30  # dias corridos para assinatura

# ---------------------------------------------------------------------------
# MAPEAMENTO: nome do sócio → e-mail
# ---------------------------------------------------------------------------

SOCIOS_LEGADUS = {
    "Fernando Almeida": "fernando.almeida@legadusconsultoria.com.br",
    "Wander Meyer":     "wander.meyer@legadusconsultoria.com.br",
    "Cezar Katayama":   "cezar.katayama@legadusconsultoria.com.br",
    "Danilo Sarro":     "danilo.sarro@legadusconsultoria.com.br",
    "Paulo Silvério":   "paulo.silverio@legadusconsultoria.com.br",
}

NOMES_SOCIOS = sorted(SOCIOS_LEGADUS.keys())

# ---------------------------------------------------------------------------
# MAPEAMENTO COMPLETO: campo do PDF → chave nos dados do Forms
# Baseado nos 135 campos reais do Assessment_Template_Legadus.pdf
# ---------------------------------------------------------------------------

CAMPO_PDF_PARA_FORM = {
    # --- Página 1 ---
    "Socio_Legadus":     "socio_legadus",

    # --- Página 2: Identificação ---
    "Tel_Rogerio":       "tel_contratante",    # telefone do contratante (campo nomeado com cliente anterior)
    "Cidade_Estado":     "cidade_estado",
    "Tel_Noelita":       "tel_conjuge",         # telefone do cônjuge

    # Regime de bens - texto livre
    "RB_Outro_Txt":      "rb_outro_txt",

    # --- Página 2: Beneficiários ---
    "B1_Nome":           "b1_nome",
    "B1_Vinculo":        "b1_vinculo",
    "B1_CPF":            "b1_cpf",
    "B1_Pais":           "b1_pais",
    "B1_Perc":           "b1_perc",

    "B2_Nome":           "b2_nome",
    "B2_Vinculo":        "b2_vinculo",
    "B2_CPF":            "b2_cpf",
    "B2_Pais":           "b2_pais",
    "B2_Perc":           "b2_perc",

    "B3_Nome":           "b3_nome",
    "B3_Vinculo":        "b3_vinculo",
    "B3_CPF":            "b3_cpf",
    "B3_Pais":           "b3_pais",
    "B3_Perc":           "b3_perc",

    "B4_Nome":           "b4_nome",
    "B4_Vinculo":        "b4_vinculo",
    "B4_CPF":            "b4_cpf",
    "B4_Pais":           "b4_pais",
    "B4_Perc":           "b4_perc",

    # --- Mapa Patrimonial (Páginas 2-3) ---
    # IU = Imóvel Urbano
    "MP_IU_Tit":         "mp_iu_tit",
    "MP_IU_Val":         "mp_iu_val",
    "MP_IU_Obs":         "mp_iu_obs",
    # IR = Imóvel Rural
    "MP_IR_Tit":         "mp_ir_tit",
    "MP_IR_Val":         "mp_ir_val",
    "MP_IR_Obs":         "mp_ir_obs",
    # Ve = Veículos
    "MP_Ve_Tit":         "mp_ve_tit",
    "MP_Ve_Val":         "mp_ve_val",
    "MP_Ve_Obs":         "mp_ve_obs",
    # Ap = Aplicações / Investimentos
    "MP_Ap_Tit":         "mp_ap_tit",
    "MP_Ap_Val":         "mp_ap_val",
    "MP_Ap_Obs":         "mp_ap_obs",
    # Pr = Previdência
    "MP_Pr_Tit":         "mp_pr_tit",
    "MP_Pr_Val":         "mp_pr_val",
    "MP_Pr_Obs":         "mp_pr_obs",
    # Qu = Quotas / Participações Societárias
    "MP_Qu_Tit":         "mp_qu_tit",
    "MP_Qu_Val":         "mp_qu_val",
    "MP_Qu_Obs":         "mp_qu_obs",
    # Re = Recebíveis
    "MP_Re_Tit":         "mp_re_tit",
    "MP_Re_Val":         "mp_re_val",
    "MP_Re_Obs":         "mp_re_obs",
    # Cr = Créditos
    "MP_Cr_Tit":         "mp_cr_tit",
    "MP_Cr_Val":         "mp_cr_val",
    "MP_Cr_Obs":         "mp_cr_obs",
    # Ex = Exterior
    "MP_Ex_Tit":         "mp_ex_tit",
    "MP_Ex_Val":         "mp_ex_val",
    "MP_Ex_Obs":         "mp_ex_obs",
    # Jo = Joias / Arte / Coleções
    "MP_Jo_Tit":         "mp_jo_tit",
    "MP_Jo_Val":         "mp_jo_val",
    "MP_Jo_Obs":         "mp_jo_obs",

    # --- Seção 4: Estrutura Societária (até 3 empresas) ---
    "S4_RS_E1":          "s4_rs_e1",     # Razão Social empresa 1
    "S4_RS_E2":          "s4_rs_e2",
    "S4_RS_E3":          "s4_rs_e3",
    "S4_CN_E1":          "s4_cn_e1",     # CNPJ empresa 1
    "S4_CN_E2":          "s4_cn_e2",
    "S4_CN_E3":          "s4_cn_e3",
    "S4_RT_E1":          "s4_rt_e1",     # Regime Tributário empresa 1
    "S4_RT_E2":          "s4_rt_e2",
    "S4_RT_E3":          "s4_rt_e3",
    "S4_Fat_E1":         "s4_fat_e1",    # Faturamento empresa 1
    "S4_Fat_E2":         "s4_fat_e2",
    "S4_Fat_E3":         "s4_fat_e3",
    "S4_Pas_E1":         "s4_pas_e1",    # Passivos empresa 1
    "S4_Pas_E2":         "s4_pas_e2",
    "S4_Pas_E3":         "s4_pas_e3",

    # --- Seção 6: Holdings / Participações ---
    "S6_Acoes":          "s6_acoes",     # Descrição de ações/participações

    # --- Seção 8: Documentos necessários — observações ---
    "S8_IRPF_Obs":       "s8_irpf_obs",
    "S8_Contr_Obs":      "s8_contr_obs",
    "S8_Matr_Obs":       "s8_matr_obs",
    "S8_Extr_Obs":       "s8_extr_obs",
    "S8_CND_Obs":        "s8_cnd_obs",
    "S8_Balan_Obs":      "s8_balan_obs",
}

# ---------------------------------------------------------------------------
# CHECKBOXES: campo do PDF → chave booleana nos dados do Forms
# ---------------------------------------------------------------------------

CHECKBOXES_PDF = {
    # Estado Civil
    "EC_Solteiro":       "ec_solteiro",
    "EC_Casado":         "ec_casado",
    "EC_Uniao":          "ec_uniao_estavel",
    "EC_Divorciado":     "ec_divorciado",
    "EC_Viuvo":          "ec_viuvo",

    # Regime de Bens
    "RB_ComParcial":     "rb_com_parcial",
    "RB_ComUniv":        "rb_com_universal",
    "RB_SepConv":        "rb_sep_convencional",
    "RB_SepLegal":       "rb_sep_legal",
    "RB_PartFinal":      "rb_part_final",
    "RB_Outro_CB":       "rb_outro",

    # Documentos existentes
    "Doc_Pacto":         "doc_pacto",
    "Doc_Escritura":     "doc_escritura",
    "Doc_Testamento":    "doc_testamento",

    # Seção 5: Situação Fiscal
    "S5_IRPF_0":         "s5_irpf_em_dia",
    "S5_IRPF_1":         "s5_irpf_atrasado",
    "S5_Cont_0":         "s5_cont_propria",
    "S5_Cont_1":         "s5_cont_terceirizada",
    "S5_Pend_0":         "s5_pend_nenhuma",
    "S5_Pend_1":         "s5_pend_sim",
    "S5_Pend_2":         "s5_pend_parcial",
    "S5_CND_0":          "s5_cnd_limpa",
    "S5_CND_1":          "s5_cnd_pendencias",
    "S5_CND_2":          "s5_cnd_nao_possui",

    # Seção 6: Blindagem / Confidencialidade
    "S6_Blind_Sim":      "s6_blind_sim",
    "S6_Blind_Nao":      "s6_blind_nao",
    "S6_Conf_Sim":       "s6_conf_sim",
    "S6_Conf_Nao":       "s6_conf_nao",

    # Seção 7: Objetivos
    "S7_0":              "s7_obj_sucessao",
    "S7_1":              "s7_obj_protecao",
    "S7_2":              "s7_obj_tributario",
    "S7_3":              "s7_obj_societario",
    "S7_4":              "s7_obj_internacional",

    # Seção 8: Documentos necessários (preenchido pelo sócio)
    "S8_IRPF_Sim":       "s8_irpf_sim",
    "S8_IRPF_Nao":       "s8_irpf_nao",
    "S8_IRPF_Parc":      "s8_irpf_parc",
    "S8_Contr_Sim":      "s8_contr_sim",
    "S8_Contr_Nao":      "s8_contr_nao",
    "S8_Contr_Parc":     "s8_contr_parc",
    "S8_Matr_Sim":       "s8_matr_sim",
    "S8_Matr_Nao":       "s8_matr_nao",
    "S8_Matr_Parc":      "s8_matr_parc",
    "S8_Extr_Sim":       "s8_extr_sim",
    "S8_Extr_Nao":       "s8_extr_nao",
    "S8_Extr_Parc":      "s8_extr_parc",
    "S8_CND_Sim":        "s8_cnd_sim",
    "S8_CND_Nao":        "s8_cnd_nao",
    "S8_CND_Parc":       "s8_cnd_parc",
    "S8_Balan_Sim":      "s8_balan_sim",
    "S8_Balan_Nao":      "s8_balan_nao",
    "S8_Balan_Parc":     "s8_balan_parc",

    # Seção 9: Etapa / Proposta (preenchido pelo sócio)
    "S9_Projeto":        "s9_projeto",
    "S9_Fases":          "s9_fases",
    "S9_Cont":           "s9_continuo",
    "S9_Ate5k":          "s9_ate5k",
    "S9_5a15k":          "s9_5a15k",
    "S9_15a30k":         "s9_15a30k",
    "S9_Acima30k":       "s9_acima30k",
}


# ---------------------------------------------------------------------------
# FUNÇÕES PRINCIPAIS
# ---------------------------------------------------------------------------

def preencher_pdf(dados: dict, output_path: Path) -> Path:
    """
    Abre o template, preenche os campos com os dados do Forms e salva.
    Retorna o caminho do PDF gerado.
    """
    if not TEMPLATE_PDF.exists():
        raise FileNotFoundError(f"Template não encontrado: {TEMPLATE_PDF}")

    doc = fitz.open(str(TEMPLATE_PDF))

    for page in doc:
        for widget in page.widgets():
            nome = widget.field_name

            if nome in CAMPO_PDF_PARA_FORM:
                chave = CAMPO_PDF_PARA_FORM[nome]
                valor = dados.get(chave, "")
                widget.field_value = str(valor) if valor else ""
                widget.update()

            elif nome in CHECKBOXES_PDF:
                chave = CHECKBOXES_PDF[nome]
                marcado = dados.get(chave, False)
                widget.field_value = "Yes" if marcado else "Off"
                widget.update()

    doc.save(str(output_path), garbage=4, deflate=True)
    doc.close()
    print(f"✅ PDF preenchido: {output_path}")
    return output_path


def enviar_clicksign(pdf_path: Path, dados: dict) -> str:
    """
    Cria envelope no Clicksign:
      - Upload do PDF preenchido
      - Cliente como signatário (assina)
      - Cônjuge como signatário (assina), se informado
      - Sócio Legadus em cópia (CC)
    Retorna o key do envelope criado.
    """
    if CLICKSIGN_TOKEN == "SEU_TOKEN_AQUI":
        raise ValueError("Configure o CLICKSIGN_TOKEN antes de enviar!")

    headers = {"Content-Type": "application/json"}
    params  = {"access_token": CLICKSIGN_TOKEN}

    nome_cliente  = dados.get("nome_contratante", "Cliente")
    email_cliente = dados.get("email_contratante", "")
    socio_nome    = dados.get("socio_legadus", "")
    socio_email   = SOCIOS_LEGADUS.get(socio_nome, "")

    hoje      = date.today()
    prazo     = hoje + timedelta(days=PRAZO_DIAS)
    prazo_str = prazo.strftime("%Y-%m-%dT00:00:00-03:00")

    # 1. Upload do documento
    nome_arquivo = f"Assessment_{nome_cliente.replace(' ', '_')}_{hoje.strftime('%Y%m%d')}.pdf"
    with open(pdf_path, "rb") as f:
        content_b64 = __import__("base64").b64encode(f.read()).decode()

    payload_doc = {
        "document": {
            "path":             f"/{nome_arquivo}",
            "content_base64":   f"data:application/pdf;base64,{content_b64}",
            "deadline_at":      prazo_str,
            "auto_close":       True,
            "locale":           "pt-BR",
            "sequence_enabled": False,
        }
    }
    r = requests.post(f"{CLICKSIGN_BASE}/documents", json=payload_doc, params=params)
    r.raise_for_status()
    doc_key = r.json()["document"]["key"]
    print(f"📄 Documento enviado ao Clicksign: {doc_key}")

    def criar_signer(email, name, cpf="", tel=""):
        """Cria signatário via POST /signers e retorna seu key.
        CPF é validado algoritmicamente antes do envio.
        Se inválido (ex: CPF de teste), omite has_documentation.
        """
        import re as _re
        def _cpf_ok(c):
            d = _re.sub(r'\D', '', c or '')
            if len(d) != 11 or len(set(d)) == 1:
                return False
            for j in range(2):
                s = sum(int(d[i]) * (10 + j - i) for i in range(9 + j))
                r = (s * 10) % 11
                if r == 10: r = 0
                if r != int(d[9 + j]):
                    return False
            return True
        cpf_valido = _cpf_ok(cpf)
        tel_limpo = _re.sub(r'\D', '', tel or '')
        signer_body = {
            "email":              email,
            "auths":              ["email"],
            "name":               name,
            "has_documentation":  cpf_valido,
        }
        if cpf_valido:
            signer_body["documentation"] = _re.sub(r'\D', '', cpf)
        if tel_limpo:
            signer_body["phone_number"] = tel_limpo
        rs = requests.post(f"{CLICKSIGN_BASE}/signers",
                           json={"signer": signer_body}, params=params)
        rs.raise_for_status()
        return rs.json()["signer"]["key"]

    def adicionar_lista(doc_key, signer_key, sign_as, message=""):
        """Adiciona signatário ao documento via POST /lists."""
        body = {
            "list": {
                "document_key": doc_key,
                "signer_key":   signer_key,
                "sign_as":      sign_as,
            }
        }
        if message:
            body["list"]["message"] = message
        rl = requests.post(f"{CLICKSIGN_BASE}/lists",
                           json=body, params=params)
        rl.raise_for_status()
        return rl.json()

    # 2. Criar signatário — cliente — e adicionar ao documento (assina)
    cpf_cliente = dados.get("cpf_contratante", "").strip()
    tel_cliente = dados.get("tel_contratante", "").strip()
    sk_cliente = criar_signer(email_cliente, nome_cliente, cpf_cliente, tel_cliente)
    adicionar_lista(
        doc_key, sk_cliente, "sign",
        f"Olá, {nome_cliente.split()[0]}! "
        "Segue o Questionário de Assessment Inicial da Legadus para sua assinatura. "
        "Por favor, revise o documento e assine digitalmente."
    )
    print(f"\u2705 Signatário: {nome_cliente} <{email_cliente}>")

    # 3. Cônjuge como signatário (opcional)
    email_conjuge = dados.get("email_conjuge", "")
    nome_conjuge  = dados.get("nome_conjuge", "")
    if email_conjuge and nome_conjuge:
        cpf_conjuge = dados.get("cpf_conjuge", "").strip()
        tel_conjuge = dados.get("tel_conjuge", "").strip()
        sk_conjuge = criar_signer(email_conjuge, nome_conjuge, cpf_conjuge, tel_conjuge)
        adicionar_lista(
            doc_key, sk_conjuge, "sign",
            f"Olá, {nome_conjuge.split()[0]}! "
            "Segue o Questionário de Assessment Inicial da Legadus para sua assinatura."
        )
        print(f"\u2705 Cônjuge: {nome_conjuge} <{email_conjuge}>")

    # 4. Sócio Legadus em cópia (CC)
    if socio_email:
        sk_socio = criar_signer(socio_email, socio_nome)
        adicionar_lista(doc_key, sk_socio, "receipt")
        print(f"📋 Cópia: {socio_nome} <{socio_email}>")

        # 5. Enviar envelope
    r = requests.patch(f"{CLICKSIGN_BASE}/documents/{doc_key}/finish", params=params)
    # 422 = doc já iniciado automaticamente (auto_close=True via /lists)
    if r.status_code not in (200, 201, 204, 422):
        r.raise_for_status()
    print(f"🚀 Envelope enviado! Key: {doc_key}")
    return doc_key


def processar_resposta_forms(dados: dict) -> str:
    """Fluxo completo: dados do Forms → PDF → Clicksign."""
    nome_cliente = dados.get("nome_contratante", "cliente").replace(" ", "_")
    hoje         = date.today().strftime("%Y%m%d")
    output_path  = Path(__file__).parent / f"Assessment_{nome_cliente}_{hoje}.pdf"

    pdf_gerado = preencher_pdf(dados, output_path)
    envelope   = enviar_clicksign(pdf_gerado, dados)
    return envelope


# ---------------------------------------------------------------------------
# DADOS DE EXEMPLO (para teste sem Forms)
# ---------------------------------------------------------------------------

DADOS_EXEMPLO = {
    # Interno Legadus
    "socio_legadus":           "Fernando Almeida",

    # Contratante
    "nome_contratante":        "Rogério Carpinelli Favale",
    "cpf_contratante":         "000.000.000-00",
    "rg_contratante":          "",
    "nascimento_contratante":  "01/01/1970",
    "naturalidade_contratante":"São Paulo - SP",
    "profissao_contratante":   "Empresário",
    "email_contratante":       "rcfavale@uol.com.br",
    "tel_contratante":         "(11) 99999-0001",
    "cidade_estado":           "São Paulo - SP",

    # Cônjuge
    "nome_conjuge":            "Noelita Hwu Favale",
    "cpf_conjuge":             "000.000.000-00",
    "email_conjuge":           "noelita@uol.com.br",
    "tel_conjuge":             "(11) 99999-0002",

    # Estado civil
    "ec_casado":               True,
    "rb_com_parcial":          True,

    # Documentos
    "doc_testamento":          False,

    # Beneficiários
    "b1_nome":                 "",
    "b1_vinculo":              "",
    "b1_cpf":                  "",
    "b1_pais":                 "Brasil",
    "b1_perc":                 "",

    # Mapa Patrimonial
    "mp_iu_tit":               "",
    "mp_iu_val":               "",
    "mp_iu_obs":               "",

    # Objetivos
    "s7_obj_sucessao":         True,
    "s7_obj_protecao":         True,
    "s7_obj_tributario":       False,
    "s7_obj_societario":       False,
    "s7_obj_internacional":    False,

    # Situação fiscal
    "s5_irpf_em_dia":          True,
    "s5_cont_terceirizada":    True,
    "s5_pend_nenhuma":         True,
    "s5_cnd_limpa":            True,
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Preenche Assessment Legadus e envia via Clicksign"
    )
    parser.add_argument("--dados",      help="Arquivo JSON com dados do cliente")
    parser.add_argument("--apenas-pdf", action="store_true", help="Gera apenas o PDF, sem enviar ao Clicksign")
    parser.add_argument("--socios",     action="store_true", help="Lista os sócios disponíveis")
    args = parser.parse_args()

    if args.socios:
        print("Sócios Legadus:")
        for nome, email in SOCIOS_LEGADUS.items():
            print(f"  • {nome} — {email}")
        return

    if args.dados:
        with open(args.dados, encoding="utf-8") as f:
            dados = json.load(f)
    else:
        print("⚠️  Sem arquivo de dados. Usando dados de exemplo.")
        dados = DADOS_EXEMPLO

    if args.apenas_pdf:
        nome   = dados.get("nome_contratante", "cliente").replace(" ", "_")
        hoje   = date.today().strftime("%Y%m%d")
        output = Path(__file__).parent / f"Assessment_{nome}_{hoje}.pdf"
        preencher_pdf(dados, output)
    else:
        processar_resposta_forms(dados)


if __name__ == "__main__":
    main()
