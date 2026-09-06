"""Inject specified echoes before de-embedding into held-out measured channels.

Adds a delayed copy of the estimated desired component while retaining the
measured image term and residual noise. This is an algorithm sensitivity test,
not a calibrated RF target or a universal detection limit.
"""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from characterize_rx import ROOT,save_json,utc
from deep_channel import load_run,load_channel,image_code,smooth_image_fit,digest
from deep_stitch import corrected_rows,stitch,align_responses,delay_profile


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('results',type=Path);ap.add_argument('--model',required=True,type=Path);ap.add_argument('--out',required=True,type=Path);args=ap.parse_args()
    r,xf=load_run(args.results);model=json.loads(args.model.read_text())['baseband_model'];prepared={}
    for direction in ('forward','reverse'):
        rows=[]
        for rec in sorted([x for x in r['records'] if x['kind']=='pilot' and x['id'].startswith(direction+'_')],key=lambda x:x['settings']['rx_lo_hz']):
            a=load_channel(rec);f=a['frequency_offset_hz'];code=image_code(f,xf)
            fit=smooth_image_fit(f,a['h_integer_aligned'],a['variance_mean'],code)
            rows.append({'center':rec['settings']['rx_lo_hz'],'f':f,'h':fit['direct'],'v':a['variance_mean'],'observed':a['h_integer_aligned'],'code':code})
        prepared[direction]=rows
    base={d:stitch(corrected_rows(rows,model),timing='fixed') for d,rows in prepared.items()}
    cases=[]
    for delay in (5,10,20,35,60,100):
        for amplitude in (.03,.1):
            for direction,rows in prepared.items():
                modified=[]
                for row in rows:
                    echo=amplitude*np.exp(-2j*np.pi*(row['center']+row['f']-5800000000)*delay*1e-9+1j*.7)
                    observation=row['observed']+row['h']*echo
                    fit=smooth_image_fit(row['f'],observation,row['v'],row['code'])
                    modified.append({**row,'h':fit['direct']})
                s=stitch(corrected_rows(modified,model),timing='fixed');f=s['frequency_hz']
                expected=base[direction]['response']*(1+amplitude*np.exp(-2j*np.pi*(f-5800000000)*delay*1e-9+1j*.7))
                aligned,comparison=align_responses(f,expected,s['response']);profile=delay_profile(f,aligned)
                near=[p for p in profile['peaks'] if abs(p['relative_delay_ns']-delay)<=profile['inverse_bandwidth_ns']/2]
                cases.append({'delay_ns':delay,'voltage_amplitude':amplitude,'nominal_relative_power_db':float(20*np.log10(amplitude)),
                    'phase_rad':.7,'direction':direction,'resolved_local_peak_near_truth':bool(near),'peaks_near_truth':near,
                    'known_injected_response_reconstruction':comparison,'strongest_secondary_peaks':profile['peaks'][:4]})
            print('injection',delay,'ns',amplitude,'done',flush=True)
    result={'schema':'rfmapping.echo-injection/v1','created_utc':utc(),'hardware_access':False,'run_id':r['run_id'],
        'input_results_sha256_lf_utf8':hashlib.sha256(args.results.read_text().encode()).hexdigest(),
        'frozen_model_sha256_lf_utf8':hashlib.sha256(args.model.read_text().encode()).hexdigest(),
        'cases':cases,'source_sha256':{name:digest(Path(__file__).parent/name) for name in ('deep_echo_injection.py','deep_channel.py','deep_stitch.py')},
        'interpretation':'A delayed copy is injected into each observed narrowband channel before smooth image decomposition and overlap reconstruction. The same measured residual/noise is retained. Resolved means a local FFT peak lies within half an inverse-bandwidth interval of the specified injected delay; this uses known truth and is not a blind detector or a calibrated experimental sensitivity bound.'}
    args.out.mkdir(parents=True,exist_ok=True);save_json(args.out/'injection.json',result)
    for name in result['source_sha256']:(args.out/name).write_bytes((Path(__file__).parent/name).read_bytes())
    print(json.dumps({'case_count':len(cases),'resolved':sum(x['resolved_local_peak_near_truth'] for x in cases),
        'maximum_response_error':max(x['known_injected_response_reconstruction']['complex_relative_rmse'] for x in cases)}))


if __name__=='__main__':main()
