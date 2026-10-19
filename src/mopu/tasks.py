"""Persistent queue, independent of models, agents and device transports."""
import copy
import datetime
import json
import secrets
import time
from pathlib import Path
from .contracts import WAIT_REASONS


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(path.name + '.new')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    tmp.chmod(0o600)
    tmp.replace(path)


class Queue:
    def __init__(self, path):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {
            'version': 1, 'tasks': [], 'events': [], 'settings': {'quiet': True, 'screen_off': True, 'close_pauses': True}}
        self.owner = 'paused'
        self.current = None
        self.generation = 0
        self.lease = None
        for task in self.data['tasks']:
            if task['status'] == 'running':
                task['status'] = 'paused'
                task['action'] = '服务重启，等待重新观察后续接'
        self.save()

    def save(self):
        atomic(self.path, self.data)

    def event(self, message):
        self.data['events'] = (self.data['events'] + [{'at': now(), 'message': message}])[-100:]
        self.save()

    def get(self, ident):
        task = next((t for t in self.data['tasks'] if t['id'] == ident), None)
        if not task:
            raise ValueError('任务不存在')
        return task

    def add(self, title, instruction, agent, agent_name):
        if not title.strip() or len(title) > 120 or not instruction.strip() or len(instruction) > 12000:
            raise ValueError('请填写任务标题和说明，标题最多120字')
        task = {'id': secrets.token_hex(6), 'title': title.strip(), 'instruction': instruction.strip(),
                'agent': agent, 'agent_name': agent_name, 'status': 'queued', 'created_at': now(),
                'wait_reason': '', 'receipt': None, 'checkpoint': '', 'action': '等待原助手领取', 'result': '', 'steps': 0}
        self.data['tasks'].append(task)
        self.event(f'{agent_name} 添加任务：{title}')
        return copy.deepcopy(task)

    def head(self):
        return next((t for t in self.data['tasks'] if t['status'] in ('queued', 'paused', 'running')), None)

    def invalidate(self, reason):
        self.generation += 1
        self.lease = None
        if self.current:
            t = self.get(self.current)
            if t['status'] == 'running':
                t.update(status='paused', action=reason)
        self.current = None
        self.save()

    def claim(self, agent):
        if self.owner != 'agent':
            return None
        self.expire()
        if self.lease:
            return None
        t = self.head()
        if not t or t['agent'] != agent or t.get('wait_reason'):
            return None
        self.generation += 1
        self.current = t['id']
        self.lease = {'token': secrets.token_urlsafe(32), 'agent': agent, 'task': t['id'], 'expires': time.monotonic() + 120}
        t.update(status='running', action='重新观察手机现场', started_at=now())
        self.event(f'{t["agent_name"]} 开始：{t["title"]}')
        return {'lease': self.lease['token'], 'task': copy.deepcopy(t), 'generation': self.generation}

    def check(self, agent, token):
        self.expire()
        if self.owner != 'agent' or not self.lease or self.lease['agent'] != agent or not secrets.compare_digest(self.lease['token'], token or ''):
            raise PermissionError('控制权已变化；停止操作，重新等待任务，禁止重放旧动作')
        self.lease['expires'] = time.monotonic() + 120
        return self.get(self.lease['task'])

    def expire(self):
        if self.lease and self.lease['expires'] < time.monotonic():
            self.invalidate('助手连接超时；等待原助手重新领取')
            self.event('助手租约到期，旧操作已失效')

    def checkpoint(self, agent, token, progress, action, wait_reason=""):
        if wait_reason and wait_reason not in WAIT_REASONS:
            raise ValueError("未知等待原因")
        t = self.check(agent, token)
        t.update(checkpoint=str(progress)[:16000], action=str(action)[:500], checkpoint_at=now(), wait_reason=wait_reason)
        self.save()

    def finish(self, agent, token, result, blocked=False, receipt=None):
        t = self.check(agent, token)
        if not str(result).strip():
            raise ValueError('请提供结果或具体阻塞原因')
        verified = bool(receipt and receipt.get('verification') == 'assistant_verified')
        status = 'blocked' if blocked else 'done' if verified else 'unverified'
        t.update(status=status, result=str(result)[:30000], receipt=copy.deepcopy(receipt), finished_at=now(), action=(t.get('action') or '等待你处理') if blocked else '原助手已核验完成' if verified else '结果已保存，待核验')
        self.invalidate('任务结束')
        self.event(('任务受阻：' if blocked else '任务已核验：' if verified else '结果待核验：') + t['title'])

    def move(self, ident, direction):
        task = self.get(ident)
        if task['status'] not in ('queued', 'paused'):
            raise ValueError('只能调整等待中的任务')
        waiting = [t for t in self.data['tasks'] if t['status'] in ('queued', 'paused')]
        i = waiting.index(task)
        j = max(0, min(len(waiting) - 1, i + direction))
        a, b = self.data['tasks'].index(task), self.data['tasks'].index(waiting[j])
        self.data['tasks'][a], self.data['tasks'][b] = self.data['tasks'][b], self.data['tasks'][a]
        self.event('已调整等待队列，当前任务不变')

    def prioritize(self, ident):
        task = self.get(ident)
        if task['status'] not in ('queued', 'paused', 'running'):
            raise ValueError('此任务不能插队')
        self.invalidate('更高优先级任务插队，进度保留')
        self.data['tasks'].remove(task)
        self.data['tasks'].insert(0, task)
        self.event('优先执行：' + task['title'])

    def cancel(self, ident):
        t = self.get(ident)
        if self.current == ident:
            self.invalidate('任务已取消')
        t.update(status='cancelled', action='已取消，保留已有结果')
        self.event('取消任务：' + t['title'])

    def snapshot(self):
        self.expire()
        return {**copy.deepcopy(self.data), 'owner': self.owner, 'current': self.current,
                'generation': self.generation, 'lease_active': self.lease is not None}
