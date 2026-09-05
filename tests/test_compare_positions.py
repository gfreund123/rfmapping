import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from compare_positions import compare_records


def records(shifts=(0,0,0),noise_shift=0,centers=(5740000000,5750000000,5760000000)):
    out=[]
    for i,(lo,shift) in enumerate(zip(centers,shifts)):
        for direction,repeat in [('forward',-.1),('reverse',.1)]:
            out.append({'id':f'{direction}_{lo}','kind':'pilot','channel':{
                'digital_transfer_power_db':-60-i+shift+repeat,
                'estimator_noise_to_signal_ratio':10**(-(15-i+noise_shift+repeat)/10)}})
    return out


class ComparePositionsTest(unittest.TestCase):
    def test_broad_shift_is_not_frequency_structure(self):
        r=compare_records(records(),list(reversed(records((2,2,2)))))
        self.assertAlmostEqual(r['summary']['power_db']['median_second_minus_first_db'],2)
        self.assertAlmostEqual(r['summary']['power_db']['rms_after_removing_median_db'],0)
        self.assertAlmostEqual(r['summary']['signal_to_averaging_noise_db']['median_second_minus_first_db'],0)
        np.testing.assert_allclose(r['centers'][0]['power_db']['observed_difference_envelope'],[1.8,2.2])

    def test_known_frequency_structure_is_retained(self):
        r=compare_records(records(),records((1,2,3),noise_shift=-1))
        np.testing.assert_allclose([x['power_db']['median_removed_difference'] for x in r['centers']],[-1,0,1])
        self.assertAlmostEqual(r['summary']['signal_to_averaging_noise_db']['median_second_minus_first_db'],-1)

    def test_unpaired_centers_are_not_silently_filled(self):
        with self.assertRaises(ValueError):compare_records(records(),records()[:-1])


if __name__=='__main__':unittest.main()
