import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from position_capture import Session


class MetadataRetryTest(unittest.TestCase):
    def session(self,root):
        s=object.__new__(Session)
        s.public=Path(root);s.result={'status':'recording'}
        s.bytes=40;s.bursts=1;s.unmute=.4
        return s

    def test_transient_windows_lock_preserves_and_replaces_snapshot(self):
        with tempfile.TemporaryDirectory() as root:
            s=self.session(root);dest=s.public/'results.json'
            dest.write_text('{"previous":true}')
            replace=Path.replace;calls=[]
            def locked_then_replace(source,target):
                calls.append(1)
                if len(calls)<3:
                    self.assertEqual(json.loads(dest.read_text()),{'previous':True})
                    raise PermissionError('simulated sharing violation')
                return replace(source,target)
            with patch.object(Path,'replace',locked_then_replace),patch('position_capture.time.sleep'):
                s.save()
            self.assertEqual(len(calls),3)
            self.assertEqual(json.loads(dest.read_text())['rf_bursts'],1)
            self.assertFalse((s.public/'results.pending').exists())

    def test_persistent_lock_stops_and_retains_both_complete_snapshots(self):
        with tempfile.TemporaryDirectory() as root:
            s=self.session(root);dest=s.public/'results.json'
            dest.write_text('{"previous":true}')
            with patch.object(Path,'replace',side_effect=PermissionError('locked')) as rename,patch('position_capture.time.sleep'):
                with self.assertRaises(PermissionError):s.save()
            self.assertEqual(rename.call_count,21)
            self.assertEqual(json.loads(dest.read_text()),{'previous':True})
            self.assertEqual(json.loads((s.public/'results.pending').read_text())['rf_bursts'],1)


if __name__=='__main__':unittest.main()
