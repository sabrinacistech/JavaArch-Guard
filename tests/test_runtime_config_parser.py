"""Tests del parser de configuracion runtime (yaml/properties/logback)."""
from __future__ import annotations

from pathlib import Path

from gsmg.extract.runtime_config_parser import (
    parse_logback,
    parse_runtime_config,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample-maven-svc" / "src" / "main" / "resources"


def test_parses_application_yaml_server_and_actuator():
    cfg = parse_runtime_config(FIXTURE / "application.yml")

    assert cfg is not None
    assert cfg.server_port == 8080
    assert set(cfg.actuator_endpoints_exposed) == {"health", "info", "prometheus"}


def test_parses_datasource_url():
    cfg = parse_runtime_config(FIXTURE / "application.yml")
    assert cfg is not None
    assert cfg.datasource_url == "jdbc:postgresql://order-db:5432/orders"


def test_extracts_feign_client_names_excluding_default():
    cfg = parse_runtime_config(FIXTURE / "application.yml")
    assert cfg is not None
    # `default` se omite explicitamente; solo nos quedamos con instancias reales
    assert cfg.feign_client_names == ("payments",)


def test_extracts_resilience4j_circuit_breaker_instances():
    cfg = parse_runtime_config(FIXTURE / "application.yml")
    assert cfg is not None
    assert cfg.resilience4j_circuit_breakers == ("payments",)


def test_parses_properties_file_fallback(tmp_path):
    f = tmp_path / "application.properties"
    f.write_text(
        "server.port=9090\n"
        "spring.datasource.url=jdbc:h2:mem:test\n"
        "# comentario\n"
        "logging.level.root=DEBUG\n",
        encoding="utf-8",
    )
    cfg = parse_runtime_config(f)
    assert cfg is not None
    assert cfg.server_port == 9090
    assert cfg.datasource_url == "jdbc:h2:mem:test"
    assert cfg.logging_level_root == "DEBUG"


def test_unknown_extension_returns_none(tmp_path):
    f = tmp_path / "config.txt"
    f.write_text("server.port=8080", encoding="utf-8")
    assert parse_runtime_config(f) is None


def test_logback_detects_structured_encoder():
    lb = parse_logback(FIXTURE / "logback-spring.xml")

    assert lb is not None
    assert lb.has_structured_encoder is True
    assert ("STDOUT", "ch.qos.logback.core.ConsoleAppender") in lb.appenders
    assert "correlationId" in lb.mdc_keys
    assert "traceId" in lb.mdc_keys


def test_logback_text_pattern_extracts_mdc_keys(tmp_path):
    f = tmp_path / "logback.xml"
    f.write_text(
        """<?xml version="1.0"?>
<configuration>
  <appender name="STDOUT" class="ch.qos.logback.core.ConsoleAppender">
    <encoder>
      <pattern>%d [%thread] %X{requestId} %X{userId} %msg%n</pattern>
    </encoder>
  </appender>
</configuration>
""",
        encoding="utf-8",
    )
    lb = parse_logback(f)
    assert lb is not None
    assert lb.has_structured_encoder is False
    assert "requestId" in lb.mdc_keys
    assert "userId" in lb.mdc_keys


def test_logback_invalid_returns_none(tmp_path):
    f = tmp_path / "logback.xml"
    f.write_text("<not><valid>xml", encoding="utf-8")
    assert parse_logback(f) is None