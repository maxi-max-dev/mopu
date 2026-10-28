from .transfers import Transfers, TransferJobs, TOOLS as FILE_TOOLS, NAMES as FILE_NAMES
from .targets import validate_target, resolve_target
from . import __version__
import asyncio
import contextlib
import json
import secrets
import signal
import time
from pathlib import Path
from aiohttp import web
from .device import Device, ALLOWED
from .tasks import Queue, atomic, now
from .input_activity import probe_inputs, InputMonitor
from .activity import ActivityLog
from .app_activity import AppActivityMonitor
from .contracts import Observations, explanation
from .capabilities import catalog, READS

WEB = Path(__file__).parent / 'web'


class Console:
    def __init__(self, config, state):
        self.state_dir = Path(state)
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.queue = Queue(self.state_dir / 'queue.json')
        self.device = Device(config, self.state_dir)
        self.transfers = Transfers(self.state_dir, self.device)
        self.transfer_jobs = TransferJobs(self)
        self.device.on_disconnect = self.disconnected
        self.op = asyncio.Lock()
        self.transition = asyncio.Lock()
        self.token = secrets.token_urlsafe(32)
        self.origin = ''
        self.agents = {}
        self.observations = Observations()
        self.available_tools = None
        self.tools_checked_at = None
        self.closed_view_at = None
        self.monitor = None
        self.error = None
        self.wanted = False
        self.retries = 0
        self.retry_at = None
        self.activity = ActivityLog(self.state_dir)
        self.app_activity = AppActivityMonitor(self.device,self.activity)
        self.device.on_action = self.activity.known
        self.inputs = InputMonitor(self.device, self.activity,
            lambda: not self.queue.current and not self.op.locked() and not self.device.active_touch and time.time()-self.activity.last_human>3)

    def disconnected(self):
        self.available_tools = None
        self.tools_checked_at = None
        self.activity.apps.end('offline')
        self.queue.revoke_continuations('连接中断：检查未完成动作后重新审批')
        self.queue.invalidate('连接中断；先核实最后动作是否完成')
        self.queue.owner = 'paused'
        self.queue.event('连接中断，任务进度保留；不会重放输入')
        if self.wanted:
            self.retry_at = time.monotonic() + 15

    def snapshot(self):
        telemetry = dict(self.device.telemetry)
        age = time.monotonic()-self.device.panel_sampled if self.device.panel_sampled is not None else None
        telemetry['panel_age'] = round(age, 2) if age is not None else None
        if not self.device.connected or age is None or age > 5:
            telemetry['panel'] = 'unknown'
        queue = self.queue.snapshot()
        for task in queue['tasks']:
            task['continuation'] = self.queue.review_summary(self.queue.get(task['id']))
            task['delivery_summary'] = self.queue.delivery_summary(self.queue.get(task['id']))
        head = self.queue.head()
        for task in queue['tasks']:
            online = time.monotonic()-self.agents.get(task['agent'], {}).get('seen', 0) < 90
            task['wait'] = explanation(task, queue['owner'], self.device.connected, head['id'] if head else None, online)
        return {**queue, 'server_version':__version__, 'file_transfer':{'protocol':1,'continuous':True,'chunk_bytes':4194304,'lease_required':True}, 'capabilities':catalog(self.device.connected, queue['owner'], self.available_tools, self.tools_checked_at), 'activity':self.activity.snapshot(self.device.connected), 'device': {'connected': self.device.connected,
            'error': self.device.error, 'telemetry': telemetry, 'health': self.device.health_snapshot(), 'width': self.device.width,
            'height': self.device.height, 'geometry_note':'width/height describe the video stream only. Agent coordinates use mobile_get_screen_size and fresh element bounds; these can be larger.', 'frame_age': round(time.monotonic()-self.device.last_packet, 1) if self.device.last_packet else None},
            'agents': self.known_agents(),
            'error': self.error, 'recovery': {'attempts':self.retries, 'pending':self.retry_at is not None}}

    def known_agents(self):
        known = {t['agent']: {'id': t['agent'], 'name': t['agent_name'], 'online': False} for t in self.queue.data['tasks']}
        known.update({k: {'id': k, 'name': a['name'], 'online': time.monotonic()-a['seen'] < 90} for k,a in self.agents.items()})
        return list(known.values())

    async def transition_to(self, owner, reason):
        async with self.transition:
            if owner != 'agent':
                self.queue.revoke_continuations(reason)
            self.queue.invalidate(reason)
            self.queue.owner = 'transition'
            await self.device.clear_actions()
            async with self.op:  # Already-issued input may finish; no new input can enter.
                with contextlib.suppress(Exception): await self.device.release_touch()
                self.device.observed_at = 0
                self.queue.owner = owner
                self.queue.event(reason)

    async def agent_request(self, payload):
        name = str(payload.get('agent', ''))
        if name not in self.agents:
            raise PermissionError('请重新连接 MCP')
        agent = self.agents[name]
        if not secrets.compare_digest(str(payload.get('agent_token', '')), agent['token']):
            raise PermissionError('助手连接已失效')
        agent['seen'] = time.monotonic()
        action = payload.get('action')
        q = self.queue
        token = payload.get('lease', '')
        if action == 'submit':
            required=payload.get('required_milestones',[])
            if not isinstance(required,list) or len(required)>20 or any(not isinstance(k,str) or not k.strip() or len(k)>80 for k in required) or len(set(required))!=len(required):
                raise ValueError('required_milestones必须为至多20个唯一阶段key')
            task=q.add(payload.get('title',''), payload.get('instruction',''), name, agent['name'])
            q.get(task['id'])['required_milestones']=required
            task['required_milestones']=required;q.save()
            return task
        if action == 'status':
            return self.snapshot()
        if action == 'session':
            snap = self.snapshot()
            own = [t for t in snap['tasks'] if t['agent'] == name and not t.get('deleted_at')]
            return {'server_version':__version__, 'owner':q.owner, 'generation':q.generation,
                'connected':self.device.connected, 'lease_active':bool(q.lease),
                'tasks':[{'id':t['id'], 'title':t['title'], 'status':t['status'],
                    'checkpoint':t.get('checkpoint'), 'continuation':t['continuation'],
                    'delivery_summary':t['delivery_summary'],
                    'updated_at':t.get('checkpoint_at') or t.get('finished_at') or t.get('created_at'),
                    'wait':t['wait']} for t in own],
                'head_id':q.head()['id'] if q.head() else None}
        if action == 'start':
            # Idempotent grant receipt; a repeated request never reclaims after takeover.
            async with self.transition:
                grant = payload.get('authorization_id')
                for old in q.data['tasks']:
                    stage = next((x for x in old.get('reviews', []) if x.get('authorization_id') == grant), None)
                    if stage:
                        if old['agent'] != name or stage.get('request') != {k:v for k,v in payload.items() if k not in ('agent','agent_token','lease','action')}:
                            raise PermissionError('授权标识已用于不同请求')
                        return {'task_id':old['id'], 'duplicate':True, 'status':old['status'],
                            'continuation':q.review_summary(old), 'next_action':'读取phone_session；仅有效授权可phone_wait，不会自动重领已撤销控制'}
                q.expire()
                if q.lease or q.owner == 'transition':
                    raise PermissionError('手机正在执行其他操作；等待空闲后再开始，不抢占当前任务')
                task_id = payload.get('task_id')
                if task_id:
                    task = q.get(task_id)
                    if task['agent'] != name: raise PermissionError('只能继续自己的原任务')
                else:
                    if any(t['agent']==name and t.get('pending_delivery') for t in q.data['tasks']):
                        raise PermissionError('原任务有未确认发送；请用task_id续接原任务')
                    # Validate all grant fields before persisting a task.
                    scratch = {'id':'validation', 'instruction':payload.get('instruction',''), 'steps':0, 'status':'queued'}
                    q.authorize_task(scratch, payload)
                    task = q.get(q.add(payload.get('title',''),payload.get('instruction',''),name,agent['name'])['id'])
                if any(t is not task and t['agent']==name and (q.needs_review(t) or t.get('pending_delivery')) for t in q.data['tasks']):
                    raise PermissionError('先续接原任务并核对未确认结果，不能另建任务跳过')
                stage = q.authorize_task(task, payload)
                stage['request'] = {k:v for k,v in payload.items() if k not in ('agent','agent_token','lease','action')}
                q.prioritize(task['id'])
                q.owner = 'transition'
                try:
                    await self.device.clear_actions()
                    async with self.op:
                        if not self.device.connected: await self.device.connect()
                        await self.device.release_touch()
                        self.device.observed_at = 0
                        q.owner = 'agent'
                        self.wanted, self.retry_at = True, None
                        q.event('整项任务授权：'+task['title'])
                except Exception:
                    q.stop_for_review(task, '连接失败；授权停止，保留进度，不重放')
                    q.owner = 'paused'
                    raise
                return {'task_id':task['id'], 'continuation':q.review_summary(task),
                    'next_action':'phone_wait领取租约，然后读屏；同一任务持续执行，无需每200调用换段'}
        if action == 'request_control':
            # A trusted client attests to a NEW direct human instruction. This is
            # not inferred from task text or automatically retried after takeover.
            ident = payload.get('task_id')
            authorization = payload.get('user_authorization')
            grant_id = payload.get('authorization_id')
            generation = payload.get('expected_generation')
            if not isinstance(authorization, str) or not authorization.strip() or len(authorization) > 1000:
                raise ValueError('需要当前用户明确授权的原话，最多1000字')
            if not isinstance(grant_id, str) or not 8 <= len(grant_id) <= 100:
                raise ValueError('需要本次用户授权的唯一标识')
            if type(generation) is not int:
                raise ValueError('需要最近状态中的expected_generation')
            async with self.transition:
                task = q.get(ident)
                if task.get('deleted_at') or task.get('user_held'):
                    raise PermissionError('此任务已删除或被你暂停，请先在控制台恢复')
                if any(t is not task and t['agent']==name and q.needs_review(t) for t in q.data['tasks']):
                    raise PermissionError('同一助手已有待检查原任务，不能切换任务绕过')
                if q.needs_review(task) or (task.get('long_task') and task['status'] in ('blocked','unverified')):
                    raise PermissionError('needs_review：控制授权不能替代人工阶段审批')
                grants = task.setdefault('control_authorizations', [])
                switch = payload.get('queue_switch_authorization')
                if switch is not None and (not isinstance(switch,str) or not switch.strip() or len(switch)>1000):
                    raise ValueError('切换队列需要当前用户明确指令')
                selecting = bool(switch) and task['status'] in ('queued','paused','blocked','unverified')
                if selecting and payload.get('expected_head') != (q.head()['id'] if q.head() else None):
                    raise PermissionError('队首已变化，不自动重试切换')
                resume = task['status'] in ('blocked', 'unverified') and (q.head() is None or selecting)
                if task['agent'] != name or (q.head() is not task and not resume and not selecting):
                    raise PermissionError('只能为自己的队首任务申请控制，不能插队')
                if any(g['id'] == grant_id for t in q.data['tasks'] for g in t.get('control_authorizations', [])):
                    raise PermissionError('这次授权已经使用；人工接管后需要新的用户指令')
                if generation != q.generation or q.owner == 'transition' or q.lease:
                    raise PermissionError('控制状态已变化；重新观察状态，不得自动重试接管')
                if len(grants) >= 100:
                    raise ValueError('本任务授权记录已满')
                # Persist consumption BEFORE connection or any awaited work.
                grants.append({'id': grant_id, 'user_authorization': authorization.strip(),
                               'at': now(), 'generation': generation, 'queue_switch_authorization': switch})
                if resume:
                    task.setdefault('attempts', []).append({k:task.get(k) for k in ('result','receipt','finished_at','steps','milestones')})
                    task.update(status='queued', milestones=[], wait_reason='',
                                action='当前用户授权原任务重新观察',
                                prior_steps=task.get('prior_steps',0)+task['steps'], steps=0)
                if selecting:
                    q.prioritize(ident)  # Normal queue operation, old tasks/checkpoints retained.
                q.invalidate('当前用户明确授权，申请交给原助手')
                q.owner = 'transition'
                try:
                    await self.device.clear_actions()
                    async with self.op:
                        if not self.device.connected:
                            await self.device.connect()
                        await self.device.release_touch()
                        self.device.observed_at = 0
                        task['wait_reason'] = ''
                        q.owner = 'agent'
                        self.wanted = True
                        self.retry_at = None
                        q.event('用户明确授权接管：' + task['title'])
                except Exception:
                    q.owner = 'paused'
                    q.event('授权接管未完成；保留任务，不自动重试')
                    raise
                return {'granted': True, 'task_id': ident, 'owner': q.owner,
                        'generation': q.generation,
                        'next_action': '调用phone_wait领取正常租约，然后重新观察屏幕'}
        if action == 'wait':
            q.expire()
            if q.owner == 'agent' and q.lease and q.lease['agent'] == name:
                task = q.check(name, q.lease['token'])
                q.ensure_budget(task, 0)
                return {'lease':q.lease['token'], 'task':dict(task), 'generation':q.generation}
            for _ in range(50):
                if self.device.connected:
                    claim = q.claim(name)
                    if claim: return claim
                await asyncio.sleep(.4)
                agent['seen'] = time.monotonic()
            own = next((t for t in self.snapshot()['tasks'] if t['agent']==name and not t.get('deleted_at') and t['status'] in ('queued','paused','running')), None)
            return {'waiting': True, 'reason': own.get('wait') if own else {'code':'no_task','label':'没有本对话待执行任务','next_action':'无须继续等待'}, 'owner': q.owner, 'head': q.head(), 'instruction': '等待人交回控制权或前序任务结束；可再次调用 phone_wait。不要另开控制通道。'}
        q.check(name, token)
        if action == 'heartbeat':
            task = q.check(name, token)
            q.ensure_budget(task, 0)
            return {'task_id':task['id'], 'renewed':True, 'continuation':q.review_summary(task)}
        if action == 'delivery_confirm':
            async with self.op:
                task = q.check(name, token)
                q.ensure_budget(task, 0)
                receipt = self.observations.receipt(task['id'], q.generation, payload.get('checks'), [])
                return q.confirm_delivery(task, payload.get('key'), payload.get('outcome'), receipt)
        if action == 'input_probe':
            if q.check(name, token).get('long_task'): raise PermissionError('长任务只通过phone_step输入')
            async with self.op:
                q.check(name, token)
                result = await probe_inputs(self.device)
                q.check(name, token)
                return result
        if action == 'milestone':
            async with self.op:
                task=q.check(name,token)
                key=payload.get('key')
                if not isinstance(key,str) or not key.strip() or len(key)>80: raise ValueError('阶段key需为1至80字')
                receipt=self.observations.receipt(task['id'],q.generation,payload.get('checks'),[])
                if receipt['verification'] != 'assistant_verified': raise ValueError('阶段必须有新鲜且通过的观察')
                stages=task.setdefault('milestones',[])
                old=next((m for m in stages if m['key']==key),None)
                if old:
                    if old['checks']==receipt['checks']: return {'saved':True,'duplicate':True,'milestone':old}
                    raise ValueError('阶段key已使用；先观察并使用新的修订key，不覆盖历史')
                if len(stages)>=20: raise ValueError('每次任务尝试至多20个阶段')
                stage={'key':key,'checks':receipt['checks'],'recorded_at':now(),'generation':q.generation,
                       'scope':'已发生的阶段观察；不是当前状态，不可替代最终读回'}
                stages.append(stage);q.save()
                return {'saved':True,'milestone':stage}
        if action == 'checkpoint':
            q.checkpoint(name, token, payload.get('progress',''), payload.get('next_action',''), payload.get('wait_reason',''))
            return {'saved': True}
        if action == 'finish':
            task = q.check(name, token)
            receipt = self.observations.receipt(task['id'], q.generation, payload.get('checks'), payload.get('unresolved'), bool(payload.get('blocked')))
            if task.get('pending_delivery'):
                receipt['verification']='unverified'
                receipt['unresolved'].append('存在未确认发送，禁止计入送达或重放')
            required=task.get('required_milestones',[]) or payload.get('required_milestones',[])
            if not isinstance(required,list) or len(required)>20 or any(not isinstance(k,str) or not k.strip() for k in required):
                raise ValueError('required_milestones必须为至多20个阶段key')
            present={m['key'] for m in task.get('milestones',[])}
            missing=[k for k in required if k not in present]
            receipt['milestones']=task.get('milestones',[])[:]
            receipt['required_milestones']=required
            if missing:
                receipt['verification']='unverified'
                receipt['unresolved'].append('缺少阶段验收：'+', '.join(missing))
            q.finish(name, token, payload.get('result',''), bool(payload.get('blocked')), receipt)
            return {'saved': True, 'task_id':task['id'], 'status':task['status'], 'receipt':receipt}
        if action == 'step':
            tool = payload.get('name')
            target=payload.get('target')
            if target is not None:
                validate_target(target)
                if tool!='mobile_click_on_screen_at_coordinates' or payload.get('arguments'):
                    raise ValueError('target只用于单击，不能同时提供坐标参数')
            mode = payload.get('observe', 'text')
            expected = payload.get('expected_text')
            settle_ms = payload.get('settle_ms',400)
            if type(settle_ms) is not int or not 400<=settle_ms<=5000:
                raise ValueError('settle_ms必须为400至5000的整数；等待不证明页面已加载')
            attempts = payload.get('read_attempts',1)
            if type(attempts) is not int or not 1<=attempts<=3 or (attempts>1 and (mode!='text' or expected is None)):
                raise ValueError('read_attempts为1至3；多次读回必须指定文字预期')
            if tool not in ALLOWED or tool in READS: raise ValueError('step只执行一个允许的输入动作')
            if mode not in ('text','screenshot'): raise ValueError('observe必须为text或screenshot')
            if expected is not None and (mode != 'text' or not isinstance(expected,str) or not expected.strip() or len(expected)>500):
                raise ValueError('expected_text仅支持文字读回，且需为1至500字')
            if any(not isinstance(payload.get(k),str) or not payload[k].strip() for k in ('progress','next_action','observation_id')):
                raise ValueError('需提供进度、下一步和当前界面观察ID')
            async with asyncio.timeout(55), self.op:
                task=q.check(name,token)
                self.observations.receipt(task['id'],q.generation,[{'criterion':'input source','observed':'current screen',
                    'observation_id':payload['observation_id'],'passed':False}],[])
                source=self.observations.records[payload['observation_id']]
                if source['tool'] not in ('mobile_list_elements_on_screen','mobile_take_screenshot'):
                    raise ValueError('输入必须基于界面文字或截图，不能使用应用列表等观察')
                if task.get('long_task'):
                    kind = payload.get('input_kind')
                    if kind not in ('navigation','send'):
                        raise ValueError('长任务需明确input_kind为navigation或send')
                    if (kind == 'send') != bool(payload.get('delivery_key')):
                        raise ValueError('发送必须标注delivery_key，导航不得冒用发送台账')
                q.ensure_budget(task, 1 + attempts + (1 if target is not None else 0))
                if task.get('pending_delivery'):
                    raise PermissionError('上次发送未确认，只能先读取现场并核验')
                q.checkpoint(name,token,payload['progress'],payload['next_action'])
                started=time.monotonic()
                if target is not None:
                    current=await self.agent_tool('call',{'name':'mobile_list_elements_on_screen','arguments':{}},name,token,agent)
                    if current.get('isError'):return current
                    point,reason=resolve_target(current.get('content',[]),target)
                    if point is None:
                        current['isError']=True
                        current.setdefault('content',[]).append({'type':'text','text':json.dumps({'phone_harness_step':{'action_dispatched':False,'target_check':reason,'instruction':'未点击；基于本次新观察重新决定，不猜坐标或盲重试'}},ensure_ascii=False)})
                        return current
                    payload={**payload,'arguments':point}
                if payload.get('delivery_key') is not None:
                    q.begin_delivery(task, payload['delivery_key'])
                result=await self.agent_tool('call',payload,name,token,agent, step_input=True)
                if result.get('isError'): return result
                for attempt in range(attempts):
                    try:
                        await asyncio.sleep(settle_ms/1000 if attempt==0 else .6)
                        observed=await self.agent_tool('call',{'name':'mobile_take_screenshot' if mode=='screenshot' else 'mobile_list_elements_on_screen','arguments':{}},name,token,agent)
                    except Exception as exc:
                        raise RuntimeError('动作可能已生效，但读回失败；先重新观察，禁止重放。'+str(exc)) from exc
                    if observed.get('isError'): return observed
                    texts=[b.get('text','') for b in observed.get('content',[]) if b.get('type')=='text' and 'phone_harness_observation' not in b.get('text','')]
                    check='not_requested' if expected is None else 'text_present' if any(expected in t for t in texts) else 'text_not_found'
                    if check!='text_not_found':break
                observed.setdefault('content',[]).append({'type':'text','text':json.dumps({'phone_harness_step':{
                    'action_dispatched':True,'target_check':'target_matched' if target is not None else 'not_requested','read_attempts':attempt+1,'readback':mode,'settle_ms':settle_ms,'expected_text_check':check,'elapsed_ms':round((time.monotonic()-started)*1000),
                    'instruction':'文字匹配不是任务完成；检查读回。未找到预期时先观察/换策略，不自动重复输入。'}},ensure_ascii=False)})
                return observed
        if action in ('tools','call'):
            if action == 'call' and payload.get('name') in FILE_NAMES and q.check(name,token).get('long_task'):
                raise PermissionError('长任务阶段不混用文件中转预算')
            if action == 'call' and payload.get('name') not in ALLOWED | FILE_NAMES:
                raise ValueError('需要有效的手机工具名称；读取目录请使用 phone_tools')
            if action == 'call' and payload.get('name') == 'mobile_transfer_job':
                # Progress reads must not wait behind a long checksum; caller
                # renewal still requires the normal authenticated lease above.
                task=q.check(name,token)
                value=self.transfer_jobs.handle(payload['name'],payload.get('arguments') or {},task,name,token)
                return {'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}]}
            async with self.op:
                return await self.agent_tool(action,payload,name,token,agent)
        raise ValueError('未知助手动作')

    async def agent_tool(self, action, payload, name, token, agent, step_input=False):
        q=self.queue
        task = q.check(name, token)
        file_call = action == 'call' and payload.get('name') in FILE_NAMES
        if task.get('long_task'):
            if file_call: raise PermissionError('长任务阶段不混用文件中转预算')
            if action == 'call' and payload.get('name') not in READS and not step_input:
                raise PermissionError('长任务输入必须使用phone_step并保留读回预算')
        if task.get('pending_delivery') and action == 'call' and payload.get('name') not in READS and not step_input:
            raise PermissionError('存在未确认发送；先读屏核验，禁止继续输入')
        if not file_call:
            q.ensure_budget(task, 0 if action == 'tools' else 1)
        if file_call: task['file_calls'] = task.get('file_calls', 0) + 1
        elif action != 'tools': task['steps'] += 1
        tool_name = payload.get('name','')
        if action == 'call' and tool_name not in READS:
            self.observations.invalidate(task['id'])
        task['wait_reason'] = ''
        task['action'] = {'mobile_click_on_screen_at_coordinates':'正在点击手机界面，随后核对结果',
            'mobile_double_tap_on_screen':'正在双击手机界面，随后核对结果',
            'mobile_long_press_on_screen_at_coordinates':'正在长按手机界面，随后核对结果',
            'mobile_swipe_on_screen':'正在滑动手机界面，随后重新观察',
            'mobile_type_keys':'正在输入任务所需文字，随后读回',
            'mobile_launch_app':'正在打开应用，随后核对界面',
            'mobile_press_button':'正在使用手机导航，随后重新观察'}.get(tool_name,
            '正在读取手机工具说明' if action == 'tools' else '正在观察并核对当前手机界面')
        q.save()
        try:
            async with asyncio.timeout(55):
                if action == 'call' and tool_name in FILE_NAMES:
                    if tool_name in ('mobile_transfer_start','mobile_transfer_job'):
                        value = self.transfer_jobs.handle(tool_name, payload.get('arguments') or {}, task, name, token)
                    else:
                        value = await self.transfers.handle(tool_name, payload.get('arguments') or {}, task, lambda: q.check(name, token))
                    result = {'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}]}
                else:
                    result = await self.device.backend(None if action == 'tools' else payload.get('name'), payload.get('arguments'), q.generation,
                                                       lambda: q.check(name, token), agent['name'])
                    if action == 'tools': result['tools'].extend(FILE_TOOLS)
        except Exception as exc:
            self.observations.invalidate(task['id'])
            self.device.observed_at = 0
            if q.lease and q.lease['token'] == token:
                q.checkpoint(name, token, task['checkpoint'], '工具失败，先重新观察；不要重复上一步')
            raise exc
        q.check(name, token)  # Discard late results after human takeover.
        if action == 'tools':
            self.available_tools = {t['name'] for t in result.get('tools', [])}
            self.tools_checked_at = now()
            result['capabilities'] = catalog(self.device.connected, q.owner, self.available_tools, self.tools_checked_at)
        elif tool_name in READS and tool_name not in ('mobile_transfer_manifest','mobile_transfer_job') and not result.get('isError'):
            # Screen reads must also pass the backend's nonempty observation guard.
            valid = bool(result.get('content'))
            if tool_name in ('mobile_take_screenshot','mobile_list_elements_on_screen'):
                valid = valid and self.device.observed_generation == q.generation and self.device.observed_at > 0
            if valid:
                obs = self.observations.record(task['id'], q.generation, tool_name)
                result.setdefault('content', []).append({'type':'text','text':json.dumps({'phone_harness_observation':obs},ensure_ascii=False)})
        return result

    async def control(self, data):
        action = data.get('action')
        q = self.queue
        notice = None
        self.error = None
        if action in ('trash', 'restore', 'hold', 'resume'):
            ids = data.get('ids')
            if not isinstance(ids, list) or not ids or len(ids)>500 or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids):
                raise ValueError('请选择有效任务')
            q.manage(action, ids, validate_only=True)
            if action in ('trash','hold') and q.current in ids:
                await self.transition_to('human', '停止所选任务，等待在途动作结束；进度保留')
            async with self.transition, self.op:
                q.manage(action, ids)
            return self.snapshot()
        if action == 'position':
            q.position(data['id'], data.get('position'), data.get('expected_order'))
            return self.snapshot()
        if action == 'review_approve':
            async with self.transition, self.op:
                q.approve_continuation(data)
            return self.snapshot()
        if action == 'activity_preference':
            if not isinstance(data.get('enabled'),bool): raise ValueError('记录开关需要布尔值')
            self.activity.data['enabled']=data['enabled'];self.activity.save()
            if not data['enabled']:self.activity.apps.end('disabled')
            return self.snapshot()
        if action == 'activity_seen':
            self.activity.data['seen_at']=time.time();self.activity.save()
            return self.snapshot()
        if action == 'activity_notify_test':
            await self.activity.test_notification()
            return self.snapshot()
        if action == 'connect':
            self.available_tools = None
            self.tools_checked_at = None
            async with self.transition:
                async with self.op:
                    if not self.device.connected:
                        await self.device.close()
                        await self.device.connect()
                    q.revoke_continuations('新连接：需要重新人工检查')
                    q.owner = 'human'
                    q.invalidate('新会话由你控制')
                    q.event('手机已连接，控制权归你')
                    self.wanted, self.retries, self.retry_at = True, 0, None
        elif action in ('takeover', 'pause', 'release'):
            if action == 'release' and not self.device.connected:
                raise ValueError('请先连接手机')
            owner = {'takeover':'human', 'release':'agent', 'pause':'paused'}[action]
            if action == 'release' and q.head(): q.head()['wait_reason'] = ''
            if action == 'pause' and q.owner == 'human': owner = 'human'
            await self.transition_to(owner, {'takeover':'手机交给你，助手停止读取和输入', 'release':'已交回原助手；下一步必须重新观察', 'pause':'全部手机任务已暂停'}[action])
        elif action in ('disconnect', 'reconnect'):
            self.available_tools = None
            self.tools_checked_at = None
            self.wanted, self.retry_at = False, None
            await self.transition_to('paused', '会话暂停，任务进度保留')
            async with self.op:
                await self.device.close()
                if action == 'reconnect':
                    await self.device.connect()
                    q.owner = 'human'
                    self.wanted, self.retries = True, 0
        elif action in ('quiet', 'screen_off', 'panel_power', 'rotate'):
            async with self.op:
                if q.current: self.observations.invalidate(q.current)
                if not self.device.connected: raise ValueError('请先连接手机')
                if action == 'quiet':
                    await self.device.quiet()
                    await self.device.sample()
                    await self.device.sample_activity()
                    audio = self.device.health_snapshot().get('audio',{}).get('data',{})
                    call_muted = all(audio.get('streams',{}).get(n,{}).get('silent') is True for n in ('VOICE_CALL','BLUETOOTH_SCO'))
                    notice = '基础与通话通道当前已静音；接通后持续核验' if call_muted else '基础静音已恢复；通话通道仍需检查'
                elif action == 'rotate':
                    if q.owner != 'human': raise ValueError('先接管手机，再切换横竖屏')
                    await self.device.clear_actions()
                    changed = await self.device.rotate()
                    notice = '已切换为' + ('横屏' if self.device.width > self.device.height else '竖屏') if changed else '已请求旋转；当前应用仍保持原方向'
                else:
                    on = False if action == 'screen_off' else data.get('on')
                    await self.device.set_panel(on)
                    notice = '实体屏幕已亮起，身边的人可以看到' if on else '实体屏幕已关闭，投屏继续'
                q.event(notice)
        elif action == 'move':
            q.move(data['id'], -1 if data.get('direction') == 'up' else 1)
        elif action == 'prioritize':
            owner = q.owner
            await self.transition_to('human' if owner == 'human' else 'paused', '保存当前任务进度，准备优先任务')
            q.prioritize(data['id'])
            if owner == 'agent': q.owner = 'agent'
        elif action == 'cancel':
            if q.current == data['id']:
                owner = q.owner
                await self.transition_to('human' if owner == 'human' else 'paused', '结束当前任务')
                q.cancel(data['id'])
                if owner == 'agent': q.owner = 'agent'
            else: q.cancel(data['id'])
        elif action == 'retry':
            t = q.get(data['id'])
            if t.get('deleted_at') or t.get('user_held'):
                raise PermissionError('请先恢复任务并取消单独暂停')
            if q.needs_review(t) or t.get('long_task'):
                raise PermissionError('needs_review：请使用人工阶段审批，不得重排清零')
            if t['status'] not in ('blocked','unverified','paused'): raise ValueError('只有受阻、待核验或暂停任务可重新排队')
            t.setdefault('attempts',[]).append({k:t.get(k) for k in ('result','receipt','finished_at','steps','milestones')})
            t.update(status='queued', milestones=[], wait_reason='', action='等待原助手重新观察', prior_steps=t.get('prior_steps',0)+t['steps'], steps=0)
            q.save()
        elif action == 'edit':
            async with self.transition, self.op:
                q.edit(data['id'], data.get('title'), data.get('instruction'), data.get('expected_title'), data.get('expected_instruction'))
        elif action == 'add':
            agent = next((a for a in self.known_agents() if a['id']==data.get('agent')), None)
            if not agent: raise ValueError('先接入一个助手，再将任务交给它')
            q.add(data.get('title',''), data.get('instruction',''), data['agent'], agent['name'])
        elif action == 'close_preference':
            if not isinstance(data.get('enabled'), bool): raise ValueError('设置值无效')
            q.data['settings']['close_pauses'] = data['enabled']
            q.event('关闭窗口后暂停已开启' if data['enabled'] else '允许关闭窗口后保留会话；助手仍需取得控制权')
        else:
            raise ValueError('未知操作')
        result = self.snapshot()
        if notice: result['notice'] = notice
        return result

    async def panel_loop(self):
        # Hardware status only: never read UI or wait behind a long Agent action.
        # The connected Device still owns the shared process-level lock.
        previous = None
        while True:
            if self.device.connected:
                try:
                    async with asyncio.timeout(4):
                        panel = await self.device.sample_panel()
                    if panel != previous and panel in ('on', 'off'):
                        self.queue.event('实体屏幕读回：' + ('亮屏' if panel == 'on' else '息屏'))
                    previous = panel
                except Exception:
                    self.device.panel_sampled = None
            else:
                previous = None
            await asyncio.sleep(1.5)

    async def activity_loop(self):
        previous = set()
        while True:
            if self.device.connected:
                await self.device.sample_activity()
                h = self.device.health_snapshot()
                audio = h.get('audio',{}).get('data',{})
                signals = {'摄像头':h.get('camera',{}).get('data',{}).get('active'),
                           '手电筒':h.get('torch',{}).get('data',{}).get('active'),
                           '麦克风':audio.get('microphone',{}).get('active'),
                           '系统录屏':h.get('projection',{}).get('data',{}).get('active'),
                           '通话音频':audio.get('call_active')}
                active = {k for k,v in signals.items() if v is True}
                for name in active - previous: self.queue.event(name + ('正在亮灯' if name == '手电筒' else '正在使用') + ('；静音不能保证通话无声' if name == '通话音频' else ''))
                for name in previous - active:
                    self.queue.event(name + ('已停止' if signals[name] is False else '状态暂时无法核验'))
                previous = active
            else: previous = set()
            await asyncio.sleep(2)

    async def monitor_loop(self):
        tick = 0
        while True:
            await asyncio.sleep(2)
            self.queue.expire()
            tick += 1
            if self.device.connected and tick % 5 == 0 and not self.op.locked():
                try:
                    async with self.op:
                        await self.device.sample()
                except Exception:
                    self.device.telemetry.update(quiet=None, haptic_disabled=None)
                    self.device.health.pop('settings',None)
            if self.closed_view_at and not self.device.watchers and time.monotonic()-self.closed_view_at > 12 and self.queue.data['settings']['close_pauses']:
                self.closed_view_at = None
                self.wanted, self.retry_at = False, None
                await self.transition_to('paused', '控制台已关闭，自动暂停；重新打开后手动继续')
                async with self.op: await self.device.close()
            if self.wanted and self.retry_at and time.monotonic() >= self.retry_at and (self.device.watchers or not self.queue.data['settings']['close_pauses']) and not self.op.locked():
                self.retry_at = None
                self.retries += 1
                try:
                    async with self.op:
                        await self.device.close()
                        await self.device.connect()
                    self.queue.owner = 'paused'
                    self.queue.event('连接已恢复；任务仍暂停，等待你交回助手')
                except Exception:
                    if self.retries < 3: self.retry_at = time.monotonic() + 30 * self.retries
                    else: self.queue.event('三次连接恢复未成功，请检查 USB 后点击重连')

    async def notification_loop(self):
        while True:
            await self.activity.tick(self.device.connected)
            await asyncio.sleep(1)


@web.middleware
async def secure(request, handler):
    c = request.app['console']
    if request.host != c.origin.removeprefix('http://'):
        raise web.HTTPForbidden(text='Invalid Host')
    origin = request.headers.get('Origin')
    if origin and origin != c.origin:
        raise web.HTTPForbidden(text='Invalid Origin')
    if request.path.startswith('/api/') or request.path == '/stream':
        token = request.headers.get('X-Phone-Token') or request.query.get('token', '')
        if not secrets.compare_digest(token, c.token):
            raise web.HTTPForbidden(text='Unauthorized local client')
    try:
        response = await handler(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        c.error = '操作超时；请先观察当前界面，不要重放输入' if isinstance(exc, TimeoutError) else str(exc)
        return web.json_response({'error': c.error}, status=409)


async def home(request):
    c = request.app['console']
    page = (WEB / 'index.html').read_text().replace('__PHONE_TOKEN__', c.token)
    return web.Response(text=page, content_type='text/html', headers={
        'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'"})


async def state(request):
    return web.json_response(request.app['console'].snapshot())


async def control(request):
    return web.json_response(await request.app['console'].control(await request.json()))


async def agent(request):
    c = request.app['console']
    payload = await request.json()
    if payload.get('action') == 'register':
        ident = payload.get('agent','')
        if not ident or len(ident) > 80 or not all(x.isalnum() or x in '-_' for x in ident):
            raise ValueError('助手标识只能包含字母、数字、横线')
        existing = c.agents.get(ident)
        # Same named integration reconnects to its queue, but invalidates its old lease.
        if existing and c.queue.lease and c.queue.lease['agent'] == ident:
            c.queue.invalidate('原助手重新连接，必须重新观察')
        token = secrets.token_urlsafe(32)
        c.agents[ident] = {'name': str(payload.get('name',ident))[:80], 'token': token, 'seen': time.monotonic()}
        return web.json_response({'agent': ident, 'agent_token':token})
    return web.json_response(await c.agent_request(payload))


async def authorized_control(request):
    """Compatibility CLI: same authenticated broker, no new agent registration.

    The console bearer is already checked by secure. Reuse the registered
    identity server-side without disclosing/rotating its private credential.
    All task/generation/one-use grant checks remain in agent_request.
    """
    c = request.app['console']
    payload = await request.json()
    registered = c.agents.get(payload.get('agent'))
    if not registered:
        raise PermissionError('请先通过原MCP客户端读取phone_status建立助手身份')
    return web.json_response(await c.agent_request({**payload,
        'action':'request_control', 'agent_token':registered['token']}))


async def stream(request):
    c = request.app['console']
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=32768, compress=False)
    await ws.prepare(request)
    c.closed_view_at = None
    c.device.watchers.add(ws)
    if c.device.width:
        await ws.send_json({'type':'size', 'width':c.device.width, 'height':c.device.height})
    if c.device.config_packet:
        await ws.send_bytes(c.device.config_packet)
        if c.device.connected: await c.device.send(bytes([17]))  # reset video produces a fresh key frame
    try:
        async for msg in ws:
            if msg.type != web.WSMsgType.TEXT: continue
            try:
                data = json.loads(msg.data)
                if data.get('type') == 'refresh':
                    if c.device.connected: await c.device.send(bytes([17]))
                    continue
                async with c.op:
                    if c.queue.owner != 'human' or data.get('generation') != c.queue.generation:
                        raise PermissionError('你还没有控制权，请先点击“我来操作”')
                    c.queue.revoke_continuations('人工操作改变现场：需重新检查阶段')
                    if data.get('type') == 'key': await c.device.key(int(data['code']))
                    elif data.get('type') == 'touch': await c.device.touch(int(data['action']), data['x'], data['y'], int(data['width']), int(data['height']))
                    elif data.get('type') == 'text': await c.device.text(data.get('text',''))
                    else: raise ValueError('未知手机输入')
                    c.device.observed_at = 0
            except (ValueError, RuntimeError, PermissionError, KeyError) as exc:
                await ws.send_json({'type':'error','message':str(exc)})
    finally:
        if ws.exception():
            print('Viewer socket error:', type(ws.exception()).__name__, str(ws.exception())[:160], flush=True)
        c.device.watchers.discard(ws)
        async with c.op:
            with contextlib.suppress(Exception): await c.device.release_touch()
        if not c.device.watchers: c.closed_view_at = time.monotonic()
    return ws


async def serve(config, state_dir):
    c = Console(config, state_dir)
    app = web.Application(middlewares=[secure], client_max_size=60000)
    app['console'] = c
    app.router.add_get('/', home)
    app.router.add_static('/static/', WEB)
    app.router.add_get('/api/state', state)
    app.router.add_post('/api/control', control)
    app.router.add_post('/api/agent', agent)
    app.router.add_post('/api/request-control', authorized_control)
    app.router.add_get('/stream', stream)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', config.get('port', 0))
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    c.origin = f'http://127.0.0.1:{port}'
    atomic(Path(state_dir)/'endpoint.json', {'url':c.origin,'token':c.token,'pid':__import__('os').getpid()})
    print(c.origin, flush=True)
    c.monitor = asyncio.create_task(c.monitor_loop())
    panel_monitor = asyncio.create_task(c.panel_loop())
    activity_monitor = asyncio.create_task(c.activity_loop())
    input_monitor = asyncio.create_task(c.inputs.run())
    app_monitor = asyncio.create_task(c.app_activity.run())
    notifications = asyncio.create_task(c.notification_loop())
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        c.monitor.cancel()
        panel_monitor.cancel()
        activity_monitor.cancel()
        input_monitor.cancel()
        app_monitor.cancel()
        notifications.cancel()
        await asyncio.gather(c.monitor, panel_monitor, activity_monitor, input_monitor, app_monitor, notifications, return_exceptions=True)
        c.queue.invalidate('服务结束，等待手动恢复')
        await c.transfer_jobs.close()
        async with c.op: await c.device.close()
        await asyncio.gather(*(ws.close() for ws in list(c.device.watchers)), return_exceptions=True)
        await runner.cleanup()
