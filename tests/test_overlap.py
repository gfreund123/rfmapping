import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from review_position import overlap_fit


class OverlapTest(unittest.TestCase):
    def test_known_channel_with_independent_capture_phase_delay_and_gain(self):
        f=np.r_[np.arange(-1800000,-100000,1000),np.arange(100000,1800001,1000)]
        lo1=5771500000;lo2=lo1+1500000
        def response(lo,gain,phase,delay):
            physical=.01+.003*np.exp(-2j*np.pi*(lo+f)*25e-9)
            return {'frequency_offset_hz':f,'h_integer_aligned':physical*gain*np.exp(1j*phase-2j*np.pi*f*delay)}
        result=overlap_fit(response(lo1,2,.4,37e-9),response(lo2,1,-1.2,-61e-9),lo1,lo2)
        self.assertLess(result['fractional_complex_residual_rms'],1e-10)
        self.assertAlmostEqual(result['gain_ratio_db'],20*np.log10(2),places=8)
