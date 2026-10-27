# Design

[Index](README.md) · [Quality](quality.md) · [Memory](memory.md)

## Scope and defaults

The selected format changes live ordinary attention K/V insertion, reading and checkpoint storage for Qwen3.8 Flash-Next (`qwen4exp`), including its MTP predictor. It is not merely checkpoint compression. Indexer raw/pooled keys remain F16, recurrent GDN state remains F32, and model weights are unchanged.

- No selector: **F16**.
- `--kv-cache-type q8_0`: plain block32 q8.
- `--kv-cache-type q8_0-rotated`: rotated block32 q8.

Both q8 modes are always compiled into the normal HIP build. There are no rotation or prefill-view build options/macros and no prefill-view opt-out. Unsupported architectures/backends, including the CPU reference inference path, reject q8 selection rather than silently substituting F16.

## Block32 codec

Each block holds a little-endian F16 scale followed immediately by 32 signed int8 codes: **34 bytes versus 64 bytes of F16**. A 512-element K or V row is 544 rather than 1024 bytes.

For finite producer values:

1. Compute `d = amax / 127` with F32 round-to-nearest-even.
2. Compute `x / d` with the same F32 rounding.
3. Apply `roundf` (ties away from zero), clamping codes to [−127,127].
4. Independently round the stored scale to F16, round-to-nearest-even. Do not recompute codes from the half-rounded scale.

All-zero blocks or F32 scale underflow produce zero scale/codes. F16 scale underflow preserves codes but reconstructs zeros. Reciprocal substitution or ties-to-even code rounding is a different byte contract.

Readers reconstruct `F16_RNE(F32(stored_scale) * code)`. Nonzero half operands must match the portable decoder exactly; signed zeros are value-equivalent on the GPU path. The packed helper preserves this boundary rather than an affine half-FMA approximation. **Exact reconstruction concerns already-quantized operands**, not identity to original F16 K/V or another engine's q8.

## Runtime-selected rotation

For supported D256 heads, rotary64, 24 query heads and 2 KV heads, normalized natural-order Sylvester Hadamard transforms use:

- Q/K: H256 after RMS normalization and RoPE.
- V: four contiguous H64 blocks after F32 projection and before quantization.
- Output: inverse V transform after all attention reductions/partial merges, **before sigmoid gating and output projection**.

Normalization comes first, then ascending-distance F32 butterflies. Cache-only MTP producers use the same ordering. Indexer inputs/state are not rotated. Floating-point transform/inverse round trips are not promised bit-exact.

Rotated q8 keeps the same packed row size but has a distinct basis and identity. It bypasses fused QKV projection, so its quality comparison changes both basis and numerical route. Neither observed lower KL tails nor higher target NLL is isolated to rotation.

## Shared transient plain-q8 prefill view

Eligible ordinary matrix-attention calls with at least 256 query rows automatically reconstruct the full populated plain-q8 K/V prefix into transient F16 scratch. Existing WMMA attention consumes those exact half-rounded operands. Canonical live/persisted storage remains packed q8; this is not F16 cache selection or a full-model F16 mirror.

The view:

- uses executor-owned buffers, shared across sessions and sequentially reused on the compute stream;
- is allocated eagerly with overflow checks only for plain-q8 executors with an eligible maximum batch; allocation failure fails creation;
- has no lazy growth or per-session validity cache;
- excludes rotated, MTP, narrow/decode-sized and last-only calls.

At KV width 512, scratch is **2 KiB × min(configured context, WMMA cap 262144)**, shared per executor: **390.625 MiB at context 200000**, at most **512 MiB**. An unspecified context (0) uses native capacity before applying the cap. Unsupported WMMA geometries allocate no view.

This changes scratch capacity only. **Canonical/session capacity is unchanged.** Supported calls beyond the view use packed fallback, with no new rejection. Contexts outside the WMMA route retain the existing narrow-attention fallback. See [memory](memory.md) for authoritative capacity data; allocation arithmetic alone is not a fresh net-memory measurement.

## Persistence and validation

| KV type | Payload version | Append layout |
| --- | ---: | ---: |
| F16 | 19 | 1 |
| Plain q8 | 19 | 2 |
| Rotated q8 | 20 | 3 |

**Version-18 caches, including F16, rebuild once after upgrade.** The snapshot magic/identity format also changes. Both plain and rotated q8 support snapshots, sessions and disk persistence. Type/epoch mismatches reject restoration, not reinterpretation or automatic conversion. Identities also bind basis, codec, context and execution policy.

The portable codec rejects nonfinite input, negative scales including −0, code −128 and F16-overflowing reconstruction. Checked ingress validates packed rows before ownership conversion. Disk startup validates matching packed publications before catalog exposure, with or without optional durable fingerprints; malformed publications are retired without relabeling resource/operational failures as corrupt data.

GPU producers instead signal nonfinite activations with **NaN-scale blocks**. This is not transactional rejection or rollback. CPU row validation can require synchronous device staging; its restore/cache-hit cost remains unmeasured. There is no general F16 snapshot-finiteness guarantee.

## Changes affecting F16 too

- Separate-weight MTP catch-up now uses the cache-only producer rather than the full forward route.
- Cache version/identity changes invalidate old F16 caches too.
- Restore rejection **before any writes** leaves the session unchanged instead of resetting it. This is not rollback after writes begin.
- The shared attention-GEMM epilogue retains full loop unrolling, a code-generation change on F16 too.

The two-call-site batched-MTP YaRN correction is a **separate base change**, found by inspection of missing arguments. Active-YaRN non-regression checks passed on both base and corrected revisions; no behavioral failing-before/passing-after test or long-position sensitivity result is claimed.

## Testing boundaries and prior art

Direct CPU codec/layout/identity-byte/ownership and disk-admission fixtures remain, along with native operators and manual real-model Session/snapshot/adapter fixtures. CPU tests do not establish HIP compilation, model execution or quality. See [revision-specific validation](reproduce.md#candidate-validation-status).

[llama.cpp's Hadamard work](https://github.com/ggml-org/llama.cpp/pull/21038) informed the transform choice. A shared storage name does not imply identical codec rounding, indexer precision, arithmetic or quality. INT8 storage here still feeds reconstructed F16 attention, not integer matrix attention.
