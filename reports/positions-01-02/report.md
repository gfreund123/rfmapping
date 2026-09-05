# RF comparison: position-01 and position-02

This compares two measured acquisition states. Position, orientation, operator effects and acquisition time can differ. The result cannot attribute differences solely to position or convert them directly into wall ranges.

- position-01: First multi-position capture at the original desk location.
- position-02: Operator placed setup at spot 2. Reported SDR rotation approximately 140-220 degrees relative to spot 1; axis and direction unspecified. Position, height and antenna geometry unmeasured. Combined position-and-orientation comparison.

Common frequency centers with both sweep directions: **97**.

![Measured comparison](comparison.png)

Shading covers the observed pair of sweeps at each position and their possible differences. It is not a confidence interval. Frequency windows overlap, and two sweeps do not establish long-term stability.

| Statistic | Raw transfer power | Relative to averaging noise |
|---|---:|---:|
| Median change, second minus first | 1.4232 dB | 1.4564 dB |
| RMS frequency-dependent change after removing median | 1.0615 dB | 0.9896 dB |
| 95th percentile absolute frequency-dependent change after removing median | 1.8807 dB | 1.8158 dB |

The noise-relative statistic may reduce common receiver-gain variation but is not independent calibration. Channel variation can enter its noise estimate. Removing the median separates a broad level change from frequency-dependent structure descriptively; it does not identify the cause of either component.

The strongest use of these data at this stage is to test repeatability and seek reproducible spectral structure across further positions. Coordinates, radio/antenna response, direct coupling, room paths, operator effects and retune phase remain unresolved. A floor plan requires a separately validated inference model.

Inputs: `2026-09-05T221649Z_position-01`, `2026-09-05T225813Z_position-02`.
Both input acquisition bundles passed their recorded reviews; their warnings are retained in comparison.json.
