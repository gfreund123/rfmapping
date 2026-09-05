"""Summarize completed placements and inference diagnostics without inventing geometry."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from characterize_rx import ROOT,save_json,utc
from compare_positions import load_verified,paired_features,compare_records
from review_position import digest


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('results',nargs=3,type=Path);ap.add_argument('--out',required=True,type=Path)
    ap.add_argument('--fringe-validation',required=True,type=Path)
    ap.add_argument('--phase-shape',required=True,type=Path);args=ap.parse_args()
    inputs=[load_verified(p) for p in args.results];entries=[]
    for (r,identity),path in zip(inputs,args.results):
        b=json.loads((path.parent/'bundle.json').read_text());q=json.loads((path.parent/'review.json').read_text())
        runs=[r]+[json.loads((ROOT/'experiments'/key/'results.json').read_text()) for key in b['controls_runs']]
        diagnostic_root=ROOT/'reports'/r['run_id']
        fringe=json.loads((diagnostic_root/'fringe/fringe.json').read_text())
        closure=json.loads((diagnostic_root/'closure/closure.json').read_text())
        if fringe['input']['results_sha256_lf_utf8']!=identity['results_sha256_lf_utf8'] or closure['results_sha256_lf_utf8']!=identity['results_sha256_lf_utf8']:
            raise ValueError('Diagnostic metadata does not match acquisition')
        entries.append({'identity':identity,'rf_bursts':sum(x['rf_bursts'] for x in runs),
            'raw_files':sum(len(x['records']) for x in runs),'raw_bytes':b['raw_bytes_verified'],
            'commanded_unmute_seconds':sum(x['commanded_unmute_seconds'] for x in runs),
            'paired_centers':q['paired_centers'],'main_warnings':q['warnings'],
            'median_absolute_repeat_difference_db':q['forward_reverse_median_abs_difference_db'],
            'p95_absolute_repeat_difference_db':q['forward_reverse_p95_abs_difference_db'],
            'held_summaries':b['held_summaries'],'final_mute_verified':all(x.get('final_tx_mute_verified') for x in runs),
            'fringe_stability_screen_passed':fringe['stable_descriptive_fringe_candidate'],
            'fringe_screen_failures':fringe['screen_failures'],
            'fringe_preferred_delays_ns':[x['delay_ns'] for x in fringe['variants']],
            'closure_summary':closure['summary'],
            'completed_profile_bursts':r['rf_bursts']+sum(s['burst_count'] for s in b['held_summaries']),
            'fringe_file_sha256_lf_utf8':hashlib.sha256((diagnostic_root/'fringe/fringe.json').read_text().encode()).hexdigest(),
            'closure_file_sha256_lf_utf8':hashlib.sha256((diagnostic_root/'closure/closure.json').read_text().encode()).hexdigest()})
    comparisons=[]
    for i,j in ((0,1),(0,2),(1,2)):
        comp=compare_records(inputs[i][0]['records'],inputs[j][0]['records'])
        comparisons.append({'first':entries[i]['identity']['position_id'],'second':entries[j]['identity']['position_id'],
            'common_centers':comp['common_paired_centers'],'summary':comp['summary']})
    validation=json.loads(args.fringe_validation.read_text())
    phase_shape=json.loads(args.phase_shape.read_text())
    if [x['input'] for x in phase_shape['placements']]!=[x[1] for x in inputs]:
        raise ValueError('Phase-correction inputs do not match the three verified acquisitions')
    result={'schema':'rfmapping.three-position-summary/v1','created_utc':utc(),'positions':entries,
        'total_rf_bursts_including_retained_partial_controls':sum(x['rf_bursts'] for x in entries),
        'total_verified_raw_files':sum(x['raw_files'] for x in entries),'total_verified_raw_bytes':sum(x['raw_bytes'] for x in entries),
        'total_commanded_unmute_seconds':sum(x['commanded_unmute_seconds'] for x in entries),
        'completed_profile_bursts':sum(x['completed_profile_bursts'] for x in entries),'full_profile_bursts':720,
        'all_final_mutes_verified':all(x['final_mute_verified'] for x in entries),'comparisons':comparisons,
        'room_geometry_status':'not identified','wall_distances_m':None,'room_dimensions_m':None,'placement_coordinates_m':None,
        'fringe_method_specificity_validated':validation['specificity_validation_passed'],
        'validation_file_sha256_lf_utf8':hashlib.sha256(args.fringe_validation.read_text().encode()).hexdigest(),
        'phase_shape_file_sha256_lf_utf8':hashlib.sha256(args.phase_shape.read_text().encode()).hexdigest(),
        'phase_shape':{k:v for k,v in phase_shape.items() if k!='placements'},
        'phase_shape_placements':[{k:v for k,v in x.items() if k!='corrected_triangles'} for x in phase_shape['placements']],
        'report_source_sha256':digest(Path(__file__))}
    args.out.mkdir(parents=True,exist_ok=True);save_json(args.out/'summary.json',result)
    (args.out/'report_three_positions.py').write_bytes(Path(__file__).read_bytes())
    fig,axes=plt.subplots(2,2,figsize=(12,8),layout='constrained')
    for (r,_),entry,color in zip(inputs,entries,['#315f87','#ad5833','#19856a']):
        pairs=paired_features(r['records']);centers=sorted(pairs);f=np.array(centers)/1e6;label=entry['identity']['position_id']
        for column,metric in enumerate(('power_db','signal_to_averaging_noise_db')):
            values=np.array([[pairs[x][d][metric] for x in centers] for d in ('forward','reverse')])
            axes[0,column].plot(f,values.mean(axis=0),label=label,color=color)
            axes[0,column].fill_between(f,values.min(axis=0),values.max(axis=0),color=color,alpha=.12)
            axes[1,column].plot(f,values[1]-values[0],label=label,color=color,alpha=.85)
    for column,title in enumerate(('Digital transfer power','Relative to averaging noise')):
        axes[0,column].set(title=title,ylabel='dB',xlabel='RF center (MHz)')
        axes[1,column].set(title='Return sweep minus upward sweep',ylabel='Difference (dB)',xlabel='RF center (MHz)')
        axes[1,column].axhline(0,color='gray',lw=.7)
    for ax in axes.ravel():ax.grid(alpha=.15);ax.legend(fontsize=8)
    fig.suptitle('Three RF placements · measured responses and repeatability',fontsize=15,fontweight='bold')
    fig.savefig(args.out/'overview.png',dpi=150);plt.close(fig)
    lines=['# Three-position RF experiment: collection complete, geometry unresolved','',
        'All three requested placements were collected and verified. The data record RF responses and their variation at three acquisition states. They do not currently support a defensible floor plan, wall distances or placement coordinates.','',
        f"The bundles retain **{result['total_rf_bursts_including_retained_partial_controls']} RF pilot bursts**, **{result['total_verified_raw_files']} raw captures** and **{result['total_verified_raw_bytes']:,} bytes** of verified raw capture data. This includes two retained partial-control bursts at spot 1; {result['completed_profile_bursts']} of the 720 full-profile main/reference bursts across three spots were completed. Final TX mute was verified for every stage.",'',
        'Position 1 is the orientation reference. Position 2 was reported roughly 140–220 degrees rotated, with direction unspecified. Position 3 was reported 30–60 degrees counterclockwise from position 1. Locations and heights were withheld for blind inference. Those unknowns remain unknown.','',
        '![Three measured RF responses](overview.png)','',
        'Shading spans the observed pair of sweeps, not a confidence interval. Frequency windows overlap and the two sweeps are technical repeats.','',
        '## Measurement summary','',
        '| Position | Paired centers | Median absolute sweep difference | 95th percentile | Held-reference SDs |','|---|---:|---:|---:|---|']
    for e in entries:
        sds=', '.join(f"{s['between_burst_sd_db']:.3f}" for s in e['held_summaries'])
        lines.append(f"| {e['identity']['position_id']} | {e['paired_centers']} | {e['median_absolute_repeat_difference_db']:.3f} dB | {e['p95_absolute_repeat_difference_db']:.3f} dB | {sds} dB |")
    lines+=['','| Comparison | Median power difference, second minus first | Frequency-dependent RMS after removing median |','|---|---:|---:|']
    for c in comparisons:
        s=c['summary']['power_db'];lines.append(f"| {c['second']} minus {c['first']} | {s['median_second_minus_first_db']:.3f} dB | {s['rms_after_removing_median_db']:.3f} dB |")
    lines+=['','Positions 2 and 3 have relatively similar measured responses despite the reported orientation difference. Similarity does not establish proximity. Position, orientation, instrument response, operator state and elapsed time all changed or may have changed. The differences cannot be assigned solely to distance or room structure.','',
        '## Why a wall map is not established','',
        'The complex responses retain unknown timing and carrier phase between tunings. A cubic phase term tied to offset within each frequency window was fitted from position 1 only, then applied unchanged to positions 2 and 3. It substantially reduces a shared three-window phase inconsistency:','',
        '| Position | Role | Median absolute phase closure before / after | 95th-percentile fit-delay closure after |',
        '|---|---|---:|---:|']
    for p in phase_shape['placements']:
        before=p['before']['wrapped_phase_closure_deg']['median_absolute'];after=p['after']['wrapped_phase_closure_deg']['median_absolute']
        delay=p['after']['equivalent_fit_delay_closure_ns']['p95_absolute']
        lines.append(f"| {p['input']['position_id']} | {p['role']} | {before:.3f} / {after:.3f} degrees | {delay:.2f} ns |")
    lines+=['','This is evidence for a repeatable measurement contribution, not a physical identification of the filter or a calibration of absolute delay. The remaining fit-delay discrepancies are not reflection delays or calibrated range error bars. Position 3 also contains individual large closure residuals at the weaker high-frequency end; all are retained. Original channel samples remain unchanged.','',
        'A separate power-ripple analysis searched 7–200 ns trial delays with three smooth-baseline orders, both raw and noise-relative metrics, both sweep directions and blocked prediction checks. Its sensitivity results are:','',
        '| Position | Descriptive stability screen | Preferred trial-delay range across choices |','|---|---|---:|']
    for e in entries:lines.append(f"| {e['identity']['position_id']} | {'passes' if e['fringe_stability_screen_passed'] else 'fails'} | {min(e['fringe_preferred_delays_ns']):.2f}–{max(e['fringe_preferred_delays_ns']):.2f} ns |")
    lines+=['','These trial values are **not measured wall ranges**. The method recovered a known simulated 35 ns weak echo, but a smooth no-echo response also passed its stability screen with roughly 8–12 ns fits. The negative-control failure is retained in the validation record; the method is not a validated echo detector. A distinct sparse-delay example also demonstrates identical Fourier power from different delay sets.','',
        'This does not prove that RF room mapping is impossible. It means this dataset and the tested models have not separated room echoes from measurement response strongly enough to identify geometry. The raw complex samples remain available for additional offline models; no extra placement is requested.','',
        '## Records','']
    for e in entries:
        key=e['identity']['run_id'];lines.append(f"- [{e['identity']['position_id']} bundle](../{key}/bundle.md), [phase consistency](../{key}/closure/closure.json), [fringe sensitivity](../{key}/fringe/fringe.json).")
    lines+=['- [Synthetic method validation](../../experiments/2026-09-05_fringe-method-validation/results.json).',
        '- [Magnitude-inference method and limitations](../../docs/magnitude-inference.md).',
        '- [Phase inference notes](../../docs/phase-inference-notes.md).',
        '- [Correction trained on spot 1 and checked on spots 2 and 3](../phase-shape-three-positions/phase-shape.json).',
        '- [Position registry](../../experiments/positions.json).','']
    (args.out/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('total_rf_bursts_including_retained_partial_controls','total_verified_raw_files','total_verified_raw_bytes','all_final_mutes_verified','room_geometry_status')}))


if __name__=='__main__':main()
