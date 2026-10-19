import asyncio,json,tempfile,unittest
from pathlib import Path
from unittest.mock import AsyncMock
from mopu.activity import ActivityLog
from mopu.input_activity import GestureParser,input_nodes,probe_inputs
from mopu.app import Console
CONFIG={'serial':'test-device','adb':'/test/adb','scrcpy_server':'/test/server','backend_command':['/test/node']}

CAP='''add device 1: /dev/input/event8
  name: "touchscreen"
  events:
    ABS_MT_POSITION_X : value 0, min 0, max 4320, fuzz 0
    ABS_MT_POSITION_Y : value 0, min 0, max 9600, fuzz 0
    ABS_MT_TRACKING_ID
    INPUT_PROP_DIRECT
'''
META='H: Handlers=event8\nS: Sysfs=/devices/platform/soc/i2c/input/input8\nI: Bus=0018'

class ParserTests(unittest.TestCase):
 def test_node_source_filter_excludes_virtual_and_external(self):
  self.assertEqual(len(input_nodes(CAP,META)),1)
  for bad in [META.replace('0018','0003'),META.replace('/platform/soc/i2c/','/virtual/'),META.replace('/i2c/','/usb1/')]:
   self.assertEqual(input_nodes(CAP,bad),[])
  self.assertEqual(input_nodes(CAP,''),[])
  candidates=input_nodes(CAP,'',allow_candidates=True)
  self.assertEqual(len(candidates),1);self.assertFalse(candidates[0]['topology_confirmed'])
 def test_touch_gestures_no_text_or_positions_emitted(self):
  p=GestureParser(input_nodes(CAP,META)[0])
  def event(t,k,v):return p.feed(f'[ {t} ] EV_ABS {k} {v}')
  event(1,'ABS_MT_TRACKING_ID','00000001');event(1,'ABS_MT_POSITION_X','00000010')
  p.feed('[ 1 ] EV_SYN SYN_REPORT 00000000')
  self.assertEqual(event(1.1,'ABS_MT_TRACKING_ID','ffffffff'),'tap')
  event(2,'ABS_MT_TRACKING_ID','00000002');event(2,'ABS_MT_POSITION_X','00000010')
  p.feed('[ 2 ] EV_SYN SYN_REPORT 00000000');event(2.1,'ABS_MT_POSITION_X','00000200')
  self.assertEqual(event(2.2,'ABS_MT_TRACKING_ID','ffffffff'),'swipe')
  event(3,'ABS_MT_TRACKING_ID','00000003')
  self.assertEqual(event(3.7,'ABS_MT_TRACKING_ID','ffffffff'),'long_press')
  self.assertIsNone(p.feed('[ 4 ] EV_KEY KEY_A DOWN'))
 def test_new_touch_at_new_position_is_not_a_swipe(self):
  p=GestureParser(input_nodes(CAP,META)[0])
  for t,x in [(1,'00000010'),(2,'00001000')]:
   p.feed(f'[ {t} ] EV_ABS ABS_MT_TRACKING_ID 00000001')
   p.feed(f'[ {t} ] EV_ABS ABS_MT_POSITION_X {x}')
   p.feed(f'[ {t} ] EV_SYN SYN_REPORT 00000000')
   self.assertEqual(p.feed(f'[ {t+.1} ] EV_ABS ABS_MT_TRACKING_ID ffffffff'),'tap')
 def test_only_allowed_keys_and_loss_is_not_a_gesture(self):
  p=GestureParser({'kind':'keys','keys':['KEY_POWER'],'axes':{}})
  self.assertEqual(p.feed('[ 1 ] EV_KEY KEY_POWER DOWN'),'power')
  self.assertIsNone(p.feed('[ 1 ] EV_KEY KEY_POWER UP'))
  self.assertIsNone(p.feed('[ 1 ] EV_KEY KEY_VOLUMEUP DOWN'))
  with self.assertRaises(ValueError):p.feed('[ 1 ] EV_SYN SYN_DROPPED 00000000')

class ActivityTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.t=1000
  self.a=ActivityLog(self.root,lambda:self.t);self.a.data['enabled']=True
  self.a.runtime.update(status='listening',fingerprint='fixture')
  (self.root/'activity-notifications.json').write_text(json.dumps({'command':['/fixture']}))
  (self.root/'activity-validation.json').write_text(json.dumps({'fingerprint':'fixture','physical_verified':True,'remote_verified':True}))
  self.a.send=AsyncMock(return_value={'status':'sent','message_id':'fixture-message'})
 async def asyncTearDown(self):self.temp.cleanup()
 async def test_continuous_actions_one_record_one_notification(self):
  for _ in range(70):
   self.a.record('device','tap',True);self.t+=2;await self.a.tick()
  self.a.send.assert_not_awaited()
  self.t+=31;await self.a.tick();await self.a.tick()
  self.assertEqual(len(self.a.data['records']),1)
  self.assertEqual(self.a.data['records'][0]['counts']['tap'],70)
  self.assertEqual(self.a.send.await_count,1)
 async def test_cooldown_and_restart_dont_repeat(self):
  self.a.record('device','tap',True);self.t+=31;await self.a.tick()
  self.t+=40;self.a.record('device','swipe',True);self.t+=31;await self.a.tick()
  self.assertEqual(self.a.send.await_count,1)
  restored=ActivityLog(self.root,lambda:self.t);restored.send=AsyncMock()
  await restored.tick();restored.send.assert_not_awaited()
  self.assertEqual(self.a.data['records'][-1]['notification'],'cooldown')
 async def test_no_notifications_without_actual_calibration(self):
  (self.root/'activity-validation.json').write_text('{}')
  self.a.record('device','tap',True);self.t+=11;await self.a.tick()
  self.a.send.assert_not_awaited();self.assertEqual(self.a.data['records'][0]['notification'],'held_unverified')
 async def test_physical_during_remote_is_logged_only(self):
  self.a.record('device','tap',False);self.t+=11;await self.a.tick();self.a.send.assert_not_awaited()
 async def test_disconnection_during_merge_window_suppresses_send(self):
  self.a.record('device','tap',True);self.t+=11;await self.a.tick(False);self.a.send.assert_not_awaited()
 async def test_hold_and_double_are_normalized(self):
  self.a.known({'id':'hold','source':'human','kind':'hold'},'sent')
  self.a.known({'id':'double','source':'agent','kind':'double'},'sent')
  self.assertEqual(self.a.data['records'][0]['counts'],{'long_press':1})
  self.assertEqual(self.a.data['records'][1]['counts'],{'double_tap':1})
 async def test_no_input_content_and_sent_then_returned_not_double_counted(self):
  cue={'id':'1','source':'human','kind':'text','text':'PRIVATE','points':[[123,456]]}
  self.a.known(cue,'sent');self.a.known(cue,'returned')
  self.assertEqual(self.a.data['records'][0]['counts'],{'text':1})
  for p in [self.a.path,self.root/'activity-events.jsonl']:
   self.assertNotIn('PRIVATE',p.read_text());self.assertNotIn('123',p.read_text())
 async def test_disconnection_and_changed_nodes_do_not_claim_coverage(self):
  self.a.runtime['fingerprint']='other';self.assertFalse(self.a.verified())
  self.assertEqual(self.a.snapshot(False)['status'],'offline')
 async def test_timeout_unknown_is_not_replayed_and_test_is_deduped(self):
  self.a.send=AsyncMock(return_value={'status':'unknown'})
  await self.a.test_notification();await self.a.test_notification()
  self.assertEqual(self.a.send.await_count,1)
  restored=ActivityLog(self.root);self.assertEqual(restored.data['test']['status'],'unknown')
 async def test_inflight_after_restart_is_unknown(self):
  self.a.record('device','tap',True);self.a.data['records'][0]['notification']='sending';self.a.save()
  restored=ActivityLog(self.root);self.assertEqual(restored.data['records'][0]['notification'],'unknown')
 async def test_restart_does_not_send_unfinished_session(self):
  self.a.record('device','tap',True);self.t+=31
  restored=ActivityLog(self.root,lambda:self.t);restored.send=AsyncMock()
  restored.runtime.update(status='listening',fingerprint='fixture')
  await restored.tick();restored.send.assert_not_awaited()
  self.assertEqual(restored.data['records'][0]['notification'],'expired')
 async def test_exact_merge_boundary_extends_session_without_early_send(self):
  self.a.record('device','tap',True);self.t+=30;await self.a.tick()
  self.a.send.assert_not_awaited();self.a.record('device','swipe',True)
  self.t+=30;await self.a.tick();self.a.send.assert_not_awaited()
  self.t+=1;await self.a.tick()
  self.assertEqual(self.a.send.await_count,1)
  self.assertEqual(self.a.data['records'][0]['counts'],{'tap':1,'swipe':1})
 async def test_summary_combines_apps_and_revisits_without_pre_session_or_private_content(self):
  self.a.apps.monotonic=lambda:self.t
  def observe(t,package):
   self.t=t;self.a.apps.observe({'status':'known','package':package,'label':{'settings':'设置','clock':'时钟'}[package],
                                'label_source':'device','text':'PRIVATE_TEXT','title':'PRIVATE_TITLE','url':'PRIVATE_URL'})
  observe(998,'settings');observe(1000,'settings');self.a.record('device','tap',True)
  observe(1002,'settings');await self.a.tick()
  observe(1004,'clock');observe(1006,'clock');await self.a.tick()
  observe(1008,'settings');self.a.record('device','swipe',True)
  for t in range(1010,1020,2):observe(t,'settings');await self.a.tick()
  self.a.apps.end('locked');self.t=1040;await self.a.tick()
  record=self.a.data['records'][0]
  self.assertEqual(record['app_summary'],[{'package':'settings','label':'设置','seconds':12.0},{'package':'clock','label':'时钟','seconds':2.0}])
  body=self.a.send.call_args.args[2]
  self.assertIn('设置：约 12 秒',body);self.assertIn('时钟：约 2 秒',body)
  self.assertEqual(body.count('• 设置'),1);self.assertIn('点击 1 次、滑动 1 次',body)
  for private in ('PRIVATE_TEXT','PRIVATE_TITLE','PRIVATE_URL'):self.assertNotIn(private,body);self.assertNotIn(private,self.a.path.read_text())
  await self.a.tick();self.assertEqual(self.a.send.await_count,1)
 async def test_pending_summary_keeps_visits_after_recent_log_eviction(self):
  self.a.apps.data['visits']=[{'id':'early','package':'settings','label':'设置','first':1000,'last':1002,'seconds':2}]
  self.a.record('device','tap',True);self.t=1002;await self.a.tick();await self.a.tick()
  self.a.apps.data['visits']=[{'id':'later','package':'clock','label':'时钟','first':1004,'last':1008,'seconds':4}]
  self.t=1008;self.a.record('device','tap',True);await self.a.tick()
  self.t=1040;await self.a.tick()
  self.assertEqual([v['seconds'] for v in self.a.data['records'][0]['app_summary']],[2,4])
  self.assertEqual(self.a.pending_apps,{})
 async def test_absent_app_readings_are_explicit_and_timeouts_are_not_replayed(self):
  self.a.send=AsyncMock(return_value={'status':'unknown'})
  self.a.record('device','tap',True);self.t+=31;await self.a.tick();await self.a.tick()
  self.assertIn('未取得可用的前台 App 读数',self.a.send.call_args.args[2])
  self.assertEqual(self.a.send.await_count,1)
 async def test_private_files_and_missing_config(self):
  self.a.record('device','key',True)
  self.assertEqual(self.a.path.stat().st_mode & 0o777,0o600)
  self.assertEqual((self.root/'activity-events.jsonl').stat().st_mode & 0o777,0o600)
  (self.root/'activity-notifications.json').write_text('{}');self.assertEqual(self.a.config(),{})
 async def test_probe_uses_sysfs_if_proc_is_denied(self):
  async def shell(*args):
   if args==('getevent','-pl'):return CAP
   if args==('cat','/proc/bus/input/devices'):raise RuntimeError('denied')
   if args[0]=='readlink':return '/sys/devices/platform/soc/i2c/input/input8'
   return '0018'
  class Device:pass
  d=Device();d.shell=shell
  self.assertTrue((await probe_inputs(d))['readable'])
 async def test_diagnostic_requires_lease(self):
  c=Console(CONFIG,self.root/'console');c.agents['a']={'token':'t','seen':0,'name':'A'}
  with self.assertRaises(PermissionError):await c.agent_request({'agent':'a','agent_token':'t','action':'input_probe'})

if __name__=='__main__':unittest.main()
