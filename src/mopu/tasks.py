"""Persistent queue, independent of models, agents and device transports."""
import copy
import datetime
import json
import secrets
import time
from pathlib import Path
from .contracts import WAIT_REASONS
from .continuation import Continuation


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(path.name + '.new')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    tmp.chmod(0o600)
    tmp.replace(path)


class Queue(Continuation):
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
        self.revoke_continuations('服务重启：阶段批准失效，需重新人工检查')
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
        self.reject_duplicate(agent)
        if not title.strip() or len(title) > 120 or not instruction.strip() or len(instruction) > 12000:
            raise ValueError('请填写任务标题和说明，标题最多120字')
        task = {'id': secrets.token_hex(6), 'title': title.strip(), 'instruction': instruction.strip(),
                'agent': agent, 'agent_name': agent_name, 'status': 'queued', 'created_at': now(),
                'wait_reason': '', 'receipt': None, 'checkpoint': '', 'action': '等待原助手领取', 'result': '', 'steps': 0}
        self.data['tasks'].append(task)
        self.event(f'{agent_name} 添加任务：{title}')
        return copy.deepcopy(task)

    def edit(self, ident, title, instruction, expected_title, expected_instruction):
        task = self.get(ident)
        if self.owner != 'human' or self.lease or task['status'] == 'running':
            raise PermissionError('请先接管手机，再修改任务要求')
        if task.get('deleted_at') or task['status'] in ('done', 'cancelled'):
            raise ValueError('已删除或结束任务保留原要求；请先恢复任务')
        if task['title'] != expected_title or task['instruction'] != expected_instruction:
            raise ValueError('任务要求已被修改，请关闭后重新打开编辑')
        if not isinstance(title, str) or not isinstance(instruction, str) or not title.strip() or len(title) > 120 or not instruction.strip() or len(instruction) > 12000:
            raise ValueError('标题须为1–120字，具体要求须为1–12000字')
        title, instruction = title.strip(), instruction.strip()
        if (title, instruction) == (task['title'], task['instruction']):
            return
        task.setdefault('requirement_history', []).append({'at': now(), 'title': task['title'], 'instruction': task['instruction'], 'source': 'console'})
        task.update(title=title, instruction=instruction, requirements_updated_at=now())
        stage = self.stage(task)
        if stage and stage['state'] in ('approved', 'active'):
            self.stop_for_review(task, '任务要求已修改，请按新要求检查下一阶段')
        self.event('任务要求已更新，保留进度与审批记录：' + title)

    def head(self):
        return next((t for t in self.data['tasks'] if not t.get('deleted_at') and not t.get('user_held') and t['status'] in ('queued', 'paused', 'running')), None)

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
        if t and any(other is not t and other['agent']==agent and self.needs_review(other) for other in self.data['tasks']):
            return None
        if not t or t['agent'] != agent or t.get('wait_reason'):
            return None
        if self.needs_review(t):
            self.stop_for_review(t, '需要人工检查原任务')
            return None
        stage = self.stage(t)
        if stage and stage['state'] == 'approved':
            stage.update(state='active', consumed_at=time.time())
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
        stage = self.stage(t)
        if stage and stage['state'] in ('approved','active'):
            stage.update(state='closed', close_reason='任务阶段结束', ended_total=self.total(t))
        self.invalidate('任务结束')
        if stage and stage.get('kind') == 'whole_task':
            self.owner = 'human'  # Do not implicitly start unrelated historic tasks.
        self.event(('任务受阻：' if blocked else '任务已核验：' if verified else '结果待核验：') + t['title'])

    def move(self, ident, direction):
        task = self.get(ident)
        if task.get('deleted_at') or task.get('user_held') or task['status'] not in ('queued', 'paused'):
            raise ValueError('只能调整等待中的任务')
        waiting = [t for t in self.data['tasks'] if not t.get('deleted_at') and not t.get('user_held') and t['status'] in ('queued', 'paused')]
        i = waiting.index(task)
        j = max(0, min(len(waiting) - 1, i + direction))
        a, b = self.data['tasks'].index(task), self.data['tasks'].index(waiting[j])
        self.data['tasks'][a], self.data['tasks'][b] = self.data['tasks'][b], self.data['tasks'][a]
        self.event('已调整等待队列，当前任务不变')

    def prioritize(self, ident):
        task = self.get(ident)
        if task.get('deleted_at') or task.get('user_held') or task['status'] not in ('queued', 'paused', 'running'):
            raise ValueError('此任务不能插队')
        self.invalidate('更高优先级任务插队，进度保留')
        self.data['tasks'].remove(task)
        self.data['tasks'].insert(0, task)
        self.event('优先执行：' + task['title'])

    def cancel(self, ident):
        t = self.get(ident)
        if self.needs_review(t) or t.get('pending_delivery'):
            raise PermissionError('先检查原任务及未确认动作；接管可随时停止，不用结束任务绕过检查')
        if self.current == ident:
            self.invalidate('任务已取消')
        t.update(status='cancelled', action='已取消，保留已有结果')
        self.event('取消任务：' + t['title'])

    def manage(self, action, ids, validate_only=False):
        if action not in ('trash', 'restore', 'hold', 'resume'):
            raise ValueError('未知任务操作')
        if not isinstance(ids, list) or not ids or len(ids) > 500 or any(not isinstance(i, str) for i in ids) or len(set(ids)) != len(ids):
            raise ValueError('请选择1–500个不同任务')
        tasks = [self.get(i) for i in ids]
        for task in tasks:
            if not validate_only and self.current == task['id']:
                raise PermissionError('请先停止当前任务，待已发出的动作结束')
            if action == 'restore' and not task.get('deleted_at'):
                raise ValueError('只能恢复回收站中的任务')
            if action != 'restore' and task.get('deleted_at'):
                raise ValueError('任务已在回收站，请刷新后再操作')
            if action in ('hold', 'resume') and task['status'] in ('done', 'cancelled'):
                raise ValueError('已结束任务不能暂停或继续')
            if action == 'resume' and not task.get('user_held'):
                raise ValueError('此任务未被你暂停')
        if validate_only:
            return
        for task in tasks:
            # Keep the task, counters and receipts; deletion is reversible visibility,
            # not a way to reset approvals or erase uncertain sends.
            if action in ('trash', 'hold'):
                stage = self.stage(task)
                if stage and stage['state'] in ('approved', 'active'):
                    self.stop_for_review(task, '用户暂停或删除了任务；旧阶段批准已失效')
            if action == 'trash':
                task['deleted_at'] = now()
            elif action == 'restore':
                task.pop('deleted_at')
                if task['status'] not in ('done', 'cancelled'):
                    task['user_held'] = True
            elif action == 'hold':
                task['user_held'] = True
            else:
                task['user_held'] = False
            task.setdefault('management_history', []).append({'at': now(), 'action': action, 'source': 'console'})
        self.event({'trash':'已移入回收站','restore':'已恢复（未自动执行）','hold':'已暂停所选任务','resume':'已取消单独暂停'}[action] + '：' + str(len(tasks)) + '项')

    def position(self, ident, position, expected_order=None):
        task = self.get(ident)
        waiting = [t for t in self.data['tasks'] if not t.get('deleted_at') and not t.get('user_held') and t['status'] in ('queued', 'paused')]
        if expected_order is not None and expected_order != [t['id'] for t in waiting]:
            raise ValueError('等待队列已变化，请关闭后重新选择顺序')
        if task not in waiting or type(position) is not int or not 1 <= position <= len(waiting):
            raise ValueError('请选择有效的等待队列位置')
        indices = [i for i,t in enumerate(self.data['tasks']) if t in waiting]
        waiting.remove(task)
        waiting.insert(position-1, task)
        for i,t in zip(indices, waiting):
            self.data['tasks'][i] = t
        self.event('已调整等待顺序；正在执行的任务不受影响')

    def snapshot(self):
        self.expire()
        return {**copy.deepcopy(self.data), 'owner': self.owner, 'current': self.current,
                'generation': self.generation, 'lease_active': self.lease is not None}
