"""Known-truth channel-domain controls using measured per-bin noise levels.

The smooth no-reflection response is an instrument/antenna-response null, not a
claim that the laboratory has no reflections. Noise is newly generated, never
borrowed as ground truth from an unknown physical scene.
"""
import argparse
import json
from pathlib import Path
import numpy as np
from characterize_rx import ROOT,save_json,utc
from deep_channel import load_run,load_channel,image_code,smooth_image_fit,digest
from deep_stitch import calibrate_overlap_baseband,corrected_rows,stitch,align_responses,delay_profile


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('reference_results',type=Path)
    ap.add_argument('--model',required=True,type=Path);ap.add_argument('--out',required=True,type=Path);args=ap.parse_args()
    r,xf=load_run(args.reference_results);model=json.loads(args.model.read_text())['baseband_model'];templates=[]
    for rec in sorted([x for x in r['records'] if x['kind']=='pilot' and x['id'].startswith('forward_')],key=lambda x:x['settings']['rx_lo_hz']):
        a=load_channel(rec);templates.append({'center':rec['settings']['rx_lo_hz'],'f':a['frequency_offset_hz'],
            'relative_noise':a['variance_mean']/np.mean(abs(a['h_integer_aligned'])**2)})
    cases=[]
    for jitter_ns in (0.,.5,2.):
        for echo in (False,True):
            seed=9062040+int(jitter_ns*10)+int(echo);rng=np.random.default_rng(seed);sweeps={};truths={}
            for position in range(3):
                def physical(f):
                    u=(f-5800000000)/72000000
                    smooth=np.exp((-.75-.07*position)*u-.08*u*u+.025*u**3+1j*((.08+.03*position)*u*u+.02*u**3))
                    if echo:smooth=smooth*(1+.05*np.exp(-2j*np.pi*(f-5800000000)*35e-9+1j*.4)+.03*np.exp(-2j*np.pi*(f-5800000000)*80e-9-1j*.6))
                    return smooth
                for direction in ('forward','reverse'):
                    rows=[]
                    for t in templates:
                        u=t['f']/1e6;signal=physical(t['center']+t['f'])
                        bb=np.exp(np.polynomial.polynomial.polyval(u,model['log_amplitude_coefficients_per_mhz_power'])+1j*(.47*u+np.polynomial.polynomial.polyval(u,model['phase_coefficients_rad_per_mhz_power'])))
                        timing=rng.normal(0,jitter_ns);gain_phase=np.exp(rng.normal(0,.04)+1j*rng.uniform(-np.pi,np.pi))
                        direct=signal*bb*gain_phase*np.exp(-2j*np.pi*u*timing/1000)
                        code=image_code(t['f'],xf);mirror=.05*direct*np.exp(1j*rng.uniform(-np.pi,np.pi))
                        v=t['relative_noise']*np.mean(abs(direct)**2)
                        noise=np.sqrt(v/2)*(rng.normal(size=len(u))+1j*rng.normal(size=len(u)))
                        observed=direct+code*mirror+noise;fit=smooth_image_fit(t['f'],observed,v,code)
                        rows.append({'center':t['center'],'f':t['f'],'h':fit['direct'],'v':v})
                    sweeps[position,direction]=rows
                truths[position]=physical
                # Bind the current position coefficients rather than retain a
                # late-bound closure over a changing loop variable.
                grid=np.arange(5726000000,5874000001,50000)
                truths[position]=(grid,physical(grid))
            learned=calibrate_overlap_baseband(sweeps[0,'forward']);entries=[]
            for position in range(3):
                for direction in ('forward','reverse'):
                    s=stitch(corrected_rows(sweeps[position,direction],learned),timing='fixed');f=s['frequency_hz']
                    tf,th=truths[position];expected=np.interp(f,tf,th.real)+1j*np.interp(f,tf,th.imag)
                    aligned,stats=align_responses(f,expected,s['response']);profile=delay_profile(f,aligned)
                    near={str(tau):[p for p in profile['peaks'] if abs(p['relative_delay_ns']-tau)<=profile['inverse_bandwidth_ns']/2] for tau in (35,80)}
                    entries.append({'position':position+1,'direction':direction,'response_error':stats['complex_relative_rmse'],
                        'peaks':profile['peaks'],'peaks_near_specified_test_delays':near,
                        'both_specified_echoes_resolved':all(near.values()) if echo else None})
            cases.append({'seed':seed,'independent_window_timing_jitter_sd_ns':jitter_ns,'echoes_present':echo,
                'specified_echoes':[{'delay_ns':35,'voltage':.05,'phase_rad':.4},{'delay_ns':80,'voltage':.03,'phase_rad':-.6}] if echo else [],'reconstructions':entries})
            print(json.dumps({'jitter_ns':jitter_ns,'echoes':echo,'median_response_error':float(np.median([x['response_error'] for x in entries])),
                'both_echoes_resolved':sum(bool(x['both_specified_echoes_resolved']) for x in entries) if echo else None}),flush=True)
    result={'schema':'rfmapping.deep-reconstruction-validation/v1','created_utc':utc(),'hardware_access':False,
        'noise_reference_run':r['run_id'],'cases':cases,
        'source_sha256':{name:digest(Path(__file__).parent/name) for name in ('validate_deep_reconstruction.py','deep_channel.py','deep_stitch.py')},
        'truth':'Smooth complex log-polynomial RF response, supplied smooth baseband filter, optional specified two echoes, random constant phase/gain per window, specified independent timing jitter, a 5% voltage mirror term using the actual pilot code, and independent Gaussian noise scaled by measured per-bin channel-estimator variance.',
        'limits':'Six seeded channel-domain scenarios test reconstruction sensitivity and noise/window artifacts. They do not model all hardware impairments, establish a statistical false-alarm rate or calibrate room-reflection detectability.'}
    args.out.mkdir(parents=True,exist_ok=True);save_json(args.out/'validation.json',result)
    for name in result['source_sha256']:(args.out/name).write_bytes((Path(__file__).parent/name).read_bytes())


if __name__=='__main__':main()
