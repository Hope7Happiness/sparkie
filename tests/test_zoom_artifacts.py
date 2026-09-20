"""Zoom policy + real workspace RPC; synthetic bridge and worker, no SDK/model calls."""
import asyncio
import base64
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from sparkie.agent_runtime import AgentRuntime
from sparkie.event_bus import EventBus
from sparkie.realtime import RealtimeAgent, session_config
from sparkie.realtime_zoom_audio import RealtimeZoomAudio
from sparkie.task_center import TaskCenter, TranscriptLedger
from sparkie.workspace import WorkspaceStore
from sparkie.workspace_client import WorkspaceClient
from sparkie.workspace_server import serve_workspace
from sparkie.zoom_output import ZoomOutputPolicy
from test_semantic_interruption import Bridge


class ZoomArtifactTests(unittest.IsolatedAsyncioTestCase):
    def test_main_page_navigation_is_a_foreground_presentation_control(self):
        config = session_config('test')['session']
        hide = next(tool for tool in config['tools'] if tool['name'] == 'hide_artifact')
        self.assertIn('return to the main artifact workspace/list', hide['description'])
        self.assertIn('not stop Zoom screen sharing', hide['description'])
        self.assertIn('main artifact page, workspace or artifact list mean hide_artifact', config['instructions'])
        self.assertIn('not a request to edit a website or delegate a background task', config['instructions'])

    async def test_zoom_addressed_task_names_image_and_controls_presentation_with_interruption_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WorkspaceStore(':memory:')
            bus = EventBus()
            runtime = AgentRuntime(store, bus)
            server = await serve_workspace(store, bus, runtime, '127.0.0.1', 0)
            client = WorkspaceClient('127.0.0.1:' + str(server.sockets[0].getsockname()[1]))
            self.assertTrue(await client.open('zoom_uuid', 'synthetic-meeting', reset=True))
            mirrors = []
            def emit(kind, **fields):
                if kind == 'background_task':
                    mirrors.append(asyncio.create_task(client.task_update(fields)))
            class Worker:
                workspace = Path(directory)
                async def run(self, *args):
                    file = self.workspace / 'chart.png'
                    file.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a8ZkAAAAASUVORK5CYII='))
                    fence = chr(96) * 3
                    return 'Chart generated.\n' + fence + 'sparkie-artifact\n' + json.dumps({'path': str(file)}) + '\n' + fence
            center = TaskCenter(TranscriptLedger(Path(directory) / 'ledger'), Worker(), emit)
            audio = RealtimeZoomAudio(Bridge(), on_event=emit)
            policy = ZoomOutputPolicy(audio, emit)
            agent = RealtimeAgent('unused', audio, center, emit, output_policy=policy, workspace=client)
            sent = []
            async def send(message): sent.append(json.loads(message))
            agent.ws = SimpleNamespace(send=send)
            await audio.join()
            async def tool(name, arguments, response='voice'):
                await agent.handle({'type': 'response.function_call_arguments.done', 'response_id': response,
                    'call_id': str(len(sent)), 'name': name, 'arguments': json.dumps(arguments)})
                return json.loads(sent[-1]['item']['output'])
            try:
                await agent.human_transcript({'text': 'Sparkie, create a weather chart', 'event_id': 'first',
                    'is_final': True, 'source': 'human'})
                await agent.handle({'type': 'response.created', 'response': {'id': 'voice'}})
                delegated = await tool('delegate_task', {'request': 'Create the chart', 'artifact_title': 'Weather chart'})
                task_id = delegated['task_id']
                self.assertEqual(delegated['artifact_title'], 'Weather chart')
                self.assertIn(task_id, policy.task_ids)
                await center.runners[task_id]
                await asyncio.gather(*mirrors)
                async with asyncio.timeout(5):
                    while not store.latest_artifact(client.workspace_id):
                        await asyncio.sleep(.01)
                catalog = await tool('list_artifacts', {})
                artifact = catalog['artifacts'][0]
                self.assertEqual((artifact['title'], artifact['type']), ('Weather chart', 'image'))
                self.assertIsNone(catalog['active_artifact_id'])
                self.assertTrue((await tool('present_artifact', {'artifact_id': artifact['artifact_id']}))['ok'])
                self.assertEqual(store.get_state(client.workspace_id)['active_artifact_id'], artifact['artifact_id'])
                await agent.interrupt()
                self.assertEqual((await tool('hide_artifact', {}))['error'], 'interrupted_before_execution')
                self.assertEqual(store.get_state(client.workspace_id)['active_artifact_id'], artifact['artifact_id'])
                await agent.handle({'type': 'response.done', 'response': {'id': 'voice', 'status': 'cancelled'}})
                await agent.human_transcript({'text': 'Hi, Sparkie. Can you go back to the main artifact page?', 'event_id': 'second',
                    'is_final': True, 'source': 'human'})
                await agent.handle({'type': 'response.created', 'response': {'id': 'hide'}})
                self.assertTrue((await tool('hide_artifact', {}, 'hide'))['ok'])
                self.assertIsNone(store.get_state(client.workspace_id)['active_artifact_id'])
                self.assertIsNotNone(store.get_artifact(artifact['artifact_id']))
                self.assertEqual(list(center.jobs), [task_id])
                self.assertEqual(center.status(task_id)['status'], 'completed')
            finally:
                await center.close()
                await asyncio.gather(*mirrors)
                await audio.leave()
                await client.close()
                server.close()
                await server.wait_closed()
                await runtime.close()
                store.close()
