"""Local Zoom output policy. No SDK, provider calls, timers, or input gating."""
import re
from .wake import ADDRESS, addressed_request

# Only explicit sentence boundaries, never commas or arbitrary name mentions.
SENTENCE_END = re.compile(r'[。！？!?]+|[.]+(?=\s|$)')
# Observed zh-CN rendering. Preserve the existing exact name/end boundary rules.
COMPACT_HELLO = re.compile(r'^hello(?=spark(?:ie|y)(?=$|[\s,，:：.!?。！？]|[\u4e00-\u9fff]))', re.I)
# Stop speaking is an output command; "stop the server" / "cancel the task"
# are addressed requests for the agent, not reasons to silently discard a turn.
DISMISSAL = re.compile(
    r"^(?:stop(?:[ ,]+(?:talking|speaking|please|for now))?|please\s+stop(?:\s+(?:talking|speaking))?|"
    r"never\s*mind|cancel|be\s+quiet|没事|不用了|取消|算了)(?=$|[.!?。！？])", re.I)


class ZoomOutputPolicy:
    def __init__(self, audio, emit):
        self.audio, self.emit = audio, emit
        self.epoch = 0
        self.chain = None
        self.generated = False
        self.pending_chain = None
        self.responses = {}
        self.items = {}
        self.task_ids = set()
        self.manual_next = False
        self.notifications_paused = False
        self.seen = set()
        self.suppressed = set()
        # Install only for Zoom sessions; capture/input_gate is untouched.
        audio.output_allowed = self.item_allowed
        audio.output_drained = self.maybe_close
        self.emit('zoom_output_state', muted=True, reason='startup', remote_audibility_verified=False)

    def decision(self, text):
        return self.evaluate(text)[0]

    def evaluate(self, text):
        decision, selected, index, normalized = 'ignore', text, None, False
        starts = [0] + [m.end() for m in SENTENCE_END.finditer(text)]
        for number, start in enumerate(starts):
            candidate = text[start:].strip()
            if not candidate:
                continue
            candidate, changed = COMPACT_HELLO.subn('hello ', candidate, count=1)
            match = ADDRESS.match(candidate)
            rest = candidate[match.end():].strip(' ,，:：.!?。！？') if match else candidate
            # Bare dismissal is accepted only at the original segment start.
            if DISMISSAL.search(rest) and (match or number == 0):
                decision = 'mute'
            elif match is not None or addressed_request(candidate) is not None:
                decision = 'wake'
            else:
                continue
            selected, index, normalized = candidate, number, bool(changed)
        reason = {'ignore': 'no_sentence_start_address', 'wake': 'addressed_sentence',
                  'mute': 'explicit_cancel'}[decision]
        if decision == 'ignore' and self.manual_next:
            decision, reason = 'wake', 'manual_next_turn'
        self.emit('zoom_wake_decision', decision=decision, reason=reason,
                  sentence_index=index, compact_greeting_normalized=normalized)
        return decision, selected

    def open(self, reason):
        self.epoch += 1
        self.chain = self.epoch
        self.generated = False
        self.manual_next = False
        self.notifications_paused = False
        self.emit('zoom_output_state', muted=False, reason=reason, chain=self.chain,
                  remote_audibility_verified=False)

    def revoke(self, reason, *, pause=True):
        was_open = self.chain is not None
        self.chain = None
        self.manual_next = False
        self.notifications_paused = pause
        if was_open or reason == 'manual_mute':
            self.emit('zoom_output_state', muted=True, reason=reason, remote_audibility_verified=False)

    def requested(self):
        self.pending_chain = self.chain

    def created(self, response_id):
        self.responses[response_id] = self.pending_chain
        self.pending_chain = None

    def allows(self, response_id):
        return self.chain is not None and self.responses.get(response_id) == self.chain

    def item_allowed(self, item_id):
        return self.chain is not None and self.items.get(item_id) == self.chain

    def accept_item(self, response_id, item_id):
        if self.allows(response_id):
            self.items[item_id] = self.chain
            return True
        if item_id not in self.suppressed:
            self.suppressed.add(item_id)
            self.emit('zoom_output_suppressed', item_id=item_id, reason='no_active_output_chain',
                      delivery_confirmed=False)
        return False

    def finished(self, response_id, continuation):
        if self.allows(response_id) and not continuation:
            self.generated = True
            self.maybe_close()

    def maybe_close(self):
        if self.chain is None or not self.generated:
            return
        if any(self.items.get(o.item_id) == self.chain and not o.cancelled.is_set() and not o.drained
               for o in self.audio.outputs.values()):
            return
        self.revoke('chain_drained', pause=False)
