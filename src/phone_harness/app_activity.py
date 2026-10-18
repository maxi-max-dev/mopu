"""Foreground package metadata only. Never query titles, UI text or usage content."""
import asyncio
import json
import re
import secrets
import time
from pathlib import Path
from .tasks import atomic

MAX_GAP = 6
# Display aliases, not titles scraped from app windows. Unknown apps show package ID.
APP_NAMES = {
    'com.android.settings':'设置', 'com.android.systemui':'系统界面',
    'com.android.launcher3':'桌面', 'com.motorola.launcher3':'桌面',
    'com.zui.launcher':'桌面', 'com.google.android.apps.nexuslauncher':'桌面',
    'com.android.deskclock':'时钟', 'com.google.android.deskclock':'时钟',
    'com.android.calculator2':'计算器', 'com.google.android.calculator':'计算器',
    'com.android.dialer':'电话', 'com.google.android.dialer':'电话',
    'com.motorola.camera5':'相机', 'com.android.camera2':'相机',
    'com.tencent.mm':'微信', 'com.tencent.mobileqq':'QQ',
    'com.xingin.xhs':'小红书', 'tv.danmaku.bili':'哔哩哔哩',
    'com.google.android.youtube':'YouTube', 'com.android.chrome':'Chrome',
    'com.ss.android.ugc.aweme':'抖音', 'com.ss.android.ugc.trill':'TikTok',
    'com.zhiliaoapp.musically':'TikTok', 'com.ss.android.lark':'飞书',
    'com.openai.chatgpt':'ChatGPT', 'com.android.documentsui':'文件',
}


def app_labels(result):
    """Read Mobile MCP's app-name metadata; keep the full inventory in memory only."""
    if result.get('isError'):return {}
    names={}
    for part in result.get('content',[]):
        text=part.get('text','')
        prefix='Found these apps on device: '
        if not text.startswith(prefix):continue
        for label,package in re.findall(r'(.*?) \(([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+)\)(?:,\s*|$)',text[len(prefix):]):
            if label.strip():names[package]=label.strip()[:80]
    return names


def parse_foreground(focus, policy, power):
    wake = re.findall(r'\bmWakefulness=(\w+)', power)
    showing = re.findall(r'^\s*showing=(true|false)\s*$', policy, re.M)
    occluded = re.findall(r'^\s*occluded=(true|false)\s*$', policy, re.M)
    if wake != ['Awake']:
        return {'status':'asleep' if wake and wake[0] in ('Asleep','Dozing','Dreaming') else 'unknown'}
    # Count no underlying app while keyguard covers it. An app visibly occluding
    # keyguard can still be foreground (e.g. a call); no content is read.
    if not showing or len(set(showing)) != 1:
        return {'status':'unknown'}
    if showing[0] == 'true' and occluded != ['true']:
        return {'status':'locked'}
    packages = re.findall(r'^\s*mCurrentFocus=Window\{[^\n{}]*\bu\d+ ([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+)/[^\s}]+', focus, re.M)
    if len(set(packages)) != 1:
        return {'status':'unknown'}
    package = packages[0]
    return {'status':'known','package':package,'label':APP_NAMES.get(package,package),
            'label_source':'alias' if package in APP_NAMES else 'package'}


async def read_foreground(device):
    # Filter on-device: the host receives only current-focus identity and state
    # flags, never a full window/activity dump or an application's visible text.
    async with asyncio.timeout(4):
        focus, policy, power = await asyncio.gather(
            device.shell("dumpsys window | grep -E '^[[:space:]]*mCurrentFocus='"),
            device.shell("dumpsys window policy | grep -E '^[[:space:]]*(showing|occluded)='"),
            device.shell("dumpsys power | grep -E '^[[:space:]]*mWakefulness='"))
    return parse_foreground(focus,policy,power)


class AppActivityLog:
    def __init__(self, root, clock=time.time, monotonic=time.monotonic):
        self.path=Path(root)/'app-activity.json'
        self.clock,self.monotonic=clock,monotonic
        self.data=json.loads(self.path.read_text()) if self.path.exists() else {'visits':[]}
        self.current=None;self.last_mono=None;self.saved_at=0
        self.runtime={'status':'unknown','at':None}
        # A restart is an observation gap; never extend the previous visit.
        for visit in self.data['visits']:
            if visit.get('ongoing'):
                visit.update(ongoing=False,end_reason='interrupted')
                self.archive(visit)
        self.save()

    def save(self):
        atomic(self.path,self.data);self.saved_at=self.clock()

    def archive(self, visit):
        path=self.path.with_name('app-visits.jsonl')
        with path.open('a') as stream:stream.write(json.dumps(visit,ensure_ascii=False)+'\n')
        path.chmod(0o600)

    def end(self, reason):
        if self.current:
            self.current.update(ongoing=False,end_reason=reason)
            self.archive(self.current)
            self.current=None;self.last_mono=None;self.save()
        self.runtime={'status':reason,'at':self.clock()}

    def observe(self, sample):
        if sample.get('status')!='known':
            self.end(sample.get('status','unknown'));return
        t,m=self.clock(),self.monotonic()
        if self.current:
            wall=t-self.current['last'];delta=m-self.last_mono
            if not (0<=wall<=MAX_GAP and 0<=delta<=MAX_GAP and abs(wall-delta)<2):
                self.end('gap')
            elif self.current['package']!=sample['package']:
                self.end('switched')
            else:
                self.current['seconds']+=delta
        if not self.current:
            self.current={'id':secrets.token_hex(12),'package':sample['package'],
                          'label':sample['label'],'label_source':sample['label_source'],
                          'first':t,'last':t,'seconds':0,'ongoing':True,'inputs':{}}
            self.data['visits'].append(self.current)
            self.data['visits']=self.data['visits'][-250:]
            self.save()
        self.current['last']=t;self.last_mono=m
        self.runtime={'status':'known','at':t}
        if t-self.saved_at>=10:self.save()

    def fresh(self):
        return self.current is not None and 0<=self.clock()-self.current['last']<=MAX_GAP and 0<=self.monotonic()-self.last_mono<=MAX_GAP

    def action(self, source, kind):
        if not self.fresh():return None
        counts=self.current['inputs'].setdefault(source,{})
        counts[kind]=counts.get(kind,0)+1;self.save()
        return self.current['id']

    def snapshot(self, connected, enabled):
        status=self.runtime['status']
        if not enabled:status='disabled'
        elif not connected:status='offline'
        elif status=='known' and not self.fresh():status='unknown'
        return {'status':status,'at':self.runtime['at'],'visits':[
            {**v,'seconds':round(v['seconds'],1),'ongoing':bool(v['ongoing'] and status=='known' and v is self.current)}
            for v in self.data['visits'][-100:]],'sample_interval_seconds':2}


class AppActivityMonitor:
    def __init__(self, device, activity):
        self.device,self.activity=device,activity
        self.labels={};self.label_session=None

    async def refresh_labels(self):
        d=self.device
        if not d.connected or not d.lockfile or not self.activity.data['enabled']:return
        session=d.lockfile
        if self.label_session is session:return
        self.label_session=session
        try:
            async with asyncio.timeout(15):
                result=await d.backend('mobile_list_apps',{})
            if d.connected and d.lockfile is session and self.activity.data['enabled']:
                self.labels=app_labels(result)
        except Exception:self.labels={}

    async def sample(self):
        d,a=self.device,self.activity
        if not a.data['enabled'] or not d.connected or not d.lockfile:
            a.apps.end('disabled' if not a.data['enabled'] else 'offline');return
        try:
            observation=await read_foreground(d)
            if not a.data['enabled'] or not d.connected or not d.lockfile:
                a.apps.end('disabled' if not a.data['enabled'] else 'offline');return
            if observation.get('package') in self.labels:
                observation.update(label=self.labels[observation['package']],label_source='device')
            a.apps.observe(observation)
        except Exception:
            a.apps.end('unknown')

    async def run(self):
        try:
            while True:
                await self.refresh_labels()
                await self.sample()
                await asyncio.sleep(2)
        finally:self.activity.apps.end('interrupted')
