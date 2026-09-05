import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from overlap_closure import fit_pair,closure


class OverlapClosureTest(unittest.TestCase):
    def test_known_affine_nuisance_is_consistent(self):
        offsets=np.arange(-1800000,1800001,1000);offsets=offsets[abs(offsets)>=100000]
        centers=[5800000000,5801500000,5803000000];arrays=[]
        for lo,phase,slope,gain in zip(centers,[1,2,-1],[.4,-.2,.1],[1,2,.7]):
            f=(offsets+lo-5800000000)/1e6
            arrays.append({'frequency_offset_hz':offsets,'h_integer_aligned':gain*np.exp(1j*(phase+slope*f))})
        ab=fit_pair(arrays[0],arrays[1],centers[0],centers[1]);bc=fit_pair(arrays[1],arrays[2],centers[1],centers[2]);ac=fit_pair(arrays[0],arrays[2],centers[0],centers[2])
        c=closure(ab,bc,ac,centers[1])
        self.assertLess(abs(c['wrapped_phase_closure_deg']),1e-9)
        self.assertLess(abs(c['equivalent_fit_delay_closure_ns']),1e-9)
        self.assertLess(abs(c['gain_closure_db']),1e-9)

    def test_inconsistent_edge_is_detected(self):
        edge={'reference_hz':5800000000,'phase_slope_rad_per_mhz':0,'phase_at_reference_rad':0,'log_amplitude_ratio':0}
        corrupt=dict(edge,phase_slope_rad_per_mhz=.25,phase_at_reference_rad=.4)
        c=closure(edge,edge,corrupt,5800000000)
        self.assertGreater(abs(c['wrapped_phase_closure_deg']),20)
        self.assertGreater(abs(c['equivalent_fit_delay_closure_ns']),30)


if __name__=='__main__':unittest.main()
