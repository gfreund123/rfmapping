"""Amplitude response of a known pilot, invariant to capture phase and delay.

Absolute RF gain and range are not calibrated. Removing capture phase/timing also
removes any inseparable bulk propagation phase; these are amplitude observables.
"""
import numpy as np
from check_duplex import PERIOD,FS


def extract(iq,tx):
    x=tx[:,0].astype(float)+1j*tx[:,1]
    xf=np.fft.fft(x)
    freq=np.fft.fftfreq(PERIOD,1/FS)
    active=(abs(freq)>=100000)&(abs(freq)<=900000)
    z=iq[:,0].astype(float)+1j*iq[:,1]
    frames=z[:len(z)//PERIOD*PERIOD].reshape(-1,PERIOD)
    choices=[]
    for conjugate in (False,True):
        f=np.conj(frames) if conjugate else frames
        rf=np.fft.fft(f,axis=1)
        corr=np.fft.ifft(rf*np.conj(xf),axis=1)
        lag=int(np.argmax(np.mean(abs(corr)**2,axis=0)))
        peak=corr[:,lag]
        rho=abs(peak)/np.sqrt(np.maximum(np.sum(abs(f)**2,axis=1)*np.sum(abs(x)**2),1e-30))
        choices.append((float(np.median(rho)),conjugate,lag,peak,rf))
    rho,conjugate,lag,peak,rf=max(choices,key=lambda a:a[0])
    t=np.arange(len(peak))*PERIOD/FS
    phi=np.unwrap(np.angle(peak)); coef=np.polyfit(t,phi,1)
    # Correct the smooth phase ramp at sample resolution, including within each
    # period. Frame-only correction leaves small frequency-dependent CFO bias.
    selected=np.conj(frames) if conjugate else frames
    model=np.polyval(coef,t)[:,None]+coef[0]*np.arange(PERIOD)[None,:]/FS
    rf=np.fft.fft(selected*np.exp(-1j*model),axis=1)
    h=rf[:,active]/xf[active]
    hmean=h.mean(axis=0)
    variance=np.var(h,axis=0,ddof=1)
    signal_power=np.maximum(abs(hmean)**2-variance/len(h),1e-30)
    overall=float(10*np.log10(signal_power.mean()))
    bins=[]
    af=freq[active]
    for center in list(np.arange(-850000,-100000,100000))+list(np.arange(150000,900000,100000)):
        select=(af>=center-50000)&(af<center+50000)
        bins.append([int(center),float(10*np.log10(signal_power[select].mean()))])
    groups=[]
    for g in np.array_split(h,4):
        p=np.maximum(abs(g.mean(axis=0))**2-np.var(g,axis=0,ddof=1)/len(g),1e-30)
        groups.append(float(10*np.log10(p.mean())))
    return {'median_correlation':rho,'pilot_detected':bool(rho>.15),'conjugate_rx':conjugate,
            'alignment_lag_samples':lag,'period_count':len(h),'phase_slope_hz':float(coef[0]/(2*np.pi)),
            'phase_residual_rms_deg':float(np.sqrt(np.mean((phi-np.polyval(coef,t))**2))*180/np.pi),
            'digital_transfer_power_db':overall,'frequency_bin_columns':['offset_hz','digital_transfer_power_db'],
            'frequency_bins':bins,'quarter_burst_transfer_db':groups,
            'mean_estimator_noise_to_signal_ratio':float(np.mean(variance/len(h))/np.mean(signal_power)),
            'interpretation':'Fixed-setting digital amplitude transfer only. Not calibrated path loss, geometric range or absolute carrier phase.'}
