"""Tests de la capa de extraccion determinista.

Verifican el contrato basico del parser javalang: que extrae paquete,
imports, anotaciones de tipo y de metodo con sus atributos, y que
falla silenciosamente (None) ante codigo invalido o archivos ilegibles.
"""
from __future__ import annotations

from pathlib import Path

from gsmg.extract.java_parser import parse_java_file, parse_project

FIXTURE = Path(__file__).parent / "fixtures" / "sample-svc"


def test_parses_spring_boot_main_class():
    facts = parse_java_file(FIXTURE / "OrderApplication.java")

    assert facts is not None
    assert facts.package == "com.example.order"
    assert "org.springframework.boot.autoconfigure.SpringBootApplication" in facts.imports
    assert "main" in facts.public_methods

    type_decl = facts.types[0]
    assert type_decl.kind == "class"
    assert type_decl.name == "OrderApplication"
    assert "public" in type_decl.modifiers

    spring_boot = next(a for a in facts.annotations if a.name == "SpringBootApplication")
    assert spring_boot.target_kind == "TYPE"
    assert spring_boot.target_name == "OrderApplication"


def test_parses_feign_client_interface_with_attributes():
    facts = parse_java_file(FIXTURE / "PaymentClient.java")

    assert facts is not None
    assert facts.package == "com.example.order.client"

    type_decl = facts.types[0]
    assert type_decl.kind == "interface"
    assert type_decl.name == "PaymentClient"

    feign = next(a for a in facts.annotations if a.name == "FeignClient")
    assert feign.target_kind == "TYPE"
    assert feign.target_name == "PaymentClient"
    assert feign.attributes.get("name") == "payments"
    assert feign.attributes.get("url") == "${payments.url}"


def test_extracts_method_level_resilience_annotations():
    facts = parse_java_file(FIXTURE / "PaymentClient.java")
    assert facts is not None

    method_annotations = [a for a in facts.annotations if a.target_kind == "METHOD"]
    by_name = {a.name: a for a in method_annotations}

    assert "CircuitBreaker" in by_name
    assert by_name["CircuitBreaker"].target_name == "charge"
    assert by_name["CircuitBreaker"].attributes.get("name") == "payments"

    assert "Retry" in by_name
    assert by_name["Retry"].target_name == "charge"


def test_project_scan_finds_all_java_files():
    files = parse_project(FIXTURE)

    names = {Path(f.path).name for f in files}
    assert names == {"OrderApplication.java", "PaymentClient.java"}


def test_project_scan_ignores_build_dirs(tmp_path):
    src = tmp_path / "src" / "Foo.java"
    target = tmp_path / "target" / "Generated.java"
    src.parent.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    src.write_text("package a; public class Foo {}", encoding="utf-8")
    target.write_text("package a; public class Generated {}", encoding="utf-8")

    files = parse_project(tmp_path)

    paths = {Path(f.path).name for f in files}
    assert paths == {"Foo.java"}


def test_invalid_java_returns_none(tmp_path):
    bad = tmp_path / "Broken.java"
    bad.write_text("this is not valid java !!!", encoding="utf-8")

    assert parse_java_file(bad) is None


def test_missing_file_returns_none(tmp_path):
    assert parse_java_file(tmp_path / "does_not_exist.java") is None
