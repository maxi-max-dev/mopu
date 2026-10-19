"""Pinned scrcpy 5.0.1 transport. All input passes through the console owner."""
import asyncio
import contextlib
import fcntl
import json
import os
import re
import secrets
import signal
import struct
import time
from pathlib import Path
from .tasks import atomic, now
from .feedback import KEYS, COORDINATE_TOOLS, describe, screen_size
from .health import audio_status, camera_status, torch_status, microphone_status, projection_status, battery_status, quiet_settings, SETTINGS

ALLOWED = {'mobile_list_apps', 'mobile_get_foreground_app', 'mobile_launch_app',
           'mobile_get_screen_size', 'mobile_click_on_screen_at_coordinates', 'mobile_double_tap_on_screen',
           'mobile_long_press_on_screen_at_coordinates', 'mobile_list_elements_on_screen', 'mobile_press_button',
           'mobile_open_url', 'mobile_swipe_on_screen', 'mobile_type_keys', 'mobile_take_screenshot', 'mobile_get_orientation'}
OBSERVE = {'mobile_list_elements_on_screen', 'mobile_take_screenshot'}


def physical_panel(sf):
    """Only physical internal display paragraphs count; virtual/cached ON does not."""
    modes = []
    for match in re.finditer(r'^Display \d+\n((?:[ \t].*\n)*)', sf + '\n', re.M):
        block = match[1]
        if 'connectionType=Internal' in block:
            mode = re.search(r'powerMode=(Off|On|DozeSuspend|Doze|\d+)\b', block, re.I)
            modes.append(mode[1].lower() if mode else 'unknown')
    # Older SurfaceFlinger layout: keep each device block isolated.
    for block in re.findall(r'DisplayDevice\{(.*?)(?=DisplayDevice\{|\Z)', sf, re.S):
        if re.search(r'isVirtual=(?:false|0)\b', block[:1500]) or re.search(r'Physical display', block[:500], re.I):
            mode = re.search(r'powerMode[=:]\s*(Off|On|DozeSuspend|Doze|\d+)\b', block[:2500], re.I)
            modes.append(mode[1].lower() if mode else 'unknown')
    lit = {'on', 'doze', 'dozesuspend', '1', '2', '3', '4'}
    panel = 'on' if any(x in lit for x in modes) else 'off' if modes and all(x in ('off','0') for x in modes) else 'unknown'
    return panel, modes


class Device:
    def __init__(self, config, state):
        self.config, self.state = config, Path(state)
        self.serial = config['serial']
        self.lockfile = None
        self.process = None
        self.video_writer = self.control = None
        self.video_task = self.control_task = None
        self.port = None
        self.connected = False
        self.width = self.height = 0
        self.config_packet = None
        self.watchers = set()
        self.error = None
        self.telemetry = {}
        self.observed_at = 0
        self.observed_generation = None
        self.last_packet = 0
        self.on_disconnect = None
        self.active_touch = None
        self.panel_lock = asyncio.Lock()
        self.panel_sampled = None
        self.health = {}
        self.health_lock = asyncio.Lock()
        self.action_epoch = 0
        self.touch_feedback = None
        self.on_action = None

    def new_action(self, description, source='human', actor='你'):
        return {'type':'action', 'id':secrets.token_hex(6), 'epoch':self.action_epoch,
                'source':source, 'actor':str(actor)[:48], **description}

    async def publish_action(self, cue, phase='sent'):
        if cue and cue['epoch'] == self.action_epoch:
            if self.on_action: self.on_action(cue,phase)
            await self.broadcast(json.dumps({**cue,'phase':phase,'at':time.time()*1000}))

    async def clear_actions(self):
        self.action_epoch += 1
        self.touch_feedback = None
        await self.broadcast(json.dumps({'type':'action_clear'}))

    async def adb(self, *args, timeout=12):
        p = await asyncio.create_subprocess_exec(self.config['adb'], *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(p.communicate(), timeout)
        except asyncio.TimeoutError:
            p.kill(); await p.wait()
            raise RuntimeError('ADB 操作超时；先检查现场，不能重放输入')
        except asyncio.CancelledError:
            with contextlib.suppress(ProcessLookupError): p.kill()
            await p.wait()
            raise
        if p.returncode:
            raise RuntimeError('ADB 操作失败：' + stderr.decode(errors='replace')[:160])
        return stdout.decode(errors='replace').strip()

    async def shell(self, *args):
        return await self.adb('-s', self.serial, 'shell', *args)

    async def acquire(self):
        lockpath = Path(self.config.get('operation_lock', self.state / 'operation.lock'))
        lockpath.parent.mkdir(parents=True, exist_ok=True)
        self.lockfile = lockpath.open('a+')
        try:
            fcntl.flock(self.lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lockfile.close(); self.lockfile = None
            raise RuntimeError('手机正由旧窗口或另一操作使用，请先关闭那个控制窗口')
        listing = await self.adb('devices', '-l')
        if not any(line.startswith(self.serial + ' ') or line.startswith(self.serial + '\t') for line in listing.splitlines() if re.search(r'\bdevice\b.*\busb:', line)):
            raise RuntimeError('已绑定手机未通过 USB 在线连接')

    async def quiet(self):
        zen = await self.shell('settings', 'get', 'global', 'zen_mode')
        volume = await self.shell('cmd', 'media_session', 'volume', '--stream', '3', '--get')
        match = re.search(r'volume is (\d+) in range', volume)
        if zen not in ('0', '1', '2', '3') or not match:
            raise RuntimeError('无法核实静音状态')
        keys = SETTINGS
        values = {}
        for namespace, names in keys.items():
            for name in names:
                val = await self.shell('settings', 'get', namespace, name)
                if val.isdigit():
                    values[namespace + '/' + name] = val
        backup = self.state / ('quiet-original-' + re.sub(r'[^A-Za-z0-9_-]', '_', self.serial) + '.json')
        original = json.loads(backup.read_text()) if backup.exists() else {'serial':self.serial, 'at':now(), 'zen':zen, 'media_volume':int(match.group(1)), 'settings':{}}
        for key, value in values.items(): original['settings'].setdefault(key,value)
        atomic(backup,original)
        if zen != '2':
            await self.shell('cmd', 'notification', 'set_dnd', 'none')
        if match.group(1) != '0':
            await self.shell('cmd', 'media_session', 'volume', '--stream', '3', '--set', '0')
        for key, value in values.items():
            ns, name = key.split('/')
            if value != '0':
                await self.shell('settings', 'put', ns, name, '0')
            if await self.shell('settings', 'get', ns, name) != '0':
                raise RuntimeError('无振动设置未通过读回：' + name)
        audio = await self.shell('dumpsys', 'audio')
        details = audio_status(audio)
        # The MediaSession shell may acknowledge a call-volume write without applying it.
        # Android's audio shell is separately verified; no fallback/replay after uncertainty.
        if details['call_active'] is False:
            call_backup = self.state / ('quiet-call-original-' + re.sub(r'[^A-Za-z0-9_-]', '_', self.serial) + '.json')
            original = json.loads(call_backup.read_text()) if call_backup.exists() else {'at':now()}
            for key,name,stream in (('voice_call','VOICE_CALL','0'),('bluetooth_sco','BLUETOOTH_SCO','6')):
                before = details['streams'][name]
                if before['silent'] is None: continue
                original.setdefault(key,before)
                atomic(call_backup,original)
                if before['silent'] is not True:
                    if before['min'] is not None and before['volume'] is not None and before['volume'] > before['min']:
                        await self.shell('cmd','audio','set-volume',stream,str(before['min']))
                    await self.shell('cmd','audio','adj-mute',stream)
            # Asynchronous AudioService changes can settle after the command returns.
            for _ in range(4):
                audio = await self.shell('dumpsys','audio')
                details = audio_status(audio)
                if all(details['streams'][n]['silent'] for n in ('VOICE_CALL','BLUETOOTH_SCO')): break
                await asyncio.sleep(.15)
        streams = {}
        for name in ('SYSTEM', 'RING', 'MUSIC', 'ALARM', 'NOTIFICATION', 'DTMF', 'SYSTEM_ENFORCED'):
            block = re.search(r'^- STREAM_' + name + r'(?::| \(aliased[^\n]*\):)\n(.*?)(?=^\S|\Z)', audio, re.M | re.S)
            streams[name] = bool(block and (re.search(r'^\s+Muted(?: Internally)?: true$', block[1], re.M) or re.search(r'^\s+streamVolume:0$', block[1], re.M)))
        if not all(streams.values()):
            raise RuntimeError('音频静音未通过读回')
        result = {'at': now(), 'streams': streams, 'haptic_settings': list(values), 'verified': True,
                  'voice_call': details['streams']['VOICE_CALL'], 'bluetooth_sco':details['streams']['BLUETOOTH_SCO'],
                  'limitation': '基础音频和通话通道分别读回；通话接通或切换输出可能改变状态，未做真实拨号和声学测量'}
        atomic(self.state / 'quiet-verification.json', result)
        return result

    async def connect(self):
        if self.connected:
            return
        self.error = None
        try:
            await self.acquire()
            await self.quiet()
            power = await self.shell('dumpsys', 'power')
            m = re.search(r'mWakefulness=(\w+)', power)
            if not m:
                raise RuntimeError('无法核实手机休眠状态')
            if m[1] != 'Awake':
                await self.shell('input', 'keyevent', 'KEYCODE_WAKEUP')
                if 'mWakefulness=Awake' not in await self.shell('dumpsys', 'power'):
                    raise RuntimeError('手机未唤醒；可能需要解锁')
            scid = secrets.randbits(31)
            remote = '/data/local/tmp/phone-harness-scrcpy-5.0.1.jar'
            await self.adb('-s', self.serial, 'push', self.config['scrcpy_server'], remote)
            self.port = int(await self.adb('-s', self.serial, 'forward', 'tcp:0', f'localabstract:scrcpy_{scid:08x}'))
            log = (self.state / 'transport.log').open('ab')
            try:
                self.process = await asyncio.create_subprocess_exec(self.config['adb'], '-s', self.serial, 'shell',
                    'CLASSPATH=' + remote, 'app_process', '/', 'com.genymobile.scrcpy.Server', '5.0.1',
                    f'scid={scid:08x}', 'tunnel_forward=true', 'audio=false', 'control=true',
                    'video_codec=h264', 'max_size=1600', 'max_fps=60', 'video_bit_rate=8000000',
                    'send_device_meta=false', 'clipboard_autosync=false', 'power_on=false',
                    'keep_active=true', 'power_off_on_close=true', 'log_level=warn',
                    stdout=log, stderr=log, start_new_session=True, pass_fds=(self.lockfile.fileno(),))
            finally:
                log.close()
            for attempt in range(30):
                try:
                    reader, writer = await asyncio.open_connection('127.0.0.1', self.port)
                    if await asyncio.wait_for(reader.readexactly(1), 1) == b'\0':
                        self.video_writer = writer
                        break
                    writer.close()
                except (OSError, asyncio.IncompleteReadError, asyncio.TimeoutError):
                    if 'writer' in locals(): writer.close()
                await asyncio.sleep(.1)
            else:
                raise RuntimeError('视频服务连接失败')
            control_reader, self.control = await asyncio.open_connection('127.0.0.1', self.port)
            codec = await asyncio.wait_for(reader.readexactly(4), 8)
            if codec != b'h264':
                raise RuntimeError('视频编码握手失败')
            self.connected = True
            await self.send(bytes([10, 0]))
            self.control_task = asyncio.create_task(self.drain_control(control_reader))
            self.video_task = asyncio.create_task(self.video_loop(reader))
            self.observed_at = 0
            await self.sample()
        except Exception as exc:
            self.error = str(exc)
            await self.close()
            raise

    async def drain_control(self, reader):
        try:
            while await reader.read(65536):
                pass  # Clipboard autosync disabled. Never expose phone clipboard.
        except (OSError, asyncio.CancelledError):
            pass

    async def video_loop(self, reader):
        try:
            while self.connected:
                header = await reader.readexactly(12)
                if header[0] & 0x80:
                    self.width, self.height = struct.unpack('>II', header[4:])
                    self.config_packet = None
                    await self.broadcast(json.dumps({'type': 'size', 'width': self.width, 'height': self.height}))
                    continue
                length = struct.unpack('>I', header[8:])[0]
                if length > 16_000_000:
                    raise RuntimeError('视频包过大')
                data = await reader.readexactly(length)
                self.last_packet = time.monotonic()
                packet = header + data
                if header[0] & 0x40:
                    self.config_packet = packet
                await self.broadcast(packet)
        except (asyncio.IncompleteReadError, OSError, RuntimeError) as exc:
            self.error = '手机画面连接中断'
            self.connected = False
            if self.on_disconnect:
                self.on_disconnect()
        except asyncio.CancelledError:
            pass

    async def broadcast(self, payload):
        # Slow viewers are disconnected rather than retaining an ever-growing video queue.
        async def one(ws):
            try:
                send = ws.send_bytes(payload) if isinstance(payload, bytes) else ws.send_str(payload)
                await asyncio.wait_for(send, .5)
            except Exception:
                self.watchers.discard(ws)
                await ws.close()
        await asyncio.gather(*(one(ws) for ws in list(self.watchers)))

    async def send(self, data):
        if not self.connected or not self.control:
            raise RuntimeError('手机未连接')
        self.control.write(data)
        await self.control.drain()

    async def key(self, code):
        if code not in (3, 4, 19, 20, 21, 22, 61, 66, 67, 111, 122, 123, 187):
            raise ValueError('不支持的按键')
        for action in (0, 1):
            await self.send(struct.pack('>BBIII', 0, action, code, 0, 0))
        await self.publish_action(self.new_action({'kind':'key','label':KEYS[code],'points':[],'video':[self.width,self.height]}))

    async def touch(self, action, x, y, width, height):
        if action not in (0, 1, 2) or (width, height) != (self.width, self.height):
            raise ValueError('画面尺寸已变化，请在新画面重试')
        x, y = max(0, min(int(x), width-1)), max(0, min(int(y), height-1))
        await self.send(struct.pack('>BBQiiHHHII', 2, action, (1 << 64)-2, x, y, width, height, 0 if action == 1 else 65535, 0, 0))
        self.active_touch = (x,y,width,height) if action != 1 else None
        point = [x/width,y/height]
        if action == 0:
            self.touch_feedback = {'cue':self.new_action({'kind':'tap','label':'按下','points':[point],'video':[width,height]}),
                                   'started':time.monotonic(),'broadcast':0}
        touch = self.touch_feedback
        if touch:
            cue = touch['cue']
            if point != cue['points'][-1]: cue['points'].append(point)
            if len(cue['points']) > 64: cue['points'] = cue['points'][:1]+cue['points'][1:-1:2]+cue['points'][-1:]
            moved = any(abs(p[0]-cue['points'][0][0])*width+abs(p[1]-cue['points'][0][1])*height > 12 for p in cue['points'])
            held = time.monotonic()-touch['started'] > .5
            cue['kind'],cue['label'] = ('swipe','滑动') if moved else ('hold','长按') if held else ('tap','点击' if action==1 else '按下')
            if action != 2 or time.monotonic()-touch['broadcast'] > .04:
                await self.publish_action(cue,'sent' if action==1 else 'touch')
                touch['broadcast'] = time.monotonic()
            if action == 1: self.touch_feedback = None

    async def release_touch(self):
        if self.active_touch and self.connected:
            await self.touch(1, *self.active_touch)
        self.active_touch = None

    async def text(self, text):
        data = str(text).encode()
        if not data or len(data) > 10000:
            raise ValueError('文本为空或过长')
        # Explicit user text only. Paste flag does not submit the field.
        await self.send(struct.pack('>BQB I', 9, 0, 1, len(data)) + data)
        await self.publish_action(self.new_action({'kind':'text','label':'输入文字','points':[],'video':[self.width,self.height]}))

    async def sample_panel(self):
        async with self.panel_lock:
            try:
                panel, modes = physical_panel(await self.shell('dumpsys', 'SurfaceFlinger'))
                self.panel_sampled = time.monotonic()
                self.telemetry.update(panel=panel, panel_at=now(), panel_modes=modes,
                                      panel_source='SurfaceFlinger physical internal display')
                return panel
            except Exception:
                self.panel_sampled = None
                self.telemetry.update(panel='unknown', panel_at=None, panel_modes=[])
                raise

    async def set_panel(self, on):
        if not isinstance(on, bool): raise ValueError('屏幕状态必须为亮屏或息屏')
        await self.send(bytes([10, int(on)]))  # scrcpy 5.0.1: explicit boolean, never a power-key toggle.
        self.observed_at = 0
        expected = 'on' if on else 'off'
        for _ in range(8):
            if await self.sample_panel() == expected: return
            await asyncio.sleep(.2)  # Read back only; never resend an uncertain action.
        raise RuntimeError('亮灭屏指令已发出，但实际状态未确认；请看右侧指示灯，不要连续重复点击')

    async def rotate(self):
        await self.release_touch()
        before = (self.width, self.height)
        self.observed_at = 0
        await self.send(bytes([11]))  # Native Android orientation, preserving its auto-rotation preference.
        for _ in range(20):
            await asyncio.sleep(.15)
            if (self.width, self.height) != before: return True
        return False  # A portrait-only app/lock screen can keep its current layout.

    def health_snapshot(self):
        result = {}
        for key, entry in self.health.items():
            age = time.monotonic() - entry['sampled'] if entry.get('sampled') is not None else None
            fresh = bool(self.connected and age is not None and age <= (20 if key in ('battery','settings') else 7))
            result[key] = {'at':entry.get('at'), 'age':round(age,2) if age is not None else None,
                          'fresh':fresh, 'data':entry.get('data',{}) if fresh else {}, 'error':entry.get('error')}
        return result

    async def read_health(self, key, command, parser):
        session = self.lockfile
        try:
            async with asyncio.timeout(4):
                raw = await self.shell(*command)
            data = parser(raw)
            if self.lockfile is session and self.connected:
                self.health[key] = {'data':data, 'at':now(), 'sampled':time.monotonic()}
            return data
        except Exception:
            if self.lockfile is session:
                previous = self.health.get(key,{})
                self.health[key] = {**previous,'sampled':None,'error':'读取失败，状态待核验'}
            return {}

    async def sample_activity(self):
        async with self.health_lock:
            await asyncio.gather(
                self.read_health('audio', ('dumpsys','audio'),
                    lambda text: {**audio_status(text), 'microphone':microphone_status(text)}),
                self.read_health('camera', ('dumpsys','media.camera'), camera_status),
                self.read_health('torch', ('dumpsys','activity','service','com.android.systemui/.SystemUIService','FlashlightControllerImpl'), torch_status),
                self.read_health('projection', ('dumpsys','media_projection'), projection_status))

    async def sample(self):
        session = self.lockfile
        power, _, battery, system, glob = await asyncio.gather(
            self.shell('dumpsys','power'), self.sample_panel(),
            self.read_health('battery', ('dumpsys','battery'), battery_status),
            self.shell('settings','list','system'), self.shell('settings','list','global'))
        if self.lockfile is not session or not self.connected: return self.telemetry
        settings = quiet_settings(system,glob)
        self.health['settings'] = {'data':settings,'at':now(),'sampled':time.monotonic()}
        m = re.search(r'mWakefulness=(\w+)',power)
        self.telemetry.update({'at':now(), 'battery':battery.get('percent'),
            'temperature':battery.get('temperature'), 'wakefulness':m[1] if m else None,
            'quiet':settings['zen_mode'] == 2 if settings['zen_mode'] is not None else None,
            'haptic_disabled':settings['haptic_feedback_enabled'] == 0 if settings['haptic_feedback_enabled'] is not None else None})
        return self.telemetry

    async def agent_swipe(self, arguments, generation, guard, actor):
        """Use the console's scrcpy touch channel, inside the existing lease.

        Never fall back to ADB or replay on transport failure. UP is cleanup only.
        """
        if time.monotonic()-self.observed_at > 120 or self.observed_generation != generation:
            raise PermissionError('需要新观察；请先读取当前界面')
        video = (self.width, self.height)
        natural = screen_size(await self.shell('wm', 'size'))
        if not natural or not all(video): raise ValueError('无法核实输入坐标尺寸')
        w,h = (max(natural),min(natural)) if video[0]>video[1] else (min(natural),max(natural))
        if abs((w/h)/(video[0]/video[1])-1) > .025: raise ValueError('画面与输入尺寸不一致，请重新观察')
        a = dict(arguments)
        direction = a.get('direction')
        if direction not in ('up','down','left','right'): raise ValueError('无效滑动方向')
        if ('x' in a) != ('y' in a): raise ValueError('起点必须同时包含x和y')
        if 'x' not in a:
            a['x'],a['y'] = {'up':(w*.5,h*.8),'down':(w*.5,h*.2),'left':(w*.8,h*.5),'right':(w*.2,h*.5)}[direction]
            a.setdefault('distance',(h if direction in ('up','down') else w)*.6)
        import math
        for field in ('x','y','distance'):
            if field in a and (isinstance(a[field],bool) or not isinstance(a[field],(int,float)) or not math.isfinite(a[field])):
                raise ValueError('滑动坐标和距离必须是有限数字')
        distance=a.get('distance',(h if direction in ('up','down') else w)*.3)
        if not 0<=a['x']<w or not 0<=a['y']<h or distance<=0 or distance>max(w,h):
            raise ValueError('滑动起点或距离越界')
        x,y=a['x'],a['y']
        ex,ey={'up':(x,max(0,y-distance)),'down':(x,min(h-1,y+distance)),
               'left':(max(0,x-distance),y),'right':(min(w-1,x+distance),y)}[direction]
        points=[[x/w,y/h],[ex/w,ey/h]]
        cue=self.new_action({'kind':'swipe','label':{'up':'向上滑动','down':'向下滑动','left':'向左滑动','right':'向右滑动'}[direction],
                             'points':points,'video':list(video)},'agent',actor)
        started=False;last=(0,0)
        async def packet(action, px, py):
            await self.send(struct.pack('>BBQiiHHHII',2,action,(1<<64)-2,px,py,*video,0 if action==1 else 65535,0,0))
        try:
            for i in range(21):
                if guard: guard()
                if video!=(self.width,self.height): raise ValueError('画面尺寸已变化，请重新观察')
                last=(min(video[0]-1,int((x+(ex-x)*i/20)/w*video[0])),min(video[1]-1,int((y+(ey-y)*i/20)/h*video[1])))
                self.observed_at=0
                started=True
                await packet(0 if i==0 else 2,*last)
                if i==0: await self.publish_action(cue)
                if i<20: await asyncio.sleep(.018)
            if guard: guard()
            await self.publish_action(cue,'returned')
            return {'content':[{'type':'text','text':'Swipe dispatched through console touch channel; read the screen to verify the outcome.'}]}
        except (Exception, asyncio.CancelledError):
            if started: await self.publish_action(cue,'uncertain')
            raise
        finally:
            if started:
                # Release only; never send another DOWN/MOVE after lease loss.
                await packet(1,*last)

    async def backend(self, name=None, arguments=None, generation=None, guard=None, actor='助手'):
        if not self.connected or not self.lockfile:
            raise RuntimeError('手机未连接')
        if name is not None and name not in ALLOWED:
            raise ValueError('不支持此工具')
        arguments = dict(arguments or {})
        if 'ref' in arguments:
            raise ValueError('此后端的元素ref不可靠，请用新观察坐标')
        if arguments.get('device') not in (None, self.serial):
            raise PermissionError('只能操作绑定的手机')
        if name == 'mobile_type_keys' and arguments.get('submit'):
            raise ValueError('输入与提交必须分开；此入口不自动提交')
        if name == 'mobile_press_button' and arguments.get('button') not in ('BACK','HOME','ENTER','DPAD_CENTER','DPAD_UP','DPAD_DOWN','DPAD_LEFT','DPAD_RIGHT'):
            raise ValueError('此会话不允许电源或音量按键改变安静状态')
        if name == 'mobile_type_keys':
            text = arguments.get('text')
            if not isinstance(text,str) or not text or len(text.encode())>10000:
                raise ValueError('文字须为1至10000字节，提交必须分开')
            if time.monotonic()-self.observed_at>120 or self.observed_generation!=generation:
                raise PermissionError('需要新观察；请先读取当前界面')
            if guard: guard()
            self.observed_at=0
            data=text.encode()
            cue=self.new_action({'kind':'text','label':'输入文字','points':[],'video':[self.width,self.height]},'agent',actor)
            try:
                await self.send(struct.pack('>BQBI',9,0,1,len(data))+data)
                await self.publish_action(cue,'returned')
            except (Exception,asyncio.CancelledError):
                await self.publish_action(cue,'uncertain')
                raise
            return {'content':[{'type':'text','text':'Text paste dispatched through console clipboard channel; verify the field. No submit was sent.'}]}
        if name == 'mobile_swipe_on_screen':
            return await self.agent_swipe(arguments, generation, guard, actor)
        process = await asyncio.create_subprocess_exec(*self.config['backend_command'], stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            env=dict(os.environ, MOBILEMCP_DISABLE_TELEMETRY='1', PATH=str(Path(self.config['adb']).parent)+os.pathsep+os.environ.get('PATH','')),
            start_new_session=True, limit=24_000_000)
        ident = 0
        async def request(method, params, on_sent=None):
            nonlocal ident
            ident += 1
            process.stdin.write((json.dumps({'jsonrpc':'2.0','id':ident,'method':method,'params':params})+'\n').encode())
            await process.stdin.drain()
            if on_sent: await on_sent()
            while True:
                line = await asyncio.wait_for(process.stdout.readline(), 45)
                if not line: raise RuntimeError('手机工具后端退出')
                reply = json.loads(line)
                if reply.get('id') == ident:
                    if 'error' in reply: raise RuntimeError('手机工具后端返回错误')
                    return reply['result']
        submitted = False
        readonly = True
        cue = None
        try:
            await request('initialize', {'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'mopu','version':'0.14.0'}})
            process.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
            catalog = await request('tools/list', {})
            catalog['tools'] = [t for t in catalog['tools'] if t['name'] in ALLOWED]
            for tool in catalog['tools']:
                schema = tool.get('inputSchema', {})
                schema.get('properties', {}).pop('device', None)
                schema['required'] = [p for p in schema.get('required', []) if p != 'device']
                if 'ref' in schema.get('properties', {}):
                    schema['properties'].pop('ref', None)
                    schema['required'] = list(dict.fromkeys(schema.get('required', []) + ['x', 'y']))
                    tool['description'] = 'Use fresh observed x,y screen coordinates. Element refs are disabled for this backend.'
                    for axis in ('x','y'):
                        schema['properties'][axis]['description'] = 'Fresh screen coordinate in device pixels'
                if tool['name'] == 'mobile_list_elements_on_screen':
                    tool['description'] = 'Observe current text and device coordinates. Reobserve after every input; do not use refs.'
                if tool['name'] == 'mobile_press_button':
                    schema['properties']['button']['enum'] = ['BACK','HOME','ENTER','DPAD_CENTER','DPAD_UP','DPAD_DOWN','DPAD_LEFT','DPAD_RIGHT']
                    schema['properties']['button']['description'] = 'Navigation key; volume and power controls are excluded'
            if name is None: return catalog
            tool = next((t for t in catalog['tools'] if t['name'] == name), None)
            if not tool: raise ValueError('后端未提供此工具')
            readonly = tool.get('annotations', {}).get('readOnlyHint', False)
            if not readonly and (time.monotonic()-self.observed_at > 120 or self.observed_generation != generation):
                raise PermissionError('需要新观察；请先读取当前界面')
            if not readonly: self.observed_at = 0
            description = describe(name, arguments, video=(self.width,self.height)) if not readonly else None
            if description and name in COORDINATE_TOOLS:
                # This is a read-only metadata probe inside the existing owner/lock.
                # If it fails, input still follows its original path, with label-only feedback.
                with contextlib.suppress(Exception):
                    async with asyncio.timeout(2):
                        natural = screen_size(await self.shell('wm','size'))
                    description = describe(name, arguments, natural, (self.width,self.height))
            if guard: guard()  # Takeover during MCP startup must block not-yet-sent input.
            if description: cue = self.new_action(description, 'agent', actor)
            arguments['device'] = self.serial
            submitted = True
            result = await request('tools/call', {'name':name,'arguments':arguments},
                                   (lambda: self.publish_action(cue)) if cue else None)
            if cue: await self.publish_action(cue,'uncertain' if result.get('isError') else 'returned')
            if name in OBSERVE and not result.get('isError'):
                parts = result.get('content', [])
                valid = any(p.get('type') == 'image' and p.get('data') for p in parts)
                for p in parts:
                    text = p.get('text', '')
                    if re.search(r' at=-?[\d.]+,-?[\d.]+ size=[\d.]+x[\d.]+', text): valid = True
                    if text.startswith('Found these elements on screen: '):
                        try: valid |= bool(json.loads(text.split(': ',1)[1]))
                        except ValueError: pass
                if valid:
                    self.observed_at, self.observed_generation = time.monotonic(), generation
            return result
        except (Exception, asyncio.CancelledError):
            if submitted and not readonly: self.observed_at = 0
            if submitted and cue: await self.publish_action(cue,'uncertain')
            raise
        finally:
            with contextlib.suppress(ProcessLookupError): os.killpg(process.pid, signal.SIGTERM)
            try: await asyncio.wait_for(process.wait(), 2)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError): os.killpg(process.pid, signal.SIGKILL)
                await process.wait()

    async def close(self):
        await self.clear_actions()
        with contextlib.suppress(Exception): await self.release_touch()
        self.connected = False
        for task in (self.video_task, self.control_task):
            if task and task is not asyncio.current_task(): task.cancel()
        for writer in (self.control, self.video_writer):
            if writer: writer.close()
        if self.process and self.process.returncode is None:
            with contextlib.suppress(ProcessLookupError): os.killpg(self.process.pid, signal.SIGTERM)
            try: await asyncio.wait_for(self.process.wait(), 3)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError): os.killpg(self.process.pid, signal.SIGKILL)
                await self.process.wait()
        if self.port:
            with contextlib.suppress(Exception): await self.adb('-s', self.serial, 'forward', '--remove', f'tcp:{self.port}')
        if self.lockfile: self.lockfile.close()
        self.lockfile = self.control = self.video_writer = self.process = None
        self.port = None
        self.observed_at = 0
        self.width = self.height = 0
        self.config_packet = None
        self.telemetry = {}
        self.health = {}
        self.panel_sampled = None
