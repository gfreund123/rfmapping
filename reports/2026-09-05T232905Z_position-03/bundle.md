# position-03: complete RF bundle review

Third and final operator-chosen spot. SDR rotated approximately 30-60 degrees counterclockwise relative to spot 1, as described by imagining spot 1 turning counterclockwise. Location and height withheld for blind RF inference; antenna geometry unmeasured.

Acquisition ready to move: **True**. Geometry inference remains **unvalidated**.

The main and reference-control stages saved **240 pilot bursts** and **812 raw captures**, totaling **2,690,646,016 bytes**. The recorded reviews verify hashes, sample integrity, pilot evidence, negative controls, required coverage and final state.

All stages verified final TX mute: **True**. Restore errors: []. Total commanded unmute interval: 92.310 seconds.

Raw IQ, TX samples, complex channel estimates and private context are retained locally. The public record contains source snapshots, settings, hashes, quality metrics and annotations.

## Coverage and repeatability

Paired ascending/descending frequency centers: **97 / 97**. Median absolute power difference: **0.3052 dB**; 95th percentile: **0.7590 dB**.

The following reference trains held frequency and filter settings fixed between seven bursts:

| Center | Bursts | Power standard deviation |
|---|---:|---:|
| 5771.5 MHz | 7 | 0.0736 dB |
| 5800.0 MHz | 7 | 0.0702 dB |
| 5853.1 MHz | 7 | 0.0536 dB |

Warnings and deviations remain part of the record:

- 95th percentile forward/reverse power change exceeds 0.5 dB.

The raw power differences and control variability describe technical repeats. They do not isolate instrument drift, operator changes, position or orientation effects. The noise-relative statistic and attenuation controls are detailed in the [main review](report.md).

## Temperature metadata

Median pilot temperature readback: 37.719 C. 0 readbacks differed from this median by more than 8 C. These values remain unchanged in the original data and are flagged in bundle-summary.json. No temperature-based correction was applied.

## Interpretation and retained evidence

Coordinates and height remain unknown where no ground truth was supplied. The RF data are preserved for blind inference, with unknown antenna geometry, instrumental response and capture phase treated explicitly. Acquisition completion does not establish a room map.

![Frequency sweep and quality diagnostics](overview.png)

[Machine-readable bundle](../../experiments/2026-09-05T232905Z_position-03/bundle.json) · [Operator annotations](../../experiments/2026-09-05T232905Z_position-03/operator-events.json) · [Collection protocol](../../docs/position-protocol.md)
