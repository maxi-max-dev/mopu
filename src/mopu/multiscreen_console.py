"""Authenticated human-only multiscreen viewing and handback, under the parent lease."""
import asyncio
import contextlib
import time
from aiohttp import web

async def console_view(request):
    c=request.app['console'];m=c.multiscreen_jobs
    job=m.jobs.get(request.match_info['job'])
    try:
        if not job:raise PermissionError('作业不存在')
        m.guard(job);b=job['_backend'];op=request.match_info['operation'];display=int(request.match_info['display'])
        if op=='list' and request.method=='GET':return web.json_response(await m.inventory(job))
        if op in ('takeover','return') and request.method=='POST':
            return web.json_response(await m.hold(job,display,op=='takeover'))
        if op=='frame' and request.method=='GET':
            if display==0:
                # Read the default physical display without waking it or starting a foreground stream.
                proc=None
                try:
                    m.guard(job)
                    proc=await asyncio.create_subprocess_exec(c.device.config['adb'],'-s',c.device.serial,'exec-out','screencap','-p',stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
                    data,error=await asyncio.wait_for(proc.communicate(),5);m.guard(job)
                    if proc.returncode or not data.startswith(b'\x89PNG'):raise RuntimeError('主屏画面不可用；不会唤醒或解锁')
                    stamp=time.time()
                finally:
                    if proc and proc.returncode is None:
                        with contextlib.suppress(ProcessLookupError):proc.kill()
                        await proc.wait()
            else:
                s=next((s for s in b.screens if s.display==display),None)
                if not s or not s.framepath.exists():raise ValueError('画面未就绪')
                data=s.framepath.read_bytes();stamp=s.framepath.stat().st_mtime
            return web.Response(body=data,content_type='image/png',headers={'Cache-Control':'no-store','X-Frame-Time':str(stamp)})
        if op=='tap' and request.method=='POST':
            async with c.op:
                m.guard(job);inventory=await m.inventory(job)
                row=next((r for r in inventory['screens'] if r['display']==display),None)
                if not row or not row['paused']:raise PermissionError('先接管此副屏')
                s=next(s for s in b.screens if s.display==display);data=await request.json();x,y=data['x'],data['y'];w,h=s.size
                if type(x)is not int or type(y)is not int or not (0<=x<w and 0<=y<h):raise ValueError('无效坐标')
                if row['phone_paused']:raise PermissionError('手机端接管仍有效，请先在手机交还')
                tree=await b.bridge('tree',{'display':display})
                candidates=[]
                for n in tree['nodes']:
                    bounds=n.get('bounds',[])
                    if len(bounds)!=4 or not n.get('visible') or not n.get('enabled') or n.get('password'):continue
                    l,t,r,bottom=bounds
                    if l<=x<r and t<=y<bottom:candidates.append(((r-l)*(bottom-t),n))
                if not candidates:raise ValueError('点击处没有可核验节点；未发送触摸')
                node=min(candidates,key=lambda item:item[0])[1]
                target={k:v for k,v in node.items() if k!='node'}
                ack=await b.bridge('action',{'display':display,'target':target,'action':'click','value':''})
                if not ack.get('dispatched'):raise RuntimeError('点击未确认，请观察后再操作')
                job['_human_epoch']=job.get('_human_epoch',0)+1
            return web.json_response({'dispatched':True,'verify_required':True})
        raise ValueError('不支持此操作')
    except (ValueError,KeyError,PermissionError,RuntimeError,StopIteration) as exc:
        return web.json_response({'error':str(exc)},status=409)
