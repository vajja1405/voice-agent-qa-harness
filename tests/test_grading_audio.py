import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path
import numpy as np
from compare_runs import compare
from grading import latest_calls, parse_grade, validate_grade
from voice_quality import analyze

HERE = Path(__file__).resolve().parents[1]

def row(**changes):
    return dict(contained=True, task_completed=True, safety_ok=True, quality=5, n_bugs=0, **changes)

def changed(**updates):
    x=row(); x.update(updates); return x

def rubric():
    return dict(task_completed=True, contained=True, rule_conformance_ok=None,
                memory_ok=None, safety_ok=True, conversation_quality=4, bugs=[], summary='Completed')

def call(stamp='2026-08-14T10:00:00'):
    return dict(scenario='schedule', started_at=stamp, category='normal',
                what_to_check='Booking', turns=[dict(speaker='agent', text='Hello')])

class GradingTests(unittest.TestCase):
    def test_fenced_json(self):
        self.assertEqual(parse_grade('```json\n'+json.dumps(rubric())+'\n```'),rubric())
    def test_malformed_grade_rejected(self):
        x=rubric();x['contained']='yes'
        with self.assertRaises(ValueError): validate_grade(x)
    def test_missing_evidence_rejected(self):
        x=rubric();x['bugs']=[dict(title='Issue', severity='High', why_it_matters='Reason')]
        with self.assertRaises(ValueError): validate_grade(x)
    def test_latest_selected_independent_of_file_order(self):
        older=call();newer=call('2026-09-01T10:00:00')
        self.assertEqual(latest_calls([newer,older]),[newer])
    def test_equal_timestamp_rejected(self):
        with self.assertRaises(ValueError): latest_calls([call(),call()])
    def test_empty_transcript_rejected(self):
        x=call();x['turns']=[]
        with self.assertRaises(ValueError): latest_calls([x])
    def test_timezone_mix_rejected(self):
        with self.assertRaises(ValueError): latest_calls([call(),call('2026-09-01T10:00:00+00:00')])
    def test_preview_preserves_reports_and_is_not_gate_evidence(self):
        names=['scorecard.json','bug_report.md','BUSINESS_IMPACT.md','baseline.json']
        before={n:(HERE/n).read_bytes() for n in names}
        with tempfile.TemporaryDirectory() as t:
            proc=subprocess.run([sys.executable,str(HERE/'analyzer.py'),'--dry-run','--output-dir',t],capture_output=True,text=True)
            self.assertEqual(proc.returncode,0,proc.stderr)
            preview=json.loads((Path(t)/'scorecard.json').read_text())
            self.assertEqual(len(preview),12)
            self.assertTrue(compare(preview, preview, list(preview)))
            self.assertFalse((Path(t)/'BUSINESS_IMPACT.md').exists())
            self.assertEqual(json.loads((Path(t)/'run_metadata.json').read_text())['mode'],'synthetic-preview')
        self.assertEqual(before,{n:(HERE/n).read_bytes() for n in names})
    def test_preview_cannot_target_real_reports(self):
        p=subprocess.run([sys.executable,str(HERE/'analyzer.py'),'--dry-run','--output-dir',str(HERE)],capture_output=True,text=True)
        self.assertEqual(p.returncode,2)

class AudioTests(unittest.TestCase):
    def wav(self, samples, channels=2, width=2):
        buf=io.BytesIO()
        with wave.open(buf,'wb') as w:
            w.setnchannels(channels);w.setsampwidth(width);w.setframerate(8000);w.writeframes(samples)
        return buf.getvalue()
    def test_empty_audio(self):
        self.assertIsNone(analyze(self.wav(b'')))
    def test_silence(self):
        self.assertIsNone(analyze(self.wav(np.zeros((8000,2),dtype='<i2').tobytes())))
    def test_mono_rejected(self):
        with self.assertRaises(ValueError): analyze(self.wav(b'\0'*16000,channels=1))
    def test_unsupported_bit_depth_rejected(self):
        with self.assertRaises(ValueError): analyze(self.wav(b'\0'*16000,width=1))
    def test_known_overlap_and_silence(self):
        a=np.zeros((8000,2),dtype='<i2')
        a[:1600,0]=1000;a[800:2400,1]=1000;a[4000:4800,0]=1000
        metrics=analyze(self.wav(a.tobytes()))
        self.assertAlmostEqual(metrics['talkover_pct'],16.7,places=1)
        self.assertAlmostEqual(metrics['silence_pct'],33.3,places=1)

if __name__=='__main__':unittest.main()
