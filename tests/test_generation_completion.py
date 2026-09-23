import base64
from playback import PlaybackState

def audio(ms): return base64.b64encode(b'x'*(ms*8)).decode()
def test_done_does_not_discard_buffered_audio():
 p=PlaybackState();p.chunk('a',audio(1000),100);p.generation_done('a')
 assert p.interrupt(350)['audio_end_ms']==250

def test_done_then_playback_completion_retires():
 p=PlaybackState();m=p.chunk('a',audio(100),0);p.generation_done('a');p.acknowledge(m)
 assert p.interrupt(500) is None

def test_playback_then_done_retires():
 p=PlaybackState();m=p.chunk('a',audio(100),0);p.acknowledge(m);p.generation_done('a')
 assert p.interrupt(500) is None
