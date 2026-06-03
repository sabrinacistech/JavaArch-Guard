"""Consolidador: ensambla CodeFacts a partir de los extractores.

Pasos:
1. Detectar modulos: directorios con pom.xml o build.gradle (poms-agregador
   con `packaging=pom` se omiten — no llevan codigo).
2. Por cada modulo: parsear manifiesto, configs Spring, logback y sus Java.
3. Asignar cada archivo Java al modulo MAS CERCANO subiendo en el arbol.
4. Volcar todo a CodeFacts (inmutable conceptualmente).

Si no se encuentra ningun modulo se trata el proyecto entero como un modulo
virtual UNKNOWN, asi los skills tienen al menos un contenedor donde agrupar
los hallazgos.
"""
from __future__ import annotations

from pathlib import Path

from ..state import CodeFacts, Module
from .gradle_parser import detect_framework_gradle, parse_gradle
from .java_parser import parse_java_file
from .pom_parser import detect_framework_maven, parse_pom
from .runtime_config_parser import parse_logback, parse_runtime_config

_IGNORE_DIRS: frozenset[str] = frozenset({
    "target", "build", "out", ".git", "node_modules", ".gradle", ".idea",
})

_CONFIG_NAMES: tuple[str, ...] = (
    "application.yml", "application.yaml", "application.properties",
)
_LOGBACK_NAMES: tuple[str, ...] = ("logback.xml", "logback-spring.xml")


def _walk(root: Path, names: tuple[str, ...]):
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in _IGNORE_DIRS for part in p.parts):
            continue
        if p.name in names:
            yield p


def _detect_modules(root: Path) -> list[tuple[Path, Module]]:
    modules: list[tuple[Path, Module]] = []
    seen: set[Path] = set()

    for pom in _walk(root, ("pom.xml",)):
        mod_root = pom.parent
        if mod_root in seen:
            continue
        facts = parse_pom(pom)
        if facts is None:
            continue
        # Pom agregador: paquete `pom` con sub-modulos -> no es servicio en si
        if facts.packaging == "pom" and facts.modules:
            continue
        modules.append((mod_root, Module(
            name=facts.artifact_id or mod_root.name,
            root_path=str(mod_root),
            framework=detect_framework_maven(facts),
            build_tool="MAVEN",
        )))
        seen.add(mod_root)

    for gradle in _walk(root, ("build.gradle", "build.gradle.kts")):
        mod_root = gradle.parent
        if mod_root in seen:
            continue
        facts = parse_gradle(gradle)
        if facts is None:
            continue
        modules.append((mod_root, Module(
            name=mod_root.name,
            root_path=str(mod_root),
            framework=detect_framework_gradle(facts),
            build_tool="GRADLE",
        )))
        seen.add(mod_root)

    return modules


def _module_for(file_path: Path, module_roots: list[Path]) -> Path | None:
    """Devuelve el root de modulo mas profundo que es ancestro del archivo."""
    candidates = [r for r in module_roots if r in file_path.parents]
    if not candidates:
        return None
    return max(candidates, key=lambda r: len(r.parts))


def _resolve_import_module(imp: str, pkg_to_module: dict[str, str]) -> str | None:
    """Resuelve un import Java al modulo que declara ese paquete.

    `imp` es la ruta completa (`com.example.payment.client.Foo`). Buscamos el
    paquete PROPIO mas largo del que `imp` es miembro (prefijo + "."). El match
    mas largo gana para evitar que un paquete raiz compartido capture imports
    que pertenecen a un sub-paquete mas especifico de otro modulo.

    Devuelve None si el import no resuelve a ningun modulo del proyecto (caso
    tipico: dependencias externas como `org.springframework.*`). No inventamos
    pertenencia: si no es de un modulo conocido, no es una arista del grafo.
    """
    best_pkg: str | None = None
    best_mod: str | None = None
    for pkg, mod in pkg_to_module.items():
        if imp == pkg or imp.startswith(pkg + "."):
            if best_pkg is None or len(pkg) > len(best_pkg):
                best_pkg, best_mod = pkg, mod
    return best_mod


def consolidate(project_path: str | Path) -> CodeFacts:
    """Construye CodeFacts completo desde un proyecto en disco."""
    root = Path(project_path).resolve()

    detected = _detect_modules(root)
    if not detected:
        detected = [(root, Module(
            name=root.name, root_path=str(root),
            framework="UNKNOWN", build_tool="UNKNOWN",
        ))]

    module_roots = [r for r, _ in detected]
    modules = [m for _, m in detected]
    module_name_by_root = {r: m["name"] for r, m in detected}

    annotations_index: dict[str, list[dict]] = {}
    http_clients: list[dict] = []
    db_bindings: list[dict] = []

    # Para el grafo de dependencias modulo->modulo: que paquetes declara cada
    # modulo y que imports declara cada archivo (con su modulo dueno).
    module_packages: dict[str, set[str]] = {}
    file_imports: list[tuple[str, tuple[str, ...]]] = []

    for jf in root.rglob("*.java"):
        if any(part in _IGNORE_DIRS for part in jf.parts):
            continue
        facts = parse_java_file(jf)
        if facts is None:
            continue
        rel = str(jf.relative_to(root)).replace("\\", "/")
        annotations_index[rel] = [
            {
                "name": a.name,
                "target_kind": a.target_kind,
                "target_name": a.target_name,
                "attributes": dict(a.attributes),
                "line": a.line,
            }
            for a in facts.annotations
        ]
        owner = _module_for(jf, module_roots)
        module_name = module_name_by_root.get(owner, modules[0]["name"])

        if facts.package and facts.package != "(default)":
            module_packages.setdefault(module_name, set()).add(facts.package)
        if facts.imports:
            file_imports.append((module_name, facts.imports))

        for ann in facts.annotations:
            if ann.name == "FeignClient" and ann.target_kind == "TYPE":
                http_clients.append({
                    "type": "FEIGN",
                    "service_name": ann.attributes.get("name", ann.target_name),
                    "class_name": ann.target_name,
                    "module": module_name,
                    "file": rel,
                    "line": ann.line,
                    "attributes": dict(ann.attributes),
                })
            if ann.name in ("Entity", "Table") and ann.target_kind == "TYPE":
                db_bindings.append({
                    "type": "JPA_ENTITY",
                    "class_name": ann.target_name,
                    "module": module_name,
                    "file": rel,
                    "line": ann.line,
                })

    actuator_endpoints: set[str] = set()
    logging_config: dict = {
        "structured": False,
        "appenders": [],
        "mdc_keys": [],
    }

    for mod_root, mod in detected:
        for cfg_path in _walk(mod_root, _CONFIG_NAMES):
            cfg = parse_runtime_config(cfg_path)
            if cfg is None:
                continue
            actuator_endpoints.update(cfg.actuator_endpoints_exposed)
            if cfg.datasource_url:
                db_bindings.append({
                    "type": "DATASOURCE",
                    "module": mod["name"],
                    "url": cfg.datasource_url,
                    "file": str(cfg_path.relative_to(root)).replace("\\", "/"),
                    "line": 0,
                })

        for lb_path in _walk(mod_root, _LOGBACK_NAMES):
            lb = parse_logback(lb_path)
            if lb is None:
                continue
            if lb.has_structured_encoder:
                logging_config["structured"] = True
            logging_config["appenders"].extend(list(lb.appenders))
            logging_config["mdc_keys"].extend(lb.mdc_keys)

    logging_config["mdc_keys"] = sorted(set(logging_config["mdc_keys"]))

    # Grafo de dependencias modulo->modulo. Un paquete puede aparecer en varios
    # modulos solo en proyectos mal estructurados; nos quedamos con una
    # asignacion estable (la ultima vista) — el caso patologico ya es un hallazgo
    # en si mismo y lo cubrira el skill DATA_INDEP.
    pkg_to_module: dict[str, str] = {}
    for mod_name, pkgs in module_packages.items():
        for pkg in pkgs:
            pkg_to_module[pkg] = mod_name

    edges: dict[str, set[str]] = {}
    for mod_name, imports in file_imports:
        for imp in imports:
            target = _resolve_import_module(imp, pkg_to_module)
            if target is not None and target != mod_name:
                edges.setdefault(mod_name, set()).add(target)

    imports_graph = {src: sorted(dsts) for src, dsts in sorted(edges.items())}

    return CodeFacts(
        modules=modules,
        annotations_index=annotations_index,
        imports_graph=imports_graph,
        http_clients=http_clients,
        db_bindings=db_bindings,
        logging_config=logging_config,
        actuator_endpoints=sorted(actuator_endpoints),
        secrets_scan_raw={},
        lint_raw={},
    )