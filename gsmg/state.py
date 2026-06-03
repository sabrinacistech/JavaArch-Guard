"""Estado global de GSMG.

Decisiones de diseno:
- `facts` es producido por la capa determinista y debe tratarse como inmutable
  tras `extract`. Los skills solo leen de `facts`.
- `findings` y `traces` usan reducer `add` para fan-out paralelo seguro.
- `routing` deja por escrito QUE decidio el Supervisor y POR QUE. Es la base
  de la auditabilidad: cualquier persona puede leer el reporte y entender
  por que se activo (o no) un skill.
- La terminacion del bucle NUNCA depende del LLM: la gobierna `max_iterations`.
"""
from __future__ import annotations

from operator import add
from typing import Annotated, Literal, TypedDict

Severity = Literal["INFO", "MINOR", "MAJOR", "CRITICAL", "BLOCKER"]
Pillar = Literal["RESILIENCE", "OBSERVABILITY", "DATA_INDEP", "CLEANCODE", "SECURITY"]
Framework = Literal[
    "SPRING_BOOT", "QUARKUS", "MICRONAUT", "FASTAPI", "FLASK", "UNKNOWN"
]
BuildTool = Literal["MAVEN", "GRADLE", "POETRY", "PIP", "UNKNOWN"]


class Module(TypedDict):
    """Microservicio detectado dentro del proyecto."""

    name: str
    root_path: str
    framework: Framework
    build_tool: BuildTool


class Finding(TypedDict):
    """Hallazgo normalizado emitido por un skill."""

    pillar: Pillar
    severity: Severity
    rule_id: str
    module: str
    file: str
    line: int
    evidence: str
    message: str
    suggestion: str
    source: Literal["TOOL", "LLM", "HYBRID"]
    confidence: float


class CodeFacts(TypedDict, total=False):
    """Hechos extraidos por la capa determinista.

    Es la fuente de verdad para todos los skills. NO se modifica despues
    de la fase `extract`.
    """

    modules: list[Module]
    annotations_index: dict[str, list[dict]]
    imports_graph: dict[str, list[str]]
    http_clients: list[dict]
    db_bindings: list[dict]
    logging_config: dict
    actuator_endpoints: list[str]
    secrets_scan_raw: dict
    lint_raw: dict[str, str]


class RouterDecision(TypedDict):
    """Traza explicable de la decision del Supervisor."""

    activated_skills: list[Pillar]
    skipped_skills: list[tuple[Pillar, str]]
    rationale: str
    decided_by: Literal["RULES", "LLM_ROUTER"]


class GSMGState(TypedDict, total=False):
    # --- Entrada ---
    project_path: str
    config: dict

    # --- Capa determinista (inmutable tras extract) ---
    facts: CodeFacts

    # --- Orquestacion ---
    routing: RouterDecision

    # --- Acumuladores concurrentes (fan-out seguro) ---
    findings: Annotated[list[Finding], add]
    traces: Annotated[list[str], add]

    # --- Scoring + gate ---
    debt_score: float
    blocker_count: int
    critical_count: int
    pillar_scores: dict[Pillar, float]

    # --- Iteracion de mejora ---
    iteration: int
    max_iterations: int
    gate_status: Literal["PENDING", "PASS", "FAIL"]

    # --- Salida ---
    report_md: str
    report_json: dict
    report_sarif: dict


def initial_state(project_path: str, max_iterations: int = 3) -> GSMGState:
    """Estado inicial con valores por defecto seguros."""
    return GSMGState(
        project_path=project_path,
        config={},
        facts=CodeFacts(),
        routing=RouterDecision(
            activated_skills=[], skipped_skills=[],
            rationale="", decided_by="RULES",
        ),
        findings=[],
        traces=[],
        debt_score=0.0,
        blocker_count=0,
        critical_count=0,
        pillar_scores={},
        iteration=0,
        max_iterations=max_iterations,
        gate_status="PENDING",
        report_md="",
        report_json={},
        report_sarif={},
    )