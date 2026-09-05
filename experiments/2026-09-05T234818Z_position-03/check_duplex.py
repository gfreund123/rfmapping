"""Bounded low-level RF calibration in the specifically surveyed 5771.5 MHz window.

User authorized low-power tests in unoccupied spectrum excluding cellular/GNSS.
The script performs a fresh receive check before RF, uses >=45 dB TX attenuation
plus digital backoff, and caps each burst with a separate-context mute timer.
This is an alignment/leakage experiment, not a range measurement.
"""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import threading
import time

import numpy as np
from characterize_rx import ROOT, Receiver, UI_STATUS, OVERFLOW, save_json, utc, iq_metrics
from survey_spectrum import capture_tile

FS=5000000
LO=5771500000
PERIOD=4096


def pilot():
    rng=np.random.default_rng(9062026)
    freq=np.fft.fftfreq(PERIOD,1/FS)
    mask=(np.abs(freq)>=100000)&(np.abs(freq)<=900000)
    bins=np.zeros(PERIOD,dtype=complex)
    bins[mask]=np.exp(1j*(np.pi/4+np.pi/2*rng.integers(0,4,mask.sum())))
    z=np.fft.ifft(bins)
    z*=8192/np.max(np.maximum(abs(z.real),abs(z.imag)))
    iq=np.round(np.column_stack((z.real,z.imag))).astype('<i2')
    return iq


def analyze_pilot(iq,tx):
    z=iq[:,0].astype(float)+1j*iq[:,1]
    frames=z[:len(z)//PERIOD*PERIOD].reshape(-1,PERIOD)
    x=tx[:,0].astype(float)+1j*tx[:,1]
    xf=np.fft.fft(x)
    candidates=[]
    for conjugate in [False,True]:
        f=np.conj(frames) if conjugate else frames
        corr=np.fft.ifft(np.fft.fft(f,axis=1)*np.conj(xf),axis=1)
        idx=np.argmax(abs(corr),axis=1)
        peaks=corr[np.arange(len(corr)),idx]
        rho=abs(peaks)/np.sqrt(np.maximum(np.sum(abs(f)**2,axis=1)*np.sum(abs(x)**2),1e-30))
        candidates.append((float(np.median(rho)),conjugate,idx,peaks,rho))
    quality,conjugate,idx,peaks,rho=max(candidates,key=lambda x:x[0])
    phase=np.unwrap(np.angle(peaks))
    t=np.arange(len(phase))*PERIOD/FS
    fit=np.polyfit(t,phase,1)
    residual=phase-np.polyval(fit,t)
    return {'period_samples':PERIOD,'period_count':len(frames),'conjugated_rx_for_match':conjugate,
            'median_normalized_correlation':quality,'correlation_min_max':[float(rho.min()),float(rho.max())],
            'alignment_sample_indices':idx.tolist(),'unique_alignment_indices':np.unique(idx).tolist(),
            'phase_slope_hz':float(fit[0]/(2*np.pi)),
            'phase_residual_rms_deg':float(np.sqrt(np.mean(residual**2))*180/np.pi),
            'phase_note':'Phase metrics are meaningful only when correlation and a stable alignment establish detection; capture origin is arbitrary.',
            'geometric_note':'Alignment includes unknown streaming and RF delays; cannot be converted to room range. Conventional resolution at 1.8 MHz span is about 83 m.'}


def read_burst(r,blocks=4):
    n=262144; buf=None; chunks=[]
    for ch in r.rx_channels: ch.enabled=True
    r.adc.set_kernel_buffers_count(4)
    try:
        buf=r.iio.Buffer(r.adc,n,False)
        for _ in range(2): buf.refill(); buf.read()
        r.adc.reg_write(UI_STATUS,OVERFLOW)
        for _ in range(blocks):
            buf.refill(); raw=buf.read()
            if len(raw)!=4*n: raise RuntimeError('Short receive buffer')
            chunks.append(raw)
        status=r.adc.reg_read(UI_STATUS)
    finally:
        if buf is not None: buf.cancel(); del buf
    return b''.join(chunks),status


def main():
    run_id=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%M%SZ')+'_duplex-calibration'
    local,public=ROOT/'data/local'/run_id,ROOT/'experiments'/run_id
    local.mkdir(parents=True,exist_ok=False); public.mkdir(parents=True,exist_ok=False)
    for name in ('check_duplex.py','characterize_rx.py','survey_spectrum.py'):
        (public/name).write_bytes((Path(__file__).parent/name).read_bytes())
    result={'schema':'rfmapping.duplex-calibration/v1','run_id':run_id,'started_utc':utc(),
            'asset_id':'RFL-SDR-001','position':'desk-1','receive_only':False,
            'authorization':'User authorized low-power laboratory transmission in non-active spectrum, excluding cellular and GNSS.',
            'environment':'Standard attached antennas near computer and router; operator may move. Geometry not measured.',
            'frequency_selection':'5771.5 MHz center, after three passive sweeps and a 10-second fixed-frequency recording; fresh RX guard check below.',
            'tx_limits':{'center_hz':LO,'nominal_pilot_span_hz':1800000,'digital_peak_component':8192,'dac_container_full_scale':32768,
                         'minimum_attenuation_db':45,'burst_watchdog_s':0.8,'maximum_planned_bursts':8,
                         'power_note':'Hardware attenuation and digital level are recorded; radiated power is not calibrated. No amplifier.'},
            'source_sha256':{name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest() for name in ('check_duplex.py','characterize_rx.py','survey_spectrum.py')},
            'cases':[]}
    tx=pilot(); txpath=local/'pilot-ci16.bin'; txpath.write_bytes(tx.tobytes())
    result['pilot_sha256']=hashlib.sha256(tx.tobytes()).hexdigest()
    result['pilot_component_rms_dbfs']=float(10*np.log10(np.mean(np.sum(tx.astype(float)**2,axis=1))/32768**2))
    r=Receiver('ip:192.168.2.1'); r.mute()
    result['initial_rx']=r.original
    original_tx={k:r.tx.attrs[k].value for k in ('rf_bandwidth','hardwaregain')}
    original_tx['lo']=r.txlo.attrs['frequency'].value
    # Independent context so a stalled main data call does not own the mute path.
    watchdog_ctx=r.iio.Context('ip:192.168.2.1'); watchdog_ctx.set_timeout(1000)
    watchdog_lo=watchdog_ctx.find_device('ad9361-phy').find_channel('altvoltage1',True)
    txchannels=sorted([c for c in r.dds.channels if c.scan_element],key=lambda c:c.index)
    original_enabled=[c.enabled for c in txchannels]
    if len(txchannels)!=2: raise RuntimeError('Expected one complex TX channel')
    if any(int(r.phy.debug_attrs[k].value.split()[0]) for k in ('bist_prbs','bist_tone','loopback')):
        raise RuntimeError('BIST and loopback must be disabled')
    save_json(public/'results.json',result)
    try:
        r.configure(FS,2400000,40,LO)
        r.tx.attrs['rf_bandwidth'].value='2400000'
        r.txlo.attrs['frequency'].value=str(LO)
        guard=capture_tile(r,'fresh_receive_guard',LO,40,20,local)
        result['fresh_receive_guard']=guard
        rows=np.array(guard['spectrum_50khz_bins'])
        relevant=(abs(rows[:,0])<=1250000)&(abs(rows[:,0])>50000)
        excess=float(np.max(rows[relevant,3])-np.median(rows[relevant,2]))
        result['fresh_guard_max_excess_db']=excess
        # Also reject a uniformly raised spectrum, which a relative-only check misses.
        result['fresh_guard_absolute_limit_dbfs_per_hz']=-114
        if excess>8 or np.max(rows[relevant,3])>-114 or guard['fifo_overflow_observed'] or guard['iq_metrics']['rail_component_count']:
            raise RuntimeError('Fresh receive guard did not pass; no RF burst started')
        baseline_raw,status=read_burst(r)
        baseline_iq=np.frombuffer(baseline_raw,dtype='<i2').reshape(-1,2)
        baseline=analyze_pilot(baseline_iq,tx)
        path=local/'tx_off.sigmf-data'; path.write_bytes(baseline_raw)
        result['baseline']={'analysis':baseline,'ui_status_end':status,'sha256':hashlib.sha256(baseline_raw).hexdigest(),'raw_relative_path':path.relative_to(ROOT).as_posix()}
        print('BASELINE correlation',baseline['median_normalized_correlation'],'guard excess',excess,flush=True)
        successful_gain=None
        # Gain ladder stops once a reliable match appears, then repeats at that level.
        gains=[-75,-65,-55,-45]
        while gains:
            gain=gains.pop(0)
            name=f'burst{len(result["cases"])+1}_gain{abs(gain)}'
            r.mute()
            r.tx.attrs['hardwaregain'].value=str(gain)
            for ch in txchannels: ch.enabled=True
            txbuf=None; timer=None; fired=threading.Event(); watchdog_errors=[]
            def mute_timeout():
                fired.set()
                try: watchdog_lo.attrs['powerdown'].value='1'
                except Exception as exc: watchdog_errors.append(str(exc))
            case={'id':name,'gain_setting_db':gain,'started_utc':utc()}
            on_start=None
            try:
                txbuf=r.iio.Buffer(r.dds,PERIOD,True)
                if txbuf.step!=4: raise RuntimeError('Unexpected TX sample stride')
                if txbuf.write(bytearray(tx.tobytes()))!=tx.nbytes: raise RuntimeError('Short TX buffer write')
                txbuf.push()
                # DDS remains zero; only the known DMA pilot is selected by buffer setup.
                timer=threading.Timer(0.8,mute_timeout); timer.daemon=True; timer.start()
                on_start=time.perf_counter()
                r.txlo.attrs['powerdown'].value='0'
                raw,status=read_burst(r)
            finally:
                r.txlo.attrs['powerdown'].value='1'
                if on_start is not None: case['host_measured_unmuted_interval_s']=time.perf_counter()-on_start
                if timer is not None: timer.cancel(); timer.join(timeout=1.2)
                if txbuf is not None: txbuf.cancel(); del txbuf
                r.mute()
            case['watchdog_fired']=fired.is_set(); case['watchdog_errors']=watchdog_errors
            iq=np.frombuffer(raw,dtype='<i2').reshape(-1,2)
            case['analysis']=analyze_pilot(iq,tx); case['iq_metrics']=iq_metrics(iq)
            case['fifo_overflow_observed']=bool(status&OVERFLOW)
            case['tx_lo_readback_hz']=int(r.txlo.attrs['frequency'].value)
            case['rx_lo_readback_hz']=int(r.rxlo.attrs['frequency'].value)
            path=local/(name+'.sigmf-data'); path.write_bytes(raw)
            case['raw_relative_path']=path.relative_to(ROOT).as_posix(); case['sha256']=hashlib.sha256(raw).hexdigest()
            case['raw_bytes']=len(raw); case['ended_utc']=utc()
            case['pilot_detected']=bool(case['analysis']['median_normalized_correlation']>max(0.15,5*baseline['median_normalized_correlation']))
            save_json(path.with_suffix('.sigmf-meta'),{'global':{'core:datatype':'ci16_le','core:version':'1.2.5','core:sample_rate':int(r.rx_channels[0].attrs['sampling_frequency'].value),'core:description':'Low-level full-duplex coded pilot; not calibrated range or power.'},'captures':[{'core:sample_start':0,'core:frequency':case['rx_lo_readback_hz']}],'annotations':[]})
            result['cases'].append(case); save_json(public/'results.json',result)
            print(json.dumps({'id':name,'rho':case['analysis']['median_normalized_correlation'],'detected':case['pilot_detected'],'phase_rms_deg':case['analysis']['phase_residual_rms_deg'] if case['pilot_detected'] else None,'alignment_count':len(case['analysis']['unique_alignment_indices']),'unmuted_s':case['host_measured_unmuted_interval_s'],'rails':case['iq_metrics']['rail_component_count']}),flush=True)
            if fired.is_set() or watchdog_errors or case['fifo_overflow_observed'] or case['iq_metrics']['rail_component_count']:
                raise RuntimeError('Burst timing or sample integrity limit reached; TX is muted')
            if case['pilot_detected'] and successful_gain is None:
                successful_gain=gain
                gains=[gain]*3
            time.sleep(0.3)
        result['detected_gain_db']=successful_gain
        result['status']='completed'
    except Exception as exc:
        result['status']='failed'
        result['error']=f'{type(exc).__name__}: {exc}'
        raise
    finally:
        r.mute()
        r.txlo.attrs['frequency'].value=original_tx['lo']
        r.tx.attrs['rf_bandwidth'].value=original_tx['rf_bandwidth']
        for ch,enabled in zip(txchannels,original_enabled): ch.enabled=enabled
        result['restore_errors']=r.restore_rx()
        result['final_rx']=r.settings()
        result['final_bist']={k:r.phy.debug_attrs[k].value for k in ('bist_prbs','bist_tone','loopback')}
        result['ended_utc']=utc()
        r.assert_muted(); result['final_tx_mute_verified']=True
        save_json(public/'results.json',result)
    print('RESULTS',public/'results.json',flush=True)


if __name__=='__main__': main()
