# Experimental q8 KV cache

Qwen3.8 Flash-Next on AMD Strix Halo (gfx1151), with historical UD-Q4_K_XL measurements dated October 27, 2026.

We compress ordinary attention K/V, not model weights. **F16 remains the runtime default.** Select plain `--kv-cache-type q8_0` when memory margin matters, or evaluate `--kv-cache-type q8_0-rotated` as a separate trade-off. Both are always compiled into the normal HIP build; neither rotation nor the eligible plain-q8 prefill view has a separate build option.

## Read by question

| Question | Page |
| --- | --- |
| How much does the output distribution change? What do controls show? | [Quality](quality.md) |
| What memory/capacity was measured, and under which configuration? | [Memory — authoritative capacity data](memory.md) |
| How close was prefill to F16, and what remains slower? | [Speed](speed.md) |
| What is stored, rotated, reconstructed and restored? | [Design](design.md) |
| Where should these results not be generalized? | [Limitations](limitations.md) |
| How do I enable it, and what has the candidate actually passed? | [Reproduction and validation](reproduce.md) |

## Evidence at a glance

- **Payload:** ordinary K/V retains 53.125% of F16 bytes. Eligible plain-q8 view scratch is 2 KiB × min(configured context, WMMA cap 262144), shared per executor: 390.625 MiB at context 200000, at most 512 MiB for supported geometry.
- **Historical capacity:** four live 199400-token prompts plus 256 outputs each had 9.324 GiB lower sampled peak GTT with plain q8; F16 also fit. That experiment predates the view. It is not a fresh combined net-memory measurement; consult [memory](memory.md) for capacity results.
- **Historical speed:** four view-enabled 8K/32K cells ranged −0.57% to +3.57% prefill throughput versus same-binary F16. Short ordered observations do not establish statistical non-inferiority.
- **Historical quality:** 144 positions / 18 histories gave mean KL 0.00137127 plain / 0.000946485 rotated and 141/144 top-1 agreement each. Rotated-minus-plain target-NLL CI is positive. The larger 1152-position plain screen, BF16-K/block16 diagnostics and protocol-limited llama.cpp references are retained in [quality](quality.md).

These are different source generations and protocols, not one fully qualified configuration. BF16-K and block16 distribution references are complete historical diagnostics, not pending experiments; block16 was rejected and is not included. No equivalence or long-agent task non-inferiority has been proved. Original strict gate failures remain.

## Candidate boundary

Current candidate: `816de7f4a7da101e8ab111aa09a984b576421d66`, stacked on the separate two-line YaRN correction `b0c25b01`, based on upstream `c92b19c5` (#850, removal of lossy chunked DeltaNet prefill). Current payloads are 19 for F16/plain and 20 for rotated; old version-18 caches rebuild once. Both modes persist to disk.

CPU checks and baseline-matched failures are revision-specific. Final native validation passed; see the [status table](reproduce.md#candidate-validation-status).

[Back to the fork overview](../../README.md)
