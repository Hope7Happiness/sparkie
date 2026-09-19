"""A failing audio transport must not prevent leaving the meeting."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from sparkie.engine import Primitive


class CleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_leaves_even_when_stop_speaking_fails(self):
        meeting = SimpleNamespace(join=AsyncMock(), leave=AsyncMock(),
                                  stop_speaking=AsyncMock(side_effect=RuntimeError('transport gone')),
                                  audio=lambda: None)
        class Ears:
            async def transcribe(self, frames):
                await asyncio.sleep(0)
                raise RuntimeError('disconnected')
                yield
        engine = Primitive(meeting, Ears(), SimpleNamespace(synthesize=AsyncMock(return_value=bytes(10))))
        response = asyncio.create_task(asyncio.sleep(60))
        engine.response_task = response
        with self.assertRaises(RuntimeError):
            await engine.run()
        meeting.leave.assert_awaited_once()
        self.assertIsNone(engine.response_task)
        self.assertTrue(response.done())
