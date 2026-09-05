import sys
from pathlib import Path
import unittest
from unittest.mock import Mock
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from position_capture import Session,CENTERS
from position_dsp import make_pilot


class PositionGuardTest(unittest.TestCase):
    def test_offset_guards_cover_pilot_and_each_others_dc(self):
        f=np.arange(-1900000,1900001,1000)
        covered=np.zeros(len(f),bool)
        for center in (-600000,600000):
            covered|=(abs(f-center)<=1450000)&(abs(f-center)>=100000)
        self.assertTrue(covered.all())
        self.assertGreaterEqual(min(CENTERS)-1800000,5725000000)
        self.assertLessEqual(max(CENTERS)+1800000,5875000000)

    def test_no_rf_if_second_guard_detects_activity(self):
        s=object.__new__(Session)
        s.result={'jobs':[],'hot_intervals_hz':[]}
        s.waveforms={'overlap-3p6MHz':make_pilot()}
        s.tune=Mock();s.save=Mock();s.transmit=Mock()
        def rec(name,quiet,lo):
            return {'id':name,'quiet_observed':quiet,'settings':{'rx_lo_hz':lo},
                    'activity':{'hot_offsets_hz':[] if quiet else [125000]},
                    'iq_metrics':{'rail_component_count':0}},None
        s.receive=Mock(side_effect=[rec('lower',True,5799400000),rec('upper',False,5800600000)])
        self.assertIsNone(s.probe('test',5800000000))
        s.transmit.assert_not_called()
        self.assertEqual(s.result['jobs'][0]['status'],'skipped-fresh-activity')
        self.assertTrue(s.result['hot_intervals_hz'])

    def test_known_occupied_interval_skips_without_rf(self):
        s=object.__new__(Session)
        s.result={'jobs':[],'hot_intervals_hz':[[5799900000,5800100000]]}
        s.waveforms={'overlap-3p6MHz':make_pilot()};s.save=Mock();s.transmit=Mock();s.receive=Mock()
        self.assertIsNone(s.probe('test',5800000000))
        s.transmit.assert_not_called();s.receive.assert_not_called()


if __name__=='__main__':unittest.main()
