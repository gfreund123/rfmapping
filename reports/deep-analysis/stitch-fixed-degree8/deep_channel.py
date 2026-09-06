"""Offline complex-channel de-embedding for the deep RF analysis.

No hardware access. Original captures are immutable. The image basis is fixed by
the transmitted waveform, not fitted from measured response residuals.
"""
import hashlib
import json
from pathlib import Path
import numpy as np
from characterize_rx import ROOT


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_run(path):
    r=json.loads(path.read_text())
    if r['status']!='completed':raise ValueError('Completed acquisition required')
    wave=r['waveforms']['overlap-3p6MHz'];p=ROOT/wave['raw_relative_path']
    if digest(p)!=wave['sha256']:raise ValueError('Waveform hash mismatch')
    tx=np.fromfile(p,dtype='<i2').reshape(-1,2)
    xf=np.fft.fft(tx[:,0].astype(float)+1j*tx[:,1])
    return r,xf


def load_channel(rec):
    p=ROOT/rec['channel_file']['raw_relative_path']
    if digest(p)!=rec['channel_file']['sha256']:raise ValueError('Channel hash mismatch')
    with np.load(p) as z:a={k:z[k] for k in z.files}
    a['variance_mean']=a['h_variance']/rec['channel']['period_count']
    return a


def image_code(offsets,xf,fs=5000000):
    k=np.rint(offsets*len(xf)/fs).astype(int)%len(xf)
    return np.conj(xf[(-k)%len(xf)])/xf[k]


def smooth_image_fit(f,h,variance,code,degree=8,include_image=True,train=None):
    """Complex polynomial approximation over one 3.6 MHz window.

    Decomposes desired response and the known mirror-code term. Per-bin variance
    weights are bounded to avoid domination by a few estimated variances.
    Polynomial degree is a sensitivity choice, not a physical path count.
    """
    basis=np.polynomial.legendre.legvander(f/1800000,degree)
    design=np.column_stack((basis,code[:,None]*basis)) if include_image else basis
    variance=np.maximum(variance,np.median(variance)*.05)
    w=1/np.sqrt(variance)
    train=np.ones(len(f),bool) if train is None else train
    coef=np.linalg.lstsq(design[train]*w[train,None],h[train]*w[train],rcond=None)[0]
    direct=basis@coef[:degree+1]
    mirror=basis@coef[degree+1:] if include_image else np.zeros(len(f),complex)
    residual=h-direct-code*mirror
    return {'direct':direct,'image':mirror,'residual':residual,
            'coefficients':coef,'variance':variance}


def image_diagnostic(a,xf,degree=8):
    f=a['frequency_offset_hz'];h=a['h_integer_aligned'];v=a['variance_mean']
    code=image_code(f,xf);train=np.arange(len(f))%5!=0
    baseline=smooth_image_fit(f,h,v,code,degree,False,train)
    image=smooth_image_fit(f,h,v,code,degree,True,train)
    test=~train
    before=float(np.mean(abs(baseline['residual'][test])**2))
    after=float(np.mean(abs(image['residual'][test])**2))
    full=smooth_image_fit(f,h,v,code,degree,True)
    return {'degree':degree,'held_bin_error_reduction':1-after/before,
        'held_bin_residual_to_estimated_noise':after/float(np.mean(v[test])),
        'image_to_direct_power_db':float(10*np.log10(np.mean(abs(full['image'])**2)/np.mean(abs(full['direct'])**2))),
        'direct_power_db':float(10*np.log10(np.mean(abs(full['direct'])**2))),
        'baseline_held_mse':before,'image_held_mse':after}
