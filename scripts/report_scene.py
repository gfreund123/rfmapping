"""Descriptive A/B/A comparison; burst variation is not a population confidence interval."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from characterize_rx import ROOT,save_json


def summarize(r):
    stages=[]
    for s in r['stages']:
        a=np.array([c['features']['digital_transfer_power_db'] for c in s['cases']])
        bins=np.array([c['features']['frequency_bins'] for c in s['cases']])
        if not len(a):continue
        stages.append({'phase':s['phase'],'burst_count':len(a),'mean_db':float(a.mean()),
                       'started_utc':s['started_utc'],'ended_utc':s['ended_utc'],
                       'burst_sd_db':float(a.std(ddof=1)) if len(a)>1 else None,
                       'min_max_db':[float(a.min()),float(a.max())],
                       'frequency_offsets_hz':bins[0,:,0].tolist(),'bin_mean_db':bins[:,:,1].mean(axis=0).tolist(),
                       'bin_burst_sd_db':bins[:,:,1].std(axis=0,ddof=1).tolist()})
    out={'schema':'rfmapping.scene-comparison/v1','source_run':r['run_id'],'stages':stages,
         'interpretation_limit':'One exploratory A/B/A cycle. Repeated bursts are technical repeats, not independent subjects or randomized interventions.'}
    by={s['phase']:s for s in stages}
    if {'A','B','C'}.issubset(by):
        a,b,c=(by[k] for k in 'ABC')
        delta=b['mean_db']-a['mean_db']; ret=c['mean_db']-a['mean_db']
        out.update({'b_minus_a_db':delta,'c_minus_a_db':ret,'b_minus_c_db':b['mean_db']-c['mean_db'],
                    'b_vs_a_relative_power_change_percent':float(100*(10**(delta/10)-1)),
                    'b_vs_a_relative_amplitude_change_percent':float(100*(10**(delta/20)-1)),
                    'return_recovery_fraction':float(1-abs(ret)/abs(delta)) if abs(delta)>1e-12 else None,
                    'b_a_burst_ranges_disjoint':bool(b['min_max_db'][0]>a['min_max_db'][1] or b['min_max_db'][1]<a['min_max_db'][0]),
                    'total_commanded_rf_on_s':float(sum(case['commanded_unmute_s'] for s in r['stages'] for case in s['cases']))})
    return out


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('results',type=Path);args=parser.parse_args()
    r=json.loads(args.results.read_text());s=summarize(r)
    out=ROOT/'reports/2026-09-06-scene-change';out.mkdir(parents=True,exist_ok=True)
    colors={'A':'#315f87','B':'#ae5833','C':'#19856a'}
    events_path=args.results.parent/'operator-events.json'
    events=json.loads(events_path.read_text()) if events_path.exists() else {}
    changed_pose=events.get('stage_c_observation',{}).get('pose_matched_to_a') is False
    if changed_pose:
        s['conclusion']='Inconclusive presence effect: return posture differed, and C did not recover the A baseline. No room geometry inferred.'
    s['operator_event_record']='operator-events.json' if events else None
    save_json(args.results.parent/'comparison.json',s)
    labels={'A':'Seated baseline','B':'Departure interval','C':'Returned, different lean' if changed_pose else 'Returned to seat'}
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(1,2,figsize=(12,4.8),layout='constrained')
    base=s['stages'][0]['mean_db']
    a=axes[0]
    for i,stage in enumerate(r['stages']):
        vals=np.array([c['features']['digital_transfer_power_db'] for c in stage['cases']])-base
        a.scatter(i+np.linspace(-.15,.15,len(vals)),vals,color=colors[stage['phase']],s=32,zorder=3)
        a.plot([i-.23,i+.23],[vals.mean()]*2,color=colors[stage['phase']],lw=2)
    a.axhline(0,color='#87919a',ls='--',lw=1)
    a.set_xticks(range(len(s['stages'])),[labels[x['phase']] for x in s['stages']])
    a.set(title='Transfer change across the three conditions',ylabel='Digital transfer power relative to baseline (dB)')
    a.grid(axis='y',alpha=.18)
    a=axes[1];ba=np.array(s['stages'][0]['bin_mean_db'])
    for stage in s['stages']:
        offsets=np.array(stage['frequency_offsets_hz'])/1e6
        delta=np.array(stage['bin_mean_db'])-ba
        # Do not interpolate across the unmeasured central pilot gap.
        for side in (offsets<0,offsets>0):
            a.plot(offsets[side],delta[side],'o-',label=labels[stage['phase']] if side[0] else None,
                   color=colors[stage['phase']],markersize=4)
    a.axvspan(-.1,.1,color='#e9ecee')
    a.set(title='Amplitude response versus pilot frequency',xlabel='Offset from 5771.5 MHz (MHz)',ylabel='Change from seated baseline (dB)')
    a.grid(alpha=.15);a.legend(fontsize=8)
    fig.suptitle('Fixed Pluto position · Departure and return'+(' with a posture change' if changed_pose else ''),fontsize=15,fontweight='bold')
    fig.savefig(out/'overview.png',dpi=160);plt.close(fig)
    lines=['# Position 1: controlled scene change','',
           '6 September 2026, Asia/Jerusalem. Run identifiers and timestamps use UTC. Equipment: RFL-SDR-001 with the supplied TX/RX antennas.', '',
           'The operator was instructed to remain seated for A, leave the room for B, then return to the original seat for C. The chair, equipment and final door position were to remain unchanged. This is one exploratory A/B/A cycle, using eight technical repeats per condition.'+(' The operator subsequently reported leaning slightly differently for C; the return did not reproduce the baseline pose.' if changed_pose else ''), '',
           '![Measured amplitude response](overview.png)', '', '## Measured result', '',
           '| Condition | Bursts | Mean digital transfer (dB) | Between-burst SD (dB) |', '|---|---:|---:|---:|']
    for stage in s['stages']:
        lines.append(f"| {stage['phase']}: {labels[stage['phase']]} | {stage['burst_count']} | {stage['mean_db']:.5f} | {stage['burst_sd_db']:.5f} |")
    if 'b_minus_a_db' in s:
        lines+=['',f"During the instructed departure interval, measured transfer was **{s['b_minus_a_db']:+.5f} dB** relative to A ({s['b_vs_a_relative_power_change_percent']:+.2f}% received pilot power; {s['b_vs_a_relative_amplitude_change_percent']:+.2f}% amplitude). After returning, C differed from A by **{s['c_minus_a_db']:+.5f} dB**. The B-minus-C difference was {s['b_minus_c_db']:+.5f} dB.", '',
                f"C recovered only {100*s['return_recovery_fraction']:.1f}% of the B-minus-A shift. Although the A and B burst ranges were disjoint, the return failed to recover the original baseline. Together with the reported posture change and the unmeasured drift between conditions, this makes attribution to presence/absence **inconclusive**. No room geometry was inferred.", '',
                '## Timing and operator observations','',
                '| Stage | Start (UTC) | End (UTC) |', '|---|---|---|']
        for stage in s['stages']:
            lines.append(f"| {stage['phase']} | {stage['started_utc']} | {stage['ended_utc']} |")
        if events:
            cue=datetime.fromisoformat(events['events'][0]['utc'])
            b=next(x for x in s['stages'] if x['phase']=='B')
            first=(datetime.fromisoformat(b['started_utc'])-cue).total_seconds()
            last=(datetime.fromisoformat(b['ended_utc'])-cue).total_seconds()
            lines+=['',f"B started {first:.2f} seconds and ended {last:.2f} seconds after the departure cue, within the instructed 30-second absence. There was no live confirmation from outside the room. C followed the operator's return confirmation; their later note identified a different lean. Exact departure, physical return time, pose and door position were not independently measured.", '',
                    'The capture record and raw sidecars originally describe controller commands as operator confirmation. That wording is too strong for the timed B capture; the operator-events sidecar corrects it without changing the original capture record or raw files.', '']
    lines+=['## Measurement method','',
            'Each short burst used the same 4096-sample coded pilot, 5771.5 MHz center, 5 MS/s, 1.8 MHz nominal pilot span, 45 dB TX attenuation and 40 dB manual RX gain. The same device context was retained, and each phase began with a receive-only activity check that rewrote the same requested RX frequency and gain. This does not establish internal calibration-state continuity. TX was muted during the waits.', '',
            'For every burst, the pilot correlation establishes a capture reference. A fitted carrier-phase ramp is removed at sample resolution before coherent averaging. The amplitude transfer is estimated independently at the occupied pilot frequencies; no amplitude normalization removes a real gain change. The estimator subtracts its estimated averaging noise bias. Its digital gain scale is not calibrated RF path loss.', '',
            'This amplitude statistic is insensitive to arbitrary capture delay and common carrier phase. Synthetic tests verify that integer/fractional delay and phase changes do not create an amplitude change, while a known amplitude change remains measurable. The frequency curves show means in 100 kHz bins, with their between-burst SD recorded in comparison.json; individual small wiggles should not be read as resolved features. The shaded center gap contains no pilot.', '',
            '## Controls and limits','',
            '- A return toward the original response supports an association with the controlled scene change, but one cycle is not a causal proof. Repeated bursts are technical repeats, not independent randomized experiments; their SD is not a population confidence interval.',
            '- Presence/absence and pose rely on operator instructions and replies, not an independent camera or occupancy sensor. Consult the operator-events record for the departure cue, timed collection and return confirmation.',
            '- The operator reported a different lean during C. Exact body pose, door placement, chair placement and antenna geometry were not measured. Nearby computer/router activity, internal calibration state and hardware drift remain possible contributors.',
            '- The received signal combines direct coupling and unresolved multipath. A stronger signal when the person leaves could reflect changed attenuation or interference between paths; it does not identify a wall, location or distance.',
            '- Conventional near-monostatic range resolution for the 1.8 MHz pilot is about 83 m, from c/(2B). This measurement detects response changes; it does not recover room geometry. See the [range-resolution reference in the preflight report](../2026-09-06-preflight/report.md).',
            '', '## Acquisition state and reproducibility','']
    cases=[c for stage in r['stages'] for c in stage['cases']]
    lines+=[f"Recorded {len(cases)} bursts, with {sum(c['commanded_unmute_s'] for c in cases):.3f} seconds of total host-measured commanded TX-unmute time. FIFO-overflow flags: {sum(c['fifo_overflow_observed'] for c in cases)}. Digital rail hits: {sum(c['iq_metrics']['rail_component_count'] for c in cases)}. Watchdog expirations: {sum(c['watchdog_fired'] for c in cases)}.", '',
            f"Final TX mute verified: {r.get('final_tx_mute_verified',False)}. RX restore errors: {r.get('restore_errors','not yet finalized')}. Raw IQ and pilot samples are kept locally under ignored `data/local/`; source snapshots, settings, per-burst metrics and SHA-256 hashes are versioned.", '',
            f"[Acquisition record](../../experiments/{r['run_id']}/results.json) · [Comparison](../../experiments/{r['run_id']}/comparison.json) · [Operator events](../../experiments/{r['run_id']}/operator-events.json) · [Raw integrity and feature replay](../../experiments/{r['run_id']}/verification.json) · [Independent mute readback](../../experiments/{r['run_id']}/final-mute-readback.json)", '',
            '## Next controlled test','',
            'Repeat several short cycles with marked chair and body posture, matching wait durations, and interleaved seated-to-seated controls. That would estimate variation without a departure and test whether a departure effect repeats. A usable room map also needs additional geometric information or measurements; an amplitude change alone supplies neither wall range nor bearing.', '']
    (out/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({k:v for k,v in s.items() if k not in ('stages',)}))
    print(out/'report.md')


if __name__=='__main__':main()
