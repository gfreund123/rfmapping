"""Receive-only check of noise shape versus bandwidth and RF center; never transmits."""
from argparse import Namespace
from pathlib import Path
import hashlib
import numpy as np
from position_capture import Session


def main():
    s=Session(Namespace(position_id='guard-check',note='Current desk, diagnose receiver-edge response.',operator_note='No controlled scene intervention.'))
    source=Path(__file__).read_bytes();(s.public/'diagnose_guard.py').write_bytes(source)
    s.result['source_sha256']['diagnose_guard.py']=hashlib.sha256(source).hexdigest()
    s.result['receive_only']=True
    try:
        s.open_radio()
        for bw in (2400000,3000000,4000000):
            for lo in (5771500000,5800000000,5853100000):
                s.tune(lo,bandwidth=bw)
                rec,_=s.receive(f'bw{bw}_lo{lo}',8)
                a=np.array(rec['activity']['bins']);mask=(abs(a[:,0])<=1450000)&(abs(a[:,0])>75000)
                rec['core_max_excess_db']=float(a[mask,3].max()-np.median(a[mask,2]))
                rec['core_max_dbfs_hz']=float(a[mask,3].max());s.save()
                print(bw,lo,'core',round(rec['core_max_excess_db'],2),round(rec['core_max_dbfs_hz'],2),'wide',round(rec['activity']['maximum_excess_db'],2),flush=True)
        s.result['status']='completed'
    finally:s.close();print('RESULTS',s.public/'results.json',flush=True)


if __name__=='__main__':main()
