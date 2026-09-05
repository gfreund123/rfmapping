"""Compare verified acquisition states without assuming geometry or phase coherence.

This is a descriptive comparison of the two sweep repeats at common RF centers.
An observed repeat envelope is not a confidence interval, and rotating the setup
confounds a position-only interpretation. No coordinate or wall solver is used.
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


def paired_features(records):
    grouped={}
    for r in records:
        direction=r['id'].split('_',1)[0]
        if direction not in ('forward','reverse') or r['kind']!='pilot':continue
        center=int(r['id'].split('_',1)[1])
        c=r['channel'];noise=c['estimator_noise_to_signal_ratio']
        if noise<=0 or not np.isfinite(noise):raise ValueError('Invalid noise ratio')
        grouped.setdefault(center,{})[direction]={
            'power_db':c['digital_transfer_power_db'],
            'signal_to_averaging_noise_db':float(-10*np.log10(noise))}
    return {f:v for f,v in grouped.items() if set(v)=={'forward','reverse'}}


def compare_records(first,second):
    a=paired_features(first);b=paired_features(second);common=sorted(set(a)&set(b))
    if len(common)<3:raise ValueError('Need at least three common paired centers')
    rows=[]
    for f in common:
        row={'center_hz':f}
        for metric in ('power_db','signal_to_averaging_noise_db'):
            av=np.array([a[f][d][metric] for d in ('forward','reverse')])
            bv=np.array([b[f][d][metric] for d in ('forward','reverse')])
            delta=float(bv.mean()-av.mean())
            row[metric]={'first_mean':float(av.mean()),'second_mean':float(bv.mean()),
                'second_minus_first':delta,'first_repeat_span':float(np.ptp(av)),
                'second_repeat_span':float(np.ptp(bv)),
                'observed_difference_envelope':[float(bv.min()-av.max()),float(bv.max()-av.min())]}
        rows.append(row)
    summaries={}
    for metric in ('power_db','signal_to_averaging_noise_db'):
        values=np.array([x[metric]['second_minus_first'] for x in rows]);shift=float(np.median(values))
        centered=values-shift
        for row,value in zip(rows,centered):row[metric]['median_removed_difference']=float(value)
        summaries[metric]={'median_second_minus_first_db':shift,
            'range_second_minus_first_db':[float(values.min()),float(values.max())],
            'rms_after_removing_median_db':float(np.sqrt(np.mean(centered**2))),
            'p95_absolute_after_removing_median_db':float(np.percentile(abs(centered),95))}
    return {'common_paired_centers':len(common),'first_only_paired_centers_hz':sorted(set(a)-set(b)),
        'second_only_paired_centers_hz':sorted(set(b)-set(a)),'summary':summaries,'centers':rows,
        'statistics_scope':'Descriptive summaries across overlapping RF windows, not independent trials or confidence bounds.'}


def load_verified(path):
    r=json.loads(path.read_text());review_path=path.parent/'review.json'
    q=json.loads(review_path.read_text());bundle_path=path.parent/'bundle.json';b=json.loads(bundle_path.read_text())
    if not q['raw_hashes_verified'] or not q['acquisition_ready_to_move'] or not b['acquisition_ready_to_move']:
        raise ValueError('A complete verified acquisition bundle is required: '+r['run_id'])
    h=hashlib.sha256(path.read_text().encode()).hexdigest()
    if q.get('results_sha256_lf_utf8')!=h or b['main_run']!=r['run_id']:
        raise ValueError('Review does not match input metadata')
    identity={'run_id':r['run_id'],'position_id':r['plan']['position_id'],
        'results_relative_path':path.resolve().relative_to(ROOT).as_posix(),
        'results_sha256_lf_utf8':h,'review_sha256_lf_utf8':hashlib.sha256(review_path.read_text().encode()).hexdigest(),
        'bundle_sha256_lf_utf8':hashlib.sha256(bundle_path.read_text().encode()).hexdigest(),
        'position_note':r['position_note'],'warnings':q['warnings']}
    event=path.parent/'operator-events.json'
    if event.exists():
        identity['operator_metadata']=json.loads(event.read_text())
        identity['operator_metadata_sha256_lf_utf8']=hashlib.sha256(event.read_text().encode()).hexdigest()
    return r,identity


def make_report(result,out):
    out.mkdir(parents=True,exist_ok=True)
    labels=[x['position_id'] for x in result['inputs']]
    rows=result['centers'];freq=np.array([x['center_hz'] for x in rows])/1e6
    fig,axes=plt.subplots(2,2,figsize=(12,8),layout='constrained')
    for column,metric in enumerate(('power_db','signal_to_averaging_noise_db')):
        data=[x[metric] for x in rows];ax=axes[0,column]
        for index,(key,span,color) in enumerate((('first_mean','first_repeat_span','#315f87'),('second_mean','second_repeat_span','#ad5833'))):
            mean=np.array([x[key] for x in data]);half=np.array([x[span] for x in data])/2
            ax.plot(freq,mean,color=color,label=labels[index]);ax.fill_between(freq,mean-half,mean+half,color=color,alpha=.15)
        ax.set(title='Raw transfer power' if column==0 else 'Relative to estimated averaging noise',ylabel='dB',xlabel='RF center (MHz)');ax.legend()
        ax=axes[1,column];mean=np.array([x['second_minus_first'] for x in data]);bounds=np.array([x['observed_difference_envelope'] for x in data])
        ax.plot(freq,mean,color='#654b91',label='Difference of repeat means');ax.fill_between(freq,bounds[:,0],bounds[:,1],color='#654b91',alpha=.15,label='Observed repeat envelope')
        ax.axhline(0,color='gray',lw=.8);ax.set(title=labels[1]+' minus '+labels[0],ylabel='Difference (dB)',xlabel='RF center (MHz)');ax.legend(fontsize=8)
    for ax in axes.ravel():ax.grid(alpha=.15)
    fig.suptitle('RF response measured at two placements',fontsize=15,fontweight='bold')
    fig.savefig(out/'comparison.png',dpi=150);plt.close(fig)
    lines=['# RF comparison: '+labels[0]+' and '+labels[1],'',
        'This compares two measured acquisition states. Position, orientation, operator effects and acquisition time can differ. '
        'The result cannot attribute differences solely to position or convert them directly into wall ranges.','',
        *['- '+x['position_id']+': '+x['position_note'] for x in result['inputs']],'',
        f"Common frequency centers with both sweep directions: **{result['common_paired_centers']}**.",'',
        '![Measured comparison](comparison.png)','',
        'Shading covers the observed pair of sweeps at each position and their possible differences. '
        'It is not a confidence interval. Frequency windows overlap, and two sweeps do not establish long-term stability.','',
        '| Statistic | Raw transfer power | Relative to averaging noise |','|---|---:|---:|']
    for title,key in [('Median change, second minus first','median_second_minus_first_db'),('RMS frequency-dependent change after removing median','rms_after_removing_median_db'),('95th percentile absolute frequency-dependent change after removing median','p95_absolute_after_removing_median_db')]:
        lines.append(f"| {title} | {result['summary']['power_db'][key]:.4f} dB | {result['summary']['signal_to_averaging_noise_db'][key]:.4f} dB |")
    lines+=['','The noise-relative statistic may reduce common receiver-gain variation but is not independent calibration. '
        'Channel variation can enter its noise estimate. Removing the median separates a broad level change from frequency-dependent structure descriptively; '
        'it does not identify the cause of either component.','',
        'The strongest use of these data at this stage is to test repeatability and seek reproducible spectral structure across further positions. '
        'Coordinates, radio/antenna response, direct coupling, room paths, operator effects and retune phase remain unresolved. '
        'A floor plan requires a separately validated inference model.','',
        'Inputs: '+', '.join('`'+x['run_id']+'`' for x in result['inputs'])+'.',
        'Both input acquisition bundles passed their recorded reviews; their warnings are retained in comparison.json.','']
    (out/'report.md').write_text('\n'.join(lines),encoding='utf-8')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('first',type=Path);ap.add_argument('second',type=Path);ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args();a,ai=load_verified(args.first);b,bi=load_verified(args.second)
    result={'schema':'rfmapping.position-comparison/v1','created_utc':utc(),'inputs':[ai,bi],
        'analysis_source_sha256':digest(Path(__file__)),'mapping_ready':False,**compare_records(a['records'],b['records'])}
    make_report(result,args.out);save_json(args.out/'comparison.json',result)
    (args.out/'compare_positions.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps({'common_paired_centers':result['common_paired_centers'],'summary':result['summary'],'report':str(args.out/'report.md')}))


if __name__=='__main__':main()
