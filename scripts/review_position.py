"""Offline verification and descriptive review before leaving a measurement spot."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from characterize_rx import ROOT,save_json
from position_dsp import averaged_pilot_evidence


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(8*1024**2),b''):h.update(block)
    return h.hexdigest()


def overlap_fit(a,b,lo_a,lo_b):
    """Diagnostic only: fit nuisance scale/phase/delay on shared RF frequencies."""
    f=a['frequency_offset_hz']+lo_a
    fb=b['frequency_offset_hz']+lo_b
    # Exclude interpolation across the second pilot's missing DC interval.
    mask=(f>=fb.min())&(f<=fb.max())&(abs(f-lo_b)>=101500)
    if mask.sum()<32:return None
    f=f[mask];x=a['h_integer_aligned'][mask]
    y=np.interp(f,fb,b['h_integer_aligned'].real)+1j*np.interp(f,fb,b['h_integer_aligned'].imag)
    valid=(abs(x)>1e-12)&(abs(y)>1e-12);f=f[valid];x=x[valid];y=y[valid]
    if len(f)<32:return None
    u=(f-f.mean())/1e6;ratio=x/y
    fit=np.polyfit(u,np.unwrap(np.angle(ratio)),1)
    gain=float(np.median(abs(ratio)))
    model=gain*np.exp(1j*np.polyval(fit,u))*y
    return {'shared_bins':len(f),'gain_ratio_db':float(20*np.log10(gain)),
            'phase_slope_rad_per_mhz':float(fit[0]),
            'fractional_complex_residual_rms':float(np.linalg.norm(x-model)/np.linalg.norm(x)),
            'note':'Scale, common phase and linear phase fitted; small residual alone does not validate absolute range or global stitching.'}


def inspect(r,public,verify):
    records={x['id']:x for x in r['records']};problems=[];warnings=[]
    if r['status']!='completed':problems.append('Acquisition did not finish: '+r['status'])
    if not r.get('final_tx_mute_verified'):problems.append('Final mute not verified')
    if r.get('restore_errors'):problems.append('Device restore errors')
    if verify:
        if 'private_context' in r:
            p=r['private_context']
            if digest(ROOT/p['raw_relative_path'])!=p['sha256']:problems.append('Private context hash mismatch')
        for name,value in r['source_sha256'].items():
            if digest(public/name)!=value:problems.append('Source hash mismatch: '+name)
        if 'inherited_survey' in r:
            inherited=r['inherited_survey'];p=ROOT/inherited['results_relative_path']
            text=p.read_text(encoding='utf-8')
            if hashlib.sha256(text.encode()).hexdigest()!=inherited['results_sha256_lf_utf8']:
                problems.append('Inherited survey metadata hash mismatch')
            parent=json.loads(text)
            for name,value in parent['source_sha256'].items():
                if digest(p.parent/name)!=value:problems.append('Inherited source hash mismatch: '+name)
        for spec in r['waveforms'].values():
            if digest(ROOT/spec['raw_relative_path'])!=spec['sha256']:problems.append('Pilot hash mismatch')
    raw_bytes=0;channel_files=0;weak_but_averaged=[]
    off_reference=max([x['off_channel']['median_correlation'] for x in records.values() if 'off_channel' in x] or [0.])
    for i,rec in enumerate(records.values()):
        p=ROOT/rec['raw_relative_path'];raw_bytes+=rec['raw_bytes']
        if verify:
            if p.stat().st_size!=rec['raw_bytes'] or digest(p)!=rec['sha256']:
                problems.append('Raw integrity mismatch: '+rec['id'])
            meta=json.loads(p.with_suffix('.sigmf-meta').read_text())
            if meta['global']['core:datatype']!='ci16_le' or meta['global']['core:sample_rate']!=rec['settings']['stream_sample_rate_hz']:
                problems.append('Sample metadata mismatch: '+rec['id'])
            if 'channel_file' in rec:
                f=rec['channel_file'];channel_files+=1
                if digest(ROOT/f['raw_relative_path'])!=f['sha256']:problems.append('Channel file mismatch: '+rec['id'])
        if rec['fifo_overflow_observed'] or rec['iq_metrics']['outside_12bit_count']:
            problems.append('Sample integrity flag: '+rec['id'])
        if rec['kind']=='pilot':
            if rec['iq_metrics']['rail_component_count'] or rec['watchdog_fired'] or rec['watchdog_errors']:
                problems.append('Pilot clipping/watchdog fault: '+rec['id'])
            if not averaged_pilot_evidence(rec['channel'],off_reference):
                problems.append('Insufficient averaged pilot evidence: '+rec['id'])
            elif not rec['channel']['pilot_detected']:
                weak_but_averaged.append(rec['id'])
        if verify and i%100==0:print('VERIFY',i+1,'/',len(records),flush=True)
    pairs=[];missing=[]
    jobs={x['id']:x for x in r['jobs']}
    for lo in r['plan']['centers_hz']:
        f=records.get(f'forward_{lo}');b=records.get(f'reverse_{lo}')
        if f and b:
            pairs.append({'center_hz':lo,'forward_db':f['channel']['digital_transfer_power_db'],
                          'reverse_db':b['channel']['digital_transfer_power_db'],
                          'reverse_minus_forward_db':b['channel']['digital_transfer_power_db']-f['channel']['digital_transfer_power_db'],
                          'reverse_minus_forward_snr_db':float(10*np.log10(f['channel']['estimator_noise_to_signal_ratio']/b['channel']['estimator_noise_to_signal_ratio'])),
                          'forward_correlation':f['channel']['median_correlation'],
                          'reverse_correlation':b['channel']['median_correlation']})
        else:
            statuses=[jobs.get(f'{d}_{lo}',{}).get('status','missing') for d in ('forward','reverse')]
            if not any(x.startswith('skipped-') for x in statuses):missing.append(lo)
    if missing:problems.append('Missing required sweep pairs: '+str(missing))
    if len(pairs)<3:problems.append('Fewer than three paired RF centers')
    if len(pairs)<len(r['plan']['centers_hz']):warnings.append('Frequency coverage contains exclusions; inspect job reasons.')
    differences=np.array([x['reverse_minus_forward_db'] for x in pairs])
    snr_differences=np.array([x['reverse_minus_forward_snr_db'] for x in pairs])
    if len(differences) and np.percentile(abs(differences),95)>.5:
        warnings.append('95th percentile forward/reverse power change exceeds 0.5 dB.')
    anchors=[];linearity=[];off=[]
    for rec in records.values():
        if rec['id'].startswith(('start_','middle_','end_')) and 'channel' in rec:
            anchors.append({'id':rec['id'],'center_hz':rec['tx_lo_hz'],
                            'started_utc':rec['started_utc'],'tx_attenuation_db':rec['tx_attenuation_db'],
                            'power_db':rec['channel']['digital_transfer_power_db']})
        if 'off_channel' in rec:
            rho=rec['off_channel']['median_correlation'];off.append({'id':rec['id'],'correlation':rho})
            if rho>.1:problems.append('Unexpected pilot match in TX-off control: '+rec['id'])
    for label in ('start','end'):
        for lo in (5771500000,5853100000):
            base=[records.get(f'{label}_{lo}_repeat{i}') for i in (1,2,3)]
            control=records.get(f'{label}_{lo}_atten48')
            if all(base) and control:
                delta=control['channel']['digital_transfer_power_db']-np.mean([x['channel']['digital_transfer_power_db'] for x in base])
                linearity.append({'stage':label,'center_hz':lo,'measured_change_db':float(delta),
                                  'expected_change_db':-3.,'error_db':float(delta+3)})
                if abs(delta+3)>.5:warnings.append(f'Attenuation control differs from -3 dB by >0.5 dB at {label}/{lo}.')
    overlap=[]
    for direction in ('forward','reverse'):
        for lo1,lo2 in zip(r['plan']['centers_hz'][:-1],r['plan']['centers_hz'][1:]):
            first=records.get(f'{direction}_{lo1}');second=records.get(f'{direction}_{lo2}')
            if not first or not second:continue
            with np.load(ROOT/first['channel_file']['raw_relative_path']) as a,np.load(ROOT/second['channel_file']['raw_relative_path']) as b:
                fit=overlap_fit(a,b,first['settings']['rx_lo_hz'],second['settings']['rx_lo_hz'])
            if fit:overlap.append({'direction':direction,'first_center_hz':lo1,'second_center_hz':lo2,**fit})
    return {'schema':'rfmapping.position-review/v1','run_id':r['run_id'],
            'results_sha256_lf_utf8':hashlib.sha256((public/'results.json').read_text().encode()).hexdigest(),
            'reviewed_utc':datetime.now(timezone.utc).isoformat(),'raw_hashes_verified':verify,
            'raw_file_count':len(records),'raw_bytes':raw_bytes,'channel_file_count_verified':channel_files,
            'blockers':problems,'warnings':warnings,
            'conservative_screen_weak_but_averaged_evidence_passed':weak_but_averaged,
            'averaged_evidence_rule':{'minimum_correlation':max(.06,2.5*off_reference),
                                     'maximum_estimator_noise_to_signal_ratio':.25,'maximum_phase_residual_rms_deg':15},
            'acquisition_ready_to_move':bool(verify and not problems),
            'mapping_ready':False,'mapping_limit':'Retune phase, propagation delay and room geometry remain uncalibrated; position metadata may be unknown.',
            'paired_centers':len(pairs),'planned_centers':len(r['plan']['centers_hz']),
            'forward_reverse_median_abs_difference_db':float(np.median(abs(differences))) if len(differences) else None,
            'forward_reverse_p95_abs_difference_db':float(np.percentile(abs(differences),95)) if len(differences) else None,
            'forward_reverse_median_abs_snr_difference_db':float(np.median(abs(snr_differences))) if len(snr_differences) else None,
            'forward_reverse_p95_abs_snr_difference_db':float(np.percentile(abs(snr_differences),95)) if len(snr_differences) else None,
            'sweep_pairs':pairs,'anchors':anchors,'attenuation_controls':linearity,'tx_off_controls':off,'overlap_diagnostics':overlap}


def report(r,q,out):
    out.mkdir(parents=True,exist_ok=True)
    plt.rcParams.update({'font.size':10,'axes.spines.right':False,'axes.spines.top':False})
    fig,axes=plt.subplots(2,2,figsize=(12,8),layout='constrained')
    pairs=q['sweep_pairs'];f=np.array([p['center_hz'] for p in pairs])/1e6
    a=axes[0,0]
    for label,key,color in [('Ascending','forward_db','#315f87'),('Descending','reverse_db','#ad5833')]:
        a.plot(f,[p[key] for p in pairs],label=label,color=color,lw=1.4)
    a.set(title='Frequency response across the spot',xlabel='RF center (MHz)',ylabel='Digital transfer power (dB)');a.legend()
    a=axes[0,1];a.plot(f,[p['reverse_minus_forward_db'] for p in pairs],color='#ad5833',label='Raw transfer power')
    a.plot(f,[p['reverse_minus_forward_snr_db'] for p in pairs],color='#19856a',label='Relative to estimated receiver noise')
    a.axhline(0,color='gray',lw=.7);a.set(title='Repeatability after returning through the frequencies',xlabel='RF center (MHz)',ylabel='Descending minus ascending (dB)')
    a.legend(fontsize=8)
    a=axes[1,0]
    start=datetime.fromisoformat(r['started_utc']).timestamp()
    for lo in sorted(set(x['center_hz'] for x in q['anchors'])):
        data=[x for x in q['anchors'] if x['center_hz']==lo and x['tx_attenuation_db']==45]
        if not data:continue
        baseline=np.mean([x['power_db'] for x in data[:3]])
        a.plot([(datetime.fromisoformat(x['started_utc']).timestamp()-start)/60 for x in data],
               [x['power_db']-baseline for x in data],'o-',label=f'{lo/1e6:.1f} MHz',markersize=4)
    a.set(title='Reference bursts through the collection',xlabel='Minutes since start',ylabel='Change from first reference mean (dB)');a.legend(fontsize=8)
    a=axes[1,1]
    for direction,color in [('forward','#315f87'),('reverse','#ad5833')]:
        data=[x for x in q['overlap_diagnostics'] if x['direction']==direction]
        a.plot([x['first_center_hz']/1e6 for x in data],[100*x['fractional_complex_residual_rms'] for x in data],label=direction,color=color)
    a.set(title='Adjacent-window mismatch after nuisance fitting',xlabel='Lower RF center (MHz)',ylabel='Complex residual RMS (%)');a.legend(fontsize=8)
    for a in axes.ravel():a.grid(alpha=.15)
    fig.suptitle(r['plan']['position_id']+' · RF capture quality, not a room map',fontsize=15,fontweight='bold')
    fig.savefig(out/'overview.png',dpi=150);plt.close(fig)
    lines=['# '+r['plan']['position_id']+': RF collection review','',
           f"Run `{r['run_id']}`. {r['position_note']}",'',r['operator_note'],'',
           '![Position measurements](overview.png)','',
           f"Acquisition ready to move: **{q['acquisition_ready_to_move']}**. Mapping ready: **False**.",'',
           f"Paired frequency centers: {q['paired_centers']} / {q['planned_centers']}. RF bursts: {r['rf_bursts']}. Total commanded TX-unmute interval: {r['commanded_unmute_seconds']:.3f} seconds.",'',
           f"Verified raw captures: {q['raw_file_count']}, totalling {q['raw_bytes']:,} bytes. Final TX mute: {r.get('final_tx_mute_verified',False)}. Restore errors: {r.get('restore_errors',[])}.",'',
           '## Checks before moving','']
    lines+=['- BLOCKER: '+x for x in q['blockers']]
    lines+=['- Review note: '+x for x in q['warnings']]
    if not q['blockers']:lines+=['- No acquisition blockers found.']
    if q['forward_reverse_median_abs_difference_db'] is not None:
        lines+=['',f"Absolute ascending/descending transfer-power difference: median {q['forward_reverse_median_abs_difference_db']:.4f} dB; 95th percentile {q['forward_reverse_p95_abs_difference_db']:.4f} dB.", '',
                f"For the averaged signal/noise statistic, the corresponding differences are {q['forward_reverse_median_abs_snr_difference_db']:.4f} dB and {q['forward_reverse_p95_abs_snr_difference_db']:.4f} dB. This divides by within-burst estimated averaging noise; it can reduce common gain variation but is not an independent calibration. Channel motion can also enter the variance estimate. Both original power and this diagnostic are retained."]
    lines+=['','| Control | Measured change | Expected |','|---|---:|---:|']
    for c in q['attenuation_controls']:
        lines.append(f"| {c['stage']}, {c['center_hz']/1e6:.1f} MHz | {c['measured_change_db']:.3f} dB | -3 dB |")
    lines+=['','## What is retained','',
            'Raw TX-off/ambient IQ; deterministic narrow and wide pilot waveforms; raw IQ for every pilot burst; per-bin complex channel means, variance and quarter-burst means; temperatures, gain, bandwidth, frequencies, timing, clipping/overflow checks; exact capture sources and SHA-256 hashes. These permit later analyses without relying only on averaged power.', '',
            'The 3.6 MHz pilot windows overlap on a 1.5 MHz tuning grid. Each RF burst is preceded by two RX-only guards at offsets of -0.6 and +0.6 MHz, using a 3 MHz RX filter and the central +/-1.45 MHz. This avoids the measured receiver-edge rise and covers both RX DC gaps. Observed occupied intervals are skipped, not filled with transmitted data.', '',
            '## Interpretation limits','',
            'Each tuning has an arbitrary capture delay and carrier phase. Overlap diagnostics fit scale, common phase and linear phase; a small residual does not prove global phase coherence or identify absolute wall range. The guard procedure retunes RX and changes filter bandwidth before each RF burst; calibration continuity is not assumed. Frequency response includes both radio/antenna response and unresolved room paths. Operator motion, cables and antenna pose can also change it.', '',
            'The paired sweeps and reference returns are technical repeats within one collection. They do not by themselves distinguish instrumental drift from scene change. Position coordinates and antenna orientation require operator records or a separately validated estimation method.', '',
            f"The original conservative per-period correlation flag remains in every capture. {len(q['conservative_screen_weak_but_averaged_evidence_passed'])} captures below that flag still passed the separate averaged-response evidence rule: correlation above max(0.06, 2.5 times the TX-off reference), averaging noise/signal ratio below 0.25, and phase residual RMS below 15 degrees. Synthetic weak-pilot and pure-noise cases check this distinction. Passing establishes measurable averaged pilot content, not precise phase in every frequency bin.", '',
            f"[Acquisition metadata](../../experiments/{r['run_id']}/results.json) · [Detailed verification and diagnostics](../../experiments/{r['run_id']}/review.json)",'']
    (out/'report.md').write_text('\n'.join(lines),encoding='utf-8')


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('results',type=Path)
    ap.add_argument('--verify',action='store_true');args=ap.parse_args()
    r=json.loads(args.results.read_text());q=inspect(r,args.results.parent,args.verify)
    q['review_source_sha256']=digest(Path(__file__))
    q['evidence_rule_source_sha256']=digest(Path(__file__).parent/'position_dsp.py')
    save_json(args.results.parent/'review.json',q)
    out=ROOT/'reports'/r['run_id'];report(r,q,out)
    print(json.dumps({k:v for k,v in q.items() if k not in ('sweep_pairs','anchors','attenuation_controls','tx_off_controls','overlap_diagnostics')}))
    print(out/'report.md')


if __name__=='__main__':main()
