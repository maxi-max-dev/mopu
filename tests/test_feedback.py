import asyncio
import json
import time
import unittest
from unittest.mock import AsyncMock, patch
from mopu.device import Device
from mopu.feedback import describe, screen_size

TAP='mobile_click_on_screen_at_coordinates'
CONFIG={'serial':'test','adb':'/test/adb','backend_command':['/test/backend']}

class GeometryTests(unittest.TestCase):
    def test_scaled_portrait_and_landscape(self):
        self.assertEqual(describe(TAP,{'x':540,'y':1200},(1080,2400),(720,1600))['points'],[[.5,.5]])
        self.assertEqual(describe(TAP,{'x':1800,'y':540},(1080,2400),(1600,720))['points'],[[.75,.5]])
        self.assertEqual(screen_size('Physical size: 1080x2400\nOverride size: 900x2000'),(900,2000))

    def test_unknown_mismatch_or_invalid_coordinate_is_label_only(self):
        for size,video,args in [(None,(720,1600),{'x':10,'y':10}),((1080,2400),(800,800),{'x':10,'y':10}),
             ((1080,2400),(720,1600),{'x':float('nan'),'y':10}),((1080,2400),(720,1600),{'x':4000,'y':10})]:
            self.assertEqual(describe(TAP,args,size,video)['points'],[])

    def test_swipe_matches_pinned_backend_defaults_and_clipping(self):
        swipe='mobile_swipe_on_screen'
        self.assertEqual(describe(swipe,{'direction':'up'},(1080,2400),(720,1600))['points'],[[.5,.8],[.5,.2]])
        self.assertEqual(describe(swipe,{'direction':'left','x':100,'y':1200,'distance':500},(1080,2400),(720,1600))['points'],[[round(100/1080,6),.5],[0.,.5]])
        # Default MCP swipe uses natural orientation: do not pretend its out-of-bounds path fits landscape.
        self.assertEqual(describe(swipe,{'direction':'up'},(1080,2400),(1600,720))['points'],[])

    def test_private_payload_never_in_feedback(self):
        for name,args in [('mobile_type_keys',{'text':'private-password'}),('mobile_open_url',{'url':'https://private.example/token'}),('mobile_launch_app',{'packageName':'private.app'})]:
            cue=describe(name,args);self.assertEqual(cue['points'],[]);self.assertNotIn('private',json.dumps(cue))
        self.assertIsNone(describe('mobile_take_screenshot',{}))

class FeedbackTests(unittest.IsolatedAsyncioTestCase):
    def device(self):
        d=Device(CONFIG,'/unused');d.width,d.height=720,1600;d.connected=True;d.lockfile=object()
        d.send=AsyncMock();d.broadcast=AsyncMock();d.shell=AsyncMock(return_value='Physical size: 1080x2400')
        d.observed_at=time.monotonic();d.observed_generation=1
        return d

    async def test_rejected_manual_input_emits_nothing(self):
        d=self.device()
        with self.assertRaises(ValueError):await d.touch(0,10,10,1600,720)
        d.broadcast.assert_not_called()
        d.send.side_effect=RuntimeError('disconnected')
        with self.assertRaises(RuntimeError):await d.key(4)
        d.broadcast.assert_not_called()

    async def test_human_path_and_takeover_clear(self):
        d=self.device();await d.touch(0,360,800,720,1600);await d.touch(2,360,500,720,1600);await d.touch(1,360,400,720,1600)
        cue=json.loads(d.broadcast.call_args.args[0]);self.assertEqual(cue['kind'],'swipe');self.assertEqual(cue['points'][0],[.5,.5]);self.assertEqual(cue['points'][-1],[.5,.25])
        await d.clear_actions();count=d.broadcast.call_count
        await d.publish_action(cue,'returned');self.assertEqual(count,d.broadcast.call_count)

    async def run_backend(self,name,args,guard=None,error=False):
        d=self.device();methods=[];lines=asyncio.Queue()
        class Process:
            pid=999999999
            async def wait(self):return 0
        p=Process()
        class Writer:
            def write(self,raw):
                msg=json.loads(raw);method=msg['method'];methods.append(method)
                if 'id'not in msg:return
                result={'tools':[{'name':name,'inputSchema':{'properties':{}},'annotations':{'readOnlyHint':False}}]} if method=='tools/list'else {'content':[], 'isError':error} if method=='tools/call'else {}
                lines.put_nowait((json.dumps({'id':msg['id'],'result':result})+'\n').encode())
            async def drain(self):pass
        p.stdin=Writer()
        class Reader:
            async def readline(self):return await lines.get()
        p.stdout=Reader()
        with patch('mopu.device.asyncio.create_subprocess_exec',AsyncMock(return_value=p)),patch('mopu.device.os.killpg'):
            if guard:
                with self.assertRaises(PermissionError):await d.backend(name,args,1,guard,'Codex')
            else:await d.backend(name,args,1,actor='Codex')
        return d,methods

    async def test_takeover_during_startup_blocks_unsent_input_and_marker(self):
        def guard():raise PermissionError('takeover')
        d,methods=await self.run_backend(TAP,{'x':540,'y':1200},guard)
        self.assertNotIn('tools/call',methods);d.broadcast.assert_not_called()

    async def test_agent_sent_and_uncertain_without_replay(self):
        d,methods=await self.run_backend(TAP,{'x':540,'y':1200},error=True)
        cues=[json.loads(c.args[0])for c in d.broadcast.call_args_list]
        self.assertEqual([c['phase']for c in cues],['sent','uncertain'])
        self.assertEqual(cues[0]['points'],[[.5,.5]]);self.assertEqual(methods.count('tools/call'),1)

    async def test_agent_text_emits_only_generic_label(self):
        d,_=await self.run_backend('mobile_type_keys',{'text':'private-password'})
        self.assertNotIn('private-password',str(d.broadcast.call_args_list))
        self.assertEqual(json.loads(d.broadcast.call_args.args[0])['label'],'输入文字')

if __name__=='__main__':unittest.main()
