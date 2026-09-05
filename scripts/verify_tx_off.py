"""Receive-only negative control after coded-pilot calibration."""
from datetime import datetime,timezone
from pathlib import Path
import hashlib
import numpy as np
from characterize_rx import ROOT,Receiver,save_json,utc
from check_duplex import pilot,analyze_pilot,read_burst,LO,FS


def main():
    name=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%M%SZ')+'_tx-off-control'
    local,public=ROOT/'data/local'/name,ROOT/'experiments'/name
    local.mkdir(parents=True,exist_ok=False); public.mkdir(parents=True,exist_ok=False)
    result={'schema':'rfmapping.tx-off-control/v1','run_id':name,'started_utc':utc(),'receive_only':True,'source_sha256':{}}
    for source in ('verify_tx_off.py','characterize_rx.py','check_duplex.py','survey_spectrum.py'):
        data=(Path(__file__).parent/source).read_bytes(); (public/source).write_bytes(data)
        result['source_sha256'][source]=hashlib.sha256(data).hexdigest()
    r=Receiver('ip:192.168.2.1'); r.mute()
    try:
        r.configure(FS,2400000,40,LO)
        raw,status=read_burst(r)
        path=local/'control.sigmf-data'; path.write_bytes(raw)
        result.update({'analysis':analyze_pilot(np.frombuffer(raw,dtype='<i2').reshape(-1,2),pilot()),
                       'ui_status_end':status,'raw_relative_path':path.relative_to(ROOT).as_posix(),
                       'sha256':hashlib.sha256(raw).hexdigest(),'raw_bytes':len(raw),
                       'rf_chip_temperature_c':float(r.phy.find_channel('temp0',False).attrs['input'].value)/1000})
        save_json(path.with_suffix('.sigmf-meta'),{'global':{'core:datatype':'ci16_le','core:version':'1.2.5','core:sample_rate':int(r.rx_channels[0].attrs['sampling_frequency'].value),'core:description':'Receive-only negative control following coded pilot calibration.'},'captures':[{'core:sample_start':0,'core:frequency':int(r.rxlo.attrs['frequency'].value)}],'annotations':[]})
    finally:
        result['restore_errors']=r.restore_rx(); result['final_rx']=r.settings()
        result['final_bist']={k:r.phy.debug_attrs[k].value for k in ('bist_prbs','bist_tone','loopback')}
        result['ended_utc']=utc(); r.assert_muted(); result['final_tx_mute_verified']=True
        save_json(public/'results.json',result)
    print('TX-off correlation',result['analysis']['median_normalized_correlation'],'RF chip temperature',result['rf_chip_temperature_c'])
    print('RESULTS',public/'results.json')


if __name__=='__main__': main()
