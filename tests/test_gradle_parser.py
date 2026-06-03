"""Tests del parser de build.gradle."""
from __future__ import annotations

from pathlib import Path

from gsmg.extract.gradle_parser import detect_framework_gradle, parse_gradle

FIXTURE = Path(__file__).parent / "fixtures" / "sample-gradle-svc"


def test_extracts_plugins():
    facts = parse_gradle(FIXTURE / "build.gradle")
    assert facts is not None
    assert "java" in facts.plugins
    assert "org.springframework.boot" in facts.plugins


def test_extracts_dependencies_by_configuration():
    facts = parse_gradle(FIXTURE / "build.gradle")
    assert facts is not None

    impls = [d.coordinate for d in facts.dependencies if d.configuration == "implementation"]
    tests = [d.coordinate for d in facts.dependencies if d.configuration == "testImplementation"]

    assert "org.springframework.boot:spring-boot-starter-web" in impls
    assert "org.springframework.cloud:spring-cloud-starter-openfeign:4.1.0" in impls
    assert "org.springframework.boot:spring-boot-starter-test" in tests


def test_detects_spring_boot_via_plugin():
    facts = parse_gradle(FIXTURE / "build.gradle")
    assert facts is not None
    assert detect_framework_gradle(facts) == "SPRING_BOOT"


def test_skips_non_dependency_strings(tmp_path):
    f = tmp_path / "build.gradle"
    f.write_text(
        """
        plugins { id 'java' }
        group = 'com.example'
        version = '1.0.0'
        dependencies {
            implementation 'org.x:y:1.0'
        }
        """,
        encoding="utf-8",
    )
    facts = parse_gradle(f)
    assert facts is not None
    # `group` y `version` no estan en _VALID_CONFIGS -> no aparecen como deps
    coords = {d.coordinate for d in facts.dependencies}
    assert coords == {"org.x:y:1.0"}