"""Rank relatively quiet observed intervals; no transmit authorization implied."""
import argparse
import json
from pathlib import Path
import numpy as np
from characterize_rx import save_json


def aggregate(r):
    bands=[]
    for lo,hi in r['intervals_hz']:
        grid=np.arange(lo+25000,hi,50000,dtype=float)
        observations=[[] for _ in grid]
        invalid=np.zeros(len(grid),dtype=bool)
        for tile in r['tiles']:
            if tile['gain_db']!=40: continue
            for off,mean,median,maximum in tile['spectrum_50khz_bins']:
                if abs(off)<50000: continue
                f=tile['lo_hz']+off
                if not lo<=f<hi: continue
                idx=int(round((f-lo-25000)/50000))
                if idx<0 or idx>=len(grid): continue
                if tile['fifo_overflow_observed'] or tile['iq_metrics']['rail_component_count']:
                    invalid[idx]=True
                observations[idx].append([mean,median,maximum,tile['pass'] or 0])
        count=np.array([len(x) for x in observations])
        def stats(col,fn):
            return np.array([float(fn(np.array(x)[:,col])) if x else np.nan for x in observations])
        med=stats(1,np.median); worst=stats(2,np.max); mean=stats(0,np.mean)
        floor=float(np.nanpercentile(med,20))
        candidates=[]
        # 2 MHz windows with an extra 0.5 MHz observed guard on both sides.
        for start in range(len(grid)-60+1):
            sl=slice(start,start+60)
            if np.any(count[sl]<2) or np.any(invalid[sl]): continue
            worst_excess=float(np.max(worst[sl])-floor)
            candidates.append({'center_hz':float((grid[start]+grid[start+59])/2),
                               'proposed_probe_bandwidth_hz':2000000,'observed_guarded_span_hz':3000000,
                               'max_observed_psd_dbfs_per_hz':float(np.max(worst[sl])),
                               'max_excess_over_band_reference_db':worst_excess,
                               'median_psd_dbfs_per_hz':float(np.median(med[sl])),
                               'minimum_bin_observations':int(count[sl].min())})
        ranked=[]
        for c in sorted(candidates,key=lambda c:c['max_observed_psd_dbfs_per_hz']):
            if all(abs(c['center_hz']-p['center_hz'])>=5000000 for p in ranked): ranked.append(c)
            if len(ranked)==5: break
        bands.append({'interval_hz':[lo,hi],'reference_psd_dbfs_per_hz':floor,
                      'reference_definition':'20th percentile of median observed per-bin PSD across this band; not a calibrated noise floor',
                      'frequency_hz':grid.tolist(),'observation_counts':count.tolist(),'invalid_bins':invalid.tolist(),
                      'median_psd_dbfs_per_hz':[None if not np.isfinite(x) else x for x in med],
                      'maximum_psd_dbfs_per_hz':[None if not np.isfinite(x) else x for x in worst],
                      'ranked_relative_quiet_windows':ranked,
                      'bins_exceeding_reference_plus_10db_fraction':float(np.mean(worst[np.isfinite(worst)]>floor+10)) if np.any(np.isfinite(worst)) else None})
    return {'schema':'rfmapping.relative-spectrum-analysis/v1','source_run':r['run_id'],'bands':bands,
            'interpretation':'Ranking describes only the finite observed dwells and uncalibrated receiving setup. It does not establish empty spectrum or authorize transmission.'}


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('results',type=Path); args=p.parse_args()
    r=json.loads(args.results.read_text()); out=aggregate(r)
    save_json(args.results.parent/'spectrum-analysis.json',out)
    for band in out['bands']:
        print('BAND',band['interval_hz'],'reference',band['reference_psd_dbfs_per_hz'],'activity fraction',band['bins_exceeding_reference_plus_10db_fraction'])
        for c in band['ranked_relative_quiet_windows']: print(c)


if __name__=='__main__': main()
