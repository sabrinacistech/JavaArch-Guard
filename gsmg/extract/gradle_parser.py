"""Parser de build.gradle (Groovy DSL).

F2 usa extraccion por regex: suficiente para detectar plugins y dependencias
en la mayoria de proyectos Gradle reales. Soporta build.gradle y build.gradle.kts
(la diferencia sintactica para lo que nos interesa es minima).

Para configuraciones complejas (closures dinamicos, `dependencies { }` anidados,
versionado via catalogs) este parser se queda corto a proposito; en esos casos
el Supervisor delegara al LLM-router para clasificar el proyecto.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..state import Framework


@dataclass(frozen=True)
class GradleDependency:
    configuration: str  # "implementation", "api", "testImplementation", ...
    coordinate: str     # "group:artifact:version" o "group:artifact"


@dataclass(frozen=True)
class GradleProjectFacts:
    plugins: tuple[str, ...]
    dependencies: tuple[GradleDependency, ...]


_PLUGIN_RE = re.compile(r"""(?:^|\n)\s*id\s*\(?\s*['"]([^'"]+)['"]""", re.M)
_DEP_RE = re.compile(
    r"""(?:^|\n)\s*(\w+)\s*\(?\s*['"]([^'"]+)['"]""", re.M,
)
_VALID_CONFIGS = frozenset({
    "implementation", "api", "compileOnly", "runtimeOnly",
    "testImplementation", "testCompileOnly", "testRuntimeOnly",
    "annotationProcessor", "testAnnotationProcessor", "developmentOnly",
})


def parse_gradle(path: str | Path) -> GradleProjectFacts | None:
    """Parsea un build.gradle / build.gradle.kts. None si no se puede leer."""
    p = Path(path)
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    plugins = tuple(_PLUGIN_RE.findall(content))

    deps: list[GradleDependency] = []
    for m in _DEP_RE.finditer(content):
        config, coord = m.group(1), m.group(2)
        if config not in _VALID_CONFIGS:
            continue
        if ":" not in coord:  # filtra strings que no son coordenadas
            continue
        deps.append(GradleDependency(configuration=config, coordinate=coord))

    return GradleProjectFacts(plugins=plugins, dependencies=tuple(deps))


def detect_framework_gradle(facts: GradleProjectFacts) -> Framework:
    """Infiere framework por plugins o por dependencias declaradas."""
    for plugin in facts.plugins:
        if plugin.startswith("org.springframework.boot"):
            return "SPRING_BOOT"
        if plugin.startswith("io.quarkus"):
            return "QUARKUS"
        if plugin.startswith("io.micronaut"):
            return "MICRONAUT"
    for dep in facts.dependencies:
        if "spring-boot-starter" in dep.coordinate:
            return "SPRING_BOOT"
        if dep.coordinate.startswith("io.quarkus:"):
            return "QUARKUS"
        if dep.coordinate.startswith("io.micronaut:"):
            return "MICRONAUT"
    return "UNKNOWN"