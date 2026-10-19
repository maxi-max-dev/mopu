import unittest,time,json
from unittest.mock import AsyncMock
import test_receipts as fixtures
import test_steps as steps
from mopu.targets import resolve_target,validate_target

class TargetParsingTests(unittest.TestCase):
    def test_exact_label_not_similar_downloads(self):
        c=[{'type':'text','text':'@e1 Button label="下载" id="one" at=20,40 size=100x60\n@e2 TextView text="下载内容" at=20,200 size=100x60'}]
        self.assertEqual(resolve_target(c,{'label':'下载'}),({'x':70,'y':70},'target_matched'))
    def test_missing_duplicate_disabled_and_zero_bounds_do_not_click(self):
        base='@e1 Button text="打开" at=20,40 size=100x60'
        for text,reason in [('', 'target_missing'),(base+'\n'+base,'target_ambiguous'),(base+' disabled','target_unavailable'),(base+' [disabled]','target_unavailable'),(base.replace('at=20,40','at=-10,40'),'target_unavailable'),(base.replace('100x60','0x60'),'target_unavailable')]:
            self.assertEqual(resolve_target([{'type':'text','text':text}],{'text':'打开'})[1],reason)
    def test_all_fields_match_and_escaped_text(self):
        text='@e1 Button text='+json.dumps('a"b')+' id="file" at=10,20 size=80x40'
        self.assertEqual(resolve_target([{'type':'text','text':text}],{'id':'file','text':'a"b','type':'Button'})[1],'target_matched')
    def test_metadata_inside_visible_text_cannot_retarget_click(self):
        caption='not disabled; at=999,999 size=100x100; id="fake"'
        line='@e1 Button text='+json.dumps(caption)+' id="real" at=10,20 size=80x40'
        self.assertEqual(resolve_target([{'type':'text','text':line}],{'id':'real'}),({'x':50,'y':40},'target_matched'))
        self.assertEqual(resolve_target([{'type':'text','text':line}],{'id':'fake'})[1],'target_missing')

    def test_selector_rejects_weak_or_unknown_fields(self):
        for target in [{},{'type':'Button'},{'text':''},{'index':1},{'text':3}]:
            with self.assertRaises(ValueError):validate_target(target)

class TargetDispatchTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.EndToEndContractTests.asyncSetUp
    asyncTearDown=fixtures.EndToEndContractTests.asyncTearDown
    call=fixtures.EndToEndContractTests.call
    source=steps.StepTests.source
    step=steps.StepTests.step
    async def setup(self,tree):
        async def backend(name,*args):
            self.c.device.observed_at=time.monotonic();self.c.device.observed_generation=self.c.queue.generation
            return {'content':[{'type':'text','text':tree if name=='mobile_list_elements_on_screen' else 'ack'}]}
        self.c.device.backend=AsyncMock(side_effect=backend)
    async def test_relocates_before_input_using_current_bounds(self):
        await self.setup('@e1 Button text="打开" at=100,200 size=40x60')
        await self.step(arguments={},target={'text':'打开'},expected_text=None)
        calls=self.c.device.backend.await_args_list
        self.assertEqual(calls[0].args[0],'mobile_list_elements_on_screen')
        self.assertEqual(calls[1].args[1],{'x':120,'y':230});self.assertEqual(len(calls),3)
    async def test_disappeared_target_returns_new_observation_without_input(self):
        await self.setup('@e1 TextView text="预览" at=10,20 size=40x60')
        r=await self.step(arguments={},target={'text':'打开'},expected_text=None)
        self.assertTrue(r['isError']);self.assertIn('target_missing',json.dumps(r));self.assertIn('phone_harness_observation',json.dumps(r))
        self.assertEqual(self.c.device.backend.await_count,1)
    async def test_coordinate_conflict_is_rejected_before_read(self):
        await self.setup('')
        with self.assertRaises(ValueError):await self.step(target={'text':'打开'})
        self.c.device.backend.assert_not_called()
    async def test_takeover_during_preflight_prevents_input(self):
        async def backend(*args):self.c.queue.invalidate('takeover');self.c.queue.owner='human';return {'content':[]}
        self.c.device.backend=AsyncMock(side_effect=backend)
        with self.assertRaises(PermissionError):await self.step(arguments={},target={'text':'打开'})
        self.assertEqual(self.c.device.backend.await_count,1)
