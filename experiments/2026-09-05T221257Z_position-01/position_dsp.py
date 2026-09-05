"""Known-waveform channel measurements and receive-only activity checks.

The complex response retains frequency structure, but its absolute delay/phase
include acquisition and radio delays. No range or cross-tuning coherence assumed.
"""
import numpy as np
from check_duplex import FS, PERIOD, pilot as narrow_pilot


def make_pilot(wide=True):
    if not wide:
        return narrow_pilot(), {'name':'legacy-1p8MHz','edge_hz':900000,'notch_hz':100000}
    rng=np.random.default_rng(9062027)
    freq=np.fft.fftfreq(PERIOD,1/FS)
    active=(abs(freq)>=100000)&(abs(freq)<=1800000)
    xf=np.zeros(PERIOD,complex)
    xf[active]=np.exp(1j*(np.pi/4+np.pi/2*rng.integers(0,4,active.sum())))
    x=np.fft.ifft(xf)
    reference=narrow_pilot().astype(float)
    limit_power=np.mean(np.sum(reference**2,axis=1))
    scale=min(8191/np.max(np.maximum(abs(x.real),abs(x.imag))),
              np.sqrt(limit_power/np.mean(abs(x)**2))*.999)
    tx=np.round(np.column_stack((x.real,x.imag))*scale).astype('<i2')
    return tx,{'name':'overlap-3p6MHz','edge_hz':1800000,'notch_hz':100000,
               'seed':9062027,'complex_power_dbfs':float(10*np.log10(np.mean(np.sum(tx.astype(float)**2,axis=1))/32768**2))}


def activity(iq,fs=FS,usable_edge_hz=1950000):
    nfft=2048;window=np.hanning(nfft)
    z=iq[:,0].astype(float)+1j*iq[:,1]
    z=z[:len(z)//(4*nfft)*(4*nfft)].reshape(-1,nfft)
    p=abs(np.fft.fft(z*window,axis=1))**2/(fs*np.sum(window**2)*2048**2)
    p=np.fft.fftshift(p.reshape(-1,4,nfft).mean(axis=1),axes=1)
    f=np.fft.fftshift(np.fft.fftfreq(nfft,1/fs))
    rows=[]
    for center in np.arange(-2125000,2150000,50000):
        v=p[:,(f>=center-25000)&(f<center+25000)].mean(axis=1)
        rows.append([float(center),*[float(10*np.log10(max(x,1e-30))) for x in (v.mean(),np.median(v),v.max())]])
    rows=np.array(rows)
    valid=(abs(rows[:,0])<=usable_edge_hz)&(abs(rows[:,0])>75000)
    floor=float(np.median(rows[valid,2]))
    hot=valid&((rows[:,3]>floor+8)|(rows[:,3]>-114))
    return {'columns':['offset_hz','mean_dbfs_hz','median_dbfs_hz','max_1p6384ms_dbfs_hz'],
            'bins':rows.tolist(),'reference_median_dbfs_hz':floor,
            'maximum_excess_db':float(rows[valid,3].max()-floor),
            'maximum_dbfs_hz':float(rows[valid,3].max()),
            'hot_offsets_hz':rows[hot,0].tolist(),'quiet_observed':not bool(hot.any()),
            'usable_edge_hz':usable_edge_hz,
            'limits':'Finite uncalibrated receive observation, excluding the RX DC vicinity.'}


def channel(iq,tx,spec,fs=FS):
    x=tx[:,0].astype(float)+1j*tx[:,1];xf=np.fft.fft(x)
    freq=np.fft.fftfreq(len(tx),1/fs)
    active=(abs(freq)>=spec['notch_hz'])&(abs(freq)<=spec['edge_hz'])
    z=iq[:,0].astype(float)+1j*iq[:,1]
    frames=z[:len(z)//len(tx)*len(tx)].reshape(-1,len(tx))
    if len(frames)<8:raise ValueError('At least eight pilot periods required')
    candidates=[]
    for conjugate in (False,True):
        f=np.conj(frames) if conjugate else frames
        corr=np.fft.ifft(np.fft.fft(f,axis=1)*np.conj(xf),axis=1)
        lag=int(np.argmax(np.mean(abs(corr)**2,axis=0)));peak=corr[:,lag]
        rho=abs(peak)/np.sqrt(np.maximum(np.sum(abs(f)**2,axis=1)*np.sum(abs(x)**2),1e-30))
        candidates.append((float(np.median(rho)),conjugate,lag,peak))
    rho,conjugate,lag,peak=max(candidates,key=lambda a:a[0])
    t=np.arange(len(frames))*len(tx)/fs;phi=np.unwrap(np.angle(peak));coef=np.polyfit(t,phi,1)
    model=np.polyval(coef,t)[:,None]+coef[0]*np.arange(len(tx))[None,:]/fs
    selected=np.conj(frames) if conjugate else frames
    h=np.fft.fft(selected*np.exp(-1j*model),axis=1)[:,active]/xf[active]
    hm=h.mean(axis=0);var=np.var(h,axis=0,ddof=1)
    power=np.maximum(abs(hm)**2-var/len(h),1e-30)
    f=freq[active];order=np.argsort(f)
    quarter=np.array([g.mean(axis=0) for g in np.array_split(h,4)])
    # Integer correlation alignment is exported separately, not mistaken for range.
    aligned=hm*np.exp(2j*np.pi*f*lag/fs)
    summary={'median_correlation':rho,'pilot_detected':bool(rho>.15),
             'conjugate_rx':conjugate,'alignment_lag_samples':lag,'period_count':len(h),
             'phase_slope_hz':float(coef[0]/(2*np.pi)),
             'phase_residual_rms_deg':float(np.std(phi-np.polyval(coef,t))*180/np.pi),
             'digital_transfer_power_db':float(10*np.log10(power.mean())),
             'estimator_noise_to_signal_ratio':float(np.mean(var/len(h))/power.mean()),
             'quarter_transfer_db':[float(10*np.log10(max(np.mean(abs(q)**2),1e-30))) for q in quarter],
             'phase_scope':'Within-burst common phase ramp removed. Retune/restart phase and absolute delay uncalibrated.'}
    arrays={'frequency_offset_hz':f[order],'h_mean':hm[order],
            'h_integer_aligned':aligned[order],'h_variance':var[order],
            'signal_power':power[order],'quarter_h_mean':quarter[:,order],
            'correlation_phase_rad':phi,'phase_fit_rad_per_second_and_intercept':coef}
    return summary,arrays
