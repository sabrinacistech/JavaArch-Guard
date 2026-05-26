# Repair Agent

## Responsabilidad
Aplicar reparaciones determinísticas según causa raíz parseada. Respeta G7 (failure-memory).

## Política determinística (Phase 2 + Phase 6)

Orden estricto:

1. **Repair determinístico** vía `repair-rules/*.rules` (Phase 6). El LLM **no** interviene.
2. **Recompilación incremental** del test afectado (Phase 3).
3. **LLM fallback** únicamente si (1) no resolvió y el error no está en `failure-memory.json` como FAILED.

El LLM **no** parsea `compile-error-index.json` ni stack traces: consume causa ya parseada (`{ errorCode, symbolFQN, file, line, suggestedRule }`).

Ver `skills/00-runtime/deterministic-analysis-policy.md`.

## Skills
- `skills/09-repair/repair-decision-matrix.md`
- `skills/09-repair/failure-memory.md`
- `skills/09-repair/retry-policy.md`

## Entradas
- `state/compile-error-index.json`
- `state/symbol-contracts/*.json` (para reemplazos verificados)
- `state/import-whitelist.json`
- `state/failure-memory.json`

## Procedimiento
1. **Determinístico primero (Phase 6)**: para cada `compile-error-index.json[*]`,
   buscar regla en `repair-rules/*.rules` por código/patrón. Si matchea, aplicar
   acción vía `tools/python/ast_patcher.py` (herramienta existente, fail-closed: solo `addImport`/`removeImport` seguros) y saltar al paso 4.
2. Si no hay regla determinística, derivar `fixId` candidato desde
   `repair-decision-matrix.md`.
3. Calcular `hash(errorCode, symbolFQN, fixId)`; si está marcado `FAILED` en
   `failure-memory.json` ⇒ G7 prohíbe el fix.
4. Aplicar fix (editar archivo de test). Re-correr G1 + G6 antes de pedir nueva
   compilación.
5. Recompilar **scope incremental** (`-pl <m> -Dtest=<one>`) — ver Phase 3.
6. Registrar resultado en `failure-memory.json`.
7. Máximo 2 intentos determinísticos por test. Si persiste → fallback LLM
   solo si la regla aplicada fue `escalateToLLM(<reason>)`.

## Salidas
- Tests reparados o descartados.
- `state/failure-memory.json` actualizado.

## Reglas
- Nunca inventar símbolos para "reparar".
- Nunca silenciar tests (`@Ignore`/`@Disabled`).
- Nunca bajar asserts para forzar pase.
