import struct,time,tempfile,unittest
from unittest.mock import AsyncMock,patch
from mopu.device import Device
from test_control import CONFIG

class SwipeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.d=Device(CONFIG,self.tmp.name)
        self.d.connected=True;self.d.lockfile=True;self.d.width=720;self.d.height=1600
        self.d.observed_at=time.monotonic();self.d.observed_generation=4
        self.d.shell=AsyncMock(return_value='Physical size: 1080x2400')
        self.d.send=AsyncMock();self.d.publish_action=AsyncMock()
    async def asyncTearDown(self): self.tmp.cleanup()
    async def swipe(self,**args):
        return await self.d.backend('mobile_swipe_on_screen',{'direction':'up','x':540,'y':2100,'distance':1500,**args},4,lambda:None)
    async def test_wire_path_scales_coordinates_and_releases(self):
        with patch('mopu.device.asyncio.create_subprocess_exec',new_callable=AsyncMock) as process:
            await self.swipe();process.assert_not_called()
        packets=[struct.unpack('>BBQiiHHHII',c.args[0]) for c in self.d.send.await_args_list]
        self.assertEqual(packets[0][1:7],(0,(1<<64)-2,360,1400,720,1600))
        self.assertEqual(packets[-1][1:7],(1,(1<<64)-2,360,400,720,1600))
        self.assertEqual(len(packets),22);self.assertEqual(self.d.observed_at,0)
    async def test_takeover_stops_moves_but_releases_pointer(self):
        calls=0
        def guard():
            nonlocal calls
            calls+=1
            if calls==3:raise PermissionError('takeover')
        with self.assertRaises(PermissionError):
            await self.d.backend('mobile_swipe_on_screen',{'direction':'up'},4,guard)
        self.assertEqual([c.args[0][1] for c in self.d.send.await_args_list],[0,2,1])
    async def test_stale_or_wrong_generation_never_inputs(self):
        self.d.observed_generation=3
        with self.assertRaises(PermissionError):await self.swipe()
        self.d.send.assert_not_called()
    async def test_invalid_geometry_and_arguments_never_inputs(self):
        for args in ({'x':-1},{'distance':float('nan')},{'direction':'diagonal'},{'distance':0}):
            with self.assertRaises(ValueError):await self.swipe(**args)
        self.d.width=1000
        with self.assertRaises(ValueError):await self.swipe()
        self.d.send.assert_not_called()
    async def test_failure_does_not_fallback_or_replay(self):
        self.d.send.side_effect=[None,TimeoutError(),None]
        with patch('mopu.device.asyncio.create_subprocess_exec',new_callable=AsyncMock) as process:
            with self.assertRaises(TimeoutError):await self.swipe()
            process.assert_not_called()
        self.assertEqual([c.args[0][1] for c in self.d.send.await_args_list],[0,2,1])
