"""Generate a static scientific figure and concise report from saved RX results."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import NullLocator
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "reports/2026-09-05-device-check")
    args = parser.parse_args()
    runs = [json.loads(p.read_text()) for p in args.runs]
    cases = [(r, c) for r in runs for c in r["cases"] if c["status"] == "completed"]
    args.output.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), layout="constrained")
    ax = axes[0]
    for overflow, color, label in [(False, "#13755b", "No FIFO overflow recorded"), (True, "#b74635", "FIFO overflow recorded")]:
        selected = [c for _, c in cases if c.get("fifo_overflow_observed") == overflow and c["id"].startswith("rate_")]
        ax.scatter([c["readback"]["stream_sample_rate_hz"]/1e6 for c in selected],
                   [c["host_delivery_msps"] for c in selected], color=color, s=55, label=label, zorder=3)
    ax.plot([2, 65], [2, 65], linestyle="--", color="#89939d", label="Host keeps up with sample clock")
    ax.set(xscale="log", yscale="log", xlabel="Configured complex sample rate (MS/s)", ylabel="Measured host delivery (MS/s)",
           title="Host delivery limits wideband streaming", xlim=(2, 70), ylim=(2, 70))
    ax.set_xticks([2.5, 5, 10, 20, 61.44], labels=["2.5", "5", "10", "20", "61.44"])
    ax.set_yticks([2.5, 5, 10, 20, 61.44], labels=["2.5", "5", "10", "20", "61.44"])
    ax.xaxis.set_minor_locator(NullLocator())
    ax.yaxis.set_minor_locator(NullLocator())
    ax.grid(alpha=0.15)
    ax.legend(loc="upper left", fontsize=8)
    ax = axes[1]
    repeats = [c for _, c in cases if c["id"] == "repeat_5msps"]
    if repeats:
        c = repeats[-1]
        wall = np.cumsum(c["refill_seconds"])
        ax.plot(wall, [m["rms_dbfs"] for m in c["block_metrics"]], color="#285884", linewidth=1)
        ax.set(xlabel="Elapsed host capture time (s)", ylabel="Received complex power (dBFS)",
               title="5 MS/s repeat: ambient power varies")
        ax.text(0.02, 0.98, "Antenna attached; operator nearby.\nVariation is not a geometric measurement.", transform=ax.transAxes,
                va="top", fontsize=9, bbox={"facecolor":"white", "edgecolor":"none", "alpha":0.9})
    ax.grid(alpha=0.15)
    fig.suptitle("PlutoSDR · Position 1 · Receive-only device check", fontsize=15, fontweight="bold")
    fig.savefig(args.output / "overview.png", dpi=160)
    plt.close(fig)
    lines = ["# Position 1: device and receive-path check", "", "Date: 2026-09-05 (Asia/Jerusalem). Asset: RFL-SDR-001.", "",
             "The Pluto receives successfully. Use 5 MS/s as the conservative streaming baseline: a 13.4-second repeat had no recorded FIFO overflow. A short 6 MS/s run also passed; 7 MS/s and higher tested rates overflowed. The host path plateaued around 6.43–6.49 MS/s. This experiment does not produce a room map.", "",
             "![Measured host delivery and ambient power](overview.png)", "", "## Observations", "",
             "| Run / condition | Actual rate (MS/s) | RX filter setting (MHz) | Host delivery (MS/s) | FIFO overflow | Rail hits |", "|---|---:|---:|---:|:---:|---:|"]
    for run, c in cases:
        s = c["readback"]
        lines.append(f"| {run['run_id'].split('_')[-1]} / {c['id']} | {s['stream_sample_rate_hz']/1e6:.3f} | {s['rf_bandwidth_hz']/1e6:g} | {c['host_delivery_msps']:.3f} | {'Yes' if c['fifo_overflow_observed'] else 'No'} | {c['rail_component_count']} |")
    lines += ["", "## Meaning and limits", "",
              "- The AD9364 compatibility profile reports 70 MHz–6 GHz RX tuning and up to 56 MHz of RX filter bandwidth. A 56 MHz setting was accepted at 61.44 MS/s; RF response and usable bandwidth were not calibrated.",
              "- Firmware is v0.32. The configured oscillator reference is 39,999,977 Hz. That is configuration metadata, not a measurement of clock error. The physical clock source and lock state were not independently verified.",
              "- Measurements use 262,144 complex samples per buffer, four kernel buffers, manual gain, and a receive center of 2.400 GHz. No transmit waveform or TX buffer was created.",
              "- TX LO powerdown, maximum attenuation (−89.75 dB setting), and zero/disabled DDS were enforced. RX settings were restored after every suite; TX was left muted. Software mute verification is not a calibrated measurement of radiated emissions.",
              "- The FIFO overflow indicator is bit 2 of ADC core UI_STATUS, at register 0x88 through the driver’s 0x80000000 address selector. It was cleared before each timed run. Overflow proves a transfer issue; its exact sample locations and lost sample count are unknown.",
              "- Clean FIFO status and matching delivery rate do not prove end-to-end sample continuity without a hardware counter, timestamps, or known test sequence. Startup buffers were excluded from timing.",
              "- There were no observed digital rail hits or out-of-format samples. This does not exclude analog compression. Power is digital dBFS, not calibrated dBm; the attached antenna precludes a noise-figure measurement.",
              "- The user sat near the antennas and could move or leave. Ambient traffic, body movement, and receiver effects are not separated. Gain comparisons are qualitative and do not establish calibrated gain accuracy.",
              "- One fixed TX/RX pair supplies no independent bearing measurement. Neither a clean spectrum nor this hardware check establishes room dimensions, reflector locations, or permission to transmit.",
              "", "## Reproducibility", "",
              "Raw IQ and private device context remain under ignored `data/local/<run_id>/`. Each JSON identifies raw paths, SHA-256, settings, buffer timings, PSD, and per-buffer statistics. SigMF sidecars retain sample format/rate and explicitly flag unverified continuity. No raw IQ or hardware serial is published.", "",
              "Source code used for each capture is preserved beside its results and checked against `script_sha256`. The combined campaign uses under 1 GiB of raw IQ; the storage budget is 2 GiB. No source, cable, terminator, or antenna calibration was available.", "",
              "Runs:", ""]
    for r, path in zip(runs, args.runs):
        rel = Path("../../experiments") / r["run_id"] / "results.json"
        lines.append(f"- [{r['run_id']}]({rel.as_posix()})")
    lines += ["", "References: [ADI driver register access](https://github.com/analogdevicesinc/linux/blob/2019_R2/drivers/iio/adc/cf_axi_adc_core.c), [ADI overflow register implementation](https://github.com/analogdevicesinc/hdl/blob/hdl_2019_r2/library/common/up_adc_common.v).", ""]
    (args.output / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(args.output / "report.md")


if __name__ == "__main__":
    main()
