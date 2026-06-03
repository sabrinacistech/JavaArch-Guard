"""Parser de pom.xml (Maven).

Extrae coordenadas, padre, modulos hijos, dependencias y propiedades.
NO resuelve interpolacion de variables (`${spring.version}`): el resultado
conserva texto crudo. La resolucion completa (descarga del pom padre,
herencia transitiva) queda fuera de F2; los skills aguas abajo trabajan
sobre lo declarado, que es lo que un revisor humano leeria.

Manejo de namespaces: pom.xml suele tener xmlns; usamos comparacion por
tag local para tolerar archivos con y sin namespace.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from ..state import Framework


@dataclass(frozen=True)
class MavenDependency:
    group_id: str
    artifact_id: str
    version: str | None
    scope: str  # "compile" (default), "test", "provided", "runtime", "import"


@dataclass(frozen=True)
class MavenProjectFacts:
    group_id: str
    artifact_id: str
    version: str
    packaging: str
    parent: tuple[str, str, str] | None  # (groupId, artifactId, version)
    modules: tuple[str, ...]
    dependencies: tuple[MavenDependency, ...]
    properties: dict[str, str]


_SPRING_BOOT_HINTS = ("spring-boot-starter", "spring-boot-dependencies")
_QUARKUS_HINTS = ("quarkus-",)
_MICRONAUT_HINTS = ("micronaut-",)


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _child(elem, name: str):
    if elem is None:
        return None
    for c in elem:
        if _local(c.tag) == name:
            return c
    return None


def _text(elem, default: str = "") -> str:
    if elem is None:
        return default
    return (elem.text or "").strip() or default


def parse_pom(path: str | Path) -> MavenProjectFacts | None:
    """Parsea un pom.xml. Devuelve None si el archivo no es XML valido."""
    p = Path(path)
    try:
        root = ET.parse(p).getroot()
    except (ET.ParseError, OSError):
        return None

    parent_elem = _child(root, "parent")
    parent: tuple[str, str, str] | None = None
    if parent_elem is not None:
        parent = (
            _text(_child(parent_elem, "groupId")),
            _text(_child(parent_elem, "artifactId")),
            _text(_child(parent_elem, "version")),
        )

    group_id = _text(_child(root, "groupId")) or (parent[0] if parent else "")
    version = _text(_child(root, "version")) or (parent[2] if parent else "")

    modules_elem = _child(root, "modules")
    modules_iter = modules_elem if modules_elem is not None else ()
    modules = tuple(
        _text(m) for m in modules_iter
        if _local(m.tag) == "module" and _text(m)
    )

    deps_elem = _child(root, "dependencies")
    dependencies: list[MavenDependency] = []
    if deps_elem is not None:
        for dep in deps_elem:
            if _local(dep.tag) != "dependency":
                continue
            dependencies.append(MavenDependency(
                group_id=_text(_child(dep, "groupId")),
                artifact_id=_text(_child(dep, "artifactId")),
                version=_text(_child(dep, "version")) or None,
                scope=_text(_child(dep, "scope"), "compile"),
            ))

    props_elem = _child(root, "properties")
    properties: dict[str, str] = {}
    if props_elem is not None:
        for prop in props_elem:
            properties[_local(prop.tag)] = _text(prop)

    return MavenProjectFacts(
        group_id=group_id,
        artifact_id=_text(_child(root, "artifactId")),
        version=version,
        packaging=_text(_child(root, "packaging"), "jar"),
        parent=parent,
        modules=modules,
        dependencies=tuple(dependencies),
        properties=properties,
    )


def detect_framework_maven(facts: MavenProjectFacts) -> Framework:
    """Infiere el framework por el padre o por las dependencias declaradas."""
    if facts.parent and any(h in facts.parent[1] for h in _SPRING_BOOT_HINTS):
        return "SPRING_BOOT"
    for dep in facts.dependencies:
        if any(h in dep.artifact_id for h in _SPRING_BOOT_HINTS):
            return "SPRING_BOOT"
        if any(h in dep.artifact_id for h in _QUARKUS_HINTS):
            return "QUARKUS"
        if any(h in dep.artifact_id for h in _MICRONAUT_HINTS):
            return "MICRONAUT"
    return "UNKNOWN"