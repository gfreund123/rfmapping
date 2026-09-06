"""Reconstruct all sweeps and expose sensitivity to a common phase ambiguity."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from characterize_rx import ROOT,save_json,utc
from deep_channel import digest
from deep_stitch import prepare,estimate_baseband,calibrate_overlap_baseband,corrected_rows,stitch,align_responses,delay_profile


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('results',nargs=3,type=Path)
    ap.add_argument('--out',required=True,type=Path);ap.add_argument('--degree',default=8,type=int)
    ap.add_argument('--timing',choices=['free','fixed'],default='free')
    ap.add_argument('--calibration',choices=['median','overlap'],default='median')
    ap.add_argument('--quarter',type=int);args=ap.parse_args()
    local=ROOT/'data/local/deep-analysis'/args.out.name
    local.mkdir(parents=True,exist_ok=False);args.out.mkdir(parents=True,exist_ok=True)
    prepared=[prepare(p,args.degree,args.quarter) for p in args.results]
    training=prepared[0][1]['forward'];model=(calibrate_overlap_baseband if args.calibration=='overlap' else estimate_baseband)(training)
    result={'schema':'rfmapping.deep-stitch/v1','created_utc':utc(),'hardware_access':False,
        'degree':args.degree,'quarter':args.quarter,'timing_model':args.timing,'calibration_method':args.calibration,
        'training_run':prepared[0][0]['run_id'],'training_sweep':'forward',
        'baseband_model':model,'inputs':[{'run_id':r['run_id'],'results_sha256_lf_utf8':hashlib.sha256(p.read_text().encode()).hexdigest()} for (r,_),p in zip(prepared,args.results)],
        'source_sha256':{name:digest(Path(__file__).parent/name) for name in ('deep_channel.py','deep_stitch.py','run_deep_stitch.py')},
        'runs':[],'repeat_comparisons':[],'room_geometry_validated':False,
        'limitations':['Empirical baseband curvature can absorb physical channel curvature.',
            'An uncalibrated common quadratic baseband phase changes the reconstructed RF phase quadratically.',
            'Independent retuning and frame timing leave overall phase, gain and delay ambiguous.',
            'Delay peaks can arise from finite-band windows or model errors; they are not wall ranges.']}
    fig,axes=plt.subplots(3,2,figsize=(13,11),layout='constrained')
    for position,(r,sweeps) in enumerate(prepared):
        solutions={}
        for direction,rows in sweeps.items():
            s=stitch(corrected_rows(rows,model),timing=args.timing);solutions[direction]=s
            profile=delay_profile(s['frequency_hz'],s['response'])
            file=local/(r['plan']['position_id']+'-'+direction+'.npz')
            with file.open('xb') as stream:np.savez_compressed(stream,frequency_hz=s['frequency_hz'],response=s['response'],phase_at_lo=s['phase_at_lo'],phase_slope_rad_per_mhz=s['phase_slope_rad_per_mhz'],log_gain=s['log_gain'])
            closure=s['closure'];d={'run_id':r['run_id'],'position_id':r['plan']['position_id'],'direction':direction,
                'reconstructed_file':{'raw_relative_path':file.relative_to(ROOT).as_posix(),'sha256':digest(file)},
                'baseband_phase_quadratic_delta':0,'peaks':profile['peaks'],'profile_peak_before_recentering_ns':profile['peak_before_recentering_ns'],
                'closure':closure,'median_absolute_phase_closure_deg':float(np.median([abs(c['phase_deg']) for c in closure])),
                'p95_absolute_fit_delay_closure_ns':float(np.percentile([abs(c['fit_delay_ns']) for c in closure],95)),
                'median_edge_complex_residual':float(np.median([e['complex_residual'] for e in s['edges']])),'gauge_sensitivity':[]}
            for delta in (-.001,-.0002,.0002,.001):
                # Exact gauge transformation: subtracting delta*u^2 from each
                # window can be absorbed by per-window affine corrections and
                # a -delta*(RF-reference)^2 phase term in the reconstruction.
                u=(s['frequency_hz']-np.mean(s['frequency_hz']))/1e6
                transformed=s['response']*np.exp(-1j*delta*u*u)
                pd=delay_profile(s['frequency_hz'],transformed)
                d['gauge_sensitivity'].append({'quadratic_delta_rad_per_mhz2':delta,'peaks':pd['peaks'],
                    'exact_gauge_if_independent_window_timing_allowed':True,
                    'qualification':'This transformation is not an exact ambiguity under the fixed-timing assumption; it shows sensitivity if that assumption is relaxed.'})
            result['runs'].append(d)
            mask=abs(profile['relative_delay_ns'])<=200
            axes[position,0].plot(profile['relative_delay_ns'][mask],profile['relative_power_db'][mask],label=direction,alpha=.85)
        a=solutions['forward'];b=solutions['reverse'];aligned,stats=align_responses(a['frequency_hz'],a['response'],b['response'])
        result['repeat_comparisons'].append({'position_id':r['plan']['position_id'],**stats})
        phase=np.unwrap(np.angle(a['response']*np.conj(aligned)))
        axes[position,1].plot(a['frequency_hz']/1e6,phase*180/np.pi,label='Forward vs aligned reverse')
        axes[position,0].set(title=r['plan']['position_id']+' · reconstructed effective response',xlabel='Delay relative to largest peak (ns)',ylabel='Relative power (dB)',ylim=(-55,2),xlim=(-200,200))
        axes[position,1].set(title='Phase repeatability after removing affine phase',xlabel='RF frequency (MHz)',ylabel='Phase difference (degrees)')
        print(json.dumps({'position':r['plan']['position_id'],'repeat':stats,'peaks':[x['peaks'][:3] for x in result['runs'] if x['run_id']==r['run_id']]}),flush=True)
    for ax in axes.ravel():ax.grid(alpha=.15);ax.legend(fontsize=8)
    fig.suptitle('Experimental reconstruction · peaks are not calibrated wall ranges',fontsize=14)
    fig.savefig(args.out/'reconstruction.png',dpi=140);plt.close(fig)
    save_json(args.out/'stitch.json',result)
    for name in result['source_sha256']:(args.out/name).write_bytes((Path(__file__).parent/name).read_bytes())
    print('BASEBAND',json.dumps(model),flush=True)


if __name__=='__main__':main()
