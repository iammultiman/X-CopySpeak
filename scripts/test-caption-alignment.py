"""Run with python scripts/test-caption-alignment.py; no engine/model dependency."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


def load(relative):
    spec = importlib.util.spec_from_file_location("wrapper", Path(__file__).parent / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


piper = load("piper/copyspeak-piper.py")
edge = load("edge/copyspeak-edge.py")
kokoro = load("kokoro/copyspeak-kokoro.py")
kitten = load("kitten/copyspeak-kitten.py")
pocket = load("pocket/copyspeak-pocket.py")


class ModelSelectionTests(unittest.TestCase):
    def test_pocket_model_selection_preserves_default_and_passes_checkpoint(self):
        for checkpoint in (None, "english_2m_2026-10", "english_7m_2026-10"):
            with self.subTest(checkpoint=checkpoint):
                loader = Mock()
                args = ["pocket", "--serve"]
                if checkpoint:
                    args.extend(["--model", checkpoint])
                with patch.dict(sys.modules, pocket_tts=SimpleNamespace(TTSModel=loader)), \
                        patch.object(sys, "argv", args), patch.object(pocket, "serve", return_value=0):
                    self.assertEqual(pocket.main(), 0)
                loader.load_model.assert_called_once_with(**({"language": checkpoint} if checkpoint else {}))
                loader.load_model.return_value.get_state_for_audio_prompt.assert_called_once_with("alba")

    def test_kitten_dispatches_both_cpu_onnx_models_and_preserves_legacy_loader(self):
        modern = Mock()
        legacy = Mock()
        with patch.dict(sys.modules, kittenml=SimpleNamespace(KittenTTS=modern),
                        kittentts=SimpleNamespace(KittenTTS=legacy)):
            for family in ("pico", "nano"):
                model_id = f"KittenML/kitten-tts-2-{family}"
                adapter, session = kitten.load_engine(model_id, "cpu")
                self.assertIsNone(session)
                modern.assert_called_with(model_id, backend="onnx", device="cpu")
                adapter.generate("Hello", "Eleanor", 1.1, clean_text=True)
                modern.return_value.generate.assert_called_with("Hello", voice="Eleanor", speed=1.1)
                with self.assertRaisesRegex(ValueError, "require CPU"):
                    kitten.load_engine(model_id, "cuda")
            model, _ = kitten.load_engine("KittenML/kitten-tts-nano-0.8", "cpu")
            self.assertIs(model, legacy.return_value)
            legacy.assert_called_once_with("KittenML/kitten-tts-nano-0.8")


class AlignmentTests(unittest.TestCase):
    def test_piper_explicit_voice_directory_is_authoritative(self):
        with tempfile.TemporaryDirectory() as root:
            project = Path(root) / "engine"
            voices = project / "voices"
            voices.mkdir(parents=True)
            (voices / "en_US-lessac-medium.onnx").touch()
            override = Path(root) / "explicit"
            override.mkdir()
            with patch.object(piper.sys, "prefix", str(project / ".venv")):
                with self.assertRaises(FileNotFoundError):
                    piper.resolve_model("en_US-lessac-medium", str(override))
                model = override / "en_US-lessac-medium.onnx"
                model.touch()
                self.assertEqual(piper.resolve_model("en_US-lessac-medium", str(override)), model)

    def test_piper_finds_voices_in_uv_project_not_wrapper_location(self):
        with tempfile.TemporaryDirectory() as root:
            project = Path(root) / "engine"
            voices = project / "voices"
            voices.mkdir(parents=True)
            model = voices / "en_US-lessac-medium.onnx"
            model.touch()
            with patch.object(piper.sys, "prefix", str(project / ".venv")), \
                    patch.object(piper, "__file__", str(Path(root) / "app" / "scripts" / "copyspeak-piper.py")):
                self.assertEqual(piper.resolve_model("en_US-lessac-medium"), model)

    def test_kokoro_native_frames_keep_bos_spaces_punctuation_and_utf16(self):
        tokens = [SimpleNamespace(text=t, whitespace=w, phonemes=p) for t, w, p in
                  [("😀", " ", "a"), ("Hi", "", "hi"), (",", " ", ","), ("there", "", "b")]]
        phones, spans = next(kokoro.caption_batches("😀 Hi, there", tokens, dict.fromkeys("ahi,b ", 1)))
        self.assertEqual(phones, "a hi, b")
        words = kokoro.native_words(spans, [2, 1, 3, 4, 2, 5, 6, 7, 8], 22800, 2400)
        self.assertEqual(words, [
            {"text_start": 0, "text_end": 2, "start_ms": 150, "end_ms": 175},
            {"text_start": 3, "text_end": 5, "start_ms": 250, "end_ms": 400},
            {"text_start": 7, "text_end": 12, "start_ms": 675, "end_ms": 850},
        ])
        with self.assertRaisesRegex(ValueError, "refusing to rescale"):
            kokoro.native_words(spans, [2, 1, 3, 4, 2, 5, 6, 7, 8], 22799, 0)

    def test_kokoro_rejects_ambiguous_source_and_unknown_model_symbols(self):
        token = SimpleNamespace(text="do\tnot", whitespace="", phonemes="du nat")
        with self.assertRaisesRegex(ValueError, "merged words"):
            list(kokoro.caption_batches(token.text, [token], dict.fromkeys(token.phonemes)))
        token = SimpleNamespace(text="Hi", whitespace="", phonemes="hz")
        with self.assertRaisesRegex(ValueError, "model tokens"):
            list(kokoro.caption_batches("Hi", [token], {"h": 1}))
        with self.assertRaisesRegex(ValueError, "original text"):
            list(kokoro.caption_batches("Hi!", [token], {"h": 1}))

    def test_kokoro_drops_unpronounceable_punctuation_instead_of_aborting(self):
        # misaki leaks an unbalanced "[" into the phonemes of "[02:11"; it is not
        # in Kokoro's vocab and must not kill the reading.
        tokens = [SimpleNamespace(text=t, whitespace=w, phonemes=p) for t, w, p in
                  [("at", " ", "at"), ("[02:11", "", "[tu:"), ("]", "", ")")]]
        phones, spans = next(kokoro.caption_batches("at [02:11]", tokens, dict.fromkeys("atu: ", 1)))
        self.assertEqual(phones, "at tu:")
        self.assertEqual(spans, [(0, 2, 0, 2), (3, 9, 3, 6)])

    def test_kokoro_whole_token_chunks_keep_source_offsets(self):
        tokens = [SimpleNamespace(text=t, whitespace=w, phonemes=p) for t, w, p in
                  [("first", " ", "a" * 509), ("next", "", "b")]]
        batches = list(kokoro.caption_batches("first next", tokens, {"a": 1, "b": 2, " ": 3}))
        self.assertEqual([len(phones) for phones, _ in batches], [509, 1])
        self.assertEqual(batches[1][1], [(6, 10, 0, 1)])
        # Offset includes the first chunk's EOS/trailing silence, not last word end.
        words = kokoro.native_words(batches[1][1], [2, 3, 4], 5400, 306600)
        self.assertEqual(words[0]["start_ms"], 12825)

    def test_kokoro_sends_one_complete_caption_frame_before_pcm(self):
        captions = {"text": "Hi", "words": [{"text_start": 0, "text_end": 2,
                    "start_ms": 25, "end_ms": 50}]}
        pcm = b"\x01\x00\x02\x00"
        output = SimpleNamespace(buffer=io.BytesIO())
        def stream(*args):
            yield pcm, 24000, 1, captions
        with patch.object(kokoro, "stream", stream), patch.object(kokoro.sys, "stdout", output), \
                patch.object(kokoro.sys, "stdin", io.StringIO('{"text":"Hi"}\n')):
            self.assertEqual(kokoro.serve(None, "af_heart", None), 0)
        wire = io.BytesIO(output.buffer.getvalue())
        self.assertEqual(wire.readline(), b"READY 2\n")
        self.assertEqual(json.loads(wire.readline())["bits_per_sample"], 16)
        self.assertEqual(json.loads(wire.readline()), {"captions": captions})
        self.assertEqual(json.loads(wire.readline()), {"chunk": len(pcm)})
        self.assertEqual(wire.read(len(pcm)), pcm)
        self.assertEqual(json.loads(wire.readline()), {"end": True})
        self.assertEqual(wire.read(), b"")

    def test_kokoro_daemon_flushes_before_requesting_next_chunk(self):
        output = SimpleNamespace(buffer=io.BytesIO())
        pcm = b"\x01\x00\x02\x00"
        snapshots = [{"text": "Hi there", "words": []},
                     {"text": "Hi there", "words": [{"text_start": 3, "text_end": 8,
                      "start_ms": 25, "end_ms": 50}]}]

        def stream(*args):
            yield pcm, 24000, 1, snapshots[0]
            if args[2] != "Ready.":
                self.assertTrue(output.buffer.getvalue().endswith(pcm))
            yield pcm, 24000, 1, snapshots[1]

        with patch.object(kokoro, "stream", stream), patch.object(kokoro.sys, "stdout", output), \
                patch.object(kokoro.sys, "stdin", io.StringIO('{"text":"Hi there"}\n')):
            self.assertEqual(kokoro.serve(None, "af_heart", None), 0)
        wire = io.BytesIO(output.buffer.getvalue())
        self.assertEqual(wire.readline(), b"READY 2\n")
        self.assertEqual(json.loads(wire.readline())["bits_per_sample"], 16)
        for captions in snapshots:
            self.assertEqual(json.loads(wire.readline()), {"captions": captions})
            self.assertEqual(json.loads(wire.readline()), {"chunk": len(pcm)})
            self.assertEqual(wire.read(len(pcm)), pcm)
        self.assertEqual(json.loads(wire.readline()), {"end": True})
        self.assertEqual(wire.read(), b"")

    def test_kokoro_one_shot_keeps_all_chunks_and_final_captions(self):
        session = SimpleNamespace(get_outputs=lambda: [SimpleNamespace(name="waveform"),
                                  SimpleNamespace(name="duration")],
                                  get_providers=lambda: ["CPUExecutionProvider"])
        modules = {"kokoro_onnx": SimpleNamespace(Kokoro=lambda *args: SimpleNamespace(sess=session)),
                   "misaki": SimpleNamespace(en=SimpleNamespace(G2P=lambda **kwargs: None),
                   espeak=SimpleNamespace(EspeakFallback=lambda **kwargs: None))}
        captions = {"text": "Hi there", "words": []}
        chunks = [(b"\x01\x00", 24000, 1, None), (b"\x02\x00", 24000, 1, captions)]
        with tempfile.TemporaryDirectory() as directory:
            output = str(Path(directory) / "speech.wav")
            with patch.dict(kokoro.sys.modules, modules), \
                    patch.object(kokoro.sys, "argv", ["kokoro", "--text", "Hi there", "--output", output]), \
                    patch.object(kokoro, "resolve_models", return_value=("model", "voices")), \
                    patch.object(kokoro, "stream", return_value=iter(chunks)), \
                    patch.object(kokoro, "write_wav") as write:
                self.assertEqual(kokoro.main(), 0)
            write.assert_called_once_with(output, b"\x01\x00\x02\x00", 24000, 1)
            self.assertEqual(json.loads(Path(output + ".captions.json").read_text()), captions)

    def test_native_sample_counts_preserve_silence_and_sentence_offsets(self):
        alignment = [SimpleNamespace(phoneme=p, num_samples=n) for p, n in
                     [("^", 100), ("h", 40), ("i", 60), (",", 250), (" ", 50), ("b", 70), ("$", 100)]]
        self.assertEqual(piper.timed_phone_groups(alignment, 1000, 1000),
                         [("hi", 1100, 1200), ("b", 1500, 1570)])

    def test_normalization_and_context_mismatch_do_not_invent_word_boundaries(self):
        class Voice:
            def phonemize(self, text):
                return [list({"Pay": "peɪ", "$12.": "twɛlv dɑləɹz.", "the": "ði",
                              "Pay $12. the": "peɪ twɛlv dɑləɹz. ðə"}[text])]
        actual, mapping = piper.word_phone_map(Voice(), "Pay $12. the")
        self.assertEqual(actual, ["peɪ", "twɛlv", "dɑləɹz", "ðə"])
        self.assertEqual(mapping, [(0, 3, 0, 0), (4, 8, 1, 2)])

    def test_edge_preserves_punctuation_and_unicode_offsets(self):
        words = [{"text_start": 0, "text_end": 2, "start_ms": 150, "end_ms": 400},
                 {"text_start": 3, "text_end": 5, "start_ms": 900, "end_ms": 1200}]
        aligned = edge.preserve_source_text("😀 Hi, hi!", "Hi hi", words)
        self.assertEqual(aligned["text"], "😀 Hi, hi!")
        self.assertEqual([w["text_start"] for w in aligned["words"]], [3, 7])
        self.assertEqual(aligned["words"][1]["start_ms"], 900)
        normalized = edge.preserve_source_text("$12", "twelve", [{**words[0], "text_end": 6}])
        self.assertEqual(normalized["text"], "twelve")


if __name__ == "__main__":
    unittest.main()
