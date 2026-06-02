"""Cliente LLM minimo. Aisla la dependencia del proveedor del resto del grafo.

- temperature=0 fijo.
- Fuerza/repara salida JSON.
- Si no hay ANTHROPIC_API_KEY o falta el SDK, degrada a respuesta vacia para
  que el grafo siga corriendo (los nodos deterministas igual producen valor).
"""
from __future__ import annotations

import json
import os
import re

from .config import SETTINGS

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.M)


def _extract_json(text: str) -> dict:
    text = _FENCE.sub("", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # rescata el primer objeto {...} balanceado
        start = text.find("{")
        if start == -1:
            return {}
        depth = 0
        for i in range(start, len(text)):
            depth += text[i] == "{"
            depth -= text[i] == "}"
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return {}
        return {}


def call_llm_json(system: str, user: str) -> dict:
    """Llama al LLM y devuelve un dict parseado. {} si no hay backend."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {}
    try:
        import anthropic  # import perezoso
    except ImportError:
        return {}

    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=SETTINGS.model,
        max_tokens=SETTINGS.max_tokens,
        temperature=SETTINGS.temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    return _extract_json(text)
