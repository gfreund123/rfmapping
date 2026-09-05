"""Run the full per-position RF bundle and review it before the move cue.

Default: print plan only. --execute: main capture, held-reference controls, offline
verification. Every hardware stage closes/mutes before the next stage starts.
"""
import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from characterize_rx import ROOT,save_json,utc
from position_capture import Session,plan
from hold_reference_controls import collect_controls,REFERENCE_CENTERS
from review_position import inspect,report,digest
from position_dsp import averaged_pilot_evidence


def held_summaries(records,centers):
    """Reconstruct finished trains from saved records, including stopped runs."""
    summaries=[]
    for lo in centers:
        cases=[x for x in records if x['kind']=='pilot' and x['id'].startswith(f'held_{lo}_')]
        off=[x for x in records if x['id']==f'held_{lo}_final_off' and 'off_channel' in x]
        if not cases:continue
        values=[x['channel']['digital_transfer_power_db'] for x in cases]
        settings=[(x['settings']['rx_lo_hz'],x['tx_lo_hz'],x['settings']['rf_bandwidth_hz'],
                   x['settings']['gain_db'],x['settings']['stream_sample_rate_hz'],x['tx_attenuation_db']) for x in cases]
        summaries.append({'center_hz':lo,'burst_count':len(cases),'mean_db':float(np.mean(values)),
            'between_burst_sd_db':float(np.std(values,ddof=1)) if len(values)>1 else None,
            'min_max_db':[float(min(values)),float(max(values))],
            'complete_train':len(cases)==7 and len(off)==1 and len(set(settings))==1,
            'pilot_ids':[x['id'] for x in cases],'final_off_ids':[x['id'] for x in off]})
    return summaries


def verify_controls(path,required_centers=None,recover_metadata_stop=False):
    r=json.loads(path.read_text());issues=[];deviations=[]
    required=list(REFERENCE_CENTERS if required_centers is None else required_centers)
    recovered=(recover_metadata_stop and r['status']=='stopped'
               and r.get('error','').startswith('PermissionError:') and 'results.pending' in r['error'])
    if recovered:deviations.append('Stopped on metadata replacement; only the explicitly selected complete trains are accepted. Original partial acquisition remains stopped.')
    if (r['status']!='completed' and not recovered) or not r.get('final_tx_mute_verified') or r.get('restore_errors'):
        issues.append('Control acquisition or final state failed')
    if 'private_context' in r:
        p=r['private_context']
        if digest(ROOT/p['raw_relative_path'])!=p['sha256']:issues.append('Control private context hash')
    for name,h in r['source_sha256'].items():
        if digest(path.parent/name)!=h:issues.append('Control source hash: '+name)
    for spec in r['waveforms'].values():
        if digest(ROOT/spec['raw_relative_path'])!=spec['sha256']:issues.append('Control waveform hash')
    total=0
    for rec in r['records']:
        raw=ROOT/rec['raw_relative_path'];total+=rec['raw_bytes']
        if digest(raw)!=rec['sha256'] or raw.stat().st_size!=rec['raw_bytes']:
            issues.append('Control raw hash: '+rec['id'])
        meta=json.loads(raw.with_suffix('.sigmf-meta').read_text())
        if meta['global']['core:datatype']!='ci16_le' or meta['global']['core:sample_rate']!=rec['settings']['stream_sample_rate_hz']:
            issues.append('Control sample metadata: '+rec['id'])
        if rec['fifo_overflow_observed'] or rec['iq_metrics']['outside_12bit_count']:
            issues.append('Control sample integrity: '+rec['id'])
        if rec['kind']=='pilot':
            if rec['watchdog_fired'] or rec['watchdog_errors'] or rec['iq_metrics']['rail_component_count']:
                issues.append('Control RF integrity: '+rec['id'])
            if not averaged_pilot_evidence(rec['channel']):issues.append('Control pilot evidence: '+rec['id'])
            if digest(ROOT/rec['channel_file']['raw_relative_path'])!=rec['channel_file']['sha256']:
                issues.append('Control channel hash: '+rec['id'])
        if 'off_channel' in rec and rec['off_channel']['median_correlation']>.1:
            issues.append('Control TX-off pilot match: '+rec['id'])
    summaries=held_summaries(r['records'],required)
    if len(summaries)!=len(required) or any(not x['complete_train'] for x in summaries):
        issues.append('Incomplete held-reference coverage')
    result={'schema':'rfmapping.held-controls-review/v1','run_id':r['run_id'],
            'verified_utc':utc(),'issues':issues,'passed':not issues,'raw_bytes_verified':total,
            'required_centers_hz':required,'deviations':deviations,
            'position_id':r['plan']['position_id'],'parent_position_run':r['parent_position_run'],
            'results_sha256_lf_utf8':hashlib.sha256(path.read_text().encode()).hexdigest(),
            'held_summaries':summaries,'verification_source_sha256':digest(Path(__file__))}
    save_json(path.parent/'verification.json',result);return result


def assemble_reviews(main_path,control_reviews):
    """Combine previously verified, metadata-bound reviews without more RF."""
    r=json.loads(main_path.read_text());q=json.loads((main_path.parent/'review.json').read_text())
    issues=[issue for c in control_reviews for issue in c['issues']]
    if q.get('results_sha256_lf_utf8')!=hashlib.sha256(main_path.read_text().encode()).hexdigest():
        issues.append('Main metadata changed since verified review')
    coverage=[]
    for c in control_reviews:
        p=ROOT/'experiments'/c['run_id']/'results.json'
        if c['results_sha256_lf_utf8']!=hashlib.sha256(p.read_text().encode()).hexdigest():
            issues.append('Control metadata changed since verified review: '+c['run_id'])
        if c['position_id']!=r['plan']['position_id'] or c['parent_position_run']!=r['run_id']:
            issues.append('Control position or parent mismatch: '+c['run_id'])
        coverage.extend(x['center_hz'] for x in c['held_summaries'] if x['complete_train'])
    if set(coverage)!=set(REFERENCE_CENTERS):issues.append('Combined controls do not cover all three reference centers')
    result={'schema':'rfmapping.position-bundle/v1','position_id':r['plan']['position_id'],
            'reviewed_utc':utc(),'main_run':r['run_id'],'controls_runs':[c['run_id'] for c in control_reviews],
            'main_review':'experiments/'+r['run_id']+'/review.json',
            'control_reviews':['experiments/'+c['run_id']+'/verification.json' for c in control_reviews],
            'acquisition_ready_to_move':q['acquisition_ready_to_move'] and all(c['passed'] for c in control_reviews) and not issues,
            'main_blockers':q['blockers'],'main_warnings':q['warnings'],'control_issues':issues,
            'deviations':[x for c in control_reviews for x in c['deviations']],
            'raw_bytes_verified':q['raw_bytes']+sum(c['raw_bytes_verified'] for c in control_reviews),
            'held_summaries':[x for c in control_reviews for x in c['held_summaries']],
            'mapping_ready':False,'bundle_source_sha256':digest(Path(__file__))}
    save_json(main_path.parent/'bundle.json',result)
    print(json.dumps(result));return result


def review_bundle(main_path,controls_path):
    r=json.loads(main_path.read_text());q=inspect(r,main_path.parent,True)
    q['review_source_sha256']=digest(Path(__file__).parent/'review_position.py')
    q['evidence_rule_source_sha256']=digest(Path(__file__).parent/'position_dsp.py')
    save_json(main_path.parent/'review.json',q)
    report(r,q,ROOT/'reports'/r['run_id'])
    return assemble_reviews(main_path,[verify_controls(controls_path)])


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--position-id',required=True)
    ap.add_argument('--note',default='Operator has not supplied coordinates or antenna orientation.')
    ap.add_argument('--operator-note',default='Operator instructed to remain at one position during capture; actual motion requires a separate annotation.')
    ap.add_argument('--execute',action='store_true')
    args=ap.parse_args()
    if not args.execute:
        print(json.dumps({'primary':plan(args.position_id),'held_controls':'Three centers, seven bounded pilot bursts each; no retune/filter writes within a train.','verification':'Raw/source hashes, paired coverage, averaged pilot evidence, negative controls and final mute.'},indent=2));return
    s=Session(args)
    source=Path(__file__).read_bytes();(s.public/'collect_position.py').write_bytes(source)
    s.result['source_sha256']['collect_position.py']=hashlib.sha256(source).hexdigest()
    try:s.run()
    except BaseException as exc:
        s.result['status']='stopped';s.result['error']=f'{type(exc).__name__}: {exc}';raise
    finally:s.close()
    controls=collect_controls(SimpleNamespace(position_id=args.position_id,parent_run=s.run_id))
    if not review_bundle(s.public/'results.json',controls)['acquisition_ready_to_move']:
        raise SystemExit(2)


if __name__=='__main__':main()
