import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from mopu.app import Console, secure, state, agent
from mopu.tasks import Queue
from mopu.device import Device
from mopu.mcp import Client


CONFIG = {'serial':'test-device','adb':'/test/adb','scrcpy_server':'/test/server','backend_command':['/test/node']}


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'queue.json'
        self.q = Queue(self.path)
        self.a = self.q.add('Task A','Read A','codex','Codex')
        self.b = self.q.add('Task B','Read B','claude','Claude')
        self.q.owner = 'agent'

    def tearDown(self): self.temp.cleanup()

    def test_tasks_stay_with_original_agent(self):
        self.assertIsNone(self.q.claim('claude'))
        lease = self.q.claim('codex')
        self.assertEqual(lease['task']['id'], self.a['id'])
        self.assertIsNone(self.q.claim('claude'))

    def test_pause_invalidates_old_token_and_preserves_progress(self):
        old = self.q.claim('codex')['lease']
        self.q.checkpoint('codex',old,'Read first paragraph','Read second')
        self.q.invalidate('Human takeover')
        with self.assertRaises(PermissionError): self.q.check('codex', old)
        fresh = self.q.claim('codex')
        self.assertNotEqual(old,fresh['lease'])
        self.assertEqual(fresh['task']['checkpoint'],'Read first paragraph')

    def test_expired_client_cannot_finish_task(self):
        token = self.q.claim('codex')['lease']
        self.q.lease['expires'] = time.monotonic()-1
        with self.assertRaises(PermissionError): self.q.finish('codex',token,'False completion')
        self.assertEqual(self.q.get(self.a['id'])['status'],'paused')

    def test_restart_requires_explicit_resume(self):
        self.q.claim('codex')
        restored=Queue(self.path)
        self.assertEqual(restored.owner,'paused')
        self.assertEqual(restored.get(self.a['id'])['status'],'paused')
        self.assertIsNone(restored.claim('codex'))

    def test_reorder_does_not_preempt_but_priority_does(self):
        token=self.q.claim('codex')['lease']
        self.q.move(self.b['id'],-1)
        self.q.check('codex',token)
        self.q.prioritize(self.b['id'])
        with self.assertRaises(PermissionError): self.q.check('codex',token)
        self.assertEqual(self.q.claim('claude')['task']['id'],self.b['id'])

    def test_result_and_cancelled_history_are_retained(self):
        token=self.q.claim('codex')['lease']
        self.q.finish('codex',token,'Observed result')
        self.q.cancel(self.b['id'])
        restored=Queue(self.path)
        self.assertEqual(restored.get(self.a['id'])['result'],'Observed result')
        self.assertEqual(restored.get(self.b['id'])['status'],'cancelled')


class HandoffTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.c=Console(CONFIG,self.temp.name)
        self.c.device.connected=True
        self.c.device.release_touch=AsyncMock()
        self.c.agents['codex']={'name':'Codex','token':'client-token','seen':time.monotonic()}
        self.c.queue.add('Read settings','Read only','codex','Codex')
        self.c.queue.owner='agent'
        self.token=self.c.queue.claim('codex')['lease']

    async def asyncTearDown(self): self.temp.cleanup()

    async def test_takeover_blocks_new_calls_before_inflight_finishes(self):
        began,release=asyncio.Event(),asyncio.Event()
        async def slow(*args):
            began.set(); await release.wait(); return {'content':[]}
        self.c.device.backend=slow
        payload={'agent':'codex','agent_token':'client-token','lease':self.token,'action':'call','name':'mobile_take_screenshot','arguments':{}}
        call=asyncio.create_task(self.c.agent_request(payload))
        await began.wait()
        takeover=asyncio.create_task(self.c.transition_to('human','Human takeover'))
        await asyncio.sleep(0)
        self.assertEqual(self.c.queue.owner,'transition')
        with self.assertRaises(PermissionError): await self.c.agent_request(payload)
        release.set()
        with self.assertRaises(PermissionError): await call
        await takeover
        self.assertEqual(self.c.queue.owner,'human')
        self.assertEqual(self.c.device.observed_at,0)

    async def test_failure_invalidates_observation_without_retry(self):
        self.c.device.backend=AsyncMock(side_effect=RuntimeError('timeout'))
        self.c.device.observed_at=time.monotonic()
        with self.assertRaises(RuntimeError):
            await self.c.agent_request({'agent':'codex','agent_token':'client-token','lease':self.token,'action':'call','name':'mobile_press_button','arguments':{}})
        self.assertEqual(self.c.device.backend.await_count,1)
        self.assertEqual(self.c.device.observed_at,0)


class DeviceTests(unittest.IsolatedAsyncioTestCase):
    async def test_physical_off_is_not_confused_with_virtual_on(self):
        d=Device(CONFIG,'/unused'); d.connected=True
        async def shell(*args):
            return {'SurfaceFlinger':'Displays (2 entries)\nDisplay 4630946747577212034\n    connectionType=Internal\n    name=""\n    powerMode=Off\n\nVirtual Display 1234\n    name="scrcpy"\n    powerMode=On\n','battery':'  level: 80\n  temperature: 250\n','power':'mWakefulness=Awake'}.get(args[-1],'0')
        d.shell=shell
        result=await d.sample()
        self.assertEqual(result['panel'],'off');self.assertEqual(result['temperature'],25)

    async def test_missing_telemetry_is_unknown_not_zero(self):
        d=Device(CONFIG,'/unused');d.connected=True;d.shell=AsyncMock(return_value='')
        result=await d.sample()
        self.assertIsNone(result['battery']);self.assertIsNone(result['temperature']);self.assertEqual(result['panel'],'unknown')

    async def test_reject_ref_and_wrong_device_before_backend_start(self):
        d=Device(CONFIG,'/unused');d.connected=True;d.lockfile=True
        with self.assertRaises(ValueError): await d.backend('mobile_click_on_screen_at_coordinates',{'ref':'@e40'})
        with self.assertRaises(PermissionError): await d.backend('mobile_take_screenshot',{'device':'other-device'})
        with self.assertRaises(ValueError): await d.backend('mobile_type_keys',{'text':'hello','submit':True})

    async def test_stale_dimensions_cannot_inject_touch(self):
        d=Device(CONFIG,'/unused');d.width,d.height=720,1600;d.send=AsyncMock()
        with self.assertRaises(ValueError): await d.touch(0,10,10,1600,720)
        d.send.assert_not_called()


class SecurityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.c=Console(CONFIG,self.temp.name)
        app=web.Application(middlewares=[secure]);app['console']=self.c
        app.router.add_get('/api/state',state);app.router.add_post('/api/agent',agent)
        self.client=TestClient(TestServer(app));await self.client.start_server()
        self.c.origin=str(self.client.make_url('/')).rstrip('/')

    async def asyncTearDown(self): await self.client.close();self.temp.cleanup()

    async def test_external_origin_rejected_even_with_token(self):
        response=await self.client.get('/api/state',headers={'X-Phone-Token':self.c.token,'Origin':'https://untrusted.example'})
        self.assertEqual(response.status,403)

    async def test_no_token_and_wrong_host_rejected(self):
        self.assertEqual((await self.client.get('/api/state')).status,403)
        response=await self.client.get('/api/state',headers={'X-Phone-Token':self.c.token,'Host':'untrusted.example'})
        self.assertEqual(response.status,403)

    async def test_registered_agent_cannot_impersonate_another(self):
        headers={'X-Phone-Token':self.c.token}
        response=await self.client.post('/api/agent',headers=headers,json={'action':'register','agent':'codex'})
        identity=await response.json()
        response=await self.client.post('/api/agent',headers=headers,json={**identity,'agent':'claude','action':'submit','title':'No','instruction':'No'})
        self.assertEqual(response.status,409)
        self.assertEqual(self.c.queue.data['tasks'],[])

    async def test_observation_error_does_not_lose_adapter_lease(self):
        import aiohttp
        c=Client(self.temp.name,'codex','Codex')
        c.endpoint={'url':self.c.origin,'token':self.c.token}
        c.lease='active-lease'
        async with aiohttp.ClientSession() as session:
            c.session=session
            with self.assertRaises(RuntimeError): await c.post({'action':'call','agent':'missing'})
        self.assertEqual(c.lease,'active-lease')


if __name__=='__main__': unittest.main()
