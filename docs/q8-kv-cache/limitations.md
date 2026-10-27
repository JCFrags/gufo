# Limitations and open work

[Index](README.md) · [Quality](quality.md) · [Reproduction](reproduce.md)

## Who should try it

Plain q8 is the suggested starting point when long-context memory margin matters more than exact F16 behavior. **F16 remains the default.** Rotated q8 is an alternative trade-off, not a universal upgrade. Neither is a promise of speedup, identical text or established long-agent quality.

## Quality

- Both historical 144-position arms agree with F16 at 141/144 positions and missed the original strict criteria. F16 agreement is not ground-truth task correctness.
- The larger plain screen had mean KL 0.00295170, 97.8299% top-1 agreement and maximum KL 1.75884. Its original failed verdict remains.
- Rotated q8 has lower observed small-screen KL tails but higher target NLL: rotated-minus-plain CI [+0.000134906, +0.0112652]. The mean-KL contrast is inconclusive, and the separate projection route remains a confound.
- BF16-K-minus-plain mean-KL CI [−0.000645661, +0.001965481] is inconclusive, not an equivalence bound. Block16 has worse mean KL despite one fewer disagreement and 5.88% more ordinary-KV bytes; it was rejected and is not included.
- The BF16/block16 comparison reuses historical F16/plain after eight exact spotchecks per arm. It does not provide 144 freshly recaptured F16/plain rows on the diagnostic executable; source/epoch confounding is outside the CIs.
- Gufo cold prefixes and llama.cpp history-streamed captures are not numerically equivalent. llama.cpp also quantizes indexer K. Own-engine F16-relative metrics do not rank absolute engine quality or prove non-inferiority.
- The selected tool-JSON tail is fragile under the demonstrated BF16-K and default-rotated llama.cpp controls. This neither proves a codec defect nor rules one out; the tail remains in the record.
- WikiText's clipped/quantized reference and tool-only 32K adaptation are approximate protocol controls. Nonzero F16 self-reference KL 0.001143 is not an additive error budget.
- Two histories per long-context category cannot establish rare population tails. Cold AR quality with MTP/reuse/vision off does not establish MTP, reuse, coding-task or hours-long agent quality.

## Memory and speed

- A q8 row retains 53.125% of F16 ordinary K/V bytes, not 53.125% of total RAM.
- The 9.324 GiB sampled GTT reduction at four × 199400-token prompts predates the view. It is historical, not a fresh net-memory result. [Memory](memory.md) owns authoritative capacity data; no new combined saving is inferred here.
- Supported plain-q8 view scratch is shared per executor: 2 KiB × min(configured context, WMMA cap 262144), 390.625 MiB at 200000, at most 512 MiB for this geometry. Context 0 uses native fallback before capping; unsupported geometry allocates none. Multiple executors cost more in aggregate.
- Beyond-view calls fall back to packed readers with no new rejection; canonical/session capacity is unchanged.
- Four live contexts do not prove four retained full-depth rewind checkpoints. Historical capture-budget refusals persisted. RSS, GTT and VRAM overlap and must not be added.
- Four short ordered view-enabled speed cells (−0.57%, −0.17%, +3.57%, +0.68%) do not establish statistical non-inferiority or recovery of the historical pre-view 200K +6.51% prefill-time cost.
- Decode about 1% behind at 32K is preliminary. There is no fresh final-R3 performance table here, no rotated speed qualification, and no serving-gain claim from kernel-only improvements.

## Implementation and default-path changes

- Both q8 modes are always compiled into the HIP build. There is no rotation or prefill-view build option/macro or view opt-out. Unsupported architecture/backend selection rejects rather than silently substituting F16.
- Both q8 modes support disk persistence. Payloads are 19 for F16/plain and 20 for rotated, layouts 1/2/3. All version-18 caches, including F16, rebuild once. Incompatible type/epoch identities reject restore.
- Separate-weight MTP cache-only routing and shared attention epilogue unrolling also affect F16. Rejection before any restore writes now leaves the session untouched, not reset; rollback after writes begin is not promised.
- GPU nonfinite producers signal with NaN scales, not transactional rollback. Checked ingress is a separate boundary; no general F16-finiteness guarantee is claimed.
- CPU row validation may synchronously stage device data. Startup/restore/cache-hit cost at depth has not been isolated.
- The separate two-line YaRN base fix was found by inspection. The historical 9974/df29 revisions passed active-YaRN non-regression; no behavioral failing-before/passing-after proof is available, and that is not a fresh run on the c92-based revision.
- Direct CPU fixtures, native operators and manual real-model Session/snapshot/adapter tests have distinct scope. A CPU pass does not mean model assets were used or native checks ran.

## Validation still open

| Item | Status |
| --- | --- |
| Final HIP build/operators and 200000 view endpoint | PASS: native build on two hosts; 5/5 KV operator tests including the exhaustive 401,210,880-value check (zero mismatches) |
| Final F16/plain/rotated smoke, snapshot/session/disk restore and affected functional checks | PASS: three-mode MTP smoke matches upstream F16 output; snapshot round trips exact; 4/4 disk save/restart/restore; 13/13 functional suites in upstream order |
| Retained dtype-aware snapshot-bound test on current `816de7f4` | PASS for F16, plain and rotated |
| Full CPU/hosted results | R3 build PASS; full 131 PASS / 10 SKIP / 4 FAIL of 145, hosted 68 PASS / 3 FAIL of 71. All r3 failures match c92 baseline assertions; not clean-suite PASS |
| Deep cache-hit validation overhead; repeated interleaved performance | **UNMEASURED / NOT ESTABLISHED** |
| Long-agent/task non-inferiority and broader platform coverage | **NOT ESTABLISHED** |

Historical evidence used gfx1151 / ROCm 7.2.4 / AMD Clang 22 with the tested runtime. Pinned **ROCm 10.1 / HIP Clang 24 is UNTESTED for this change**. No other-GPU, Vulkan or NPU runtime claim follows.

See the [revision-specific validation table](reproduce.md#candidate-validation-status). Native assessments do not constitute public/upstream approval. Owner testing and final approval remain required before publication.
