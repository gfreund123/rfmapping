"""Validate host IQ order using the AD936x internal RX-only PRBS generator.

The recurrence and I/Q reconstruction follow ADI's BIST FAQ and PN checker.
No TX buffer or RF loopback is used. A periodic PRBS cannot reveal losses of
exactly a whole pattern period. Raw data and source snapshots are preserved.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from characterize_rx import ROOT, Receiver, UI_STATUS, OVERFLOW, save_json, utc


def reverse_bits(x, width):
    y = np.zeros_like(x, dtype=np.uint16)
    for bit in range(width):
        y |= ((x >> bit) & 1) << (width - 1 - bit)
    return y


def next_state(x, direction):
    x = np.asarray(x, dtype=np.uint16)
    parity = np.zeros_like(x)
    taps = list(range(4, 16)) + [1, 2] if direction == "left" else list(range(12)) + [13, 14]
    for bit in taps:
        parity ^= (x >> bit) & 1
    return ((x << 1) | parity).astype(np.uint16) if direction == "left" else ((x >> 1) | (parity << 15)).astype(np.uint16)


def reconstruct(iq, swap=False, sign_xor=False):
    v = iq.astype(np.uint16) & 0xfff
    if sign_xor:
        v = v ^ 0x800
    i, q = (v[:, 1], v[:, 0]) if swap else (v[:, 0], v[:, 1])
    qr = reverse_bits(q, 12)
    return ((i << 4) | (qr & 15)).astype(np.uint16), (i & 255) == (qr >> 4)


def analyze(iq, buffer_samples):
    # Select the documented orientation using only a short prefix, then validate
    # every subsequent sample with the fixed mapping, including buffer boundaries.
    candidates = []
    for swap in [False, True]:
        for sign_xor in [False, True]:
            state, overlap = reconstruct(iq[:4096], swap, sign_xor)
            for direction in ["left", "right"]:
                score = np.mean(overlap) + np.mean(next_state(state[:-1], direction) == state[1:])
                candidates.append((float(score), swap, sign_xor, direction))
    score, swap, sign_xor, direction = max(candidates)
    state, overlap = reconstruct(iq, swap, sign_xor)
    bad = np.flatnonzero(next_state(state[:-1], direction) != state[1:]) + 1
    at_boundary = bad % buffer_samples == 0
    return {"mapping_prefix_samples": min(4096,len(iq)), "mapping_score_maximum_2":score,
            "swap_iq":swap, "sign_bit_xor":sign_xor, "recurrence_direction":direction,
            "sample_count":len(iq), "iq_overlap_mismatches":int(np.count_nonzero(~overlap)),
            "transition_mismatches":len(bad), "boundary_transition_mismatches":int(at_boundary.sum()),
            "within_buffer_transition_mismatches":int((~at_boundary).sum()),
            "first_mismatch_sample_indices":bad[:32].tolist(),
            "distinct_states":len(np.unique(state)),
            "pattern_recognized":bool(score > 1.99),
            "all_checked_transitions_valid":bool(score > 1.99 and not len(bad) and np.all(overlap)),
            "limitation":"Periodic sequence: losses or repetitions of whole sequence periods may be invisible; not a unique absolute sample counter."}


def main():
    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ") + "_rx-prbs"
    local, public = ROOT/"data/local"/run_id, ROOT/"experiments"/run_id
    local.mkdir(parents=True, exist_ok=False)
    public.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).read_bytes()
    (public/"capture_script.py").write_bytes(source)
    helper=(Path(__file__).parent/"characterize_rx.py").read_bytes()
    (public/"receiver_helper.py").write_bytes(helper)
    r = Receiver("ip:192.168.2.1")
    r.mute()
    debug = r.phy.debug_attrs
    original = {k:debug[k].value for k in ("bist_prbs","bist_tone","loopback")}
    if any(int(v.split()[0]) for v in original.values()):
        raise RuntimeError("A BIST or loopback mode was already active; inspect before changing it")
    result={"schema":"rfmapping.rx-prbs/v1", "run_id":run_id,"started_utc":utc(),
            "receive_only":True,"asset_id":"RFL-SDR-001","injection":"AD936x RX digital data port; RF path bypassed",
            "initial_bist":original,"source_sha256":hashlib.sha256(source).hexdigest(),
            "receiver_helper_sha256":hashlib.sha256(helper).hexdigest(), "initial_rx":r.original,
            "references":["https://github.com/analogdevicesinc/linux/blob/2019_R2/drivers/iio/adc/ad9361.c",
                          "https://github.com/analogdevicesinc/hdl/blob/hdl_2019_r2/library/axi_ad9361/axi_ad9361_rx_pnmon.v",
                          "https://ez.analog.com/cfs-file/__key/communityserver-wikis-components-files/00-00-00-02-20/AD9361BISTFAQ.pdf"],
            "cases":[],"success_criteria":"Recognized documented PRBS with no I/Q overlap or transition errors at 5 MS/s; overload positive control detects losses at 7 MS/s."}
    save_json(public/"results.json",result)
    try:
        for name,fs,blocks in [("baseline_5msps",5000000,64),("overload_7msps",7000000,32),("repeat_5msps",5000000,64)]:
            r.configure(fs,4000000,40,2400000000)
            debug["bist_prbs"].value="2"
            # Direct register READ confirms PRBS selected at RX injection point.
            bist_register=r.phy.reg_read(0x3f4)
            if bist_register & 15 != 9:
                raise RuntimeError(f"Unexpected BIST register {hex(bist_register)}")
            r.assert_muted()
            for ch in r.rx_channels: ch.enabled=True
            r.adc.set_kernel_buffers_count(4)
            n=262144
            buf=None
            chunks=[]
            case={"id":name,"settings":r.settings(),"started_utc":utc(),"bist_register":hex(bist_register),"buffer_samples":n,"requested_blocks":blocks}
            print("START",name,flush=True)
            try:
                buf=r.iio.Buffer(r.adc,n,False)
                if buf.step !=4: raise RuntimeError("Unexpected sample stride")
                for _ in range(2): buf.refill(); buf.read()
                r.adc.reg_write(UI_STATUS,OVERFLOW)
                t0=time.perf_counter()
                for _ in range(blocks):
                    buf.refill(); raw=buf.read()
                    if len(raw)!=4*n: raise RuntimeError("Short RX buffer")
                    chunks.append(raw)
                case["elapsed_s"]=time.perf_counter()-t0
                case["ui_status_end"]=r.adc.reg_read(UI_STATUS)
            finally:
                if buf is not None: buf.cancel(); del buf
                debug["bist_prbs"].value="0"
                r.assert_muted()
            raw_path=local/(name+".sigmf-data")
            h=hashlib.sha256()
            with raw_path.open("xb") as f:
                for raw in chunks: f.write(raw); h.update(raw)
            iq=np.fromfile(raw_path,dtype="<i2").reshape(-1,2)
            case.update(analyze(iq,n))
            case["fifo_overflow_observed"]=bool(case["ui_status_end"] & OVERFLOW)
            case["raw_relative_path"]=raw_path.relative_to(ROOT).as_posix()
            case["raw_bytes"]=raw_path.stat().st_size
            case["sha256"]=h.hexdigest()
            case["ended_utc"]=utc()
            save_json(raw_path.with_suffix(".sigmf-meta"),{"global":{"core:datatype":"ci16_le","core:version":"1.2.5","core:sample_rate":case["settings"]["stream_sample_rate_hz"],"core:description":"Internal RX PRBS, not an RF recording; consult results for continuity errors."},"captures":[{"core:sample_start":0}],"annotations":[]})
            result["cases"].append(case)
            save_json(public/"results.json",result)
            print(json.dumps({k:case[k] for k in ("id","sample_count","pattern_recognized","iq_overlap_mismatches","transition_mismatches","boundary_transition_mismatches","fifo_overflow_observed")}),flush=True)
    finally:
        debug["bist_prbs"].value="0"
        result["restore_errors"]=r.restore_rx()
        result["final_bist"]={k:debug[k].value for k in original}
        result["final_rx"]=r.settings()
        result["ended_utc"]=utc()
        r.assert_muted()
        save_json(public/"results.json",result)
    print("RESULTS",public/"results.json",flush=True)


if __name__=="__main__": main()
