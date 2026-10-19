import {existsSync} from 'node:fs';
import fs from 'node:fs/promises';
import {readFileSync} from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {createHash} from 'node:crypto';
import {createResumeService} from './resume.js';

export const tools = JSON.parse(readFileSync(new URL('./tools.json', import.meta.url), 'utf8'));
const text = value => ({content:[{type:'text',text:JSON.stringify(value)}]});

export function identityFor(ctx) {
  const conversation = ctx.sessionId || ctx.sessionKey;
  if (!ctx.agentId || !conversation) throw Error('Missing host conversation identity; phone access refused');
  return 'openclaw-' + createHash('sha256').update(ctx.agentId+'\0'+conversation).digest('hex').slice(0,24);
}

// Each OpenClaw conversation gets its own broker identity and lease. The model
// cannot supply or select someone else's identity. There is no model worker here.
export function createBridge(config = {}, deps = {}) {
  const stateDir = config.stateDir || (existsSync(path.join(os.homedir(),'.local/share/phone-harness')) ? path.join(os.homedir(),'.local/share/phone-harness') : path.join(os.homedir(),'.local/share/mopu'));
  const clients = new Map();
  const load = deps.load || (() => fs.readFile(path.join(stateDir,'endpoint.json'),'utf8'));
  const fetcher = deps.fetch || fetch;
  async function post(endpoint, body) {
    const url = new URL(endpoint.url);
    if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || url.username || url.password || url.search || url.pathname !== '/') {
      throw Error('Phone endpoint must be a local loopback URL');
    }
    const response = await fetcher(endpoint.url+'/api/agent', {
      method:'POST', headers:{'Content-Type':'application/json','X-Phone-Token':endpoint.token},
      body:JSON.stringify(body), signal:AbortSignal.timeout(65000), redirect:'error',
    });
    const result = await response.json();
    if (!response.ok) throw Error(result.error || 'Phone request failed');
    return result;
  }
  return async function invoke(ctx, name, args) {
    try {
      if (!(config.allowedAgents || ['main']).includes(ctx.agentId)) throw Error('This assistant is not enabled for Mopu');
      if (!tools.some(t=>t.name===name)) throw Error('Unknown phone tool');
      const agent = identityFor(ctx);
      let client = clients.get(agent);
      if (!client) {
        if (clients.size >= 128) throw Error('Phone conversation limit reached; restart the gateway when idle');
        client = {endpoint:null, identity:null, lease:null, chain:Promise.resolve()}; clients.set(agent,client);
      }
      const run = async () => {
        const endpoint = JSON.parse(await load());
        const signature = JSON.stringify(endpoint);
        if (client.endpoint !== signature) {
          client.lease = null;
          client.identity = await post(endpoint, {action:'register',agent,name:(config.displayName || 'Jarvis')+' · '+agent.slice(-4)});
          client.endpoint = signature;
        }
        const action = name.slice('phone_'.length);
        const result = await post(endpoint, {...args,...client.identity,action,lease:client.lease || ''});
        if (action === 'wait' && result.lease) {client.lease=result.lease; delete result.lease;}
        if (action === 'finish') client.lease=null;
        return ['call','step'].includes(action) ? result : text(result);
      };
      const result = client.chain.then(run);
      client.chain = result.catch(()=>{});
      const response = await result;
      await deps.onInvoke?.(ctx,name,response);
      return response;
    } catch(error) {
      // Never replay a timed-out phone action. The next call must inspect state.
      return {isError:true,content:[{type:'text',text:String(error.message)+'; inspect state, then reacquire and observe before new input. Never replay an uncertain action.'}]};
    }
  };
}

export default {id:'phone-harness',name:'Mopu',register(api) {
  const resume = createResumeService(api,identityFor);
  const invoke = createBridge(api.pluginConfig || {},{onInvoke:resume.bind});
  if (api.pluginConfig?.resumeOnRelease) {
    api.registerService({id:'phone-harness-resume',start:resume.start,stop:resume.stop});
  }
  for (const tool of tools) api.registerTool(ctx => ({
    name:tool.name,label:tool.name,description:tool.description,
    parameters:tool.inputSchema,execute:(_id,args)=>invoke(ctx,tool.name,args),
  }),{name:tool.name,optional:true});
}};
