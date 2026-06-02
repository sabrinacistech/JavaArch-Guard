"""Estado global tipado que viaja por el grafo de JavaArch-Guard.

Decisiones de diseño:
- Los acumuladores usan `Annotated[..., add]` para permitir fan-out paralelo
  de los agentes de analisis sin condiciones de carrera (cada rama hace append).
- `max_iterations` impone terminacion garantizada del bucle de correccion:
  la decision de iterar NUNCA depende del LLM, es una regla dura del router.
- Cada Finding lleva `source` ("TOOL" | "LLM") para auditar que parte del
  resultado es determinista y cual proviene del modelo.
"""
from __future__ import annotations

from operator import add
from typing import Annotated, Literal, TypedDict

Severity = Literal["INFO", "MINOR", "MAJOR", "CRITICAL"]
Dimension = Literal["LANG", "SECURITY", "DESIGN", "LOGGING", "DOC"]
FindingSource = Literal["TOOL", "LLM"]


class Finding(TypedDict):
    """Hallazgo individual normalizado."""

    dimension: Dimension
    severity: Severity
    rule_id: str  # ej. "OWASP-A03-SQLI", "SOLID-SRP", "LOG-SYSOUT"
    file: str
    line: int
    message: str
    suggestion: str
    source: FindingSource


class FileUnit(TypedDict):
    """Unidad de archivo Java con resumen de AST para ahorrar tokens."""

    path: str
    content: str
    ast_summary: str  # firmas publicas, anotaciones, imports (resumen barato)


class Patch(TypedDict):
    """Parche propuesto por el agente de refactor."""

    file: str
    diff: str  # unified diff
    rationale: str
    addresses_rules: list[str]


class ArchGuardState(TypedDict, total=False):
    # --- Entrada inmutable ---
    project_path: str
    files: list[FileUnit]

    # --- Resultados deterministas de herramientas ---
    static_raw: dict[str, str]  # salida cruda por herramienta

    # --- Acumuladores concurrentes (fan-out seguro) ---
    findings: Annotated[list[Finding], add]
    messages: Annotated[list[str], add]

    # --- Metricas y puntuacion (deterministas) ---
    metrics: dict[str, float]
    debt_score: float
    critical_count: int

    # --- Bucle de correccion ---
    patches: Annotated[list[Patch], add]
    iteration: int
    max_iterations: int
    gate_status: Literal["PENDING", "PASS", "FAIL"]

    # --- Salida ---
    report_md: str


def initial_state(project_path: str, max_iterations: int = 3) -> ArchGuardState:
    """Construye el estado inicial con valores por defecto seguros."""
    return ArchGuardState(
        project_path=project_path,
        files=[],
        static_raw={},
        findings=[],
        messages=[],
        metrics={},
        debt_score=0.0,
        critical_count=0,
        patches=[],
        iteration=0,
        max_iterations=max_iterations,
        gate_status="PENDING",
        report_md="",
    )
