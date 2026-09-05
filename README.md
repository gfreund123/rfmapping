# RF room mapping experiments

Reproducible experiments with one ADALM-PlutoSDR and its supplied TX/RX antennas.
The objective is to investigate which room properties can be inferred from RF
measurements, starting at one fixed desk position and later adding known positions.

## Position 1: device check completed

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
  at −89.75 dB, DDS disabled and zeroed. No transmit waveform was generated.

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
- `scripts/`: capture and offline analysis; no TX implementation exists yet.
- `tests/`: synthetic numerical checks for sample rails and PSD/power scaling.
- `reports/`: generated scientific plots and interpretations.

The next experimental questions are usable spectrum at this position, TX/RX
leakage and synchronization, and repeatability of a known scene change. A quiet
receive trace is not sufficient evidence that a transmit frequency is suitable.
Transmission remains a separate experimental stage, subject to the user's
exclusion of cellular, GNSS and occupied spectrum.

Several separated quiet frequency intervals cannot automatically be combined into
one coherent wideband measurement. Retuning phase, timing, hardware response and
scene motion need to be measured before interpreting a synthetic delay profile.

A single fixed pair provides no independent bearing. Any future inferred geometry
must state its assumptions and uncertainty, and should be checked using additional
known positions or controlled targets.
