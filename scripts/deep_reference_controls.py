"""Measure within-position phase-slope stability using retained reference trains."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from characterize_rx import ROOT,save_json,utc
from deep_channel import load_channel,image_code,smooth_image_fit,digest


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('results',nargs=3,type=Path);ap.add_argument('--out',required=True,type=Path);args=ap.parse_args()
    rows=[];inputs=[]
    for path in args.results:
        main=json.loads(path.read_text());bundle=json.loads((path.parent/'bundle.json').read_text());assert bundle['acquisition_ready_to_move']
        sources=[(path,'retuned-reference')]+[(ROOT/'experiments'/run/'results.json','held-reference') for run in bundle['controls_runs']]
        for source,kind in sources:
            r=json.loads(source.read_text());inputs.append({'run_id':r['run_id'],'results_sha256_lf_utf8':hashlib.sha256(source.read_text().encode()).hexdigest()})
            allowed=None
            if kind=='held-reference':
                v=json.loads((source.parent/'verification.json').read_text());assert v['passed']
                allowed={name for s in v['held_summaries'] if s['complete_train'] for name in s['pilot_ids']}
            spec=r['waveforms']['overlap-3p6MHz'];p=ROOT/spec['raw_relative_path'];assert digest(p)==spec['sha256']
            tx=np.fromfile(p,dtype='<i2').reshape(-1,2);xf=np.fft.fft(tx[:,0]+1j*tx[:,1])
            for rec in r['records']:
                if rec['kind']!='pilot' or rec.get('tx_attenuation_db')!=45:continue
                if allowed is not None and rec['id'] not in allowed:continue
                if allowed is None and (not rec['id'].startswith(('start_','middle_','end_')) or '_repeat' not in rec['id']):continue
                a=load_channel(rec);f=a['frequency_offset_hz'];fit=smooth_image_fit(f,a['h_integer_aligned'],a['variance_mean'],image_code(f,xf))
                h=fit['direct'];u=f/1e6
                coef=np.polynomial.polynomial.polyfit(u,np.unwrap(np.angle(h)),5)
                rows.append({'position_id':main['plan']['position_id'],'run_id':r['run_id'],'id':rec['id'],'kind':kind,
                    'center_hz':round(rec['tx_lo_hz']/100)*100,'source_channel_sha256':rec['channel_file']['sha256'],
                    'local_phase_slope_equivalent_delay_ns':float(-coef[1]/(2*np.pi)*1000),
                    'phase_coefficients':coef.tolist(),'direct_power_db':float(10*np.log10(np.mean(abs(h)**2)))})
    groups=[]
    for key in sorted({(x['position_id'],x['kind'],x['center_hz']) for x in rows}):
        selected=[x for x in rows if (x['position_id'],x['kind'],x['center_hz'])==key]
        values=np.array([x['local_phase_slope_equivalent_delay_ns'] for x in selected])
        groups.append({'position_id':key[0],'kind':key[1],'center_hz':key[2],'count':len(selected),
            'mean_local_phase_slope_delay_ns':float(values.mean()),'within_group_sd_ns':float(values.std(ddof=1)),
            'min_max_ns':[float(values.min()),float(values.max())]})
    result={'schema':'rfmapping.deep-reference-controls/v1','created_utc':utc(),'hardware_access':False,'inputs':inputs,'rows':rows,'groups':groups,
        'source_sha256':{name:digest(Path(__file__).parent/name) for name in ('deep_reference_controls.py','deep_channel.py')},
        'qualification':'These are polynomial phase-slope equivalents including radio and acquisition delays, not wall ranges. Their within-center variation tests approximate fractional-timing stability. Noise and filter recalibration both contribute. Partial/incomplete held trains are excluded using verified train IDs.'}
    args.out.mkdir(parents=True,exist_ok=True);save_json(args.out/'reference-controls.json',result)
    for name in result['source_sha256']:(args.out/name).write_bytes((Path(__file__).parent/name).read_bytes())
    print(json.dumps({'reference_bursts':len(rows),'groups':groups}))


if __name__=='__main__':main()
