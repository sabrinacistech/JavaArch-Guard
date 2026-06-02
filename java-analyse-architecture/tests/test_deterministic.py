"""Tests deterministas. No requieren API key: el grafo corre con LLM degradado
a vacio, validando que la parte determinista (AST, SAST parse, scoring, gate,
reporte) funciona por si sola.
"""
from __future__ import annotations

from javaarch_guard import tools
from javaarch_guard.nodes import quality_gate_router
from javaarch_guard.state import Finding


def _finding(sev: str, dim: str = "SECURITY") -> Finding:
    return Finding(dimension=dim, severity=sev, rule_id="X", file="A.java",
                   line=1, message="m", suggestion="s", source="TOOL")


def test_ast_summary_extracts_record_and_methods():
    src = (
        "package com.demo;\n"
        "import java.util.List;\n"
        "public record User(String name) {\n"
        "  public String greet() { return name; }\n"
        "}\n"
    )
    summary = tools.java_ast_summary(src)
    assert "com.demo" in summary
    assert "record User" in summary
    assert "greet" in summary
    assert "java.util.List" in summary


def test_detect_sysout_logging():
    files = [{"path": "A.java", "content": 'System.out.println("hi");', "ast_summary": ""}]
    found = tools.detect_logging_issues(files)
    assert len(found) == 1
    assert found[0]["rule_id"] == "LOG-SYSOUT"
    assert found[0]["severity"] == "MAJOR"


def test_debt_score_weights():
    findings = [_finding("CRITICAL"), _finding("MAJOR"), _finding("MINOR")]
    score, critical = tools.compute_debt_score(findings)
    assert score == 10 + 4 + 1
    assert critical == 1


def test_dedupe_removes_duplicates():
    f = _finding("MAJOR")
    assert len(tools.dedupe([f, dict(f)])) == 1  # type: ignore[arg-type]


def test_gate_routes_to_refactor_when_critical_and_iterations_left():
    state = {"critical_count": 2, "iteration": 0, "max_iterations": 3}
    assert quality_gate_router(state) == "refactor"  # type: ignore[arg-type]


def test_gate_routes_to_report_when_iterations_exhausted():
    state = {"critical_count": 2, "iteration": 3, "max_iterations": 3}
    assert quality_gate_router(state) == "report"  # type: ignore[arg-type]


def test_gate_routes_to_report_when_clean():
    state = {"critical_count": 0, "iteration": 0, "max_iterations": 3}
    assert quality_gate_router(state) == "report"  # type: ignore[arg-type]


def test_parse_semgrep_findings():
    raw = {"semgrep": '{"results":[{"check_id":"java.sqli","path":"A.java",'
                       '"start":{"line":10},"extra":{"severity":"ERROR","message":"SQLi"}}]}'}
    found = tools.parse_tool_findings(raw)
    assert found[0]["severity"] == "CRITICAL"
    assert found[0]["dimension"] == "SECURITY"
    assert found[0]["line"] == 10
