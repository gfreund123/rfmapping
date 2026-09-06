"""Re-estimate selected channels from original IQ and compare independent halves."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from characterize_rx import ROOT,save_json,utc
from position_dsp import channel
from deep_channel import load_run,load_channel,image_code,smooth_image_fit,digest
from deep_stitch import align_responses


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('results',nargs='+',type=Path);ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args();rows=[];inputs=[]
    for path in args.results:
        r,xf=load_run(path);spec=r['waveforms']['overlap-3p6MHz'];tx=np.fromfile(ROOT/spec['raw_relative_path'],dtype='<i2').reshape(-1,2)
        inputs.append({'run_id':r['run_id'],'results_sha256_lf_utf8':hashlib.sha256(path.read_text().encode()).hexdigest()})
        for direction in ('forward','reverse'):
            recs=sorted([x for x in r['records'] if x['kind']=='pilot' and x['id'].startswith(direction+'_')],key=lambda x:x['settings']['rx_lo_hz'])
            for rec in [recs[0],recs[len(recs)//2],recs[-1]]:
                p=ROOT/rec['raw_relative_path']
                if digest(p)!=rec['sha256']:raise ValueError('Raw hash mismatch')
                iq=np.fromfile(p,dtype='<i2').reshape(-1,2);summary,a=channel(iq,tx,spec)
                saved=load_channel(rec);error=float(np.max(abs(a['h_integer_aligned']-saved['h_integer_aligned'])))
                halves=[]
                for data in np.array_split(iq,2):
                    hs,ha=channel(data,tx,spec);f=ha['frequency_offset_hz'];v=ha['h_variance']/hs['period_count']
                    fit=smooth_image_fit(f,ha['h_integer_aligned'],v,image_code(f,xf))
                    halves.append(fit['direct'])
                aligned,stats=align_responses(f,halves[0],halves[1]);ph=np.unwrap(np.angle(halves[0]*np.conj(aligned)))
                coef=np.polynomial.polynomial.polyfit(f/1e6,ph,5)
                row={'run_id':r['run_id'],'id':rec['id'],'raw_sha256':rec['sha256'],
                    'recomputed_max_absolute_channel_difference':error,
                    'recomputed_power_difference_db':summary['digital_transfer_power_db']-rec['channel']['digital_transfer_power_db'],
                    'independent_half_comparison':stats,'half_phase_rms_after_affine_removal_deg':float(np.sqrt(np.mean(ph**2))*180/np.pi),
                    'half_phase_polynomial_difference':coef.tolist()}
                rows.append(row)
        print(r['run_id'],'raw audit complete',flush=True)
    result={'schema':'rfmapping.deep-raw-audit/v1','created_utc':utc(),'hardware_access':False,'inputs':inputs,'rows':rows,
        'source_sha256':{name:digest(Path(__file__).parent/name) for name in ('deep_raw_audit.py','deep_channel.py','deep_stitch.py','position_dsp.py')},
        'selection':'Lowest, middle and highest center in each sweep at every placement. Original raw hashes verified before recomputation. Independent half captures each refit their own pilot alignment and carrier-phase ramp.',
        'interpretation':'Half comparisons measure repeatability over one burst; they do not calibrate shared systematic instrument phase.'}
    args.out.mkdir(parents=True,exist_ok=True);save_json(args.out/'raw-audit.json',result)
    for name in result['source_sha256']:(args.out/name).write_bytes((Path(__file__).parent/name).read_bytes())
    print(json.dumps({'raw_captures_reprocessed':len(rows),'maximum_recompute_difference':max(x['recomputed_max_absolute_channel_difference'] for x in rows),'median_half_phase_rms_deg':float(np.median([x['half_phase_rms_after_affine_removal_deg'] for x in rows]))}))


if __name__=='__main__':main()
