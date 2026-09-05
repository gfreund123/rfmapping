import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from phase_shape_diagnostic import cubic_closure_coefficient
from overlap_closure import fit_pair,closure


class PhaseShapeTest(unittest.TestCase):
    def test_known_cubic_phase_is_removed_without_removing_echo(self):
        offsets=np.arange(-1800000,1800001,1000);offsets=offsets[abs(offsets)>=100000]
        centers=[5800000000,5801500000,5803000000];coefficient=.08;arrays=[];corrected=[]
        for lo,phase,slope in zip(centers,[1,-2,.7],[.3,-.1,.4]):
            f=offsets+lo
            physical=1+.1*np.exp(-2j*np.pi*(f-5800000000)*35e-9)
            nuisance=np.exp(1j*(phase+slope*(f-5800000000)/1e6))
            h=physical*nuisance*np.exp(1j*coefficient*(offsets/1e6)**3)
            arrays.append({'frequency_offset_hz':offsets,'h_integer_aligned':h})
            corrected.append({'frequency_offset_hz':offsets,'h_integer_aligned':h*np.exp(-1j*coefficient*(offsets/1e6)**3)})
            np.testing.assert_allclose(abs(corrected[-1]['h_integer_aligned']),abs(physical),atol=1e-12)
        def tri(a):
            return closure(fit_pair(a[0],a[1],centers[0],centers[1]),fit_pair(a[1],a[2],centers[1],centers[2]),fit_pair(a[0],a[2],centers[0],centers[2]),centers[1])
        before=tri(arrays);after=tri(corrected)
        self.assertAlmostEqual(before['wrapped_phase_closure_deg']/cubic_closure_coefficient(offsets),coefficient,places=10)
        self.assertLess(abs(after['wrapped_phase_closure_deg']),1e-9)
        self.assertLess(abs(after['equivalent_fit_delay_closure_ns']),1e-9)


if __name__=='__main__':unittest.main()
