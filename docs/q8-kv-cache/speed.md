# Historical speed versus F16

[Index](README.md) · [Memory](memory.md) · [Reproduction](reproduce.md)

**These are earlier development measurements, not fresh R3 performance results.** No final-candidate speed table is available here.

## Plain-q8 prefill near F16 in four measured cells

gfx1151, ROCm 7.2.4, AMD Clang 22, patched ROCr, HIP, plain q8, UD-Q4_K_XL weights and shared-Q8 MTP. The process allocated four sessions, context 200000, prefill chunk 4096 and cache cap 11329267712 bytes, without prompt reuse.

C1/C4 mean one/four concurrent requests within that four-session process. Each cell used four distinct prompts and 128 outputs/request in one pass. Nominal 8K/32K targets produced **8194/32767 native prompt tokens**.

Native prefill throughput is total prompt tokens divided by summed native per-request prefill time, **not cohort-wall throughput or time to first token**.

| Work | Same-binary F16, tok/s | Plain q8 with view, tok/s | Throughput change |
| --- | ---: | ---: | ---: |
| 8194 tokens, C1 | 1690.830 | 1681.116 | −0.57% |
| 8194 tokens, C4 | 1740.427 | 1737.502 | −0.17% |
| 32767 tokens, C1 | 1664.062 | 1723.418 | +3.57% |
| 32767 tokens, C4 | 1665.123 | 1676.393 | +0.68% |

These short ordered observations are **not repeated-interleaved non-inferiority tests**. The later F16 control's 32K rates drifted down from the original F16 screen; against the original, q8 ranged −0.87% to +0.43%. This supports descriptive near-parity, not a reliable 3.6% speedup.

Decode was **about 1% behind F16 at 32K**, explicitly preliminary. Later packed-reader/verification changes are not a new end-to-end decode result; kernel gains cannot be added to this table.

## How prefill changed

| Work, tok/s | Original F16 | Initial plain q8 | Exact packed reconstruction | Packed + F16 view |
| --- | ---: | ---: | ---: | ---: |
| 8194 tokens, C1 | 1695.885 | 1621.529 | 1644.948 | 1681.116 |
| 8194 tokens, C4 | 1740.539 | 1668.477 | 1687.257 | 1737.502 |
| 32767 tokens, C1 | 1715.960 | 1591.169 | 1648.601 | 1723.418 |
| 32767 tokens, C4 | 1685.267 | 1588.824 | 1609.021 | 1676.393 |

Initial q8 prefill was roughly 4–7% slower. Two retained changes reduced reconstruction work:

1. Packed-half reconstruction preserves the same stored bytes and half-rounded attention operands with fewer conversions.
2. A transient F16 view reconstructs each populated layer K/V prefix once per attention call, sharing it across query workgroups.

In the current interface, eligible plain-q8 ordinary matrix prefill with at least 256 query rows **always uses the view when it fits**. There is no build switch or opt-out. MTP, rotated, narrow/decode-sized, last-only and beyond-view calls use packed readers. Scratch is shared per executor: **2 KiB × min(configured context, WMMA cap 262144)**; 390.625 MiB at 200000, maximum 512 MiB for supported geometry. Context 0 uses native capacity before capping; unsupported WMMA geometry allocates none. Canonical/session capacity does not change, and beyond-view fallback introduces no new rejection.

Full-prefix reconstruction grows with frontier; the 256-row threshold is heuristic, not qualification of every shape. See [design](design.md) and [memory](memory.md).

## Exactness is not quality or speed equivalence

Historical packed-load checks covered **401210880 operand comparisons** against the portable codec, with zero-sign canonicalization only. Native operators covered tails, splits and graph replay; poisoning checked that view reconstruction wrote its destination.

All 23 optimized-q8 greedy completions matched earlier q8 references. Separately, 23 F16 controls matched original F16. **This is not q8-versus-F16 output identity.** Historical view-enabled/disabled builds exercised the then-current interface, not an opt-out in the current candidate.

An earlier preload-batch reduction was rejected despite fewer spills: its three-row microkernel slowed from 97.117 to 104.836 µs and concurrent serving results were inconsistent. Resource improvements alone do not establish request-level gains.

## Historical near-200K result

The [capacity experiment](memory.md) predates the transient view. Four requests each processed 199400 prompt tokens plus 256 outputs:

| Observation | F16 | Plain q8 | Change |
| --- | ---: | ---: | ---: |
| Sum of native long-prefill times | 493.978 s | 526.153 s | +6.51% time |
| Long-cohort wall time | 507.664 s | 539.887 s | +6.35% time |
| Short C1 delivered output | 53.316 tok/s | 53.085 tok/s | −0.43% rate |
| Short C4 delivered output | 80.736 tok/s | 76.358 tok/s | −5.42% rate |

The short output rates include prefill/queueing. C1 used three quick prompts once each; C4 padded them to four. Different outputs and MTP acceptance affect interpretation; this was one ordered pair.

The four smaller view-enabled cells **do not demonstrate 200K recovery**. Rotated performance, sustained reuse/decode and final-R3 serving performance remain unestablished here. Synchronous CPU row-validation cost at cache-hit depth is unmeasured. Historical ROCm 7.2.4 / Clang 22 results do not qualify pinned **ROCm 10.1 / HIP Clang 24, which is UNTESTED for this change**.
