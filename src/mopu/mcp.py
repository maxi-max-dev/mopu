"""Agent-neutral MCP adapter. It never starts or selects a model."""
import asyncio
import contextlib
import json
import sys
from pathlib import Path
import aiohttp
from . import __version__


def schema(properties=None, required=None):
    return {'type':'object', 'properties':properties or {}, 'required':required or [], 'additionalProperties':False}


TEXT = {'type':'string'}
CHECK = schema({'criterion':TEXT,'observed':TEXT,'observation_id':TEXT,'passed':{'type':'boolean'}}, ['criterion','observed','observation_id','passed'])
TOOLS = [
    {'name':'phone_status','description':'Read connection, ownership, specific waiting reasons and capability availability. Does not read screen contents.', 'inputSchema':schema()},
    {'name':'phone_submit','description':'Queue the phone part of your authorized task under your own agent identity. This does not dispatch to another agent.',
     'inputSchema':schema({'title':TEXT,'instruction':TEXT,'required_milestones':{'type':'array','items':TEXT,'maxItems':20}}, ['title','instruction'])},
    {'name':'phone_wait','description':'Wait up to 20 seconds for your next task and exclusive phone control. If waiting, stop phone actions and wait again when appropriate. After a new lease always observe before acting.', 'inputSchema':schema()},
    {'name':'phone_tools','description':'Read actual device tool schemas and capability catalog under the lease. Catalog availability is not proof of task success.', 'inputSchema':schema()},
    {'name':'phone_call','description':'Call a listed phone tool under the current lease. Observe before every input; use fresh coordinates, never refs. On any error observe again, never replay an uncertain input.',
     'inputSchema':schema({'name':TEXT, 'arguments':{'type':'object','default':{}}}, ['name'])},
    {'name':'phone_step','description':'Execute ONE authorized input with checkpoint and fresh readback. Requires a current screen observation ID. No input retries. Choose screenshot for custom editors/webviews; expected_text is only a substring diagnostic, not task verification.',
     'inputSchema':schema({'name':TEXT,'arguments':{'type':'object','default':{}},'target':schema({'id':TEXT,'text':TEXT,'label':TEXT,'type':TEXT}),'observation_id':TEXT,'progress':TEXT,'next_action':TEXT,'observe':{'type':'string','enum':['text','screenshot'],'default':'text'},'expected_text':{'type':'string','minLength':1,'maxLength':500},'settle_ms':{'type':'integer','minimum':400,'maximum':5000,'default':400,'description':'Bounded delay before first readback for lazy-loaded content; not proof of readiness. Input is never repeated.'},'read_attempts':{'type':'integer','minimum':1,'maximum':3,'default':1}}, ['name','observation_id','progress','next_action'])},
    {'name':'phone_milestone','description':'Seal a completed workflow stage BEFORE switching apps. Requires fresh passed checks. Key is immutable; reuse identical key/checks only for acknowledgement recovery. Historical stage evidence never replaces final fresh readback.',
     'inputSchema':schema({'key':{'type':'string','minLength':1,'maxLength':80},'checks':{'type':'array','items':CHECK,'minItems':1,'maxItems':20}},['key','checks'])},
    {'name':'phone_checkpoint','description':'Save completed progress and describe the next phone action so the user can understand and interrupt it.',
     'inputSchema':schema({'progress':TEXT,'next_action':TEXT,'wait_reason':{'type':'string','enum':['','user_unlock','user_decision','external_service'],'default':''}}, ['progress','next_action'])},
    {'name':'phone_finish','description':'Save results and release the phone. To mark verified, supply checks referring to broker-issued phone_harness_observation IDs from fresh reads after the last input. Otherwise the result is saved as unverified. Never use tool acknowledgements as proof. Store only minimal non-sensitive readbacks.',
     'inputSchema':schema({'result':TEXT,'blocked':{'type':'boolean','default':False},'required_milestones':{'type':'array','items':TEXT,'maxItems':20},'checks':{'type':'array','items':CHECK,'maxItems':20},'unresolved':{'type':'array','items':TEXT,'maxItems':20}}, ['result'])},
]


class Client:
    def __init__(self, state, agent, name):
        self.state, self.agent, self.name = Path(state), agent, name
        self.endpoint = self.identity = None
        self.lease = None
        self.session = None

    async def post(self, body):
        async with self.session.post(self.endpoint['url']+'/api/agent', json=body,
                headers={'X-Phone-Token':self.endpoint['token']}) as response:
            result = await response.json()
            if response.status != 200:
                raise RuntimeError(result.get('error', 'Phone console request failed'))
            return result

    async def request(self, action, args=None):
        endpoint = json.loads((self.state/'endpoint.json').read_text())
        if self.endpoint != endpoint or self.identity is None:
            self.endpoint, self.lease = endpoint, None
            self.identity = await self.post({'action':'register', 'agent':self.agent, 'name':self.name})
        result = await self.post({**(args or {}), **self.identity, 'action':action, 'lease':self.lease or ''})
        if action == 'wait' and result.get('lease'):
            self.lease = result.pop('lease')
        if action == 'finish': self.lease = None
        return result


async def stdio(state, agent, name):
    client = Client(state, agent, name)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=65)) as session:
        client.session = session
        while True:
            line = await asyncio.to_thread(sys.stdin.readline)
            if not line: return
            try:
                message = json.loads(line)
                ident = message.get('id')
                if ident is None: continue
                method = message.get('method')
                if method == 'initialize':
                    result = {'protocolVersion':'2024-11-05','capabilities':{'tools':{}},'serverInfo':{'name':'mopu','version':__version__},
                        'instructions':'Use phone_status, submit only authorized phone tasks, then phone_wait. Human takeover revokes the lease. Never use another ADB/MCP path to bypass it. The queue does not start an AI model.'}
                elif method == 'ping': result = {}
                elif method == 'tools/list': result = {'tools':TOOLS}
                elif method == 'tools/call':
                    params = message.get('params', {})
                    name = params.get('name', '')
                    if name not in {t['name'] for t in TOOLS}: raise ValueError('Unknown tool')
                    action = name.removeprefix('phone_')
                    try:
                        value = await client.request(action, params.get('arguments', {}))
                        result = value if action in ('call','step') else {'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}]}
                    except Exception as exc:
                        result = {'isError':True,'content':[{'type':'text','text':str(exc)+'; inspect current state before any new input.'}]}
                else:
                    print(json.dumps({'jsonrpc':'2.0','id':ident,'error':{'code':-32601,'message':'Method not found'}}),flush=True)
                    continue
                print(json.dumps({'jsonrpc':'2.0','id':ident,'result':result},ensure_ascii=False),flush=True)
            except (ValueError, KeyError) as exc:
                print(json.dumps({'jsonrpc':'2.0','id':None,'error':{'code':-32600,'message':str(exc)}}),flush=True)
