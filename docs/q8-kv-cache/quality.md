# Quality versus F16

[Index](README.md) · [Limits](limitations.md) · [Reproduction](reproduce.md)

All measurements below are **historical development evidence**, not final-R3 quality validation. We compare distributions on identical frozen histories, not free-running histories after divergence. F16 is each engine's numerical reference, not ground-truth task correctness.

## llama.cpp reference: protocol differences first

**This is not a strictly matched codec comparison.** Gufo independently re-prefilled each cold prefix; llama.cpp advanced teacher-forced through each history, clearing state between histories. llama.cpp q8 also quantizes indexer K, while Gufo retains F16 indexer keys. The engines' F16 distributions differ.

Same UD-Q4_K_XL weights, 144 frozen positions across 18 histories, gfx1151; llama.cpp source [338fce6511c744893cc0d3d958b275f40552c7a4](https://github.com/ggml-org/llama.cpp/tree/338fce6511c744893cc0d3d958b275f40552c7a4). Each row is relative to **its own engine's F16**:

| Engine / KV | Capture | Mean KL | p99 KL | Maximum KL | Top-1 agreement |
| --- | --- | ---: | ---: | ---: | ---: |
| Gufo plain q8 | Cold prefixes | 0.00137127 | 0.0309366 | 0.0825341 | 141/144 |
| Gufo rotated q8 | Cold prefixes | 0.000946485 | 0.0175448 | 0.0377823 | 141/144 |
| llama.cpp plain q8 | History-streamed | 0.0132854 | 0.0359624 | 1.79347 | 141/144 |
| llama.cpp default rotated q8 | History-streamed | 0.00643116 | 0.0511198 | 0.734231 | 141/144 |

Four streamed/cold llama.cpp F16 controls retained argmax but reached KL 0.0822699. Numerical equivalence of capture protocols is not established. These observations provide context, **not an absolute engine ranking or proof of non-inferiority**.

## Historical 144-position Gufo screen

Same executable, UD-Q4_K_XL weights and tokenizer across F16/plain/rotated; cold single-session autoregressive inference, MTP/reuse/vision off, context 262144, prefill chunk 4096. Historical source: `f2ae34244b939ee7611c9c17612a035a75533450`. Each position captures all 248320 F32 vocabulary logits; scoring uses F64.

KL means `KL(F16 || candidate)`. Target ΔNLL means `NLL(candidate) − NLL(F16)`; negative favors the candidate on the frozen target, not necessarily over the full distribution. Units are nats. p99 uses linear interpolation.

| Metric | Plain q8 | Rotated q8 |
| --- | ---: | ---: |
| Mean KL | 0.00137127 | 0.000946485 |
| p99 KL | 0.0309366 | 0.0175448 |
| Maximum KL | 0.0825341 | 0.0377823 |
| Top-1 agreement | 141/144 | 141/144 |
| Mean target ΔNLL | −0.000224419 | +0.00463353 |
| Original strict numeric verdict | FAIL | FAIL |

The 3/144 disagreements per arm are not three demonstrated wrong answers. Equal counts do not mean identical error positions.

Rotated q8 had lower observed finite-screen KL tails, but higher target NLL. It also bypasses fused QKV projection: basis and numerical route both change.

Paired rotated-minus-plain contrasts use 5000 whole-history bootstrap resamples, PCG64 seed 20261025, token weighting:

| Metric | Difference | Two-sided 95% CI | Interpretation |
| --- | ---: | --- | --- |
| Mean KL | −0.000424789 | [−0.00139693, +0.000179719] | Inconclusive |
| Target ΔNLL | +0.00485795 | [+0.000134906, +0.0112652] | Rotated higher |
| Top-1 disagreement, percentage points | 0 | [−2.77778, +2.77778] | Inconclusive |

These are marginal intervals, not simultaneous/multiplicity-adjusted bounds. p99/max are finite-corpus points without population-tail confidence bounds. Each long-context category has only two independent histories. Rotation is not uniformly better.

## BF16-key control and rejected block16 diagnostic

Same 144 frozen positions / 18 histories versus Gufo F16:

| Arm | Mean KL | p99 KL | Maximum KL | Top-1 disagreements | Target ΔNLL |
| --- | ---: | ---: | ---: | ---: | ---: |
| Plain block32 q8 | 0.00137127 | 0.0309366 | 0.0825341 | 3/144 | −0.000224419 |
| BF16-rounded K, V F16 | 0.00179624 | 0.0441063 | 0.117239 | 3/144 | −0.0101736 |
| Block16 q8 diagnostic | 0.00352501 | 0.0666951 | 0.186887 | 2/144 | −0.0058822 |

BF16-K-minus-plain mean-KL CI **[−0.000645661, +0.001965481]** is inconclusive. This structured precision control does not establish an irreducible error bound or statistical equivalence. Its lower target NLL is not recovery of the F16 distribution.

Block16 has **worse mean KL**, paired CI **[+0.000372368, +0.004288204]**, despite one fewer top-1 disagreement. It costs **5.88% more ordinary-KV bytes** (13824 versus 13056 bytes/context token without MTP). It was rejected and **is not included**.

**Build/provenance limit:** this diagnostic contrast reused F16/plain captures from historical revision `9df6ea7f`; BF16/block16 and the eight fresh byte-exact spotchecks per reference arm used `054fd833`. These are separate build identities from the earlier three-arm screen above, even where aggregate values coincide. Eight spotchecks do not prove all 144 rows identical under that new executable; residual source/epoch confounding lies outside the bootstrap CIs. These are historical diagnostics, not 144 newly recaptured F16/plain rows on R3.

## Larger historical plain-q8 screen

An earlier source generation evaluated **1152 positions across 18 histories**. This is not a matched before/after comparison with the smaller screen.

| Metric | Plain q8 versus F16 |
| --- | ---: |
| Mean KL | 0.00295170 |
| Mean-KL upper 95% bound | 0.00578105 |
| p99 KL | 0.0287409 |
| Maximum KL | 1.75884145 |
| Top-1 agreement | 97.8299% (25/1152 disagreements) |
| Target ΔNLL | +0.00153216 |
| ΔNLL upper 95% bound | +0.00433905 |

Five positions above KL 0.1 contributed about 73.6% of summed KL. The worst, long tool-JSON position **32823**, contributed about 51.7%. The smaller screen does not show that this tail disappeared.

### Selected tail controls: sensitivity, not a codec verdict

Fresh Gufo controls reproduced plain-q8 KL **1.75884** and the winner change **23429 → 1405**. Rounding **K alone F16 → BF16 → F16**, with V kept F16 throughout the prefix, also flipped that winner at KL **1.70017**. The F16 winner led by 1.81564 logits, so this is not merely a final-logit near tie.

A separate cold control at llama.cpp **338fce65** gave:

| llama.cpp arm versus its own cold F16 | KL at position 32823 | Top-1 disagreement |
| --- | ---: | --- |
| Plain q8, rotation disabled | 0.439238 | No |
| Default rotated q8 | 1.691804 | Yes |

The engines' F16 distributions already differ on this row; similar tail KL or the same final token would not establish a shared mechanism. These purposeful controls show fragility to the tested perturbations, **not sensitivity to every small perturbation, proof of a codec defect, or proof that the codec is defect-free**. They do not erase the measured tail or establish distribution-wide equivalence.

Four purposeful Gufo rows also tested block16 (tail KL 1.44844), full K/V rotation (3.37959), K-only rotation (2.01346) and unfused plain projection (1.75884). None removed the tail flip. Fused/unfused plain logits were byte-identical on those four rows only, not a resolution of the full-screen route confound.

Saved activations first differed at attention layer 3, followed by changed sparse-selection and expert sets. All 24 saved F16/plain selection masks matched an independent sort of their own scores. Changed inputs, recurrence and discrete selection may amplify one another; their causal contributions remain unisolated.

## Approximate WikiText reference

Separate single-chunk llama.cpp measurements at the same pin used:

| Arm | Mean KL, 4K | Mean KL, 32K |
| --- | ---: | ---: |
| Plain q8 | 0.018891 | 0.018793 |
| Default rotated q8 | 0.016809 | 0.019046 |
| BF16 K+V | 0.018149 | 0.018888 |

This BF16 K+V arm is not Gufo's K-only control. The tool saves full-vocabulary reference logits in **quantized uint16 form with a 16-logit floor**, excludes sufficiently small reconstructed probabilities and does not renormalize retained mass. KL is approximate, not interchangeable with full-F32 cold-prefix scoring.

The 32K path uses a disclosed **tool-only streaming adaptation**, not the stock executable. At 4K, its saved reference was byte-identical and printed metrics matched stock; core/model/backend code was unmodified. Different depths score different positions. The 32K F16 self-reference itself has mean KL **0.001143**, with cause unisolated. It is **not an additive error budget to subtract** from q8 KL.

## Original criteria and remaining verdict

The preregistered overall limits were mean-KL upper95 ≤0.001, p99 ≤0.01, max ≤0.1, top-1-disagreement upper95 ≤0.005 and ΔNLL upper95 ≤0.002. Per-category limits were 0.002 / 0.02 / 0.1 / 0.01 / 0.005. These are the experiment's internal criteria, not upstream requirements or a universal q8 standard.

Both 144-position arms missed the original strict numeric screen. The 1152-position plain arm missed all five overall limits: its ΔNLL point met 0.002, but its upper bound did not. Underpowered long categories remain without a full quality verdict. Low average error and the larger screen's approximately 97.8% agreement are useful experimental progress, **not release qualification**.

The historical greedy-prefix diagnostic diverged at median 33.5/128 tokens, minimum 2; its original failed verdict remains. Free-running text identity is not semantic accuracy, and coherent output alone is not equivalence.

Long-agent task quality, MTP/reuse quality and statistical non-inferiority remain unproved. Final candidate native checks are tracked separately in [reproduction](reproduce.md#candidate-validation-status); they cannot turn historical gate failures into passes.
