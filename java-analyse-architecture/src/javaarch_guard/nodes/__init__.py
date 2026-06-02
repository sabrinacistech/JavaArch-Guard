"""Nodos del grafo. Cada funcion recibe el State y devuelve un dict parcial
que LangGraph fusiona usando los reducers definidos en state.py.

Convencion de tipos por nodo (ver tabla del diseno):
- DETERMINISTA: solo codigo, 0 tokens.
- LLM: invoca al modelo con prompt de prompts/__init__.py.
- HIBRIDO: reglas deterministas + LLM para lo semantico.
"""
from __future__ import annotations

import json

from ..llm import call_llm_json
from ..prompts import (
    DESIGN_PATTERNS_PROMPT,
    DOCUMENTATION_PROMPT,
    LANG_PRACTICES_PROMPT,
    LOGGING_PROMPT,
    REFACTOR_PROMPT,
    REPORT_SUMMARY_PROMPT,
    SECURITY_PROMPT,
)
from ..state import ArchGuardState, Finding, Patch
from .. import tools


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _coerce_findings(raw: dict, dimension: str) -> list[Finding]:
    out: list[Finding] = []
    for item in raw.get("findings", []):
        try:
            out.append(
                Finding(
                    dimension=dimension,
                    severity=item.get("severity", "INFO"),
                    rule_id=str(item.get("rule_id", "LLM")),
                    file=str(item.get("file", "")),
                    line=int(item.get("line", 0) or 0),
                    message=str(item.get("message", "")),
                    suggestion=str(item.get("suggestion", "")),
                    source="LLM",
                )
            )
        except (TypeError, ValueError):
            continue
    return out


def _ast_payload(files) -> str:
    return "\n\n".join(f"### {f['path']}\n{f['ast_summary']}" for f in files)


# --------------------------------------------------------------------------- #
# Nodos DETERMINISTAS
# --------------------------------------------------------------------------- #
def ingest_code(s: ArchGuardState) -> dict:
    files = tools.load_java_files(s["project_path"])
    return {"files": files, "messages": [f"ingest: {len(files)} archivos .java"]}


def build_ast(s: ArchGuardState) -> dict:
    return {"files": tools.summarize_files(s["files"])}


def run_static(s: ArchGuardState) -> dict:
    raw = tools.run_static_tools(s["project_path"])
    return {
        "static_raw": raw,
        "findings": tools.parse_tool_findings(raw),
        "messages": ["herramientas SAST/SCA ejecutadas"],
    }


def aggregate_findings(s: ArchGuardState) -> dict:
    return {"findings": tools.dedupe(s["findings"]), "messages": ["findings agregados"]}


def score_node(s: ArchGuardState) -> dict:
    score, critical = tools.compute_debt_score(s["findings"])
    return {
        "debt_score": score,
        "critical_count": critical,
        "metrics": {"total_findings": len(s["findings"]), "critical": critical},
    }


def verify_refactor(s: ArchGuardState) -> dict:
    tools.apply_patches(s["project_path"], s["patches"])
    ok = tools.compile_project(s["project_path"])
    files = tools.summarize_files(tools.load_java_files(s["project_path"]))
    rescan = tools.parse_tool_findings(tools.run_static_tools(s["project_path"]))
    rescan += tools.detect_logging_issues(files)
    rescan += tools.detect_doc_coverage(files)
    return {
        "files": files,
        "findings": tools.dedupe(rescan),
        "iteration": s["iteration"] + 1,
        "messages": [f"verify iter={s['iteration'] + 1} compila={ok}"],
    }


# --------------------------------------------------------------------------- #
# Nodos LLM / HIBRIDOS
# --------------------------------------------------------------------------- #
def lang_practices_agent(s: ArchGuardState) -> dict:
    raw = call_llm_json(LANG_PRACTICES_PROMPT, _ast_payload(s["files"]))
    return {"findings": _coerce_findings(raw, "LANG")}


def security_agent(s: ArchGuardState) -> dict:
    tool_facts = [f for f in s["findings"] if f["dimension"] == "SECURITY"]
    user = "HALLAZGOS DE HERRAMIENTAS:\n" + json.dumps(tool_facts, ensure_ascii=False)
    raw = call_llm_json(SECURITY_PROMPT, user)
    # El LLM solo re-triagea; si no responde, conservamos los hechos de la herramienta.
    return {"findings": _coerce_findings(raw, "SECURITY")}


def design_patterns_agent(s: ArchGuardState) -> dict:
    raw = call_llm_json(DESIGN_PATTERNS_PROMPT, _ast_payload(s["files"]))
    return {"findings": _coerce_findings(raw, "DESIGN")}


def logging_agent(s: ArchGuardState) -> dict:
    deterministic = tools.detect_logging_issues(s["files"])  # System.out, etc.
    raw = call_llm_json(LOGGING_PROMPT, _ast_payload(s["files"]))  # PII, niveles
    return {"findings": deterministic + _coerce_findings(raw, "LOGGING")}


def documentation_agent(s: ArchGuardState) -> dict:
    deterministic = tools.detect_doc_coverage(s["files"])  # cobertura
    raw = call_llm_json(DOCUMENTATION_PROMPT, _ast_payload(s["files"]))  # calidad
    return {"findings": deterministic + _coerce_findings(raw, "DOC")}


def refactor_agent(s: ArchGuardState) -> dict:
    targets = [f for f in s["findings"] if f["severity"] in ("CRITICAL", "MAJOR")]
    affected = {f["file"] for f in targets}
    code = "\n\n".join(
        f"### {f['path']}\n```java\n{f['content']}\n```"
        for f in s["files"]
        if f["path"] in affected
    )
    user = f"HALLAZGOS:\n{json.dumps(targets, ensure_ascii=False)}\n\nCODIGO:\n{code}"
    raw = call_llm_json(REFACTOR_PROMPT, user)
    patches: list[Patch] = []
    for p in raw.get("patches", []):
        patches.append(
            Patch(
                file=str(p.get("file", "")),
                diff=str(p.get("diff", "")),
                rationale=str(p.get("rationale", "")),
                addresses_rules=list(p.get("addresses_rules", [])),
            )
        )
    return {"patches": patches, "messages": [f"refactor: {len(patches)} parches"]}


def consolidate_report(s: ArchGuardState) -> dict:
    user = json.dumps(
        {
            "debt_score": s["debt_score"],
            "metrics": s["metrics"],
            "findings": s["findings"][:80],
        },
        ensure_ascii=False,
    )
    summary = call_llm_json(REPORT_SUMMARY_PROMPT, user)  # puede venir vacio
    summary_text = summary.get("text") if isinstance(summary, dict) else ""
    report = _render_markdown(s, summary_text or "")
    return {"report_md": report, "gate_status": "PASS" if s["critical_count"] == 0 else "FAIL"}


def _render_markdown(s: ArchGuardState, summary: str) -> str:
    by_dim: dict[str, list] = {}
    for f in s["findings"]:
        by_dim.setdefault(f["dimension"], []).append(f)
    lines = [
        "# Reporte JavaArch-Guard",
        "",
        f"**Debt score:** {s['debt_score']:.0f}  |  "
        f"**Criticos:** {s['critical_count']}  |  "
        f"**Iteraciones:** {s['iteration']}",
        "",
    ]
    if summary:
        lines += ["## Resumen ejecutivo", "", summary, ""]
    for dim in ("SECURITY", "LANG", "DESIGN", "LOGGING", "DOC"):
        items = by_dim.get(dim, [])
        lines.append(f"## {dim} ({len(items)})")
        for f in sorted(items, key=lambda x: x["severity"]):
            src = "🔧" if f["source"] == "TOOL" else "🤖"
            lines.append(
                f"- {src} `{f['severity']}` **{f['rule_id']}** "
                f"{f['file']}:{f['line']} — {f['message']}"
            )
        lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# ROUTERS (deterministas)
# --------------------------------------------------------------------------- #
ANALYSIS_BRANCHES = ["lang", "sec", "design", "log", "doc"]


def fan_out_router(s: ArchGuardState) -> list[str]:
    return ANALYSIS_BRANCHES


def quality_gate_router(s: ArchGuardState) -> str:
    """REGLA DURA: la decision de iterar NO la toma el LLM."""
    if s["critical_count"] > 0 and s["iteration"] < s["max_iterations"]:
        return "refactor"
    return "report"
