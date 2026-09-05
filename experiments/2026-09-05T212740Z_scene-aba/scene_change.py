"""Fixed-device A/B/A scene experiment, with explicit operator cues on stdin.

Between stages TX is muted and the same RX/LO configuration remains selected.
Commands B and C mean the operator has confirmed a settled position. Input timeout
or EOF stops the session and restores settings. Raw data are never overwritten.
"""
from datetime import datetime,timezone
import hashlib
from pathlib import Path
import queue
import threading
import time

import numpy as np
from characterize_rx import ROOT,Receiver,save_json,utc,iq_metrics,OVERFLOW
from check_duplex import FS,LO,PERIOD,pilot,read_burst
from channel_features import extract
from survey_spectrum import capture_tile


def await_command(expected,timeout=300):
    replies=queue.Queue()
    def receive():
        try: replies.put(input().strip())
        except EOFError: replies.put('EOF')
    threading.Thread(target=receive,daemon=True).start()
    print('AWAIT_PHASE',expected,'TX_MUTED',flush=True)
    try: reply=replies.get(timeout=timeout)
    except queue.Empty: raise RuntimeError('Operator confirmation timed out; TX remains muted')
    if reply!=expected: raise RuntimeError('Stopped: expected phase '+expected+', received '+repr(reply))
    return {'command':reply,'received_utc':utc(),'meaning':'Assistant relayed operator confirmation that the required position is settled.'}


def main():
    run_id=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%M%SZ')+'_scene-aba'
    local,public=ROOT/'data/local'/run_id,ROOT/'experiments'/run_id
    local.mkdir(parents=True,exist_ok=False);public.mkdir(parents=True,exist_ok=False)
    sources=('scene_change.py','channel_features.py','check_duplex.py','characterize_rx.py','survey_spectrum.py')
    hashes={}
    for name in sources:
        data=(Path(__file__).parent/name).read_bytes();(public/name).write_bytes(data)
        hashes[name]=hashlib.sha256(data).hexdigest()
    tx=pilot();(local/'pilot-ci16.bin').write_bytes(tx.tobytes())
    result={'schema':'rfmapping.scene-aba/v1','run_id':run_id,'started_utc':utc(),'asset_id':'RFL-SDR-001',
            'position_id':'desk-1','receive_only':False,'source_sha256':hashes,'pilot_sha256':hashlib.sha256(tx.tobytes()).hexdigest(),
            'hypothesis':'The operator leaving the room may alter amplitude transfer beyond repeated-burst variability; return toward the first response would support a scene-related effect.',
            'protocol':{'stages':['A: original seated position','B: operator outside room; chair/device/final door position unchanged','C: returned and settled at original seated position'],
                        'bursts_per_stage':8,'tx_attenuation_db':45,'pilot_span_hz':1800000,'center_hz':LO,
                        'sample_rate_hz':FS,'rx_gain_db':40,'rx_tx_bandwidth_hz':2400000,
                        'samples_per_burst':1048576,'burst_mute_watchdog_s':.8,'maximum_planned_rf_bursts':24,
                        'operator_input_timeout_s':300,'storage_budget_bytes':536870912,
                        'analysis':'Compare absolute digital transfer amplitude and frequency-dependent amplitude shape; account for timing and carrier-phase nuisance independently per burst. No conversion to range.'},
            'criteria':'Describe B change relative to burst variability and check C return. One A/B/A cycle is exploratory; without a return or if change is within repeat variability, attribution is inconclusive.',
            'environment':'Pluto and stock antennas fixed near computer/router; operator controls chair/body position. No measured antenna geometry, exact displacement or bearing.',
            'stages':[],'operator_commands':[]}
    r=Receiver('ip:192.168.2.1');r.mute();result['initial_rx']=r.original
    original_tx={'lo':r.txlo.attrs['frequency'].value,'bandwidth':r.tx.attrs['rf_bandwidth'].value}
    channels=sorted([c for c in r.dds.channels if c.scan_element],key=lambda c:c.index)
    if len(channels)!=2:raise RuntimeError('Expected one complex TX channel')
    enabled=[c.enabled for c in channels]
    guard_ctx=r.iio.Context('ip:192.168.2.1');guard_ctx.set_timeout(1000)
    guard_lo=guard_ctx.find_device('ad9361-phy').find_channel('altvoltage1',True)
    save_json(public/'results.json',result)
    print('SESSION',run_id,flush=True)
    try:
        if any(int(r.phy.debug_attrs[k].value.split()[0]) for k in ('bist_prbs','bist_tone','loopback')):
            raise RuntimeError('BIST or loopback is active')
        r.configure(FS,2400000,40,LO)
        r.txlo.attrs['frequency'].value=str(LO);r.tx.attrs['rf_bandwidth'].value='2400000'
        for phase in ('A','B','C'):
            if phase!='A':
                result['operator_commands'].append(await_command(phase))
            stage={'phase':phase,'started_utc':utc(),'cases':[]}
            result['stages'].append(stage)
            print('RECORDING_PHASE',phase,flush=True)
            r.mute()
            check=capture_tile(r,phase+'_receive_guard',LO,40,20,local)
            stage['receive_guard']=check
            rows=np.array(check['spectrum_50khz_bins']);mask=(abs(rows[:,0])<=1250000)&(abs(rows[:,0])>50000)
            excess=float(rows[mask,3].max()-np.median(rows[mask,2]))
            stage['guard_max_excess_db']=excess
            if excess>8 or rows[mask,3].max()>-114 or check['fifo_overflow_observed'] or check['iq_metrics']['rail_component_count']:
                raise RuntimeError('Receive guard failed for stage '+phase)
            # capture_tile leaves this same LO/gain selected. No retune between stages.
            for b in range(8):
                name=f'{phase}_burst{b+1}'
                case={'id':name,'started_utc':utc(),'tx_attenuation_db':45}
                r.mute();r.tx.attrs['hardwaregain'].value='-45'
                for ch in channels:ch.enabled=True
                txbuf=None;timer=None;fired=threading.Event();watch_errors=[];on_start=None
                def timeout_mute():
                    fired.set()
                    try:guard_lo.attrs['powerdown'].value='1'
                    except Exception as exc:watch_errors.append(str(exc))
                try:
                    txbuf=r.iio.Buffer(r.dds,PERIOD,True)
                    if txbuf.step!=4 or txbuf.write(bytearray(tx.tobytes()))!=tx.nbytes:raise RuntimeError('TX buffer layout/write failed')
                    txbuf.push()
                    timer=threading.Timer(.8,timeout_mute);timer.daemon=True;timer.start()
                    on_start=time.perf_counter();r.txlo.attrs['powerdown'].value='0'
                    raw,status=read_burst(r)
                finally:
                    r.txlo.attrs['powerdown'].value='1'
                    if on_start is not None:case['commanded_unmute_s']=time.perf_counter()-on_start
                    if timer is not None:timer.cancel();timer.join(timeout=1.2)
                    if txbuf is not None:txbuf.cancel();del txbuf
                    r.mute()
                path=local/(name+'.sigmf-data');path.write_bytes(raw)
                iq=np.frombuffer(raw,dtype='<i2').reshape(-1,2)
                case.update({'features':extract(iq,tx),'iq_metrics':iq_metrics(iq),'fifo_overflow_observed':bool(status&OVERFLOW),
                             'watchdog_fired':fired.is_set(),'watchdog_errors':watch_errors,
                             'raw_relative_path':path.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(raw).hexdigest(),
                             'raw_bytes':len(raw),'ended_utc':utc()})
                save_json(path.with_suffix('.sigmf-meta'),{'global':{'core:datatype':'ci16_le','core:version':'1.2.5','core:sample_rate':int(r.rx_channels[0].attrs['sampling_frequency'].value),'core:description':'Scene A/B/A coded pilot. Phase labels follow operator confirmation; no calibrated range.','rfmapping:phase':phase},'captures':[{'core:sample_start':0,'core:frequency':int(r.rxlo.attrs['frequency'].value)}],'annotations':[]})
                stage['cases'].append(case);save_json(public/'results.json',result)
                print(name,'transfer_db',round(case['features']['digital_transfer_power_db'],5),'rho',round(case['features']['median_correlation'],4),flush=True)
                if fired.is_set() or watch_errors or case['fifo_overflow_observed'] or case['iq_metrics']['rail_component_count'] or not case['features']['pilot_detected']:
                    raise RuntimeError('Timing, sample integrity or pilot detection failed; TX muted')
                time.sleep(.3)
            stage['ended_utc']=utc();stage['end_state']=r.settings()
            save_json(public/'results.json',result)
            print('PHASE_COMPLETE',phase,'TX_MUTED',flush=True)
        result['status']='completed'
    except BaseException as exc:
        result['status']='stopped';result['error']=f'{type(exc).__name__}: {exc}'
        raise
    finally:
        r.mute();r.txlo.attrs['frequency'].value=original_tx['lo'];r.tx.attrs['rf_bandwidth'].value=original_tx['bandwidth']
        for ch,value in zip(channels,enabled):ch.enabled=value
        result['restore_errors']=r.restore_rx();result['final_rx']=r.settings()
        result['final_bist']={k:r.phy.debug_attrs[k].value for k in ('bist_prbs','bist_tone','loopback')}
        r.assert_muted();result['final_tx_mute_verified']=True;result['ended_utc']=utc()
        save_json(public/'results.json',result)
        print('RESULTS',public/'results.json',flush=True)


if __name__=='__main__':main()
