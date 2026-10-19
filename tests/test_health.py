import unittest
from mopu.health import audio_status, camera_status, torch_status, microphone_status, projection_status, battery_status

class HealthParserTests(unittest.TestCase):
    TORCH='    FlashlightController state:\n      mCameraId=0\n      mFlashlightEnabled=%s\n      mTorchAvailable=%s\n\n    Dump took 2ms\n'

    def test_torch_current_on_and_off(self):
        self.assertEqual(torch_status(self.TORCH%('false','true')),{'active':False,'available':True,'camera_id':'0'})
        self.assertTrue(torch_status(self.TORCH%('true','true'))['active'])

    def test_torch_unavailable_does_not_reuse_cached_enabled(self):
        for enabled in ('true','false'):
            self.assertIsNone(torch_status(self.TORCH%(enabled,'false'))['active'])
        self.assertIsNone(torch_status((self.TORCH%('false','true')).replace('mCameraId=0','mCameraId=null'))['active'])

    def test_torch_capability_history_missing_and_conflicts_are_unknown(self):
        for raw in ('Has a flash unit: true', 'Event log: mFlashlightEnabled=false', 'Permission denied',
                    'FlashlightController state:\n  mCameraId=0\n  mFlashlightEnabled=false\n',
                    (self.TORCH%('false','true'))+(self.TORCH%('true','true'))):
            self.assertIsNone(torch_status(raw)['active'])

    def test_calls_are_separate_from_silent_ringer(self):
        raw='- STREAM_VOICE_CALL:\n   Muted: false\n   Min: 1\n   Max: 8\n   streamVolume:1\n   Devices: earpiece(1)\n\nAudio mode:\n- Actual mode = MODE_IN_CALL\n'
        a=audio_status(raw)
        self.assertTrue(a['call_active']);self.assertFalse(a['streams']['VOICE_CALL']['silent'])
        self.assertEqual(a['streams']['VOICE_CALL']['min'],1)
        self.assertIsNone(a['basic_silent'])

    def test_camera_uses_live_clients_not_event_history(self):
        raw='Active Camera Clients:\n[]\nAllowed user IDs: 0\nCONNECT device 0 client for package example.old\n'
        self.assertFalse(camera_status(raw)['active'])
        raw=raw.replace('[]','[\n(Camera ID: 0, Client Package Name: example.camera)\n]')
        self.assertEqual(camera_status(raw),{'active':True,'apps':['example.camera']})
        self.assertIsNone(camera_status('Permission denied')['active'])

    def test_mic_history_inactive_and_silenced(self):
        base='RecordActivityMonitor dump time: 10:00\n%s\nEvents log: recording activity received by AudioService\nrec start uid 123\n'
        self.assertFalse(microphone_status(base%'')['active'])
        self.assertFalse(microphone_status(base%'riid 1; active? false\n pack:example.old silenced:false')['active'])
        a=microphone_status(base%'riid 1; active? true\n source client=MIC -- pack:example.camera -- silenced:true')
        self.assertTrue(a['active']);self.assertTrue(a['silenced'])
        self.assertEqual(a['apps'],['example.camera'])
        self.assertIsNone(microphone_status('truncated')['active'])

    def test_charging_and_power_supply_are_distinct(self):
        b=battery_status('  AC powered: true\n  USB powered: false\n  status: 4\n  level: 79\n  scale: 100\n  temperature: 250\n AdaptiveCharging: mUpperLimit:80, mChargingDisabled:true\n')
        self.assertEqual(b['status'],'not_charging'); self.assertTrue(b['plugged']);self.assertTrue(b['protection_paused'])
        self.assertEqual(b['temperature'],25);self.assertEqual(b['protection_limit'],80)
        self.assertIsNone(battery_status('error')['plugged'])

    def test_projection_unknown_is_not_idle(self):
        self.assertIsNone(projection_status('denied')['active'])
        self.assertFalse(projection_status('Media Projection: \nnull')['active'])
        self.assertTrue(projection_status('Media Projection: \n(packageName=example.screen, uid=1)')['active'])


import asyncio
import tempfile
import time
from unittest.mock import AsyncMock
from mopu.device import Device
from mopu.app import Console
CONFIG={'serial':'test','adb':'/test/adb','backend_command':[]}

class HealthLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_data_and_disconnect_do_not_report_idle(self):
        d=Device(CONFIG,'/unused');d.connected=True
        d.health['camera']={'data':{'active':False},'sampled':time.monotonic()-8,'at':'old'}
        s=d.health_snapshot()['camera'];self.assertFalse(s['fresh']);self.assertEqual(s['data'],{});self.assertEqual(s['at'],'old')
        d.health['camera']['sampled']=time.monotonic();self.assertTrue(d.health_snapshot()['camera']['fresh'])
        d.connected=False;self.assertEqual(d.health_snapshot()['camera']['data'],{})

    async def test_read_failure_invalidates_previous_sample(self):
        d=Device(CONFIG,'/unused');d.connected=True;d.shell=AsyncMock(side_effect=RuntimeError('USB'))
        d.health['camera']={'data':{'active':False},'sampled':time.monotonic(),'at':'previous-success'}
        await d.read_health('camera',('dumpsys','media.camera'),camera_status)
        s=d.health_snapshot()['camera'];self.assertFalse(s['fresh']);self.assertEqual(s['at'],'previous-success')

    async def test_old_connection_cannot_overwrite_new_session(self):
        d=Device(CONFIG,'/unused');d.connected=True;d.lockfile=object()
        async def shell(*args):
            d.lockfile=object()
            return 'Active Camera Clients:\n[]\nAllowed user IDs: 0'
        d.shell=shell
        await d.read_health('camera',('dumpsys','media.camera'),camera_status)
        self.assertNotIn('camera',d.health)

    async def test_activity_monitor_runs_during_agent_operation(self):
        with tempfile.TemporaryDirectory() as folder:
            c=Console(CONFIG,folder);c.device.connected=True;seen=asyncio.Event()
            async def sample(): seen.set()
            c.device.sample_activity=sample
            async with c.op:
                task=asyncio.create_task(c.activity_loop())
                try: await asyncio.wait_for(seen.wait(),.5)
                finally:
                    task.cancel();await asyncio.gather(task,return_exceptions=True)

class QuietCallTests(unittest.IsolatedAsyncioTestCase):
    async def test_muting_uses_audio_shell_and_verifies_without_replay(self):
        from unittest.mock import patch
        from mopu.health import STREAMS
        def dump(muted):
            result=''
            for name in STREAMS:
                v=0 if muted or name not in ('VOICE_CALL','BLUETOOTH_SCO') else 6
                result+=f'- STREAM_{name}:\n   Muted: {str(v==0).lower()}\n   Min: 1\n   Max: 8\n   streamVolume:{v}\n   Devices: earpiece(1)\n\n'
            return result+'Audio mode:\n- Actual mode = MODE_NORMAL\n'
        with tempfile.TemporaryDirectory() as folder:
            d=Device(CONFIG,folder);calls=[];read_count=0
            async def shell(*args):
                nonlocal read_count
                calls.append(args)
                if args[:3]==('settings','get','global'):return '2' if args[-1]=='zen_mode' else 'null'
                if args[:2]==('settings','get'):return 'null'
                if args[:2]==('cmd','media_session'):return '[v] volume is 0 in range [0..15]'
                if args==('dumpsys','audio'):
                    read_count+=1
                    return dump(read_count>1)
                return 'ack'
            d.shell=shell
            result=await d.quiet()
            self.assertTrue(result['voice_call']['silent']);self.assertTrue(result['bluetooth_sco']['silent'])
            self.assertEqual(calls.count(('cmd','audio','adj-mute','0')),1)
            self.assertEqual(calls.count(('cmd','audio','adj-mute','6')),1)
            self.assertFalse(any(c[:4]==('cmd','media_session','volume','--stream') and '0' in c and '--set' in c for c in calls))

class AudioSourceTests(unittest.TestCase):
    def test_playback_capture_is_not_a_microphone(self):
        text='RecordActivityMonitor dump time: now\nriid 7; active? true\n source client=REMOTE_SUBMIX -- pack:example.recorder -- silenced:false\nEvents log: recording activity received by AudioService\n'
        self.assertFalse(microphone_status(text)['active'])
        self.assertIsNone(microphone_status(text.replace('REMOTE_SUBMIX','OEM_UNKNOWN'))['active'])
    def test_aosp_projection_layout(self):
        self.assertEqual(projection_status('Media Projection: \n(example.recorder, uid=10001): TYPE_SCREEN_CAPTURE'),{'active':True,'apps':['example.recorder']})

if __name__=='__main__': unittest.main()
