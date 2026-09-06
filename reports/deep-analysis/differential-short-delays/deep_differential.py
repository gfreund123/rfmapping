"""Test complex cross-placement ratios after cancellation of shared response.

Uses weak-echo terms in complex log response. Ratios, trial delays and smooth
baseline choices do not by themselves establish physical walls.
"""
import argparse
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from characterize_rx import ROOT,save_json,utc
from deep_channel import digest
from deep_stitch import align_responses

DELAYS=np.r_[np.arange(-200,-6.99,.5),np.arange(7,200.01,.5)]


def polynomial(f,degree,reference,span):
    return np.polynomial.legendre.legvander(2*(f-reference)/span,degree)


def scan_complex(f,y,degree,delays=DELAYS):
    reference=float(f.mean());span=float(np.ptp(f));b=polynomial(f,degree,reference,span)
    q=np.linalg.qr(b,mode='reduced')[0];res=y-q@(q.conj().T@y)
    e=np.exp(-2j*np.pi*(f[:,None]-reference)*delays[None,:]*1e-9)
    er=e-q@(q.conj().T@e);norm=np.sum(abs(er)**2,axis=0)
    projection=er.conj().T@res;reduction=abs(projection)**2/np.maximum(norm,1e-30)
    index=int(np.argmax(reduction));coefficient=projection[index]/norm[index]
    baseline=np.linalg.lstsq(b,y,rcond=None)[0]
    coeff=np.linalg.lstsq(b,y-coefficient*e[:,index],rcond=None)[0]
    return {'delay_ns':float(delays[index]),'coefficient':coefficient,'baseline_coefficients':baseline,
        'coefficients':coeff,'reference':reference,'span':span,'profile_improvement':reduction/max(float(np.sum(abs(res)**2)),1e-30),
        'baseline_mse':float(np.mean(abs(res)**2)),'best_mse':float((np.sum(abs(res)**2)-reduction[index])/len(f))}


def predict(f,fit,degree,echo=True):
    b=polynomial(f,degree,fit['reference'],fit['span'])
    if echo:return b@fit['coefficients']+fit['coefficient']*np.exp(-2j*np.pi*(f-fit['reference'])*fit['delay_ns']*1e-9)
    return b@fit['baseline_coefficients']


def blocked(f,forward,reverse,degree,delays=DELAYS):
    fold=(np.floor((f-f.min())/8000000).astype(int))%3;rows=[];base_error=echo_error=0
    for source,target,label in [(forward,reverse,'forward-to-reverse'),(reverse,forward,'reverse-to-forward')]:
        for k in range(3):
            train=fold!=k;test=~train;fit=scan_complex(f[train],source[train],degree,delays)
            b=polynomial(f,1,float(f.mean()),float(np.ptp(f)))
            nuisance=b@np.linalg.lstsq(b[train],target[train]-source[train],rcond=None)[0]
            base=target[test]-nuisance[test]-predict(f[test],fit,degree,False)
            echo=target[test]-nuisance[test]-predict(f[test],fit,degree,True)
            base_error+=float(np.sum(abs(base)**2));echo_error+=float(np.sum(abs(echo)**2))
            rows.append({'direction':label,'fold':k,'delay_ns':fit['delay_ns']})
    return {'prediction_squared_error_reduction':1-echo_error/max(base_error,1e-30),'fold_preferred_delays_ns':[x['delay_ns'] for x in rows],'folds':rows}


def diagnose(f,forward,reverse,delays=DELAYS):
    rows=[]
    for degree in (1,2,3):
        mean=scan_complex(f,(forward+reverse)/2,degree,delays);a=scan_complex(f,forward,degree,delays);b=scan_complex(f,reverse,degree,delays)
        rows.append({'baseline_degree':degree,'preferred_delay_ns':mean['delay_ns'],
            'weak_echo_coefficient_abs':float(abs(mean['coefficient'])),'coefficient_real_imag':[float(mean['coefficient'].real),float(mean['coefficient'].imag)],
            'forward_delay_ns':a['delay_ns'],'reverse_delay_ns':b['delay_ns'],
            'in_sample_error_reduction':float(max(mean['profile_improvement'])),
            'profile_improvement':mean['profile_improvement'].tolist(),**blocked(f,forward,reverse,degree,delays)})
    return rows


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('stitch',type=Path);ap.add_argument('--out',required=True,type=Path)
    ap.add_argument('--min-delay-ns',type=float,default=7);ap.add_argument('--delay-step-ns',type=float,default=.5);args=ap.parse_args()
    positive=np.arange(args.min_delay_ns,200.001,args.delay_step_ns);delays=np.r_[-positive[::-1],positive]
    original=json.loads(args.stitch.read_text());data={};f=None
    for r in original['runs']:
        p=ROOT/r['reconstructed_file']['raw_relative_path']
        if digest(p)!=r['reconstructed_file']['sha256']:raise ValueError('Reconstructed hash mismatch')
        with np.load(p) as z:
            if f is None:f=z['frequency_hz']
            else:np.testing.assert_equal(f,z['frequency_hz'])
            data[r['position_id'],r['direction']]=z['response']
    result={'schema':'rfmapping.deep-differential/v1','created_utc':utc(),'hardware_access':False,
        'stitch_sha256_lf_utf8':__import__('hashlib').sha256(args.stitch.read_text().encode()).hexdigest(),
        'source_sha256':digest(Path(__file__)),'comparisons':[],
        'method':'Ratios cancel shared instrument response and the common quadratic-phase gauge; overall gain and affine phase remain nuisance parameters. Fit a complex polynomial plus one signed-delay exponential in log ratio. Three interleaved 8 MHz block sets predict the other sweep, with only training frequencies used for affine nuisance alignment.',
        'physical_echo_validated':False,'room_geometry_validated':False,'search_delays_ns':delays.tolist()}
    fig,axes=plt.subplots(3,2,figsize=(13,10),layout='constrained')
    for i,(a,b) in enumerate([('position-01','position-02'),('position-01','position-03'),('position-02','position-03')]):
        ratios=[data[b,d]/data[a,d] for d in ('forward','reverse')]
        _,stats=align_responses(f,*ratios)
        logs=[np.log(abs(r))+1j*np.unwrap(np.angle(r)) for r in ratios]
        # 0.5 MHz sampling for the diagnostic fit; the reconstruction itself
        # retains its denser grid. These samples are not independent trials.
        index=np.arange(0,len(f),10);rows=diagnose(f[index],logs[0][index],logs[1][index],delays)
        entry={'first':a,'second':b,'ratio_repeat_comparison':stats,'variants':rows};result['comparisons'].append(entry)
        for y,label in zip(logs,['forward','reverse']):
            basis=polynomial(f,1,float(f.mean()),float(np.ptp(f)));res=y-basis@np.linalg.lstsq(basis,y,rcond=None)[0]
            axes[i,0].plot(f/1e6,res.real*20/np.log(10),label=label)
        for row in rows:axes[i,1].plot(delays,row['profile_improvement'],label='Baseline degree '+str(row['baseline_degree']))
        axes[i,0].set(title=b+' / '+a,xlabel='RF frequency (MHz)',ylabel='Log-magnitude curvature (dB)')
        axes[i,1].set(title='Complex-log echo model sensitivity',xlabel='Signed trial delay (ns)',ylabel='In-sample error reduction')
        print(json.dumps({'comparison':b+'/'+a,'repeat':stats,'variants':[{k:v for k,v in x.items() if k not in ('profile_improvement','folds')} for x in rows]}),flush=True)
    for ax in axes.ravel():ax.grid(alpha=.15);ax.legend(fontsize=8)
    fig.suptitle('Cross-placement ratios · smooth response can mimic a short-delay echo',fontsize=14)
    args.out.mkdir(parents=True,exist_ok=True);fig.savefig(args.out/'differential.png',dpi=140);plt.close(fig)
    save_json(args.out/'differential.json',result);(args.out/'deep_differential.py').write_bytes(Path(__file__).read_bytes())


if __name__=='__main__':main()
