"""Tests del consolidador: integracion de todos los parsers en CodeFacts."""
from __future__ import annotations

from pathlib import Path

from gsmg.extract.consolidator import consolidate

MAVEN_FIXTURE = Path(__file__).parent / "fixtures" / "sample-maven-svc"


def test_consolidate_detects_single_maven_module():
    facts = consolidate(MAVEN_FIXTURE)

    assert len(facts["modules"]) == 1
    mod = facts["modules"][0]
    assert mod["name"] == "order-service"
    assert mod["framework"] == "SPRING_BOOT"
    assert mod["build_tool"] == "MAVEN"


def test_consolidate_indexes_annotations_per_file():
    facts = consolidate(MAVEN_FIXTURE)

    index = facts["annotations_index"]
    payment_files = [k for k in index if "PaymentClient.java" in k]
    assert payment_files, "PaymentClient.java debe estar indexado"
    annotations = index[payment_files[0]]
    names = {a["name"] for a in annotations}
    assert {"FeignClient", "CircuitBreaker", "Retry"}.issubset(names)


def test_consolidate_detects_feign_http_client_with_attributes():
    facts = consolidate(MAVEN_FIXTURE)

    clients = facts["http_clients"]
    assert len(clients) == 1
    client = clients[0]
    assert client["type"] == "FEIGN"
    assert client["service_name"] == "payments"
    assert client["class_name"] == "PaymentClient"
    assert client["module"] == "order-service"
    assert "PaymentClient.java" in client["file"]


def test_consolidate_collects_db_bindings():
    facts = consolidate(MAVEN_FIXTURE)

    bindings = facts["db_bindings"]
    kinds = {b["type"] for b in bindings}
    assert "JPA_ENTITY" in kinds
    assert "DATASOURCE" in kinds

    entity = next(b for b in bindings if b["type"] == "JPA_ENTITY")
    assert entity["class_name"] == "OrderEntity"
    assert entity["module"] == "order-service"

    ds = next(b for b in bindings if b["type"] == "DATASOURCE")
    assert ds["url"] == "jdbc:postgresql://order-db:5432/orders"


def test_consolidate_detects_structured_logging_and_mdc():
    facts = consolidate(MAVEN_FIXTURE)

    log = facts["logging_config"]
    assert log["structured"] is True
    assert "correlationId" in log["mdc_keys"]
    assert "traceId" in log["mdc_keys"]
    assert any(name == "STDOUT" for name, _ in log["appenders"])


def test_consolidate_collects_exposed_actuator_endpoints():
    facts = consolidate(MAVEN_FIXTURE)
    assert set(facts["actuator_endpoints"]) == {"health", "info", "prometheus"}


def test_consolidate_unknown_project_yields_virtual_module(tmp_path):
    # proyecto sin pom ni build.gradle: solo un .java suelto
    src = tmp_path / "Foo.java"
    src.write_text("package x; public class Foo {}", encoding="utf-8")

    facts = consolidate(tmp_path)

    assert len(facts["modules"]) == 1
    mod = facts["modules"][0]
    assert mod["framework"] == "UNKNOWN"
    assert mod["build_tool"] == "UNKNOWN"
    assert mod["name"] == tmp_path.name


def test_consolidate_builds_cross_module_imports_graph(tmp_path):
    # Dos modulos Maven; order importa una clase del paquete de payment.
    # Eso debe producir una arista order-service -> payment-service.
    def _mk_module(name: str, pkg: str) -> Path:
        mod = tmp_path / name
        (mod).mkdir(parents=True)
        (mod / "pom.xml").write_text(
            f"""<?xml version="1.0"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
    <modelVersion>4.0.0</modelVersion>
    <groupId>com.example</groupId>
    <artifactId>{name}</artifactId>
    <version>1.0.0</version>
    <packaging>jar</packaging>
</project>
""",
            encoding="utf-8",
        )
        src = mod / "src" / "main" / "java" / Path(pkg.replace(".", "/"))
        src.mkdir(parents=True)
        return src

    pay_src = _mk_module("payment-service", "com.example.payment")
    (pay_src / "PaymentEntity.java").write_text(
        "package com.example.payment; public class PaymentEntity {}",
        encoding="utf-8",
    )
    order_src = _mk_module("order-service", "com.example.order")
    (order_src / "OrderService.java").write_text(
        "package com.example.order;\n"
        "import com.example.payment.PaymentEntity;\n"
        "public class OrderService { PaymentEntity p; }",
        encoding="utf-8",
    )

    facts = consolidate(tmp_path)
    graph = facts["imports_graph"]

    assert graph.get("order-service") == ["payment-service"]
    # payment no importa nada de order: sin arista inversa (ni self-loops).
    assert "payment-service" not in graph


def test_consolidate_imports_graph_ignores_external_deps(tmp_path):
    # Un solo modulo que solo importa libs externas no genera aristas.
    facts = consolidate(MAVEN_FIXTURE)
    graph = facts["imports_graph"]
    # sample-maven-svc es un unico modulo: no puede haber dependencia inter-modulo.
    assert graph == {}


def test_consolidate_skips_aggregator_pom(tmp_path):
    # raiz con pom agregador (packaging=pom) + un submodulo real
    (tmp_path / "pom.xml").write_text(
        """<?xml version="1.0"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
    <modelVersion>4.0.0</modelVersion>
    <groupId>com.example</groupId>
    <artifactId>parent</artifactId>
    <version>1.0.0</version>
    <packaging>pom</packaging>
    <modules><module>svc-a</module></modules>
</project>
""",
        encoding="utf-8",
    )
    svc = tmp_path / "svc-a"
    svc.mkdir()
    (svc / "pom.xml").write_text(
        """<?xml version="1.0"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
    <modelVersion>4.0.0</modelVersion>
    <groupId>com.example</groupId>
    <artifactId>svc-a</artifactId>
    <version>1.0.0</version>
    <packaging>jar</packaging>
</project>
""",
        encoding="utf-8",
    )

    facts = consolidate(tmp_path)
    names = [m["name"] for m in facts["modules"]]
    assert names == ["svc-a"]