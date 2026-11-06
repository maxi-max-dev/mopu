import asyncio,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock
from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer
from mopu.multiscreen import MultiscreenJobs
from mopu.multiscreen_console import console_view
from mopu.multiscreen_agent import Backend

class ConsoleTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  self.tmp=tempfile.TemporaryDirectory();q=Mock();q.generation=1;q.lease={'expires':time.monotonic()+60};q.check.return_value={'id':'t'}
  self.c=SimpleNamespace(queue=q,state_dir=Path(self.tmp.name),op=asyncio.Lock());self.m=MultiscreenJobs(self.c);self.c.multiscreen_jobs=self.m
  self.job={'id':'j','task_id':'t','agent':'a','generation':1,'status':'running','_lease':'secret'}
  self.screen=SimpleNamespace(display=4,video=Mock(),cw=Mock(),size=(720,1280));self.screen.video.done.return_value=False;self.screen.cw.drain=AsyncMock()
  self.backend=SimpleNamespace(screens=[self.screen],entered=True,bridge=AsyncMock(return_value={'screens':[{'id':4,'paused':False,'app':'Browser'}]}))
  async def bridge(method,arg=None):
   if method=='tree':return {'nodes':[{'node':0,'bounds':[0,0,720,1280],'visible':True,'enabled':True,'text':'Tutorial','package':'example.browser'}]}
   if method=='action':return {'dispatched':True}
   return self.backend.state
  self.backend.state=self.backend.bridge.return_value
  self.backend.bridge.side_effect=bridge
  self.job['_backend']=self.backend;self.m.jobs['j']=self.job
  app=web.Application();app['console']=self.c;app.router.add_route('*','/api/multiscreen/{job}/{operation}/{display}',console_view)
  self.client=TestClient(TestServer(app));await self.client.start_server()
 async def asyncTearDown(self):await self.client.close();self.tmp.cleanup()
 async def test_agent_cannot_return_human_screen(self):
  await self.m.handle({'operation':'takeover','job_id':'j','display':4},{'id':'t'},'a','secret')
  with self.assertRaises(ValueError):await self.m.handle({'operation':'return','job_id':'j','display':4},{'id':'t'},'a','secret')
  self.assertIn(4,self.job['_held'])
 async def test_human_takeover_handback_and_no_unowned_display(self):
  r=await self.client.post('/api/multiscreen/j/takeover/4',json={});self.assertEqual(r.status,200);self.assertTrue((await r.json())['screens'][0]['paused'])
  r=await self.client.post('/api/multiscreen/j/return/4',json={});self.assertFalse((await r.json())['screens'][0]['paused']);self.assertEqual(self.job['_human_epoch'],2)
  r=await self.client.post('/api/multiscreen/j/takeover/99',json={});self.assertEqual(r.status,409)
 async def test_tap_requires_takeover_and_revocation_stops_input(self):
  r=await self.client.post('/api/multiscreen/j/tap/4',json={'x':1,'y':2});self.assertEqual(r.status,409);self.assertFalse(any(c.args[0]=='action' for c in self.backend.bridge.call_args_list))
  await self.m.hold(self.job,-1,True)
  r=await self.client.post('/api/multiscreen/j/tap/4',json={'x':1,'y':2});self.assertEqual(r.status,200);self.assertEqual(sum(c.args[0]=='action' for c in self.backend.bridge.call_args_list),1)
  self.c.queue.generation+=1
  r=await self.client.post('/api/multiscreen/j/tap/4',json={'x':1,'y':2});self.assertEqual(r.status,409);self.assertEqual(sum(c.args[0]=='action' for c in self.backend.bridge.call_args_list),1)
 async def test_host_pause_blocks_worker_without_deadlocking_human_handback(self):
  await self.m.hold(self.job,4,True)
  b=object.__new__(Backend);b.job=self.job;b.guard=lambda:None;b.bridge=self.backend.bridge
  with self.assertRaises(ValueError):await b.ready(self.screen,wait=False)
  waiter=asyncio.create_task(b.ready(self.screen));await asyncio.sleep(.01);self.assertFalse(waiter.done())
  await self.m.hold(self.job,4,False);await asyncio.wait_for(waiter,1)
 async def test_phone_pause_survives_host_handback(self):
  self.backend.state['screens'][0]['paused']=True
  state=await self.m.hold(self.job,4,False);self.assertTrue(state['screens'][0]['paused']);self.assertTrue(state['screens'][0]['phone_paused'])

 async def test_all_hold_includes_later_created_display(self):
  await self.m.hold(self.job,-1,True)
  self.backend.screens.append(SimpleNamespace(display=5))
  self.backend.state['screens'].append({'id':5,'paused':False,'app':'Second'})
  state=await self.m.inventory(self.job);self.assertTrue(all(s['paused'] for s in state['screens']))
  state=await self.m.hold(self.job,5,False)
  self.assertTrue(state['screens'][0]['paused']);self.assertFalse(state['screens'][1]['paused'])
