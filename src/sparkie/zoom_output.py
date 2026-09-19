"""Local Zoom output policy. No SDK, provider calls, timers, or input gating."""
from .wake import ADDRESS, CANCEL, addressed_request


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
        match = ADDRESS.match(text)
        rest = text[match.end():].strip(' ,，:：.!?。！？') if match else text.strip()
        if CANCEL.search(rest):
            return 'mute'
        if addressed_request(text) is not None or self.manual_next:
            return 'wake'
        return 'ignore'

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
