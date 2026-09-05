# Power-fringe inference: a tested limitation

The RF collection retains complex responses, but phase continuity across tuning
steps is not established. A separate exploratory analysis tests what the power
measurements can support without assuming that continuity. This is a sensitivity
study, not a validated echo detector or room solver.

For a direct path plus one weaker delayed path, an idealized response is
`H(f) = a0 + a1 exp(-j 2 pi f tau)`. Its power contains a sinusoidal cross-term.
For a sufficiently weak second path, this produces an approximately sinusoidal
ripple in dB. A ripple fit can therefore propose a trial delay, but the physical
interpretation requires distinguishing propagation from instrument response.

The scripts fit a Legendre-polynomial baseline of degree 1, 2 or 3 plus sine and
cosine terms at trial delays from 7 to 200 ns in 0.25 ns steps. The fine trial grid
is not a resolution claim. Both sweep directions and both raw power and the
noise-relative statistic are retained. Three interleaved sets of contiguous
eight-center blocks test prediction in the opposite sweep. A constant sweep
offset is estimated using training frequencies only.

The descriptive stability screen requires delay preferences to agree within an
inverse-bandwidth interval, excludes search-boundary preferences, requires at
least 10% reduction in blocked prediction squared error for every baseline/metric choice, and
limits variation across block fits. Overlapping windows and two sweeps do not
provide independent statistical trials; these are not confidence bounds.

## Synthetic controls and the failed specificity expectation

A known direct-plus-echo control uses a 35 ns excess delay and a reflected voltage
of 0.075 relative to the direct component. Its exact complex power is averaged
over the pilot's occupied frequency offsets before conversion to dB. A smooth
gain trend, independent 0.035 dB noise and a 0.1 dB reverse-sweep offset are added
with a fixed seed. Preferred delays are 34.75–35 ns.

A second control contains **no echo**: its smooth response includes a tanh bend
plus the same noise and sweep-offset levels. It nevertheless passes all the
descriptive stability checks, producing preferred delays around 8–12 ns.
The initial unit expectation that this control would be rejected failed. That
counterexample is retained, and the method is explicitly disqualified as an echo
detector. No physical-data threshold was tuned to hide this failure.

Another control changes the ripple between sweeps and fails the stability screen.
The numerical tests also verify that two different sparse delay sets can produce
the same Fourier power: `[0, 1, 4, 10, 12, 17]` and `[0, 1, 8, 11, 13, 17]`, each
scaled by 5 ns and with equal path amplitudes. These are toy impulse responses,
not proposed room geometries or a model of the measured antennas.

The broader nonuniqueness of one-dimensional Fourier magnitude recovery, and
conditions under which added information can resolve it, are treated in
[Bendory, Beinert and Eldar, Fourier Phase Retrieval: Uniqueness and Algorithms](https://arxiv.org/abs/1705.09590)
and [Huang, Eldar and Sidiropoulos, Phase Retrieval from 1D Fourier Measurements](https://arxiv.org/abs/1603.05215).
Those results do not imply that every constrained RF mapping experiment is
unidentifiable. Here they reinforce the need to validate the actual assumptions.

## Implication for this experiment

A stable numerical ripple fit would still not establish a wall. An unstable fit
provides less support. Unknown gain/antenna response, finite bandwidth, retuned
phase and missing placement coordinates must be handled jointly before assigning
room dimensions. All raw IQ and complex estimates remain available for further
offline approaches.

[Full synthetic controls, truth, impairments and source hashes](../experiments/2026-09-05_fringe-method-validation/results.json).
