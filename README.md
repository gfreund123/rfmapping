# RF room mapping experiments

Reproducible experiments with one ADALM-PlutoSDR and its supplied TX/RX antennas.
The objective is to investigate which room properties can be inferred from RF
measurements, starting at one fixed desk position and later adding known positions.

## Latest: position 1 departure and return test

[Read the scene-change report](reports/2026-09-06-scene-change/report.md).

- Eight pilot bursts in each condition: seated baseline, instructed departure
  interval, then returned to the seat. Equipment remained at the same desk position.
- Transfer rose 0.101 dB during the departure interval, about 2.35% in pilot power.
  After returning it remained 0.074 dB above baseline, recovering only 27% of the shift.
- The operator reported a different lean after returning. This pose mismatch,
  incomplete recovery and unmeasured drift make the presence effect inconclusive.
- All 24 bursts completed without recorded clipping or FIFO overflow. Total
  commanded TX-unmute time was 9.15 seconds; TX was muted and RX settings restored.
- Raw IQ, exact acquisition sources, hashes, timing and the posture deviation are
  preserved. No wall ranges, bearings or floor plan have been inferred.

![Departure and return measurements](reports/2026-09-06-scene-change/overview.png)

## Position 1 preflight

[Read the spectrum, sample-integrity and duplex report](reports/2026-09-06-preflight/report.md).

- RX-internal PRBS checked 33.6 million samples at 5 MS/s without a sequence error;
  the 7 MS/s overload control detected three buffer-boundary skips.
- Repeated passive sweeps found strong 2.4 GHz activity. A seemingly quiet
  2475.5 MHz interval showed bursts on a longer listen and was excluded.
- The monitored 5771.5 and 5853.1 MHz windows showed no comparable excess activity
  during the finite observations. That is not proof of permanent vacancy.
- Seven highly attenuated pilot bursts at 5771.5 MHz used about 2.7 seconds of
  commanded RF-on time. Four repeats at 45 dB TX attenuation produced clear
  matches, without clipping or FIFO overflow. TX is muted again.
- Timing offsets changed after stream restarts. Each subsequent measurement needs
  a reference; the pilot's 1.8 MHz span cannot resolve room-scale reflections.

The nearby computer, router and possibly moving operator are recorded as part of
the setup. No room geometry has been inferred from these preflight measurements.

## Initial device check (5 September 2026)

[Read the measured report](reports/2026-09-05-device-check/report.md).

- Pluto is reachable over its USB network interface; firmware v0.32, AD9364 profile.
- 5 MS/s is the conservative host-streaming rate for the next experiments: a
  13.4-second repeat completed without recorded FIFO overflow. A short 6 MS/s run
  also passed; 7 MS/s and higher tested rates overflowed.
- The receiver accepted a 56 MHz filter setting, but the host cannot continuously
  receive that full bandwidth at its required sample rate. Configured bandwidth
  has not been calibrated with an RF source.
- All 14 conditions returned their requested buffers. No digital rail clipping or
  out-of-format samples were observed. This does not certify analog linearity or
  perfect sample continuity.
- RX settings were restored. TX remains muted: oscillator powered down, attenuation
  at −89.75 dB, DDS disabled and zeroed. No transmit waveform was generated during
  this initial receive-only stage.

![Characterization overview](reports/2026-09-05-device-check/overview.png)

The operator was sitting near the attached antennas and could move during capture.
Ambient changes cannot be interpreted as a stationary room response. This stage
does not measure range or bearing and does not produce a floor plan.

## Run the characterization

Use Python 3.12, a system installation of libiio 0.x, and the packages in
`requirements.txt`. This was tested with libiio 0.26 / pylibiio 0.25 on Windows.

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python scripts/characterize_rx.py --suite smoke
python scripts/characterize_rx.py --suite full
python scripts/characterize_rx.py --suite threshold
```

The default URI is `ip:192.168.2.1`; `--uri` overrides it. The default RX center is
2.400 GHz; `--lo` changes only the receive center. Do not run this while another
application owns the SDR. No firmware, boot variables, reference clock selection,
or persistent device configuration is changed.

Each suite logs requested/readback settings, software identity, host buffer timing,
RX FIFO overflow, per-buffer IQ metrics, power spectra, source hashes and raw-data
hashes. A `finally` block restores RX settings and keeps TX muted. Interrupted or
failed conditions must be inspected in the results; a returned buffer alone does
not certify continuous sampling. The exit status reports software/capture failures,
not expected overflow at deliberately excessive rates.

## Records and next measurements

- `experiments/`: sanitized observations, manifests and exact capture source.
- `data/local/`: ignored raw IQ, SigMF sidecars and private context/serial records.
- `scripts/`: receive capture, internal PRBS, offline analysis and a bounded RF
  calibration script specific to the surveyed 5771.5 MHz window.
- `tests/`: synthetic numerical checks for sample rails and PSD/power scaling.
- `reports/`: generated scientific plots and interpretations.

The next experimental question is repeatability across several departure/return
cycles with marked posture and interleaved seated-to-seated controls. A quiet
receive trace is not sufficient evidence
that a transmit frequency is suitable. The user's exclusions of cellular, GNSS
and occupied spectrum continue to apply.

Additional receive-only checks can be reproduced with:

```powershell
python scripts/check_prbs.py
python scripts/survey_spectrum.py
python scripts/survey_spectrum.py --monitor 5771.5 5853.1 2475.5
python scripts/verify_tx_off.py
```

`check_duplex.py` transmits short cyclic-pilot bursts at the fixed 5771.5 MHz
center after a fresh receive guard check. It enforces at least 45 dB hardware
attenuation, digital backoff, a separate-context mute timer and final cleanup.
It was used under the user's laboratory authorization; its recorded settings do
not constitute a radiated-power calibration or general frequency authorization.

`scene_change.py` uses the same fixed pilot and bounded bursts for three stages,
muting TX while it waits for `B` and `C` on stdin. A controller command starts a
stage; human replies and cue timing must be logged separately. The script stops
and restores settings on EOF, unexpected input or a five-minute input timeout.
`report_scene.py` analyzes the saved results without accessing the SDR.

Several separated quiet frequency intervals cannot automatically be combined into
one coherent wideband measurement. Retuning phase, timing, hardware response and
scene motion need to be measured before interpreting a synthetic delay profile.

A single fixed pair provides no independent bearing. Any future inferred geometry
must state its assumptions and uncertainty, and should be checked using additional
known positions or controlled targets.
