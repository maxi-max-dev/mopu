import asyncio
import contextlib
import json
import secrets
import signal
import time
from pathlib import Path
from aiohttp import web
from .device import Device
from .tasks import Queue, atomic, now
from .input_activity import probe_inputs, InputMonitor
from .activity import ActivityLog
from .app_activity import AppActivityMonitor

WEB = Path(__file__).parent / 'web'


class Console:
    def __init__(self, config, state):
        self.state_dir = Path(state)
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.queue = Queue(self.state_dir / 'queue.json')
        self.device = Device(config, self.state_dir)
        self.device.on_disconnect = self.disconnected
        self.op = asyncio.Lock()
        self.transition = asyncio.Lock()
        self.token = secrets.token_urlsafe(32)
        self.origin = ''
        self.agents = {}
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
        self.activity.apps.end('offline')
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
        return {**self.queue.snapshot(), 'activity':self.activity.snapshot(self.device.connected), 'device': {'connected': self.device.connected,
            'error': self.device.error, 'telemetry': telemetry, 'health': self.device.health_snapshot(), 'width': self.device.width,
            'height': self.device.height, 'geometry_note':'width/height describe the video stream only. Agent coordinates use mobile_get_screen_size and fresh element bounds; these can be larger.', 'frame_age': round(time.monotonic()-self.device.last_packet, 1) if self.device.last_packet else None},
            'agents': [{'id': k, 'name': a['name'], 'online': time.monotonic()-a['seen'] < 90} for k, a in self.agents.items()],
            'error': self.error, 'recovery': {'attempts':self.retries, 'pending':self.retry_at is not None}}

    async def transition_to(self, owner, reason):
        async with self.transition:
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
            return q.add(payload.get('title',''), payload.get('instruction',''), name, agent['name'])
        if action == 'status':
            return self.snapshot()
        if action == 'wait':
            for _ in range(50):
                if self.device.connected:
                    claim = q.claim(name)
                    if claim: return claim
                await asyncio.sleep(.4)
                agent['seen'] = time.monotonic()
            return {'waiting': True, 'owner': q.owner, 'head': q.head(), 'instruction': '等待人交回控制权或前序任务结束；可再次调用 phone_wait。不要另开控制通道。'}
        q.check(name, token)
        if action == 'input_probe':
            async with self.op:
                q.check(name, token)
                result = await probe_inputs(self.device)
                q.check(name, token)
                return result
        if action == 'checkpoint':
            q.checkpoint(name, token, payload.get('progress',''), payload.get('next_action',''))
            return {'saved': True}
        if action == 'finish':
            q.finish(name, token, payload.get('result',''), bool(payload.get('blocked')))
            return {'saved': True}
        if action in ('tools','call'):
            async with self.op:
                task = q.check(name, token)
                if task['steps'] >= 200:
                    q.finish(name, token, '已达200步上限，请缩小任务或人工检查', True)
                    raise RuntimeError('任务达到步数上限')
                task['steps'] += 1
                tool_name = payload.get('name','')
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
                        result = await self.device.backend(None if action == 'tools' else payload.get('name'), payload.get('arguments'), q.generation,
                                                           lambda: q.check(name, token), agent['name'])
                except Exception as exc:
                    self.device.observed_at = 0
                    if q.lease and q.lease['token'] == token:
                        q.checkpoint(name, token, task['checkpoint'], '工具失败，先重新观察；不要重复上一步')
                    raise exc
                q.check(name, token)  # Discard late results after human takeover.
                return result
        raise ValueError('未知助手动作')

    async def control(self, data):
        action = data.get('action')
        q = self.queue
        notice = None
        self.error = None
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
            async with self.transition:
                async with self.op:
                    if not self.device.connected:
                        await self.device.close()
                        await self.device.connect()
                    q.owner = 'human'
                    q.invalidate('新会话由你控制')
                    q.event('手机已连接，控制权归你')
                    self.wanted, self.retries, self.retry_at = True, 0, None
        elif action in ('takeover', 'pause', 'release'):
            if action == 'release' and not self.device.connected:
                raise ValueError('请先连接手机')
            owner = {'takeover':'human', 'release':'agent', 'pause':'paused'}[action]
            if action == 'pause' and q.owner == 'human': owner = 'human'
            await self.transition_to(owner, {'takeover':'手机交给你，助手停止读取和输入', 'release':'已交回原助手；下一步必须重新观察', 'pause':'全部手机任务已暂停'}[action])
        elif action in ('disconnect', 'reconnect'):
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
            if t['status'] != 'blocked': raise ValueError('只有受阻任务可重新排队')
            t.update(status='queued', action='等待原助手重新观察', prior_steps=t.get('prior_steps',0)+t['steps'], steps=0)
            q.save()
        elif action == 'add':
            agent = self.agents.get(data.get('agent'))
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
        async with c.op: await c.device.close()
        await asyncio.gather(*(ws.close() for ws in list(c.device.watchers)), return_exceptions=True)
        await runner.cleanup()
