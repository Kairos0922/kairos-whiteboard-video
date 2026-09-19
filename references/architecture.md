# Engineering Architecture

## 1. Problem definition

The system is not primarily an animation generator.

Its job is to preserve one causal chain:

**knowledge → learner transition → expression → visual state change → time → rendered media**

Engineering quality means minimizing three classes of failure:

| Failure class | Example | Primary control |
|---|---|---|
| Semantic drift | drawing something the narration has not established | IR + lint |
| Temporal drift | drawing continues after narration / narration outruns reveal | word timeline + validation |
| Rendering drift | ghost frames, missing strokes, unstable hand/character | deterministic renderer + assets + QA |

A change is justified when it reduces one failure class without increasing another.

## 2. MECE quality model

1. **Correctness** — IR, assets, timing, media contract.
2. **Consistency** — theme, characters, hand, scene identity.
3. **Continuity** — state transitions, scene boundaries, residual frames.
4. **Perception** — legibility, pacing, visual cleanliness, audio quality.
5. **Operability** — reproducibility, diagnostics, incremental rebuilds.

Do not solve a category by adding rules to another category.

## 3. Source-of-truth hierarchy

1. input/script.json — semantic and expressive decisions.
2. input/characters.json — project character identity.
3. themes/<id>/ — visual contracts and canonical assets.
4. build/ — generated intermediates; always reproducible.
5. state.json — workflow state only; never a semantic source.
6. deliverables/ — output only.

If two files disagree, regenerate the lower layer from the higher layer rather than patching both.

## 4. Dependency-driven rebuilds

~~~text
script ───────────────┬─→ prompts ─→ boards ─→ layout ─→ annotations ─→ render ─→ assemble
                      │
                      └─→ voice ─→ words ────────────────┘
theme ────────────────┴─→ prompts / import / render
characters ─────────────→ prompts / references
~~~

Required behavior:

- script change: invalidate affected prompts, boards/annotations and downstream render.
- one board change: invalidate only that scene's layout/annotation/render.
- voice change: invalidate words and time-dependent annotations/render; preserve boards.
- theme asset change: invalidate dependent render outputs.
- subtitle-only change: do not regenerate boards.

Prefer hashes / fingerprints over timestamps. Render cache must include the renderer implementation and all scene inputs; changing engine code invalidates affected renders automatically.

## 5. Quality gates

### Static gates

- schema / IR validity
- enum validity
- dependency topology
- scene / beat / element alignment
- theme completeness
- asset existence and dimensions
- no unsupported reveal operations

### Media gates

- dimensions / codec / pixel format / fps
- audio presence and loudness
- word-to-reveal alignment
- scene duration alignment
- missing strokes / end-of-scene truncation
- transition residuals

### Human gates

Machine checks cannot reliably judge:

- character identity from a contact sheet
- style fidelity
- cognitive clarity
- perceived pacing
- distracting motion

Human review should use contact sheets and evidence frames, not memory.

## 6. Quantitative targets

Targets are acceptance thresholds, not quality scores:

| Metric | Target |
|---|---:|
| blocking static findings | 0 |
| annotation fallback warnings | 0 |
| unsupported operations | 0 |
| word-anchor coverage | 100% |
| scene render failures | 0 |
| final video decode failure | 0 |
| end-of-scene missing ink | ≤ 1% |
| word timing deviation | ≤ 120 ms |
| final duration vs narration | ≤ 200 ms |
| CI test failures | 0 |

Perceptual metrics must remain evidence-based. Do not convert subjective quality into a single number unless the measurement protocol is defined first.

## 7. Change discipline

Before modifying code:

1. identify the invariant being protected;
2. identify the source of truth;
3. identify the smallest affected layer;
4. define a regression test;
5. implement the smallest change;
6. run the narrowest test first;
7. run the full suite;
8. run a representative render when media behavior changes.

Avoid:

- speculative abstractions;
- duplicate state machines;
- hidden fallbacks;
- hard-coded scene-specific behavior in shared engine code;
- docs that describe commands not present in the code;
- keeping compatibility paths indefinitely without a removal plan.

## 8. Maintainability standard

Prefer:

- small pure functions around file contracts;
- explicit data structures;
- one canonical command path;
- stable error codes;
- deterministic outputs;
- tests at the boundary between stages.

A module should have one reason to change. If a file mixes CLI orchestration, domain rules, media rendering and persistence, extract the smallest stable boundary before adding more features.

## 9. Testing pyramid

~~~text
              ┌──────────────┐
              │ Human review │  few / expensive
              ├──────────────┤
              │ Media smoke  │
              ├──────────────┤
              │ Contract     │
              ├──────────────┤
              │ Unit tests   │  many / fast
              └──────────────┘
~~~

The test suite should fail for the same reasons production would fail, but at the cheapest possible layer.

## 10. Definition of done

A change is complete only when:

- the invariant is documented;
- the implementation is covered by an appropriate test;
- no legacy path is accidentally made canonical;
- CI passes;
- affected media behavior has a representative render check;
- user-facing commands and documentation agree with the implementation.
