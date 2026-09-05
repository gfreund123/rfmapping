"""Numerical checks independent of live hardware."""
import importlib.util
from pathlib import Path
import unittest
import numpy as np

spec = importlib.util.spec_from_file_location("probe", Path(__file__).resolve().parents[1] / "scripts/characterize_rx.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class MetricsTest(unittest.TestCase):
    def test_signed_12bit_rails(self):
        iq = np.array([[-2048, 2047], [0, 0], [100, -100]], dtype=np.int16)
        result = probe.iq_metrics(iq)
        self.assertEqual(result["rail_component_count"], 2)
        self.assertEqual(result["outside_12bit_count"], 0)
        self.assertEqual(result["zero_pair_fraction"], 1/3)

    def test_complex_tone_power_and_psd_units(self):
        fs = 4096000
        t = np.arange(16384)
        z = 1024*np.exp(2j*np.pi*123*t/4096)
        iq = np.column_stack((z.real, z.imag))
        result = probe.iq_metrics(iq)
        self.assertAlmostEqual(result["rms_dbfs"], -6.020599913, places=7)
        freq, psd = probe.spectrum(iq, fs)
        self.assertAlmostEqual(float(psd.sum() * fs/4096), 0.25, places=7)
        self.assertEqual(freq[np.argmax(psd)], 123000)


if __name__ == "__main__":
    unittest.main()
