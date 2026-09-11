import base64
import pytest
from playback import PlaybackState
from compare_runs import compare
from scenarios import SCENARIOS

def payload(ms): return base64.b64encode(b'0'*(ms*8)).decode()
def row(**kw): return dict(contained=True,task_completed=True,safety_ok=True,quality=5,**kw)

def test_interrupt_keeps_generation_separate_from_playback():
 p=PlaybackState();p.chunk('i',payload(1000),100,content_index=2)
 event=p.interrupt(350)
 assert event['audio_end_ms']==250 and event['content_index']==2
 assert p.chunk('i',payload(200),360) is None
 assert p.interrupt(360) is None

def test_cutoff_bounded_by_generated_audio_and_acknowledgment():
 p=PlaybackState();m=p.chunk('i',payload(100),0);p.acknowledge(m)
 assert p.interrupt(30)['audio_end_ms']==100
 p.chunk('j',payload(100),0);assert p.interrupt(10000)['audio_end_ms']==100

def test_clear_ack_does_not_corrupt_next_item():
 p=PlaybackState();old=p.chunk('i',payload(500),0);p.interrupt(10)
 p.chunk('j',payload(50),20);p.acknowledge(old)
 assert p.ack_ms==0 and p.interrupt(30)['audio_end_ms']==10

def test_missing_and_invalid_cases_fail_gate():
 assert compare({'x':row()},{},['x'])
 for field,value in [('task_completed',None),('safety_ok',None),('quality',float('nan')),('contained','yes')]:
  new=row();new[field]=value;assert compare({'x':row()},{'x':new},['x'])
 assert compare({'x':row()},{'x':row(evaluation_mode='dry_run')},['x'])

def test_appropriate_escalation_is_not_automatically_failure():
 new=row();new['contained']=False
 assert compare({'x':row()},{'x':new},['x'])==[]

def test_safety_cases_need_affirmative_pass():
 name=next(k for k,v in SCENARIOS.items() if v.category=='safety')
 new=row();new['safety_ok']=None
 assert compare({name:new},{name:new},[name])

def test_declared_suite_includes_all_scenarios():
 full={name:row() for name in SCENARIOS}
 assert compare(full,full,list(SCENARIOS))==[]
 missing=dict(full);missing.pop(next(iter(missing)))
 assert compare(full,missing,list(SCENARIOS))
