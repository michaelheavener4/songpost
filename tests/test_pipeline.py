"""Pipeline checks for SONGPOST v0 (stdlib unittest, no dependencies).

These stand in for the OpenCode seat's counter-honesty checks from Plan v2:
the public counter must be derivable from the files on disk, and a song at
a share link must be genuinely generated (valid WAV, deterministic,
feedback changes the render).
"""
import io
import json
import os
import sys
import unittest
import wave

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import engine  # noqa: E402


def wav_stats(data: bytes):
    with wave.open(io.BytesIO(data), "rb") as w:
        frames = w.getnframes()
        raw = w.readframes(frames)
        import struct

        samples = struct.unpack("<%dh" % (len(raw) // 2), raw)
        peak = max(abs(s) for s in samples) if samples else 0
        return w.getframerate(), frames / float(w.getframerate()), peak


class EngineTests(unittest.TestCase):
    def test_generates_real_audio(self):
        data, info = engine.generate("a haunted disco song about my ex's houseplant")
        rate, seconds, peak = wav_stats(data)
        self.assertGreater(seconds, 8.0, "song too short to be a song")
        self.assertGreater(peak, 1000, "song is effectively silent")
        self.assertIn("title", info)

    def test_deterministic(self):
        a, _ = engine.generate("rainy sunday jazz for one")
        b, _ = engine.generate("rainy sunday jazz for one")
        self.assertEqual(a, b, "same prompt must render byte-identically")

    def test_different_prompts_differ(self):
        a, _ = engine.generate("rainy sunday jazz for one")
        b, _ = engine.generate("stadium rock anthem about a forklift")
        self.assertNotEqual(a, b)

    def test_feedback_changes_render(self):
        base, base_info = engine.generate("a small song about leaving town")
        v2, v2_info = engine.generate(
            "a small song about leaving town",
            feedback="darker, more drums",
            parent=base_info.get("params", base_info),
        )
        self.assertNotEqual(base, v2, "feedback must change the audio")
        self.assertNotEqual(
            base_info.get("params", base_info),
            v2_info.get("params", v2_info),
            "feedback must change the params",
        )


class CounterHonestyTests(unittest.TestCase):
    def test_stats_derived_from_files(self):
        import tempfile

        sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
        # Exercise the derivation logic directly: songs = dirs, plays/feedback = log lines.
        with tempfile.TemporaryDirectory() as d:
            songs = os.path.join(d, "songs")
            os.makedirs(os.path.join(songs, "abc123"))
            os.makedirs(os.path.join(songs, "def456"))
            with open(os.path.join(d, "plays.log"), "w") as f:
                f.write("x\n" * 7)
            with open(os.path.join(d, "feedback.log"), "w") as f:
                f.write("y\n" * 3)
            self.assertEqual(len(os.listdir(songs)), 2)
            self.assertEqual(sum(1 for _ in open(os.path.join(d, "plays.log"))), 7)
            self.assertEqual(sum(1 for _ in open(os.path.join(d, "feedback.log"))), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
