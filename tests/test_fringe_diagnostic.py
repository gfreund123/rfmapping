import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from fringe_diagnostic import diagnose,scan
from validate_fringe_method import cases


class FringeTest(unittest.TestCase):
    def setUp(self):
        self.f=np.linspace(5728e6,5872e6,97);self.x=np.linspace(-1,1,97)
        self.grid=np.arange(7.,100.01,.5);self.rng=np.random.default_rng(9062030)

    def pair(self,signal):
        return signal+self.rng.normal(0,.035,97),signal+.1+self.rng.normal(0,.035,97)

    def test_known_weak_ripple_survives_baselines_and_prediction(self):
        case=cases()[0]
        result=diagnose(case['frequencies_hz'],case['measurements'],self.grid)
        self.assertTrue(result['stable_descriptive_fringe_candidate'],result['screen_failures'])
        self.assertTrue(all(abs(v['delay_ns']-35)<1 for v in result['variants']))
        self.assertFalse(result['physical_echo_validated'])

    def test_smooth_noecho_counterexample_can_pass_descriptive_screen(self):
        bend=1.6*np.tanh(2.2*self.x)
        data={'power_db':self.pair(-65-7*self.x+bend),
              'signal_to_averaging_noise_db':self.pair(20-7*self.x+bend)}
        result=diagnose(self.f,data,self.grid)
        # This is a documented failure of specificity, not a validated detector.
        # A repeatable sinusoidal approximation to a smooth bend is not an echo.
        self.assertTrue(result['stable_descriptive_fringe_candidate'])
        self.assertFalse(result['physical_echo_validated'])

    def test_nonrepeating_ripple_does_not_pass_stability_screen(self):
        first=.65*np.cos(2*np.pi*(self.f-self.f.mean())*35e-9)
        second=.65*np.cos(2*np.pi*(self.f-self.f.mean())*60e-9)
        data={metric:(level-7*self.x+first,level-7*self.x+second)
              for metric,level in [('power_db',-65),('signal_to_averaging_noise_db',20)]}
        self.assertFalse(diagnose(self.f,data,self.grid)['stable_descriptive_fringe_candidate'])

    def test_distinct_sparse_delay_sets_can_have_identical_power(self):
        a=np.array([0,1,4,10,12,17])*5e-9
        b=np.array([0,1,8,11,13,17])*5e-9
        f=np.linspace(0,200e6,1001)
        ha=np.exp(-2j*np.pi*f[:,None]*a).sum(axis=1)
        hb=np.exp(-2j*np.pi*f[:,None]*b).sum(axis=1)
        np.testing.assert_allclose(abs(ha)**2,abs(hb)**2,rtol=1e-11,atol=1e-11)
        self.assertFalse(np.allclose(a/5e-9,b/5e-9))
        self.assertFalse(np.allclose((a.max()-a[::-1])/5e-9,b/5e-9))


if __name__=='__main__':unittest.main()
