"""Lease-scoped virtual-display lifecycle. No alternate grant or automatic reclaim."""
import asyncio
import contextlib
import json
import secrets
import time
from .tasks import atomic, now

class MultiscreenJobs:
    def __init__(self, console, backend=None):
        self.c = console
        self.backend = backend
        self.jobs = {}
        self.workers = set()

    def guard(self, job, cost=0):
        q = self.c.queue
        if q.generation != job['generation']:
            raise PermissionError('副屏租约代际已变化')
        # Work must never renew its own assistant lease.
        expiry = q.lease['expires'] if q.lease else None
        task = q.check(job['agent'], job['_lease'])
        q.lease['expires'] = expiry
        if task['id'] != job['task_id']:
            raise PermissionError('副屏任务归属已变化')
        q.ensure_budget(task, cost)
        if job['status'] not in ('starting', 'running'):
            raise PermissionError('副屏任务已停止')
        if cost:
            task['steps'] += cost
            self.c.observations.invalidate(task['id'])
            q.save()
        return task

    def public(self, job):
        return {k:v for k,v in job.items() if not k.startswith('_')}

    def save(self, job):
        atomic(self.c.state_dir/'multiscreen'/f"{job['id']}.json", self.public(job))

    async def handle(self, payload, task, agent, token):
        op = payload.get('operation')
        if op in ('status','stop'):
            job = self.jobs.get(payload.get('job_id'))
            if not job or job['task_id'] != task['id'] or job['agent'] != agent:
                raise PermissionError('不是当前任务的副屏')
            if op == 'stop' and not job.get('finished_at'):
                job['status']='stopping'
                job['_worker'].cancel()
                await asyncio.gather(job['_worker'],return_exceptions=True)
            return self.public(job)
        if op != 'start': raise ValueError('operation必须为start/status/stop')
        instruction=payload.get('instruction')
        if not isinstance(instruction,str) or not 1<=len(instruction)<=2000:
            raise ValueError('需要一句任务，最多2000字')
        soak=payload.get('soak_seconds',0)
        if type(soak) is not int or not 0<=soak<=2400:raise ValueError('soak_seconds须为0-2400')
        if self.backend is None:
            raise RuntimeError('副屏设备后端尚未装配；不创建显示或改主屏')
        if any(not w.done() for w in self.workers):
            raise PermissionError('已有副屏作业，先查询或停止，不重复创建')
        job={'id':secrets.token_hex(10),'task_id':task['id'],'agent':agent,
             'generation':self.c.queue.generation,'instruction':instruction,
             'status':'starting','started_at':now(),'screens':[],'soak_seconds':soak,
             '_lease':token}
        self.guard(job)
        self.jobs[job['id']]=job
        worker=asyncio.create_task(self.work(job))
        job['_worker']=worker;self.workers.add(worker);worker.add_done_callback(self.workers.discard)
        self.save(job)
        return self.public(job)

    async def work(self, job):
        backend=None
        execution=None
        try:
            backend=self.backend(job,lambda cost=0:self.guard(job,cost))
            # Backend owns only resources in its manifest, never arbitrary PIDs.
            execution=asyncio.create_task(backend.run())
            job['status']='running';self.save(job)
            while not execution.done():
                self.guard(job)
                await asyncio.sleep(.1)
            job['result']=await execution
            self.guard(job)
            job['status']='partial' if isinstance(job['result'],list) and any(r.get('verified') is False for r in job['result']) else 'complete'
        except (Exception,asyncio.CancelledError) as exc:
            job['status']='interrupted';job['error']=str(exc)[:250] or '任务停止'
            if isinstance(exc,BaseExceptionGroup):job['causes']=[str(e)[:250] for e in exc.exceptions]
        finally:
            if execution and not execution.done():execution.cancel()
            if execution:await asyncio.gather(execution,return_exceptions=True)
            # Narrow cleanup remains permitted after revocation: close only owned
            # sockets/process handles/mappings, never new screen reads or inputs.
            try:job['cleanup']=await backend.close() if backend else {'closed_owned_transports':True,'resources':[]}
            except Exception as exc:job['cleanup']={'verified':False,'error':str(exc)[:250]}
            if job['status']=='complete' and job.get('cleanup',{}).get('display_absence_readback'):
                job['observation']=self.c.observations.record(job['task_id'],job['generation'],'phone_multiscreen_result')
            job['finished_at']=now();self.save(job)

    async def close(self):
        for w in list(self.workers):w.cancel()
        await asyncio.gather(*self.workers,return_exceptions=True)
