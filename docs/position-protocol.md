# RF collection at multiple positions

Keep the Pluto, antenna angles and antenna spacing fixed relative to each other.
Place the equipment on a stable support. Record a position ID, approximate height,
orientation and distances to two identifiable walls when available. Unknown values
stay unknown; moving to random spots does not itself supply position coordinates.
Use a consistent operator position and posture during each collection.

The assistant gives a settling cue, runs the collection, verifies it, then gives
the move cue. TX is muted during handling and after every bounded burst.

## Per-position bundle

1. Passive 2.4 GHz context, with no transmission in that band.
2. Passive 5.8 GHz survey. Observed occupied intervals are excluded from TX.
3. Three legacy 1.8 MHz pilot captures for continuity with the initial desk tests.
4. 3.6 MHz coded-pilot measurements at up to 97 centers from 5728 to 5872 MHz,
   on a 1.5 MHz overlapping grid, in ascending and descending order.
5. Three repetitions at reference centers 5771.5 and 5853.1 MHz near the start,
   middle and end. Start/end controls add 3 dB attenuation to check gain response.
6. Same-frequency TX-off negative controls after each reference group.
7. Seven further pilot bursts at each of three reference centers, with RX/TX
   frequency and filter settings held steady within each train. This helps assess
   variation introduced by reconfiguration. Each repeat has a TX-off guard over
   the full occupied pilot span; the first has the two offset guards as well.
8. Integrity, coverage, repeatability, attenuation and overlap checks before moving.

Each sweep RF burst has two preceding RX-only checks, at +/-0.6 MHz from its intended
center, using a 3 MHz filter and only the central +/-1.45 MHz. Their useful
regions overlap and cover each other's RX DC gap. The broader receiver-edge
response was measured in a separate receive-only diagnostic and is excluded
from activity decisions. The earlier rejected survey and diagnostic are retained.
Held-reference repeats use the same-frequency guards described in step 7.

The stream rate is 5 MS/s. TX uses at least 45 dB hardware attenuation and digital
power no greater than the earlier pilot. RF is limited to the selected 5.8 GHz
windows; cellular, GNSS and observed occupied intervals remain excluded. Each
burst has a separate-context 0.8-second mute timer. Limits are 240 bursts,
115 seconds total commanded unmute time and a 3 GiB raw capture budget per run.
These settings do not establish radiated power or permanent spectrum vacancy.

## Commands

Print the plan without opening the radio:

```powershell
python scripts/collect_position.py --position-id position-02
```

After the equipment is settled, run the authorized laboratory measurement:

```powershell
python scripts/collect_position.py --position-id position-02 --note "Operator description of the new spot" --execute
```

To stop between bounded bursts, create `STOP_RF_CAPTURE` in the repository root.
The script also restores settings and mutes TX when interrupted. The next run
refuses to start until that file is deliberately removed. Do not run two processes
that access the SDR simultaneously.

Verify saved data without accessing the radio:

```powershell
python scripts/review_position.py experiments/RUN_ID/results.json --verify
```

The `acquisition_ready_to_move` result requires completed acquisition, valid raw
and source hashes, paired RF data, no missing required sweep pairs, usable pilots,
clean TX-off controls and final mute/restore verification. Warnings require review
before a move cue. Acquisition readiness is separate from mapping readiness.

`collect_position.py` runs the primary sweep and held-reference controls in
sequence, then verifies both. The primary profile plans 219 RF bursts; the held
controls add up to 21. Individual stages restore/mute before handing over to the
next stage. `position_capture.py` remains available for the primary stage alone.
The first main sweep took about 19 minutes, including configuration and file
writes. Later runs use compact live metadata, but elapsed time is not guaranteed.
The move cue depends on completion and review, not a fixed countdown.

Windows sharing locks are retried for up to two seconds while TX is muted. A
persistent lock stops acquisition and retains both the previous complete manifest
and its pending replacement. Raw captures are never overwritten. A stopped
reference run can be supplemented at the same unmoved position using:

```powershell
python scripts/hold_reference_controls.py --position-id position-01 --parent-run MAIN_RUN_ID --centers 5800000000 5853100000
```

Offline `verify_controls` accepts an explicit subset of required reference centers.
Its default still requires all three. A metadata-stop recovery must be requested
explicitly and retains the original stopped status; a complete accepted train
requires all seven pilots, unchanged settings and its final TX-off control.
The combined position review must cover all three centers across the retained runs.

A recent complete passive survey can be reused after an interrupted attempt with
`--survey-from experiments/PREVIOUS_RUN/results.json`, only at the same position,
with matching guard settings and an age under 15 minutes. Fresh guards still run
before every transmitted burst. The original raw data and source provenance stay
linked rather than being overwritten or silently relabelled.

## Retained data and interpretation

Raw IQ and deterministic TX samples remain in ignored `data/local/`. Public
records contain hashes, timing, gain/filter/LO settings, temperature, quality
metrics, experiment deviations and exact capture-source snapshots. Per-burst
local NPZ files retain the complex frequency response, variance and quarter-burst
means; phase-processing parameters and the original raw IQ remain available.

No calibrated wall range, bearing or phase continuity is assumed. Overlap fitting
is a diagnostic of consistency after fitting nuisance scale, phase and timing.
A low fitting residual is not independent proof of coherent wideband ranging.
Radio/antenna response, direct coupling, unresolved multipath, operator pose and
position uncertainty must be handled in later inference.

After verification, write the complete bundle summary without accessing the radio:

```powershell
python scripts/report_position_bundle.py experiments/RUN_ID/results.json
```

`compare_positions.py FIRST_RESULTS SECOND_RESULTS --out REPORT_DIRECTORY`
compares common centers only after both bundles are verified. It retains overall
level change, median-removed spectral differences and observed repeat envelopes.
The envelopes are descriptive, not confidence intervals. Unknown coordinates and
large orientation changes stay explicit.

`overlap_closure.py RESULTS --out REPORT_DIRECTORY` checks three-window phase,
gain and nuisance-slope consistency using saved complex responses. Its fitted
delay discrepancies are not propagation delays. See
[phase inference notes](phase-inference-notes.md) for the rationale and limitations.
