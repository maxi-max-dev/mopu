import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
from mopu.app import Console
from mopu.contracts import Observations, explanation
from mopu.capabilities import catalog
from mopu.device import ALLOWED
from mopu.mcp import TOOLS
from test_control import CONFIG


class ReceiptTests(unittest.TestCase):
    def setUp(self): self.o = Observations()
    def item(self, obs, passed=True):
        return {'criterion':'Foreground is Settings','observed':'com.android.settings', 'observation_id':obs['id'],'passed':passed}
    def test_no_evidence_is_not_verified(self):
        self.assertEqual(self.o.receipt('t',1,None,None)['verification'],'unverified')
    def test_broker_reference_not_arbitrary_string(self):
        with self.assertRaises(ValueError): self.o.receipt('t',1,[self.item({'id':'made-up'})],[])
    def test_other_task_and_reacquired_lease_rejected(self):
        obs=self.o.record('t',1,'mobile_get_foreground_app')
        for task,gen in [('other',1),('t',2)]:
            with self.assertRaises(ValueError): self.o.receipt(task,gen,[self.item(obs)],[])
    def test_stale_and_pre_mutation_evidence_rejected(self):
        old=self.o.record('t',1,'mobile_get_foreground_app')
        self.o.records[old['id']]['monotonic']-=121
        with self.assertRaises(ValueError): self.o.receipt('t',1,[self.item(old)],[])
        fresh=self.o.record('t',1,'mobile_get_foreground_app');self.o.invalidate('t')
        with self.assertRaises(ValueError): self.o.receipt('t',1,[self.item(fresh)],[])
    def test_readback_after_input_can_verify_without_storing_screen(self):
        self.o.invalidate('t');obs=self.o.record('t',1,'mobile_get_foreground_app')
        receipt=self.o.receipt('t',1,[self.item(obs)],[])
        self.assertEqual(receipt['verification'],'assistant_verified')
        self.assertNotIn('monotonic',receipt['checks'][0])
        self.assertEqual(set(self.o.records[obs['id']]),{'id','task_id','generation','tool','observed_at','monotonic'})
    def test_failed_or_unresolved_checks_never_verify(self):
        obs=self.o.record('t',1,'mobile_get_foreground_app')
        for checks,unresolved,blocked in [([self.item(obs,False)],[],False),([self.item(obs)],['Unknown'],False),([self.item(obs)],[],True)]:
            self.assertEqual(self.o.receipt('t',1,checks,unresolved,blocked)['verification'],'unverified')
    def test_invalid_payload_rejected(self):
        for checks,issues in [('yes',[]),([], 'none'),([{}],[]),([], [None])]:
            with self.assertRaises(ValueError):self.o.receipt('t',1,checks,issues)


class EndToEndContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.c=Console(CONFIG,self.temp.name)
        self.c.device.connected=True;self.c.agents['a']={'name':'Assistant','token':'secret','seen':time.monotonic()}
        self.task=self.c.queue.add('Read foreground','Verify Settings','a','Assistant');self.c.queue.owner='agent'
        self.lease=self.c.queue.claim('a')['lease']
    async def asyncTearDown(self):self.temp.cleanup()
    async def call(self,action,**kwargs):
        return await self.c.agent_request({'agent':'a','agent_token':'secret','lease':self.lease,'action':action,**kwargs})
    async def read(self):
        self.c.device.backend=AsyncMock(return_value={'content':[{'type':'text','text':'com.android.settings'}]})
        result=await self.call('call',name='mobile_get_foreground_app',arguments={})
        return json.loads(result['content'][-1]['text'])['phone_harness_observation']
    async def test_missing_tool_name_never_dispatches_or_invalidates_evidence(self):
        obs=await self.read();backend=self.c.device.backend;backend.reset_mock()
        with self.assertRaises(ValueError):await self.call('call',tool='mobile_take_screenshot',arguments={})
        backend.assert_not_called()
        self.assertEqual(self.c.observations.receipt(self.task['id'],self.c.queue.generation,[{'criterion':'Settings','observed':'com.android.settings','observation_id':obs['id'],'passed':True}],[])['verification'],'assistant_verified')
    async def test_result_text_only_remains_unverified_and_releases_queue(self):
        result=await self.call('finish',result='Done')
        self.assertEqual(result['status'],'unverified');self.assertIsNone(self.c.queue.lease)
        self.assertIsNone(self.c.queue.head())
    async def test_read_finish_persist_retry_preserves_history(self):
        obs=await self.read()
        result=await self.call('finish',result='Checked foreground',checks=[{'criterion':'Settings','observed':'com.android.settings','observation_id':obs['id'],'passed':True}])
        self.assertEqual(result['status'],'done')
        stored=json.loads((Path(self.temp.name)/'queue.json').read_text())['tasks'][0]
        self.assertEqual(stored['receipt']['checks'][0]['observation_id'],obs['id'])
    async def test_uncertain_mutation_invalidates_read_receipt(self):
        obs=await self.read();self.c.device.backend=AsyncMock(side_effect=TimeoutError())
        with self.assertRaises(TimeoutError):await self.call('call',name='mobile_press_button',arguments={'button':'HOME'})
        with self.assertRaises(ValueError):await self.call('finish',result='Wrong',checks=[{'criterion':'Settings','observed':'com.android.settings','observation_id':obs['id'],'passed':True}])
        self.assertEqual(self.c.queue.get(self.task['id'])['status'],'running')
    async def test_empty_screen_and_error_cannot_supply_receipt_id(self):
        for output in [{'content':[]},{'isError':True,'content':[{'type':'text','text':'failed'}]},{'content':[{'type':'text','text':'Found these elements on screen: []'}]}]:
            self.c.device.backend=AsyncMock(return_value=output)
            result=await self.call('call',name='mobile_list_elements_on_screen',arguments={})
            self.assertNotIn('phone_harness_observation',json.dumps(result))
    async def test_retry_keeps_prior_result_and_clears_wait(self):
        await self.call('checkpoint',progress='At lock screen',next_action='Swipe or owner authentication',wait_reason='user_unlock')
        await self.call('finish',result='Locked',blocked=True)
        self.assertEqual(self.c.snapshot()['tasks'][0]['wait']['next_action'],'Swipe or owner authentication')
        state=await self.c.control({'action':'retry','id':self.task['id']})
        t=state['tasks'][0];self.assertEqual(t['wait_reason'],'');self.assertEqual(t['attempts'][0]['result'],'Locked')
    async def test_declared_wait_prevents_automatic_reclaim(self):
        await self.call('checkpoint',progress='Prepared',next_action='Choose option',wait_reason='user_decision')
        self.c.queue.lease['expires']=time.monotonic()-1;self.c.queue.expire()
        self.assertIsNone(self.c.queue.claim('a'))
    async def test_catalog_is_device_confirmed_only_after_tools(self):
        self.assertTrue(all(x['availability']=='unconfirmed' for x in self.c.snapshot()['capabilities']['items']))
        self.c.device.backend=AsyncMock(return_value={'tools':[{'name':'mobile_launch_app'}]})
        result=await self.call('tools');items={x['name']:x for x in result['capabilities']['items']}
        self.assertEqual(items['mobile_launch_app']['availability'],'provided')
        self.assertEqual(items['mobile_take_screenshot']['availability'],'unavailable')
        self.c.disconnected();self.assertTrue(all(x['availability']=='unconfirmed' for x in self.c.snapshot()['capabilities']['items']))


class WaitingAndSchemaTests(unittest.TestCase):
    def test_reason_has_action_and_does_not_claim_model_running(self):
        t={'id':'a','status':'queued','action':'Waiting'}
        cases=[('agent',False,'a',True,'device_offline'),('human',True,'a',True,'human_control'),('agent',True,'b',True,'queue'),('agent',True,'a',False,'agent_inactive'),('agent',True,'a',True,'ready')]
        for owner,connected,head,online,expected in cases:
            value=explanation(t,owner,connected,head,online);self.assertEqual(value['code'],expected);self.assertTrue(value['next_action'])
    def test_catalog_matches_execution_allowlist_and_distinguishes_routes(self):
        items={x['name']:x for x in catalog(True,'human',set(ALLOWED))['items']}
        self.assertEqual(set(items),ALLOWED | __import__('mopu.transfers',fromlist=['NAMES']).NAMES);self.assertEqual(items['mobile_launch_app']['route'],'direct')
        self.assertEqual(items['mobile_swipe_on_screen']['route'],'ui');self.assertFalse(any(x['ready_for_lease'] for x in items.values()))
    def test_openclaw_and_stdio_schemas_stay_identical(self):
        source=Path(__file__).resolve().parents[1]/'integrations/openclaw/tools.json'
        self.assertEqual(json.loads(source.read_text()),TOOLS)
