"""验证时间、证据保存及复用，不把识别文本当作准确率测试。"""
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/interview-recording-review/scripts/recording.py'
SPEC = importlib.util.spec_from_file_location('recording_under_test', SCRIPT)
recording = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recording)


@dataclass
class Segment:
    start: float
    end: float
    text: str
    avg_logprob: float = -0.2
    no_speech_prob: float = 0.1
    compression_ratio: float = 1.2


class Tests(unittest.TestCase):
    def test_original_timeline_and_clamp(self):
        row = recording.normalize_segment(Segment(-0.1, 3, '合成文本'), 910, 2)
        self.assertEqual((row['start'], row['end']), (910, 912))
        self.assertIn('timestamp_clamped', row['quality_flags'])
        self.assertEqual(recording.timestamp(row['start'], True), '00:15:10,000')
        self.assertIsNone(recording.normalize_segment(Segment(3, 4, '幻觉'), 910, 2))

    def test_finite_selection_and_prepare_offset(self):
        self.assertEqual(recording.selection(280, 900, 400, 500), (400, 500))
        for start, end in [(0, 500), (500, 500), (300, 901), (float('nan'), 500)]:
            with self.assertRaises(ValueError):
                recording.selection(280, 900, start, end)

    def test_low_confidence_is_flagged_not_silently_deleted(self):
        row = recording.normalize_segment(Segment(0, 1, '待核对', -1.2, 0.7, 3), 0, 2)
        self.assertEqual(row['text'], '待核对')
        self.assertEqual(set(row['quality_flags']),
                         {'possible_repetition', 'possible_non_speech', 'low_model_confidence'})

    def setup_work(self, path):
        audio = path / 'audio.flac'
        audio.write_bytes(b'synthetic-fixture-not-real-audio')
        recording.save_json(path / 'metadata.json', {
            'audio': 'audio.flac', 'audio_sha256': recording.fingerprint(audio),
            'selection_start': 280, 'selection_end': 282,
        })
        return recording.parser().parse_args(['transcribe', '--work-dir', str(path)])

    def fake_runtime(self, failing=False):
        module = types.ModuleType('faster_whisper')

        class FakeModel:
            def __init__(self, *args, **kwargs):
                pass

            def transcribe(self, *args, **kwargs):
                def stream():
                    yield Segment(0, 1, '合成一句')
                    if failing:
                        raise RuntimeError('模拟生成中途失败')
                    yield Segment(1, 2, '合成二句')
                return stream(), {'duration': 2}

        module.WhisperModel = FakeModel
        module.BatchedInferencePipeline = object
        return module

    def test_midstream_failure_preserves_partial_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            args = self.setup_work(path)
            with patch.dict(sys.modules, {'faster_whisper': self.fake_runtime(failing=True)}):
                with self.assertRaisesRegex(RuntimeError, '中途失败'):
                    recording.transcribe(args)
            output = path / 'runs/primary'
            state = json.loads((output / 'run.json').read_text(encoding='utf-8'))
            self.assertEqual(state['status'], 'failed')
            self.assertEqual(state['segments_written'], 1)
            self.assertIn('00:04:40', (output / 'transcript.txt').read_text(encoding='utf-8'))
            with self.assertRaises(FileExistsError):
                recording.transcribe(args)

    def test_completed_results_are_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            args = self.setup_work(path)
            with patch.dict(sys.modules, {'faster_whisper': self.fake_runtime()}):
                recording.transcribe(args)
            output = path / 'runs/primary'
            before = (output / 'segments.jsonl').stat().st_mtime_ns
            recording.transcribe(args)
            self.assertEqual((output / 'segments.jsonl').stat().st_mtime_ns, before)
            state = json.loads((output / 'run.json').read_text(encoding='utf-8'))
            self.assertEqual(state['status'], 'complete')
            self.assertEqual(state['processed_original_range'], [280, 282])

    def test_changed_audio_does_not_reuse_old_result(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            args = self.setup_work(path)
            with patch.dict(sys.modules, {'faster_whisper': self.fake_runtime()}):
                recording.transcribe(args)
            (path / 'audio.flac').write_bytes(b'changed-audio')
            with self.assertRaisesRegex(ValueError, '已变动'):
                recording.transcribe(args)


if __name__ == '__main__':
    unittest.main()
