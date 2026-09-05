import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from check_duplex import pilot,analyze_pilot,PERIOD,FS
from survey_spectrum import spectral_summary


class PilotTest(unittest.TestCase):
    def test_peak_level_and_occupied_span(self):
        iq=pilot(); self.assertLessEqual(abs(iq.astype(int)).max(),8192)
        z=iq[:,0].astype(float)+1j*iq[:,1]
        power=abs(np.fft.fft(z))**2; f=np.fft.fftfreq(PERIOD,1/FS)
        self.assertLess(power[abs(f)>1000000].sum()/power.sum(),1e-6)

    def test_delay_and_frequency_offset(self):
        x=pilot(); base=np.tile(np.roll(x,123,axis=0),(32,1))
        t=np.arange(len(base))/FS
        z=(base[:,0]+1j*base[:,1])*np.exp(1j*(0.7+2*np.pi*10*t))
        iq=np.column_stack((z.real,z.imag))
        a=analyze_pilot(iq,x)
        self.assertEqual(a['unique_alignment_indices'],[123])
        self.assertGreater(a['median_normalized_correlation'],0.999)
        self.assertAlmostEqual(a['phase_slope_hz'],10,places=5)

    def test_noise_is_not_a_pilot(self):
        iq=np.random.default_rng(99).normal(0,10,(PERIOD*16,2))
        self.assertLess(analyze_pilot(iq,pilot())['median_normalized_correlation'],0.15)

    def test_survey_frequency_sign(self):
        t=np.arange(262144)/FS
        z=100*np.exp(2j*np.pi*1025390.625*t)
        b=np.array(spectral_summary(np.column_stack((z.real,z.imag)),FS))
        self.assertEqual(b[np.argmax(b[:,1]),0],1025000)


if __name__=='__main__': unittest.main()
