"""Offline ACP protocol and asynchronous Zoom authorization regression tests."""
import asyncio
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import test_zoom_barge_in as zoom_fixture
from sparkie.wake_router import DevinWakeRouter, WakeRouterError, INSTRUCTION


# A real child process exercises framing, EOF, cancellation and process cleanup.
# It does not contact Devin or any network service.
FAKE_ACP = r'''
import json, sys, time
mode = sys.argv[1]
def send(message):
    print(json.dumps(message), flush=True)
for line in sys.stdin:
    message = json.loads(line)
    method = message.get('method')
    result = {}
    if method == 'initialize':
        result = {'protocolVersion': 1}
    elif method == 'session/new':
        result = {'sessionId': 'session-' + str(message['id'])}
    elif method == 'session/prompt':
        if mode == 'hang':
            time.sleep(60)
        if mode == 'eof':
            break
        session = message['params']['sessionId']
        text = message['params']['prompt'][0]['text']
        answer = '{"decision":"accept"}' if 'Hey Sparkie' in text else '{"decision":"reject"}'
        if mode == 'invalid':
            answer = '{"decision":"accept","extra":true}'
        if mode == 'oversized':
            answer = 'x' * 4097
        if mode == 'permission':
            send({'method':'session/request_permission', 'id':900, 'params':{}})
            continue
        if mode == 'error':
            send({'id':message['id'], 'error':{'message':'private provider information'}})
            continue
        # Unrelated sessions and thoughts must never enter the decision.
        send({'method':'session/update','params':{'sessionId':'old','update':{
            'sessionUpdate':'agent_message_chunk','content':{'type':'text','text':'stale'}}}})
        send({'method':'session/update','params':{'sessionId':session,'update':{
            'sessionUpdate':'agent_thought_chunk','content':{'type':'text','text':'private thought'}}}})
        send({'method':'session/update','params':{'sessionId':session,'update':{
            'sessionUpdate':'tool_call' if mode == 'tool' else 'agent_message_chunk',
            'content':{'type':'text','text':answer}}}})
        result = {'stopReason':'cancelled' if mode == 'incomplete' else 'end_turn'}
    send({'id':message['id'],'result':result})
'''


class RouterProtocolTests(unittest.IsolatedAsyncioTestCase):
    def router(self, mode='normal', timeout=1):
        async def spawn(*args, **kwargs):
            self.spawn_args = args, kwargs
            child = await asyncio.create_subprocess_exec(sys.executable, '-u', '-c', FAKE_ACP,
                                                         mode, **kwargs)
            self.children.append(child)
            return child
        self.children = []
        router = DevinWakeRouter(process_factory=spawn, timeout=timeout)
        self.addAsyncCleanup(router.close)
        return router

    async def test_decisions_are_isolated_tool_free_and_context_is_bounded(self):
        router = self.router()
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'never-pass-to-router'}):
            await asyncio.gather(router.start(), router.start())
        self.assertEqual(len(self.children), 1)
        args, kwargs = self.spawn_args
        self.assertIn('summarizer', args)
        self.assertIn('gemini-3-5-flash-minimal', args)
        self.assertNotIn('OPENAI_API_KEY', kwargs['env'])
        self.assertNotEqual(kwargs['cwd'], os.getcwd())
        self.assertEqual(await router.classify('Hey Sparkie, hello.'), 'accept')
        old = router.session_id
        self.assertEqual(await router.classify('Sparkie is our assistant.'), 'reject')
        self.assertNotEqual(old, router.session_id)
        old = router.session_id
        self.assertEqual(await router.classify('Ordinary discussion.'), 'reject')
        self.assertNotEqual(old, router.session_id)
        directory = kwargs['cwd']
        await router.close()
        self.assertIsNotNone(self.children[0].returncode)
        self.assertFalse(os.path.exists(directory))
        with self.assertRaisesRegex(WakeRouterError, 'closed'):
            await router.start()

    async def test_invalid_protocol_never_authorizes_and_disposes_process(self):
        for mode, reason in [('invalid', 'invalid_result'), ('oversized', 'oversized_result'),
                             ('permission', 'unexpected_permission'), ('tool', 'unexpected_tool'),
                             ('error', 'provider_error'), ('eof', 'connection_closed'),
                             ('incomplete', 'incomplete_result')]:
            with self.subTest(mode=mode):
                router = self.router(mode)
                with self.assertRaisesRegex(WakeRouterError, reason):
                    await router.classify('Hey Sparkie')
                self.assertIsNone(router.process)
                self.assertIsNotNone(self.children[0].returncode)

    async def test_timeout_disposes_child_and_allows_retry(self):
        router = self.router('hang', timeout=.15)
        with self.assertRaisesRegex(WakeRouterError, 'timeout'):
            await router.classify('Hey Sparkie')
        self.assertIsNotNone(self.children[0].returncode)
        self.assertIsNone(router.startup)
        with self.assertRaisesRegex(WakeRouterError, 'timeout'):
            await router.classify('Hey Sparkie')
        self.assertEqual(len(self.children), 2)

    async def test_cancelled_active_turn_kills_child_but_waiter_cancellation_does_not(self):
        router = self.router('hang', timeout=5)
        await router.start()
        active = asyncio.create_task(router.classify('Hey Sparkie'))
        await asyncio.sleep(.02)
        waiting = asyncio.create_task(router.classify('Another request'))
        await asyncio.sleep(0)
        waiting.cancel()
        await asyncio.gather(waiting, return_exceptions=True)
        self.assertIsNone(self.children[0].returncode)
        active.cancel()
        await asyncio.gather(active, return_exceptions=True)
        self.assertIsNotNone(self.children[0].returncode)
        self.assertIsNone(router.startup)

    async def test_failed_prewarm_can_retry_on_first_real_utterance(self):
        router = self.router()
        factory = router.process_factory
        router.process_factory = AsyncMock(side_effect=FileNotFoundError())
        with self.assertRaises(FileNotFoundError):
            await router.start()
        router.process_factory = factory
        self.assertEqual(await router.classify('Hey Sparkie'), 'accept')

    async def test_structured_window_survives_fresh_session(self):
        router = self.router()
        await router.start()
        rpc = router._rpc
        prompts = []
        async def capture(method, params):
            if method == 'session/prompt':
                prompts.append(params)
            return await rpc(method, params)
        router._rpc = capture
        context = [{'role': 'human', 'text': str(i), 'speaker_id': 'zoom:10'} for i in range(10)]
        for _ in range(2):
            await router.classify('The short version.', context=context, speaker='Oliver', speaker_id='zoom:10')
        self.assertNotEqual(prompts[0]['sessionId'], prompts[1]['sessionId'])
        for prompt in prompts:
            payload = json.loads(prompt['prompt'][0]['text'][len(INSTRUCTION):])
            self.assertEqual(payload['context'], context[-8:])
            self.assertEqual(payload['current'], dict(role='human', text='The short version.',
                                                      speaker='Oliver', speaker_id='zoom:10'))


class ControlledRouter:
    model = 'test-router'

    def __init__(self):
        self.calls = asyncio.Queue()
        self.inputs = []
        self.close = AsyncMock()

    async def classify(self, text, **kwargs):
        self.inputs.append({'text': text, **kwargs})
        future = asyncio.get_running_loop().create_future()
        await self.calls.put((text, future))
        # Deliberately resistant: stale fencing must work even if cancellation
        # reaches a provider after it has already produced its answer.
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            return await future


class SemanticWakeTests(unittest.IsolatedAsyncioTestCase):
    transcript = zoom_fixture.ZoomBargeInTests.transcript
    activity = zoom_fixture.ZoomBargeInTests.activity
    creates = zoom_fixture.ZoomBargeInTests.creates

    async def asyncSetUp(self):
        await zoom_fixture.ZoomBargeInTests.asyncSetUp(self)
        self.router = ControlledRouter()
        self.agent.wake_router = self.router
        self.addAsyncCleanup(self.agent.close_wake_router)

    async def settle(self, future, decision='accept'):
        pending = list(self.agent.wake_tasks)
        future.set_result(decision)
        await asyncio.wait_for(asyncio.gather(*pending), 1)

    async def assistant_text(self, text, item='answer', response='reply', kind='done'):
        await self.agent.handle({'type': 'response.output_audio_transcript.' + kind,
                                 'item_id': item, 'response_id': response,
                                 'transcript' if kind == 'done' else 'delta': text})

    async def test_followup_sees_assistant_question_and_current_speaker(self):
        await self.assistant_text('Would you like the short or detailed version?')
        await self.assistant_text('Would you like the short or detailed version?')
        await self.agent.human_transcript(dict(text='The short version.', event_id='followup',
            meeting_id='m', is_final=True, source='human', speaker='Oliver', speaker_id='zoom:10'))
        _, future = await self.router.calls.get()
        request = self.router.inputs[-1]
        self.assertEqual(len(request['context']), 1)
        self.assertEqual(request['context'][0]['role'], 'assistant')
        self.assertEqual(request['speaker'], 'Oliver')
        self.assertEqual(request['speaker_id'], 'zoom:10')
        await self.settle(future)
        self.assertEqual(self.creates(), 1)

    async def test_window_keeps_last_eight_prior_turns_including_rejections(self):
        for i in range(11):
            await self.transcript(f'Ordinary discussion {i}', ident=str(i), speaker=f'zoom:{i % 2}')
            _, future = await self.router.calls.get()
            await self.settle(future, 'reject')
        request = self.router.inputs[-1]
        self.assertEqual([entry['text'] for entry in request['context']],
                         [f'Ordinary discussion {i}' for i in range(2, 10)])
        self.assertEqual(request['context'][-1]['speaker_id'], 'zoom:1')
        self.assertEqual(len(self.agent.wake_context), 8)
        await self.transcript('Duplicate', ident='10')
        self.assertTrue(self.router.calls.empty())
        self.assertEqual(self.creates(), 0)

    async def test_snapshot_does_not_change_with_streamed_text_or_later_turn(self):
        await self.assistant_text('First part.', kind='delta')
        await self.transcript('Tell me more.', ident='old')
        _, old = await self.router.calls.get()
        old_task = self.agent.wake_pending
        await self.assistant_text(' Unheard ending.', kind='delta')
        await self.transcript('Oliver, can you take this?', ident='new', speaker='zoom:20')
        _, new = await self.router.calls.get()
        self.assertEqual(self.router.inputs[0]['context'][0]['text'], 'First part.')
        self.assertEqual(self.router.inputs[1]['context'][-1]['text'], 'Tell me more.')
        old.set_result('accept')
        await old_task
        await self.settle(new, 'reject')
        self.assertEqual(self.creates(), 0)

    async def test_interruption_labels_partial_output_and_drops_unplayed_output(self):
        await self.assistant_text('Some words, then an unheard question.', item='partial')
        await self.assistant_text('Entirely unplayed.', item='unplayed')
        self.agent.interrupt_wake_context({'reply'}, [
            SimpleNamespace(item_id='partial', played_ms=lambda: 100),
            SimpleNamespace(item_id='unplayed', played_ms=lambda: 0)])
        self.agent.cancelled.add('reply')
        await self.assistant_text('Late cancelled text.', item='unplayed')
        await self.transcript('Please continue.')
        _, future = await self.router.calls.get()
        context = self.router.inputs[-1]['context']
        self.assertEqual(len(context), 1)
        self.assertEqual(context[0]['delivery'], 'interrupted_may_include_unheard_words')
        await self.settle(future, 'reject')

    async def test_external_turn_uses_same_context_window(self):
        await self.assistant_text('Which version?')
        await self.agent.control(dict(action='human_turn', phase='start', turn_id='ext', source='human'))
        await self.agent.control(dict(action='human_turn', phase='commit', turn_id='ext',
                                      source='human', text='The shorter one.'))
        _, future = await self.router.calls.get()
        self.assertEqual(self.router.inputs[-1]['context'][0]['text'], 'Which version?')
        await self.settle(future)
        self.assertEqual(self.creates(), 1)

    async def test_evicted_assistant_item_cannot_reappear_on_late_final(self):
        await self.assistant_text('Early draft.', kind='delta')
        for i in range(8):
            await self.transcript(f'Discussion {i}', ident=str(i))
            _, future = await self.router.calls.get()
            await self.settle(future, 'reject')
        await self.assistant_text('Late final.')
        self.assertTrue(all(entry['role'] == 'human' for entry in self.agent.wake_context))

    async def test_real_interrupt_removes_unplayed_assistant_context(self):
        await self.assistant_text('This has not been submitted.')
        self.agent.response_id = 'reply'
        await self.activity('started')
        self.assertFalse(self.agent.wake_context)
        await self.assistant_text('Late cancelled final.')
        self.assertFalse(self.agent.wake_context)

    async def test_full_sentence_routes_async_and_waits_for_speech_end(self):
        await self.activity('started')
        sentence = 'Could you summarize that, Sparkie?'
        await asyncio.wait_for(self.transcript(sentence), .2)
        text, future = await self.router.calls.get()
        self.assertEqual(text, sentence)
        self.assertFalse(self.agent.turn_lock.locked())
        self.assertEqual(self.creates(), 0)
        await self.settle(future)
        self.assertEqual(self.creates(), 0)
        await self.activity('stopped')
        self.assertEqual(self.creates(), 1)
        texts = [m['item']['content'][0]['text'] for m in self.sent
                 if m['type'] == 'conversation.item.create' and m['item']['role'] == 'user']
        self.assertEqual(texts, [sentence])

    async def test_new_speech_and_manual_mute_fence_delayed_accept(self):
        for manual in (False, True):
            await self.transcript('Hey Sparkie, reply.', ident=str(manual))
            _, future = await self.router.calls.get()
            if manual:
                await asyncio.wait_for(self.agent.control({'action': 'mute'}), .2)
            else:
                await asyncio.wait_for(self.activity('started'), .2)
            await self.settle(future)
            self.assertEqual(self.creates(), 0)
            self.assertIsNone(self.policy.chain)
            await self.activity('stopped')

    async def test_new_final_supersedes_old_accept(self):
        await self.transcript('Hey Sparkie, reply.', ident='old')
        _, old = await self.router.calls.get()
        old_task = self.agent.wake_pending
        await self.transcript('Sparkie is a product.', ident='new')
        _, new = await self.router.calls.get()
        old.set_result('accept')
        await old_task
        self.assertIsNotNone(self.agent.wake_pending)
        await self.settle(new, 'reject')
        self.assertEqual(self.creates(), 0)

    async def test_noise_candidate_does_not_invalidate_pending_decision(self):
        await self.transcript('Hey Sparkie, reply.')
        _, future = await self.router.calls.get()
        await self.activity('candidate')
        await self.settle(future)
        self.assertEqual(self.creates(), 1)

    async def test_stop_and_manual_unmute_bypass_model_but_stop_server_does_not(self):
        await self.transcript('Sparkie, stop.', ident='stop')
        self.assertTrue(self.router.calls.empty())
        self.assertTrue(self.policy.notifications_paused)
        await self.transcript('Sparkie, stop the server.', ident='task')
        text, future = await self.router.calls.get()
        self.assertEqual(text, 'Sparkie, stop the server.')
        await self.settle(future, 'reject')
        await self.agent.control({'action': 'unmute'})
        await self.transcript('Give me the summary.', ident='manual')
        self.assertTrue(self.router.calls.empty())
        self.assertEqual(self.creates(), 1)

    async def test_reject_or_error_releases_pending_background_result(self):
        job = {'task_id': 'eligible', 'status': 'completed', 'result': 'Verified offline result'}
        self.center.jobs['eligible'] = job
        self.center._save(job)
        self.policy.task_ids.add('eligible')
        for fail in (False, True):
            await self.transcript('Ordinary discussion.', ident=str(fail))
            _, future = await self.router.calls.get()
            self.assertFalse(self.agent.notification_ready())
            pending = self.agent.wake_pending
            if fail:
                future.set_exception(WakeRouterError('timeout'))
                await pending
            else:
                await self.settle(future, 'reject')
            self.assertEqual(self.creates(), 0)
            self.assertTrue(self.agent.notification_ready())
        self.agent.ready.set()
        notifier = asyncio.create_task(self.agent.notify_tasks())
        try:
            async with asyncio.timeout(1):
                while not self.creates():
                    await asyncio.sleep(.01)
            self.assertEqual(job['announcement']['state'], 'offered')
        finally:
            notifier.cancel()
            await asyncio.gather(notifier, return_exceptions=True)

    async def test_shutdown_discards_resistant_pending_accept(self):
        await self.transcript('Hey Sparkie, reply.')
        _, future = await self.router.calls.get()
        closing = asyncio.create_task(self.agent.close_wake_router())
        await asyncio.sleep(0)
        future.set_result('accept')
        await asyncio.wait_for(closing, 1)
        self.assertEqual(self.creates(), 0)
        self.router.close.assert_awaited_once()
        await self.transcript('Hey Sparkie, flushed after shutdown.', ident='late')
        self.assertTrue(self.router.calls.empty())
        self.assertFalse(self.agent.wake_tasks)

    async def test_old_provider_cancellation_does_not_discard_new_human_request(self):
        self.agent.response_id = 'old'
        await self.transcript('Could you help, Sparkie?')
        _, future = await self.router.calls.get()
        await self.agent.handle({'type': 'response.done',
                                 'response': {'id': 'old', 'status': 'cancelled'}})
        await self.settle(future)
        self.assertEqual(self.creates(), 1)
