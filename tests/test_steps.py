import json,struct,time,unittest
from unittest.mock import AsyncMock,patch
import test_receipts as receipts
import test_agent_swipe as swipes

class StepTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=receipts.EndToEndContractTests.asyncSetUp
    asyncTearDown=receipts.EndToEndContractTests.asyncTearDown
    call=receipts.EndToEndContractTests.call
    async def source(self):return self.c.observations.record(self.task['id'],self.c.queue.generation,'mobile_take_screenshot')['id']
    async def step(self,**kw):
        args={'name':'mobile_click_on_screen_at_coordinates','arguments':{'x':10,'y':20},'observation_id':await self.source(),'progress':'At page','next_action':'Click','expected_text':'460'};args.update(kw)
        return await self.call('step',**args)
    async def setup_backend(self,text='460'):
        async def backend(name,*args):
            if name=='mobile_list_elements_on_screen':
                self.c.device.observed_at=time.monotonic();self.c.device.observed_generation=self.c.queue.generation
                return {'content':[{'type':'text','text':text}]}
            return {'content':[{'type':'text','text':'dispatched'}]}
        self.c.device.backend=AsyncMock(side_effect=backend)
    async def test_step_returns_fresh_evidence_and_diagnostic_not_done(self):
        await self.setup_backend();r=await self.step()
        self.assertIn('phone_harness_observation',json.dumps(r));self.assertIn('text_present',json.dumps(r))
        self.assertEqual(self.c.queue.get(self.task['id'])['status'],'running');self.assertEqual(self.c.device.backend.await_count,2)
    async def test_missing_expected_state_never_replays(self):
        await self.setup_backend('0');r=await self.step();self.assertIn('text_not_found',json.dumps(r));self.assertEqual(self.c.device.backend.await_count,2)
    async def test_non_screen_or_invalid_reference_stops_before_dispatch(self):
        await self.setup_backend()
        for ref in ['fake',self.c.observations.record(self.task['id'],self.c.queue.generation,'mobile_list_apps')['id']]:
            with self.assertRaises(ValueError):await self.step(observation_id=ref)
        self.c.device.backend.assert_not_called()
    async def test_screenshot_returns_image_blocks(self):
        self.c.device.backend=AsyncMock(side_effect=[{'content':[]},{'content':[{'type':'image','data':'abc','mimeType':'image/png'}]}])
        r=await self.step(observe='screenshot',expected_text=None);self.assertEqual(r['content'][0]['type'],'image')
    async def test_failed_mutation_is_not_replayed_or_read_as_success(self):
        self.c.device.backend=AsyncMock(return_value={'isError':True,'content':[{'type':'text','text':'failed'}]})
        r=await self.step();self.assertTrue(r['isError']);self.assertEqual(self.c.device.backend.await_count,1)
    async def test_takeover_after_dispatch_prevents_followup_read(self):
        async def backend(*args):self.c.queue.invalidate('takeover');self.c.queue.owner='human';return {'content':[]}
        self.c.device.backend=AsyncMock(side_effect=backend)
        with self.assertRaises(PermissionError):await self.step()
        self.assertEqual(self.c.device.backend.await_count,1)

    async def test_lazy_screenshot_waits_once_without_replaying_input(self):
        self.c.device.backend=AsyncMock(side_effect=[{'content':[]},{'content':[{'type':'image','data':'abc','mimeType':'image/png'}]}])
        with patch('mopu.app.asyncio.sleep',new_callable=AsyncMock) as sleep:
            r=await self.step(observe='screenshot',expected_text=None,settle_ms=3000)
        sleep.assert_awaited_once_with(3.0)
        self.assertEqual(self.c.device.backend.await_count,2)
        self.assertIn('"settle_ms": 3000',json.dumps(r).replace('\\"','"'))

    async def test_invalid_settle_delay_rejected_before_input(self):
        await self.setup_backend()
        for delay in [True,0,399,5001,1.5,'1000',None]:
            with self.assertRaises(ValueError):await self.step(settle_ms=delay)
        self.c.device.backend.assert_not_called()

    async def test_takeover_during_settle_prevents_read_and_replay(self):
        await self.setup_backend()
        async def takeover(_):
            self.c.queue.invalidate('takeover');self.c.queue.owner='human'
        with patch('mopu.app.asyncio.sleep',side_effect=takeover):
            with self.assertRaisesRegex(RuntimeError,'禁止重放'):
                await self.step(settle_ms=5000)
        self.assertEqual(self.c.device.backend.await_count,1)

class PasteTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=swipes.SwipeTests.asyncSetUp
    asyncTearDown=swipes.SwipeTests.asyncTearDown
    async def test_unicode_paste_packet_has_no_submit_or_text_echo(self):
        with patch('mopu.device.asyncio.create_subprocess_exec',new_callable=AsyncMock) as proc:
            r=await self.d.backend('mobile_type_keys',{'text':'中文\n460'},4,lambda:None);proc.assert_not_called()
        data=self.d.send.await_args.args[0];self.assertEqual(struct.unpack('>BQBI',data[:14]),(9,0,1,len('中文\n460'.encode())))
        self.assertEqual(data[14:],'中文\n460'.encode());self.assertNotIn('中文',json.dumps(r));self.assertEqual(self.d.observed_at,0)
    async def test_paste_takeover_rejected_before_send(self):
        def guard():raise PermissionError('taken')
        with self.assertRaises(PermissionError):await self.d.backend('mobile_type_keys',{'text':'test'},4,guard)
        self.d.send.assert_not_called()
    async def test_paste_failure_never_replays(self):
        self.d.send.side_effect=TimeoutError()
        with self.assertRaises(TimeoutError):await self.d.backend('mobile_type_keys',{'text':'test'},4,lambda:None)
        self.assertEqual(self.d.send.await_count,1)
