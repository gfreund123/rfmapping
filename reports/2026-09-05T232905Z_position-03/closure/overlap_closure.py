"""Check independent three-window consistency before any bandwidth stitching.

Fits log gain and affine phase to pairwise overlapping complex responses, then
tests whether A/B times B/C agrees with A/C. No delay profile or map is produced.
Closure slopes are nuisance-fit inconsistency, not propagation delays.
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
from review_position import digest


def fit_pair(a,b,lo_a,lo_b):
    f=a['frequency_offset_hz']+lo_a;fb=b['frequency_offset_hz']+lo_b
    mask=(f>=fb.min())&(f<=fb.max())&(abs(f-lo_b)>=101500)
    f=f[mask];x=a['h_integer_aligned'][mask]
    y=np.interp(f,fb,b['h_integer_aligned'].real)+1j*np.interp(f,fb,b['h_integer_aligned'].imag)
    valid=(abs(x)>1e-12)&(abs(y)>1e-12);f=f[valid];x=x[valid];y=y[valid]
    if len(f)<32:return None
    reference=(lo_a+lo_b)/2;u=(f-reference)/1e6;ratio=x/y
    phase=np.unwrap(np.angle(ratio));coef=np.polyfit(u,phase,1)
    loggain=float(np.median(np.log(abs(ratio))))
    predicted=np.exp(loggain+1j*np.polyval(coef,u))*y
    return {'reference_hz':reference,'phase_slope_rad_per_mhz':float(coef[0]),
        'phase_at_reference_rad':float(coef[1]),'log_amplitude_ratio':loggain,
        'overlap_bins':len(f),'fractional_complex_residual_rms':float(np.linalg.norm(x-predicted)/np.linalg.norm(x))}


def closure(ab,bc,ac,reference_hz):
    def phase(edge):
        return edge['phase_at_reference_rad']+edge['phase_slope_rad_per_mhz']*(reference_hz-edge['reference_hz'])/1e6
    raw=phase(ab)+phase(bc)-phase(ac)
    slope=ab['phase_slope_rad_per_mhz']+bc['phase_slope_rad_per_mhz']-ac['phase_slope_rad_per_mhz']
    return {'reference_hz':reference_hz,'wrapped_phase_closure_deg':float(np.angle(np.exp(1j*raw))*180/np.pi),
        'slope_closure_rad_per_mhz':slope,
        'equivalent_fit_delay_closure_ns':float(-slope/(2*np.pi)*1000),
        'gain_closure_db':float((ab['log_amplitude_ratio']+bc['log_amplitude_ratio']-ac['log_amplitude_ratio'])*20/np.log(10))}


def analyze(r,phase_cubic_correction=0.):
    records={x['id']:x for x in r['records']};triangles=[];edges=[]
    for direction in ('forward','reverse'):
        centers=sorted(int(x.split('_')[1]) for x in records if x.startswith(direction+'_') and records[x]['kind']=='pilot')
        arrays={}
        for lo in centers:
            rec=records[f'{direction}_{lo}'];p=ROOT/rec['channel_file']['raw_relative_path']
            if digest(p)!=rec['channel_file']['sha256']:raise ValueError('Channel hash mismatch')
            with np.load(p) as z:arrays[lo]={k:z[k] for k in ('frequency_offset_hz','h_integer_aligned')}
            if phase_cubic_correction:
                a=arrays[lo]
                a['h_integer_aligned']=a['h_integer_aligned']*np.exp(-1j*phase_cubic_correction*(a['frequency_offset_hz']/1e6)**3)
        pairs={}
        for index,lo in enumerate(centers):
            for other in centers[index+1:index+3]:
                if other-lo>3000000:continue
                a=records[f'{direction}_{lo}']['settings']['rx_lo_hz'];b=records[f'{direction}_{other}']['settings']['rx_lo_hz']
                fit=fit_pair(arrays[lo],arrays[other],a,b)
                if fit:
                    pairs[lo,other]=fit;edges.append({'direction':direction,'centers_hz':[lo,other],**fit})
        for a,b,c in zip(centers,centers[1:],centers[2:]):
            if all(pair in pairs for pair in ((a,b),(b,c),(a,c))):
                triangles.append({'direction':direction,'centers_hz':[a,b,c],**closure(pairs[a,b],pairs[b,c],pairs[a,c],b)})
    if not triangles:raise ValueError('No three-window overlap triangles')
    summaries={}
    for key in ('wrapped_phase_closure_deg','equivalent_fit_delay_closure_ns','gain_closure_db'):
        v=np.array([x[key] for x in triangles]);summaries[key]={'median_absolute':float(np.median(abs(v))),'p95_absolute':float(np.percentile(abs(v),95)),'max_absolute':float(max(abs(v)))}
    return {'triangle_count':len(triangles),'edge_count':len(edges),'summary':summaries,'triangles':triangles,'edges':edges,
        'phase_cubic_correction_rad_per_mhz3':phase_cubic_correction,
        'limits':'Descriptive consistency test. Fit-delay closure is not a reflection delay. Small closure cannot establish absolute delay or distinguish radio/antenna response from room paths; no calibrated uncertainty threshold is imposed.'}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('results',type=Path);ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args();r=json.loads(args.results.read_text());result={'schema':'rfmapping.overlap-closure/v1','run_id':r['run_id'],'created_utc':utc(),'analysis_source_sha256':digest(Path(__file__)),'results_sha256_lf_utf8':hashlib.sha256(args.results.read_text().encode()).hexdigest(),**analyze(r)}
    args.out.mkdir(parents=True,exist_ok=True);save_json(args.out/'closure.json',result)
    (args.out/'overlap_closure.py').write_bytes(Path(__file__).read_bytes())
    fig,axes=plt.subplots(3,1,figsize=(11,8),layout='constrained')
    for ax,(key,label) in zip(axes,[('wrapped_phase_closure_deg','Phase closure (degrees)'),('equivalent_fit_delay_closure_ns','Fit-delay closure (ns)'),('gain_closure_db','Gain closure (dB)')]):
        for direction in ('forward','reverse'):
            rows=[x for x in result['triangles'] if x['direction']==direction]
            ax.plot([x['reference_hz']/1e6 for x in rows],[x[key] for x in rows],label=direction)
        ax.axhline(0,color='gray',lw=.7);ax.set(ylabel=label,xlabel='Middle RF center (MHz)');ax.grid(alpha=.15);ax.legend()
    fig.suptitle(r['plan']['position_id']+' · Three-window consistency; fit delays are not ranges')
    fig.savefig(args.out/'closure.png',dpi=150);plt.close(fig)
    print(json.dumps({'run_id':r['run_id'],'triangle_count':result['triangle_count'],'summary':result['summary']}))


if __name__=='__main__':main()
