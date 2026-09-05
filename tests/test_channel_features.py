import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from check_duplex import pilot,PERIOD,FS
from channel_features import extract


def fixture(amplitude=.01,delay=0.,phase=0.,cfo=0.):
    tx=pilot(); x=tx[:,0].astype(float)+1j*tx[:,1]
    shifted=np.fft.ifft(np.fft.fft(x)*np.exp(-2j*np.pi*np.fft.fftfreq(PERIOD)*delay))
    z=np.tile(shifted,64)*amplitude
    z*=np.exp(1j*(phase+2*np.pi*cfo*np.arange(len(z))/FS))
    return np.column_stack((z.real,z.imag)),tx


class ChannelFeatureTest(unittest.TestCase):
    def test_fractional_delay_and_phase_do_not_change_power(self):
        a=extract(*fixture(delay=17.15,phase=.3,cfo=.1))
        b=extract(*fixture(delay=1234.72,phase=-2.2,cfo=-.15))
        self.assertAlmostEqual(a['digital_transfer_power_db'],-40,places=5)
        self.assertAlmostEqual(a['digital_transfer_power_db'],b['digital_transfer_power_db'],places=5)
        np.testing.assert_allclose(np.array(a['frequency_bins'])[:,1],np.array(b['frequency_bins'])[:,1],atol=1e-5)

    def test_amplitude_change_is_preserved(self):
        a=extract(*fixture(amplitude=.01)); b=extract(*fixture(amplitude=.02,delay=321.4,phase=1.9))
        self.assertAlmostEqual(b['digital_transfer_power_db']-a['digital_transfer_power_db'],20*np.log10(2),places=6)


if __name__=='__main__':unittest.main()
