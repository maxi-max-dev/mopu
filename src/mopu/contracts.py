"""Task receipts and explanations. No phone contents are collected here."""
import copy
import datetime
import secrets
import time

WAIT_REASONS = {'user_unlock', 'user_decision', 'external_service'}
REASON_TEXT = {
    'device_offline': ('等待手机连接', '连接手机后交回原助手'),
    'human_control': ('等待你交回手机', '操作完成后点「交回助手」'),
    'paused': ('任务已暂停', '交回原助手后重新观察'),
    'handoff': ('正在交接控制权', '等待已发出的动作结束'),
    'queue': ('等待前序任务', '前序任务结束后由原助手领取'),
    'agent_inactive': ('等待原助手继续', '回到原对话要求继续；控制台不会启动模型'),
    'ready': ('等待原助手领取', '原助手调用 phone_wait 后继续'),
    'user_unlock': ('等待解锁', '先尝试正常滑动；身份验证由设备主人完成'),
    'user_decision': ('等待你的决定', '处理后重新排队或交回原助手'),
    'external_service': ('等待外部服务', '核实服务结果后继续，勿重复提交'),
    'verification': ('结果待核验', '原助手读取新鲜状态并补充完成回执'),
    'running': ('正在执行', '可随时接管手机'),
    'blocked': ('需要处理', '查看阻塞原因，处理后重新排队'),
}


def explanation(task, owner, connected, head_id, online, locked=False):
    status = task['status']
    if status in ('done', 'cancelled'):
        return None
    if status == 'unverified': code = 'verification'
    elif status == 'blocked': code = task.get('wait_reason') or 'blocked'
    elif not connected: code = 'device_offline'
    elif owner == 'transition': code = 'handoff'
    elif owner == 'human': code = 'human_control'
    elif owner == 'paused': code = 'paused'
    elif task.get('wait_reason'): code = task['wait_reason']
    elif task['id'] != head_id: code = 'queue'
    elif not online: code = 'agent_inactive'
    elif status == 'running': code = 'running'
    else: code = 'ready'
    label, action = REASON_TEXT[code]
    if code in WAIT_REASONS and task.get('action'):
        action = task['action']
    # Lock telemetry is a hint, not proof the agent cannot swipe to unlock.
    return {'code': code, 'label': label, 'next_action': action,
            'detail': task.get('action', ''), 'lock_hint': bool(locked)}


class Observations:
    """Ephemeral, broker-issued references; raw screens/text are never stored."""
    def __init__(self):
        self.records = {}
        self.mutations = {}

    def invalidate(self, task_id):
        self.mutations[task_id] = time.monotonic()

    def record(self, task_id, generation, tool):
        stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        record = {'id': secrets.token_hex(12), 'task_id': task_id,
                  'generation': generation, 'tool': tool, 'observed_at': stamp}
        self.records[record['id']] = {**record, 'monotonic': time.monotonic()}
        while len(self.records) > 256: self.records.pop(next(iter(self.records)))
        return record

    def receipt(self, task_id, generation, checks, unresolved, blocked=False):
        if checks is None: checks = []
        if unresolved is None: unresolved = []
        if not isinstance(checks, list) or len(checks) > 20:
            raise ValueError('checks 必须是至多20项的验收列表')
        if not isinstance(unresolved, list) or len(unresolved) > 20 or any(not isinstance(x, str) or len(x)>1000 for x in unresolved):
            raise ValueError('unresolved 必须是至多20条简短说明')
        checked = []
        for item in checks:
            if not isinstance(item, dict) or set(item)-{'criterion','observed','observation_id','passed'}:
                raise ValueError('验收项只允许 criterion/observed/observation_id/passed')
            if any(not isinstance(item.get(k), str) or not item[k].strip() or len(item[k])>2000 for k in ('criterion','observed','observation_id')) or type(item.get('passed')) is not bool:
                raise ValueError('每项需填写验收目标、实际观察、观察ID与布尔 passed')
            obs = self.records.get(item['observation_id'])
            if not obs or obs['task_id'] != task_id or obs['generation'] != generation:
                raise ValueError('观察ID不属于本任务当前控制权；请重新观察')
            if time.monotonic()-obs['monotonic'] > 120 or obs['monotonic'] <= self.mutations.get(task_id, -1):
                raise ValueError('观察已过期或其后发生操作；请重新读回再完成')
            checked.append({**copy.deepcopy(item), 'tool': obs['tool'], 'observed_at': obs['observed_at']})
        verified = bool(checked) and all(c['passed'] for c in checked) and not unresolved and not blocked
        return {'version': 1, 'verification': 'assistant_verified' if verified else 'unverified',
                'checks': checked, 'unresolved': list(unresolved),
                'scope': '原助手判断与本任务新鲜工具观察关联；不是独立事实认证。'}
