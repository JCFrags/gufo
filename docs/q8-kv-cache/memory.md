# Memory and long-context capacity

[Index](README.md) · [Design](design.md) · [Reproduction](reproduce.md)

## What shrinks

Each block stores 32 signed 8-bit codes and one F16 scale: **34 bytes versus 64 bytes for F16**, retaining 53.125% of ordinary K/V payload (46.875% saved). A 512-element K **or** V row is 544 versus 1024 bytes.

This does not halve the model or total RAM. We leave pooled indexer keys F16 and recurrent GDN state F32. Weights, cache bookkeeping, checkpoints and workspaces have separate costs.

## Stock-cache measurements with the prefill view enabled

These were **measured on the nightly fork build**, on gfx1151 Strix Halo on October 27, 2026:
`c005ab746f38332a96222ca8f2f2bb7e7a2546a2`, ELF
`2e32a9dae2935c784e8a61641413f6fe13d3038fb7d61a230fca32c37adfaa3c`—not fresh
qualification of r3 or the public export. r3 uses the same q8 codec plus the capped
view described below; we do not recompute r3 capacity or savings from these
nightly measurements. Plain q8, F16 prefill view enabled,
UD-Q4_K_XL weights, shared-Q8 MTP, chunk 4096 and text-only requests with thinking
off. Cache sizing was **AUTO**: no `--cache-ram-bytes`, pins or disk tier.

Each initial prompt was cold and generated 256 tokens. After all initial
responses completed, each actual assistant history received one new user turn
(output cap 32). **Every return selected LIVE**, not RAM or disk:

| Slots × configured context | Cold prompt tokens each | Return prompt tokens each | Cached / newly prefilled each | Peak GTT GiB | Minimum MemAvailable GiB |
| --- | ---: | ---: | ---: | ---: | ---: |
| 4 × 262144 |261544|261821|261800 / 21|99.597481|10.812355|
| 4 × 376832, YaRN |376231|376508|376487 / 21|106.214642|7.201157|
| 1 × 1048576, YaRN |1047978|1048255|1048234 / 21|99.805099|13.723938|

All initial and returning requests completed. Server VmSwap stayed 0; global
pswpin remained 0, pswpout remained 3150 and oom_kill remained 0. The nonzero
historical swap-out counter did not grow. Every approximately 1-second memory
sample exceeded the 2 GiB available-memory floor; GiB values above are rounded.
There were 13, 14 and 8 samples, respectively, witnessing all configured requests
fully prefilled and still decoding. These are completed workloads, not merely
startup allocations.

**AUTO is not a fixed 8.5 GB allowance.** Actual selected budgets were:

- S4/262144: **12064702464 bytes**.
- S4/376832: **8533805056 bytes**.
- S1/1048576: **11631800320 bytes**.

The default selects half available RAM, capped at 32 GiB; available RAM and the
resulting budget change with context, slots and process conditions. These rows
are not matched-context F16/q8 memory-saving comparisons.

### Startup brackets are not completed-fill maxima

| Profile | Tested startup success | Tested startup refusal | Completed-fill qualification |
| --- | --- | --- | --- |
| q8, S4 |262144, 327680, 360448, 376832|393216|262144 and 376832 only|
| q8, S1 |1392640;1048576 also completed|1507328|1048576 only|
| F16, S4 |200000|262144|No fresh F16 fill in this campaign|

The refusals were **`text runner request-state claim exceeds state capacity`**,
not physical OOMs. The finite brackets are376832–393216 for q8 S4,
1392640–1507328 for q8 S1 startup, and 200000–262144 for F16 S4 startup.
They do not locate exact universal maxima. In particular, 1392640 was not filled;
**1M is a confirmed S1 lower bound, not its measured maximum**. F16 S4/200000
startup reached GTT 103.965 GiB with 14.936 GiB minimum available memory, but that is
not fresh near-full F16 qualification. The older matched 200K run is separate below.

Every context above 262144 used `--enable-yarn`, static for the whole process.
**YaRN quality is unvalidated. These are capacity and continuation-accounting
claims, not long-context retrieval, task-accuracy or quality-equivalence claims.**

### Limits of extrapolation

KV/indexer memory roughly follows aggregate tokens, but per-slot buffers,
retained checkpoints and admission reservations also matter. Use the measured
startup brackets and completed fills above, not a universal four-to-one scaling
rule. The r3 scratch cap below is not a newly measured capacity result.

## Historical four-slot capacity, before the prefill view

We compared F16 and plain q8 with the same development binary and UD-Q4_K_XL weights, shared-Q8 MTP enabled, four allocated sessions, context 200000, prefill chunk 4096 and retained-cache budget **11329267712 bytes (~10.55 GiB)**. Vision was available but no images were used. Each arm used a fresh server, F16 first then q8, one pair.

Each request processed **199400 cold prompt tokens plus 256 outputs**, reaching 199656 tokens. Both arms completed all four requests with zero prompt reuse. Samples witnessed four distinct, fully prefilled slots decoding with speculation enabled: 13 samples for F16, 12 for q8. This is live work, not just admitted requests.

| Sampled observation, GiB | F16 | Plain q8 |
| --- | ---: | ---: |
| Whole-run peak GTT | 104.976 | 95.652 |
| Long-phase peak GTT | 104.963 | 95.645 |
| Minimum long-phase MemAvailable | 6.210 | 15.448 |
| Peak server RSS | 11.658 | 11.730 |
| Peak VRAM, separate view | 0.173 | 0.171 |

Whole-run peak GTT fell **9.324162 GiB**; the matched long-phase reduction was 9.317871 GiB. Minimum available system memory rose 9.238 GiB, or 9.122 GiB after adjusting for the starting available-memory difference.

**F16 also fit.** Neither arm grew swap or the system OOM counter; server swap stayed zero, and no device loss was observed in the bounded run. We did not search for absolute maximum capacity.

GTT is driver-accounted graphics translation-table memory, not a unique process physical-RAM total. On unified memory these views overlap: **do not add RSS + GTT + VRAM**. RSS slightly increased. Samples were about 1.018 seconds apart, so peaks are sampled rather than instantaneous guarantees.

## Capped F16 prefill scratch in r3

The [speed optimization](speed.md) reconstructs one layer's K/V into executor-owned
F16 scratch, reused across attention calls. Canonical storage and checkpoints
stay q8. It is **not a full-model F16 cache mirror** or a per-session allocation.

For this model's 512-element K/V rows, the r3 allocation is capped at the WMMA
limit:

```text
min(context_capacity, 262144) × 2 KiB
```

That is **409600000 bytes = 390.625 MiB at 200000**, and a maximum of
**536870912 bytes = 512 MiB per executor**, including at contexts above 262144.

We make no modelled net-saving claim. The measured nightly-fork contrast is
that q8 **4 × 376832 completed**, while F16 **4 × 262144 was refused at startup**.
This does not substitute for a fresh r3 measurement or a matched-context
memory-saving comparison.

## Live slots are not retained rewind checkpoints

**The genuine eviction/re-prefill threshold remains untested.** The owner stopped
the first S4/131072 four-plus-one eviction experiment during its initial four
cold fills. The fifth conversation and evicted-history return were never reached.
Its output is **INCOMPLETE**, not a retention verdict. The 262144 eviction and
same-context F16 contrast were not run; no RAM-restore bytes or eviction TTFT
were measured. The unfinished protocol used read-only lookup observability,
not a cache-budget override. That diagnostic interface is not part of the
current export; no completed result depends on it.

In the completed runs, S4/376832 reported RAM-candidate depth 0 for all four
returns. S1/1048576 reported a deepest RAM candidate of 260096 while reusing
1048234 tokens LIVE. At S4/262144 only one return also had a RAM candidate at
261544; the other three reported 0. None selected RAM. **These observations do
not prove full-context checkpoint restoration after slot eviction.**

In the historical matched 200K run, both arms received the full requested cache budget, but byte-capacity checkpoint-capture refusals still occurred: **7 F16 / 4 q8**. These were retention-budget events, not model OOMs.

Four live near-200K contexts do not prove four independently retained full-depth rewind checkpoints. Increasing the cache cap, adding pinned prefixes or disk retention, or adding executors consumes headroom and requires a separate measurement. Rotated q8 has the same packed row size, but this measured capacity result is **plain q8 only**.

The pre-view capacity run also observed slower prefill and short concurrent output; see [speed](speed.md#historical-near-200k-result). Memory savings are not a throughput claim.
