"""Human-reviewed bounded continuation. No device or network access."""
import copy
import hashlib
import json
import secrets
import time


class Continuation:
    @staticmethod
    def total(task):
        return task.get('prior_steps', 0) + task['steps']

    @staticmethod
    def stage(task):
        return (task.get('reviews') or [None])[-1]

    def needs_review(self, task):
        if task['status'] == 'done' and not task.get('pending_delivery'):
            return False
        stage = self.stage(task)
        if task.get('long_task'):
            return (not stage or stage['state'] not in ('approved', 'active')
                    or stage['expires_at'] <= time.time()
                    or self.total(task) >= stage['ceiling'])
        return task['steps'] >= 200 or task.get('stop_reason') == 'needs_review'

    def review_version(self, task):
        # Bind every durable task field, including checkpoints and delivery evidence.
        return hashlib.sha256(json.dumps(task, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    @staticmethod
    def delivery_summary(task):
        recorded = 'deliveries' in task
        rows = task.get('deliveries', [])
        return {'coverage':'recorded' if recorded else 'unrecorded',
            'verified':sum(d.get('outcome') == 'delivered' for d in rows) if recorded else None,
            'pending':sum(d.get('outcome') == 'uncertain' for d in rows) if recorded else None,
            'not_sent':sum(d.get('outcome') == 'not_sent' for d in rows) if recorded else None,
            'report_available':bool(task.get('result')),
            'scope':'仅逐条记录；未记录的历史发送数量未知'}

    def review_summary(self, task):
        stage = self.stage(task)
        return {'version': self.review_version(task), 'required': self.needs_review(task),
                'total_calls': self.total(task),
                'remaining_calls': max(0, stage['ceiling']-self.total(task)) if stage else max(0, 200-task['steps']),
                'pending_delivery': task.get('pending_delivery'),
                'verified_deliveries': sum(d.get('outcome') == 'delivered' for d in task.get('deliveries', []))}

    def stop_for_review(self, task, reason):
        stage = self.stage(task)
        if stage and stage['state'] in ('approved', 'active'):
            stage.update(state='closed', close_reason=reason, ended_total=self.total(task))
        task.update(status='blocked', stop_reason='needs_review', wait_reason='', action=reason)
        if self.current == task['id']:
            self.invalidate(reason)
        self.save()

    def revoke_continuations(self, reason):
        for task in self.data['tasks']:
            stage = self.stage(task)
            if task.get('long_task') and stage and stage['state'] in ('approved', 'active'):
                self.stop_for_review(task, reason)

    def ensure_budget(self, task, cost):
        stage = self.stage(task)
        remaining = stage['ceiling']-self.total(task) if stage else 200-task['steps']
        invalid_stage = task.get('long_task') and (not stage or stage['state'] not in ('approved','active') or stage['expires_at'] <= time.time())
        if invalid_stage or (cost > 0 and self.needs_review(task)) or remaining < cost:
            self.stop_for_review(task, '需要人工检查：本阶段预算不足，未发出新动作')
            raise PermissionError('needs_review：先人工检查原任务，禁止重排、重复提交或重置计数')

    def approve_continuation(self, data):
        task = self.get(data.get('id'))
        if task.get('deleted_at') or task.get('user_held'):
            raise PermissionError('请先恢复任务并取消单独暂停，再检查下一阶段')
        if self.owner != 'human' or self.lease or self.current:
            raise PermissionError('先由用户接管，待在途动作结束后检查')
        if task['status'] not in ('blocked', 'paused', 'unverified'):
            raise ValueError('只审查已停止的原任务')
        if type(data.get('expected_generation')) is not int or data['expected_generation'] != self.generation:
            raise PermissionError('控制状态已变化，请重新检查')
        if data.get('review_version') != self.review_version(task):
            raise PermissionError('任务或证据已变化，请重新检查')
        if data.get('checked_progress') is not True or data.get('checked_uncertainty') is not True:
            raise ValueError('需检查进度及未确认动作')
        scope, note = data.get('scope'), data.get('review_note')
        if any(not isinstance(s, str) or not s.strip() or len(s)>2000 for s in (scope,note)):
            raise ValueError('需填写有限范围及人工检查结论，最多2000字')
        budget, maximum = data.get('budget'), data.get('max_deliveries')
        if type(budget) is not int or not 2 <= budget <= 200:
            raise ValueError('阶段预算必须为2至200')
        if type(maximum) is not int or not 0 <= maximum <= 20:
            raise ValueError('本阶段送达项上限必须为0至20（0禁止发送）')
        old = self.stage(task)
        if old and old['state'] in ('approved', 'active'):
            raise PermissionError('已有未消费/执行中的审批，不能叠加')
        stamp = time.time()
        review = {'id':secrets.token_hex(12), 'state':'approved', 'reviewed_at':stamp,
                  'expires_at':stamp+1800, 'source':'human_console',
                  'review_version':data['review_version'], 'review_note':note.strip(),
                  'scope':scope.strip(), 'budget':budget, 'start_total':self.total(task),
                  'ceiling':self.total(task)+budget, 'max_deliveries':maximum}
        task.setdefault('reviews', []).append(review)
        task.update(long_task=True, status='queued', stop_reason='', wait_reason='',
                    action='人工已检查有限阶段；交回原助手后先观察')
        # No reset of steps, prior_steps, milestones, receipts, or delivery history.
        self.save()
        return copy.deepcopy(review)

    def authorize_task(self, task, data):
        """One user-scoped grant for a whole task, never an automatic renewal."""
        wording, grant = data.get('user_authorization'), data.get('authorization_id')
        calls, sends = data.get('max_calls'), data.get('max_deliveries')
        seconds = data.get('duration_seconds', 28800)
        if not isinstance(wording, str) or not 1 <= len(wording.strip()) <= 1000:
            raise ValueError('需要当前用户对本任务的明确授权原话')
        if not isinstance(grant, str) or not 8 <= len(grant) <= 100:
            raise ValueError('authorization_id须为8至100字的唯一授权标识')
        if type(calls) is not int or not 2 <= calls <= 100000:
            raise ValueError('整项任务max_calls须为2至100000；按任务规模选取')
        if type(sends) is not int or not 0 <= sends <= 1000:
            raise ValueError('max_deliveries须为0至1000；无发送授权必须为0')
        if type(seconds) is not int or not 60 <= seconds <= 86400:
            raise ValueError('duration_seconds须为60至86400')
        if any(x.get('authorization_id') == grant for t in self.data['tasks'] for x in t.get('reviews', [])):
            raise PermissionError('授权已经使用；不得重新激活或增加额度')
        if task.get('deleted_at') or task.get('user_held') or task['status'] in ('done','cancelled','running'):
            raise PermissionError('任务已停止、结束或正在运行；不能隐式恢复或叠加授权')
        stage = self.stage(task)
        if stage and stage['state'] in ('approved','active') and not self.needs_review(task):
            raise PermissionError('本任务已有有效授权；继续phone_wait，不叠加额度')
        if stage:
            stage.update(state='closed', close_reason='新的明确授权替代过期或已停止授权', ended_total=self.total(task))
        stamp = time.time()
        stage = {'id':secrets.token_hex(12), 'state':'approved', 'reviewed_at':stamp,
            'expires_at':stamp+seconds, 'source':'assistant_user_attestation',
            'authorization_id':grant, 'user_authorization':wording.strip(),
            'scope':task['instruction'], 'budget':calls, 'start_total':self.total(task),
            'ceiling':self.total(task)+calls, 'max_deliveries':sends, 'kind':'whole_task'}
        task.setdefault('reviews', []).append(stage)
        if not task.get('steps') and not task.get('prior_steps') and not task.get('result'):
            task.setdefault('deliveries', [])
        task.update(long_task=True, status='queued', stop_reason='', wait_reason='',
                    action='整项任务已授权，等待原助手领取')
        self.save()
        return stage

    def reject_duplicate(self, agent):
        if any(t['agent']==agent and (self.needs_review(t) or
               (t.get('long_task') and t['status'] not in ('done','cancelled')))
               for t in self.data['tasks']):
            raise PermissionError('原任务待审查或长任务未结束；不能新建任务替代续接')

    def begin_delivery(self, task, key):
        if not isinstance(key, str) or not key.strip() or len(key)>160:
            raise ValueError('delivery_key需要稳定目标标识，最多160字')
        if task.get('pending_delivery'):
            raise PermissionError('上次发送未逐条核验，先观察确认，不得继续输入')
        if any(d['key']==key for d in task.get('deliveries', [])):
            raise PermissionError('目标已有发送尝试；禁止重放，包括未确认或未送达项')
        stage = self.stage(task)
        if stage and sum(d['review_id']==stage['id'] for d in task.get('deliveries', [])) >= stage['max_deliveries']:
            raise PermissionError('本阶段发送项已达人工批准上限')
        task.setdefault('deliveries', []).append({'key':key, 'review_id':stage['id'] if stage else None,
            'outcome':'uncertain', 'started_at':time.time(), 'start_total':self.total(task)})
        task['pending_delivery'] = key
        self.save()

    def confirm_delivery(self, task, key, outcome, receipt):
        if outcome not in ('delivered','not_sent'):
            raise ValueError('只能以新鲜观察确认delivered或not_sent；不确定项保留')
        if task.get('pending_delivery') != key:
            raise ValueError('仅核验当前未确认发送项')
        if receipt['verification'] != 'assistant_verified' or any(
                c['tool'] not in ('mobile_take_screenshot','mobile_list_elements_on_screen') for c in receipt['checks']):
            raise ValueError('送达核验需要当前界面读回且全部检查通过')
        item = next(d for d in task['deliveries'] if d['key']==key)
        item.update(outcome=outcome, receipt=copy.deepcopy(receipt), confirmed_at=time.time())
        task['pending_delivery'] = None
        self.save()
        return copy.deepcopy(item)
