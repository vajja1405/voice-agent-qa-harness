"""Separate generated audio from playback; pure offline-testable state."""
import base64
from collections import deque

class PlaybackState:
    def __init__(self):
        self.item = None
        self.content_index = 0
        self.start_ms = 0
        self.generated_ms = 0.0
        self.ack_ms = 0.0
        self.pending = {}
        self.interrupted = deque(maxlen=100)
        self.sequence = 0

    def chunk(self, item, payload, now_ms, content_index=0):
        if not item or item in self.interrupted:
            return None
        duration = len(base64.b64decode(payload, validate=True)) / 8.0
        if item != self.item:
            self.pending.clear()
            self.item, self.content_index = item, content_index
            self.start_ms, self.generated_ms, self.ack_ms = now_ms, 0.0, 0.0
        self.generated_ms += duration
        self.sequence += 1
        mark = f'audio-{self.sequence}'
        self.pending[mark] = (item, self.generated_ms)
        return mark

    def acknowledge(self, mark):
        entry = self.pending.pop(mark, None)
        if entry and entry[0] == self.item:
            self.ack_ms = max(self.ack_ms, entry[1])

    def interrupt(self, now_ms):
        if self.item is None:
            return None
        # Call-clock time estimates playback; marks give a lower bound.
        cutoff = min(self.generated_ms, max(self.ack_ms, now_ms-self.start_ms, 0))
        event = {'type': 'conversation.item.truncate', 'item_id': self.item,
                 'content_index': self.content_index, 'audio_end_ms': int(cutoff)}
        self.interrupted.append(self.item)
        self.item = None
        # Clear acknowledgments can mean discarded audio, not played audio.
        self.pending.clear()
        return event
