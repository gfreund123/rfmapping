import sys
from pathlib import Path
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from check_prbs import analyze, reverse_bits


def fixture(n=12000):
    # Independent scalar implementation of the ADI FAQ's right-shifting LFSR.
    state=0x0a54
    words=[]
    for _ in range(n):
        words.append(state)
        state=(state>>1)|(((state&0x6fff).bit_count()&1)<<15)
    assert words[:4]==[0x0a54,0x852a,0xc295,0x614a]
    words=np.array(words,dtype=np.uint16)
    raw=np.column_stack((words>>4,reverse_bits(words,16)>>4)).astype(np.int16)
    return np.where(raw>=2048,raw-4096,raw).astype(np.int16)


class PRBSTest(unittest.TestCase):
    def test_valid_pattern(self):
        r=analyze(fixture(),1024)
        self.assertTrue(r['all_checked_transitions_valid'])

    def test_single_dropped_sample_detected_after_training_prefix(self):
        r=analyze(np.delete(fixture(),6144,axis=0),1024)
        self.assertEqual(r['transition_mismatches'],1)
        self.assertEqual(r['boundary_transition_mismatches'],1)
        self.assertFalse(r['all_checked_transitions_valid'])

    def test_bit_corruption_detected(self):
        iq=fixture(); iq[7000,0]^=16
        r=analyze(iq,1024)
        self.assertGreater(r['iq_overlap_mismatches'],0)
        self.assertFalse(r['all_checked_transitions_valid'])

    def test_random_input_rejected(self):
        iq=np.random.default_rng(7).integers(-2048,2048,(12000,2),dtype=np.int16)
        self.assertFalse(analyze(iq,1024)['pattern_recognized'])


if __name__=='__main__': unittest.main()
