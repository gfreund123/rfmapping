"""Cross-placement check of one empirical within-window phase correction.

Fit one cubic-offset phase coefficient to the first placement's triangle closure.
Evaluate the same coefficient at all placements. Original channel files remain
unchanged. This tests consistency, not absolute delay or wall geometry.
"""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from characterize_rx import ROOT,save_json,utc
from compare_positions import load_verified
from overlap_closure import fit_pair,closure,analyze
from review_position import digest


def cubic_closure_coefficient(offsets):
    centers=[5800000000,5801500000,5803000000];coefficient=.01
    a={'frequency_offset_hz':offsets,'h_integer_aligned':np.exp(1j*coefficient*(offsets/1e6)**3)}
    ab=fit_pair(a,a,centers[0],centers[1]);bc=fit_pair(a,a,centers[1],centers[2]);ac=fit_pair(a,a,centers[0],centers[2])
    return closure(ab,bc,ac,centers[1])['wrapped_phase_closure_deg']/coefficient


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('results',nargs='+',type=Path);ap.add_argument('--out',required=True,type=Path)
    args=ap.parse_args();inputs=[load_verified(p) for p in args.results]
    first=inputs[0][0];training=analyze(first)
    rec=next(x for x in first['records'] if x['id'].startswith('forward_') and x['kind']=='pilot')
    with np.load(ROOT/rec['channel_file']['raw_relative_path']) as z:offsets=z['frequency_offset_hz']
    response=cubic_closure_coefficient(offsets)
    coefficient=float(np.median([x['wrapped_phase_closure_deg'] for x in training['triangles']])/response)
    results=[]
    for index,(r,identity) in enumerate(inputs):
        before=training if index==0 else analyze(r);after=analyze(r,coefficient)
        results.append({'input':identity,'role':'training' if index==0 else 'held-out placement',
            'before':before['summary'],'after':after['summary'],'corrected_triangles':after['triangles']})
    result={'schema':'rfmapping.phase-shape-diagnostic/v1','created_utc':utc(),
        'training_run':first['run_id'],'cubic_correction_rad_per_mhz3':coefficient,
        'unit_cubic_triangle_response_deg':response,'placements':results,
        'source_sha256':{name:digest(ROOT/'scripts'/name) for name in ('phase_shape_diagnostic.py','overlap_closure.py','compare_positions.py')},
        'absolute_delay_calibrated':False,'room_geometry_validated':False,
        'limits':'One effective cubic-offset phase term is fitted from spot 1 only. Improvement on other spots supports a repeatable measurement contribution but does not identify its physical cause. Noise, gain response, global phase/delay ambiguity and unknown geometry remain. No original complex samples are changed.'}
    args.out.mkdir(parents=True,exist_ok=True);save_json(args.out/'phase-shape.json',result)
    for name in result['source_sha256']:(args.out/name).write_bytes((ROOT/'scripts'/name).read_bytes())
    print(json.dumps({'coefficient':coefficient,'placements':[{'position':x['input']['position_id'],'role':x['role'],'before_phase_deg':x['before']['wrapped_phase_closure_deg']['median_absolute'],'after_phase_deg':x['after']['wrapped_phase_closure_deg']['median_absolute'],'after_fit_delay_ns':x['after']['equivalent_fit_delay_closure_ns']['p95_absolute']} for x in results]}))


if __name__=='__main__':main()
