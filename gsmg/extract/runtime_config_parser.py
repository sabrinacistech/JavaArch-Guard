"""Parser de configuracion runtime: application.{yml,yaml,properties} + logback.

Estrategia para configs Spring: aplanar yaml a un dict de claves dotted, igual
formato que .properties. Asi un solo conjunto de reglas puede consultar ambos
formatos sin ramificar.

Para logback detectamos encoders estructurados (LogstashEncoder y familia) y
appenders. La presencia de encoder estructurado es la senal mas confiable de
"logs en JSON" — mucho mas que adivinar por el patron de texto.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class RuntimeConfigFacts:
    """Configuracion runtime aplanada + campos de interes ya derivados."""

    flat: dict[str, str]
    server_port: int | None
    actuator_endpoints_exposed: tuple[str, ...]
    datasource_url: str | None
    feign_client_names: tuple[str, ...]
    resilience4j_circuit_breakers: tuple[str, ...]
    logging_level_root: str | None


@dataclass(frozen=True)
class LogbackFacts:
    appenders: tuple[tuple[str, str], ...]  # (name, fqn de la clase)
    has_structured_encoder: bool
    pattern: str | None
    mdc_keys: tuple[str, ...]


# --------------------------------------------------------------------------- #
# YAML / properties
# --------------------------------------------------------------------------- #
def _flatten(node, prefix: str = "") -> dict[str, str]:
    """Aplana un dict yaml a {clave.dotted: valor_str}."""
    out: dict[str, str] = {}
    if isinstance(node, dict):
        for k, v in node.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            out.update(_flatten(v, key))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out.update(_flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = "" if node is None else str(node)
    return out


def _parse_yaml(path: Path) -> dict[str, str]:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    flat: dict[str, str] = {}
    try:
        for doc in yaml.safe_load_all(content):
            if doc is not None:
                flat.update(_flatten(doc))
    except yaml.YAMLError:
        return {}
    return flat


def _parse_properties(path: Path) -> dict[str, str]:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    out: dict[str, str] = {}
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "!")):
            continue
        sep = None
        for s in ("=", ":"):
            if s in line:
                sep = s
                break
        if sep is None:
            continue
        k, v = line.split(sep, 1)
        out[k.strip()] = v.strip()
    return out


def _names_at(flat: dict[str, str], prefix: str, depth: int) -> tuple[str, ...]:
    """Devuelve los `name` distintos en claves del estilo `<prefix>.<name>.x`."""
    names: set[str] = set()
    for key in flat:
        if not key.startswith(prefix):
            continue
        parts = key.split(".")
        if len(parts) <= depth:
            continue
        name = parts[depth]
        if name and name != "default":
            names.add(name)
    return tuple(sorted(names))


def parse_runtime_config(path: str | Path) -> RuntimeConfigFacts | None:
    """Parsea application.{yml,yaml,properties}. None si la extension no aplica
    o el archivo no se puede leer/parsear."""
    p = Path(path)
    if not p.exists():
        return None

    suffix = p.suffix.lower()
    if suffix in (".yml", ".yaml"):
        flat = _parse_yaml(p)
    elif suffix == ".properties":
        flat = _parse_properties(p)
    else:
        return None

    if not flat:
        return None

    server_port: int | None = None
    if "server.port" in flat:
        try:
            server_port = int(flat["server.port"])
        except ValueError:
            server_port = None

    actuator_raw = flat.get("management.endpoints.web.exposure.include", "")
    actuator_endpoints = tuple(
        e.strip() for e in actuator_raw.replace(",", " ").split() if e.strip()
    )

    feign_names = _names_at(flat, "feign.client.config.", 3)
    r4j_names = _names_at(flat, "resilience4j.circuitbreaker.instances.", 3)

    return RuntimeConfigFacts(
        flat=flat,
        server_port=server_port,
        actuator_endpoints_exposed=actuator_endpoints,
        datasource_url=flat.get("spring.datasource.url") or None,
        feign_client_names=feign_names,
        resilience4j_circuit_breakers=r4j_names,
        logging_level_root=flat.get("logging.level.root"),
    )


# --------------------------------------------------------------------------- #
# Logback
# --------------------------------------------------------------------------- #
_STRUCTURED_HINTS = (
    "LogstashEncoder",
    "LoggingEventCompositeJsonEncoder",
    "JsonLayout",
    "EcsEncoder",
)


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def parse_logback(path: str | Path) -> LogbackFacts | None:
    """Parsea logback.xml / logback-spring.xml.

    Detecta:
    - appenders y la clase del encoder usado
    - presencia de encoder estructurado (JSON)
    - patron de texto (si lo hay)
    - claves MDC declaradas via `%X{key}` o `<includeMdcKeyName>`
    """
    p = Path(path)
    try:
        root = ET.parse(p).getroot()
    except (ET.ParseError, OSError):
        return None

    appenders: list[tuple[str, str]] = []
    structured = False
    pattern: str | None = None
    mdc: set[str] = set()

    for elem in root.iter():
        local = _local(elem.tag)
        if local == "appender":
            name = elem.attrib.get("name", "")
            klass = elem.attrib.get("class", "")
            appenders.append((name, klass))
            if any(h in klass for h in _STRUCTURED_HINTS):
                structured = True
        elif local == "encoder":
            klass = elem.attrib.get("class", "")
            if any(h in klass for h in _STRUCTURED_HINTS):
                structured = True
        elif local == "pattern" and pattern is None:
            text = (elem.text or "").strip()
            pattern = text or None
            for token in text.split("%X{")[1:]:
                end = token.find("}")
                if end > 0:
                    mdc.add(token[:end])
        elif local == "includeMdcKeyName":
            key = (elem.text or "").strip()
            if key:
                mdc.add(key)

    return LogbackFacts(
        appenders=tuple(appenders),
        has_structured_encoder=structured,
        pattern=pattern,
        mdc_keys=tuple(sorted(mdc)),
    )