# Fixture Builder Strategy (Skill — Phase 5)

## Objetivo

Determinar la estrategia de construcción de fixtures para cada tipo requerido,
usando exclusivamente evidencia verificada del contrato del SUT y del catálogo.

## Regla de oro

> El LLM **nunca** decide la estrategia de fixture por inferencia libre.
> La estrategia proviene del campo `state/symbol-contracts/<fqcn>.json → instantiation`.

---

## Árbol de decisión (determinístico)

```
¿Existe state/symbol-contracts/<fqcn>.json?
├── NO  → BLOCKED: registrar status: UNKNOWN; no generar test para este SUT
└── SÍ  → leer `instantiation.strategy`
           ├── "constructor"  → usar el constructor preferido (instantiation.preferred)
           │                    Verificar parámetros contra constructors[].params
           ├── "builder"      → ver sección BUILDERS abajo
           ├── "mock"         → Mockito.mock(Type.class) — solo colaborador pasivo
           ├── "factory"      → usar el método factory documentado en builders[].entry
           └── "unknown"      → BLOCKED: solicitar re-run del bytecode_scanner
```

---

## Estrategia por tipo de annotation processor

### FreeBuilder (`@FreeBuilder`)

Fuente de verdad: `state/symbol-contracts/<fqcn>.json → builders[kind="freebuilder"]`

```java
// ✅ CORRECTO — solo si builders[0].entry está documentado
SomeInterface fixture = new SomeInterface.Builder()
    .fieldA(value)   // verificar setter en builders[0].setters[]
    .fieldB(value)
    .build();

// ❌ INCORRECTO — nunca si builders[] está vacío o kind != "freebuilder"
new SomeInterface()  // interfaz no instanciable
SomeInterface.builder()  // no es el patrón FreeBuilder
```

Si `has_declared_builder: false` en el contrato → **mock pasivo** obligatorio:
```java
SomeInterface fixture = Mockito.mock(SomeInterface.class);
```

### Lombok `@Builder` / `@Data`

Fuente de verdad: annotation `@Builder` en `state/index/annotations.json → classes[fqcn]`
**Y** `state/stack-profile.json → annotationProcessors` incluye `lombok`.

```java
// ✅ CORRECTO
SomeClass fixture = SomeClass.builder()
    .field(value)   // verificar campo en symbol-contracts → methods[name="field" kind="builder"]
    .build();

// ❌ INCORRECTO — sin Lombok en stack-profile
SomeClass.builder()  // puede no existir en runtime
```

### Immutables / AutoValue

Usar la clase generada (`ImmutableX`, `AutoValue_X`) **solo si** existe en
`state/generated-code-index.json` y en `state/index/classes.json`.

```java
// ✅ CORRECTO — ImmutableFoo confirmado en generated-code-index.json
ImmutableFoo fixture = ImmutableFoo.builder()
    .field(value)
    .build();

// ❌ INCORRECTO — sin evidencia en generated-code-index
ImmutableFoo.builder()  // puede no haberse generado
```

### MapStruct

```java
// ✅ CORRECTO — solo si la impl existe en generated-code-index.json
XMapper mapper = Mappers.getMapper(XMapper.class);

// ❌ INCORRECTO
new XMapperImpl()  // si XMapperImpl no está en generated-code-index
```

### Sin annotation processor

Sin annotation processor confirmado en `state/stack-profile.json → annotationProcessors`:

- **Constructor directo** si `instantiation.strategy == "constructor"`.
- **Mockito mock** para colaboradores pasivos.
- **Prohibido** cualquier builder generado.

---

## Fixtures para valores límite y edge cases

Según el modo de cobertura activo (`state/execution-state.json → mode`):

| Modo             | Variantes de fixture a generar                          |
|------------------|---------------------------------------------------------|
| `coverage`       | Happy path + 1 null por parámetro nullable              |
| `branch-coverage`| Null, vacío, valor mínimo, valor máximo, valor inválido |
| `mutation-hardening` | Valores específicos que maten mutantes sobrevivientes |

Los valores exactos de límite se leen de `state/mutation-intelligence.json`
(si existe) o se derivan del tipo primitivo:
- `int/long`: 0, -1, Integer.MIN_VALUE, Integer.MAX_VALUE
- `String`: null, "", " ", string de 255 chars
- `List`: null, Collections.emptyList(), lista con 1 elemento, lista con N elementos

---

## Catálogo de fixtures (state/fixture-catalog.json)

El Fixture Catalog Agent persiste los fixtures construidos exitosamente para
reutilización en ciclos futuros. Formato por entrada:

```json
{
  "fqcn": "com.acme.Foo",
  "strategy": "constructor",
  "evidenceId": "ctor:com.acme.Foo:a1b2",
  "cycleSafe": true,
  "code": "new Foo(\"arg1\", 42)",
  "variants": [
    { "label": "null_name", "code": "new Foo(null, 42)" }
  ]
}
```

`cycleSafe: true` indica que la fixture no tiene dependencias circulares.
Consultar `state/fixture-catalog.json` **antes** de construir una nueva fixture.

---

## Anti-patrones

| Anti-patrón                                         | Causa                                      |
|-----------------------------------------------------|--------------------------------------------|
| `new SomeInterface()`                               | Interfaces no son instanciables            |
| `mock(X.class)` como SUT (no como colaborador)      | El SUT debe ser real para tener cobertura  |
| `SomeClass.builder()` sin Lombok en stack-profile   | Builder generado puede no existir          |
| Inventar setters del builder                        | Solo setters documentados en el contrato   |
| Fixture distinta por cada test del mismo SUT        | Usar catálogo para consistencia            |
| Fixtures con estado mutable compartido entre tests  | Deben declararse en `@BeforeEach`          |
