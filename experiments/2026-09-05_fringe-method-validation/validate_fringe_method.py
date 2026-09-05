"""Known-truth controls documenting the fringe screen's limits; no hardware access."""
import argparse
import json
from pathlib import Path
import numpy as np
from characterize_rx import ROOT,save_json,utc
from fringe_diagnostic import diagnose
from review_position import digest


def cases():
    f=np.linspace(5728e6,5872e6,97);x=np.linspace(-1,1,97)
    offsets=np.fft.fftfreq(4096,1/5e6);offsets=offsets[(abs(offsets)>=1e5)&(abs(offsets)<=1.8e6)]
    # Exact mean power of a direct path and one weak delayed path, averaged
    # across the pilot's occupied frequency offsets before taking logarithms.
    gain=.075;delay=35e-9
    h=1+gain*np.exp(-2j*np.pi*((f-f.mean())[:,None]+offsets)*delay+.4j)
    echo_db=10*np.log10(np.mean(abs(h)**2,axis=1))
    result=[]
    for name,feature,truth in [('weak_echo',echo_db,{'echo_present':True,'excess_delay_ns':35.,'relative_voltage':gain}),
            ('smooth_no_echo',1.6*np.tanh(2.2*x),{'echo_present':False,'response':'Smooth tanh bend added to baseline in dB'})]:
        rng=np.random.default_rng(9062030)
        def pair(signal):return signal+rng.normal(0,.035,97),signal+.1+rng.normal(0,.035,97)
        data={'power_db':pair(-65-7*x+.1*x*x+feature if name=='weak_echo' else -65-7*x+feature),
              'signal_to_averaging_noise_db':pair(20-7*x+.1*x*x+feature if name=='weak_echo' else 20-7*x+feature)}
        result.append({'name':name,'truth':truth,'frequencies_hz':f,'measurements':data,
            'impairments':{'seed':9062030,'independent_db_noise_sd':.035,'reverse_sweep_offset_db':.1,
                'notes':'No clipping or lost samples. Smooth gain response is uncalibrated. This does not simulate all physical radio effects.'}})
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--out',type=Path,required=True);args=ap.parse_args()
    args.out.mkdir(parents=True,exist_ok=False);records=[]
    for case in cases():
        result=diagnose(case['frequencies_hz'],case['measurements'])
        records.append({'name':case['name'],'truth':case['truth'],'impairments':case['impairments'],
            'frequencies_hz':case['frequencies_hz'].tolist(),
            'measurements':{k:[x.tolist() for x in v] for k,v in case['measurements'].items()},'diagnostic':result})
    sources={}
    for name in ('validate_fringe_method.py','fringe_diagnostic.py','compare_positions.py','review_position.py','position_dsp.py','characterize_rx.py','check_duplex.py','survey_spectrum.py'):
        p=ROOT/'scripts'/name;(args.out/name).write_bytes(p.read_bytes());sources[name]=digest(p)
    summary={'schema':'rfmapping.fringe-validation/v1','created_utc':utc(),'receive_only':True,'hardware_access':False,
        'source_sha256':sources,'cases':records,
        'specificity_validation_passed':False,
        'finding':'The known weak echo is recovered, but a smooth response with no echo also passes the descriptive stability screen. It is not a validated echo detector.',
        'development_deviation':'An initial unit expectation that the smooth no-echo response would be rejected failed. The counterexample was retained and interpretation restricted, rather than tuning the screen on physical data.',
        'room_geometry_validated':False}
    save_json(args.out/'results.json',summary)
    print(json.dumps({'specificity_validation_passed':False,'cases':[{'name':x['name'],'truth':x['truth'],'screen_passed':x['diagnostic']['stable_descriptive_fringe_candidate'],'preferred_delays_ns':[v['delay_ns'] for v in x['diagnostic']['variants']]} for x in records]}))


if __name__=='__main__':main()
