"""Capa de extraccion determinista (zero-LLM).

Esta capa produce hechos verificables sobre el codigo. Si un parser falla,
el archivo se omite (se reporta en `traces`) y el sistema sigue: nunca
rellena con un modelo lo que un parser no pudo extraer.
"""
from .consolidator import consolidate
from .gradle_parser import (
    GradleDependency,
    GradleProjectFacts,
    detect_framework_gradle,
    parse_gradle,
)
from .java_parser import (
    JavaAnnotation,
    JavaFileFacts,
    JavaTypeDecl,
    parse_java_file,
    parse_project,
)
from .pom_parser import (
    MavenDependency,
    MavenProjectFacts,
    detect_framework_maven,
    parse_pom,
)
from .runtime_config_parser import (
    LogbackFacts,
    RuntimeConfigFacts,
    parse_logback,
    parse_runtime_config,
)

__all__ = [
    # java
    "JavaAnnotation", "JavaFileFacts", "JavaTypeDecl",
    "parse_java_file", "parse_project",
    # maven
    "MavenDependency", "MavenProjectFacts",
    "detect_framework_maven", "parse_pom",
    # gradle
    "GradleDependency", "GradleProjectFacts",
    "detect_framework_gradle", "parse_gradle",
    # runtime
    "RuntimeConfigFacts", "LogbackFacts",
    "parse_runtime_config", "parse_logback",
    # consolidator
    "consolidate",
]