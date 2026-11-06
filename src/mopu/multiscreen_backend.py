"""Shared transport for lease-scoped experimental secondary displays."""
import asyncio, contextlib, json, os, re, secrets, shlex, struct, time, shutil
from pathlib import Path
from .tasks import atomic

class Screen:
    def __init__(self,b,name):self.b=b;self.name=name;self.scid=secrets.randbits(31);self.port=None;self.proc=None;self.writers=[];self.video=None;self.display=None;self.decoder=None
    async def start(self):
        b=self.b;c=b.c.device.config
        remote=f'/data/local/tmp/codex-ms-{self.scid:08x}.jar'
        await b.adb('push',c['scrcpy_server'],remote)
        self.port=int(await b.adb('forward','tcp:0',f'localabstract:scrcpy_{self.scid:08x}'))
        self.resource={'display':None,'scid':f'{self.scid:08x}','forward':self.port,'host_pid':None};b.manifest.append(self.resource);atomic(b.folder/'resources.json',b.manifest)
        self.logpath=b.folder/(self.name+'.log');self.log=self.logpath.open('wb');self.rawpath=b.folder/(self.name+'.h264');self.raw=self.rawpath.open('wb')
        b.guard()
        self.proc=await asyncio.create_subprocess_exec(c['adb'],'-s',c['serial'],'shell','CLASSPATH='+remote,'app_process','/','com.genymobile.scrcpy.Server','5.0.1',f'scid={self.scid:08x}','tunnel_forward=true','audio=false','control=true','video_codec=h264','max_fps=5','video_bit_rate=1000000','send_device_meta=false','clipboard_autosync=false','power_on=false','stay_awake=false','power_off_on_close=false','new_display=720x1280/240','display_ime_policy=local','log_level=debug',stdout=self.log,stderr=self.log)
        self.resource['host_pid']=self.proc.pid;atomic(b.folder/'resources.json',b.manifest)
        for _ in range(40):
            b.guard()
            try:
                self.reader,w=await asyncio.open_connection('127.0.0.1',self.port);self.writers.append(w)
                if await asyncio.wait_for(self.reader.readexactly(1),1)!=b'\0':raise RuntimeError('invalid handshake')
                break
            except (OSError,asyncio.TimeoutError,asyncio.IncompleteReadError):await asyncio.sleep(.1)
        else:raise RuntimeError('scrcpy handshake failed')
        self.cr,self.cw=await asyncio.open_connection('127.0.0.1',self.port);self.writers.append(self.cw)
        if await self.reader.readexactly(4)!=b'h264':raise RuntimeError('codec mismatch')
        for _ in range(30):
            m=re.search(r'\(id=(\d+)\)',self.logpath.read_text())
            if m:break
            await asyncio.sleep(.1)
        if not m:raise RuntimeError('display not confirmed')
        self.display=int(m[1])
        self.framepath=b.folder/(self.name+'-latest.png')
        self.decoder=await asyncio.create_subprocess_exec(shutil.which('ffmpeg') or 'ffmpeg','-loglevel','error','-probesize','32','-analyzeduration','0','-flags','low_delay','-f','h264','-i','pipe:0','-fps_mode','passthrough','-update','1','-atomic_writing','1','-y',str(self.framepath),stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.DEVNULL,stderr=self.log)
        self.video=asyncio.create_task(self.read())
        self.resource['display']=self.display
        atomic(b.folder/'resources.json',b.manifest)
    async def read(self):
        while True:
            h=await self.reader.readexactly(12)
            if h[0]&0x80:self.size=struct.unpack('>II',h[4:]);continue
            n=struct.unpack('>I',h[8:])[0]
            if n>16000000:raise RuntimeError('video packet size limit')
            data=await self.reader.readexactly(n)
            if self.raw.tell()<8_000_000:self.raw.write(data);self.raw.flush()
            self.decoder.stdin.write(data);await self.decoder.stdin.drain()
    async def close(self):
        if self.video:self.video.cancel();await asyncio.gather(self.video,return_exceptions=True)
        for w in self.writers:w.close()
        if self.proc and self.proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):self.proc.terminate()
            try:await asyncio.wait_for(self.proc.wait(),3)
            except asyncio.TimeoutError:
                self.proc.kill();await self.proc.wait()
        if self.decoder:
            if self.decoder.stdin:self.decoder.stdin.close()
            try:await asyncio.wait_for(self.decoder.wait(),3)
            except asyncio.TimeoutError:
                self.decoder.kill();await self.decoder.wait()
        if self.port:
            # Cleanup-only operation: exact manifest-owned mapping, no broad kill.
            with contextlib.suppress(Exception):await self.b.c.device.adb('-s',self.b.c.device.serial,'forward','--remove',f'tcp:{self.port}')
        if hasattr(self,'raw'):self.raw.close()
        if hasattr(self,'log'):self.log.close()

class Backend:
    def __init__(self,c,job,guard):
        self.c=c;self.job=job;self.guard=guard;self.apps={};self.screens=[];self.manifest=[];self.registry=[]
        self.folder=c.state_dir/'multiscreen'/job['id'];self.folder.mkdir(parents=True,exist_ok=True)
        self.events=[];self.model=None;self.entered=False;self.reverse_port=None
        self.job['_viewer_token']=secrets.token_urlsafe(32);self.job['_backend']=self
    async def adb(self,*args):
        self.guard();r=await self.c.device.adb('-s',self.c.device.serial,*args);self.guard();return r
    async def bridge(self,method,arg=None):
        a=['shell','content','call','--uri','content://dev.mopu.multiscreen.bridge','--method',method]
        if arg is not None:a+=['--arg',shlex.quote(json.dumps(arg,ensure_ascii=False))]
        raw=await self.adb(*a);prefix='Result: Bundle[{result='
        if not raw.startswith(prefix):raise RuntimeError(raw[:200])
        return json.loads(raw[len(prefix):-2])
    async def enter(self):
        d=self.c.device
        async with self.c.op:
            self.guard()
            if not d.connected or not d.background_mode:
                raise PermissionError('副屏任务必须以execution_mode=background取得租约；不隐式切换主屏')
            cli=Path(d.config['backend_command'][1]).parents[3]/'mobilecli'/'index.js'
            if not cli.exists():raise RuntimeError('MobileCLI shutdown binary not resolved')
            panel=await d.sample_panel();self.guard()
            atomic(self.folder/'before-mode.json',{'panel':panel,'connected':d.connected,'background':True})
            p=await asyncio.create_subprocess_exec(d.config['backend_command'][0],str(cli),'daemon','stop',stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            out,err=await asyncio.wait_for(p.communicate(),10);self.guard()
            if p.returncode:raise RuntimeError('MobileCLI graceful stop failed')
            self.entered=True
        for _ in range(30):
            if (await self.bridge('status'))['connected']:break
            await asyncio.sleep(.2)
        else:raise RuntimeError('accessibility did not reconnect')
    async def publish(self):
        self.job['screens']=[{k:v for k,v in row.items() if k not in ('viewer','human_url')}|{'display':row['id']} for row in self.registry]
        await self.bridge('publish',self.registry)
        self.c.multiscreen_jobs.save(self.job)
    async def run(self):
        tasks=await self.plan()
        for task in tasks:task['_duplicate']=sum(t['app']==task['app'] for t in tasks)>1
        await self.enter()
        for i,t in enumerate(tasks):
            s=Screen(self,str(i));self.screens.append(s);await s.start()
            self.registry.append({'id':s.display,'app':self.apps[t['app']][0],'step':t['goal'],'status':'就绪',
                                  'viewer':f"http://127.0.0.1:{self.c.origin.rsplit(':',1)[1]}/ms/{self.job['_viewer_token']}/frame/{s.display}",
                                  'human_url':f"http://127.0.0.1:{self.c.origin.rsplit(':',1)[1]}/ms/{self.job['_viewer_token']}/human/{s.display}"})
        self.reverse_port=int(self.c.origin.rsplit(':',1)[1])
        existing=await self.adb('reverse','--list')
        if f'tcp:{self.reverse_port}' in existing:raise RuntimeError('reverse mapping already exists; not ours')
        await self.adb('reverse',f'tcp:{self.reverse_port}',f'tcp:{self.reverse_port}')
        self.job['screens']=self.manifest;await self.publish()
        async with asyncio.TaskGroup() as group:
            workers=[group.create_task(self.work(s,t)) for s,t in zip(self.screens,tasks)]
        results=[w.result() for w in workers]
        return results
    async def close(self):
        if self.model and self.model.returncode is None:
            with contextlib.suppress(ProcessLookupError):self.model.terminate()
            await self.model.wait()
        for s in self.screens:await s.close()
        if self.reverse_port:
            with contextlib.suppress(Exception):await self.c.device.adb('-s',self.c.device.serial,'reverse','--remove',f'tcp:{self.reverse_port}')
        if self.entered:
            # Clear only our own registry; another registration is preserved.
            with contextlib.suppress(Exception):
                raw=await self.c.device.shell('content','call','--uri','content://dev.mopu.multiscreen.bridge','--method','status')
                state=json.loads(raw[len('Result: Bundle[{result='):-2])
                if {x['id'] for x in state['screens']}=={s.display for s in self.screens if s.display}:
                    await self.c.device.shell('content','call','--uri','content://dev.mopu.multiscreen.bridge','--method','clear')
        # Final state remains in background mode: never surprise the human by
        # reconnecting the foreground screen or silently restarting MobileCLI.
        remaining=None
        # Resource-only teardown verification, never reading an App screen or
        # issuing input after revocation. Do not destroy unowned displays.
        with contextlib.suppress(Exception):
            for _ in range(5):
                raw=await self.c.device.shell('dumpsys','display')
                remaining=[int(x) for x in re.findall(r'^  Display (\d+):',raw,re.M)]
                if not any(s.display in remaining for s in self.screens if s.display):break
                await asyncio.sleep(.2)
        return {'closed_owned_transports':True,'resources':self.manifest,'remaining_displays':remaining,'display_absence_readback':remaining is not None and not any(s.display in remaining for s in self.screens if s.display),'background_mode':self.entered}

async def view(request):
    from aiohttp import web
    c=request.app['console'];key=request.match_info['key'];display=int(request.match_info['display'])
    job=next((j for j in c.multiscreen_jobs.jobs.values() if secrets.compare_digest(j.get('_viewer_token',''),key)),None)
    if not job:raise web.HTTPForbidden()
    try:
        c.multiscreen_jobs.guard(job);b=job['_backend'];s=next(s for s in b.screens if s.display==display)
        if request.match_info['operation']=='frame' and request.method=='GET':
            path=s.framepath
            b.guard()
            if not path.exists():raise ValueError('画面尚未就绪')
            return web.Response(body=path.read_bytes(),content_type='image/png',headers={'Cache-Control':'no-store','X-Frame-Time':str(path.stat().st_mtime)})
        if request.match_info['operation']!='human' or request.method!='POST':raise ValueError('unsupported operation')
        data=await request.json()
        async with c.op:
            b.guard();status=await b.bridge('status');row=next(x for x in status['screens'] if x['id']==display)
            if not row['paused']:raise PermissionError('先接管此副屏')
            if data.get('op')!='tap':raise ValueError('此版本人工通道只支持点击')
            x,y=data['x'],data['y'];w,h=s.size
            if type(x) is not int or type(y) is not int or not (0<=x<w and 0<=y<h):raise ValueError('invalid coordinates')
            for action in (0,1):
                b.guard();s.cw.write(struct.pack('>BBQiiHHHII',2,action,(1<<64)-2,x,y,w,h,0 if action else 65535,0,0));await s.cw.drain()
        return web.json_response({'dispatched':True,'verify_required':True})
    except Exception as exc:return web.json_response({'error':str(exc)[:200]},status=409)
