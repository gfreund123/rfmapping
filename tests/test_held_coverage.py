import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from collect_position import held_summaries


class HeldCoverageTest(unittest.TestCase):
    def records(self,n=7,off=True):
        lo=5800000000
        r=[{'kind':'pilot','id':f'held_{lo}_repeat{i}','tx_lo_hz':lo,'tx_attenuation_db':45,
            'settings':{'rx_lo_hz':lo,'rf_bandwidth_hz':4000000,'gain_db':40,'stream_sample_rate_hz':4999999},
            'channel':{'digital_transfer_power_db':-65+i*.01}} for i in range(n)]
        if off:r.append({'kind':'rx-only','id':f'held_{lo}_final_off','off_channel':{}})
        return r

    def test_finished_train_can_be_reconstructed_from_partial_run(self):
        self.assertTrue(held_summaries(self.records(),[5800000000])[0]['complete_train'])

    def test_missing_repeat_or_negative_control_is_incomplete(self):
        for records in (self.records(n=6),self.records(off=False)):
            self.assertFalse(held_summaries(records,[5800000000])[0]['complete_train'])

    def test_changed_settings_are_not_a_held_train(self):
        r=self.records();r[3]['settings']['gain_db']=41
        self.assertFalse(held_summaries(r,[5800000000])[0]['complete_train'])


if __name__=='__main__':unittest.main()
