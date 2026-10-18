"""Small, local action summaries and an opt-in notification hook.

No coordinates, typed text, UI trees or screenshots enter this log.
"""
import asyncio
import json
import secrets
import time
from pathlib import Path
from .tasks import atomic, now
from .app_activity import AppActivityLog

KINDS = {'tap':'点击','swipe':'滑动','long_press':'长按','double_tap':'双击',
         'key':'导航按键','text':'文字输入','app':'打开应用或链接',
         'power':'电源键','volume':'音量键'}
MERGE_SECONDS = 30


class ActivityLog:
    def __init__(self, root, clock=time.time):
        self.root, self.clock = Path(root), clock
        self.path = self.root/'activity.json'
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {
            'enabled':False,'records':[],'last_notification':0,'seen_at':0}
        self.notification_lock = asyncio.Lock()
        self.pending_apps = {}
        self.apps = AppActivityLog(root,clock)
        self.last_human = self.clock()
        self.known_ids = set()
        self.runtime = {'status':'disabled','nodes':[],'fingerprint':None,'at':None,'error':None}
        # An interrupted send has an uncertain outcome; never replay it automatically.
        for r in self.data['records']:
            if r.get('notification') == 'sending': r['notification'] = 'unknown'
            elif r.get('notification') == 'pending': r['notification'] = 'expired'
        if self.data.get('test',{}).get('status')=='sending':self.data['test']['status']='unknown'
        self.save()

    def save(self): atomic(self.path,self.data)

    def config(self):
        try:
            cfg = json.loads((self.root/'activity-notifications.json').read_text())
            command = cfg.get('command')
            if not isinstance(command,list) or not command or not all(isinstance(x,str) and x for x in command): return {}
            return cfg
        except (OSError, ValueError): return {}

    def verified(self):
        try:
            v = json.loads((self.root/'activity-validation.json').read_text())
            return bool(self.runtime['fingerprint'] and v.get('fingerprint')==self.runtime['fingerprint']
                        and v.get('physical_verified') is True and v.get('remote_verified') is True)
        except (OSError, ValueError): return False

    def known(self, cue, phase):
        if cue.get('source') == 'human': self.last_human = self.clock()
        if phase != 'sent' or cue['id'] in self.known_ids: return
        self.known_ids.add(cue['id'])
        if len(self.known_ids)>1000: self.known_ids={cue['id']}
        try:self.record(cue.get('source'),{'hold':'long_press','long':'long_press','double':'double_tap'}.get(cue.get('kind'),cue.get('kind')),False)
        except OSError:self.runtime.update(status='unavailable',error='活动记录写入失败')

    def record(self, source, kind, idle):
        if not self.data['enabled'] or source not in ('human','agent','device') or kind not in KINDS: return
        t = self.clock()
        self.apps.action(source,kind)
        records = self.data['records']
        r = next((x for x in reversed(records) if x['source']==source and x['idle']==idle and x.get('verified')==(source!='device' or self.verified()) and 0<=t-x['last']<=MERGE_SECONDS),None)
        if r is None:
            r = {'id':secrets.token_hex(12),'source':source,'idle':bool(idle),'first':t,'last':t,'at':now(),
                 'counts':{},'verified':source!='device' or self.verified(),'notification':'pending' if source=='device' and idle else 'not_applicable'}
            records.append(r)
        r['last']=t;r['counts'][kind]=r['counts'].get(kind,0)+1
        # Persist an append-only, metadata-only journal; the UI keeps recent summaries.
        entry={'id':r['id'],'source':source,'kind':kind,'at':t,'idle':bool(idle)}
        with (self.root/'activity-events.jsonl').open('a') as f: f.write(json.dumps(entry)+'\n')
        (self.root/'activity-events.jsonl').chmod(0o600)
        self.data['records']=records[-250:]
        self.save()

    def app_summary(self, record, end):
        # Retain per-visit metadata in memory while merging, including visits that
        # leave the recent-250 log during a long session. Repeated reads replace
        # the same visit, while returning to an app adds a separate visit.
        visits=self.pending_apps.setdefault(record['id'],{})
        for visit in self.apps.interval_visits(record['first'],end):
            visits[visit['id']]=visit
        grouped={}
        for visit in visits.values():
            row=grouped.setdefault(visit['package'],{'package':visit['package'],'label':visit['label'],'seconds':0})
            row['seconds']+=visit['seconds']
        return [{**row,'seconds':round(row['seconds'],1)} for row in grouped.values()]

    @staticmethod
    def notification_body(record):
        stamp=lambda value:time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(value))
        lines=['手机检测到一段本体输入。',
               '统计区间：'+stamp(record['first'])+' → '+stamp(record['summary_end']),
               '操作合计：'+ActivityLog.describe(record), '本段观察到的前台 App（重复进入已合计）：']
        for app in record['app_summary']:
            label=' '.join(app['label'].split())[:80] or app['package']
            seconds=app['seconds']
            duration='不足 1 秒' if seconds<1 else str(int(seconds))+' 秒'
            lines.append('• '+label+'：约 '+duration)
        if not record['app_summary']:lines.append('• 未取得可用的前台 App 读数，不推测应用或时长。')
        lines.extend(['连续 30 秒无新操作后合并发送；统计至末次操作后 30 秒，每段只提醒一次，提醒至少间隔 5 分钟。',
                      '检测输入时无控制台人工输入、无正在执行的助手任务。App 时长只计有效前台读数，约每 2 秒取样；锁屏或读数中断不补算。前台停留不代表持续使用，无法确认是谁打开或操作。',
                      '不记录或发送页面内容、输入文字、截图、录音。'])
        return '\n'.join(lines)

    def snapshot(self, connected):
        runtime = dict(self.runtime)
        if not self.data['enabled']: runtime['status']='disabled'
        elif not connected: runtime['status']='offline'
        verified = self.verified()
        records = self.data['records'][-100:]
        return {**runtime,'enabled':self.data['enabled'],'verified':verified,
                'notifications_configured':bool(self.config()),
                'unread':sum(r['source']=='device' and r['last']>self.data['seen_at'] for r in records),
                'records':records,'test':self.data.get('test'),
                'apps':self.apps.snapshot(connected,self.data['enabled'])}

    async def send(self, event_id, title, body):
        cfg = self.config()
        if not cfg: return {'status':'unconfigured'}
        # The private hook accepts text on stdin plus stable event id/title arguments.
        p = None
        try:
            p=await asyncio.create_subprocess_exec(*cfg['command'],'--event-id',event_id,'--title',title,
                stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
            stdout,_=await asyncio.wait_for(p.communicate(body.encode()),30)
            result=json.loads(stdout)
            if p.returncode==0 and result.get('ok') is True and result.get('status')=='sent' and result.get('messageId'):
                return {'status':'sent','message_id':str(result['messageId'])[:100],
                        'deduplicated':bool(result.get('deduplicated'))}
            return {'status':'failed'}
        except asyncio.CancelledError:
            if p and p.returncode is None:
                p.kill();await p.wait()
            raise
        except (OSError,ValueError,asyncio.TimeoutError):
            if p and p.returncode is None:
                p.kill();await p.wait()
            return {'status':'unknown'}

    async def tick(self, connected=True):
        async with self.notification_lock:
            t=self.clock()
            for r in self.data['records']:
                if r['notification']!='pending': continue
                # No backlog alerts after restart, validation or a long disconnect.
                if not connected or not self.data['enabled'] or self.runtime['status']!='listening' or not self.verified() or not r.get('verified'):
                    r['notification']='held_unverified';self.save();continue
                if t<r['last'] or t-r['last']>90: r['notification']='expired';self.save();continue
                summary=self.app_summary(r,min(t,r['last']+MERGE_SECONDS))
                if t-r['last']<=MERGE_SECONDS:continue
                if not self.config(): r['notification']='unconfigured';self.save();continue
                if t-self.data['last_notification']<300:
                    r['notification']='cooldown';self.save();continue
                r.update(notification='sending',app_summary=summary,summary_end=r['last']+MERGE_SECONDS)
                self.data['last_notification']=t;self.save()
                body=self.notification_body(r)
                try: result=await self.send('phone-activity-'+r['id'],'手机外部操作提醒',body)
                except asyncio.CancelledError:
                    r['notification']='unknown';self.save();raise
                r['notification']=result['status'];r['delivery']=result;self.save()
            pending={r['id'] for r in self.data['records'] if r['notification']=='pending'}
            self.pending_apps={key:value for key,value in self.pending_apps.items() if key in pending}

    @staticmethod
    def describe(record): return '、'.join(KINDS[k]+' '+str(n)+' 次' for k,n in record['counts'].items())

    async def test_notification(self):
        async with self.notification_lock:
            test=self.data.setdefault('test',{'id':'phone-activity-test-'+secrets.token_hex(12)})
            if test.get('status') in ('sent','sending','unknown'): return test
            if test.get('attempt_at') and self.clock()-test['attempt_at']<300: return test
            test.update(status='sending',attempt_at=self.clock());self.save()
            try:
                result=await self.send(test['id'],'Phone Harness · 活动提醒测试',
                    '这是你授权的手机活动提醒通道测试，不代表有人操作了手机。\n正式外部操作告警仍待实体触摸对照实测，当前没有启用。连续30秒无新操作后合并记录，附本段App名称及前台时长，提醒设5分钟冷却。')
            except asyncio.CancelledError:
                test['status']='unknown';self.save();raise
            test.update(result);self.save();return test
