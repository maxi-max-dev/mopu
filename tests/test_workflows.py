import json,time,unittest
from unittest.mock import AsyncMock
import test_receipts as fixtures
import test_steps as steps

class MilestoneTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.EndToEndContractTests.asyncSetUp
    asyncTearDown=fixtures.EndToEndContractTests.asyncTearDown
    call=fixtures.EndToEndContractTests.call
    read=fixtures.EndToEndContractTests.read
    async def check(self):
        obs=await self.read()
        return {'criterion':'Source value','observed':'460','observation_id':obs['id'],'passed':True}
    async def test_stage_persists_but_does_not_replace_final_fresh_read(self):
        c=await self.check();await self.call('milestone',key='source',checks=[c])
        self.c.observations.invalidate(self.task['id'])
        with self.assertRaises(ValueError):await self.call('finish',result='done',checks=[c])
        r=await self.call('finish',result='done',required_milestones=['source'])
        self.assertEqual(r['status'],'unverified');self.assertEqual(len(r['receipt']['milestones']),1)
    async def test_missing_required_stage_prevents_completion(self):
        self.c.queue.get(self.task['id'])['required_milestones']=['source','saved']
        c=await self.check();await self.call('milestone',key='source',checks=[c])
        c=await self.check();r=await self.call('finish',result='done',checks=[c],required_milestones=[])
        self.assertEqual(r['status'],'unverified');self.assertIn('saved',r['receipt']['unresolved'][0])
    async def test_stage_and_final_complete_and_retry_preserves_history(self):
        c=await self.check();await self.call('milestone',key='source',checks=[c])
        self.c.observations.invalidate(self.task['id']);c=await self.check()
        r=await self.call('finish',result='done',checks=[c],required_milestones=['source'])
        self.assertEqual(r['status'],'done')
        self.c.queue.get(self.task['id'])['status']='unverified';await self.c.control({'action':'retry','id':self.task['id']})
        self.assertEqual(self.c.queue.get(self.task['id'])['milestones'],[]);self.assertEqual(self.c.queue.get(self.task['id'])['attempts'][0]['milestones'][0]['key'],'source')
    async def test_duplicate_ack_is_idempotent_but_revision_cannot_overwrite(self):
        c=await self.check();await self.call('milestone',key='source',checks=[c])
        self.assertTrue((await self.call('milestone',key='source',checks=[c]))['duplicate'])
        c=await self.check()
        with self.assertRaises(ValueError):await self.call('milestone',key='source',checks=[c])
        self.assertEqual(len(self.c.queue.get(self.task['id'])['milestones']),1)
    async def test_stale_or_failed_or_foreign_stage_is_rejected(self):
        c=await self.check();self.c.observations.invalidate(self.task['id'])
        with self.assertRaises(ValueError):await self.call('milestone',key='source',checks=[c])
        c=await self.check();c['passed']=False
        with self.assertRaises(ValueError):await self.call('milestone',key='source',checks=[c])
        self.c.queue.invalidate('takeover');self.c.queue.owner='human'
        with self.assertRaises(PermissionError):await self.call('milestone',key='source',checks=[c])
    async def test_submit_freezes_unique_requirements(self):
        with self.assertRaises(ValueError):await self.call('submit',title='x',instruction='x',required_milestones=['a','a'])
        t=await self.call('submit',title='x',instruction='x',required_milestones=['a','b'])
        self.assertEqual(t['required_milestones'],['a','b']);self.assertEqual(self.c.queue.get(t['id'])['required_milestones'],['a','b'])

class SettleTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.EndToEndContractTests.asyncSetUp
    asyncTearDown=fixtures.EndToEndContractTests.asyncTearDown
    call=fixtures.EndToEndContractTests.call
    source=steps.StepTests.source
    step=steps.StepTests.step
    async def test_loading_then_expected_uses_reads_only(self):
        texts=iter(['loading','460'])
        async def backend(name,*args):
            if name=='mobile_list_elements_on_screen':
                self.c.device.observed_at=time.monotonic();self.c.device.observed_generation=self.c.queue.generation
                return {'content':[{'type':'text','text':next(texts)}]}
            return {'content':[]}
        self.c.device.backend=AsyncMock(side_effect=backend)
        r=await self.step(read_attempts=3)
        self.assertIn('text_present',json.dumps(r));self.assertEqual(self.c.device.backend.await_count,3)
        self.assertEqual(sum(c.args[0]=='mobile_click_on_screen_at_coordinates' for c in self.c.device.backend.await_args_list),1)
    async def test_missing_condition_stops_at_bound_and_no_input_replay(self):
        await steps.StepTests.setup_backend(self,'loading');r=await self.step(read_attempts=3)
        self.assertIn('text_not_found',json.dumps(r));self.assertEqual(self.c.device.backend.await_count,4)
    async def test_invalid_wait_contract_stops_before_dispatch(self):
        self.c.device.backend=AsyncMock()
        for kwargs in ({'read_attempts':4},{'read_attempts':True},{'read_attempts':2,'expected_text':None}):
            with self.assertRaises(ValueError):await self.step(**kwargs)
        self.c.device.backend.assert_not_called()
