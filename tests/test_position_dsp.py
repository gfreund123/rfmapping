import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from position_dsp import make_pilot,channel,activity,averaged_pilot_evidence,FS


class PositionDspTest(unittest.TestCase):
    def test_wide_pilot_does_not_increase_total_power(self):
        wide,spec=make_pilot();old,_=make_pilot(False)
        self.assertLessEqual(np.max(abs(wide.astype(float))),8192)
        self.assertLessEqual(np.mean(np.sum(wide.astype(float)**2,axis=1)),np.mean(np.sum(old.astype(float)**2,axis=1)))
        f=np.fft.fftfreq(len(wide),1/FS)
        x=wide[:,0].astype(float)+1j*wide[:,1]
        outside=(abs(f)<100000)|(abs(f)>1800000)
        self.assertLess(np.sum(abs(np.fft.fft(x)[outside])**2)/np.sum(abs(np.fft.fft(x))**2),1e-6)

    def test_multipath_amplitude_survives_capture_delay_and_cfo(self):
        tx,spec=make_pilot();x=tx[:,0].astype(float)+1j*tx[:,1]
        f=np.fft.fftfreq(len(x),1/FS)
        truth=.01+.004*np.exp(-2j*np.pi*f*8.25/FS+1j*.4)
        y=np.fft.ifft(np.fft.fft(x)*truth*np.exp(-2j*np.pi*f*217.35/FS))
        z=np.tile(y,64)*np.exp(1j*(.7+2*np.pi*.12*np.arange(len(y)*64)/FS))
        summary,a=channel(np.column_stack((z.real,z.imag)),tx,spec)
        expected=abs(.01+.004*np.exp(-2j*np.pi*a['frequency_offset_hz']*8.25/FS+1j*.4))
        np.testing.assert_allclose(abs(a['h_mean']),expected,rtol=2e-5,atol=1e-7)
        self.assertTrue(summary['pilot_detected'])

    def test_guard_detects_activity_at_wide_pilot_edge(self):
        rng=np.random.default_rng(25);n=262144
        z=rng.normal(0,1.5,n)+1j*rng.normal(0,1.5,n)
        self.assertTrue(activity(np.column_stack((z.real,z.imag)))['quiet_observed'])
        z+=30*np.exp(2j*np.pi*1780000*np.arange(n)/FS)
        self.assertFalse(activity(np.column_stack((z.real,z.imag)))['quiet_observed'])

    def test_averaged_weak_pilot_is_separated_from_pure_noise(self):
        tx,spec=make_pilot();x=tx[:,0].astype(float)+1j*tx[:,1]
        signal=np.tile(x,256)*.001
        sigma=np.sqrt(np.mean(abs(signal)**2)*(1/.12**2-1)/2)
        for seed in (11,12,13):
            rng=np.random.default_rng(seed)
            noise=rng.normal(0,sigma,len(signal))+1j*rng.normal(0,sigma,len(signal))
            off,_=channel(np.column_stack((noise.real,noise.imag)),tx,spec)
            z=signal+noise;on,_=channel(np.column_stack((z.real,z.imag)),tx,spec)
            self.assertFalse(averaged_pilot_evidence(off))
            self.assertLess(on['median_correlation'],.15)
            self.assertTrue(averaged_pilot_evidence(on,off['median_correlation']))


if __name__=='__main__':unittest.main()
