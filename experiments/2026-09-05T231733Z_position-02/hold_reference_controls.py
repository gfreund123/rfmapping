"""Same-position controls without RF retuning between repeated pilot bursts.

Use only after a position capture, before its move cue. A full offset guard
precedes each reference train; subsequent TX-off guards cover the occupied pilot
span at the unchanged RX center and bandwidth. Any activity aborts that train.
"""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from characterize_rx import ROOT
from position_capture import Session
from position_dsp import channel

REFERENCE_CENTERS=(5771500000,5800000000,5853100000)


def collect_controls(args):
    args.note='Reference controls at the same position, with no retune/filter writes within each train.'
    args.operator_note='Operator instructed to keep equipment and pose fixed; consult operator-events for actual confirmations.'
    s=Session(args)
    raw=Path(__file__).read_bytes();(s.public/'hold_reference_controls.py').write_bytes(raw)
    s.result['source_sha256']['hold_reference_controls.py']=hashlib.sha256(raw).hexdigest()
    s.result['parent_position_run']=args.parent_run
    s.result['plan']['profile']='same-position-held-reference-controls'
    s.result['plan']['steps']=['Two-offset receive guard and initial reference',
        'Six repeats without retuning or rewriting filter settings, each with a TX-off guard over the full occupied pilot span',
        'Final same-frequency TX-off control; repeat at three centers; restore/mute']
    s.result['held_guard']={'rf_bandwidth_hz':4000000,'usable_edge_hz':1800000,
        'dc_note':'Pilot excludes +/-100 kHz; initial offset guards also observe the central RF interval.',
        'validation':'Existing same-frequency TX-off recordings passed the unchanged excess/absolute activity thresholds over this occupied span.'}
    centers=getattr(args,'centers',None) or REFERENCE_CENTERS
    if len(set(centers))!=len(centers) or any(x not in REFERENCE_CENTERS for x in centers):
        raise ValueError('Choose distinct centers from the three planned references')
    s.result['requested_held_centers_hz']=list(centers)
    summaries=[];s.result['held_summaries']=summaries
    try:
        s.open_radio()
        for lo in centers:
            first=s.probe(f'held_{lo}_initial',lo)
            if first is None:continue
            cases=[first]
            for i in range(6):
                guard,_=s.receive(f'held_{lo}_repeat{i+1}_off_guard',2,guard_edge=1800000)
                if not guard['quiet_observed']:
                    s.result.setdefault('skipped_trains',[]).append({'center_hz':lo,'reason':'Occupied-span TX-off guard rejected; no further RF at this center.'})
                    break
                cases.append(s.transmit(f'held_{lo}_repeat{i+1}','overlap-3p6MHz'))
            off,iq=s.receive(f'held_{lo}_final_off',4,guard_edge=1800000)
            tx,spec=s.waveforms['overlap-3p6MHz'];off['off_channel'],_=channel(iq,tx,spec)
            values=[x['channel']['digital_transfer_power_db'] for x in cases]
            summaries.append({'center_hz':lo,'burst_count':len(cases),'mean_db':float(np.mean(values)),
                'between_burst_sd_db':float(np.std(values,ddof=1)) if len(values)>1 else None,
                'min_max_db':[float(min(values)),float(max(values))]})
            s.save();print('HELD',lo,'bursts',len(cases),'SD',summaries[-1]['between_burst_sd_db'],flush=True)
        s.result['held_summaries']=summaries;s.result['status']='completed'
    except BaseException as exc:
        s.result['status']='stopped';s.result['error']=f'{type(exc).__name__}: {exc}';raise
    finally:s.close();print('RESULTS',s.public/'results.json',flush=True)
    return s.public/'results.json'


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--position-id',required=True)
    ap.add_argument('--parent-run',required=True)
    ap.add_argument('--centers',nargs='+',type=int,choices=REFERENCE_CENTERS,
                    help='Finish only missing reference trains after a stopped run at the same position.')
    collect_controls(ap.parse_args())


if __name__=='__main__':main()
