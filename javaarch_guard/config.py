"""Configuracion central del Guardian. Todo lo ajustable vive aqui."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


# Pesos para el calculo determinista del debt_score.
SEVERITY_WEIGHTS: dict[str, int] = {
    "CRITICAL": 10,
    "MAJOR": 4,
    "MINOR": 1,
    "INFO": 0,
}


@dataclass(frozen=True)
class Settings:
    # LLM: temperatura 0 para minimizar aleatoriedad.
    model: str = os.getenv("ARCHGUARD_MODEL", "claude-sonnet-4-5")
    temperature: float = 0.0
    max_tokens: int = 4096

    # Umbral del quality gate. Si quedan criticos, se intenta refactor.
    max_iterations: int = int(os.getenv("ARCHGUARD_MAX_ITER", "3"))

    # Cualquier debt_score por encima de esto bloquea el merge en CI.
    debt_score_gate: int = int(os.getenv("ARCHGUARD_DEBT_GATE", "30"))

    # Comandos de herramientas estaticas (deterministas).
    static_tools: dict[str, str] = field(
        default_factory=lambda: {
            "semgrep": "semgrep scan --config=p/owasp-top-ten --json {path}",
            "pmd": "pmd check -d {path} -R rulesets/java/quickstart.xml -f json",
            "spotbugs": "spotbugs -textui -json {path}",
            "dependency_check": "dependency-check --scan {path} --format JSON",
            "detect_secrets": "detect-secrets scan {path}",
        }
    )

    # Extensiones y rutas a ignorar al ingerir codigo.
    java_glob: str = "**/*.java"
    ignore_dirs: tuple[str, ...] = ("target", "build", ".git", "node_modules")

    # Build tool para verificar refactors.
    compile_cmd: str = os.getenv("ARCHGUARD_COMPILE", "mvn -q -DskipTests compile")


SETTINGS = Settings()
