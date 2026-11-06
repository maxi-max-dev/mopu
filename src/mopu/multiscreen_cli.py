"""One explicit user invocation -> one bounded, broker-owned background job.
No retries after takeover, no manual plan JSON, no raw ADB in the launcher.
"""
import argparse,asyncio,json,secrets
from pathlib import Path
from .client import call_tool
from .paths import default_state

async def run(args):
    agent=args.agent if args.task_id else 'multiscreen-'+secrets.token_hex(6)
    async def call(name,payload=None):return await call_tool(args.state,agent,'副屏一句话',name,payload or {})
    session=await call('phone_session')
    if args.task_id:
        if not any(t['id']==args.task_id and t['status']=='running' for t in session.get('tasks',[])) or not session.get('lease_active'):
            raise PermissionError('原任务没有有效租约；回原助手核对，不在入口自动续权')
        started={'task_id':args.task_id}
    else:
        started=await call('phone_start',{'title':'副屏：'+args.instruction[:50],
            'instruction':args.instruction,'user_authorization':args.instruction,
            'authorization_id':agent,'execution_mode':'background','max_calls':300,'max_deliveries':0,'duration_seconds':3600})
        lease=await call('phone_wait')
        if lease.get('waiting'):
            print(json.dumps({'task_id':started['task_id'],'waiting':True,'detail':'未取得控制权，不启动任何副屏；回原任务处理，勿重复提交'},ensure_ascii=False));return
    job=await call('phone_multiscreen',{'operation':'start','instruction':args.instruction})
    print(json.dumps({'task_id':started['task_id'],'job_id':job['id'],'status':job['status']},ensure_ascii=False),flush=True)
    while not job.get('finished_at'):
        await asyncio.sleep(15)
        # Authentication failure propagates; never reacquire a revoked lease.
        job=await call('phone_multiscreen',{'operation':'status','job_id':job['id']})
        print(json.dumps({'status':job['status'],'screens':job['screens']},ensure_ascii=False),flush=True)
    print(json.dumps(job,ensure_ascii=False),flush=True)
    # Results remain task receipts, not fabricated fresh UI observations after
    # the temporary displays have been destroyed.
    if args.task_id:return
    checks=[]
    if job.get('observation') and job['status']=='complete':
        checks=[{'criterion':'副屏任务读回结果且本任务显示已释放','observed':json.dumps(job['result'],ensure_ascii=False),'observation_id':job['observation']['id'],'passed':True}]
    await call('phone_finish',{'result':json.dumps(job,ensure_ascii=False),'checks':checks,
        'blocked':job['status']!='complete','unresolved':[] if job['status']=='complete' else [job.get('error','副屏作业未完成')]})

def main():
    p=argparse.ArgumentParser(description='一句任务启动Mopu副屏；读取实际安装App并逐步观察执行，最多两屏，禁止外发、付款和删除。')
    p.add_argument('instruction');p.add_argument('--task-id');p.add_argument('--agent',default='multiscreen-client');p.add_argument('--state',type=Path,default=default_state())
    args=p.parse_args()
    try:asyncio.run(run(args))
    except (RuntimeError,PermissionError,ValueError) as exc:raise SystemExit(str(exc))
if __name__=='__main__':main()
