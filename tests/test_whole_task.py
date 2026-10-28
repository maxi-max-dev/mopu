import asyncio
import copy
import json
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch
from mopu.app import Console
from mopu.tasks import Queue
from test_control import CONFIG


class WholeTaskTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.c=Console(CONFIG,self.tmp.name);self.q=self.c.queue
        self.c.device.connected=True
        self.c.device.clear_actions=AsyncMock();self.c.device.release_touch=AsyncMock()
        self.c.agents['fresh-ai']={'name':'Fresh AI','token':'secret','seen':time.monotonic()}
        self.q.owner='human';self.lease=''
        async def backend(name,*args):
            if name is None:return {'tools':[]}
            if name in ('mobile_take_screenshot','mobile_list_elements_on_screen'):
                self.c.device.observed_at=time.monotonic();self.c.device.observed_generation=self.q.generation
            return {'content':[{'type':'text','text':'Synthetic recipient delivered'}]}
        self.c.device.backend=AsyncMock(side_effect=backend)
    async def asyncTearDown(self):self.tmp.cleanup()
    async def call(self,action,**kw):
        return await self.c.agent_request({'agent':'fresh-ai','agent_token':'secret','lease':self.lease,'action':action,**kw})
    def args(self,**kw):
        return dict(title='Synthetic acceptance',instruction='150 synthetic deliveries only',user_authorization='Run synthetic test; no real messages',authorization_id='synthetic-grant-001',max_calls=10000,max_deliveries=150,**kw)
    async def start(self,**kw):
        result=await self.call('start',**self.args(**kw));self.task=self.q.get(result['task_id'])
        self.lease=(await self.call('wait'))['lease'];return result
    def source(self):return self.c.observations.record(self.task['id'],self.q.generation,'mobile_take_screenshot')['id']
    def checks(self,obs):return [{'criterion':'Synthetic delivery','observed':'Synthetic delivered','observation_id':obs,'passed':True}]
    async def send(self,key):
        with patch('mopu.app.asyncio.sleep',new_callable=AsyncMock):
            result=await self.call('step',name='mobile_click_on_screen_at_coordinates',arguments={'x':1,'y':2},observation_id=self.source(),progress='Synthetic progress',next_action='Synthetic send',input_kind='send',delivery_key=key)
        return json.loads(result['content'][-2]['text'])['phone_harness_observation']['id']
    async def test_150_deliveries_one_grant_over_200_calls_without_console(self):
        old=self.q.add('Old stopped job','Do not resume','other','Other');self.q.get(old['id'])['status']='paused'
        before=copy.deepcopy(self.q.get(old['id']))
        await self.start()
        for i in range(150):
            # Several reads per candidate, plus one input/readback; >200 calls.
            for _ in range(3):await self.call('call',name='mobile_list_elements_on_screen')
            obs=await self.send(f'synthetic-{i}')
            await self.call('delivery_confirm',key=f'synthetic-{i}',outcome='delivered',checks=self.checks(obs))
            await self.call('heartbeat')
        self.assertEqual(self.task['steps'],750)
        self.assertEqual(len(self.task['reviews']),1)
        self.assertEqual(self.q.review_summary(self.task)['verified_deliveries'],150)
        with self.assertRaises(PermissionError):await self.send('over-limit')
        result=await self.call('finish',result='Synthetic acceptance only',checks=self.checks(obs))
        self.assertEqual(result['status'],'done');self.assertEqual(self.q.get(old['id']),before)
    async def test_takeover_revokes_and_replayed_start_does_not_reclaim(self):
        await self.start();await self.c.transition_to('human','user takeover')
        replay=await self.call('start',**self.args())
        self.assertTrue(replay['duplicate']);self.assertEqual(self.q.owner,'human');self.assertIsNone(self.q.lease)
        with self.assertRaises(PermissionError):await self.call('heartbeat')
    async def test_same_grant_different_scope_rejected(self):
        await self.start();args=self.args();args['max_calls']=20000
        with self.assertRaises(PermissionError):await self.call('start',**args)
        self.assertEqual(self.task['reviews'][0]['budget'],10000)
    async def test_no_send_authorization_rejected_before_input(self):
        args=self.args();args['max_deliveries']=0
        r=await self.call('start',**args);self.task=self.q.get(r['task_id']);self.lease=(await self.call('wait'))['lease']
        with self.assertRaises(PermissionError):await self.send('not-authorized')
        self.c.device.backend.assert_not_called()
    async def test_wait_response_recovery_and_natural_expiry_keep_same_task(self):
        await self.start();generation=self.q.generation
        self.assertEqual((await self.call('wait'))['lease'],self.lease)
        self.assertEqual(self.q.generation,generation)
        self.q.lease['expires']=0
        renewed=await self.call('wait');self.assertEqual(renewed['task']['id'],self.task['id'])
        self.assertNotEqual(renewed['lease'],self.lease);self.assertEqual(len(self.task['reviews']),1)
    async def test_restart_preserves_pending_and_revokes_grant(self):
        await self.start();await self.send('uncertain')
        q=Queue(self.q.path);t=q.get(self.task['id'])
        self.assertEqual(t['pending_delivery'],'uncertain');self.assertTrue(q.needs_review(t))
        self.assertIsNone(q.lease)
    async def test_heartbeat_and_catalog_are_free(self):
        await self.start();self.c.device.tools=AsyncMock(return_value=[])
        for _ in range(10):await self.call('heartbeat')
        await self.call('tools')
        self.assertEqual(self.task['steps'],0)
    async def test_invalid_grant_does_not_create_task(self):
        args=self.args();args['max_calls']=0
        with self.assertRaises(ValueError):await self.call('start',**args)
        self.assertEqual(self.q.data['tasks'],[])
    async def test_active_other_client_cannot_be_preempted(self):
        self.q.add('Other','Other task','other','Other');self.q.owner='agent';claim=self.q.claim('other')
        with self.assertRaises(PermissionError):await self.call('start',**self.args())
        self.assertEqual(self.q.lease['token'],claim['lease']);self.assertEqual(len(self.q.data['tasks']),1)
    async def test_regular_tasks_can_record_delivery(self):
        t=self.q.add('Legacy','Authorized legacy send','fresh-ai','Fresh AI');self.task=self.q.get(t['id'])
        self.q.owner='agent';self.lease=self.q.claim('fresh-ai')['lease']
        obs=await self.send('legacy-recipient')
        await self.call('delivery_confirm',key='legacy-recipient',outcome='delivered',checks=self.checks(obs))
        self.assertEqual(self.q.review_summary(self.task)['verified_deliveries'],1)

if __name__=='__main__':unittest.main()
