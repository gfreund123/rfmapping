"""Exploratory delay-fringe sensitivity test on verified power measurements.

Fits polynomial baselines plus one sinusoidal ripple in dB. This is a weak-echo
approximation/description, not a calibrated channel or room model. It cannot
distinguish an echo ripple from an identical instrument-response ripple.
"""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from characterize_rx import ROOT,save_json,utc
from compare_positions import load_verified,paired_features
from review_position import digest

DELAYS_NS=np.arange(7.,200.01,.25)
DEGREES=(1,2,3)
METRICS=('power_db','signal_to_averaging_noise_db')
RULE={'minimum_blocked_prediction_improvement_fraction':.10,
      'maximum_variant_delay_span_in_inverse_bandwidth_units':1.,
      'maximum_fold_delay_span_in_inverse_bandwidth_units':2.,
      'boundary_guard_ns':.5,
      'qualification':'Sensitivity screen only. A smooth no-echo synthetic response passes this screen; passing does not identify an RF echo or room geometry.'}


def design(f,degree,delay=None,reference=None,span=None):
    reference=float(np.mean(f)) if reference is None else reference
    span=float(np.ptp(f)) if span is None else span
    x=2*(f-reference)/span
    a=np.polynomial.legendre.legvander(x,degree)
    if delay is not None:
        phase=2*np.pi*(f-reference)*delay*1e-9
        a=np.column_stack((a,np.cos(phase),np.sin(phase)))
    return a


def scan(f,y,degree,delays=DELAYS_NS):
    reference=float(np.mean(f));span=float(np.ptp(f));base=design(f,degree,reference=reference,span=span)
    base_coef=np.linalg.lstsq(base,y,rcond=None)[0];base_prediction=base@base_coef
    errors=[];best=None
    for delay in delays:
        a=design(f,degree,delay,reference,span);coef=np.linalg.lstsq(a,y,rcond=None)[0]
        error=float(np.mean((y-a@coef)**2));errors.append(error)
        if best is None or error<best['mse']:
            best={'delay_ns':float(delay),'mse':error,'coefficients':coef.tolist(),
                  'ripple_amplitude_db':float(np.hypot(*coef[-2:])),
                  'design_condition_number':float(np.linalg.cond(a))}
    best.update(reference_hz=reference,span_hz=span,baseline_coefficients=base_coef.tolist(),
        baseline_mse=float(np.mean((y-base_prediction)**2)),profile_mse=errors)
    return best


def blocked_prediction(f,forward,reverse,degree,delays=DELAYS_NS):
    # Three interleaved groups of contiguous eight-center blocks. Fit one sweep,
    # predict held-out frequencies in the other. Offset is estimated on training
    # frequencies only, identically for baseline and fringe models.
    folds=(np.arange(len(f))//8)%3;rows=[];base_sse=fringe_sse=0.;count=0
    for source,target,label in ((forward,reverse,'forward-to-reverse'),(reverse,forward,'reverse-to-forward')):
        for fold in range(3):
            train=folds!=fold;test=~train
            fit=scan(f[train],source[train],degree,delays)
            offset=float(np.mean(target[train]-source[train]))
            a=design(f[test],degree,fit['delay_ns'],fit['reference_hz'],fit['span_hz'])
            b=design(f[test],degree,reference=fit['reference_hz'],span=fit['span_hz'])
            e=target[test]-(a@fit['coefficients']+offset)
            eb=target[test]-(b@fit['baseline_coefficients']+offset)
            fringe_sse+=float(e@e);base_sse+=float(eb@eb);count+=int(test.sum())
            rows.append({'direction':label,'fold':fold,'training_best_delay_ns':fit['delay_ns'],
                         'fringe_rmse_db':float(np.sqrt(np.mean(e**2))),
                         'baseline_rmse_db':float(np.sqrt(np.mean(eb**2)))})
    return {'baseline_rmse_db':float(np.sqrt(base_sse/count)),
        'fringe_rmse_db':float(np.sqrt(fringe_sse/count)),
        'prediction_improvement_fraction':float(1-fringe_sse/max(base_sse,1e-30)),
        'training_delay_span_ns':float(np.ptp([r['training_best_delay_ns'] for r in rows])),
        'folds':rows,'scope':'Descriptive blocked prediction; overlapping windows and two sweeps are not independent experimental replicates.'}


def diagnose(f,measurements,delays=DELAYS_NS):
    variants=[];nominal_cell=1e9/np.ptp(f)
    for metric in METRICS:
        forward,reverse=measurements[metric]
        for degree in DEGREES:
            fit=scan(f,(forward+reverse)/2,degree,delays)
            ff=scan(f,forward,degree,delays);rr=scan(f,reverse,degree,delays)
            cv=blocked_prediction(f,forward,reverse,degree,delays)
            variants.append({'metric':metric,'baseline_degree':degree,**fit,
                'forward_best_delay_ns':ff['delay_ns'],'reverse_best_delay_ns':rr['delay_ns'],
                'blocked_prediction':cv})
    spread=float(np.ptp([v['delay_ns'] for v in variants]));reasons=[]
    if spread>nominal_cell:reasons.append('Preferred delay changes by more than one inverse-bandwidth interval across baseline/metric choices.')
    if any(abs(v['forward_best_delay_ns']-v['reverse_best_delay_ns'])>nominal_cell for v in variants):reasons.append('Sweep-specific preferred delays disagree.')
    if any(v['delay_ns']<=delays[0]+RULE['boundary_guard_ns'] or v['delay_ns']>=delays[-1]-RULE['boundary_guard_ns'] for v in variants):reasons.append('A preferred delay lies at a search boundary.')
    if any(v['blocked_prediction']['prediction_improvement_fraction']<RULE['minimum_blocked_prediction_improvement_fraction'] for v in variants):reasons.append('Ripple fails to improve blocked prediction by 10% for every baseline/metric choice.')
    if any(v['blocked_prediction']['training_delay_span_ns']>2*nominal_cell for v in variants):reasons.append('Preferred delay is unstable across frequency-block fits.')
    return {'frequency_span_hz':float(np.ptp(f)),'inverse_bandwidth_interval_ns':float(nominal_cell),
        'search_delays_ns':delays.tolist(),'degrees':list(DEGREES),'screen_rule':RULE,
        'variant_preferred_delay_span_ns':spread,'stable_descriptive_fringe_candidate':not reasons,
        'screen_failures':reasons,'variants':variants,'physical_echo_validated':False,'room_geometry_validated':False,
        'specificity_validation':'Failed: the seeded smooth tanh-response control without echoes can pass all descriptive stability checks. This method is not an echo detector.',
        'limits':'Finite-band power ripple is not a calibrated delay measurement. Unknown instrument/antenna response can produce the same feature. Baseline sensitivity and prediction tests do not remove that ambiguity.'}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('results',type=Path);ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args();r,identity=load_verified(args.results);pairs=paired_features(r['records']);centers=sorted(pairs);f=np.array(centers,float)
    measurements={m:(np.array([pairs[x]['forward'][m] for x in centers]),np.array([pairs[x]['reverse'][m] for x in centers])) for m in METRICS}
    result={'schema':'rfmapping.fringe-diagnostic/v1','created_utc':utc(),'input':identity,
        'analysis_source_sha256':digest(Path(__file__)),**diagnose(f,measurements)}
    args.out.mkdir(parents=True,exist_ok=True);save_json(args.out/'fringe.json',result)
    (args.out/'fringe_diagnostic.py').write_bytes(Path(__file__).read_bytes())
    fig,axes=plt.subplots(1,2,figsize=(12,4),layout='constrained')
    for ax,metric in zip(axes,METRICS):
        for v in result['variants']:
            if v['metric']!=metric:continue
            improvement=1-np.array(v['profile_mse'])/max(v['baseline_mse'],1e-30)
            ax.plot(DELAYS_NS,improvement,label=f"Baseline degree {v['baseline_degree']}; best {v['delay_ns']:.2f} ns")
        ax.set(xlabel='Trial ripple delay (ns; not a measured wall range)',ylabel='In-sample fractional error reduction',title=metric.replace('_',' '));ax.grid(alpha=.15);ax.legend(fontsize=8)
    fig.suptitle(r['plan']['position_id']+' · Delay-fringe model sensitivity')
    fig.savefig(args.out/'fringe.png',dpi=150);plt.close(fig)
    print(json.dumps({'run_id':r['run_id'],'stable_descriptive_fringe_candidate':result['stable_descriptive_fringe_candidate'],
        'screen_failures':result['screen_failures'],'variants':[{'metric':v['metric'],'degree':v['baseline_degree'],'best_delay_ns':v['delay_ns'],'cv_improvement':v['blocked_prediction']['prediction_improvement_fraction']} for v in result['variants']]}))


if __name__=='__main__':main()
