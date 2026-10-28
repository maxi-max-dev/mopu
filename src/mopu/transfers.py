"""Task-scoped, resumable file transfer through the console's existing ADB owner.

No general shell/path API. Each call transfers at most 4 MiB. Durable offsets
advance only after readback. A failed chunk is reconciled at the same offset.
"""
import asyncio
import contextlib
from contextvars import ContextVar
import time
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import stat
from .tasks import atomic, now

PROFILE = ContextVar('mopu_transfer_profile', default=None)

def record_timing(category, started, input_bytes=0, output_bytes=0):
    profile = PROFILE.get()
    if profile is None: return
    elapsed = time.monotonic()-started
    row = profile.setdefault(category, {'calls':0,'seconds':0.0,'input_bytes':0,'output_bytes':0,'max_seconds':0.0})
    row['calls'] += 1; row['seconds'] += elapsed
    row['input_bytes'] += input_bytes; row['output_bytes'] += output_bytes
    row['max_seconds'] = max(row['max_seconds'], elapsed)

CHUNK = 4 * 1024 * 1024
BASE = '/storage/emulated/0/Download'
TEXT = {'type': 'string'}

def tool(name, description, fields=None, required=None):
    return {'name': name, 'description': description, 'inputSchema': {
        'type': 'object', 'properties': fields or {}, 'required': required or [], 'additionalProperties': False}}

TOOLS = [
    tool('mobile_transfer_space', 'Read available bytes on phone shared storage under this lease.'),
    tool('mobile_transfer_scope', 'Freeze exact existing local source/destination directories for this task, with current task authorization. No broad home/root scope.',
         {'source_root': TEXT, 'destination_root': TEXT, 'user_authorization': TEXT}, ['source_root','destination_root','user_authorization']),
    tool('mobile_transfer_manifest', 'Read this task manifest; offsets survive reconnect/restart. Manifest is historical, use verify for fresh device evidence.'),
    tool('mobile_transfer_push', 'Start or resume a file upload, one 4 MiB chunk per call. Supply relative source and expected full SHA256; no source deletion.',
         {'source': TEXT, 'sha256': TEXT}, ['source','sha256']),
    tool('mobile_transfer_verify', 'Read size and SHA256 of a task-created remote file. Full checksum can time out; no success is inferred.', {'transfer_id': TEXT}, ['transfer_id']),
    tool('mobile_transfer_pull', 'Pull one 4 MiB chunk of a verified task file into a new relative destination. Never overwrite existing files. Repeat until downloaded.',
         {'transfer_id': TEXT, 'destination': TEXT}, ['transfer_id','destination']),
    tool('mobile_transfer_cleanup', 'Delete ONLY one manifest-owned phone temporary file. Requires recovery evidence or explicit abandoned-test reason. Never deletes original/local files.',
         {'transfer_id': TEXT, 'recovery_evidence': TEXT}, ['transfer_id','recovery_evidence']),
]
TOOLS += [
    tool('mobile_transfer_start', 'Start continuous broker-owned push/pull/verify. Internal chunks are automatic, not a file-size limit. Poll job every 30 seconds to maintain the lease; takeover or expired lease stops it. After reconnect/restart start the same transfer to resume its manifest.',
         {'operation': {'type':'string','enum':['push','pull','verify']}, 'source':TEXT,'sha256':TEXT,'transfer_id':TEXT,'destination':TEXT}, ['operation']),
    tool('mobile_transfer_job', 'Read this task background transfer status and renew the caller lease. This is progress, not checksum evidence.', {'job_id':TEXT}, ['job_id']),
]
NAMES = {t['name'] for t in TOOLS}
READS = {'mobile_transfer_space','mobile_transfer_manifest','mobile_transfer_verify','mobile_transfer_job'}


def safe_local(root, relative):
    if not isinstance(relative, str) or not relative or '\x00' in relative:
        raise ValueError('需要非空相对文件路径')
    p = Path(relative)
    if p.is_absolute() or any(x in ('.','..') for x in relative.split('/')):
        raise ValueError('拒绝绝对路径或路径穿越')
    root = Path(root)
    path = root / p
    current = Path('/')
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink(): raise PermissionError('不允许符号链接路径')
    if not path.resolve().is_relative_to(root.resolve()): raise PermissionError('路径超出范围')
    return path


class Transfers:
    def __init__(self, state, device):
        self.directory = Path(state) / 'transfers'
        self.device = device

    def load(self, task):
        if not re.fullmatch(r'[a-f0-9]{12}', task['id']): raise ValueError('invalid task id')
        path = self.directory / (task['id'] + '.json')
        return json.loads(path.read_text()) if path.exists() else {
            'version': 1, 'task_id': task['id'], 'agent': task['agent'], 'files': []}

    def save(self, manifest):
        started=time.monotonic()
        manifest['updated_at'] = now()
        atomic(self.directory / (manifest['task_id'] + '.json'), manifest)
        record_timing('manifest_save',started)

    async def run(self, command, guard, data=None, timeout=48):
        """Bounded existing-device subprocess, terminated promptly on lease loss."""
        guard()
        if not self.device.connected or not self.device.lockfile: raise PermissionError('设备独占锁未持有')
        started=time.monotonic(); out=b''
        category = 'payload_write' if data is not None else 'payload_read' if 'dd if=' in command else 'remote_sha256' if 'sha256sum ' in command else 'metadata_commands'
        proc = await asyncio.create_subprocess_exec(self.device.config['adb'], '-s', self.device.serial,
            'shell', '-T', 'sh', '-c', shlex.quote(command),
            stdin=asyncio.subprocess.PIPE if data is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        pending = asyncio.create_task(proc.communicate(data))
        try:
            async with asyncio.timeout(timeout):
                while not pending.done():
                    guard()
                    await asyncio.wait({pending}, timeout=.05)
                out, err = await pending
                guard()
                if proc.returncode: raise RuntimeError('文件操作失败：' + err.decode(errors='replace')[:160])
                return out
        finally:
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError): proc.kill()
                await proc.wait()
            if not pending.done():
                pending.cancel()
                with contextlib.suppress(asyncio.CancelledError): await pending
            record_timing(category,started,len(data) if data is not None else 0,len(out))

    async def remote_guard(self, directory, guard):
        # Every path is broker-generated; Android's shared-storage alias is
        # resolved once to its canonical path. Reject links inside task storage.
        quoted = shlex.quote(directory)
        out = await self.run(f'test ! -L {quoted} && test "$(readlink -f {quoted})" = {quoted} && test -d {quoted}', guard)
        return out

    async def checksum(self, path, guard):
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            while True:
                guard()
                block = stream.read(CHUNK)
                if not block: break
                digest.update(block)
                await asyncio.sleep(0)
        guard()
        return digest.hexdigest()

    async def handle(self, name, args, task, guard, background=False):
        spec = next(t['inputSchema'] for t in TOOLS if t['name'] == name)
        if set(args) - set(spec['properties']) or set(spec['required']) - set(args): raise ValueError('文件工具参数不符')
        if any(not isinstance(v, str) for v in args.values()): raise ValueError('参数必须为字符串')
        guard()
        m = self.load(task)
        if m['agent'] != task['agent']: raise PermissionError('传输任务不属于本助手')
        if name == 'mobile_transfer_space':
            out = (await self.run(f'df -k {BASE}', guard)).decode().splitlines()
            fields = out[-1].split()
            return {'available_bytes': int(fields[3])*1024, 'filesystem': BASE, 'observed_at': now()}
        if name == 'mobile_transfer_manifest': return m
        if name == 'mobile_transfer_scope':
            roots = {}
            for key in ('source_root','destination_root'):
                p = Path(args[key])
                if not p.is_absolute() or not p.is_dir() or p.resolve() != p or len(p.parts) < 5:
                    raise ValueError('范围必须为已存在、无符号链接的具体绝对目录')
                allowed = self.device.config.get('transfer_local_roots', [str(Path.home()/'Documents'/'Codex')])
                if not any(p.is_relative_to(Path(base).resolve()) and p != Path(base).resolve() for base in allowed):
                    raise PermissionError('目录不在管理员允许的传输根目录之下')
                safe_local(p, 'scope-check')
                roots[key] = str(p)
            if not args['user_authorization'].strip(): raise ValueError('需要本任务文件授权说明')
            if m.get('scope') and m['scope'] != roots: raise PermissionError('任务范围已冻结，请为不同范围建立新任务')
            m.update(scope=roots, authorization=args['user_authorization'][:1000])
            self.save(m)
            return {'scope': roots, 'task_id': task['id']}
        if not m.get('scope'): raise PermissionError('先为本任务冻结文件目录范围')
        if name == 'mobile_transfer_push':
            if not re.fullmatch('[a-f0-9]{64}', args['sha256']): raise ValueError('需要小写完整SHA256')
            source = safe_local(m['scope']['source_root'], args['source'])
            info = source.stat()
            if not stat.S_ISREG(info.st_mode): raise ValueError('只支持普通文件')
            fingerprint = [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]
            f = next((x for x in m['files'] if x['source'] == args['source']), None)
            if f is None:
                ident = secrets.token_hex(16)
                f = {'id': ident, 'source': args['source'], 'sha256': args['sha256'], 'size': info.st_size,
                     'fingerprint': fingerprint, 'directory': BASE+'/mopu-'+task['id']+'-'+ident,
                     'uploaded': 0, 'status': 'allocating', 'created_at': now()}
                m['files'].append(f); self.save(m)
                # mkdir without -p will refuse any preexisting directory.
                await self.remote_guard(BASE, guard)
                await self.run('mkdir '+shlex.quote(f['directory']), guard)
                f['directory_inode'] = (await self.run('stat -c %i '+shlex.quote(f['directory']), guard)).decode().strip()
                if not f['directory_inode'].isdigit(): raise RuntimeError('无有效目录inode；创建结果不确定')
                f['status'] = 'uploading'; self.save(m)
            if f['fingerprint'] != fingerprint or f['sha256'] != args['sha256']: raise ValueError('源文件已改变，不继续旧传输')
            if f['status'] == 'allocating': raise RuntimeError('目录创建结果不确定；人工核对，不冒认已有目录')
            if f['status'] not in ('uploading','uploaded','verified','downloaded'): raise ValueError('传输已清理')
            await self.remote_guard(f['directory'], guard)
            if (await self.run('stat -c %i '+shlex.quote(f['directory']), guard)).decode().strip() != f['directory_inode']: raise PermissionError('任务目录已被替换')
            remote = f['directory']+'/payload'
            q = shlex.quote(remote)
            offset = f['uploaded']
            if f['status'] == 'uploading':
                with source.open('rb') as stream:
                    stream.seek(offset); block = stream.read(CHUNK)
                if offset == 0:
                    # noclobber: only create once; later uncertain chunk retries
                    # may reuse the recorded payload within our exclusive dir.
                    await self.run(f'test ! -L {q} && (test -f {q} || (set -C; : > {q}))', guard)
                else:
                    await self.run(f'test ! -L {q} && test -f {q}', guard)
                inode = (await self.run(f'stat -c %i {q}', guard)).decode().strip()
                if not inode.isdigit(): raise RuntimeError('无有效文件inode')
                if f.get('payload_inode') and inode != f['payload_inode']: raise PermissionError('临时文件已被替换')
                f['payload_inode']=inode; self.save(m)
                await self.run(f'dd of={q} bs={CHUNK} seek={offset//CHUNK} conv=notrunc 2>/dev/null', guard, block)
                actual = await self.run(f'dd if={q} bs={CHUNK} skip={offset//CHUNK} count=1 2>/dev/null', guard)
                if actual != block: raise RuntimeError('上传块读回不一致；偏移未推进')
                f['uploaded'] += len(block)
                if f['uploaded'] == f['size']: f['status'] = 'uploaded'
                self.save(m)
            return f
        f = next((x for x in m['files'] if x['id'] == args.get('transfer_id')), None)
        if not f: raise PermissionError('只能访问本任务创建的文件')
        if name in ('mobile_transfer_cleanup','mobile_transfer_verify'):
            qdir=shlex.quote(f['directory'])
            absent = await self.run(f'if test ! -e {qdir} && test ! -L {qdir}; then echo absent; fi',guard)
            if absent.strip() == b'absent':
                if name == 'mobile_transfer_cleanup':
                    if not args['recovery_evidence'].strip(): raise ValueError('需要清理依据')
                    f['status']='cleaned';f['cleaned_at']=now();self.save(m);return f
                return {'transfer_id':f['id'],'absent':True,'expected_present':f['status']!='cleaned','observed_at':now()}
        if f['status'] == 'cleaned':
            if name == 'mobile_transfer_cleanup': return f
            if name == 'mobile_transfer_verify':
                q = shlex.quote(f['directory'])
                await self.run(f'test ! -e {q} && test ! -L {q}', guard)
                return {'transfer_id':f['id'],'absent':True,'observed_at':now()}
            raise ValueError('手机临时副本已清理')
        if name == 'mobile_transfer_cleanup' and f.get('cleaning'):
            missing = await self.run('if test ! -e '+shlex.quote(f['directory'])+'; then echo absent; fi', guard)
            if missing.strip() == b'absent':
                f['status']='cleaned'; f['cleaned_at']=now(); self.save(m); return f
        await self.remote_guard(f['directory'], guard)
        if (await self.run('stat -c %i '+shlex.quote(f['directory']), guard)).decode().strip() != f['directory_inode']: raise PermissionError('任务目录已被替换')
        remote = f['directory']+'/payload'; q = shlex.quote(remote)
        inode = (await self.run(f'if test -e {q}; then stat -c %i {q}; fi', guard)).decode().strip()
        if inode and inode != f.get('payload_inode'): raise PermissionError('临时文件已被替换')
        if name == 'mobile_transfer_verify':
            out = await self.run(f'test ! -L {q} && test -f {q} && stat -c %s {q} && sha256sum {q}', guard, timeout=3600 if background else 48)
            lines = out.decode().splitlines(); size = int(lines[0]); digest = lines[1].split()[0]
            ok = size == f['size'] and digest == f['sha256']
            if ok:
                if f['status'] != 'downloaded': f['status'] = 'verified'
                f['verified_at'] = now(); self.save(m)
            elif f['status'] in ('verified','downloaded'):
                f['status']='uploaded'; f['verification_failed_at']=now(); self.save(m)
            return {'transfer_id': f['id'], 'size': size, 'sha256': digest, 'matches': ok, 'observed_at': now()}
        if name == 'mobile_transfer_pull':
            if f['status'] not in ('verified','downloaded'): raise PermissionError('先核对手机完整大小与SHA256')
            dest = safe_local(m['scope']['destination_root'], args['destination'])
            if not dest.parent.is_dir(): raise ValueError('目标父目录须已存在')
            if f.get('destination') and f['destination'] != args['destination']: raise ValueError('恢复路径已冻结')
            part = dest.with_name('.mopu-'+f['id']+'.part')
            safe_local(m['scope']['destination_root'], str(part.relative_to(m['scope']['destination_root'])))
            if f['status'] == 'downloaded':
                if dest.exists() and await self.checksum(dest, guard) == f['sha256']: return f
                raise RuntimeError('此前恢复目标已改变或不存在')
            if dest.exists():
                # Recover an acknowledged/uncertain publish only if both links
                # still identify our part file. Never adopt an unrelated file.
                if f.get('publishing') and part.exists() and os.path.samefile(part, dest) and await self.checksum(dest, guard) == f['sha256']:
                    f['status']='downloaded'; f['downloaded_at']=now(); self.save(m)
                    part.unlink(); return f
                raise FileExistsError('不会覆盖目标文件')
            if 'destination' not in f:
                f.update(destination=args['destination'], pulled=0, part_created=False); self.save(m)
            if not f.get('part_created'):
                with part.open('xb'): pass
                f['part_created']=True; self.save(m)
            offset = f['pulled']
            block = b'' if offset == f['size'] else await self.run(f'test ! -L {q} && test -f {q} && dd if={q} bs={CHUNK} skip={offset//CHUNK} count=1 2>/dev/null', guard)
            if len(block) != min(CHUNK, f['size']-offset): raise RuntimeError('下载块大小不符')
            local_write_started=time.monotonic()
            with part.open('r+b') as stream:
                stream.seek(offset); stream.write(block); stream.truncate(offset+len(block)); stream.flush(); os.fsync(stream.fileno())
            record_timing('local_write_fsync',local_write_started,input_bytes=len(block))
            f['pulled'] += len(block); self.save(m)
            if f['pulled'] == f['size']:
                if await self.checksum(part, guard) != f['sha256']: raise RuntimeError('Mac恢复SHA256不一致')
                guard(); f['publishing']=True; self.save(m)
                os.link(part, dest)
                f['status']='downloaded'; f['downloaded_at']=now(); self.save(m)
                part.unlink()
            return f
        if name == 'mobile_transfer_cleanup':
            if not args['recovery_evidence'].strip(): raise ValueError('需要云端恢复验证依据，或明确的废弃测试说明')
            if f['status'] == 'allocating': raise PermissionError('不删除未确认由任务创建的目录')
            f['cleanup_evidence']=args['recovery_evidence'][:2000]; f['cleaning']=True; self.save(m)
            # No recursive delete, wildcard or arbitrary paths. Unknown contents
            # make rmdir fail and remain intact. Local originals are never deleted.
            await self.run(f'test ! -L {q} && (test ! -e {q} || test -f {q}) && rm -f {q} && rmdir '+shlex.quote(f['directory']), guard)
            f['status']='cleaned'; f['cleaned_at']=now(); self.save(m)
            return f
        raise ValueError('未知文件操作')


class TransferJobs:
    """In-memory workers never survive broker restart or reclaim lost ownership."""
    def __init__(self, console):
        self.console = console
        self.jobs = {}
        self.workers = set()

    def handle(self, name, args, task, agent, token):
        if name == 'mobile_transfer_job':
            if set(args) != {'job_id'}: raise ValueError('需要job_id')
            job = self.jobs.get(args['job_id'])
            if not job or job['task_id'] != task['id']: raise PermissionError('任务不存在；重启后按清单续传')
            return dict(job)
        operation = args.get('operation')
        required = {'operation','source','sha256'} if operation == 'push' else {'operation','transfer_id','destination'} if operation == 'pull' else {'operation','transfer_id'} if operation == 'verify' else set()
        if not required or set(args) != required or any(not isinstance(v,str) for v in args.values()):
            raise ValueError('push需要source/sha256；pull需要transfer_id/destination')
        if any(j['status']=='running' and j['task_id']==task['id'] for j in self.jobs.values()):
            raise PermissionError('本任务已有传输，先读取进度')
        job = {'id':secrets.token_hex(12),'task_id':task['id'],'operation':operation,'status':'running','bytes_done':0,'started_at':now()}
        self.jobs[job['id']] = job
        worker = asyncio.create_task(self.work(job, {k:v for k,v in args.items() if k!='operation'}, task, agent, token))
        self.workers.add(worker);worker.add_done_callback(self.workers.discard)
        return dict(job)

    async def work(self, job, args, task, agent, token):
        c = self.console
        profile_token=PROFILE.set(job.setdefault('profile',{}))
        def guard():
            # Worker activity does NOT keep its assistant alive indefinitely.
            # Only incoming authenticated calls renew the lease.
            expiry = c.queue.lease['expires'] if c.queue.lease else None
            c.queue.check(agent,token)
            c.queue.lease['expires'] = expiry
        try:
            while True:
                async with c.op:
                    guard()
                    c.observations.invalidate(task['id'])
                    result = await c.transfers.handle('mobile_transfer_'+job['operation'], args, task, guard, background=True)
                    if job['operation']=='verify':
                        job.update(status='complete',result=result,finished_at=now(),observation=c.observations.record(task['id'],c.queue.generation,'mobile_transfer_verify'))
                        break
                    job.update(transfer_id=result['id'],bytes_done=result['uploaded'] if job['operation']=='push' else result['pulled'],size=result['size'],updated_at=now())
                    if result['status'] in (('uploaded','verified','downloaded') if job['operation']=='push' else ('downloaded',)):
                        job.update(status='complete',finished_at=now())
                        break
                await asyncio.sleep(0)
        except (Exception,asyncio.CancelledError) as exc:
            job.update(status='interrupted',error=str(exc)[:250] or 'broker stopped',finished_at=now())
        finally:
            PROFILE.reset(profile_token)

    async def close(self):
        for worker in list(self.workers): worker.cancel()
        await asyncio.gather(*self.workers,return_exceptions=True)
