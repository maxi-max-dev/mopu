import asyncio,copy,tempfile,unittest,time
from pathlib import Path
from unittest.mock import AsyncMock
from mopu.tasks import Queue
from mopu.app import Console
from mopu.contracts import explanation
CONFIG={'serial':'synthetic','adb':'/NO-DEVICE','scrcpy_server':'/NO-DEVICE','backend_command':['/NO-DEVICE']}
class ManagementTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.q=Queue(Path(self.tmp.name)/'queue.json');self.q.owner='human'
  self.a=self.q.get(self.q.add('A','Scope A','a','A')['id']);self.b=self.q.get(self.q.add('B','Scope B','b','B')['id']);self.c=self.q.get(self.q.add('C','Scope C','c','C')['id'])
 def test_delete_restore_preserve_pending_budget_evidence(self):
  self.a.update(status='blocked',steps=200,prior_steps=100,long_task=True,pending_delivery='pending',deliveries=[{'key':'pending','outcome':'pending'}],checkpoint='Keep checkpoint')
  before=copy.deepcopy(self.a);self.q.manage('trash',[self.a['id']]);self.assertEqual(self.q.head()['id'],self.b['id'])
  with self.assertRaises(PermissionError):self.q.add('Duplicate','New scope','a','A')
  self.q.manage('restore',[self.a['id']]);self.assertTrue(self.a['user_held']);self.assertNotIn('deleted_at',self.a)
  for key,value in before.items():self.assertEqual(self.a[key],value)
  fresh=Queue(self.q.path).get(self.a['id']);self.assertTrue(fresh['user_held']);self.assertEqual(len(fresh['management_history']),2)
 def test_delete_queued_cannot_be_claimed_and_restore_stays_held(self):
  self.q.manage('trash',[self.a['id']]);self.q.owner='agent';self.assertIsNone(self.q.claim('a'));self.q.manage('restore',[self.a['id']]);self.assertIsNone(self.q.claim('a'));self.q.manage('resume',[self.a['id']]);self.assertIsNotNone(self.q.claim('a'))
 def test_hold_release_and_restart(self):
  self.q.manage('hold',[self.a['id'],self.b['id']]);self.assertEqual(self.q.head()['id'],self.c['id']);q=Queue(self.q.path);self.assertEqual(q.head()['id'],self.c['id']);q.manage('resume',[self.a['id']]);self.assertEqual(q.head()['id'],self.a['id'])
 def test_bulk_atomic_validation(self):
  self.b['status']='done';before=copy.deepcopy(self.q.data)
  with self.assertRaises(ValueError):self.q.manage('hold',[self.a['id'],self.b['id']])
  self.assertEqual(before,self.q.data)
  with self.assertRaises(ValueError):self.q.manage('trash',[self.a['id'],'missing'])
  self.assertEqual(before,self.q.data)
 def test_restore_finished_stays_finished(self):
  self.a.update(status='done',result='Keep result');self.q.manage('trash',[self.a['id']]);self.q.manage('restore',[self.a['id']]);self.assertEqual(self.a['status'],'done');self.assertEqual(self.a['result'],'Keep result');self.assertFalse(self.a.get('user_held'))
 def test_position_does_not_preempt_running(self):
  self.q.owner='agent';lease=self.q.claim('a')['lease'];self.q.position(self.c['id'],1);self.q.check('a',lease);self.assertEqual([t['title'] for t in self.q.data['tasks']],['A','C','B'])
 def test_hidden_tasks_cannot_edit_move_approve(self):
  self.q.manage('trash',[self.a['id']])
  with self.assertRaises(ValueError):self.q.edit(self.a['id'],'new','new','A','Scope A')
  with self.assertRaises(ValueError):self.q.move(self.a['id'],1)
  with self.assertRaises(PermissionError):self.q.approve_continuation({'id':self.a['id']})
 def test_hold_revokes_approved_stage(self):
  self.a.update(long_task=True,reviews=[{'state':'approved','ceiling':200,'expires_at':9999999999}]);self.q.manage('hold',[self.a['id']]);self.assertEqual(self.a['reviews'][0]['state'],'closed');self.assertTrue(self.a['user_held'])
 def test_explanations(self):
  self.a['user_held']=True;self.assertEqual(explanation(self.a,'human',True,None,False)['code'],'held');self.a['deleted_at']='today';self.assertEqual(explanation(self.a,'human',True,None,False)['code'],'trash')
class ManagementControlTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.c=Console(CONFIG,self.tmp.name);self.c.device.connected=True;self.c.device.release_touch=AsyncMock();self.c.device.clear_actions=AsyncMock();self.t=self.c.queue.add('Running','Scope','a','A');self.c.queue.owner='agent';self.lease=self.c.queue.claim('a')['lease']
 async def test_running_delete_stops_and_waits_for_inflight(self):
  await self.c.op.acquire();deletion=asyncio.create_task(self.c.control({'action':'trash','ids':[self.t['id']]}));await asyncio.sleep(.01)
  with self.assertRaises(PermissionError):self.c.queue.check('a',self.lease)
  self.assertFalse(deletion.done());self.assertNotIn('deleted_at',self.c.queue.get(self.t['id']));self.c.op.release();await deletion
  self.assertEqual(self.c.queue.owner,'human');self.assertIn('deleted_at',self.c.queue.get(self.t['id']))
 async def test_bad_batch_does_not_stop_running_task(self):
  with self.assertRaises(ValueError):await self.c.control({'action':'trash','ids':[self.t['id'],'missing']})
  self.c.queue.check('a',self.lease)
 async def test_offline_known_agent_can_receive_task_without_starting(self):
  self.c.queue.owner='human';self.c.queue.invalidate('test');self.c.agents.clear()
  self.assertEqual(self.c.snapshot()['agents'],[{'id':'a','name':'A','online':False}])
  await self.c.control({'action':'add','title':'Later','instruction':'Later scope','agent':'a'})
  self.assertEqual(len(self.c.queue.data['tasks']),2);self.assertIsNone(self.c.queue.lease)
