"""Parser Java determinista basado en javalang.

Por que javalang:
- Pure Python, sin dependencias nativas (instalable en Windows sin toolchain).
- AST tipado: clases, interfaces, enums, anotaciones con `position` (linea).
- Suficiente para extraer los hechos que necesita GSMG (anotaciones,
  imports, firmas publicas). Para analisis de cuerpo de metodos mas
  profundo migraremos a tree-sitter en fases posteriores.

Regla anti-alucinacion: si el archivo no parsea, devolvemos None. NUNCA
caemos a una heuristica de regex ni a un LLM para "intentar entenderlo".
El sistema aguas abajo debe poder distinguir "no se pudo parsear" de
"se parseo y no hay nada".
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import javalang
from javalang.tree import (
    ClassDeclaration,
    EnumDeclaration,
    InterfaceDeclaration,
    MethodDeclaration,
)

_IGNORE_DIRS_DEFAULT: frozenset[str] = frozenset({
    "target", "build", "out", ".git", "node_modules", ".gradle", ".idea",
})


@dataclass(frozen=True)
class JavaAnnotation:
    """Anotacion encontrada en una declaracion.

    `attributes` guarda la representacion textual de los pares clave/valor
    que aparecen en la anotacion (`@FeignClient(name = "payments")` ->
    `{"name": "payments"}`). Conservamos texto crudo a proposito: los
    skills decidiran como interpretarlo segun la anotacion.
    """

    name: str
    target_kind: str  # "TYPE" | "METHOD" | "FIELD"
    target_name: str
    attributes: dict[str, str]
    line: int


@dataclass(frozen=True)
class JavaTypeDecl:
    """Declaracion de tipo de primer nivel en un archivo."""

    kind: str  # "class" | "interface" | "enum"
    name: str
    modifiers: frozenset[str]
    line: int


@dataclass(frozen=True)
class JavaFileFacts:
    """Hechos extraidos de un unico archivo .java."""

    path: str
    package: str
    imports: tuple[str, ...]
    types: tuple[JavaTypeDecl, ...]
    annotations: tuple[JavaAnnotation, ...]
    public_methods: tuple[str, ...]
    loc: int


# --------------------------------------------------------------------------- #
# Helpers internos
# --------------------------------------------------------------------------- #
_KIND_BY_NODE: dict[type, str] = {
    ClassDeclaration: "class",
    InterfaceDeclaration: "interface",
    EnumDeclaration: "enum",
}


def _literal_value(node: Any) -> str | None:
    """Reduce un nodo de expresion de javalang a su representacion textual.

    Cubre los casos mas comunes en atributos de anotacion: Literal, MemberReference,
    Annotation anidada. Para nodos no soportados devuelve None: prefiero ausencia
    de dato a inventarlo.
    """
    if node is None:
        return None
    # Literal: "payments", 5, true, etc. javalang guarda el token crudo con comillas.
    value = getattr(node, "value", None)
    if isinstance(value, str):
        # Quitar comillas de string literals: '"payments"' -> 'payments'.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            return value[1:-1]
        return value
    # MemberReference: PaymentClient.class -> "PaymentClient"
    member = getattr(node, "member", None)
    if member is not None:
        return str(member)
    # Annotation anidada: @CircuitBreaker(name="x") -> "@CircuitBreaker"
    name = getattr(node, "name", None)
    if name is not None:
        return f"@{name}"
    return None


def _annotation_attrs(annotation: Any) -> dict[str, str]:
    """Extrae los pares clave/valor de una anotacion.

    Soporta las tres formas:
    - marcador: @Override -> {}
    - valor unico: @Foo("bar") -> {"value": "bar"}
    - pares: @FeignClient(name = "x", url = "y") -> {"name": "x", "url": "y"}
    """
    element = getattr(annotation, "element", None)
    if element is None:
        return {}

    pairs = element if isinstance(element, list) else [element]
    out: dict[str, str] = {}
    for pair in pairs:
        # ElementValuePair tiene .name y .value; un valor suelto solo .value/expr.
        name = getattr(pair, "name", None) or "value"
        value_node = getattr(pair, "value", pair)
        text = _literal_value(value_node)
        if text is not None:
            out[name] = text
    return out


def _line_of(node: Any, default: int = 0) -> int:
    pos = getattr(node, "position", None)
    return pos.line if pos is not None else default


def _walk_body(body: Any):
    """Itera miembros de un cuerpo de tipo (clase/interface/enum).

    EnumDeclaration en javalang envuelve su cuerpo en EnumBody con `.declarations`;
    el resto tiene una lista directa. Unificamos aqui.
    """
    if body is None:
        return
    declarations = getattr(body, "declarations", body)
    if not isinstance(declarations, list):
        return
    yield from declarations


# --------------------------------------------------------------------------- #
# API publica
# --------------------------------------------------------------------------- #
def parse_java_file(path: str | Path) -> JavaFileFacts | None:
    """Parsea un archivo Java a JavaFileFacts.

    Devuelve None si:
    - el archivo no se puede leer
    - el contenido no es Java valido (sintaxis o lexer)
    """
    p = Path(path)
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    try:
        tree = javalang.parse.parse(content)
    except (javalang.parser.JavaSyntaxError, javalang.tokenizer.LexerError):
        return None
    except Exception:  # noqa: BLE001 — javalang lanza varios tipos no documentados
        return None

    package = tree.package.name if tree.package else "(default)"
    imports = tuple(imp.path for imp in (tree.imports or ()))

    types: list[JavaTypeDecl] = []
    annotations: list[JavaAnnotation] = []
    public_methods: list[str] = []

    for tdecl in (tree.types or ()):
        kind = _KIND_BY_NODE.get(type(tdecl), "unknown")
        type_line = _line_of(tdecl)
        types.append(JavaTypeDecl(
            kind=kind,
            name=tdecl.name,
            modifiers=frozenset(tdecl.modifiers or ()),
            line=type_line,
        ))

        for ann in (tdecl.annotations or ()):
            annotations.append(JavaAnnotation(
                name=ann.name,
                target_kind="TYPE",
                target_name=tdecl.name,
                attributes=_annotation_attrs(ann),
                line=_line_of(ann, type_line),
            ))

        for member in _walk_body(getattr(tdecl, "body", None)):
            if not isinstance(member, MethodDeclaration):
                continue
            modifiers = member.modifiers or set()
            if "public" in modifiers:
                public_methods.append(member.name)
            for ann in (member.annotations or ()):
                annotations.append(JavaAnnotation(
                    name=ann.name,
                    target_kind="METHOD",
                    target_name=member.name,
                    attributes=_annotation_attrs(ann),
                    line=_line_of(ann, _line_of(member)),
                ))

    return JavaFileFacts(
        path=str(p),
        package=package,
        imports=imports,
        types=tuple(types),
        annotations=tuple(annotations),
        public_methods=tuple(public_methods),
        loc=content.count("\n") + 1,
    )


def parse_project(
    project_path: str | Path,
    ignore_dirs: frozenset[str] = _IGNORE_DIRS_DEFAULT,
) -> list[JavaFileFacts]:
    """Escanea recursivamente un proyecto y parsea sus archivos .java.

    Los archivos que no parsean se OMITEN silenciosamente: la capa
    determinista no debe producir hallazgos falsos. La traza de
    archivos saltados se reportara en niveles superiores.
    """
    root = Path(project_path)
    facts: list[JavaFileFacts] = []
    for p in root.rglob("*.java"):
        if any(part in ignore_dirs for part in p.parts):
            continue
        result = parse_java_file(p)
        if result is not None:
            facts.append(result)
    return facts