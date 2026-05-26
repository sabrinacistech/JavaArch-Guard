# Unit Test Generation

## Objetivo
Emitir tests JUnit que compilen y citen evidencia. Cero invención de símbolos.

## Precondiciones
- `state/stack-profile.json` válido (gate G5).
- `state/import-whitelist.json` actualizado (gate G1).
- `state/symbol-contracts/<sut>.json` y contratos de colaboradores presentes (gate G2).
- `state/fixture-catalog.json` poblado para los tipos requeridos.

## Procedimiento
1. Tomar objetivo de `state/batch-plan.json`: `{sut, method, branchId?, mutationId?}`.
2. Resolver firma del método desde el contrato y colaboradores desde `dependency-graph.json`.
3. Seleccionar fixtures de `fixture-catalog.json`. Si falta fixture obligatorio ⇒ abortar el objetivo (no improvisar).
4. Construir test con plantilla AAA:
   - **Arrange**: declarar mocks (`@Mock`), fixtures (`Type.builder()...build()`), inyección (`@InjectMocks` o constructor explícito según `dependency-graph.json`).
   - **Act**: una sola invocación al método objetivo.
   - **Assert**: usar lib del `stack-profile` (`AssertJ` si presente, `JUnit assertions` si no). Incluir asserts de retorno y verificación de interacciones relevantes.
5. Emitir el archivo en la misma estructura de paquete bajo `src/test/java`.
6. Anexar bloque de cita al final del método de test:
   ```java
   // evidence-ids:
   //   sym:com.acme.FooService#calc(java.math.BigDecimal):e7a1
   //   ctor:com.acme.FooService(com.acme.Repo):2b3d
   //   builder:com.acme.Order:lombok:a91c
   ```

## Reglas
- Un test por escenario (happy / branch / exception).
- Nombrado: `should<Behavior>_when<Condition>` o `methodName_condition_expected`.
- Prohibido `Thread.sleep`, `System.out`, fechas no fijas, aleatorios sin seed.
- Prohibido `@Ignore`/`@Disabled` salvo decisión registrada en `state/batch-plan.json`.
- Sin imports wildcard salvo los del preset emitido por stack-profile.
- Stubs solo para métodos que el SUT realmente invoca según `dependency-graph.json`.
