"""Experimental overlap reconstruction with explicit instrument-response gauges.

Reconstruction has arbitrary overall complex gain and linear phase. An unknown
common quadratic baseband phase also produces a quadratic RF phase ambiguity.
Reported delay profiles are diagnostics, never calibrated wall ranges.
"""
import numpy as np
from scipy.signal import find_peaks
from deep_channel import load_run,load_channel,image_code,smooth_image_fit


def prepare(path,degree=8,quarter=None):
    r,xf=load_run(path);sweeps={}
    for direction in ('forward','reverse'):
        rows=[]
        recs=sorted([x for x in r['records'] if x['kind']=='pilot' and x['id'].startswith(direction+'_')],key=lambda x:x['settings']['rx_lo_hz'])
        for rec in recs:
            a=load_channel(rec);f=a['frequency_offset_hz'];h=a['h_integer_aligned'];v=a['variance_mean']
            if quarter is not None:
                h=a['quarter_h_mean'][quarter]*np.exp(2j*np.pi*f*rec['channel']['alignment_lag_samples']/5000000)
                v=v*4
            fit=smooth_image_fit(f,h,v,image_code(f,xf),degree)
            rows.append({'center':rec['settings']['rx_lo_hz'],'f':f,'h':fit['direct'],
                'v':v,'id':rec['id'],'source_channel_sha256':rec['channel_file']['sha256']})
        sweeps[direction]=rows
    return r,sweeps


def estimate_baseband(rows,phase_degree=5,amplitude_degree=6):
    phases=[];amplitudes=[]
    for row in rows:
        u=row['f']/1e6;h=row['h'];valid=abs(u)<1.65
        phases.append(np.polynomial.polynomial.polyfit(u[valid],np.unwrap(np.angle(h))[valid],phase_degree))
        amplitudes.append(np.polynomial.polynomial.polyfit(u[valid],np.log(abs(h[valid])),amplitude_degree))
    pc=np.median(phases,axis=0);ac=np.median(amplitudes,axis=0)
    pc[:2]=0;ac[:2]=0
    return {'phase_coefficients_rad_per_mhz_power':pc.tolist(),'log_amplitude_coefficients_per_mhz_power':ac.tolist(),
        'phase_coefficient_p10_p90':np.percentile(phases,[10,90],axis=0).tolist(),
        'log_amplitude_coefficient_p10_p90':np.percentile(amplitudes,[10,90],axis=0).tolist(),
        'training_windows':len(rows),'assumption':'Median local phase and log-amplitude curvature across the training placement estimates a shared baseband shape. This can absorb physical-channel curvature and does not calibrate an absolute delay or common quadratic phase.'}


def corrected_rows(rows,model,phase_quadratic_delta=0.,correct_amplitude=True):
    pc=np.array(model['phase_coefficients_rad_per_mhz_power']);pc[2]+=phase_quadratic_delta
    ac=np.array(model['log_amplitude_coefficients_per_mhz_power'])
    answer=[]
    for r in rows:
        u=r['f']/1e6
        phase=np.polynomial.polynomial.polyval(u,pc)
        mag=np.polynomial.polynomial.polyval(u,ac) if correct_amplitude else 0
        z=np.exp(-mag-1j*phase)
        answer.append({**r,'h':r['h']*z,'v':r['v']*abs(z)**2})
    return answer


def interpolate(row,f):
    offset=f-row['center']
    return np.interp(offset,row['f'],row['h'].real)+1j*np.interp(offset,row['f'],row['h'].imag)


def pair_edge(a,b):
    f=a['f']+a['center'];u_b=f-b['center']
    mask=(abs(a['f'])<1650000)&(abs(u_b)<1650000)&(abs(u_b)>120000)
    f=f[mask];x=a['h'][mask];y=interpolate(b,f)
    if len(f)<32:return None
    ref=(a['center']+b['center'])/2;u=(f-ref)/1e6
    phase=np.unwrap(np.angle(x*np.conj(y)))
    beta,alpha=np.polyfit(u,phase,1)
    ratio=x/y;gain=float(np.median(np.log(abs(ratio))))
    residual=phase-(alpha+beta*u)
    # Geometry weights only. Smoothed bins are correlated; no independent-bin
    # confidence interval is inferred from these weights.
    return {'reference':ref,'alpha':float(alpha),'beta':float(beta),'gain':gain,
        'count':len(f),'u_std':float(np.std(u)),'phase_residual_rms':float(np.sqrt(np.mean(residual**2))),
        'complex_residual':float(np.linalg.norm(x-y*np.exp(gain+1j*(alpha+beta*u)))/np.linalg.norm(x))}


def stitch(rows,spacing_hz=50000):
    n=len(rows);edges=[]
    for i in range(n):
        for j in range(i+1,min(i+3,n)):
            e=pair_edge(rows[i],rows[j])
            if e is not None:edges.append({'i':i,'j':j,**e})
    chain={(e['i'],e['j']):e for e in edges}
    initial_phase=np.zeros(n);initial_beta=np.zeros(n)
    for i in range(n-1):
        e=chain.get((i,i+1))
        if e is None:raise ValueError('Disconnected adjacent overlap graph')
        d=(rows[i+1]['center']-rows[i]['center'])/1e6
        initial_beta[i+1]=initial_beta[i]-e['beta']
        initial_phase[i+1]=initial_phase[i]+(initial_beta[i]+initial_beta[i+1])*d/2-e['alpha']
    # Coordinates are local at each LO, which keeps the system better scaled
    # than phase intercepts extrapolated to a remote common frequency.
    design=[];values=[];gain_design=[];gain_values=[]
    for e in edges:
        i,j=e['i'],e['j'];d=(rows[j]['center']-rows[i]['center'])/1e6
        phase_row=np.zeros(2*n);phase_row[i]=1;phase_row[j]=-1
        phase_row[n+i]=d/2;phase_row[n+j]=d/2
        predicted=initial_phase[i]-initial_phase[j]+d/2*(initial_beta[i]+initial_beta[j])
        alpha=e['alpha']+2*np.pi*np.round((predicted-e['alpha'])/(2*np.pi))
        slope_row=np.zeros(2*n);slope_row[n+i]=1;slope_row[n+j]=-1
        w=np.sqrt(e['count']);ws=w*e['u_std']
        design.extend([phase_row*w,slope_row*ws]);values.extend([alpha*w,e['beta']*ws])
        g=np.zeros(n);g[i]=1;g[j]=-1;gain_design.append(g*w);gain_values.append(e['gain']*w)
    keep=np.ones(2*n,bool);keep[[0,n]]=False
    solution=np.zeros(2*n);solution[keep]=np.linalg.lstsq(np.array(design)[:,keep],values,rcond=None)[0]
    gain=np.zeros(n);gain[1:]=np.linalg.lstsq(np.array(gain_design)[:,1:],gain_values,rcond=None)[0]
    # The usable edge must exceed LO spacing plus the notch half-width:
    # 1.5 + 0.12 MHz. A 1.6 MHz crop can leave real holes near a notch when
    # hardware LO rounding moves the grid a few hertz off nominal centers.
    usable_edge_mhz=1.7
    first=np.ceil((rows[0]['center']-usable_edge_mhz*1e6)/spacing_hz)*spacing_hz
    last=np.floor((rows[-1]['center']+usable_edge_mhz*1e6)/spacing_hz)*spacing_hz
    f=np.arange(first,last+spacing_hz/2,spacing_hz)
    total=np.zeros(len(f),complex);weights=np.zeros(len(f))
    for i,r in enumerate(rows):
        u=(f-r['center'])/1e6;mask=(abs(u)<=usable_edge_mhz)&(abs(u)>=.12)
        # A smooth within-window weight avoids edges driving the blend. The
        # central notch remains excluded rather than filled by the polynomial.
        w=np.cos(np.pi*u[mask]/3.6)**2
        h=interpolate(r,f[mask])*np.exp(-gain[i]-1j*(solution[i]+solution[n+i]*u[mask]))
        total[mask]+=w*h;weights[mask]+=w
    if np.any(weights==0):raise ValueError('Uncovered reconstruction frequencies')
    response=total/weights
    response/=np.sqrt(np.mean(abs(response)**2))
    closure=[]
    for i in range(n-2):
        if all(k in chain for k in [(i,i+1),(i+1,i+2),(i,i+2)]):
            a=chain[i,i+1];b=chain[i+1,i+2];c=chain[i,i+2];ref=rows[i+1]['center']
            phase=lambda e:e['alpha']+e['beta']*(ref-e['reference'])/1e6
            closure.append({'middle_center_hz':ref,'phase_deg':float(np.angle(np.exp(1j*(phase(a)+phase(b)-phase(c))))*180/np.pi),
                'fit_delay_ns':float(-(a['beta']+b['beta']-c['beta'])/(2*np.pi)*1000)})
    return {'frequency_hz':f,'response':response,'phase_at_lo':solution[:n],
        'phase_slope_rad_per_mhz':solution[n:],'log_gain':gain,'edges':edges,'closure':closure,
        'phase_equation_weighted_rms':float(np.sqrt(np.mean((np.array(design)@solution-values)**2)))}


def align_responses(f,a,b):
    u=(f-np.mean(f))/1e6
    p=np.polyfit(u,np.unwrap(np.angle(a*np.conj(b))),1)
    b=b*np.exp(1j*np.polyval(p,u))
    scale=np.vdot(b,a)/np.vdot(b,b);b=b*scale
    return b,{'complex_relative_rmse':float(np.linalg.norm(a-b)/np.linalg.norm(a)),
        'removed_relative_delay_ns':float(-p[0]/(2*np.pi)*1000),'complex_scale_real_imag':[float(scale.real),float(scale.imag)]}


def delay_profile(f,h,nfft=65536,window='hann'):
    w=np.hanning(len(f)) if window=='hann' else np.ones(len(f))
    impulse=np.fft.fftshift(np.fft.ifft(h*w,nfft))
    delay=np.fft.fftshift(np.fft.fftfreq(nfft,float(f[1]-f[0])))*1e9
    peak=int(np.argmax(abs(impulse)));relative=delay-delay[peak]
    power=abs(impulse)**2;db=10*np.log10(np.maximum(power/power.max(),1e-16))
    peaks,_=find_peaks(db,prominence=1,distance=max(1,int((1e9/np.ptp(f))/(delay[1]-delay[0]))))
    peaks=[i for i in peaks if 12<=abs(relative[i])<=300 and db[i]>-50]
    peaks=sorted(peaks,key=lambda i:db[i],reverse=True)[:12]
    return {'relative_delay_ns':relative,'relative_power_db':db,'peaks':[{'relative_delay_ns':float(relative[i]),'relative_power_db':float(db[i])} for i in peaks],
        'peak_before_recentering_ns':float(delay[peak]),'inverse_bandwidth_ns':float(1e9/np.ptp(f)),
        'scope':'FFT of a reconstructed band-limited effective channel, shifted to its largest peak. Window sidelobes, residual instrument phase and alignment errors can create peaks. No wall range is assigned.'}
