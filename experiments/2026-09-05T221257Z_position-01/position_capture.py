"""One-position RF collection with guarded overlapping sweeps and local raw IQ.

Default invocation only prints the plan. --execute starts the authorized lab
measurement; an external STOP file aborts between bounded bursts. No firmware
changes or automatic movement. The device stays muted after completion/failure.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time
import numpy as np
from characterize_rx import ROOT,Receiver,save_json,utc,iq_metrics,OVERFLOW
from check_duplex import FS,read_burst
from position_dsp import make_pilot,activity,channel

CENTERS=list(range(5728000000,5872000001,1500000))
ANCHORS=[5771500000,5853100000]
SOURCES=['position_capture.py','position_dsp.py','characterize_rx.py','check_duplex.py','survey_spectrum.py']
STORAGE=3*1024**3
MAX_BURSTS=240
MAX_UNMUTE=115.


def plan(position_id):
    return {'position_id':position_id,'asset_id':'RFL-SDR-001','center_count':len(CENTERS),
            'centers_hz':CENTERS,'pilot_nominal_span_hz':3600000,'step_hz':1500000,
            'sample_rate_hz':FS,'rx_tx_bandwidth_hz':4000000,'rx_gain_db':40,
            'minimum_tx_attenuation_db':45,'per_burst_watchdog_seconds':.8,
            'maximum_rf_bursts':MAX_BURSTS,'maximum_total_commanded_unmute_seconds':MAX_UNMUTE,
            'storage_budget_bytes':STORAGE,'settling_seconds':15,
            'receive_guard':{'centers_relative_to_tx_hz':[-600000,600000],
                             'rf_bandwidth_hz':3000000,'usable_offsets_hz':[-1450000,1450000],
                             'blocks_per_center':2,'reason':'Avoid measured receiver-edge noise rise; overlapping guards cover each other\'s RX DC gap and the full pilot span.'},
            'steps':['RX-only 2.4 GHz context at gain 20 dB',
                     'RX-only 5.8 GHz survey offset from TX centers; reject observed occupied intervals',
                     'Legacy narrow pilot, two wideband anchors and attenuation controls',
                     'Ascending overlapping sweep; fresh RX guard before every RF burst',
                     'Repeated anchors and descending overlapping sweep',
                     'Final anchors, TX-off controls, restore and mute verification'],
            'constraints':['TX confined to candidate windows wholly inside 5725-5875 MHz.',
                           'Cellular, GNSS and observed occupied intervals excluded.',
                           'Hardware settings and finite receive checks do not calibrate EIRP or establish permanent vacancy.',
                           'No phase coherence across retunes or positions assumed.',
                           'No floor plan or calibrated ranges claimed from acquisition alone.']}


class Session:
    def __init__(self,args):
        self.run_id=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%M%SZ')+'_'+args.position_id
        self.local=ROOT/'data/local'/self.run_id
        self.public=ROOT/'experiments'/self.run_id
        self.local.mkdir(parents=True,exist_ok=False);self.public.mkdir(parents=True,exist_ok=False)
        self.stop=ROOT/'STOP_RF_CAPTURE';self.bytes=0;self.bursts=0;self.unmute=0.
        if self.stop.exists():raise RuntimeError('STOP_RF_CAPTURE exists; remove deliberately before another run')
        if shutil.disk_usage(ROOT).free<STORAGE+1024**3:raise RuntimeError('Insufficient free disk space')
        self.waveforms={}
        for wide in (False,True):
            tx,spec=make_pilot(wide);key=spec['name'];self.waveforms[key]=(tx,spec)
            p=self.local/(key+'.ci16');p.write_bytes(tx.tobytes())
            spec['raw_relative_path']=p.relative_to(ROOT).as_posix()
            spec['sha256']=hashlib.sha256(tx.tobytes()).hexdigest()
            spec['sample_count']=len(tx)
        hashes={}
        for name in SOURCES:
            raw=(Path(__file__).parent/name).read_bytes();(self.public/name).write_bytes(raw)
            hashes[name]=hashlib.sha256(raw).hexdigest()
        self.result={'schema':'rfmapping.position-capture/v1','run_id':self.run_id,'started_utc':utc(),
                     'status':'preparing','plan':plan(args.position_id),'source_sha256':hashes,
                     'software':{k:importlib.metadata.version(k) for k in ('numpy','pylibiio')},
                     'git_revision_before_capture':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                     'waveforms':{k:s for k,(_,s) in self.waveforms.items()},
                     'position_note':args.note,'operator_note':args.operator_note,
                     'geometry':{'coordinates_m':None,'height_m':None,'orientation_degrees':None,
                                 'antenna_spacing_m':None,'status':'Await operator metadata; never inferred from missing values.'},
                     'hypothesis':'Frequency-dependent channel features may repeat within a spot and change across spots; geometry needs additional calibration and position constraints.',
                     'ground_truth':'Known transmitted waveform; device position and antenna geometry are not yet measured.',
                     'records':[],'jobs':[],'hot_intervals_hz':[],'excluded_centers':[]}
        self.r=None;self.guard=None;self.tx_original=None;self.txchannels=[];self.enabled=[]
        self.save()

    def save(self):
        self.result['raw_capture_bytes']=self.bytes
        self.result['rf_bursts']=self.bursts
        self.result['commanded_unmute_seconds']=self.unmute
        save_json(self.public/'results.json',self.result)

    def check_budget(self,blocks=4,rf=False):
        if self.stop.exists():raise RuntimeError('Operator STOP file detected')
        if self.bytes+blocks*262144*4>STORAGE:raise RuntimeError('Position storage budget reached')
        if rf and (self.bursts>=MAX_BURSTS or self.unmute+.8>MAX_UNMUTE):
            raise RuntimeError('Position RF budget reached')

    def open_radio(self):
        self.r=Receiver('ip:192.168.2.1');self.r.mute()
        r=self.r
        self.result['initial_rx']=r.original
        self.tx_original={'frequency':r.txlo.attrs['frequency'].value,'rf_bandwidth':r.tx.attrs['rf_bandwidth'].value}
        self.txchannels=sorted([c for c in r.dds.channels if c.scan_element],key=lambda c:c.index)
        self.enabled=[c.enabled for c in self.txchannels]
        if len(self.txchannels)!=2:raise RuntimeError('Expected one complex TX path')
        self.guard=r.iio.Context('ip:192.168.2.1');self.guard.set_timeout(1000)
        self.guard_lo=self.guard.find_device('ad9361-phy').find_channel('altvoltage1',True)
        if any(int(r.phy.debug_attrs[k].value.split()[0]) for k in ('bist_prbs','bist_tone','loopback')):
            raise RuntimeError('BIST or loopback active')
        r.configure(FS,4000000,40,CENTERS[0]);r.tx.attrs['rf_bandwidth'].value='4000000'
        self.result['configured_rx']=r.settings();self.save()

    def tune(self,lo,gain=40,bandwidth=4000000):
        self.r.mute()
        self.r.rxlo.attrs['frequency'].value=str(lo)
        self.r.rx.attrs['hardwaregain'].value=str(gain)
        if int(self.r.rx.attrs['rf_bandwidth'].value)!=bandwidth:
            self.r.rx.attrs['rf_bandwidth'].value=str(bandwidth)
        self.r.tx.attrs['rf_bandwidth'].value=str(bandwidth)
        self.r.txlo.attrs['frequency'].value=str(lo)
        time.sleep(.08)

    def record(self,name,raw,status,kind,started,extra=None):
        p=self.local/(name+'.sigmf-data')
        with p.open('xb') as f:f.write(raw)
        self.bytes+=len(raw)
        iq=np.frombuffer(raw,dtype='<i2').reshape(-1,2)
        rec={'id':name,'kind':kind,'started_utc':started,'ended_utc':utc(),
             'raw_relative_path':p.relative_to(ROOT).as_posix(),'raw_bytes':len(raw),
             'sha256':hashlib.sha256(raw).hexdigest(),'settings':self.r.settings(),
             'tx_lo_hz':int(self.r.txlo.attrs['frequency'].value),
             'rf_chip_temperature_c':float(self.r.phy.find_channel('temp0',False).attrs['input'].value)/1000,
             'fifo_overflow_observed':bool(status&OVERFLOW),'iq_metrics':iq_metrics(iq)}
        if extra:rec.update(extra)
        save_json(p.with_suffix('.sigmf-meta'),{'global':{'core:datatype':'ci16_le','core:version':'1.2.5',
            'core:sample_rate':rec['settings']['stream_sample_rate_hz'],
            'core:description':'Position RF measurement. Per-file timing/phase origin arbitrary. Consult run metadata.',
            'rfmapping:kind':kind,'rfmapping:position':self.result['plan']['position_id']},
            'captures':[{'core:sample_start':0,'core:frequency':rec['settings']['rx_lo_hz']}],'annotations':[]})
        self.result['records'].append(rec);self.save()
        if rec['fifo_overflow_observed'] or rec['iq_metrics']['outside_12bit_count']:
            raise RuntimeError('Sample integrity failed at '+name)
        return rec,iq

    def receive(self,name,blocks=4,guard_edge=1450000):
        self.check_budget(blocks);self.r.assert_muted();started=utc()
        raw,status=read_burst(self.r,blocks)
        rec,iq=self.record(name,raw,status,'rx-only',started)
        rec['activity']=activity(iq,rec['settings']['stream_sample_rate_hz'],guard_edge)
        rec['quiet_observed']=rec['activity']['quiet_observed'] and not rec['iq_metrics']['rail_component_count']
        self.save();return rec,iq

    def transmit(self,name,waveform,attenuation=45):
        self.check_budget(4,rf=True)
        r=self.r;lo=int(r.rxlo.attrs['frequency'].value)
        tx,spec=self.waveforms[waveform]
        if lo-spec['edge_hz']<5725000000 or lo+spec['edge_hz']>5875000000 or attenuation<45:
            raise RuntimeError('RF limits violated')
        r.assert_muted()
        if abs(int(r.txlo.attrs['frequency'].value)-lo)>10:raise RuntimeError('RX/TX LO mismatch')
        r.tx.attrs['hardwaregain'].value=str(-attenuation)
        actual=float(r.tx.attrs['hardwaregain'].value.split()[0])
        if abs(actual+attenuation)>.01:raise RuntimeError('TX attenuation readback failed')
        for ch in self.txchannels:ch.enabled=True
        buf=None;timer=None;fired=threading.Event();errors=[];start=None;elapsed=0.;started=utc()
        def timeout_mute():
            fired.set()
            try:self.guard_lo.attrs['powerdown'].value='1'
            except Exception as exc:errors.append(str(exc))
        try:
            buf=r.iio.Buffer(r.dds,len(tx),True)
            if buf.step!=4 or buf.write(bytearray(tx.tobytes()))!=buf.nbytes:raise RuntimeError('TX buffer mismatch')
            buf.push();timer=threading.Timer(.8,timeout_mute);timer.daemon=True;timer.start()
            start=time.perf_counter();self.bursts+=1;r.txlo.attrs['powerdown'].value='0'
            raw,status=read_burst(r,4)
        finally:
            try:r.txlo.attrs['powerdown'].value='1'
            except Exception:
                self.guard_lo.attrs['powerdown'].value='1'
                raise
            finally:
                if start is not None:elapsed=time.perf_counter()-start;self.unmute+=elapsed
                if timer is not None:timer.cancel();timer.join(timeout=1.2)
                if buf is not None:buf.cancel();del buf
                r.mute();self.save()
        rec,iq=self.record(name,raw,status,'pilot',started,{'waveform':waveform,
             'tx_attenuation_db':attenuation,'commanded_unmute_seconds':elapsed,
             'watchdog_fired':fired.is_set(),'watchdog_errors':errors})
        # Use nominal digital grid for exact active-bin membership; actual rates
        # and LO are separately recorded for later physical frequency correction.
        rec['channel'],arrays=channel(iq,tx,spec)
        p=self.local/(name+'.channel.npz');np.savez_compressed(p,**arrays)
        rec['channel_file']={'raw_relative_path':p.relative_to(ROOT).as_posix(),
                             'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'raw_bytes':p.stat().st_size}
        self.save()
        if fired.is_set() or errors or rec['iq_metrics']['rail_component_count']:
            raise RuntimeError('RF timing or clipping failure at '+name)
        return rec

    def blocked(self,lo,edge=1800000):
        return any(a<lo+edge+100000 and b>lo-edge-100000 for a,b in self.result['hot_intervals_hz'])

    def probe(self,name,lo,waveform='overlap-3p6MHz',attenuation=45):
        job={'id':name,'center_hz':lo,'waveform':waveform,'attenuation_db':attenuation}
        self.result['jobs'].append(job)
        edge=self.waveforms[waveform][1]['edge_hz']
        if self.blocked(lo,edge):
            job['status']='skipped-observed-activity';self.save();return None
        bw=2400000 if waveform=='legacy-1p8MHz' else 4000000
        job['guard_ids']=[]
        for offset in (-600000,600000):
            self.tune(lo+offset,bandwidth=3000000)
            guard,_=self.receive(name+f'_guard{offset}',2);job['guard_ids'].append(guard['id'])
            if not guard['quiet_observed']:
                job['status']='skipped-fresh-activity'
                actual=guard['settings']['rx_lo_hz']
                for hot in guard['activity']['hot_offsets_hz']:
                    self.result['hot_intervals_hz'].append([actual+hot-75000,actual+hot+75000])
                if guard['iq_metrics']['rail_component_count']:
                    self.result['hot_intervals_hz'].append([lo-2200000,lo+2200000])
                self.save();return None
        self.tune(lo,bandwidth=bw)
        rec=self.transmit(name,waveform,attenuation);job['pilot_id']=rec['id']
        job['status']='captured' if rec['channel']['pilot_detected'] else 'captured-weak'
        self.save();return rec

    def anchors(self,label):
        for lo in ANCHORS:
            for i in range(3):self.probe(f'{label}_{lo}_repeat{i+1}',lo)
            if label in ('start','end'):
                self.probe(f'{label}_{lo}_atten48',lo,attenuation=48)
            # Same-frequency TX-off negative control, even if RF was skipped.
            self.tune(lo)
            off,iq=self.receive(f'{label}_{lo}_off',4)
            tx,spec=self.waveforms['overlap-3p6MHz'];off['off_channel'],_=channel(iq,tx,spec);self.save()

    def run(self):
        self.open_radio();self.result['status']='recording';self.save()
        print('SESSION',self.run_id,'TX_MUTED_SETTLE_15_SECONDS',flush=True);time.sleep(15)
        for i,lo in enumerate(range(2401500000,2482000001,3000000)):
            self.tune(lo,gain=20);self.receive(f'ambient24_{lo}',2)
        print('PASSIVE_24_DONE; SURVEYING_58',flush=True)
        for i,lo in enumerate(range(5727000000,5873000001,2000000)):
            self.tune(lo,bandwidth=3000000);rec,_=self.receive(f'survey58_{lo}',8)
            actual=rec['settings']['rx_lo_hz']
            for offset in rec['activity']['hot_offsets_hz']:
                self.result['hot_intervals_hz'].append([actual+offset-75000,actual+offset+75000])
            if rec['iq_metrics']['rail_component_count']:
                self.result['hot_intervals_hz'].append([lo-2200000,lo+2200000])
            if i%15==0:print('SURVEY58',i+1,'/74',flush=True)
        self.result['excluded_centers']=[x for x in CENTERS if self.blocked(x)]
        self.save();print('SURVEY_DONE excluded_centers',len(self.result['excluded_centers']),flush=True)
        # Compatibility with previous desk measurements.
        for i in range(3):self.probe(f'legacy_{i+1}',ANCHORS[0],'legacy-1p8MHz')
        self.anchors('start')
        for direction,centers in [('forward',CENTERS),('reverse',list(reversed(CENTERS)))]:
            for i,lo in enumerate(centers):
                rec=self.probe(f'{direction}_{lo}',lo)
                if i%10==0 or i==len(centers)-1:
                    print(direction,i+1,'/97',lo,'rho',round(rec['channel']['median_correlation'],3) if rec else 'skipped',flush=True)
            if direction=='forward':self.anchors('middle')
        self.anchors('end');self.result['status']='completed'

    def close(self):
        errors=[]
        if self.r is not None:
            r=self.r
            try:r.mute()
            except Exception as exc:
                errors.append(str(exc))
                if self.guard is not None:self.guard_lo.attrs['powerdown'].value='1'
            if self.tx_original:
                for obj,key,value in [(r.txlo,'frequency',self.tx_original['frequency']),
                                      (r.tx,'rf_bandwidth',self.tx_original['rf_bandwidth'])]:
                    try:obj.attrs[key].value=value
                    except Exception as exc:errors.append(str(exc))
            for ch,value in zip(self.txchannels,self.enabled):ch.enabled=value
            errors.extend(r.restore_rx())
            self.result['final_rx']=r.settings()
            self.result['final_bist']={k:r.phy.debug_attrs[k].value for k in ('bist_prbs','bist_tone','loopback')}
            r.assert_muted();self.result['final_tx_mute_verified']=True
        self.result['restore_errors']=errors;self.result['ended_utc']=utc();self.save()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--position-id',default='position-01')
    ap.add_argument('--note',default='First multi-position capture at the original desk location.')
    ap.add_argument('--operator-note',default='Operator instructed to remain still; exact pose and movement times not independently measured.')
    ap.add_argument('--execute',action='store_true');args=ap.parse_args()
    if not args.position_id.replace('-','').isalnum():raise ValueError('Use letters, numbers and hyphens for position ID')
    if not args.execute:print(json.dumps(plan(args.position_id),indent=2));return
    s=Session(args)
    try:s.run()
    except BaseException as exc:
        s.result['status']='stopped';s.result['error']=f'{type(exc).__name__}: {exc}';raise
    finally:s.close();print('RESULTS',s.public/'results.json',flush=True)


if __name__=='__main__':main()
