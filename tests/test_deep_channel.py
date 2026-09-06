import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from position_dsp import make_pilot
from deep_channel import image_code,smooth_image_fit,image_diagnostic
from deep_stitch import stitch,corrected_rows,align_responses,delay_profile,calibrate_overlap_baseband


class DeepChannelTest(unittest.TestCase):
    def test_known_mirror_component_predicts_withheld_bins(self):
        tx,_=make_pilot();xf=np.fft.fft(tx[:,0]+1j*tx[:,1]);f=np.fft.fftfreq(len(tx),1/5000000)
        f=np.sort(f[(abs(f)>=100000)&(abs(f)<=1800000)])
        rng=np.random.default_rng(9062031);truth=(1+.12*np.exp(-2j*np.pi*f*65e-9))*np.exp(-2j*np.pi*f*80e-9)
        code=image_code(f,xf);noise=(rng.normal(size=len(f))+1j*rng.normal(size=len(f)))*.02
        h=truth+.07*np.exp(1j*.6)*code+noise;v=np.full(len(f),.0008)
        fit=smooth_image_fit(f,h,v,code)
        self.assertLess(np.linalg.norm(fit['direct']-truth)/np.linalg.norm(truth),.005)
        d=image_diagnostic({'frequency_offset_hz':f,'h_integer_aligned':h,'variance_mean':v},xf)
        self.assertGreater(d['held_bin_error_reduction'],.75)
        self.assertAlmostEqual(d['held_bin_residual_to_estimated_noise'],1,delta=.2)

    def test_mirror_fit_does_not_invent_large_image_in_null(self):
        tx,_=make_pilot();xf=np.fft.fft(tx[:,0]+1j*tx[:,1]);f=np.fft.fftfreq(len(tx),1/5000000)
        f=np.sort(f[(abs(f)>=100000)&(abs(f)<=1800000)])
        rng=np.random.default_rng(9062032);h=np.exp(-2j*np.pi*f*80e-9)+(rng.normal(size=len(f))+1j*rng.normal(size=len(f)))*.02
        d=image_diagnostic({'frequency_offset_hz':f,'h_integer_aligned':h,'variance_mean':np.full(len(f),.0008)},xf)
        self.assertLess(d['held_bin_error_reduction'],.03)
        self.assertLess(d['image_to_direct_power_db'],-45)

    def test_noiseless_overlap_recovers_known_echoes_with_known_filter(self):
        rng=np.random.default_rng(9062033);f=np.r_[np.arange(-1800000,-99999,2500),np.arange(100000,1800001,2500)]
        model={'phase_coefficients_rad_per_mhz_power':[0,0,.007,-.044,0,.001],
               'log_amplitude_coefficients_per_mhz_power':[0,0,-.1,0,-.01]}
        def physical(rf):return 1+.2*np.exp(-2j*np.pi*(rf-5800000000)*35e-9)+.1*np.exp(-2j*np.pi*(rf-5800000000)*85e-9)
        rows=[]
        for lo in np.arange(5728000000,5872000001,1500000):
            u=f/1e6;bb=np.exp(np.polynomial.polynomial.polyval(u,model['log_amplitude_coefficients_per_mhz_power'])+1j*np.polynomial.polynomial.polyval(u,model['phase_coefficients_rad_per_mhz_power']))
            h=physical(lo+f)*bb*np.exp(rng.normal(0,.15)+1j*(rng.uniform(-np.pi,np.pi)+rng.uniform(-.6,.6)*u))
            rows.append({'center':lo,'f':f,'h':h,'v':np.ones(len(f))})
        s=stitch(corrected_rows(rows,model));truth=physical(s['frequency_hz']);fit,stats=align_responses(s['frequency_hz'],truth,s['response'])
        self.assertLess(stats['complex_relative_rmse'],.001)
        profile=delay_profile(s['frequency_hz'],fit)
        for delay in (35,85):self.assertLess(min(abs(p['relative_delay_ns']-delay) for p in profile['peaks']),1.)

    def test_small_lo_rounding_does_not_create_grid_edge_holes(self):
        f=np.r_[np.arange(-1800000,-99999,2500),np.arange(100000,1800001,2500)]
        rows=[{'center':lo,'f':f,'h':np.ones(len(f),complex),'v':np.ones(len(f))} for lo in [5727999998,5729499997,5730999999]]
        s=stitch(rows)
        np.testing.assert_allclose(abs(s['response']),1,atol=1e-10)

    def test_overlap_calibration_with_common_fractional_timing(self):
        rng=np.random.default_rng(9062034);f=np.r_[np.arange(-1800000,-99999,2500),np.arange(100000,1800001,2500)]
        pc=np.array([0,.47,.007,-.036,.0002,-.0026]);ac=np.array([0,-.03,-.04,.001,.016,-.0004,-.011])
        def physical(rf):return 1+.17*np.exp(-2j*np.pi*(rf-5800000000)*45e-9)
        rows=[]
        for lo in np.arange(5728000000,5872000001,1500000):
            u=f/1e6;bb=np.exp(np.polynomial.polynomial.polyval(u,ac)+1j*np.polynomial.polynomial.polyval(u,pc))
            h=physical(lo+f)*bb*np.exp(rng.normal(0,.15)+1j*rng.uniform(-np.pi,np.pi))
            rows.append({'center':lo,'f':f,'h':h,'v':np.ones(len(f))*.001})
        model=calibrate_overlap_baseband(rows)
        np.testing.assert_allclose(model['phase_coefficients_rad_per_mhz_power'][2:],pc[2:],atol=1e-10)
        np.testing.assert_allclose(model['log_amplitude_coefficients_per_mhz_power'][2:],ac[2:],atol=1e-10)
        s=stitch(corrected_rows(rows,model),timing='fixed')
        # Linear amplitude of the common baseband filter is a gain gauge;
        # remove the known test value when checking the recovered scene.
        u=(s['frequency_hz']-5800000000)/1e6;response=s['response']*np.exp(-ac[1]*u)
        aligned,stats=align_responses(s['frequency_hz'],physical(s['frequency_hz']),response)
        self.assertLess(stats['complex_relative_rmse'],.001)
        profile=delay_profile(s['frequency_hz'],aligned)
        self.assertLess(min(abs(p['relative_delay_ns']-45) for p in profile['peaks']),1.)

    def test_quadratic_gauge_is_exact_when_window_timing_is_free(self):
        f=np.linspace(-1.8,1.8,200);center=31.;delta=.001
        b=np.exp(-.04*f*f-1j*.04*f**3);c=1+.1*np.exp(-2j*np.pi*(center+f)*.035)
        original=np.exp(1j*(.4+.47*f))*b*c
        changed_b=b*np.exp(1j*delta*f*f)
        changed_c=c*np.exp(-1j*delta*(center+f)**2)
        changed_nuisance=np.exp(1j*(.4+delta*center**2+(.47+2*delta*center)*f))
        np.testing.assert_allclose(original,changed_nuisance*changed_b*changed_c,atol=1e-14)


if __name__=='__main__':unittest.main()
