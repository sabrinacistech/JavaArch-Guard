"""Herramientas deterministas (codigo puro, 0 tokens de LLM).

Aqui vive todo lo que produce HECHOS verificables y reproducibles:
- ingest de archivos Java
- resumen de AST (firmas, anotaciones, imports) para abaratar el contexto LLM
- ejecucion y parseo de herramientas SAST/SCA
- deteccion determinista de logging (System.out, niveles)
- cobertura de Javadoc
- calculo de debt_score
- aplicacion de parches + recompilacion

Las funciones de ejecucion externa estan aisladas tras `_run` para poder
mockearlas facilmente en tests y porque el entorno puede no tener las
herramientas instaladas (degradan a vacio en vez de romper el grafo).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from ..config import SETTINGS, SEVERITY_WEIGHTS
from ..state import Finding, FileUnit, Patch


# --------------------------------------------------------------------------- #
# Ingest
# --------------------------------------------------------------------------- #
def load_java_files(project_path: str) -> list[FileUnit]:
    root = Path(project_path)
    units: list[FileUnit] = []
    for p in root.rglob("*.java"):
        if any(part in SETTINGS.ignore_dirs for part in p.parts):
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        units.append(
            FileUnit(path=str(p.relative_to(root)), content=content, ast_summary="")
        )
    return units


# --------------------------------------------------------------------------- #
# AST summary (regex-based; reemplazable por JavaParser/tree-sitter)
# --------------------------------------------------------------------------- #
_PKG = re.compile(r"^\s*package\s+([\w.]+);", re.M)
_IMPORT = re.compile(r"^\s*import\s+(static\s+)?([\w.*]+);", re.M)
_TYPE = re.compile(
    r"(?:^|\n)\s*(?:public|protected|private)?\s*"
    r"(?:final|abstract|sealed|non-sealed)?\s*"
    r"(class|interface|enum|record)\s+(\w+)"
)
_PUB_METHOD = re.compile(
    r"\n\s*(public)\s+(?:static\s+)?(?:final\s+)?"
    r"[\w<>\[\],.\s?]+\s+(\w+)\s*\([^)]*\)"
)
_ANNOTATION = re.compile(r"\n\s*@(\w+)")


def java_ast_summary(content: str) -> str:
    """Resumen compacto: paquete, imports, tipos, metodos publicos, anotaciones.

    Reduce el contexto enviado al LLM ~80-90% frente al archivo crudo.
    """
    pkg = _PKG.search(content)
    imports = [m.group(2) for m in _IMPORT.finditer(content)]
    types = [f"{m.group(1)} {m.group(2)}" for m in _TYPE.finditer(content)]
    pub_methods = [m.group(2) for m in _PUB_METHOD.finditer(content)]
    annotations = sorted({m.group(1) for m in _ANNOTATION.finditer(content)})

    parts = [
        f"package: {pkg.group(1) if pkg else '(default)'}",
        f"imports: {', '.join(imports[:40])}",
        f"types: {', '.join(types)}",
        f"public_methods: {', '.join(pub_methods[:60])}",
        f"annotations: {', '.join(annotations)}",
        f"loc: {content.count(chr(10)) + 1}",
    ]
    return "\n".join(parts)


def summarize_files(files: list[FileUnit]) -> list[FileUnit]:
    return [FileUnit(**{**f, "ast_summary": java_ast_summary(f["content"])}) for f in files]


# --------------------------------------------------------------------------- #
# Ejecucion de herramientas externas (aislada para mock/degradacion)
# --------------------------------------------------------------------------- #
def _run(cmd: str, timeout: int = 600) -> str:
    """Ejecuta un comando; devuelve stdout o '' si la herramienta no existe."""
    exe = cmd.split()[0]
    if shutil.which(exe) is None:
        return ""
    try:
        proc = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return proc.stdout or ""
    except (subprocess.TimeoutExpired, OSError):
        return ""


def run_static_tools(project_path: str) -> dict[str, str]:
    raw: dict[str, str] = {}
    for name, template in SETTINGS.static_tools.items():
        raw[name] = _run(template.format(path=project_path))
    return raw


# --------------------------------------------------------------------------- #
# Parseo de salidas a Findings normalizados (source="TOOL")
# --------------------------------------------------------------------------- #
def _sev_from_semgrep(s: str) -> str:
    return {"ERROR": "CRITICAL", "WARNING": "MAJOR", "INFO": "MINOR"}.get(s, "MINOR")


def parse_tool_findings(raw: dict[str, str]) -> list[Finding]:
    findings: list[Finding] = []

    # Semgrep (OWASP) -> seguridad
    try:
        data = json.loads(raw.get("semgrep") or "{}")
        for r in data.get("results", []):
            findings.append(
                Finding(
                    dimension="SECURITY",
                    severity=_sev_from_semgrep(
                        r.get("extra", {}).get("severity", "INFO")
                    ),
                    rule_id=r.get("check_id", "SEMGREP"),
                    file=r.get("path", ""),
                    line=r.get("start", {}).get("line", 0),
                    message=r.get("extra", {}).get("message", ""),
                    suggestion="Revisar regla OWASP asociada.",
                    source="TOOL",
                )
            )
    except (json.JSONDecodeError, AttributeError):
        pass

    # detect-secrets -> seguridad CRITICAL
    try:
        data = json.loads(raw.get("detect_secrets") or "{}")
        for path, secrets in data.get("results", {}).items():
            for sec in secrets:
                findings.append(
                    Finding(
                        dimension="SECURITY",
                        severity="CRITICAL",
                        rule_id=f"SECRET-{sec.get('type', 'UNKNOWN')}",
                        file=path,
                        line=sec.get("line_number", 0),
                        message="Posible secreto hardcodeado.",
                        suggestion="Mover a variable de entorno o gestor de secretos.",
                        source="TOOL",
                    )
                )
    except (json.JSONDecodeError, AttributeError):
        pass

    return findings


# --------------------------------------------------------------------------- #
# Reglas deterministas de logging y documentacion
# --------------------------------------------------------------------------- #
_SYSOUT = re.compile(r"System\.(out|err)\.print")
_JAVADOC_BEFORE_PUBLIC = re.compile(r"/\*\*[\s\S]*?\*/\s*\n\s*public")


def detect_logging_issues(files: list[FileUnit]) -> list[Finding]:
    out: list[Finding] = []
    for f in files:
        for i, line in enumerate(f["content"].splitlines(), start=1):
            if _SYSOUT.search(line):
                out.append(
                    Finding(
                        dimension="LOGGING",
                        severity="MAJOR",
                        rule_id="LOG-SYSOUT",
                        file=f["path"],
                        line=i,
                        message="Uso de System.out/err en vez de un logger.",
                        suggestion="Usar SLF4J (logger.info/debug/error) con placeholders.",
                        source="TOOL",
                    )
                )
    return out


def detect_doc_coverage(files: list[FileUnit]) -> list[Finding]:
    out: list[Finding] = []
    for f in files:
        public_methods = len(_PUB_METHOD.findall(f["content"]))
        documented = len(_JAVADOC_BEFORE_PUBLIC.findall(f["content"]))
        missing = max(public_methods - documented, 0)
        if public_methods >= 3 and missing > 0:
            out.append(
                Finding(
                    dimension="DOC",
                    severity="MINOR",
                    rule_id="DOC-COVERAGE",
                    file=f["path"],
                    line=0,
                    message=f"{missing}/{public_methods} APIs publicas sin Javadoc.",
                    suggestion="Documentar contratos publicos (params, retorno, excepciones).",
                    source="TOOL",
                )
            )
    return out


# --------------------------------------------------------------------------- #
# Agregacion y scoring (deterministas)
# --------------------------------------------------------------------------- #
def dedupe(findings: list[Finding]) -> list[Finding]:
    seen: set[tuple] = set()
    out: list[Finding] = []
    for f in findings:
        key = (f["dimension"], f["rule_id"], f["file"], f["line"])
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def compute_debt_score(findings: list[Finding]) -> tuple[float, int]:
    score = float(sum(SEVERITY_WEIGHTS.get(f["severity"], 0) for f in findings))
    critical = sum(1 for f in findings if f["severity"] == "CRITICAL")
    return score, critical


# --------------------------------------------------------------------------- #
# Verificacion de refactors
# --------------------------------------------------------------------------- #
def apply_patches(project_path: str, patches: list[Patch]) -> None:
    for p in patches:
        diff_file = Path(project_path) / ".archguard_patch.diff"
        diff_file.write_text(p["diff"], encoding="utf-8")
        _run(f"git -C {project_path} apply {diff_file}")
        diff_file.unlink(missing_ok=True)


def compile_project(project_path: str) -> bool:
    exe = SETTINGS.compile_cmd.split()[0]
    if shutil.which(exe) is None:
        return True  # no se puede verificar -> no bloquea
    try:
        proc = subprocess.run(
            SETTINGS.compile_cmd, shell=True, cwd=project_path,
            capture_output=True, text=True, timeout=900,
        )
        return proc.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False
