# Position 1: controlled scene change

6 September 2026, Asia/Jerusalem. Run identifiers and timestamps use UTC. Equipment: RFL-SDR-001 with the supplied TX/RX antennas.

The operator was instructed to remain seated for A, leave the room for B, then return to the original seat for C. The chair, equipment and final door position were to remain unchanged. This is one exploratory A/B/A cycle, using eight technical repeats per condition. The operator subsequently reported leaning slightly differently for C; the return did not reproduce the baseline pose.

![Measured amplitude response](overview.png)

## Measured result

| Condition | Bursts | Mean digital transfer (dB) | Between-burst SD (dB) |
|---|---:|---:|---:|
| A: Seated baseline | 8 | -61.87230 | 0.01638 |
| B: Departure interval | 8 | -61.77147 | 0.00781 |
| C: Returned, different lean | 8 | -61.79823 | 0.01256 |

During the instructed departure interval, measured transfer was **+0.10082 dB** relative to A (+2.35% received pilot power; +1.17% amplitude). After returning, C differed from A by **+0.07407 dB**. The B-minus-C difference was +0.02676 dB.

C recovered only 26.5% of the B-minus-A shift. Although the A and B burst ranges were disjoint, the return failed to recover the original baseline. Together with the reported posture change and the unmeasured drift between conditions, this makes attribution to presence/absence **inconclusive**. No room geometry was inferred.

## Timing and operator observations

| Stage | Start (UTC) | End (UTC) |
|---|---|---|
| A | 2026-09-05T21:27:42.634142+00:00 | 2026-09-05T21:27:52.029150+00:00 |
| B | 2026-09-05T21:28:58.612273+00:00 | 2026-09-05T21:29:08.037138+00:00 |
| C | 2026-09-05T21:32:37.341393+00:00 | 2026-09-05T21:32:47.020719+00:00 |

B started 18.45 seconds and ended 27.87 seconds after the departure cue, within the instructed 30-second absence. There was no live confirmation from outside the room. C followed the operator's return confirmation; their later note identified a different lean. Exact departure, physical return time, pose and door position were not independently measured.

The capture record and raw sidecars originally describe controller commands as operator confirmation. That wording is too strong for the timed B capture; the operator-events sidecar corrects it without changing the original capture record or raw files.

## Measurement method

Each short burst used the same 4096-sample coded pilot, 5771.5 MHz center, 5 MS/s, 1.8 MHz nominal pilot span, 45 dB TX attenuation and 40 dB manual RX gain. The same device context was retained, and each phase began with a receive-only activity check that rewrote the same requested RX frequency and gain. This does not establish internal calibration-state continuity. TX was muted during the waits.

For every burst, the pilot correlation establishes a capture reference. A fitted carrier-phase ramp is removed at sample resolution before coherent averaging. The amplitude transfer is estimated independently at the occupied pilot frequencies; no amplitude normalization removes a real gain change. The estimator subtracts its estimated averaging noise bias. Its digital gain scale is not calibrated RF path loss.

This amplitude statistic is insensitive to arbitrary capture delay and common carrier phase. Synthetic tests verify that integer/fractional delay and phase changes do not create an amplitude change, while a known amplitude change remains measurable. The frequency curves show means in 100 kHz bins, with their between-burst SD recorded in comparison.json; individual small wiggles should not be read as resolved features. The shaded center gap contains no pilot.

## Controls and limits

- A return toward the original response supports an association with the controlled scene change, but one cycle is not a causal proof. Repeated bursts are technical repeats, not independent randomized experiments; their SD is not a population confidence interval.
- Presence/absence and pose rely on operator instructions and replies, not an independent camera or occupancy sensor. Consult the operator-events record for the departure cue, timed collection and return confirmation.
- The operator reported a different lean during C. Exact body pose, door placement, chair placement and antenna geometry were not measured. Nearby computer/router activity, internal calibration state and hardware drift remain possible contributors.
- The received signal combines direct coupling and unresolved multipath. A stronger signal when the person leaves could reflect changed attenuation or interference between paths; it does not identify a wall, location or distance.
- Conventional near-monostatic range resolution for the 1.8 MHz pilot is about 83 m, from c/(2B). This measurement detects response changes; it does not recover room geometry. See the [range-resolution reference in the preflight report](../2026-09-06-preflight/report.md).

## Acquisition state and reproducibility

Recorded 24 bursts, with 9.149 seconds of total host-measured commanded TX-unmute time. FIFO-overflow flags: 0. Digital rail hits: 0. Watchdog expirations: 0.

Final TX mute verified: True. RX restore errors: []. Raw IQ and pilot samples are kept locally under ignored `data/local/`; source snapshots, settings, per-burst metrics and SHA-256 hashes are versioned.

[Acquisition record](../../experiments/2026-09-05T212740Z_scene-aba/results.json) · [Comparison](../../experiments/2026-09-05T212740Z_scene-aba/comparison.json) · [Operator events](../../experiments/2026-09-05T212740Z_scene-aba/operator-events.json) · [Raw integrity and feature replay](../../experiments/2026-09-05T212740Z_scene-aba/verification.json) · [Independent mute readback](../../experiments/2026-09-05T212740Z_scene-aba/final-mute-readback.json)

## Next controlled test

Repeat several short cycles with marked chair and body posture, matching wait durations, and interleaved seated-to-seated controls. That would estimate variation without a departure and test whether a departure effect repeats. A usable room map also needs additional geometric information or measurements; an amplitude change alone supplies neither wall range nor bearing.
