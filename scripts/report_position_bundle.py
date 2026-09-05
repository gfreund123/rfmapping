"""Write a readable summary of an already verified position bundle; no radio access."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from characterize_rx import ROOT,save_json,utc
from review_position import digest


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('results',type=Path)
    args=ap.parse_args();p=args.results;r=json.loads(p.read_text());q=json.loads((p.parent/'review.json').read_text());b=json.loads((p.parent/'bundle.json').read_text())
    if not b['acquisition_ready_to_move'] or not q['raw_hashes_verified'] or q.get('results_sha256_lf_utf8')!=hashlib.sha256(p.read_text().encode()).hexdigest():
        raise ValueError('A completed verified bundle matching these results is required')
    runs=[r]+[json.loads((ROOT/'experiments'/key/'results.json').read_text()) for key in b['controls_runs']]
    pilots=[x for run in runs for x in run['records'] if x['kind']=='pilot']
    temperature=np.array([x['rf_chip_temperature_c'] for x in pilots]);median=float(np.median(temperature))
    anomalies=[{'id':x['id'],'temperature_readback_c':x['rf_chip_temperature_c'],'started_utc':x['started_utc']} for x in pilots if abs(x['rf_chip_temperature_c']-median)>8]
    summary={'created_utc':utc(),'main_run':r['run_id'],'position_id':r['plan']['position_id'],
        'rf_bursts':sum(x['rf_bursts'] for x in runs),'raw_file_count':sum(len(x['records']) for x in runs),
        'raw_bytes_verified':b['raw_bytes_verified'],'commanded_unmute_seconds':sum(x['commanded_unmute_seconds'] for x in runs),
        'all_stages_final_mute_verified':all(x.get('final_tx_mute_verified',False) for x in runs),
        'all_stages_restore_errors':[e for x in runs for e in x.get('restore_errors',[])],
        'temperature_readback_median_c':median,'temperature_readback_outliers':anomalies,
        'temperature_flag_rule':'More than 8 C from the median of all pilot readbacks; descriptive outlier flag, not a sensor diagnosis or calibration.',
        'report_source_sha256':digest(Path(__file__))}
    out=ROOT/'reports'/r['run_id'];out.mkdir(parents=True,exist_ok=True)
    save_json(out/'bundle-summary.json',summary)
    lines=['# '+r['plan']['position_id']+': complete RF bundle review','',r['position_note'],'',
        f"Acquisition ready to move: **{b['acquisition_ready_to_move']}**. Geometry inference remains **unvalidated**.",'',
        f"The main and reference-control stages saved **{summary['rf_bursts']} pilot bursts** and **{summary['raw_file_count']} raw captures**, totaling **{summary['raw_bytes_verified']:,} bytes**. The recorded reviews verify hashes, sample integrity, pilot evidence, negative controls, required coverage and final state.",'',
        f"All stages verified final TX mute: **{summary['all_stages_final_mute_verified']}**. Restore errors: {summary['all_stages_restore_errors']}. Total commanded unmute interval: {summary['commanded_unmute_seconds']:.3f} seconds.",'',
        'Raw IQ, TX samples, complex channel estimates and private context are retained locally. The public record contains source snapshots, settings, hashes, quality metrics and annotations.','',
        '## Coverage and repeatability','',
        f"Paired ascending/descending frequency centers: **{q['paired_centers']} / {q['planned_centers']}**. Median absolute power difference: **{q['forward_reverse_median_abs_difference_db']:.4f} dB**; 95th percentile: **{q['forward_reverse_p95_abs_difference_db']:.4f} dB**.",'',
        'The following reference trains held frequency and filter settings fixed between seven bursts:','',
        '| Center | Bursts | Power standard deviation |','|---|---:|---:|']
    for s in b['held_summaries']:lines.append(f"| {s['center_hz']/1e6:.1f} MHz | {s['burst_count']} | {s['between_burst_sd_db']:.4f} dB |")
    lines+=['','Warnings and deviations remain part of the record:','']
    items=b['main_blockers']+b['main_warnings']+b['control_issues']+b['deviations']
    lines.extend('- '+item for item in (items or ['No acquisition blockers or review warnings recorded.']))
    lines+=['','The raw power differences and control variability describe technical repeats. They do not isolate instrument drift, operator changes, position or orientation effects. The noise-relative statistic and attenuation controls are detailed in the [main review](report.md).','',
        '## Temperature metadata','',
        f"Median pilot temperature readback: {median:.3f} C. {len(anomalies)} readbacks differed from this median by more than 8 C. These values remain unchanged in the original data and are flagged in bundle-summary.json. No temperature-based correction was applied.",'',
        '## Interpretation and retained evidence','',
        'Coordinates and height remain unknown where no ground truth was supplied. The RF data are preserved for blind inference, with unknown antenna geometry, instrumental response and capture phase treated explicitly. Acquisition completion does not establish a room map.','',
        '![Frequency sweep and quality diagnostics](overview.png)','',
        f"[Machine-readable bundle](../../experiments/{r['run_id']}/bundle.json) · [Operator annotations](../../experiments/{r['run_id']}/operator-events.json) · [Collection protocol](../../docs/position-protocol.md)",'']
    (out/'bundle.md').write_text('\n'.join(lines),encoding='utf-8')
    (out/'report_position_bundle.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps(summary))


if __name__=='__main__':main()
