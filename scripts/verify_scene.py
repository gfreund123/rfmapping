"""Offline integrity and feature replay for a completed scene capture; no SDR access."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import numpy as np
from characterize_rx import ROOT,save_json
from channel_features import extract


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha(path):
    # Git normalizes public JSON line endings. Normalize only these text hashes;
    # raw IQ, pilot, and exact capture-source hashes remain byte-for-byte checks.
    return hashlib.sha256(path.read_text(encoding='utf-8').encode('utf-8')).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('results',type=Path)
    args=parser.parse_args()
    r=json.loads(args.results.read_text())
    assert r['status']=='completed'
    assert [s['phase'] for s in r['stages']]==['A','B','C']
    assert r['final_tx_mute_verified'] and not r['restore_errors']
    for name,value in r['source_sha256'].items():
        assert sha(args.results.parent/name)==value,name
    # Replay with the same estimator that was used during collection.
    assert sha(Path(__file__).parent/'channel_features.py')==r['source_sha256']['channel_features.py']
    local=ROOT/'data/local'/r['run_id']
    assert sha(local/'pilot-ci16.bin')==r['pilot_sha256']
    tx=np.fromfile(local/'pilot-ci16.bin',dtype='<i2').reshape(-1,2)
    raw_files=0;raw_bytes=0;replayed=0;max_error=0.
    for stage in r['stages']:
        assert len(stage['cases'])==r['protocol']['bursts_per_stage']
        for record in [stage['receive_guard'],*stage['cases']]:
            p=ROOT/record['raw_relative_path']
            assert sha(p)==record['sha256'],record['id']
            assert p.stat().st_size==record['raw_bytes']
            assert not record['fifo_overflow_observed']
            assert record['iq_metrics']['rail_component_count']==0
            assert record['iq_metrics']['outside_12bit_count']==0
            meta=json.loads(p.with_suffix('.sigmf-meta').read_text())
            assert meta['global']['core:datatype']=='ci16_le'
            assert meta['global']['core:sample_rate']==stage['end_state']['stream_sample_rate_hz']
            raw_files+=1;raw_bytes+=p.stat().st_size
            if 'features' in record:
                assert record['features']['pilot_detected'] and not record['watchdog_fired']
                assert not record['watchdog_errors']
                iq=np.fromfile(p,dtype='<i2').reshape(-1,2)
                assert len(iq)==r['protocol']['samples_per_burst']
                f=extract(iq,tx)
                error=abs(f['digital_transfer_power_db']-record['features']['digital_transfer_power_db'])
                max_error=max(max_error,error)
                np.testing.assert_allclose(f['digital_transfer_power_db'],record['features']['digital_transfer_power_db'],atol=1e-9,rtol=0)
                np.testing.assert_allclose(f['frequency_bins'],record['features']['frequency_bins'],atol=1e-9,rtol=0)
                replayed+=1
    out={'schema':'rfmapping.scene-verification/v1','verified_utc':datetime.now(timezone.utc).isoformat(),
         'run_id':r['run_id'],'source_snapshots_verified':len(r['source_sha256']),
         'raw_capture_files_verified':raw_files,'raw_capture_bytes_verified':raw_bytes,
         'pilot_bytes_verified':(local/'pilot-ci16.bin').stat().st_size,
         'burst_features_replayed':replayed,'maximum_transfer_replay_error_db':max_error,
         'numpy_version':np.__version__,'verification_source_sha256':sha(Path(__file__)),
         'operator_annotation_sha256_lf_utf8':text_sha(args.results.parent/'operator-events.json'),
         'capture_results_sha256_lf_utf8':text_sha(args.results),
         'text_hash_convention':'UTF-8 after universal-newline normalization to LF; capture source and raw hashes use original bytes.',
         'result':'passed'}
    save_json(args.results.parent/'verification.json',out)
    print(json.dumps(out))


if __name__=='__main__':main()
