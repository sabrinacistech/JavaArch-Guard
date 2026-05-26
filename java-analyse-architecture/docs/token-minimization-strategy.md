# Token Minimization Strategy

## Objetivo

Reducir el consumo de tokens LLM al mínimo necesario sin sacrificar calidad ni
determinismo. Cada token que no llega al LLM es un token que no puede generar
alucinaciones.

---

## Regla 1 — Context Pack como única entrada al LLM

El agente LLM **solo recibe** el archivo `state/context-packs/<fqcn>.json`
producido por `context_pack_builder.py`. Este archivo es una rebanada curada
que incluye exactamente lo necesario para un SUT.

**Prohibido enviar al LLM:**

| Archivo | Por qué está prohibido |
|---------|------------------------|
| `pom.xml` completo | Hasta 2000 líneas; el agente solo necesita `stack-profile.json` |
| `jacoco.xml` completo | Hasta 50K líneas; el agente solo necesita `coverage-targets.json` |
| Stack traces crudos | No estructurados; el agente solo necesita `compile-error-index.json` |
| `.java` de producción | El agente no necesita código fuente; solo los contratos de bytecode |
| `import-whitelist.json` completo | El context-pack incluye solo los imports relevantes al SUT |
| `symbol-contracts.json` (manifiesto) | No contiene definiciones; enviar el contrato del SUT específico |

---

## Regla 2 — Estructura del Context Pack

El context pack es un JSON que contiene exactamente:

```json
{
  "schemaVersion": 1,
  "generatedAt": "2026-05-26T10:00:00Z",
  "sut": {
    "fqcn": "com.acme.FooService",
    "kind": "class",
    "constructors": [...],
    "methods": [...],
    "builders": [...]
  },
  "stack": {
    "testFramework": "junit5",
    "mockFramework": "mockito",
    "assertFramework": "assertj",
    "mockitoInline": false,
    "springTest": false
  },
  "template": "junit5-mockito",
  "collaborators": [
    {
      "field": "fooRepository",
      "type": "com.acme.FooRepository",
      "injection": "constructor",
      "methods": [...]
    }
  ],
  "fixtures": [...],
  "coverageTargets": {
    "missedLines": 45,
    "missedBranches": 12,
    "priority": "HIGH"
  },
  "allowedImports": [
    "org.junit.jupiter.api.Test",
    "org.mockito.Mock",
    "org.assertj.core.api.Assertions"
  ],
  "existingTests": ["testDoFoo_happyPath"],
  "failureMemory": []
}
```

**El context pack NO incluye:**
- Código fuente del SUT (solo contratos derivados de bytecode)
- Todos los métodos del classpath (solo los del SUT y sus colaboradores directos)
- Historia de ciclos anteriores (solo `failureMemory` para evitar loops)
- JaCoCo XML (solo los contadores numéricos en `coverageTargets`)

---

## Regla 3 — Presupuesto de tokens por agente

| Agente | Input máximo | Output máximo |
|--------|-------------|---------------|
| Body Agent (generación) | 4K tokens | 2K tokens (JSON de métodos) |
| Repair Agent (reparación) | 2K tokens | 1K tokens (JSON de parches) |
| Classification Agent | 3K tokens | 1K tokens |
| Symbol Contract Agent | 4K tokens | 2K tokens |

Si el context pack supera estos límites, `context_pack_builder.py` aplica reducción:
1. Truncar `methods[]` al SUT al subconjunto de métodos sin cobertura (`missedLines > 0`).
2. Truncar `collaborators[].methods[]` a los métodos efectivamente usados en el SUT.
3. Omitir `fixtures[]` si ya hay un constructor directo disponible.

---

## Regla 4 — El LLM produce JSON, no Java

El agente **nunca** produce código Java directamente. Produce un JSON de
intención estructurada:

```json
{
  "schemaVersion": 1,
  "patchId": "patch:abc123def456",
  "cycle": 1,
  "sut": "com.acme.FooService",
  "testClass": "com.acme.FooServiceTest",
  "testPackage": "com.acme",
  "template": "junit5-mockito",
  "targetModule": "my-module",
  "allowedImports": ["org.junit.jupiter.api.Test"],
  "fields": [
    {"annotation": "@Mock", "type": "FooRepository", "name": "fooRepository"}
  ],
  "methods": [
    {
      "name": "testDoFoo_happyPath",
      "annotations": ["@Test"],
      "body": "// arrange\nwhen(fooRepository.findById(1L)).thenReturn(Optional.of(new Foo()));\n// act\nString result = sut.doFoo(1L);\n// assert\nassertThat(result).isEqualTo(\"expected\");",
      "evidenceIds": ["sym:com.acme.FooService#doFoo:e7a1"]
    }
  ]
}
```

Este JSON es transformado en código Java por `test_patch_applier.py` —
una herramienta determinista que no alucina.

**Ventajas de este modelo:**
- El LLM no necesita saber la indentación exacta del archivo destino.
- La lógica de colisión de firmas (método ya existe) la maneja el patcher.
- Los imports se validan contra `import-whitelist.json` antes de ser escritos.
- El `patchId` proporciona trazabilidad completa del origen de cada método.

---

## Regla 5 — Copilot y entornos VS Code

Copilot en VS Code opera con el mismo principio: no se le pasan archivos completos.
Ver `.github/copilot-instructions.md` sección "Token minimization rules".

Copilot **no es un escritor de archivos**. Sus sugerencias son revisadas por
`test_linter.py` antes de ser aceptadas, y si se aceptan, se materializan
mediante `test_patch_applier.py` con un patch JSON explícito.

---

## Métricas de referencia

| Práctica prohibida | Costo estimado | Alternativa |
|-------------------|----------------|-------------|
| Enviar `pom.xml` completo | ~1500-3000 tokens | `stack-profile.json`: ~200 tokens |
| Enviar `jacoco.xml` completo | ~10000-50000 tokens | `coverage-targets.json`: ~100 tokens |
| Enviar stack trace crudo | ~500-2000 tokens | `compile-error-index.json`: ~150 tokens |
| Enviar `.java` fuente completo | ~2000-8000 tokens | `context-pack.json`: ~800-1500 tokens |
| Enviar todos los contratos | ~5000-20000 tokens | Context pack del SUT: ~400-800 tokens |
