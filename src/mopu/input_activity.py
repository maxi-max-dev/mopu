"""Read-only input capability probe. Never injects kernel input events."""
import asyncio
import hashlib
import re


def input_nodes(capabilities, devices, allow_candidates=False):
    metadata = {}
    for block in devices.split('\n\n'):
        handlers = re.search(r'^H: Handlers=(.*)', block, re.M)
        sysfs = re.search(r'^S: Sysfs=(.*)', block, re.M)
        bus = re.search(r'^I: Bus=(\w+)', block, re.M)
        if handlers:
            for event in re.findall(r'\bevent\d+\b', handlers[1]):
                metadata['/dev/input/'+event] = (sysfs[1] if sysfs else '', bus[1] if bus else '')
    result = []
    for block in re.split(r'(?=add device \d+:)', capabilities):
        path = re.search(r'^add device \d+: (/dev/input/event\d+)', block)
        name = re.search(r'name:\s*"([^"]+)"', block)
        if not path or not name: continue
        sysfs, bus = metadata.get(path[1], ('',''))
        # A built-in platform path excludes virtual, USB, Bluetooth and UHID devices.
        internal = sysfs.startswith('/devices/platform/') and not any(x in sysfs.lower() for x in ('/virtual/','/usb','/bluetooth','/uhid')) and bus in ('0000','0018','0019','001c')
        touch = all(x in block for x in ('ABS_MT_POSITION_X','ABS_MT_POSITION_Y','ABS_MT_TRACKING_ID','INPUT_PROP_DIRECT'))
        keys = [x for x in ('KEY_POWER','KEY_VOLUMEUP','KEY_VOLUMEDOWN') if re.search(r'\b'+x+r'\b',block)]
        # OEMs may hide topology even while getevent is readable. These nodes can
        # be observed for calibration, but must never be called physical proof.
        candidate = allow_candidates and not sysfs and not bus and (touch or bool(re.fullmatch(r'pmic_\w+|gpio-keys',name[1])))
        if not (internal or candidate) or not (touch or keys) or re.search(r'jack|headset',name[1],re.I): continue
        axes = {}
        for axis in ('X','Y'):
            m = re.search(r'ABS_MT_POSITION_'+axis+r'\s*:.*?min\s+(-?\d+), max\s+(-?\d+)',block)
            if m: axes[axis] = [int(m[1]),int(m[2])]
        result.append({'path':path[1],'name':name[1][:80],'kind':'touch' if touch else 'keys',
                       'keys':keys,'axes':axes,'topology_confirmed':internal,'fingerprint':hashlib.sha256((name[1]+sysfs+bus+str(axes)).encode()).hexdigest()[:20]})
    return result


async def probe_inputs(device):
    async with asyncio.timeout(15):
        return await _probe_inputs(device)


async def _probe_inputs(device):
    capabilities, devices = await asyncio.gather(device.shell('getevent','-pl'), device.shell('cat','/proc/bus/input/devices'), return_exceptions=True)
    if isinstance(capabilities, Exception):
        return {'readable':False, 'nodes':[], 'physical_verified':False, 'error':str(capabilities)}
    if isinstance(devices, Exception):
        async def metadata(node):
            event=node['path'].rsplit('/',1)[1]
            try:
                path, bus = await asyncio.gather(device.shell('readlink','-f','/sys/class/input/'+event+'/device'),
                                                device.shell('cat','/sys/class/input/'+event+'/device/id/bustype'))
                return 'H: Handlers='+event+'\nS: Sysfs='+path.removeprefix('/sys')+'\nI: Bus='+bus
            except RuntimeError:return ''
        blocks=await asyncio.gather(*(metadata(n) for n in input_nodes(capabilities,'',allow_candidates=True)))
        devices = '\n\n'.join(blocks)
    nodes = input_nodes(capabilities, devices, allow_candidates=True)
    return {'readable':bool(nodes), 'nodes':nodes, 'physical_verified':False,
            'note':'输入节点可读取；来源仍需实体触摸与远程输入对照' if nodes else '未发现可用于对照的输入节点'}


class GestureParser:
    """Keep transient coordinates in memory; emit only gesture categories."""
    def __init__(self,node):
        self.node=node;self.slot=0;self.active=False;self.started=0;self.origin=None;self.pos={};self.moved=False

    def frame(self):
        if self.origin is None:self.origin=dict(self.pos);return
        for axis,v in self.pos.items():
            self.origin.setdefault(axis,v)
            low,high=self.node['axes'].get(axis,[0,10000])
            if abs(v-self.origin[axis])>max(12,(high-low)*.015):self.moved=True

    def feed(self,line):
        m=re.search(r'\[\s*([\d.]+)\s*\]\s+(?:/dev/input/event\d+:\s+)?(EV_\w+)\s+(\w+)\s+(\w+)',line)
        if not m: return None
        stamp,typ,code,value=float(m[1]),m[2],m[3],m[4]
        if code=='SYN_DROPPED': raise ValueError('输入事件丢失，需重新核验')
        if code=='SYN_REPORT' and self.active:self.frame();return None
        if typ=='EV_KEY' and code in self.node['keys'] and value in ('DOWN','00000001'):
            return 'power' if code=='KEY_POWER' else 'volume'
        if self.node['kind']!='touch' or typ!='EV_ABS': return None
        if code=='ABS_MT_SLOT': self.slot=int(value,16);return None
        if self.slot!=0: return None
        if code=='ABS_MT_TRACKING_ID':
            if value.lower()=='ffffffff':
                if not self.active:return None
                self.frame()
                self.active=False
                return 'swipe' if self.moved else 'long_press' if stamp-self.started>=.5 else 'tap'
            self.active=True;self.started=stamp;self.origin=None;self.moved=False
        elif code in ('ABS_MT_POSITION_X','ABS_MT_POSITION_Y'):
            axis=code[-1];v=int(value,16);self.pos[axis]=v
        return None


class InputMonitor:
    def __init__(self,device,activity,idle):
        self.device,self.activity,self.idle=device,activity,idle
        self.processes=[]

    async def read(self,process,node):
        parser=GestureParser(node)
        while True:
            line=await process.stdout.readline()
            if not line: raise RuntimeError('输入事件通道已关闭')
            kind=parser.feed(line.decode(errors='replace'))
            if not self.device.connected or not self.activity.data['enabled']:return
            if kind:self.activity.record('device',kind,self.idle())

    async def close(self):
        for p in self.processes:
            if p.returncode is None:
                try:p.terminate()
                except ProcessLookupError:pass
        for p in self.processes:
            try:await asyncio.wait_for(p.wait(),2)
            except asyncio.TimeoutError:
                p.kill();await p.wait()
        self.processes=[]

    async def session(self):
        d,a=self.device,self.activity
        a.runtime.update(status='probing',error=None,nodes=[])
        probe=await probe_inputs(d)
        if not probe['readable']:raise RuntimeError(probe.get('error',probe['note'] if 'note' in probe else '无法读取输入节点'))
        nodes=probe['nodes']
        fingerprint=hashlib.sha256('|'.join(sorted(n['fingerprint'] for n in nodes)).encode()).hexdigest()
        readers=[]
        try:
            for node in nodes:
                if not d.connected or not d.lockfile:return
                p=await asyncio.create_subprocess_exec(d.config['adb'],'-s',d.serial,'shell','getevent','-lt',node['path'],
                    stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
                self.processes.append(p);readers.append(asyncio.create_task(self.read(p,node)))
            await asyncio.sleep(.25)
            if any(t.done() for t in readers):raise RuntimeError('输入事件通道无法持续读取')
            from .tasks import now
            a.runtime.update(status='listening',nodes=[{'name':n['name'],'kind':n['kind']} for n in nodes],fingerprint=fingerprint,at=now())
            while d.connected and a.data['enabled']:
                if any(t.done() for t in readers):
                    for t in readers:
                        if t.done():t.result()
                    raise RuntimeError('输入事件通道已停止')
                a.runtime['at']=now()
                await asyncio.sleep(1)
        finally:
            for t in readers:t.cancel()
            await asyncio.gather(*readers,return_exceptions=True)
            await self.close()
            a.runtime['status']='offline' if not d.connected else 'disabled' if not a.data['enabled'] else 'unavailable'

    async def run(self):
        while True:
            if self.device.connected and self.activity.data['enabled']:
                try:await self.session()
                except Exception as exc:
                    self.activity.runtime.update(status='unavailable',error=str(exc)[:180])
                    await asyncio.sleep(30)
            else:
                self.activity.runtime['status']='disabled' if not self.activity.data['enabled'] else 'offline'
            await asyncio.sleep(1)
