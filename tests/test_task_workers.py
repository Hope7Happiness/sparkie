import asyncio
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest.mock import patch

from sparkie.providers import ProviderError
from sparkie.task_workers import CodexTaskWorker, DevinTaskWorker, configured_task_worker
from sparkie.task_center import TaskCenter, TranscriptLedger
from sparkie.realtime import RealtimeAgent


class ConfigurationTests(unittest.TestCase):
    def test_default_and_explicit_backend_models(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsInstance(configured_task_worker(), CodexTaskWorker)
            with patch.dict(os.environ, {'SPARKIE_TASK_BACKEND': 'devin'}):
                self.assertEqual(configured_task_worker().model, 'swe-1-6-fast')
                with patch.dict(os.environ, {'DEVIN_MODEL': 'test-model'}):
                    self.assertEqual(configured_task_worker().model, 'test-model')
            with patch.dict(os.environ, {'SPARKIE_TASK_BACKEND': 'typo'}):
                with self.assertRaises(ValueError): configured_task_worker()


FIXTURE = r'''
import json,os,sys
from pathlib import Path
sid='fixture-conversation'
pending=None
with open('starts.jsonl','a') as f:
    f.write(json.dumps({'pid':os.getpid(),'args':sys.argv[1:],'cwd':os.getcwd(),
        'has_voice_key':'OPENAI_API_KEY' in os.environ,'tool_env':os.getenv('SPARKIE_TEST_TOOL_ENV')})+'\n')
def send(msg): print(json.dumps({'jsonrpc':'2.0',**msg}),flush=True)
def result(rid,value): send({'id':rid,'result':value})
def event(value): send({'method':'session/update','params':{'sessionId':sid,'update':value}})
def answer(rid,request):
    event({'sessionUpdate':'agent_thought_chunk','content':{'type':'text','text':'PRIVATE_THOUGHT'}})
    event({'sessionUpdate':'tool_call','kind':'read','status':'completed','rawOutput':'PRIVATE_TOOL_OUTPUT'})
    if request!='EMPTY':
        event({'sessionUpdate':'agent_message_chunk','content':{'type':'text','text':'Verified '+request}})
    result(rid,{'stopReason':'end_turn'})
for line in sys.stdin:
    msg=json.loads(line);method=msg.get('method');rid=msg.get('id');params=msg.get('params',{})
    if method=='initialize': result(rid,{'protocolVersion':1})
    elif method=='session/new': result(rid,{'sessionId':sid})
    elif method=='session/set_mode': result(rid,{})
    elif method=='session/prompt':
        payload=json.loads(params['prompt'][0]['text'].split('\n',1)[1])
        path=Path(payload['complete_transcript_file']); request=payload['request']
        with open('calls.jsonl','a') as f:
            f.write(json.dumps({'request':request,'session_id':params['sessionId'],
                'transcript':json.loads(path.read_text()),'path':str(path)})+'\n')
        if request=='CRASH': sys.exit(7)
        elif request=='FAIL': send({'id':rid,'error':{'code':-1,'message':'PRIVATE_ERROR'}})
        elif request in ('WAIT','IGNORE_CANCEL'): pending=(rid,request)
        elif request=='PERMISSION':
            pending=(rid,request)
            send({'id':'permission-1','method':'session/request_permission','params':{'sessionId':sid,
                'options':[{'kind':'allow_once','optionId':'yes'}]}})
        else: answer(rid,request)
    elif method=='session/cancel':
        if pending and pending[1]!='IGNORE_CANCEL':
            result(pending[0],{'stopReason':'cancelled'});pending=None
    elif rid=='permission-1':
        assert msg['result']['outcome']=={'outcome':'selected','optionId':'yes'}
        answer(pending[0],pending[1]);pending=None
'''


class DevinWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.executable = self.root / 'devin'
        # A venv path can contain spaces, which macOS splits in a shebang.
        self.executable.write_text('#!' + str(Path(sys.executable).resolve()) + '\n' + FIXTURE)
        self.executable.chmod(0o700)
        self.which = patch('sparkie.devin_acp.shutil.which', return_value=str(self.executable))
        self.which.start()
        self.worker = DevinTaskWorker(workspace=self.root)

    async def asyncTearDown(self):
        await self.worker.close()
        self.which.stop()
        self.temp.cleanup()

    def records(self, name):
        path = self.root / name
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    async def wait_calls(self, count):
        async with asyncio.timeout(10):
            while len(self.records('calls.jsonl')) < count:
                await asyncio.sleep(.01)

    async def test_reuses_process_session_and_keeps_private_snapshots_until_close(self):
        records = [{'text': '完整上下文' * 2000} for _ in range(80)]
        progress = []
        with patch.dict(os.environ, {'OPENAI_API_KEY':'voice-secret','SPARKIE_TEST_TOOL_ENV':'preserved'}):
            await self.worker.start()
        for request in ('first $(literal)', 'followup'):
            result = await self.worker.run_with_progress(request, records, lambda **kw: progress.append(kw))
            self.assertEqual(result, 'Verified '+request)
        calls = self.records('calls.jsonl');starts = self.records('starts.jsonl')
        self.assertEqual(len(starts), 1)
        self.assertEqual({c['session_id'] for c in calls}, {'fixture-conversation'})
        self.assertEqual(calls[0]['transcript'], records)
        self.assertTrue(all(Path(c['path']).exists() for c in calls))
        self.assertEqual(starts[0]['cwd'], str(self.root.resolve()))
        self.assertFalse(starts[0]['has_voice_key'])
        self.assertEqual(starts[0]['tool_env'], 'preserved')
        self.assertIn('acp', starts[0]['args'])
        self.assertNotIn('--print', starts[0]['args'])
        self.assertIn('swe-1-6-fast', starts[0]['args'])
        self.assertNotIn('PRIVATE', json.dumps(progress))
        await self.worker.close()
        self.assertTrue(all(not Path(c['path']).exists() for c in calls))
        with self.assertRaises(ProcessLookupError): os.kill(starts[0]['pid'], 0)

    async def test_rpc_error_and_empty_result_are_not_success_and_session_remains_usable(self):
        for request, message in [('FAIL','devin_rpc_failed'), ('EMPTY','devin_empty_result')]:
            with self.subTest(request=request):
                with self.assertRaisesRegex(ProviderError,message): await self.worker.run(request, [])
        self.assertEqual(await self.worker.run('recovered', []), 'Verified recovered')
        self.assertEqual(len(self.records('starts.jsonl')), 1)

    async def test_missing_executable_fails(self):
        with patch('sparkie.devin_acp.shutil.which', return_value=None):
            with self.assertRaisesRegex(ProviderError, 'devin_unavailable'): await self.worker.run('test', [])

    async def test_cancel_stops_turn_but_reuses_same_process_for_next_task(self):
        task = asyncio.create_task(self.worker.run('WAIT', []))
        await self.wait_calls(1)
        pid = self.worker.process.pid
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertIsNone(self.worker.process.returncode)
        self.assertEqual(await self.worker.run('next', []), 'Verified next')
        self.assertEqual(self.worker.process.pid, pid)

    async def test_connection_loss_fails_without_replaying_or_silently_resetting_session(self):
        with self.assertRaises(ProviderError): await self.worker.run('CRASH', [])
        with self.assertRaises(ProviderError): await self.worker.run('do not replay', [])
        self.assertEqual(len(self.records('starts.jsonl')), 1)

    async def test_permission_uses_existing_authorization_without_raw_tool_forwarding(self):
        self.assertEqual(await self.worker.run('PERMISSION', []), 'Verified PERMISSION')

    async def test_running_revision_and_followup_use_same_agent_and_task_id(self):
        center = TaskCenter(TranscriptLedger(self.root/'ledger'), self.worker, lambda *a, **kw: None)
        center.start()
        try:
            identifier = center.submit('WAIT')['task_id']
            await self.wait_calls(1)
            sent = []
            class VoiceSocket:
                async def send(self, message): sent.append(json.loads(message))
            voice = RealtimeAgent('fixture-key', None, center, lambda *a, **kw: None)
            voice.ws = VoiceSocket()
            await voice.handle({'type': 'response.function_call_arguments.done',
                                'call_id': 'revision-call', 'response_id': 'voice-response',
                                'name': 'update_task', 'arguments': json.dumps(
                                    {'task_id': identifier, 'request': 'revised goal'})})
            update = json.loads(sent[-1]['item']['output'])
            self.assertEqual(update['update_delivery'], 'pending')
            self.assertEqual(update['task_id'], identifier)
            await asyncio.wait_for(center.runners[identifier], 10)
            job = center.status(identifier)
            self.assertEqual(job['status'], 'completed')
            self.assertEqual(job['result'], 'Verified revised goal')
            self.assertEqual(job['applied_revision'], 1)
            self.assertEqual(job['update_delivery'], 'delivered')
            self.assertEqual(job['request_history'][0]['request'], 'WAIT')
            follow = center.submit('followup')['task_id']
            await center.runners[follow]
            self.assertEqual(center.status(follow)['agent_session_id'], job['agent_session_id'])
            self.assertEqual(len(self.records('starts.jsonl')), 1)
            self.assertEqual(center.notifications.qsize(), 2)
        finally:
            await center.close()

    async def test_close_with_active_and_queued_jobs_cleans_process(self):
        center = TaskCenter(TranscriptLedger(self.root/'ledger'), self.worker, lambda *a, **kw: None)
        active = center.submit('WAIT')['task_id']
        queued = center.submit('never run')['task_id']
        await self.wait_calls(1)
        pid = self.worker.process.pid
        await center.close()
        self.assertEqual(center.status(active)['status'], 'cancelled')
        self.assertEqual(center.status(queued)['status'], 'cancelled')
        self.assertEqual(len(self.records('calls.jsonl')), 1)
        with self.assertRaises(ProcessLookupError): os.kill(pid, 0)

    async def test_unacknowledged_cancel_kills_agent_and_prevents_next_turn(self):
        task = asyncio.create_task(self.worker.run('IGNORE_CANCEL', []))
        await self.wait_calls(1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertIsNotNone(self.worker.process.returncode)
        with self.assertRaises(ProviderError): await self.worker.run('unsafe replay', [])
