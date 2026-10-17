#!/usr/bin/env python3
"""Loopback-only UI fixture. No ADB, broker, device state or model is accessed.
Run python3 tools/preview.py, open http://127.0.0.1:18797. All data is synthetic.
"""
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime, timezone
import argparse, json
ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'src/phone_harness/web'
state = {
 'owner':'agent','current':'demo-a','generation':1,'settings':{'close_pauses':True},
 'agents':[{'id':'demo-codex','name':'Codex','online':True},{'id':'demo-claude','name':'Claude','online':True},{'id':'demo-jarvis','name':'Jarvis','online':False}],
 'tasks':[
  {'id':'demo-a','agent':'demo-codex','agent_name':'Codex','title':'整理收藏中的阅读笔记','instruction':'示例任务：从收藏中提取主题和要点。','status':'running','action':'正在查看收藏列表 · 2 / 4','checkpoint':'已阅读两条示例笔记','result':''},
  {'id':'demo-b','agent':'demo-jarvis','agent_name':'Jarvis','title':'查看今天的待办事项','instruction':'示例任务：检查待办事项，不修改内容。','status':'queued','action':'等待前一项完成','checkpoint':'','result':''},
  {'id':'demo-c','agent':'demo-claude','agent_name':'Claude','title':'验证应用的登录流程','instruction':'示例任务：观察登录页，不输入凭据。','status':'queued','action':'等待手机控制权','checkpoint':'','result':''}],
 'events':[],
 'device':{'connected':True,'width':720,'height':1600,'error':None,'telemetry':{'panel':'off','panel_age':0},'health':{}}
}

def refresh():
 now=datetime.now(timezone.utc).isoformat()
 state['device']['telemetry']['panel_at']=now
 streams={k:{'silent':True,'volume':0,'max':15,'route':'speaker'} for k in ['MUSIC','RING','NOTIFICATION','ALARM','SYSTEM','DTMF','SYSTEM_ENFORCED','VOICE_CALL','BLUETOOTH_SCO']}
 data={'audio':{'streams':streams,'basic_silent':True,'microphone':{'active':False,'apps':[]},'call_active':False,'mode':'MODE_NORMAL','ringer':'SILENT','communication_route':'earpiece'},
 'settings':{'zen_mode':2,**{k:0 for k in ['dtmf_tone','sound_effects_enabled','haptic_feedback_enabled','vibrate_when_ringing','keyboard_vibration_enabled','notification_vibration_intensity','ring_vibration_intensity','alarm_vibration_intensity','charging_sounds_enabled','charging_vibration_enabled']}},
 'battery':{'percent':78,'status':'charging','plugged':True,'sources':['USB'],'temperature':28.4,'voltage_mv':4110},
 'camera':{'active':False,'apps':[]},'torch':{'active':False,'available':True},'projection':{'active':False,'apps':[]}}
 state['device']['health']={k:{'fresh':True,'age':0,'at':now,'data':v} for k,v in data.items()}
 return state

class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args): pass
 def reply(self,data,mime='application/json'):
  if not isinstance(data,bytes):data=data.encode()
  self.send_response(200);self.send_header('Content-Type',mime+'; charset=utf-8');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
 def do_GET(self):
  path=self.path.split('?')[0]
  if path=='/':
   html=(WEB/'index.html').read_text().replace('__PHONE_TOKEN__','demo-not-a-credential').replace('</body>','<script src="/preview.js"></script></body>')
   return self.reply(html,'text/html')
  if path=='/api/state':return self.reply(json.dumps(refresh()))
  if path=='/preview.js':return self.reply((ROOT/'tools/preview.js').read_bytes(),'application/javascript')
  if path=='/demo.svg':return self.reply((ROOT/'docs/demo-screen.svg').read_bytes(),'image/svg+xml')
  if path in ['/static/style.css','/static/actions.js','/static/app.js']:
   f=WEB/Path(path).name;data=f.read_text()
   if path.endswith('app.js'):data=data[:data.rfind("poll();if('VideoDecoder'")]+"poll();\n"
   return self.reply(data,'text/css' if path.endswith('css') else 'application/javascript')
  self.send_error(404)
 def do_POST(self):
  if self.path!='/api/control':return self.send_error(404)
  payload=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
  a=payload.get('action')
  if a in ['takeover','release','pause']:
   state['owner']={'takeover':'human','release':'agent','pause':'paused'}[a]
   state['generation']+=1
   for t in state['tasks']:
    if t['status']=='running':t['status']='paused'
   state['current']=None
   if a=='release':
    t=next((t for t in state['tasks'] if t['status'] in ['paused','queued']),None)
    if t:t['status']='running';state['current']=t['id']
  if a=='panel_power':state['device']['telemetry']['panel']='on' if payload['on'] else 'off'
  if a=='rotate':state['device']['width'],state['device']['height']=state['device']['height'],state['device']['width']
  if a in ['disconnect','connect']:state['device']['connected']=a=='connect'
  if a=='close_preference':state['settings']['close_pauses']=payload['enabled']
  if a in ['move','prioritize']:
   tasks=state['tasks'];i=next(i for i,t in enumerate(tasks) if t['id']==payload['id']);j=0 if a=='prioritize' else max(0,min(len(tasks)-1,i+(-1 if payload['direction']=='up' else 1)));tasks.insert(j,tasks.pop(i))
  if a=='cancel':
   for t in state['tasks']:
    if t['id']==payload['id']:t['status']='cancelled'
  if a=='add':
   agent=next(t for t in state['agents'] if t['id']==payload['agent']);state['tasks'].append({'id':'demo-'+str(len(state['tasks'])),'agent':agent['id'],'agent_name':agent['name'],'title':payload['title'],'instruction':payload['instruction'],'status':'queued','action':'等待执行','checkpoint':'','result':''})
  self.reply(json.dumps(refresh()))

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',type=int,default=18797);a=p.parse_args()
 print(f'Synthetic UI fixture: http://127.0.0.1:{a.port} (no phone connection)',flush=True)
 ThreadingHTTPServer(('127.0.0.1',a.port),Handler).serve_forever()
