"""
Cliente do Gemini (Google AI) para as camadas de IA nas bordas do motor —
parsing assistido e explicação. NUNCA no cálculo: core.py/modules.py/
engine.py não importam nada deste pacote, e nada aqui altera um número já
calculado deterministicamente.

Chave em GOOGLE_API_KEY (variável de ambiente, ou um arquivo .env na raiz do
projeto — carregado automaticamente via python-dotenv se presente, ver
.env.example). Se a chave estiver ausente — ou o SDK não estiver instalado,
ou a chamada falhar —, a IA fica indisponível e quem chamou decide o
fallback (normalmente: seguir sem a IA). Nunca uma dependência dura do motor.
"""
from __future__ import annotations

import os

MODELO_PADRAO = "gemini-2.5-flash"
_DOTENV_CARREGADO = False


class IAIndisponivel(RuntimeError):
    """A camada de IA não pode ser usada agora (sem chave configurada, SDK
    ausente, ou erro na chamada à API). Quem chama decide o fallback —
    nunca silenciado dentro do motor de cálculo."""


def _carregar_dotenv():
    """Carrega .env uma única vez (idempotente); silenciosamente ignora se
    python-dotenv não estiver instalado — variável de ambiente já setada
    (export manual) continua funcionando do mesmo jeito."""
    global _DOTENV_CARREGADO
    if _DOTENV_CARREGADO:
        return
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    _DOTENV_CARREGADO = True


def chave_configurada() -> bool:
    _carregar_dotenv()
    return bool(os.environ.get("GOOGLE_API_KEY"))


def gerar_texto(prompt: str, modelo: str = MODELO_PADRAO) -> str:
    """Chama a API do Gemini com o prompt e devolve o texto da resposta.
    Levanta IAIndisponivel em qualquer ponto de falha — nunca devolve um
    texto inventado ou vazio calado."""
    _carregar_dotenv()
    chave = os.environ.get("GOOGLE_API_KEY")
    if not chave:
        raise IAIndisponivel("GOOGLE_API_KEY não configurada")
    try:
        from google import genai
    except ImportError as e:
        raise IAIndisponivel(
            "pacote 'google-genai' não instalado (ver requirements-ia.txt)"
        ) from e
    try:
        cliente = genai.Client(api_key=chave)
        resposta = cliente.models.generate_content(model=modelo, contents=prompt)
        return resposta.text
    except Exception as e:
        raise IAIndisponivel(f"chamada à API do Gemini falhou: {e}") from e
