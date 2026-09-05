"""RX-only, repeated survey of selected 2.4/5.8 GHz intervals at position 1.

Reports relative observed activity, never labels spectrum legally available or
permanently empty. Fixed manual gain; records overload and finite dwell limits.
"""
import argparse
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import time

import numpy as np
from characterize_rx import ROOT, Receiver, UI_STATUS, OVERFLOW, save_json, utc, iq_metrics


def spectral_summary(iq, fs):
    nfft=2048
    w=np.hanning(nfft)
    f=np.fft.fftshift(np.fft.fftfreq(nfft,1/fs))
    centers=np.arange(-1475000,1500000,50000)
    masks=[(f>=center-25000)&(f<center+25000) for center in centers]
    temporal=[]
    for start in range(0,len(iq),64*nfft):
        a=iq[start:start+64*nfft]
        a=a[:len(a)//(4*nfft)*(4*nfft)]
        if not len(a): continue
        z=a[:,0].astype(float)+1j*a[:,1]
        p=np.abs(np.fft.fft(z.reshape(-1,nfft)*w,axis=1))**2/(fs*np.sum(w*w)*2048**2)
        # Four-window power average (1.6384 ms at 5 MS/s) before temporal maximum.
        p=np.fft.fftshift(p.reshape(-1,4,nfft).mean(axis=1),axes=1)
        temporal.append(np.column_stack([p[:,mask].mean(axis=1) for mask in masks]))
    temporal=np.concatenate(temporal)
    bins=[]
    for index,center in enumerate(centers):
        power=temporal[:,index]
        bins.append([float(center),float(10*np.log10(np.maximum(power.mean(),1e-30))),
                     float(10*np.log10(np.maximum(np.median(power),1e-30))),
                     float(10*np.log10(np.maximum(power.max(),1e-30)))])
    return bins


def capture_tile(r, label, lo, gain, blocks, local, settle=0.06):
    r.rxlo.attrs['frequency'].value=str(int(lo))
    r.rx.attrs['hardwaregain'].value=str(gain)
    r.assert_muted()
    time.sleep(settle)
    n=262144
    for ch in r.rx_channels: ch.enabled=True
    r.adc.set_kernel_buffers_count(4)
    buf=None
    chunks=[]
    start=utc()
    try:
        buf=r.iio.Buffer(r.adc,n,False)
        for _ in range(2): buf.refill(); buf.read()
        r.adc.reg_write(UI_STATUS,OVERFLOW)
        t0=time.perf_counter()
        for _ in range(blocks):
            buf.refill(); raw=buf.read()
            if len(raw)!=n*4: raise RuntimeError('Short RX buffer')
            chunks.append(raw)
        elapsed=time.perf_counter()-t0
        status=r.adc.reg_read(UI_STATUS)
    finally:
        if buf is not None: buf.cancel(); del buf
        r.assert_muted()
    path=local/(label+'.sigmf-data')
    h=hashlib.sha256()
    with path.open('xb') as f:
        for raw in chunks: f.write(raw); h.update(raw)
    iq=np.fromfile(path,dtype='<i2').reshape(-1,2)
    fs=int(r.rx_channels[0].attrs['sampling_frequency'].value)
    actual_lo=int(r.rxlo.attrs['frequency'].value)
    out={'id':label,'started_utc':start,'ended_utc':utc(),'lo_hz':actual_lo,'sample_rate_hz':fs,
         'gain_db':float(r.rx.attrs['hardwaregain'].value.split()[0]),'rf_bandwidth_hz':int(r.rx.attrs['rf_bandwidth'].value),
         'buffer_samples':n,'blocks':blocks,'host_elapsed_s':elapsed,'observed_sample_time_s':len(iq)/fs,
         'ui_status_end':status,'fifo_overflow_observed':bool(status&OVERFLOW),'raw_bytes':path.stat().st_size,
         'raw_relative_path':path.relative_to(ROOT).as_posix(),'sha256':h.hexdigest(),
         'iq_metrics':iq_metrics(iq),'spectrum_columns':['offset_hz','mean_dbfs_per_hz','median_dbfs_per_hz','max_1p6384ms_dbfs_per_hz'],
         'spectrum_50khz_bins':spectral_summary(iq,fs)}
    save_json(path.with_suffix('.sigmf-meta'),{'global':{'core:datatype':'ci16_le','core:version':'1.2.5','core:sample_rate':fs,
        'core:description':'Ambient RF spectrum survey; separate tuning dwell, no continuity between files; possible operator motion.',
        'rfmapping:gain_db':gain,'rfmapping:fifo_overflow_observed':bool(status&OVERFLOW)},
        'captures':[{'core:sample_start':0,'core:frequency':actual_lo}],'annotations':[]})
    return out


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--monitor',nargs='*',type=float,help='Optional fixed RX centers in MHz, 10-second dwell each')
    args=parser.parse_args()
    suffix='monitor' if args.monitor else 'survey'
    run_id=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%M%SZ')+'_'+suffix
    local,public=ROOT/'data/local'/run_id,ROOT/'experiments'/run_id
    local.mkdir(parents=True,exist_ok=False); public.mkdir(parents=True,exist_ok=False)
    source=Path(__file__).read_bytes(); (public/'capture_script.py').write_bytes(source)
    helper=(Path(__file__).parent/'characterize_rx.py').read_bytes(); (public/'receiver_helper.py').write_bytes(helper)
    result={'schema':'rfmapping.spectrum-survey/v1','run_id':run_id,'started_utc':utc(),'receive_only':True,'position':'desk-1',
            'environment':'User is near attached antennas, may move/leave. SDR is near computer and a few feet from a router. Antenna geometry and movement timing unmeasured.',
            'host_wifi_context':{'band':'5 GHz','channel':36,'radio':'802.11ac','reported_signal_percent':92,'note':'Host association, not proof of identity or complete channel use of the nearby router.'},
            'asset_id':'RFL-SDR-001','source_sha256':hashlib.sha256(source).hexdigest(),'receiver_helper_sha256':hashlib.sha256(helper).hexdigest(),
            'intervals_hz':[[2400000000,2483500000],[5725000000,5875000000]],
            'band_choice_reference':'https://wiki.analog.com/university/tools/pluto/users/antennas',
            'gain_db':40,'storage_budget_bytes':2147483648,'tiles':[],
            'limitations':['Receive-only observations are not authorization or assurance that a channel is empty.','Brief swept dwells miss intermittent, weak and hidden signals.','No absolute power, antenna response, or noise calibration.','DC vicinity is excluded during analysis; LO offsets vary between passes.','Nearby router/computer and user motion can affect the observations.'],
            'protocol':'3 interleaved sweeps; 2 x 262144 samples per tuning at 5 MS/s; 4 MHz RX filter; keep central +/-1.5 MHz, exclude +/-50 kHz around DC in analysis; 50 kHz bins. Extra lower-gain recapture on rail clipping.'}
    r=Receiver('ip:192.168.2.1'); r.mute()
    if any(int(r.phy.debug_attrs[k].value.split()[0]) for k in ('bist_prbs','bist_tone','loopback')):
        raise RuntimeError('RX BIST/loopback must be off for an ambient survey')
    result['initial_rx']=r.original
    save_json(public/'results.json',result)
    try:
        r.configure(5000000,4000000,40,2401500000)
        if args.monitor:
            todo=[('monitor_'+str(int(mhz*1000000)),int(mhz*1000000),192,None) for mhz in args.monitor]
        else:
            todo=[]
            for sweep,shift in enumerate([0,1000000,-1000000]):
                groups=[]
                for a,b in result['intervals_hz']:
                    centers=list(range(a+1500000,b,3000000))
                    centers=[max(a+1500000,min(b-1500000,c+shift)) for c in centers]
                    groups.extend(sorted(set(centers),reverse=sweep%2==1))
                for lo in groups: todo.append((f'pass{sweep+1}_{lo}',lo,2,sweep+1))
        for idx,(name,lo,blocks,sweep) in enumerate(todo):
            tile=capture_tile(r,name,lo,40,blocks,local)
            tile['pass']=sweep
            result['tiles'].append(tile)
            if tile['iq_metrics']['rail_component_count']:
                lower=capture_tile(r,name+'_gain20',lo,20,blocks,local)
                lower['pass']=sweep; lower['reason']='Repeat after digital rail clipping at gain 40 dB'
                result['tiles'].append(lower)
            save_json(public/'results.json',result)
            if idx%10==0 or idx==len(todo)-1:
                print(f"{idx+1}/{len(todo)} center={lo/1e6:.3f} MHz rails={tile['iq_metrics']['rail_component_count']} overflow={tile['fifo_overflow_observed']}",flush=True)
    finally:
        result['restore_errors']=r.restore_rx()
        result['final_rx']=r.settings()
        result['final_bist']={k:r.phy.debug_attrs[k].value for k in ('bist_prbs','bist_tone','loopback')}
        result['ended_utc']=utc()
        r.assert_muted()
        save_json(public/'results.json',result)
    print('RESULTS',public/'results.json',flush=True)


if __name__=='__main__': main()
