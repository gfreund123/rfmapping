"""Test a known waveform-mirror basis against held-out measured frequency bins."""
import argparse
import json
from pathlib import Path
import numpy as np
from characterize_rx import save_json,utc
from deep_channel import load_run,load_channel,image_diagnostic,digest


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('results',nargs='+',type=Path);ap.add_argument('--out',required=True,type=Path)
    ap.add_argument('--stride',type=int,default=1);args=ap.parse_args()
    rows=[];inputs=[]
    for path in args.results:
        r,xf=load_run(path);inputs.append({'run_id':r['run_id'],'results_sha256_lf_utf8':__import__('hashlib').sha256(path.read_text().encode()).hexdigest()})
        recs=[x for x in r['records'] if x['kind']=='pilot' and x['id'].startswith(('forward_','reverse_'))]
        for rec in recs[::args.stride]:
            a=load_channel(rec)
            rows.append({'run_id':r['run_id'],'id':rec['id'],'lag_samples':rec['channel']['alignment_lag_samples'],
                         'source_channel_sha256':rec['channel_file']['sha256'],**image_diagnostic(a,xf)})
        print(r['run_id'],'done',flush=True)
    result={'schema':'rfmapping.iq-image-diagnostic/v1','created_utc':utc(),'inputs':inputs,'rows':rows,
        'hardware_access':False,'source_sha256':{name:digest(Path(__file__).parent/name) for name in ('deep_channel.py','diagnose_iq_image.py')},
        'scope':'Exploratory known-code decomposition. Image basis is conjugate mirror pilot spectrum divided by pilot spectrum. Held-out bins are every fifth bin; they are not independent scene replicates. A detected image term does not locate its physical source.'}
    args.out.mkdir(parents=True,exist_ok=True);save_json(args.out/'image-diagnostic.json',result)
    for name in result['source_sha256']:(args.out/name).write_bytes((Path(__file__).parent/name).read_bytes())
    for identity in inputs:
        values=[x for x in rows if x['run_id']==identity['run_id']]
        print(json.dumps({'run_id':identity['run_id'],'count':len(values),**{k:float(np.median([x[k] for x in values])) for k in ('held_bin_error_reduction','held_bin_residual_to_estimated_noise','image_to_direct_power_db')}}))


if __name__=='__main__':main()
