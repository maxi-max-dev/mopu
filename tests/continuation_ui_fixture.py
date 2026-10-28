"""Generate synthetic UI state. Does not read production settings or devices."""
import argparse
import json
import tempfile
from pathlib import Path
from mopu.app import Console

parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
with tempfile.TemporaryDirectory() as directory:
    c=Console({'serial':'synthetic','adb':'/NO-DEVICE','scrcpy_server':'/NO-DEVICE','backend_command':['/NO-DEVICE']},directory)
    task=c.queue.get(c.queue.add('离线合成任务 · 非真实BOSS任务','仅验证人工阶段审批界面，不发送任何消息','offline-test','离线测试')['id'])
    task.update(status='blocked',steps=200,checkpoint='合成进度：已核验3项，未确认0项',result='合成预算耗尽')
    c.queue.owner='human'
    Path(args.output).write_text(json.dumps(c.snapshot(),ensure_ascii=False))
