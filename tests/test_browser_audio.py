import base64
import unittest
import struct
from unittest.mock import patch
from sparkie.browser_audio import BrowserAudio
from sparkie.providers import ProviderError

class BrowserAudioTests(unittest.IsolatedAsyncioTestCase):
    async def test_input_diagnostics_distinguish_clipping_and_silence_without_retaining_audio(self):
        events = []
        audio = BrowserAudio(max_seconds=0, on_event=lambda kind, **fields: events.append((kind, fields)))
        samples = [0, 16384, -16384, 32767] * 120
        pcm = base64.b64encode(struct.pack('<480h', *samples)).decode()
        with patch('sparkie.browser_audio.time.monotonic', side_effect=[i * .02 for i in range(100)]):
            for i in range(100): audio.accept({'action': 'audio_input', 'sequence': i, 'pcm': pcm})
        summaries = [fields for kind, fields in events if kind == 'audio_input_diagnostics']
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]['clipped_fraction'], .25)
        self.assertEqual(summaries[0]['zero_fraction'], .25)
        self.assertAlmostEqual(summaries[0]['rms_dbfs'], -4.3, delta=.1)
        self.assertEqual(summaries[0]['max_packet_gap_ms'], 20)
        self.assertNotIn('pcm', summaries[0])
        self.assertEqual(audio.queue.get_nowait().pcm, struct.pack('<480h', *samples))

    async def test_manual_session_accepts_audio_until_explicit_stop(self):
        audio = BrowserAudio(max_seconds=0, on_event=lambda *a, **k: None)
        pcm = base64.b64encode(bytes(960)).decode()
        audio.accept({'action': 'audio_input', 'sequence': 0, 'pcm': pcm})
        stream = audio.audio()
        self.assertEqual((await anext(stream)).pcm, bytes(960))
        audio.request_stop()
        with self.assertRaises(StopAsyncIteration):
            await anext(stream)

    async def test_duplex_capture_continues_during_output_and_interrupt_discards_late_progress(self):
        events=[]
        audio=BrowserAudio(max_seconds=10,on_event=lambda kind,**fields:events.append((kind,fields)))
        pcm=b'\x10\0'*480
        audio.append_output('i',pcm)
        audio.accept({'action':'audio_input','sequence':0,'pcm':base64.b64encode(pcm).decode()})
        frame=await anext(audio.audio())
        self.assertEqual(frame.pcm,pcm)
        audio.accept({'action':'audio_progress','generation':0,'item_id':'i','played_bytes':480})
        self.assertEqual(audio.outputs['i'].played_ms(),10)
        await audio.stop_speaking()
        audio.accept({'action':'audio_progress','generation':0,'item_id':'i','played_bytes':960})
        self.assertEqual(audio.outputs['i'].played_ms(),10)
        self.assertEqual(events[-1][0],'audio_clear')
        self.assertTrue(audio.outputs['i'].cancelled.is_set())

    async def test_capture_loss_is_explicit(self):
        audio=BrowserAudio(max_seconds=10,on_event=lambda *args,**kwargs:None)
        with self.assertRaises(ProviderError):
            audio.accept({'action':'audio_input','sequence':2,'pcm':base64.b64encode(bytes(960)).decode()})
