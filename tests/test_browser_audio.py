import base64
import unittest
from sparkie.browser_audio import BrowserAudio
from sparkie.providers import ProviderError

class BrowserAudioTests(unittest.IsolatedAsyncioTestCase):
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
