"""Bounded receive-only Pluto characterization. Never creates a TX buffer.

Raw IQ and serial-bearing context remain under ignored data/local/. Public JSON
contains selected, sanitized metadata. Requires libiio 0.x and its Python binding.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
UI_STATUS = 0x80000088
OVERFLOW = 4


def utc():
    return datetime.now(timezone.utc).isoformat()


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def number(value):
    return float(str(value).split()[0])


def iq_metrics(iq):
    """dBFS uses mean |I+jQ|^2 / 2048^2; rails are signed 12-bit."""
    x = iq.astype(np.float64)
    power = np.mean(np.sum(x * x, axis=1))
    mean = x.mean(axis=0)
    return {
        "sample_count": len(iq),
        "min_iq": iq.min(axis=0).tolist(),
        "max_iq": iq.max(axis=0).tolist(),
        "mean_iq": mean.tolist(),
        "rms_dbfs": float(10 * np.log10(max(power, 1e-30) / 2048**2)),
        "dc_power_dbfs": float(10 * np.log10(max(float(mean @ mean), 1e-30) / 2048**2)),
        "rail_component_count": int(np.count_nonzero((iq <= -2048) | (iq >= 2047))),
        "outside_12bit_count": int(np.count_nonzero((iq < -2048) | (iq > 2047))),
        "zero_pair_fraction": float(np.mean(np.all(iq == 0, axis=1))),
    }


def spectrum(iq, fs, nfft=4096):
    z = iq[:, 0].astype(np.float64) + 1j * iq[:, 1]
    frames = z[:len(z) // nfft * nfft].reshape(-1, nfft)
    w = np.hanning(nfft)
    # Integrated two-sided PSD equals complex power / full-scale squared.
    psd = np.mean(abs(np.fft.fft(frames * w, axis=1))**2, axis=0)
    psd /= fs * np.sum(w*w) * 2048**2
    return np.fft.fftshift(np.fft.fftfreq(nfft, 1/fs)), np.fft.fftshift(psd)


class Receiver:
    def __init__(self, uri):
        import iio
        self.iio = iio
        self.ctx = iio.Context(uri)
        self.ctx.set_timeout(10000)
        self.phy = self.ctx.find_device("ad9361-phy")
        self.adc = self.ctx.find_device("cf-ad9361-lpc")
        self.dds = self.ctx.find_device("cf-ad9361-dds-core-lpc")
        if any(d is None for d in (self.phy, self.adc, self.dds)):
            raise RuntimeError("Expected Pluto IIO devices are missing")
        self.rx = self.phy.find_channel("voltage0", False)
        self.rxlo = self.phy.find_channel("altvoltage0", True)
        self.tx = self.phy.find_channel("voltage0", True)
        self.txlo = self.phy.find_channel("altvoltage1", True)
        self.rx_channels = sorted([c for c in self.adc.channels if c.scan_element], key=lambda c: c.index)
        if len(self.rx_channels) != 2:
            raise RuntimeError("This probe expects exactly two I/Q scan elements")
        for ch in self.rx_channels:
            f = ch.data_format
            if not (f.bits == 12 and f.length == 16 and f.shift == 0 and f.is_signed and not f.is_be):
                raise RuntimeError("Unsupported sample format; inspect before decoding")
        self.original = self.settings()
        self.original_enabled = [c.enabled for c in self.rx_channels]

    def mute(self):
        self.txlo.attrs["powerdown"].value = "1"
        self.tx.attrs["hardwaregain"].value = "-89.75"
        for ch in self.dds.channels:
            if ch.id.startswith("altvoltage"):
                ch.attrs["scale"].value = "0"
                ch.attrs["raw"].value = "0"
        self.assert_muted()

    def assert_muted(self):
        if self.txlo.attrs["powerdown"].value != "1" or number(self.tx.attrs["hardwaregain"].value) != -89.75:
            raise RuntimeError("TX mute state changed")
        if any(number(c.attrs["scale"].value) != 0 or number(c.attrs["raw"].value) != 0
               for c in self.dds.channels if c.id.startswith("altvoltage")):
            raise RuntimeError("DDS mute state changed")

    def settings(self):
        return {
            "rx_lo_hz": int(self.rxlo.attrs["frequency"].value),
            "sample_rate_hz": int(self.rx.attrs["sampling_frequency"].value),
            "stream_sample_rate_hz": int(self.rx_channels[0].attrs["sampling_frequency"].value),
            "rf_bandwidth_hz": int(self.rx.attrs["rf_bandwidth"].value),
            "gain_mode": self.rx.attrs["gain_control_mode"].value,
            "gain_db": number(self.rx.attrs["hardwaregain"].value),
            "fir_enabled": self.rx.attrs["filter_fir_en"].value,
            "port": self.rx.attrs["rf_port_select"].value,
            "tx_lo_powerdown": self.txlo.attrs["powerdown"].value,
            "tx_attenuation_setting_db": number(self.tx.attrs["hardwaregain"].value),
        }

    def configure(self, fs, bandwidth, gain, lo):
        self.mute()
        self.rx.attrs["gain_control_mode"].value = "manual"
        self.rx.attrs["sampling_frequency"].value = str(fs)
        self.rx_channels[0].attrs["sampling_frequency"].value = self.rx.attrs["sampling_frequency"].value
        self.rx.attrs["rf_bandwidth"].value = str(bandwidth)
        self.rxlo.attrs["frequency"].value = str(lo)
        self.rx.attrs["hardwaregain"].value = str(gain)
        self.mute()
        time.sleep(0.15)

    def restore_rx(self):
        o = self.original
        # Do not undo the protective TX mute. Restore RX settings even after errors.
        errors = []
        for channel, key, value in [
            (self.rx, "gain_control_mode", "manual"),
            (self.rx, "sampling_frequency", o["sample_rate_hz"]),
            (self.rx_channels[0], "sampling_frequency", o["stream_sample_rate_hz"]),
            (self.rx, "rf_bandwidth", o["rf_bandwidth_hz"]),
            (self.rxlo, "frequency", o["rx_lo_hz"]),
            (self.rx, "hardwaregain", o["gain_db"]),
            (self.rx, "gain_control_mode", o["gain_mode"]),
        ]:
            try:
                channel.attrs[key].value = str(value)
            except Exception as exc:
                errors.append(f"{key}: {exc}")
        for ch, enabled in zip(self.rx_channels, self.original_enabled):
            ch.enabled = enabled
        self.mute()
        return errors

    def capture(self, case, local, n, blocks):
        fs, bw, gain = case["sample_rate_hz"], case["bandwidth_hz"], case["gain_db"]
        self.configure(fs, bw, gain, case["lo_hz"])
        settings = self.settings()
        if abs(settings["stream_sample_rate_hz"] / fs - 1) > 0.0001:
            raise RuntimeError("Unexpected streaming decimation or rate")
        for ch in self.rx_channels:
            ch.enabled = True
        self.adc.set_kernel_buffers_count(4)
        buf = None
        chunks, times = [], []
        result = {"id": case["id"], "requested": case, "readback": settings, "started_utc": utc(),
                  "buffer_samples": n, "kernel_buffers": 4, "requested_blocks": blocks}
        try:
            buf = self.iio.Buffer(self.adc, n, False)
            if buf.step != 4:
                raise RuntimeError(f"Unexpected I/Q buffer stride: {buf.step}")
            for _ in range(2):
                buf.refill()
                buf.read()
            result["ui_status_before_clear"] = self.adc.reg_read(UI_STATUS)
            # Clear only the documented sticky RX FIFO overflow bit, not any RF register.
            self.adc.reg_write(UI_STATUS, OVERFLOW)
            result["ui_status_start"] = self.adc.reg_read(UI_STATUS)
            start = time.perf_counter()
            for _ in range(blocks):
                t0 = time.perf_counter()
                buf.refill()
                raw = buf.read()
                times.append(time.perf_counter() - t0)
                if len(raw) != n * 4:
                    raise RuntimeError(f"Short RX buffer: {len(raw)} != {n*4}")
                chunks.append(raw)
            elapsed = time.perf_counter() - start
            result["ui_status_end"] = self.adc.reg_read(UI_STATUS)
            result["host_capture_elapsed_s"] = elapsed
            result["host_delivery_msps"] = len(chunks) * n / elapsed / 1e6
            result["sampled_time_s_if_contiguous"] = len(chunks) * n / settings["stream_sample_rate_hz"]
            result["refill_seconds"] = times
            result["fifo_overflow_observed"] = bool(result["ui_status_end"] & OVERFLOW)
            result["status"] = "completed"
        except Exception as exc:
            result["status"] = "failed"
            result["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            if buf is not None:
                buf.cancel()
                del buf
            self.assert_muted()
        # Disk and DSP are outside the streaming timing measurement.
        raw_path = local / (case["id"] + ".sigmf-data")
        digest = hashlib.sha256()
        block_metrics = []
        psd_sum = None
        with raw_path.open("xb") as out:
            for raw in chunks:
                out.write(raw)
                digest.update(raw)
                iq = np.frombuffer(raw, dtype="<i2").reshape(-1, 2)
                block_metrics.append(iq_metrics(iq))
                freq, psd = spectrum(iq, settings["stream_sample_rate_hz"])
                psd_sum = psd if psd_sum is None else psd_sum + psd
        result["received_blocks"] = len(chunks)
        result["raw_relative_path"] = str(raw_path.relative_to(ROOT)).replace("\\", "/")
        result["sha256"] = digest.hexdigest()
        result["raw_bytes"] = raw_path.stat().st_size
        result["block_metrics"] = block_metrics
        if block_metrics:
            result["rail_component_count"] = sum(m["rail_component_count"] for m in block_metrics)
            result["outside_12bit_count"] = sum(m["outside_12bit_count"] for m in block_metrics)
            result["rms_dbfs_min_median_max"] = [float(f([m["rms_dbfs"] for m in block_metrics])) for f in (np.min, np.median, np.max)]
            result["mean_psd_dbfs_per_hz"] = (10*np.log10(np.maximum(psd_sum/len(chunks), 1e-30))).tolist()
            result["psd_offsets_hz"] = freq.tolist()
        result["ended_utc"] = utc()
        meta = {"global": {"core:datatype": "ci16_le", "core:sample_rate": settings["stream_sample_rate_hz"],
                           "core:version": "1.2.5", "core:sha512": hashlib.sha512(raw_path.read_bytes()).hexdigest(),
                           "core:description": "RX-only characterization; 12-bit signed IQ in int16. Buffer boundaries may have gaps. Host start time is not a hardware timestamp.",
                           "rfmapping:buffer_samples": n, "rfmapping:continuity_verified": False,
                           "rfmapping:fifo_overflow_observed": result.get("fifo_overflow_observed")},
                "captures": [{"core:sample_start": 0, "core:frequency": settings["rx_lo_hz"]}], "annotations": []}
        save_json(raw_path.with_suffix(".sigmf-meta"), meta)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", default="ip:192.168.2.1")
    parser.add_argument("--lo", type=int, default=2400000000, help="Receive center only; no transmission")
    parser.add_argument("--suite", choices=("smoke", "full", "threshold"), default="full")
    args = parser.parse_args()
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ") + "_" + args.suite
    local = ROOT / "data/local" / run_id
    local.mkdir(parents=True, exist_ok=False)
    public = ROOT / "experiments" / run_id
    public.mkdir(parents=True, exist_ok=False)
    receiver = Receiver(args.uri)
    receiver.mute()
    save_json(local / "context-private.json", receiver.ctx.attrs)
    (local / "context-private.xml").write_text(receiver.ctx.xml, encoding="utf-8")
    selected_attrs = {k:v for k,v in receiver.ctx.attrs.items() if k in
                      ("hw_model", "fw_version", "ad9361-phy,xo_correction", "ad9361-phy,model", "local,kernel")}
    summary = {"schema": "rfmapping.rx-characterization/v1", "run_id": run_id, "started_utc": utc(),
               "asset_id": "RFL-SDR-001", "receive_only": True, "antenna": "User-reported standard Pluto antenna attached to RX; TX antenna also attached",
               "environment": "Indoors on desk. Operator seated near antenna and may move or leave during collection; motion not timestamped. No calibrated source or terminator.",
               "ground_truth": None, "host_timezone": "Asia/Jerusalem", "context": selected_attrs,
               "python": sys.version.split()[0], "libiio": receiver.iio.version, "backend": receiver.ctx.version,
               "packages": {p:importlib.metadata.version(p) for p in ("numpy", "matplotlib", "pylibiio")},
               "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "original_rx_settings": receiver.original,
               "reported_ranges": {k:receiver.rx.attrs[k].value for k in ("sampling_frequency_available", "rf_bandwidth_available", "hardwaregain_available")},
               "rx_lo_range": receiver.rxlo.attrs["frequency_available"].value,
               "clock_note": "xo_correction is configured reference frequency, not measured accuracy; physical reference source and lock are unverified.",
               "adc_core_version": hex(receiver.adc.reg_read(0x80000000)),
               "limits": ["Ambient recordings do not measure absolute noise figure, calibrated gain, filter transfer function, or sample-clock accuracy.",
                          "No hardware timestamps or sample counter: clean overflow status alone does not prove end-to-end sample continuity.",
                          "FIFO bit is sticky and can include control/read latency at the endpoints. Repeat or controlled pattern needed to localize losses.",
                          "Full-scale rail counts do not exclude analog front-end compression.",
                          "No spectrum occupancy survey, phase-coherence test, ranging, or mapping performed."],
               "register_sources": ["https://github.com/analogdevicesinc/linux/blob/2019_R2/drivers/iio/adc/cf_axi_adc_core.c",
                                    "https://github.com/analogdevicesinc/hdl/blob/hdl_2019_r2/library/common/up_adc_common.v"],
               "cases": []}
    cases = []
    rates = [2500000] if args.suite == "smoke" else ([2500000, 3000000, 3500000, 4000000, 4500000, 5000000] if args.suite == "threshold" else [2500000, 5000000, 10000000, 20000000, 30720000, 61440000])
    for fs in rates:
        cases.append({"id": f"rate_{fs}", "sample_rate_hz":fs, "bandwidth_hz":min(int(fs*0.8), 56000000), "gain_db":40, "lo_hz":args.lo, "blocks":8 if args.suite=="smoke" else 48})
    if args.suite == "full":
        cases[-1]["bandwidth_hz"] = 56000000
        for gain in [20, 60]:
            cases.append({"id":f"gain_{gain}", "sample_rate_hz":2500000, "bandwidth_hz":2000000, "gain_db":gain, "lo_hz":args.lo, "blocks":16})
        cases.append({"id":"repeat_low_rate", "sample_rate_hz":2500000, "bandwidth_hz":2000000, "gain_db":40, "lo_hz":args.lo, "blocks":96})
    summary["protocol"] = cases
    summary["success_criteria"] = ["Every requested buffer returns expected length", "No out-of-format samples", "Record rail clipping and RX FIFO overflow per condition", "At least one low-rate run completes without RX FIFO overflow", "Final TX mute verified and RX settings restored"]
    save_json(public / "results.json", summary)
    try:
        for case in cases:
            print(f"START {case['id']}", flush=True)
            try:
                result = receiver.capture(case, local, 262144, case["blocks"])
            except Exception as exc:
                result = {"id":case["id"], "status":"failed", "error":f"{type(exc).__name__}: {exc}"}
            summary["cases"].append(result)
            save_json(public / "results.json", summary)
            print(json.dumps({k:v for k,v in result.items() if k in ("id", "status", "error", "host_delivery_msps", "fifo_overflow_observed", "rail_component_count", "rms_dbfs_min_median_max")}), flush=True)
    finally:
        summary["restore_errors"] = receiver.restore_rx()
        summary["final_settings"] = receiver.settings()
        receiver.assert_muted()
        summary["final_tx_mute_verified"] = True
        summary["ended_utc"] = utc()
        save_json(public / "results.json", summary)
        print(f"RESULTS {public / 'results.json'}", flush=True)
    return 1 if summary["restore_errors"] or any(c["status"] != "completed" for c in summary["cases"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
