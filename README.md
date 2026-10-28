# Gufo fork

This fork adds experimental q8 KV storage for Qwen3.8 Flash-Next on AMD Strix Halo (gfx1151). **F16 remains the default.** q8 offers long-context memory headroom, not guaranteed faster inference or identical output.

## Build from source

Follow the [upstream build requirements](https://github.com/gufo-org/gufo/blob/c92b19c5dc7ec12f83d0c2a5603cda78cc200b3e/README.md#build-from-source), then use the [current fork build and usage commands](docs/q8-kv-cache/reproduce.md). Historical validation used ROCm 7.2.4 / Clang 22; the pinned ROCm 10.1 / Clang 24 stack remains untested for this change.

## Experimental q8 KV cache

Ordinary attention keys and values, including the MTP predictor, use block32 8-bit storage. Indexer keys stay F16; recurrent GDN state stays F32. Model weights are unchanged.

Append one selector to your usual Flash-Next launch arguments:

```sh
--kv-cache-type q8_0          # plain q8; suggested starting point
--kv-cache-type q8_0-rotated  # experimental Hadamard-rotated alternative
```

Both modes are always compiled into the normal HIP build. Eligible plain-q8 matrix prefill uses a shared transient F16 view automatically; there is no rotation or prefill-view build switch or opt-out. See [build and usage](docs/q8-kv-cache/reproduce.md).

- **Memory:** a 512-value K or V row shrinks from 1024 to 544 bytes, not a halving of total RAM. View scratch is shared per executor: 390.625 MiB at context 200000, capped at 512 MiB for supported geometry. See [memory and capacity data](docs/q8-kv-cache/memory.md).
- **Historical capacity:** an earlier view-enabled build completed four 376832-token slots and one 1048576-token slot with YaRN and LIVE follow-up turns. These are not fresh R3, task-quality or evicted-checkpoint results; see the [measured limits](docs/q8-kv-cache/memory.md).
- **Historical speed:** plain-q8 prefill with the view ranged −0.57% to +3.57% versus same-binary F16 across four 8K/32K cells. Decode was about 1% behind at 32K, preliminarily. These are not final-R3 performance measurements. Fork main additionally carries exact MTP-verify kernel speedups (Group4 −14% at n8); see [speed](docs/q8-kv-cache/speed.md#fork-only-decode-verification-speedups-2026-10-28).
- **Historical quality:** a 144-position / 18-history screen gave mean KL 0.00137127 plain / 0.000946485 rotated, with 141/144 top-1 agreement each versus F16. Rotation raised target NLL; it is not uniformly better.

**Upgrade:** version-18 Flash-Next caches, including F16, rebuild once. Current payloads are 19 for F16/plain q8 and 20 for rotated q8; both q8 modes support disk persistence. Incompatible type/epoch identities are rejected.

q8 is lossy. The original strict quality gates were not met, and long-agent task non-inferiority is unproved. Historical measurements do not qualify the final candidate. The [validation table](docs/q8-kv-cache/reproduce.md#candidate-validation-status) still awaits final native results; native assessments are not public approval.

[Documentation index](docs/q8-kv-cache/README.md) · [Quality](docs/q8-kv-cache/quality.md) · [Memory](docs/q8-kv-cache/memory.md) · [Speed](docs/q8-kv-cache/speed.md) · [Design](docs/q8-kv-cache/design.md) · [Limitations](docs/q8-kv-cache/limitations.md)
