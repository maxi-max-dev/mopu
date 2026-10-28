import {existsSync} from 'node:fs';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {randomUUID} from 'node:crypto';

export function eligible(state,binding,active,attempts) {
  const head=state.tasks?.find(t=>['queued','paused','running'].includes(t.status));
  return Boolean(state.owner==='agent' && state.device?.connected && !state.lease_active && head &&
    head.agent===binding.identity && !head.wait_reason && !active && (attempts[head.id]||0)<3);
}

// Event-driven continuation belongs to the existing OpenClaw host. No cron,
// model selection, phone UI polling, external delivery or cross-agent routing.
export function createResumeService(api,identityFor,deps={}) {
  const settings=api.pluginConfig||{};
  const root=settings.stateDir||(existsSync(path.join(os.homedir(),'.local/share/phone-harness')) ? path.join(os.homedir(),'.local/share/phone-harness') : path.join(os.homedir(),'.local/share/mopu'));
  const file=path.join(root,'openclaw-resume.json');
  let records={},timer=null,loading=null,busy=false,lastError='',activeSession=null;
  const running=new Set();
  const load=()=>loading ||= (async()=>{
    try{records=JSON.parse(await fs.readFile(file,'utf8'));}catch(e){if(e.code!=='ENOENT'){loading=null;throw e;}}
  })();
  let saving=Promise.resolve();
  const save=()=>{
    const data=JSON.stringify(records,null,2)+'\n';
    saving=saving.catch(()=>{}).then(async()=>{await fs.mkdir(root,{recursive:true,mode:0o700});await fs.writeFile(file+'.new',data,{mode:0o600});await fs.rename(file+'.new',file);});
    return saving;
  };
  async function bind(ctx,name) {
    if(!settings.resumeOnRelease || !ctx.sessionKey || !ctx.sessionId)return;
    await load();
    const identity=identityFor(ctx);
    const old=records[identity];
    if(!old){records[identity]={identity,agentId:ctx.agentId,sessionKey:ctx.sessionKey,sessionId:ctx.sessionId,attempts:{}};await save();}
  }
  async function tick() {
    if(busy || !settings.resumeOnRelease)return;
    busy=true;
    try {
      await load();
      const endpoint=JSON.parse(await fs.readFile(path.join(root,'endpoint.json'),'utf8'));
      const url=new URL(endpoint.url);
      if(url.protocol!=='http:'||url.hostname!=='127.0.0.1'||url.username||url.password||url.search||url.pathname!=='/')return;
      const response=await (deps.fetch||fetch)(endpoint.url+'/api/state',{headers:{'X-Phone-Token':endpoint.token},signal:AbortSignal.timeout(3000),redirect:'error'});
      if(!response.ok)return;
      const state=await response.json();
      const head=state.tasks?.find(t=>['queued','paused','running'].includes(t.status));
      if(!head)return;
      const binding=records[head.agent];
      if(binding && state.owner==='human' && binding.attempts[head.id]){
        binding.attempts[head.id]=0;await save(); // A new explicit handoff gets a fresh bounded allowance.
      }
      if(!binding||!activeSession||!eligible(state,binding,Boolean(activeSession(binding.sessionKey))||running.has(binding.sessionKey),binding.attempts))return;
      const signature=endpoint.pid+':'+state.generation+':'+head.id;
      if(binding.lastAttempt===signature)return;
      const current=await api.runtime.agent.session.getSessionEntry({agentId:binding.agentId,sessionKey:binding.sessionKey});
      if(!current||current.sessionId!==binding.sessionId)return; // Never cross a reset/new conversation.
      binding.lastAttempt=signature;binding.attempts[head.id]=(binding.attempts[head.id]||0)+1;
      binding.lastWakeAt=new Date().toISOString();binding.lastWakeTask=head.id;await save();
      running.add(binding.sessionKey);
      const cfg=api.runtime.config.current();
      const allowed=['phone_status','phone_wait','phone_tools','phone_call','phone_step','phone_delivery_confirm','phone_checkpoint','phone_finish'];
      // The fixed prompt only points to an already-authorized task; task text
      // and checkpoint are retrieved through the same lease protocol.
      const prompt='用户已在 Mopu 控制台交回手机，或前序手机任务已完成。继续本对话已有的授权手机任务，不新建任务、不发任何外部消息。先 phone_status，再 phone_wait。只执行本对话原有队列；无任务就结束。有人工接管则停止读屏和输入，最多等待两次，仍 waiting 就结束本轮，队列保留，稍后交回会自动续接。拿到控制权后 phone_tools，读 checkpoint，并重新观察当前屏幕再决定下一步。每个输入前 phone_checkpoint，输入后重新观察。不要重放超时动作，不用其他控制通道、不改静音或实体息屏设置。截图与坐标按实际工具，菜单说明不是开关状态。读取 phone_tools 的能力目录，优先使用直接能力。phone_call 的成功读回会附 phone_harness_observation ID；phone_finish 的 checks 必须关联这些新鲜ID，填写 criterion、observed、passed，并列 unresolved。缺少有效回执只保存为待核验。需要人处理时 phone_checkpoint 填 wait_reason（user_unlock/user_decision/external_service）再明确阻塞。只有实际读回才 phone_finish，然后继续原队列下一项。';
      const storePath=api.runtime.agent.session.resolveStorePath(cfg.session?.store,{agentId:binding.agentId});
      Promise.resolve().then(()=>api.runtime.agent.session.runWithWorkAdmission({storePath,sessionKey:binding.sessionKey},signal=>
        api.runtime.agent.runEmbeddedAgent({sessionId:binding.sessionId,sessionKey:binding.sessionKey,agentId:binding.agentId,
        workspaceDir:api.runtime.agent.resolveAgentWorkspaceDir(cfg,binding.agentId),
        config:cfg,prompt,runId:randomUUID(),trigger:'manual',timeoutMs:600000,abortSignal:signal,disableMessageTool:true,toolsAllow:allowed})))
        .then(async()=>{binding.lastWakeResult='completed';await save();})
        .catch(async error=>{binding.lastWakeResult='failed';binding.lastWakeError=String(error.message).slice(0,500);await save();})
        .finally(()=>running.delete(binding.sessionKey));
      lastError='';
    } catch(error) {
      // A closed console is expected. Other service failures are deduplicated.
      const code=error.code||error.cause?.code;
      if(!['ENOENT','ECONNREFUSED'].includes(code)&&error.message!==lastError){lastError=error.message;api.logger.warn('Phone continuation: '+lastError);}
    } finally {busy=false;}
  }
  return {bind,
    start:async()=>{await load();activeSession=deps.activeSession||(await import('openclaw/plugin-sdk/agent-harness-runtime')).resolveActiveEmbeddedRunSessionId;if(!timer){timer=(deps.setInterval||setInterval)(tick,4000);timer.unref?.();}},
    stop:async()=>{if(timer)(deps.clearInterval||clearInterval)(timer);timer=null;await saving;}};
}
