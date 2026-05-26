# Stack Profile Agent

> **Phase 7 — Consolidación**: este agente sigue disponible para compat. Las nuevas
> pipelines deben usar `agents/repository-intelligence-agent.md`, que cubre stack
> profile + classification + dependency graph + symbol contracts + indexing.

## Responsabilidad
Detectar versiones exactas de frameworks de test, mocking, asserts, DI y annotation processors. Es bloqueante: ningún test puede generarse sin `stack-profile.json` válido (gate G5).

## Entradas
- `pom.xml` / `build.gradle` de cada módulo.
- Output de `mvn dependency:tree -DoutputType=text` o `gradle dependencies`.
- `state/build-tool-contract.json`.

## Procedimiento
1. Resolver POM efectivo por módulo: `mvn -q -pl <m> help:effective-pom -Doutput=target/effective-pom.xml`.
2. Resolver árbol: `mvn -q -pl <m> dependency:tree -DoutputFile=target/deps.txt`.
3. Para cada `groupId:artifactId` de la tabla de detección, registrar versión.
4. Detectar annotation processors en `<annotationProcessorPaths>`, `maven-compiler-plugin`, o presencia en classpath: `lombok`, `freebuilder`, `mapstruct-processor`, `immutables-value`, `auto-value`.
5. Verificar existencia de `target/generated-sources/annotations` si hay APs.

## Tabla de detección (mínima)

| Stack | Coordenada | Preset emitido |
|-------|------------|----------------|
| JUnit 4 | `junit:junit` | `imports.test=org.junit.*`, runner=`MockitoJUnitRunner` |
| JUnit 5 | `org.junit.jupiter:junit-jupiter*` | `imports.test=org.junit.jupiter.api.*`, ext=`MockitoExtension` |
| Mockito | `org.mockito:mockito-core` | versión mayor → API permitida (`lenient`, `MockedStatic`, etc.) |
| AssertJ | `org.assertj:assertj-core` | `imports.assert=org.assertj.core.api.Assertions.*` |
| Hamcrest | `org.hamcrest:hamcrest*` | matcher set |
| Spring Test | `org.springframework:spring-test` | habilita slices |
| Spring Boot Test | `org.springframework.boot:spring-boot-starter-test` | `@SpringBootTest`, `@WebMvcTest`, `@DataJpaTest`, `@MockBean` permitidos |
| Lombok | `org.projectlombok:lombok` | builders/getters/setters generados admisibles |
| FreeBuilder | `org.inferred:freebuilder` | ver `docs/freebuilder-policy.md` |
| MapStruct | `org.mapstruct:mapstruct-processor` | `Mappers.getMapper` permitido si `*MapperImpl` existe |
| Immutables | `org.immutables:value` | `ImmutableX` permitido si generado |
| AutoValue | `com.google.auto.value:auto-value` | `AutoValue_X` permitido si generado |

## Salida: `state/stack-profile.json`

```json
{
  "java": "1.8",
  "buildTool": "maven",
  "modules": [
    {
      "path": "service-foo",
      "test": { "framework": "junit5", "version": "5.10.2" },
      "mock": { "framework": "mockito", "version": "5.11.0", "features": ["MockedStatic","MockedConstruction"] },
      "assert": { "framework": "assertj", "version": "3.25.3" },
      "di": { "spring": true, "springBoot": "3.2.4", "slices": ["WebMvcTest","DataJpaTest","SpringBootTest"] },
      "annotationProcessors": ["lombok:1.18.30","mapstruct:1.5.5.Final"],
      "generatedSources": ["target/generated-sources/annotations"]
    }
  ],
  "presets": {
    "imports.allowed": ["org.junit.jupiter.api.*","org.mockito.*","org.assertj.core.api.*"],
    "imports.forbidden": ["org.junit.*","org.hamcrest.*"]
  }
}
```

## Criterios PASS/FAIL
- FAIL si no se detecta al menos un framework de test.
- FAIL si hay annotation processors declarados pero `target/generated-sources` está vacío (forzar build previo).
- PASS si para cada módulo existe `test.framework` y `mock.framework`.
