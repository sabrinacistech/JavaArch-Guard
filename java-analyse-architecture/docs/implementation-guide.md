# Implementation Guide

## Prerequisitos
- JDK detectado correctamente (`java -version`).
- **Maven** en el repo (Gradle no soportado aún en el pipeline Python; ver `skills/08-validation/build-tool-adapter.md`).
- Repo compila al menos una vez sin tests (`mvn -DskipTests package`) para poblar `target/classes` y `target/generated-sources`.

## Paso a paso

### Paso 1 — Discovery
Invocar `discovery-agent`. Validar `state/build-tool-contract.json` y `state/discovery-summary.json` contra schemas.

### Paso 2 — Stack Profile
Invocar `stack-profile-agent`. Confirmar versiones de JUnit, Mockito, AssertJ, Spring, Lombok, FreeBuilder, MapStruct, Immutables, AutoValue. Si falta `target/generated-sources` con APs declarados, ejecutar build previo.

### Paso 3 — Classification
Invocar `classification-agent`. Excluir generated/config/dto puros. Score 0–100.

### Paso 4 — Symbol Contract (por SUT del primer batch)
Invocar `symbol-contract-agent` con la lista de SUTs candidatos. Salida: `state/symbol-contracts/<fqcn>.json` y `state/import-whitelist.json`.

### Paso 5 — Dependency Graph
Invocar `dependency-graph-agent`. Foco: solo métodos efectivamente invocados (anti-overstub).

### Paso 6 — Fixtures
Invocar `fixture-agent`. Crear variantes mínimas (`default`, y `boundary`/`null-optional` si modo lo requiere).

### Paso 7 — Planning
Invocar `planning-agent`. Lee JaCoCo XML, ordena por ROI, calcula tamaño de batch.

### Paso 8 — Generation
Invocar `generation-agent`. Cada test embebe `evidence-ids`. G1/G6 corren antes de compilar.

### Paso 9 — Validation
Invocar `validation-agent`. Narrow runner, parseo de errores, delta JaCoCo.

### Paso 10 — Repair (si aplica)
Invocar `repair-agent`. Matriz determinística. G7 bloquea reintentos.

### Paso 11 — Cierre del ciclo
Orchestrator evalúa G8. Si no se cumple, vuelve a Paso 7 con baseline actualizado.

### Paso 12 — Reporting final
Cuando se alcanza la condición de parada, `reporting-agent` emite el reporte con XML JaCoCo adjuntos.

## Anti-patrones a evitar
- Ejecutar `mvn clean` entre ciclos (rompe baseline y caché).
- Editar `pom.xml`/`build.gradle` sin instrucción explícita.
- Generar tests sin contrato (los gates lo impedirán; no intentarlo).
- Confiar en cobertura "estimada" sin XML.
- Reintentar el mismo fix esperando otro resultado (G7 lo bloquea).
