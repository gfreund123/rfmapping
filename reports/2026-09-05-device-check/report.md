# Position 1: device and receive-path check

Date: 2026-09-05 (Asia/Jerusalem). Asset: RFL-SDR-001.

The Pluto receives successfully. Use 5 MS/s as the conservative streaming baseline: a 13.4-second repeat had no recorded FIFO overflow. A short 6 MS/s run also passed; 7 MS/s and higher tested rates overflowed. The host path plateaued around 6.43–6.49 MS/s. This experiment does not produce a room map.

![Measured host delivery and ambient power](overview.png)

## Observations

| Run / condition | Actual rate (MS/s) | RX filter setting (MHz) | Host delivery (MS/s) | FIFO overflow | Rail hits |
|---|---:|---:|---:|:---:|---:|
| smoke / rate_2500000 | 2.500 | 2 | 2.508 | No | 0 |
| full / rate_2500000 | 2.500 | 2 | 2.502 | No | 0 |
| full / rate_5000000 | 5.000 | 4 | 5.006 | No | 0 |
| full / rate_10000000 | 10.000 | 8 | 6.489 | Yes | 0 |
| full / rate_20000000 | 20.000 | 16 | 6.444 | Yes | 0 |
| full / rate_30720000 | 30.720 | 24.576 | 6.449 | Yes | 0 |
| full / rate_61440000 | 61.440 | 56 | 6.493 | Yes | 0 |
| full / gain_20 | 2.500 | 2 | 2.506 | No | 0 |
| full / gain_60 | 2.500 | 2 | 2.505 | No | 0 |
| full / repeat_low_rate | 2.500 | 2 | 2.501 | No | 0 |
| threshold / rate_5000000 | 5.000 | 4 | 5.007 | No | 0 |
| threshold / rate_6000000 | 6.000 | 4.8 | 6.010 | No | 0 |
| threshold / rate_7000000 | 7.000 | 5.6 | 6.431 | Yes | 0 |
| threshold / repeat_5msps | 5.000 | 4 | 5.001 | No | 0 |

## Meaning and limits

- The AD9364 compatibility profile reports 70 MHz–6 GHz RX tuning and up to 56 MHz of RX filter bandwidth. A 56 MHz setting was accepted at 61.44 MS/s; RF response and usable bandwidth were not calibrated.
- Firmware is v0.32. The configured oscillator reference is 39,999,977 Hz. That is configuration metadata, not a measurement of clock error. The physical clock source and lock state were not independently verified.
- Measurements use 262,144 complex samples per buffer, four kernel buffers, manual gain, and a receive center of 2.400 GHz. No transmit waveform or TX buffer was created.
- TX LO powerdown, maximum attenuation (−89.75 dB setting), and zero/disabled DDS were enforced. RX settings were restored after every suite; TX was left muted. Software mute verification is not a calibrated measurement of radiated emissions.
- The FIFO overflow indicator is bit 2 of ADC core UI_STATUS, at register 0x88 through the driver’s 0x80000000 address selector. It was cleared before each timed run. Overflow proves a transfer issue; its exact sample locations and lost sample count are unknown.
- Clean FIFO status and matching delivery rate do not prove end-to-end sample continuity without a hardware counter, timestamps, or known test sequence. Startup buffers were excluded from timing.
- There were no observed digital rail hits or out-of-format samples. This does not exclude analog compression. Power is digital dBFS, not calibrated dBm; the attached antenna precludes a noise-figure measurement.
- The user sat near the antennas and could move or leave. Ambient traffic, body movement, and receiver effects are not separated. Gain comparisons are qualitative and do not establish calibrated gain accuracy.
- One fixed TX/RX pair supplies no independent bearing measurement. Neither a clean spectrum nor this hardware check establishes room dimensions, reflector locations, or permission to transmit.

## Reproducibility

Raw IQ and private device context remain under ignored `data/local/<run_id>/`. Each JSON identifies raw paths, SHA-256, settings, buffer timings, PSD, and per-buffer statistics. SigMF sidecars retain sample format/rate and explicitly flag unverified continuity. No raw IQ or hardware serial is published.

Source code used for each capture is preserved beside its results and checked against `script_sha256`. The combined campaign uses under 1 GiB of raw IQ; the storage budget is 2 GiB. No source, cable, terminator, or antenna calibration was available.

Runs:

- [2026-09-05T204923Z_smoke](../../experiments/2026-09-05T204923Z_smoke/results.json)
- [2026-09-05T204934Z_full](../../experiments/2026-09-05T204934Z_full/results.json)
- [2026-09-05T205028Z_threshold](../../experiments/2026-09-05T205028Z_threshold/results.json)

References: [ADI driver register access](https://github.com/analogdevicesinc/linux/blob/2019_R2/drivers/iio/adc/cf_axi_adc_core.c), [ADI overflow register implementation](https://github.com/analogdevicesinc/hdl/blob/hdl_2019_r2/library/common/up_adc_common.v).
