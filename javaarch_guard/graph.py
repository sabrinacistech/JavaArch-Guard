"""Construccion del StateGraph del Guardian de Arquitectura.

Flujo:
  ingest -> ast -> static -> (fan-out paralelo: lang/sec/design/log/doc)
         -> aggregate -> score -> gate
                                   |-> refactor -> verify -> score  (bucle)
                                   |-> report -> END
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from . import nodes
from .state import ArchGuardState, initial_state


def build_graph():
    g = StateGraph(ArchGuardState)

    # Nodos
    g.add_node("ingest", nodes.ingest_code)
    g.add_node("ast", nodes.build_ast)
    g.add_node("static", nodes.run_static)
    g.add_node("lang", nodes.lang_practices_agent)
    g.add_node("sec", nodes.security_agent)
    g.add_node("design", nodes.design_patterns_agent)
    g.add_node("log", nodes.logging_agent)
    g.add_node("doc", nodes.documentation_agent)
    g.add_node("aggregate", nodes.aggregate_findings)
    g.add_node("score", nodes.score_node)
    g.add_node("refactor", nodes.refactor_agent)
    g.add_node("verify", nodes.verify_refactor)
    g.add_node("report", nodes.consolidate_report)

    # Pipeline determinista inicial
    g.add_edge(START, "ingest")
    g.add_edge("ingest", "ast")
    g.add_edge("ast", "static")

    # Fan-out paralelo de los 5 analisis
    g.add_conditional_edges("static", nodes.fan_out_router, nodes.ANALYSIS_BRANCHES)
    for branch in nodes.ANALYSIS_BRANCHES:
        g.add_edge(branch, "aggregate")  # fan-in via reducer 'add'

    g.add_edge("aggregate", "score")

    # Quality gate + bucle de correccion (terminacion garantizada por max_iterations)
    g.add_conditional_edges(
        "score", nodes.quality_gate_router,
        {"refactor": "refactor", "report": "report"},
    )
    g.add_edge("refactor", "verify")
    g.add_edge("verify", "score")
    g.add_edge("report", END)

    return g.compile()


def run(project_path: str, max_iterations: int = 3) -> ArchGuardState:
    app = build_graph()
    return app.invoke(initial_state(project_path, max_iterations))
