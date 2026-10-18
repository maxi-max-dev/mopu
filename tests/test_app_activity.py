import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from phone_harness.app_activity import AppActivityLog, AppActivityMonitor, parse_foreground, app_labels
from phone_harness.activity import ActivityLog

FOCUS='  mCurrentFocus=Window{abc u0 com.android.settings/.Settings}'
POLICY='  showing=false\n  occluded=false'
POWER='mWakefulness=Awake'
SETTINGS={'status':'known','package':'com.android.settings','label':'设置','label_source':'alias'}
CLOCK={'status':'known','package':'com.android.deskclock','label':'时钟','label_source':'alias'}


class ForegroundTests(unittest.TestCase):
    def test_actual_app_names_are_metadata_and_unknown_format_is_not_guessed(self):
        result={'content':[{'type':'text','text':'Found these apps on device: 设置 (com.android.settings), My App (Demo) (com.example.app)'}]}
        self.assertEqual(app_labels(result),{'com.android.settings':'设置','com.example.app':'My App (Demo)'})
        self.assertEqual(app_labels({'isError':True,**result}),{})
        self.assertEqual(app_labels({'content':[{'text':'unexpected private content'}]}),{})

    def test_focus_and_lock_are_separate_from_physical_panel(self):
        self.assertEqual(parse_foreground(FOCUS,POLICY,POWER),SETTINGS)
        self.assertEqual(parse_foreground(FOCUS,POLICY.replace('showing=false','showing=true'),POWER),{'status':'locked'})
        self.assertEqual(parse_foreground(FOCUS,POLICY,POWER.replace('Awake','Dozing')),{'status':'asleep'})
        self.assertEqual(parse_foreground(FOCUS,'showing=true\noccluded=true',POWER),SETTINGS)

    def test_no_focus_or_ambiguous_focus_is_unknown(self):
        for focus in ['mCurrentFocus=null','mCurrentFocus=Window{abc u0 private window title}',FOCUS+'\n'+FOCUS.replace('com.android.settings','com.example.other')]:
            self.assertEqual(parse_foreground(focus,POLICY,POWER),{'status':'unknown'})
        self.assertEqual(parse_foreground(FOCUS,'',POWER),{'status':'unknown'})

    def test_unknown_app_falls_back_to_package_without_title(self):
        r=parse_foreground(FOCUS.replace('com.android.settings','com.example.custom'),POLICY,POWER)
        self.assertEqual(r['label'],'com.example.custom');self.assertEqual(r['label_source'],'package')
        self.assertNotIn('Settings',json.dumps(r))


class VisitTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.t=1000;self.m=50
        self.log=AppActivityLog(self.root,lambda:self.t,lambda:self.m)
    def tearDown(self):self.temp.cleanup()
    def advance(self,seconds):self.t+=seconds;self.m+=seconds

    def test_switch_duration_and_input_sources(self):
        self.log.observe(SETTINGS);self.advance(2);self.log.observe(SETTINGS)
        self.log.action('agent','tap');self.log.action('human','swipe')
        self.advance(2);self.log.observe(CLOCK)
        a,b=self.log.data['visits']
        self.assertEqual(a['seconds'],2);self.assertFalse(a['ongoing']);self.assertEqual(a['end_reason'],'switched')
        self.assertEqual(a['inputs'],{'agent':{'tap':1},'human':{'swipe':1}})
        self.assertEqual(b['seconds'],0);self.assertTrue(b['ongoing'])

    def test_unknown_lock_and_disconnect_end_at_last_observation(self):
        for reason in ('unknown','locked','asleep','offline','disabled'):
            self.log.observe(SETTINGS);self.advance(2);self.log.observe(SETTINGS)
            self.advance(2);self.log.end(reason);self.advance(100)
            row=self.log.data['visits'][-1]
            self.assertEqual(row['seconds'],2);self.assertFalse(row['ongoing'])
            self.assertIsNone(self.log.action('human','tap'))

    def test_sleep_gap_clock_jump_and_stale_snapshot_do_not_inflate(self):
        self.log.observe(SETTINGS);self.advance(2);self.log.observe(SETTINGS)
        self.advance(300)
        self.assertEqual(self.log.snapshot(True,True)['status'],'unknown')
        self.assertFalse(self.log.snapshot(True,True)['visits'][-1]['ongoing'])
        self.log.observe(SETTINGS)
        self.assertEqual([x['seconds'] for x in self.log.data['visits']],[2,0])
        self.t-=10;self.m+=2;self.log.observe(SETTINGS)
        self.assertEqual(len(self.log.data['visits']),3)

    def test_restart_preserves_history_but_never_resumes_duration(self):
        self.log.observe(SETTINGS);self.advance(2);self.log.observe(SETTINGS);self.log.save()
        self.advance(100)
        new=AppActivityLog(self.root,lambda:self.t,lambda:self.m)
        self.assertEqual(new.data['visits'][0]['seconds'],2)
        self.assertEqual(new.data['visits'][0]['end_reason'],'interrupted')
        new.observe(SETTINGS);self.assertEqual(len(new.data['visits']),2)
        self.assertEqual(self.log.path.stat().st_mode & 0o777,0o600)
        archived=json.loads((self.root/'app-visits.jsonl').read_text().splitlines()[0])
        self.assertEqual(archived['seconds'],2);self.assertEqual(archived['end_reason'],'interrupted')

    def test_ignores_unrequested_content_fields(self):
        self.log.observe({**SETTINGS,'title':'private-title','text':'private-text','url':'secret-url'})
        text=self.log.path.read_text()
        for private in ('private-title','private-text','secret-url'):self.assertNotIn(private,text)
        self.assertNotIn('title',text)

    def test_app_switches_do_not_change_input_notification_grouping(self):
        a=ActivityLog(self.root,lambda:self.t);a.data['enabled']=True;a.apps=self.log
        self.log.observe(SETTINGS);a.record('device','tap',True)
        self.advance(2);self.log.observe(CLOCK);a.record('device','tap',True)
        self.assertEqual(len(a.data['records']),1)
        self.assertEqual(len(self.log.data['visits']),2)
        self.assertFalse(a.verified())

    def test_notification_window_clips_both_ends_and_excludes_gaps_and_outside_apps(self):
        self.log.observe(SETTINGS)
        for _ in range(5):self.advance(2);self.log.observe(SETTINGS)
        self.log.end('locked');self.advance(20);self.log.observe(CLOCK)
        self.advance(2);self.log.observe(CLOCK)
        rows=self.log.interval_visits(1004,1008)
        self.assertEqual([(r['label'],r['seconds']) for r in rows],[('设置',4)])
        self.assertEqual(sum(r['seconds'] for r in self.log.interval_visits(1004,1040)),8)
        self.assertEqual(self.log.interval_visits(1012,1025),[])
        self.assertEqual(self.log.interval_visits(1010,1000),[])


class MonitorTests(unittest.IsolatedAsyncioTestCase):
    async def test_device_names_override_aliases_once_per_connection(self):
        with tempfile.TemporaryDirectory() as root:
            a=ActivityLog(root);a.data['enabled']=True
            d=SimpleNamespace(connected=True,lockfile=object(),backend=AsyncMock(return_value={'content':[{'text':'Found these apps on device: Actual Name (com.android.settings)'}]}))
            m=AppActivityMonitor(d,a)
            await m.refresh_labels();await m.refresh_labels()
            d.backend.assert_awaited_once()
            with patch('phone_harness.app_activity.read_foreground',AsyncMock(return_value=dict(SETTINGS))):await m.sample()
            self.assertEqual(a.apps.current['label'],'Actual Name');self.assertEqual(a.apps.current['label_source'],'device')
            self.assertNotIn('labels',a.apps.path.read_text())

    async def test_late_result_after_recording_disabled_is_discarded(self):
        with tempfile.TemporaryDirectory() as root:
            a=ActivityLog(root);a.data['enabled']=True
            d=SimpleNamespace(connected=True,lockfile=True)
            async def late(device):
                a.data['enabled']=False
                return SETTINGS
            with patch('phone_harness.app_activity.read_foreground',late):
                await AppActivityMonitor(d,a).sample()
            self.assertEqual(a.apps.data['visits'],[])
            self.assertEqual(a.apps.runtime['status'],'disabled')

    async def test_failed_read_and_missing_device_lock_do_not_keep_counting(self):
        with tempfile.TemporaryDirectory() as root:
            a=ActivityLog(root);a.data['enabled']=True;a.apps.observe(SETTINGS)
            d=SimpleNamespace(connected=True,lockfile=True)
            with patch('phone_harness.app_activity.read_foreground',AsyncMock(side_effect=RuntimeError)):
                await AppActivityMonitor(d,a).sample()
            self.assertFalse(a.apps.data['visits'][0]['ongoing'])
            d.lockfile=None
            with patch('phone_harness.app_activity.read_foreground',AsyncMock()) as read:
                await AppActivityMonitor(d,a).sample();read.assert_not_called()

if __name__=='__main__':unittest.main()
