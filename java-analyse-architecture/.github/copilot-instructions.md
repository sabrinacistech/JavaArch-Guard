# GitHub Copilot Workspace Instructions
# Java Test Coverage Agent — Anti-Hallucination Rules

> **IMPORTANT**: These instructions apply to ALL Copilot suggestions in this workspace.
> They enforce the same gates (G1–G9) as the LLM agent pipeline.
> Violating these rules produces tests that fail to compile or introduce hallucinated symbols.

---

## ABSOLUTE PROHIBITIONS — never do these

### 1. No invented imports (G1 — Import Whitelist)

- **NEVER** suggest an import that does not appear in `state/import-whitelist.json`
  (`packages[]` or `classes[]`) or `state/index/imports.json`.
- Do NOT infer imports from class names, training data, conventions, or "what seems right."
- If an import cannot be verified → **omit it** and leave a placeholder:
  ```java
  // TODO: verify import in state/import-whitelist.json
  // import com.acme.SomeClass;
  ```

### 2. No uninspected symbols (G2 — Symbol Evidence)

- Every `new X(...)`, `X.staticMethod(...)`, `obj.method(...)` MUST have an entry in
  `state/symbol-contracts/<fqcn>.json` (the per-class contract file) or `state/index/methods.json`.
- **`state/symbol-contracts.json` is a manifest/index only** — it lists which contracts exist
  but does NOT contain constructor or method definitions.
  The authoritative contracts are at `state/symbol-contracts/<fqcn>.json`.
- If a constructor or method is not in the contract → **do not generate it**.
  Use Mockito as fallback **only if `state/stack-profile.json` confirms Mockito is available**:
  ```java
  SomeType dep = Mockito.mock(SomeType.class);
  // TODO: verify symbol in state/symbol-contracts/com.acme.SomeType.json
  ```
- Do NOT mock final classes unless `state/stack-profile.json` declares `mockito-inline`
  or an equivalent inline mock capability.

### 3. No interface or abstract class instantiation

- **NEVER** write `new SomeInterface()` or `new AbstractSomething()`.
- For FreeBuilder interfaces: use `new InterfaceName.Builder()` **only if** the contract
  `state/symbol-contracts/<fqcn>.json` contains a builder entry with `new InterfaceName.Builder()`.
- For unknown or abstract types: use `Mockito.mock(Type.class)` only if Mockito is
  confirmed in `state/stack-profile.json`.

### 4. No invented builders, factories, or setters (G2 — FreeBuilder guard)

- **NEVER** write `new TypeName_Builder()` or `new TypeName_Builder(...)`.
  The direct generated class (`Type_Builder`) is an internal detail and must not be used directly.
- The only allowed FreeBuilder form is `new TypeName.Builder()` — and only when the contract
  confirms it with a `builders[]` entry containing `new TypeName.Builder()`.
- **NEVER** call a setter on a builder (`.setField(x)`, `.setPersonCommonData(...)`, etc.)
  unless that setter name appears explicitly in `state/symbol-contracts/<fqcn>.json`
  under `builders[].setters[]`.
- **NEVER** invent setter names. If a setter is not listed in the contract, the field
  may not be settable or may use a different API.
- Do NOT use Lombok-style fluent builders (`.builder().field(x).build()`) unless
  `@Builder` is confirmed in `state/symbol-contracts/<fqcn>.json` → `instantiation`.
- Do NOT use `Mappers.getMapper(X.class)` unless the generated implementation is confirmed
  in `state/symbol-contracts/<fqcn>.json`.

### 5. No framework features absent from the stack (G5 — Stack Profile)

Always read `state/stack-profile.json` before using any framework annotation or class.
Specific rules:

| Framework / feature | Only use if `state/stack-profile.json` declares… |
|---------------------|--------------------------------------------------|
| `org.junit.jupiter.*` (JUnit 5) | JUnit 5 or `junit-jupiter` |
| `org.junit.*` (JUnit 4) | JUnit 4 or `junit` |
| `@ExtendWith(MockitoExtension.class)`, `@Mock` | Mockito available |
| `Mockito.mockStatic(...)` | `mockito-inline` or equivalent |
| `@RunWith(PowerMockRunner.class)` | PowerMock available |
| `@SpringBootTest`, `@SpringExtension` | Spring Test available |
| `javax.*` | Stack declares `javax` namespace (not `jakarta`) |
| `jakarta.*` | Stack declares `jakarta` namespace (not `javax`) |
| `assertThat(...)` from AssertJ | AssertJ listed as allowed dependency |
| `assertThat(...)` from Hamcrest | Hamcrest listed as allowed dependency |

- **Never mix JUnit 4 and JUnit 5 annotations in the same test class.**
- **Never mix `javax.*` and `jakarta.*`.**
- If the stack profile is absent or incomplete, use the most conservative option and
  leave a `// TODO: verify framework version in state/stack-profile.json` comment.

### 6. No `@Ignore` / `@Disabled`

- Never silence a test with `@Ignore`, `@Disabled`, `assume*`, or a caught exception
  that swallows the failure.
- A test that does not run is not a test.

### 7. No non-determinism

- Never use `Thread.sleep(N)` without a comment explaining why it is unavoidable.
- Never use `new Random()` or `Math.random()` without a fixed seed.
- Never use `LocalDateTime.now()`, `Instant.now()`, or `new Date()` without a `Clock` mock.

### 8. No modification of production code

- Test generation MUST NOT modify any file under `src/main/java/`.
- If a class is untestable as-is, suggest an extraction or refactor but do NOT apply it.

### 9. No full-file context loading

- Do NOT load entire POMs, entire JaCoCo XML files, or raw stack traces into prompts.
- Reference `state/index/` files and `state/symbol-contracts/<fqcn>.json` instead.

---

## REQUIRED BEFORE ACCEPTING A SUGGESTION

Run the static pre-compile linter before accepting any generated test method or class:

```bash
python tools/python/test_linter.py \
  --test-file     <path/to/TestFile.java> \
  --whitelist     state/import-whitelist.json \
  --contracts     state/symbol-contracts/ \
  --stack-profile state/stack-profile.json \
  --index         state/index \
  --context-pack  state/context-packs/<fqcn>.json
```

Flags:
- `--stack-profile` — enables G5 (JUnit/Mockito/Spring version compatibility).
- `--index` — loads `state/index/methods.json` as G2 fallback for types without a full contract.
- `--context-pack` — cross-validates the linted file corresponds to the expected SUT.

If the linter reports **G1** (import not whitelisted) or **G2** (symbol not in contract)
violations → **reject the suggestion entirely**.

---

## WHERE TO LOOK FOR VALID SYMBOLS

| What you need              | Where to look                                              |
|----------------------------|------------------------------------------------------------|
| Valid imports              | `state/import-whitelist.json` → `packages[]`, `classes[]` |
| Available frameworks       | `state/stack-profile.json` → declared deps, `presets`     |
| Class exists?              | `state/index/classes.json` → look up FQCN                 |
| Constructor signature      | `state/symbol-contracts/<fqcn>.json` → `constructors[]`   |
| Method exists?             | `state/index/methods.json` → `methods[fqcn]`              |
| Builder strategy           | `state/symbol-contracts/<fqcn>.json` → `instantiation`    |
| Builder setters            | `state/symbol-contracts/<fqcn>.json` → `builders[].setters[]` |
| Framework annotations      | `state/index/annotations.json` → `classes[fqcn]`          |
| Test dependencies (DI)     | `state/dependency-graph.json` → `graphs[].dependencies`   |
| Fixture builders           | `state/fixture-catalog.json`                              |
| Which contracts exist      | `state/symbol-contracts.json` ← manifest only; no method defs |

---

## GATE REFERENCE (G1–G9)

| Gate | What it checks                                  | Trigger                         |
|------|-------------------------------------------------|---------------------------------|
| G1   | Import in whitelist                             | Every import in generated test  |
| G2   | Symbol in contract (evidence-id required)       | Every `new`, method call        |
| G3   | Bytecode-first resolution                       | `target/classes` present        |
| G4   | Generated sources indexed                       | Annotation processors detected  |
| G5   | Stack profile declared                          | Before any generation           |
| G6   | Static pre-compile linter passes before compile | Every proposed test             |
| G7   | Failure memory not blocking the fix             | Repair attempts                 |
| G8   | No 2 consecutive zero-delta cycles              | Orchestrator convergence check  |
| G9   | JDT/Copilot diagnostics normalised to index     | VS Code error squiggles         |

---

## CORRECTIVE PATTERNS

```java
// ── Import not in whitelist ──────────────────────────────────────────────────
// ❌ Don't:
import com.acme.SomeClass;   // not verified in state/import-whitelist.json

// ✅ Do:
// TODO: verify import in state/import-whitelist.json
// import com.acme.SomeClass;


// ── Symbol not in contract — use mock ────────────────────────────────────────
// ❌ Don't:
UnverifiedService sut = new UnverifiedService(dep1, dep2);

// ✅ Do (only if Mockito is in state/stack-profile.json):
UnverifiedService sut = Mockito.mock(UnverifiedService.class);
// TODO: verify symbol in state/symbol-contracts/com.acme.UnverifiedService.json


// ── FreeBuilder — only .Builder(), never _Builder ────────────────────────────
// ❌ Don't:
NaturalPerson p = new NaturalPerson_Builder().setName("John").build();
NaturalPerson_Builder b = new NaturalPerson_Builder();

// ✅ Do (only if contract confirms new NaturalPerson.Builder()):
NaturalPerson p = new NaturalPerson.Builder()
    .setName("John")   // only if setName is in builders[].setters[]
    .build();


// ── Invented setter ──────────────────────────────────────────────────────────
// ❌ Don't:
builder.setPersonCommonData(data);  // not in builders[].setters[]
builder.setNaturalPerson(person);   // not in builders[].setters[]

// ✅ Do: use only setters listed in state/symbol-contracts/<fqcn>.json


// ── Framework not in stack ───────────────────────────────────────────────────
// ❌ Don't (if stack-profile.json declares JUnit 4):
import org.junit.jupiter.api.Test;
@ExtendWith(MockitoExtension.class)

// ✅ Do: read state/stack-profile.json first; match the declared test framework
```

---

## TEMPLATE SELECTION (Phase 5)

Choose the test template from `templates/` based on the SUT archetype:

| SUT type (from `state/classification-index.json`) | Template                         |
|----------------------------------------------------|----------------------------------|
| `@RestController`, `@Controller`                   | `templates/webmvc-test.java`     |
| `@Service`, `@Component`, `@Repository`            | `templates/junit5-mockito.java`  |
| Reactive (`Mono`, `Flux`, `@ReactiveController`)   | `templates/reactive-test.java`   |
| `@SpringBootTest` integration tests                | `templates/springboot-test.java` |

The LLM (and Copilot) completes **only** the `@Test` method bodies and assertions.
The skeleton (imports, class declaration, `@ExtendWith`, mocks) comes from the template.

---

## EVIDENCE-ID COMMENT REQUIREMENT

Every generated `@Test` method MUST end with an evidence comment:

```java
@Test
void testProcessName_happyPath() {
    // arrange
    when(collaborator.fetch("id")).thenReturn(fixture);
    // act
    String result = sut.processName("id");
    // assert
    assertThat(result).isEqualTo("expected");
    // evidence: sym:com.acme.FooService#processName:e7a1, ctor:com.acme.FooService:b3c1
}
```

If you cannot cite an evidence-id → the symbol is unverified → **remove that line**.

---

---

## TOKEN MINIMIZATION RULES

These rules govern what context Copilot (and any LLM tool in this workspace)
is allowed to use. Loading files outside these rules wastes tokens and
introduces hallucination risk from irrelevant content.

### What you MUST use as context

| Need | Source | Max size |
|------|--------|----------|
| SUT contract, constructors, methods, builders | `state/context-packs/<fqcn>.json` | ~1500 tokens |
| Valid imports | `allowedImports[]` in the context pack | pre-filtered |
| Test framework + mock framework | `stack` section in the context pack | ~50 tokens |
| Dependency injection map | `collaborators[]` in the context pack | ~200 tokens |
| Existing test methods (to avoid collision) | `existingTests[]` in the context pack | ~50 tokens |
| Compile errors to repair | `state/compile-error-index.json` | ~150 tokens |

### What you MUST NOT load as context

| File | Why forbidden |
|------|---------------|
| `pom.xml` (any module) | ~1500-3000 tokens; `stack-profile.json` has all needed info |
| `target/site/jacoco/jacoco.xml` | ~10K-50K tokens; use `coverage-targets.json` only |
| Raw `mvn` build logs | ~2K tokens; use `compile-error-index.json` (normalized) |
| Full `.java` source of the SUT | ~2K-8K tokens; use the symbol contract instead |
| `state/import-whitelist.json` in full | ~500 tokens; context pack pre-filters the relevant subset |
| `state/symbol-contracts.json` (manifest) | Not authoritative; use `state/symbol-contracts/<fqcn>.json` |

### Output format for Copilot-generated test suggestions

When Copilot generates a test suggestion, it MUST be in the form of a JSON
patch descriptor (see `docs/agent-json-protocol.md`), NOT as a raw Java diff.
The patch is then applied via `test_patch_applier.py`:

```bash
# 1. Save Copilot's suggestion as a patch
#    (or let the agent write it to state/_patches/<TestClass>.patch.json)

# 2. Apply the patch deterministically
python tools/python/test_patch_applier.py \
  --patch        state/_patches/<FQCNTest>.patch.json \
  --repo         <ruta-al-repo-java> \
  --state        state \
  --templates    templates \
  --context-pack state/context-packs/<fqcn>.json \
  --whitelist    state/import-whitelist.json \
  --out          state/generated-tests.json

# 3. Lint before accepting
python tools/python/test_linter.py \
  --test-file <path/to/FooServiceTest.java> \
  --whitelist state/import-whitelist.json \
  --contracts state/symbol-contracts/ \
  --stack-profile state/stack-profile.json \
  --index state/index

# 4. Accept ONLY if exit code is 0 (no G1/G2/G5 violations)
```

### Context pack is the only authorized LLM input

```
# ✅ Correct: pass ONLY the context pack
cat state/context-packs/com.acme.FooService.json | <LLM>

# ❌ Wrong: pass the full source file
cat src/main/java/com/acme/FooService.java | <LLM>

# ❌ Wrong: pass multiple large state files
cat state/import-whitelist.json state/dependency-graph.json | <LLM>
```

The context pack is built by `context_pack_builder.py` and contains a
curated, minimal slice of all relevant state for ONE SUT. It is the
single source of truth for any LLM-based generation or repair step.

*These rules are enforced by the agent pipeline. Copilot suggestions that violate them
will be rejected by the static pre-compile linter (G6) and will not be committed.*
