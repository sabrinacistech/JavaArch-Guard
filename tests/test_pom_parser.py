"""Tests del parser de pom.xml."""
from __future__ import annotations

from pathlib import Path

from gsmg.extract.pom_parser import (
    MavenDependency,
    detect_framework_maven,
    parse_pom,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample-maven-svc"


def test_parses_basic_coordinates_and_parent():
    facts = parse_pom(FIXTURE / "pom.xml")

    assert facts is not None
    assert facts.group_id == "com.example"
    assert facts.artifact_id == "order-service"
    assert facts.version == "1.0.0"
    assert facts.packaging == "jar"
    assert facts.parent == (
        "org.springframework.boot",
        "spring-boot-starter-parent",
        "3.2.0",
    )


def test_parses_dependencies_with_scope():
    facts = parse_pom(FIXTURE / "pom.xml")
    assert facts is not None

    by_artifact = {d.artifact_id: d for d in facts.dependencies}

    assert "spring-boot-starter-web" in by_artifact
    assert by_artifact["spring-boot-starter-web"].scope == "compile"

    test_dep = by_artifact.get("spring-boot-starter-test")
    assert test_dep is not None
    assert test_dep.scope == "test"

    feign = by_artifact.get("spring-cloud-starter-openfeign")
    assert feign is not None
    assert feign.version == "4.1.0"


def test_parses_properties():
    facts = parse_pom(FIXTURE / "pom.xml")
    assert facts is not None
    assert facts.properties.get("java.version") == "21"


def test_detect_framework_spring_boot_via_parent():
    facts = parse_pom(FIXTURE / "pom.xml")
    assert facts is not None
    assert detect_framework_maven(facts) == "SPRING_BOOT"


def test_invalid_pom_returns_none(tmp_path):
    bad = tmp_path / "pom.xml"
    bad.write_text("<not><valid>xml", encoding="utf-8")
    assert parse_pom(bad) is None


def test_missing_pom_returns_none(tmp_path):
    assert parse_pom(tmp_path / "nope.xml") is None


def test_aggregator_pom_lists_modules(tmp_path):
    pom = tmp_path / "pom.xml"
    pom.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
    <modelVersion>4.0.0</modelVersion>
    <groupId>com.example</groupId>
    <artifactId>aggregator</artifactId>
    <version>1.0.0</version>
    <packaging>pom</packaging>
    <modules>
        <module>service-a</module>
        <module>service-b</module>
    </modules>
</project>
""",
        encoding="utf-8",
    )
    facts = parse_pom(pom)
    assert facts is not None
    assert facts.packaging == "pom"
    assert facts.modules == ("service-a", "service-b")


def test_detect_framework_quarkus_via_dependency():
    fake = type("F", (), {})()
    fake.parent = None
    fake.dependencies = (
        MavenDependency("io.quarkus", "quarkus-arc", "3.0", "compile"),
    )
    assert detect_framework_maven(fake) == "QUARKUS"  # type: ignore[arg-type]