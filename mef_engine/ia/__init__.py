"""
Camadas de IA na borda do motor (Gemini/Google AI) — parsing assistido e
explicação. Nunca no cálculo: core.py/modules.py/engine.py não dependem
deste pacote, e nada aqui altera um resultado já calculado.

Opcional: requer GOOGLE_API_KEY e o pacote 'google-genai' (ver
requirements-ia.txt). Sem isso, as funções aqui ficam indisponíveis
(`IAIndisponivel`) e o resto do motor continua funcionando normalmente.
"""
from __future__ import annotations

from .cliente import IAIndisponivel, chave_configurada, gerar_texto
from .explicacao import explicar_resultado, montar_prompt_explicacao
from .parsing import (
    detectar_e_ingerir_com_ia_fallback, montar_prompt_parsing,
    parsear_resposta_parsing, sugerir_faixas,
)

__all__ = [
    "IAIndisponivel", "chave_configurada", "gerar_texto",
    "explicar_resultado", "montar_prompt_explicacao",
    "detectar_e_ingerir_com_ia_fallback", "montar_prompt_parsing",
    "parsear_resposta_parsing", "sugerir_faixas",
]
