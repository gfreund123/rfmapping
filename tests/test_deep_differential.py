import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from deep_differential import scan_complex,blocked


class DifferentialTest(unittest.TestCase):
    def test_known_weak_complex_echo_and_affine_nuisance(self):
        rng=np.random.default_rng(9062035);f=np.linspace(5728000000,5872000000,289);u=(f-f.mean())/np.ptp(f)
        echo=np.log(1+.06*np.exp(-2j*np.pi*(f-f.mean())*40e-9+1j*.7))
        noise=lambda:.002*(rng.normal(size=len(f))+1j*rng.normal(size=len(f)))
        base=.1+(.3+.2j)*u+echo
        a=base+noise();b=base+noise()+.2-.4j+.3j*u
        delays=np.arange(7,100,.5);fit=scan_complex(f,a,2,delays)
        self.assertAlmostEqual(fit['delay_ns'],40,delta=.5)
        self.assertGreater(blocked(f,a,b,2,delays)['prediction_squared_error_reduction'],.9)

    def test_correct_smooth_null_baseline_has_no_repeatable_large_echo(self):
        rng=np.random.default_rng(9062036);f=np.linspace(5728000000,5872000000,289);u=(f-f.mean())/np.ptp(f)
        smooth=.1+(.3+.2j)*u+(.2-.1j)*u*u
        noise=lambda:.003*(rng.normal(size=len(f))+1j*rng.normal(size=len(f)))
        a=smooth+noise();b=smooth+noise()+.1+.2j*u;delays=np.arange(7,100,.5)
        fit=scan_complex(f,a,2,delays)
        self.assertLess(abs(fit['coefficient']),.002)
        self.assertLess(blocked(f,a,b,2,delays)['prediction_squared_error_reduction'],.1)


if __name__=='__main__':unittest.main()
