# Enable and reproduce

[Index](README.md) · [Design](design.md) · [Limits](limitations.md)

These are current-interface commands and disclosed measurement protocols, **not a complete one-command reproduction package**. Historical evaluation inputs/capture tools are not bundled here. Current-revision checks are listed separately from the historical measurement protocols.

## Current candidate and build interface

- Candidate: `816de7f4a7da101e8ab111aa09a984b576421d66`
- Tree: `cffd7ab5eed3519927bab1aceb84235ace215105`
- Base: separate two-line YaRN fix `b0c25b012fe87b7c46d9fa060d40baa6dcda5c25`, on upstream `c92b19c5dc7ec12f83d0c2a5603cda78cc200b3e` (#850, removal of lossy chunked DeltaNet prefill).

From a checkout with supported HIP dependencies and model assets already available:

```sh
cmake --preset release
cmake --build --preset release --parallel 2

build/release/gufo serve llm --model "$MODEL" --kv-cache-type q8_0
# Alternative basis; use instead of the preceding server:
build/release/gufo serve llm --model "$MODEL" --kv-cache-type q8_0-rotated
```

Set `MODEL` to your model file and retain your usual context, MTP and serving arguments. `prompt`, `chat`, `bench` and `serve llm` accept the canonical selector on the ROCm Flash-Next path. Omit it for **F16**, the default.

**Both q8 modes are always compiled. There are no rotation or prefill-view build options/macros and no view opt-out.** Eligible plain-q8 matrix prefill uses the transient view automatically; other supported calls use packed readers. The CPU reference inference path and unsupported architectures/backends reject q8 rather than silently choosing F16.

Verify the selected mode and effective settings through available startup/runtime properties. If a setting is not exposed there, preserve the exact command/configuration rather than claiming runtime verification.

**Cache upgrade:** version-18 entries, including F16, rebuild once. Current payloads are 19 for F16/plain and 20 for rotated, with append layouts 1/2/3. Both q8 modes persist to disk, but incompatible type/epoch identities reject restore. Do not relabel old state.

### Focused test commands

CPU checks (not HIP/model execution):

```sh
cmake --preset cpu-test
cmake --build --preset cpu-test --parallel 2
ctest --preset cpu-test -R '^qwen38_flash_next\.(kv_cache|kv_rotation)$'
# Hosted PR selection, including its CPU checks:
cmake --build --preset pr --parallel 2
```

Native operator checks, on supported hardware:

```sh
cmake --preset gpu-test
cmake --build --preset gpu-test --parallel 2 --target \
  qwen38_flash_next_kv_q8_ops_test \
  qwen38_flash_next_kv_rotation_ops_test \
  qwen38_flash_next_kv_q8_load_test
ctest --preset gpu-full \
  -R '^qwen38_flash_next\.(kv_q8_ops|kv_rotation_ops|kv_q8_load)$'

# Builds the explicit model fixtures; does not run them:
cmake --build --preset gpu-test --parallel 2 \
  --target qwen38_flash_next_model_tests
```

The Session, snapshot and continuation-adapter executables require model assets and manual invocation with their own arguments. They are not automatic full-model passes from CPU CTest or the operator commands above. Current direct CPU identity/layout/ownership fixtures remain; native/full-model checks have separate evidence requirements.

## Candidate validation status

Results are revision-specific. Current R3 rebases the earlier candidate onto upstream `c92b19c5`; older CPU/native results are not automatically new-revision passes.

| Check on `816de7f4` | Recorded result |
| --- | --- |
| Full CPU build and CTest | Build PASS; 131 PASS / 10 SKIP / 4 FAIL of 145 |
| Hosted PR preset | 68 PASS / 3 FAIL of 71 |
| Exact unchanged-`c92b19c5` failure-signature pairing | All r3 failures match unchanged-baseline assertions. Baseline full: 125 PASS / 10 SKIP / 5 FAIL of 140; hosted: 67 PASS / 3 FAIL of 70. Identity test failed baseline full but passed r3/both hosted runs; neither suite is clean PASS |
| Source docs and PR title | PASS: 107 Markdown files / 621 links; title accepted |
| Packed-disk corruption regression | PASS in fresh CPU suite; historical genuine pre-fix RED/fix GREEN preserved |
| Final HIP build and packed-load/plain/rotated operators, including view endpoint 200000 | PASS: two hosts, ROCm 7.2.4 / AMD Clang 22; 5/5 KV operator tests, zero mismatches |
| F16/plain/rotated MTP smoke; snapshot/session; rotated disk restore | PASS: identical greedy output hash to upstream F16; exact snapshot round trips; 4/4 disk restore (AR/MTP × plain/rotated) |
| Affected AR/MTP functional suites, cache/long-context and F16 greedy parity against upstream with YaRN off | PASS: 13/13 suites in upstream order on one server; F16 long-context + cache AR/MTP timing 4/4 within 5% and 10 ms of upstream `c92b19c5`, per request and phase |
| q8 restore/cache-hit time to first token at depth | **UNMEASURED** |

The earlier snapshot fixture passed 12 exact and 2 borrowed checks before hitting an F16-sized 80 MiB lower bound under q8. The retained test correction uses **80 MiB × actual KV byte ratio**: unchanged 80 MiB for F16, 42.5 MiB for a 512-value q8/rotated row. Payload/overwrite assertions and the short 8 MiB upper bound remain unchanged. That was a test-bound bug, not an observed payload failure; native validation is recorded separately.

The separate YaRN fix was found by inspection. Historical active-YaRN batch non-regression passed on both `9974cb4c` and `df29f13d`, without demonstrating failing-before/passing-after behavior. This is not a new batch run on rebased `b0c25b01`. Long-position cache-row sensitivity remains unmeasured.

**Toolchain limit:** historical measurements used ROCm 7.2.4 / AMD Clang 22 and a patched ROCr. The pinned ROCm 10.1 / HIP Clang 24 stack is **UNTESTED for this change**.

## Record a new comparison

Retain source/tree, executable hash, build configuration, hardware/OS/driver/runtime/compiler, model/sidecar/tokenizer identities, complete arguments, native input IDs and effective runtime settings. Use the same executable for F16/q8 where possible, changing only the selector. Preserve failed attempts and verify zero actual reuse for cold tests.

Historical builds used different interfaces and feature controls. Their results below remain historical; do not copy their old build switches into the current candidate.

## Historical quality protocol

1. Freeze prompt token IDs, positions and targets before evaluating modes.
2. Independently re-prefill the 144 prefixes from 18 histories: context 262144, chunk 4096, one active session, AR, MTP/reuse/vision off.
3. Capture all 248320 pre-output F32 logits per position. The historical capture made one greedy output selection per prefix, not a free-running continuation comparison.
4. Validate finiteness, token/position alignment, cold repeats, sensitivity and observable probe-off controls.
5. Score `KL(F16 || candidate)`, linear p99/max, top-1 agreement and target ΔNLL. Use whole-history resampling for paired uncertainty: 5000 draws, PCG64 seed 20261025.
6. Keep the larger 1152-position screen and purposeful tail controls separate. Keep historical F16/plain reuse after eight spotchecks distinct from fresh diagnostic captures.

For llama.cpp pin [338fce65](https://github.com/ggml-org/llama.cpp/tree/338fce6511c744893cc0d3d958b275f40552c7a4), each mode uses its own engine's F16. The 144-row reference is history-streamed, not cold-prefix-equivalent; indexer K is also q8. The cold four-row controls are separate. Approximate WikiText saved-reference KL and the disclosed 32K tool-only streaming adaptation are not substitutes for Gufo's full-F32 oracle. See [quality](quality.md) for results and protocol limits.

## Historical memory/capacity protocol

The pre-view experiment used UD-Q4_K_XL, shared-Q8 MTP enabled, four sessions, context 200000, chunk 4096, retained-cache cap 11329267712 bytes, thinking off and four distinct simultaneous cold prompts. Each processed 199400 prompt tokens plus 256 outputs.

Verify four fully prefilled slots actively decoding, not merely admissions. Track GTT, MemAvailable, RSS, VRAM, swap/OOM counters, capture refusals and completions separately. The old run was one F16-first pair with roughly one-second samples. Do not add overlapping memory views.

A current view-enabled run is a new comparison, not reproduction of the pre-view 9.324 GiB result. Record eligibility and actual scratch allocation, not an obsolete ON/OFF build setting. Use [memory](memory.md) for authoritative capacity data; no fresh combined net result is inferred here.

## Historical speed protocol

Use the four-session/context/cache/chunk/MTP profile above, no reuse, four prompts per cell and 128 outputs/request. Test one/four concurrent requests separately. Native prompt counts were **8194 and 32767**, not nominal 8192/32768.

Native prefill rate is total prompt tokens divided by summed native prefill time. Keep cohort wall, time to first token, decode and delivered output rates separate. Preserve output lengths and MTP proposal/acceptance counts. Repeat in interleaved order before claiming a small advantage.

Compare optimized q8 completion hashes to earlier q8, and F16 controls separately to F16. Include view reconstruction cost. Kernel-only improvements are not serving gains.

## Reproduction material still needed

- Final revision-bound native/functional results for the pending table above.
- Screened/licensed inputs, frozen token/position manifest and capture/scoring tools.
- Public-safe raw result artifacts and stable evidence links.

The historical BF16-K/block16 and llama.cpp distribution aggregates are already available in [quality](quality.md); they are not pending measurements. Input licensing, screened artifacts and stable evidence links must be resolved before claiming complete independent reproduction.
