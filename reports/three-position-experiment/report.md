# Three-position RF experiment: collection complete, geometry unresolved

All three requested placements were collected and verified. The data record RF responses and their variation at three acquisition states. They do not currently support a defensible floor plan, wall distances or placement coordinates.

The bundles retain **722 RF pilot bursts**, **2441 raw captures** and **8,086,618,112 bytes** of verified raw capture data. This includes two retained partial-control bursts at spot 1; 720 of the 720 full-profile main/reference bursts across three spots were completed. Final TX mute was verified for every stage.

Position 1 is the orientation reference. Position 2 was reported roughly 140–220 degrees rotated, with direction unspecified. Position 3 was reported 30–60 degrees counterclockwise from position 1. Locations and heights were withheld for blind inference. Those unknowns remain unknown.

![Three measured RF responses](overview.png)

Shading spans the observed pair of sweeps, not a confidence interval. Frequency windows overlap and the two sweeps are technical repeats.

## Measurement summary

| Position | Paired centers | Median absolute sweep difference | 95th percentile | Held-reference SDs |
|---|---:|---:|---:|---|
| position-01 | 97 | 0.304 dB | 0.670 dB | 0.015, 0.043, 0.049 dB |
| position-02 | 97 | 0.323 dB | 0.903 dB | 0.039, 0.088, 0.041 dB |
| position-03 | 97 | 0.305 dB | 0.759 dB | 0.074, 0.070, 0.054 dB |

| Comparison | Median power difference, second minus first | Frequency-dependent RMS after removing median |
|---|---:|---:|
| position-02 minus position-01 | 1.423 dB | 1.061 dB |
| position-03 minus position-01 | 1.007 dB | 0.838 dB |
| position-03 minus position-02 | -0.129 dB | 0.419 dB |

Positions 2 and 3 have relatively similar measured responses despite the reported orientation difference. Similarity does not establish proximity. Position, orientation, instrument response, operator state and elapsed time all changed or may have changed. The differences cannot be assigned solely to distance or room structure.

## Why a wall map is not established

The complex responses retain unknown timing and carrier phase between tunings. A cubic phase term tied to offset within each frequency window was fitted from position 1 only, then applied unchanged to positions 2 and 3. It substantially reduces a shared three-window phase inconsistency:

| Position | Role | Median absolute phase closure before / after | 95th-percentile fit-delay closure after |
|---|---|---:|---:|
| position-01 | training | 6.188 / 0.241 degrees | 20.48 ns |
| position-02 | held-out placement | 6.124 / 0.273 degrees | 22.29 ns |
| position-03 | held-out placement | 6.211 / 0.268 degrees | 22.27 ns |

This is evidence for a repeatable measurement contribution, not a physical identification of the filter or a calibration of absolute delay. The remaining fit-delay discrepancies are not reflection delays or calibrated range error bars. Position 3 also contains individual large closure residuals at the weaker high-frequency end; all are retained. Original channel samples remain unchanged.

A separate power-ripple analysis searched 7–200 ns trial delays with three smooth-baseline orders, both raw and noise-relative metrics, both sweep directions and blocked prediction checks. Its sensitivity results are:

| Position | Descriptive stability screen | Preferred trial-delay range across choices |
|---|---|---:|
| position-01 | fails | 7.00–118.50 ns |
| position-02 | fails | 7.00–30.50 ns |
| position-03 | fails | 7.00–47.75 ns |

These trial values are **not measured wall ranges**. The method recovered a known simulated 35 ns weak echo, but a smooth no-echo response also passed its stability screen with roughly 8–12 ns fits. The negative-control failure is retained in the validation record; the method is not a validated echo detector. A distinct sparse-delay example also demonstrates identical Fourier power from different delay sets.

This does not prove that RF room mapping is impossible. It means this dataset and the tested models have not separated room echoes from measurement response strongly enough to identify geometry. The raw complex samples remain available for additional offline models; no extra placement is requested.

## Records

- [position-01 bundle](../2026-09-05T221649Z_position-01/bundle.md), [phase consistency](../2026-09-05T221649Z_position-01/closure/closure.json), [fringe sensitivity](../2026-09-05T221649Z_position-01/fringe/fringe.json).
- [position-02 bundle](../2026-09-05T225813Z_position-02/bundle.md), [phase consistency](../2026-09-05T225813Z_position-02/closure/closure.json), [fringe sensitivity](../2026-09-05T225813Z_position-02/fringe/fringe.json).
- [position-03 bundle](../2026-09-05T232905Z_position-03/bundle.md), [phase consistency](../2026-09-05T232905Z_position-03/closure/closure.json), [fringe sensitivity](../2026-09-05T232905Z_position-03/fringe/fringe.json).
- [Synthetic method validation](../../experiments/2026-09-05_fringe-method-validation/results.json).
- [Magnitude-inference method and limitations](../../docs/magnitude-inference.md).
- [Phase inference notes](../../docs/phase-inference-notes.md).
- [Correction trained on spot 1 and checked on spots 2 and 3](../phase-shape-three-positions/phase-shape.json).
- [Position registry](../../experiments/positions.json).
