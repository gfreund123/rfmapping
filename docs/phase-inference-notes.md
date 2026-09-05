# Interpreting frequency steps before room inference

The acquisition saves overlapping windows so that later processing can test and,
where justified, estimate unknown gain, phase and timing changes between tunings.
It does not require position coordinates to record useful observations. Position,
height and orientation can remain unknown quantities in a future inference model.

## Why overlap was retained

AD936x documentation describes independent RX and TX RF synthesizers and separate
configuration/calibration. Sharing the clock does not establish the required
relative RF phase for a sequence of retuned measurements. The manufacturer also
discusses the lack of built-in RF phase synchronization in its hopping support
guidance. [AD9361 reference manual](https://www.analog.com/media/en/technical-documentation/user-guides/ad9361.pdf),
[Analog Devices phase-coherent hopping guidance](https://ez.analog.com/rf/wide-band-rf-transceivers/design-support/f/q-a/80380/ad9361-phase-coherent-hopping/150247).

Published stepped-frequency radar work uses overlapping subbands to estimate
phase discontinuities. This motivates a consistency test here; it does not
establish that this Pluto experiment satisfies those methods' assumptions.
[Gao et al., Experimental results on ISAR imaging with stepped-frequency waveforms](https://doi.org/10.1049/el:20092830),
[KAIST publication record, Phase-Discontinuity Correction Method With an Overlapped Signal Structure](https://pure.kaist.ac.kr/en/publications/phase-discontinuity-correction-method-with-an-overlapped-signal-s-2/).

## The additional saved-data check

`overlap_closure.py` fits pairwise amplitude ratios and linear phase to overlapping
complex-channel estimates. For three consecutive windows A, B and C, it compares
the A/B and B/C fits against the independently fitted A/C overlap. A discrepancy
means these fits do not describe one consistent set of per-window corrections.
Fits are evaluated at a common RF reference before phase wrapping. No propagation
delay is derived from the fitted nuisance slopes.

The first position yielded 190 such triangles across two sweeps. Median absolute
phase closure was 6.19 degrees; median absolute equivalent fit-delay closure was
4.83 ns, rising to 20.47 ns at the 95th percentile. Phase closure was mostly of one
sign across frequency and both sweeps. These are measured fit discrepancies,
not wall delays or calibrated error bars. The numerical controls verify exact
affine consistency and detect a deliberately inconsistent edge.

Position 2 also yielded 190 triangles: median absolute phase closure 6.12 degrees,
median absolute equivalent fit-delay closure 3.63 ns and its 95th percentile
22.21 ns. The similar phase-closure pattern at a different placement motivates
testing a shared instrument/estimator contribution. It does not prove that cause.
[Position 1 closure data](../reports/2026-09-05T221649Z_position-01/closure/closure.json),
[position 2 closure data](../reports/2026-09-05T225813Z_position-02/closure/closure.json).

Baseband filters affect both magnitude and phase; a response tied to offset from
the LO can therefore differ between two windows observing the same RF frequency.
[Analog Devices receive/transmit filtering description](https://wiki.analog.com/resources/eval/user-guides/ad9361).
The repeatable phase discrepancy motivates checking this possibility, alongside
noise and estimator bias. It does not identify the cause by itself.

## What a future blind inference must resolve

### Empirical correction checked at another placement

`phase_shape_diagnostic.py` estimates one cubic phase coefficient in baseband
offset from position 1's median signed triangle closure. The exact overlap
estimator applied to a synthetic cubic phase response gives its scaling. The
coefficient is then fixed for the other placements; no physical channel file is
modified. A known-truth direct-plus-echo numerical control verifies removal of a
specified cubic impairment while preserving the simulated echo response.

The fitted coefficient is approximately -0.04412 radians per MHz cubed. It reduces
position 1's median absolute phase closure from 6.188 to 0.241 degrees and the
held-out position 2's from 6.124 to 0.273 degrees. This supports a repeatable
measurement contribution but does not identify its physical source. The 95th
percentiles of equivalent fit-delay closure remain 20.48 and 22.29 ns. These are
consistency residuals, not room echoes or calibrated uncertainty bounds.
[Two-position correction check](../reports/phase-shape-validation/phase-shape.json).

The unchanged coefficient also reduces the final position 3's median absolute
phase closure from 6.211 to 0.268 degrees. Its 95th-percentile fit-delay closure
remains 22.27 ns. Several individual high-frequency fits have much larger
residuals, retained in the full results. No uncertainty threshold was calibrated
to convert these discrepancies into distance errors.
[All-three-position check](../reports/phase-shape-three-positions/phase-shape.json).

### Remaining requirements

- Test reproducibility of spectral structure across independent sweeps and spots.
- Test whether a shared instrument-response model explains overlap discrepancies
  on data withheld from fitting; retain model residuals and sensitivity.
- Distinguish fit consistency from physical calibration. Overall gain, phase and
  delay remain ambiguous even when pairwise fits are consistent.
- Evaluate candidate echoes against direct coupling, radio/antenna response,
  operator effects, unknown positions and large orientation uncertainty.
- Validate any resulting geometric hypotheses with synthetic known-truth cases
  and additional real measurements before presenting a room map.

The present comparison and closure tools report measured structure and remaining
ambiguity. They do not fill unknown coordinates with invented estimates.
