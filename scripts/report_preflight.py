"""Create the position-1 preflight report from saved measurements only."""
from pathlib import Path
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from characterize_rx import ROOT


def latest(suffix):
    p=sorted((ROOT/'experiments').glob('*_'+suffix+'/results.json'))[-1]
    return p,json.loads(p.read_text())


def main():
    pp,prbs=latest('rx-prbs'); sp,survey=latest('survey'); mp,monitor=latest('monitor')
    dp,duplex=latest('duplex-calibration'); op,off=latest('tx-off-control')
    analysis=json.loads((sp.parent/'spectrum-analysis.json').read_text())
    out=ROOT/'reports/2026-09-06-preflight'; out.mkdir(parents=True,exist_ok=True)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,ax=plt.subplots(2,2,figsize=(13,8),layout='constrained')
    for a,band,title in zip(ax[0],analysis['bands'],['2.4 GHz: intermittent and strong activity','5.8 GHz: relatively quiet during observation']):
        f=np.array(band['frequency_hz'])/1e6
        a.plot(f,band['maximum_psd_dbfs_per_hz'],color='#aa4638',lw=1,label='Maximum observed, 1.64 ms averages')
        a.plot(f,band['median_psd_dbfs_per_hz'],color='#315f87',lw=1,label='Median observed')
        a.set(title=title,xlabel='Frequency (MHz)',ylabel='Received PSD (dBFS/Hz)')
        a.grid(alpha=.15); a.legend(fontsize=8,loc='upper right')
    ax[0,1].axvline(5771.5,color='#19856a',ls='--',lw=1)
    ax[0,1].text(.03,.04,'Pilot test: 5771.5 MHz',transform=ax[0,1].transAxes,
                 fontsize=9,color='#126b54',bbox={'facecolor':'white','edgecolor':'none','alpha':.9})
    a=ax[1,0]
    counts=[c['transition_mismatches'] for c in prbs['cases']]
    a.bar(range(3),counts,color=['#19856a','#aa4638','#19856a'],width=.5)
    for i,c in enumerate(prbs['cases']):
        a.text(i,counts[i]+.10,f"{counts[i]} errors\n{c['sample_count']/1e6:.1f} M samples",ha='center',fontsize=9)
    a.set_xticks(range(3),['5 MS/s','7 MS/s\noverload control','5 MS/s repeat'])
    a.set(title='Known pattern verifies sample ordering',ylabel='PRBS transition errors',ylim=(0,4))
    a.set_yticks(range(5)); a.grid(axis='y',alpha=.15)
    a=ax[1,1]
    cases=duplex['cases'];rho=[c['analysis']['median_normalized_correlation'] for c in cases]
    a.plot(range(1,len(cases)+1),rho,'o-',color='#315f87')
    a.axhline(.15,color='#89939d',ls='--',label='Detection threshold')
    a.axhline(off['analysis']['median_normalized_correlation'],color='#aa4638',ls=':',label='TX-off negative control')
    a.set_xticks(range(1,len(cases)+1),[str(abs(c['gain_setting_db'])) for c in cases])
    a.set(title='Received pilot follows the transmit level',xlabel='TX attenuation (dB); one burst per point',ylabel='Normalized pilot correlation',ylim=(0,.45))
    a.legend(fontsize=8,loc='upper left');a.grid(alpha=.15)
    fig.suptitle('Position 1 · Spectrum, data integrity and duplex preflight',fontsize=16,fontweight='bold')
    fig.savefig(out/'overview.png',dpi=160);plt.close(fig)
    detected=[c for c in cases if c['pilot_detected']]
    gate=sum(c['host_measured_unmuted_interval_s'] for c in cases)
    lines=['# Position 1 preflight', '',
           'Local dates: 5–6 September 2026 (Asia/Jerusalem). Run identifiers use UTC. Asset: RFL-SDR-001.', '',
           'The receive data path and a brief low-level full-duplex coded-pilot measurement work at this desk position. A usable next measurement can now include a timing reference. These checks do not establish a floor plan or calibrated range.', '',
           '![Measured preflight overview](overview.png)', '', '## Setup and observations', '',
           'The supplied TX/RX antennas remained attached. The user reported sitting near the SDR, possibly moving or leaving, with the SDR near the computer and a few feet from a router. Distances, antenna orientation and movement times were not measured. The host reported a 5 GHz channel-36 Wi-Fi association; this does not identify every nearby transmitter. SSID, BSSID and the hardware serial are not published.', '',
           '## Sample ordering', '',
           'The internal AD936x PRBS generator was injected into the RX digital port, with TX muted and RF loopback disabled. Two 5 MS/s captures each contained 16,777,216 complex samples with zero I/Q overlap errors and zero invalid sequence transitions, including buffer boundaries. The 7 MS/s overload control contained three sequence skips, all at buffer boundaries, and asserted the RX FIFO overflow flag.', '',
           'This is stronger evidence than delivery timing alone. It tests the digital path from the PRBS injection point through the FPGA and host, not the analog receiver. The pattern has 65,535 states, so loss of an exact whole period can be invisible. The alternative I/Q reversal and recurrence-direction representations are equivalent; the selected software reconstruction is not independent proof of analog I/Q polarity.', '',
           '## Spectrum survey', '',
           'Three passes covered 2400–2483.5 MHz and 5725–5875 MHz, using 234 main tuning dwells of approximately 105 ms each at 5 MS/s, manual gain 40 dB, a 4 MHz RX filter, and the central 3 MHz for spectral analysis. Two clipped 2.4 GHz dwells were repeated at 20 dB gain. All 236 dwells completed without recorded FIFO overflow.', '',
           'The 2.4 GHz region contained strong and intermittent signals. The clipped centers were about 2461.5 and 2462.5 MHz; the lower-gain repeats did not clip. A relatively quiet sweep candidate at 2475.5 MHz showed bursts on a subsequent 10.07-second dwell and was excluded from the pilot test.', '',
           '| Fixed RX center | Dwell | Peak excess over its median PSD | Result |',
           '|---|---:|---:|---|']
    for t in monitor['tiles']:
        a=np.array(t['spectrum_50khz_bins']); keep=abs(a[:,0])>50000
        excess=float(a[keep,3].max()-np.median(a[keep,2]))
        lines.append(f"| {t['lo_hz']/1e6:.4f} MHz | {t['observed_sample_time_s']:.2f} s | {excess:.2f} dB | {'Bursts; excluded' if t['lo_hz']<3e9 else 'No comparable excess detected'} |")
    lines+=['', 'The 5.8 GHz observations are a finite local survey, not proof of permanently empty spectrum. PSD is relative to digital full scale, not calibrated RF power. Hidden receivers, weak signals, intermittent transmissions, antenna response and receiver compression remain limitations. The 20th-percentile band reference used for ranking is not a calibrated noise floor.', '',
            '## Low-level duplex and timing check', '',
            'A fresh receive-only guard check preceded the transmission. The pilot used a 5771.5 MHz center and a 1.8 MHz nominal frequency span, with a DC notch. A deterministic 4096-sample periodic code was sent from a small cyclic DMA buffer. Each burst was guarded by a separate-context 0.8-second TX-mute timer and ended normally before that timer fired.', '',
            f'There were {len(cases)} RF bursts, each approximately 0.38–0.40 seconds, totalling {gate:.3f} seconds of host-measured commanded unmute intervals. Hardware TX attenuation progressed from 75 to 45 dB; digital complex power was {duplex["pilot_component_rms_dbfs"]:.2f} dBFS relative to 32768. No amplifier was used. Radiated power and unwanted emissions were not measured, so these settings are not an EIRP calibration.', '',
            '| Burst | TX attenuation | Median correlation | Detection |', '|---|---:|---:|---|']
    for c in cases:
        lines.append(f"| {c['id']} | {abs(c['gain_setting_db'])} dB | {c['analysis']['median_normalized_correlation']:.4f} | {'Yes' if c['pilot_detected'] else 'Below conservative threshold'} |")
    lines+=['',f'The four 45 dB attenuation captures repeated at correlation 0.358–0.360, compared with {duplex["baseline"]["analysis"]["median_normalized_correlation"]:.4f} before TX and {off["analysis"]["median_normalized_correlation"]:.4f} in the subsequent TX-off control. No digital clipping or RX FIFO overflow occurred. Within each detected burst, residual phase variation after a linear fit was approximately 1.05–1.14 degrees RMS. This does not certify coherence across retunes or restarts.', '',
            'The detected correlation peak was localized to adjacent sample bins within each burst, but moved between 1273/1274, 2758/2759, 2163/2164 and 3710/3711 across stream restarts. Those offsets include arbitrary acquisition timing. They must not be multiplied by propagation speed and interpreted as wall ranges. A reference and alignment step are required for each capture.', '',
            'The received pilot can include direct antenna coupling, coupling inside the device and room multipath. This test does not separate them. Its approximately 1.8 MHz span gives conventional near-monostatic range resolution of roughly 83 m, much coarser than a room. Wider calibrated measurements, stronger scene assumptions or additional measured positions are needed for useful geometry; even 56 MHz corresponds to roughly 2.7 m conventional range resolution.', '',
            '## End state and next experiment', '',
            'TX is muted: TX LO powered down, maximum attenuation restored, DDS zeroed/disabled, and cyclic TX buffers destroyed. RX settings were restored and BIST/loopback were off. A separate RX-only negative control confirmed disappearance of the pilot. Final RF-chip telemetry was 35.1 °C.', '',
            'The next position-1 experiment should measure a repeatable channel response with an in-capture reference and a controlled scene change. Report direct coupling and unresolved multipath explicitly. Do not infer a room outline from a single stationary omnidirectional pair, and do not coherently combine separated frequency windows until retune phase and hardware response have been calibrated.', '',
            'One initial calibration attempt failed before TX unmute because libiio required a mutable bytearray. The corrected attempt succeeded; the failed attempt and its note are retained. No RF burst was started by that failed attempt.', '',
            '## Reproducibility', '',
            'Raw IQ, pilot samples and SigMF sidecars remain in ignored `data/local/`. Public records contain requested/readback settings, timing, statistics, source hashes and data hashes. Exact capture sources are preserved beside each run. Synthetic checks cover PRBS errors and missing samples, pilot delay/frequency recovery, false detection on noise, digital level/bandwidth and spectrum frequency sign.', '', 'Records:', '']
    for p in [pp,sp,mp,dp,op]: lines.append(f'- [{p.parent.name}](../../experiments/{p.parent.name}/results.json)')
    lines+=['', 'Technical references: [ADI BIST description](https://analogdevicesinc.github.io/documentation/solutions/reference-designs/fmcomms2/software/ad9361_adv_plugin.html), [ADI PRBS reference](https://github.com/analogdevicesinc/hdl/blob/hdl_2019_r2/library/axi_ad9361/axi_ad9361_rx_pnmon.v), [supplied antenna measurements](https://wiki.analog.com/university/tools/pluto/users/antennas), [range-resolution relationship](https://www.analog.com/en/resources/technical-articles/how-to-build-a-24-ghz-fmcw-radar-system.html).', '']
    (out/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    print(out/'report.md')


if __name__=='__main__': main()
