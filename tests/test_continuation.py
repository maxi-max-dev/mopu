"""Offline synthetic tasks only: never load production queue or device config."""
import asyncio
import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from mopu.tasks import Queue
from mopu.app import Console
from mopu.mcp import TOOLS
from test_control import CONFIG


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.q=Queue(Path(self.tmp.name)/'queue.json')
        self.task=self.q.get(self.q.add('Synthetic campaign','No real sends','a','A')['id'])
        self.task.update(status='blocked',steps=200,prior_steps=1136,checkpoint='23 confirmed; 127 remaining',receipt={'old':'keep'},milestones=[{'old':'keep'}])
        self.q.owner='human';self.q.save()
    def tearDown(self):self.tmp.cleanup()
    def approval(self,**kw):
        return {'id':self.task['id'],'expected_generation':self.q.generation,'review_version':self.q.review_version(self.task),
                'checked_progress':True,'checked_uncertainty':True,'scope':'Synthetic next 3 recipients; stop on uncertainty',
                'review_note':'Checked 23 historical records and last action','budget':20,'max_deliveries':3,**kw}
    def approve(self,**kw):return self.q.approve_continuation(self.approval(**kw))
    def test_approval_preserves_monotonic_history_and_does_not_claim(self):
        before=copy.deepcopy(self.task);r=self.approve()
        for key in ('steps','prior_steps','checkpoint','receipt','milestones'):self.assertEqual(self.task[key],before[key])
        self.assertEqual(r['ceiling'],1356);self.assertEqual(self.q.owner,'human');self.assertIsNone(self.q.lease)
        self.assertEqual(self.q.review_summary(self.task)['remaining_calls'],20)
    def test_stale_task_or_generation_rejected(self):
        data=self.approval();self.task['checkpoint']='changed'
        with self.assertRaises(PermissionError):self.q.approve_continuation(data)
        with self.assertRaises(PermissionError):self.approve(expected_generation=-1)
    def test_unchecked_overlarge_and_invalid_approval_rejected(self):
        for kw in [{'checked_progress':False},{'checked_uncertainty':False},{'budget':201},{'budget':True},{'budget':1},{'max_deliveries':21},{'scope':''},{'review_note':''}]:
            with self.assertRaises(ValueError):self.approve(**kw)
        self.assertNotIn('reviews',self.task)
    def test_agent_ownership_cannot_approve(self):
        self.q.owner='agent'
        with self.assertRaises(PermissionError):self.approve()
    def test_approval_cannot_be_replayed_or_stacked(self):
        data=self.approval();self.q.approve_continuation(data)
        with self.assertRaises((ValueError,PermissionError)):self.q.approve_continuation(data)
        self.task['status']='paused'
        with self.assertRaises(PermissionError):self.approve()
        self.assertEqual(len(self.task['reviews']),1)
    def test_expired_approval_never_claimed(self):
        self.approve();self.task['reviews'][-1]['expires_at']=0;self.q.owner='agent'
        self.assertIsNone(self.q.claim('a'));self.assertEqual(self.task['stop_reason'],'needs_review')
    def test_restart_revokes_approval_without_losing_history(self):
        self.approve();self.q.owner='agent';self.q.claim('a');self.task['steps']+=3;self.q.save()
        q=Queue(self.q.path);t=q.get(self.task['id'])
        self.assertEqual(q.total(t),1339);self.assertEqual(t['reviews'][0]['state'],'closed')
        self.assertEqual(t['status'],'blocked');self.assertIsNone(q.lease)
    def test_cancel_does_not_allow_duplicate_budget_escape(self):
        with self.assertRaises(PermissionError):self.q.cancel(self.task['id'])
        with self.assertRaises(PermissionError):self.q.add('New','Same work','a','A')
    def test_other_preexisting_task_cannot_be_claimed_around_hold(self):
        self.q.data['tasks'].append({'id':'other','agent':'a','status':'queued','steps':0,'wait_reason':''})
        self.q.owner='agent';self.assertIsNone(self.q.claim('a'))
    def test_next_review_adds_bounded_stage_without_reset(self):
        self.approve(budget=2);self.q.owner='agent';self.q.claim('a');self.task['steps']+=2
        with self.assertRaises(PermissionError):self.q.ensure_budget(self.task,1)
        self.q.owner='human';self.approve(budget=4)
        self.assertEqual(self.q.total(self.task),1338);self.assertEqual(len(self.task['reviews']),2)
        self.assertEqual(self.task['reviews'][1]['ceiling'],1342)
    def test_partial_budget_is_not_carried_over(self):
        self.approve(budget=200);self.q.owner='agent';self.q.claim('a');self.task['steps']+=1
        self.q.revoke_continuations('human takeover');self.q.owner='human';self.approve(budget=10)
        self.assertEqual(self.q.review_summary(self.task)['remaining_calls'],10)


class BrokerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.c=Console(CONFIG,self.tmp.name);self.q=self.c.queue
        self.c.device.connected=True;self.c.device.clear_actions=AsyncMock();self.c.device.release_touch=AsyncMock()
        self.c.agents['a']={'name':'A','token':'secret','seen':time.monotonic()}
        self.task=self.q.get(self.q.add('Synthetic only','No real phone','a','A')['id'])
        self.task.update(status='blocked',steps=200);self.q.owner='human'
        await self.approve()
        self.q.owner='agent';self.lease=self.q.claim('a')['lease']
        async def backend(name,*args):
            if name in ('mobile_take_screenshot','mobile_list_elements_on_screen'):
                self.c.device.observed_at=time.monotonic();self.c.device.observed_generation=self.q.generation
            return {'content':[{'type':'text','text':'Synthetic delivered screen'}]}
        self.c.device.backend=AsyncMock(side_effect=backend)
    async def asyncTearDown(self):self.tmp.cleanup()
    async def approve(self,**kw):
        return await self.c.control({'action':'review_approve','id':self.task['id'],'expected_generation':self.q.generation,
            'review_version':self.q.review_version(self.task),'checked_progress':True,'checked_uncertainty':True,
            'scope':'Synthetic 2 recipients only','review_note':'Checked last action','budget':20,'max_deliveries':2,**kw})
    async def call(self,action,**kw):
        return await self.c.agent_request({'agent':'a','agent_token':'secret','lease':self.lease,'action':action,**kw})
    def source(self):return self.c.observations.record(self.task['id'],self.q.generation,'mobile_take_screenshot')['id']
    def checks(self,obs=None):return [{'criterion':'Target conversation shows sent message delivered','observed':'Synthetic recipient / delivered', 'observation_id':obs or self.source(),'passed':True}]
    async def step(self,**kw):
        with patch('mopu.app.asyncio.sleep',new_callable=AsyncMock):
            return await self.call('step',name='mobile_click_on_screen_at_coordinates',arguments={'x':1,'y':2},observation_id=self.source(),progress='Synthetic progress',next_action='Synthetic click',input_kind='navigation',**kw)
    async def send(self,key='recipient-1'):
        with patch('mopu.app.asyncio.sleep',new_callable=AsyncMock):
            return await self.call('step',name='mobile_click_on_screen_at_coordinates',arguments={'x':1,'y':2},observation_id=self.source(),progress='Synthetic progress',next_action='Synthetic send',input_kind='send',delivery_key=key)
    async def test_budget_preflight_blocks_before_any_dispatch(self):
        self.task['steps']=219
        with self.assertRaises(PermissionError):await self.step()
        self.c.device.backend.assert_not_called();self.assertEqual(self.task['steps'],219)
        self.assertEqual(self.task['stop_reason'],'needs_review');self.assertIsNone(self.q.lease)
    async def test_exact_target_reserves_three_calls(self):
        self.task['steps']=218
        with self.assertRaises(PermissionError):
            await self.call('step',name='mobile_click_on_screen_at_coordinates',target={'text':'send'},observation_id=self.source(),progress='x',next_action='x',input_kind='send',delivery_key='recipient-1')
        self.c.device.backend.assert_not_called()
    async def test_read_attempts_reserve_maximum_before_input(self):
        self.task['steps']=217
        with self.assertRaises(PermissionError):await self.step(read_attempts=3,expected_text='delivered')
        self.c.device.backend.assert_not_called()
    async def test_exact_remaining_budget_allows_send_readback_and_receipt(self):
        self.task['steps']=218
        result=await self.send();obs=json.loads(result['content'][-2]['text'])['phone_harness_observation']['id']
        item=await self.call('delivery_confirm',key='recipient-1',outcome='delivered',checks=self.checks(obs))
        self.assertEqual(item['outcome'],'delivered');self.assertEqual(self.task['steps'],220)
        with self.assertRaises(PermissionError):await self.call('call',name='mobile_take_screenshot')
    async def test_pending_send_blocks_input_but_allows_observation(self):
        await self.send()
        with self.assertRaises(PermissionError):await self.step()
        count=self.c.device.backend.await_count
        await self.call('call',name='mobile_take_screenshot')
        self.assertEqual(self.c.device.backend.await_count,count+1)
    async def test_duplicate_recipient_rejected_after_delivery(self):
        await self.send();await self.call('delivery_confirm',key='recipient-1',outcome='delivered',checks=self.checks())
        count=self.c.device.backend.await_count
        with self.assertRaises(PermissionError):await self.send()
        self.assertEqual(self.c.device.backend.await_count,count)
    async def test_uncertain_timeout_kept_and_not_counted(self):
        self.c.device.backend.side_effect=TimeoutError('synthetic timeout')
        with self.assertRaises(TimeoutError):await self.send()
        self.assertEqual(self.task['pending_delivery'],'recipient-1')
        self.assertEqual(self.q.review_summary(self.task)['verified_deliveries'],0)
        with self.assertRaises(PermissionError):await self.step()
        self.assertEqual(self.c.device.backend.await_count,1)
    async def test_pre_send_stale_foreign_and_non_screen_evidence_rejected(self):
        old=self.source();await self.send()
        foreign=self.c.observations.record('other',self.q.generation,'mobile_take_screenshot')['id']
        nonscreen=self.c.observations.record(self.task['id'],self.q.generation,'mobile_list_apps')['id']
        stale=self.source();self.c.observations.records[stale]['monotonic']-=121
        for ref in [old,foreign,nonscreen,stale]:
            with self.assertRaises(ValueError):await self.call('delivery_confirm',key='recipient-1',outcome='delivered',checks=self.checks(ref))
        self.assertEqual(self.task['pending_delivery'],'recipient-1')
    async def test_pending_send_prevents_verified_finish(self):
        await self.send();r=await self.call('finish',result='Synthetic only',checks=self.checks())
        self.assertEqual(r['status'],'unverified');self.assertTrue(r['receipt']['unresolved'])
    async def test_send_requires_explicit_intent_and_key(self):
        with self.assertRaises(ValueError):
            await self.call('step',name='mobile_press_button',arguments={'button':'BACK'},observation_id=self.source(),progress='x',next_action='x',input_kind='send')
        self.c.device.backend.assert_not_called()
    async def test_direct_input_and_file_budget_route_denied(self):
        for name in ['mobile_press_button','mobile_transfer_manifest']:
            with self.assertRaises(PermissionError):await self.call('call',name=name,arguments={})
        with self.assertRaises(PermissionError):await self.call('input_probe')
        self.c.device.backend.assert_not_called()
    async def test_takeover_revokes_stage_and_late_input_result(self):
        async def backend(*args):
            await self.c.transition_to('human','synthetic takeover')
            return {'content':[{'type':'text','text':'late'}]}
        # Simulate takeover invalidation without waiting on the in-flight op lock.
        async def takeover(*args):
            self.q.revoke_continuations('human takeover');self.q.invalidate('human');self.q.owner='human'
            return {'content':[]}
        self.c.device.backend.side_effect=takeover
        with self.assertRaises(PermissionError):await self.send()
        self.assertEqual(self.c.device.backend.await_count,1);self.assertEqual(self.task['reviews'][-1]['state'],'closed')
        self.assertEqual(self.task['pending_delivery'],'recipient-1')
    async def test_real_transition_revokes_and_old_control_grant_cannot_resume(self):
        await self.c.transition_to('human','synthetic takeover')
        with self.assertRaises(PermissionError):
            await self.call('request_control',task_id=self.task['id'],expected_generation=self.q.generation,authorization_id='new-user-authorization',user_authorization='continue')
        self.assertEqual(self.task['reviews'][-1]['state'],'closed')
    async def test_retry_and_new_task_cannot_clear_review(self):
        await self.c.transition_to('human','synthetic takeover')
        before=copy.deepcopy(self.task)
        with self.assertRaises(PermissionError):await self.c.control({'action':'retry','id':self.task['id']})
        with self.assertRaises(PermissionError):await self.call('submit',title='duplicate',instruction='duplicate')
        self.assertEqual(self.task,before)
    async def test_expiry_blocks_new_input_and_preserves_pending_send(self):
        await self.send();self.task['reviews'][-1]['expires_at']=0
        with self.assertRaises(PermissionError):await self.call('call',name='mobile_take_screenshot')
        self.assertEqual(self.task['pending_delivery'],'recipient-1')
    async def test_new_review_can_resolve_pending_with_fresh_evidence(self):
        await self.send();old=self.source();await self.c.transition_to('human','takeover')
        await self.approve();self.q.owner='agent';self.lease=self.q.claim('a')['lease']
        with self.assertRaises(ValueError):await self.call('delivery_confirm',key='recipient-1',outcome='delivered',checks=self.checks(old))
        await self.call('call',name='mobile_take_screenshot')
        await self.call('delivery_confirm',key='recipient-1',outcome='delivered',checks=self.checks())
        self.assertEqual(self.q.review_summary(self.task)['verified_deliveries'],1)
    async def test_zero_send_scope_rejects_send_before_backend(self):
        self.task['reviews'][-1]['max_deliveries']=0
        with self.assertRaises(PermissionError):await self.send('forbidden-outgoing')
        self.c.device.backend.assert_not_called()
        self.assertNotIn('pending_delivery',self.task)

    async def test_stage_recipient_limit_is_enforced(self):
        for i in range(2):
            key=f'recipient-{i}';await self.send(key);await self.call('delivery_confirm',key=key,outcome='not_sent',checks=self.checks())
        count=self.c.device.backend.await_count
        with self.assertRaises(PermissionError):await self.send('recipient-3')
        self.assertEqual(self.c.device.backend.await_count,count)
    async def test_review_action_is_not_an_agent_tool(self):
        self.assertNotIn('phone_review_approve',[t['name'] for t in TOOLS])
        with self.assertRaises(ValueError):await self.call('review_approve')


class ReviewHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient,TestServer
        from mopu.app import secure,control,agent
        self.tmp=tempfile.TemporaryDirectory();self.c=Console(CONFIG,self.tmp.name)
        self.c.device.connect=AsyncMock(side_effect=AssertionError('No device access allowed'))
        self.c.device.backend=AsyncMock(side_effect=AssertionError('No device access allowed'))
        self.c.agents['a']={'name':'A','token':'secret','seen':time.monotonic()}
        self.t=self.c.queue.get(self.c.queue.add('synthetic','synthetic','a','A')['id']);self.t.update(status='blocked',steps=200)
        self.c.queue.owner='human'
        app=web.Application(middlewares=[secure]);app['console']=self.c
        app.router.add_post('/api/control',control);app.router.add_post('/api/agent',agent)
        self.client=TestClient(TestServer(app));await self.client.start_server()
        self.c.origin=str(self.client.make_url('/')).rstrip('/')
    async def asyncTearDown(self):await self.client.close();self.tmp.cleanup()
    def body(self):return {'action':'review_approve','id':self.t['id'],'expected_generation':self.c.queue.generation,
        'review_version':self.c.queue.review_version(self.t),'scope':'synthetic next recipient','review_note':'synthetic checked',
        'budget':10,'max_deliveries':1,'checked_progress':True,'checked_uncertainty':True}
    async def test_requires_local_console_auth_and_origin(self):
        for headers in [{},{'X-Phone-Token':self.c.token,'Origin':'https://external.example'}]:
            r=await self.client.post('/api/control',json=self.body(),headers=headers);self.assertEqual(r.status,403)
        self.assertNotIn('reviews',self.t)
    async def test_review_success_and_replay_rejection_without_device(self):
        body=self.body();headers={'X-Phone-Token':self.c.token,'Origin':self.c.origin}
        r=await self.client.post('/api/control',json=body,headers=headers);self.assertEqual(r.status,200)
        state=await r.json();self.assertEqual(state['owner'],'human');self.assertFalse(state['lease_active'])
        r=await self.client.post('/api/control',json=body,headers=headers);self.assertEqual(r.status,409)
        self.c.device.connect.assert_not_awaited();self.c.device.backend.assert_not_awaited()
    async def test_agent_endpoint_cannot_approve(self):
        r=await self.client.post('/api/agent',headers={'X-Phone-Token':self.c.token},json={**self.body(),'agent':'a','agent_token':'secret'})
        self.assertEqual(r.status,409);self.assertNotIn('reviews',self.t)

class CampaignTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = BrokerTests.asyncSetUp
    asyncTearDown = BrokerTests.asyncTearDown
    approve = BrokerTests.approve
    call = BrokerTests.call
    source = BrokerTests.source
    checks = BrokerTests.checks
    send = BrokerTests.send

    async def test_150_synthetic_items_require_eight_human_reviews(self):
        self.task['reviews'][-1]['max_deliveries']=20
        self.task['reviews'][-1]['budget']=200
        self.task['reviews'][-1]['ceiling']=400
        for i in range(150):
            if i and i % 20 == 0:
                await self.c.transition_to('human','synthetic human review boundary')
                before=self.q.total(self.task)
                await self.approve(budget=200,max_deliveries=20)
                self.assertEqual(self.q.total(self.task),before)
                self.q.owner='agent';self.lease=self.q.claim('a')['lease']
            # Actual synthetic backend read, then send+read, then receipt.
            await self.call('call',name='mobile_take_screenshot')
            result=await self.send(f'synthetic-recipient-{i}')
            obs=json.loads(result['content'][-2]['text'])['phone_harness_observation']['id']
            await self.call('delivery_confirm',key=f'synthetic-recipient-{i}',outcome='delivered',checks=self.checks(obs))
        self.assertEqual(len(self.task['reviews']),8)
        self.assertEqual(self.q.total(self.task),650) # initial 200 + 150*(read + input + read)
        self.assertEqual(self.q.review_summary(self.task)['verified_deliveries'],150)
        result=await self.call('finish',result='150 synthetic deliveries; not real messages',checks=self.checks())
        self.assertEqual(result['status'],'done')
        # A verified completion must not permanently block unrelated future work.
        self.assertIsNotNone(self.q.add('New unrelated task','Synthetic new task','a','A'))

    async def test_expiry_between_input_and_readback_keeps_uncertainty(self):
        async def expired(_):self.task['reviews'][-1]['expires_at']=0
        with patch('mopu.app.asyncio.sleep',side_effect=expired):
            with self.assertRaisesRegex(RuntimeError,'禁止重放'):
                await self.call('step',name='mobile_click_on_screen_at_coordinates',arguments={'x':1,'y':2},observation_id=self.source(),progress='x',next_action='x',input_kind='send',delivery_key='synthetic-one')
        self.assertEqual(self.c.device.backend.await_count,1)
        self.assertEqual(self.task['pending_delivery'],'synthetic-one')
        self.assertEqual(self.task['stop_reason'],'needs_review')

class TakeoverRaceTests(CampaignTests):
    test_150_synthetic_items_require_eight_human_reviews = None
    test_expiry_between_input_and_readback_keeps_uncertainty = None

    async def test_takeover_during_inflight_send_invalidates_before_waiting_for_lock(self):
        dispatched=asyncio.Event();release=asyncio.Event()
        async def backend(*args):
            dispatched.set();await release.wait();return {'content':[]}
        self.c.device.backend.side_effect=backend
        send=asyncio.create_task(self.send())
        await asyncio.wait_for(dispatched.wait(),1)
        transitioning=asyncio.Event()
        self.c.device.clear_actions=AsyncMock(side_effect=transitioning.set)
        takeover=asyncio.create_task(self.c.transition_to('human','synthetic concurrent takeover'))
        await asyncio.wait_for(transitioning.wait(),1)
        self.assertIsNone(self.q.lease)
        self.assertEqual(self.task['reviews'][-1]['state'],'closed')
        release.set()
        with self.assertRaises(PermissionError):await send
        await asyncio.wait_for(takeover,1)
        self.assertEqual(self.q.owner,'human')
        self.assertEqual(self.c.device.backend.await_count,1)
        self.assertEqual(self.task['pending_delivery'],'recipient-1')

if __name__=='__main__':unittest.main()
