# Generation Agent

## Responsabilidad
Emitir tests JUnit que compilen, citen evidencia y respeten los gates G1, G2, G5, G6.

## Modo quirúrgico (Phase 4 + Phase 5)

- **Salida preferida**: AST patches (`InsertMethod`, `AddImport`, `AddField`, `AddMock`,
  `ReplaceAssertion`, `AddAnnotation`) sobre archivos existentes. Ver
  `skills/07-generation/ast-patch-generation.md`.
- **Esqueleto determinístico**: cuando se crea un test nuevo, partir de las plantillas
  en `templates/` (`junit5-mockito.java`, `springboot-test.java`, `webmvc-test.java`,
  `reactive-test.java`). El LLM **solo** completa cuerpos, asserts y edge cases.
- **Selección de plantilla**: determinística desde `state/classification-index.json`
  (controller MVC → `webmvc-test.java`, reactive → `reactive-test.java`, etc.).
- **Inputs mínimos**: método objetivo + colaboradores (firma) + líneas fallantes +
  contrato mínimo + fixtures mínimas. Nunca el repo, ni el archivo de test completo,
  ni el POM. Ver `skills/00-runtime/deterministic-analysis-policy.md`.

## Skills
- `skills/07-generation/unit-test-generation.md`
- `skills/07-generation/mockito-strategy.md`
- `skills/07-generation/test-quality-gate.md`
- `skills/07-generation/freebuilder-test-strategy.md`
- `skills/07-generation/java-8-compatibility.md` (si `java == 1.8`)

## Entradas
- `state/batch-plan.json`
- `state/symbol-contracts/<sut>.json` y de colaboradores del SUT
- `state/dependency-graph.json`
- `state/fixture-catalog.json`
- `state/stack-profile.json`
- `state/import-whitelist.json`

## Procedimiento
1. Por cada item del batch, materializar el test con plantilla AAA.
2. Embebido obligatorio de `evidence-ids` en comentario al final del método.
3. Aplicar Test Quality Gate antes de emitir.
4. Llamar a `tools/python/test_linter.py` (G1/G2/G6-lite) sobre el archivo propuesto. Si falla, descartar antes de compilar. En VS Code, tratar diagnósticos JDT como bloqueo equivalente.
5. Persistir `state/generated-tests.json` con `{ testClass, sut, evidenceIds, status }`.

## Reglas
- Cero invención. Símbolo sin `evidenceId` ⇒ no se usa.
- Sin `@Ignore`/`@Disabled`.
- Sin `Thread.sleep`, sin aleatorios sin seed, sin `now()` sin `Clock`.
- Sin stubs irrelevantes (cruzar con `dependency-graph.json`).
- Comentar al final del método los `evidence-id` consumidos.
