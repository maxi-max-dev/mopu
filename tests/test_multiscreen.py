import asyncio, tempfile, time, unittest
from pathlib import Path
from unittest.mock import Mock
from mopu.multiscreen import MultiscreenJobs

class Queue:
    generation=7
    def __init__(self):
        self.lease={'expires':time.monotonic()+60}
        self.task={'id':'task','steps':0};self.cap=4
    def check(self,agent,token):
        if not self.lease or time.monotonic()>=self.lease['expires'] or token!='valid':raise PermissionError('revoked')
        self.lease['expires']=time.monotonic()+120
        return self.task
    def ensure_budget(self,task,cost):
        if task['steps']+cost>self.cap:raise PermissionError('budget')
    def save(self):pass

class Backend:
    def __init__(self,job,guard):self.guard=guard;self.cleaned=False;self.inputs=0
    async def run(self):
        while True:
            self.guard(1);self.inputs+=1;await asyncio.sleep(.05)
    async def close(self):self.cleaned=True;return {'verified':True}

class Tests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.c=Mock();self.c.state_dir=Path(self.tmp.name);self.c.queue=Queue();self.backends=[]
        def factory(job,guard):
            b=Backend(job,guard);self.backends.append(b);return b
        self.m=MultiscreenJobs(self.c,factory)
    async def asyncTearDown(self):await self.m.close();self.tmp.cleanup()
    async def start(self):
        return await self.m.handle({'operation':'start','instruction':'只读两个副屏'},self.c.queue.task,'agent','valid')
    async def test_expiry_not_self_renewed(self):
        before=self.c.queue.lease['expires'];j=await self.start();await asyncio.sleep(.02)
        self.assertEqual(before,self.c.queue.lease['expires'])
    async def test_revocation_stops_and_cleans(self):
        j=await self.start();await asyncio.sleep(.02);self.c.queue.generation+=1
        await asyncio.sleep(.15)
        self.assertEqual(self.m.jobs[j['id']]['status'],'interrupted');self.assertTrue(self.backends[0].cleaned)
        count=self.backends[0].inputs;await asyncio.sleep(.1);self.assertEqual(count,self.backends[0].inputs)
    async def test_budget_blocks_before_dispatch(self):
        self.c.queue.cap=1;j=await self.start();await asyncio.sleep(.2)
        self.assertEqual(self.backends[0].inputs,1);self.assertEqual(self.m.jobs[j['id']]['status'],'interrupted')
    async def test_other_task_cannot_stop(self):
        j=await self.start()
        with self.assertRaises(PermissionError):await self.m.handle({'operation':'stop','job_id':j['id']},{'id':'other'},'agent','valid')
    async def test_missing_backend_no_side_effect(self):
        self.m.backend=None
        with self.assertRaises(RuntimeError):await self.start()
        self.assertEqual(self.m.jobs,{})
    async def test_no_secret_in_manifest(self):
        await self.start();await asyncio.sleep(.02)
        self.assertNotIn('valid',next((self.c.state_dir/'multiscreen').glob('*.json')).read_text())
    async def test_expired_lease_cannot_create(self):
        self.c.queue.lease['expires']=time.monotonic()-1
        with self.assertRaises(PermissionError):await self.start()
        self.assertEqual(self.m.jobs,{})

class PartialResultTests(unittest.IsolatedAsyncioTestCase):
 async def test_blocked_screen_does_not_become_full_success(self):
  with tempfile.TemporaryDirectory() as tmp:
   c=Mock();c.state_dir=Path(tmp);c.queue=Queue();c.observations.record.return_value={'id':'test-observation'}
   class Mixed:
    async def run(self):return [{'verified':True,'summary':'read'}, {'verified':False,'error':'needs user'}]
    async def close(self):return {'display_absence_readback':True}
   m=MultiscreenJobs(c,lambda j,g:Mixed())
   j=await m.handle({'operation':'start','instruction':'two tasks'},c.queue.task,'agent','valid')
   await asyncio.gather(*m.workers)
   self.assertEqual(m.jobs[j['id']]['status'],'partial')
   self.assertNotIn('observation',m.jobs[j['id']])

 async def test_stop_finished_preserves_result(self):
  with tempfile.TemporaryDirectory() as tmp:
   c=Mock();c.state_dir=Path(tmp);c.queue=Queue();c.observations.record.return_value={'id':'test-observation'}
   class Done:
    async def run(self):return [{'verified':True}]
    async def close(self):return {'display_absence_readback':True}
   m=MultiscreenJobs(c,lambda j,g:Done())
   j=await m.handle({'operation':'start','instruction':'one task'},c.queue.task,'agent','valid')
   await asyncio.gather(*m.workers)
   result=await m.handle({'operation':'stop','job_id':j['id']},c.queue.task,'agent','valid')
   self.assertEqual(result['status'],'complete')
