import test from 'node:test';
import assert from 'node:assert/strict';
import {createBridge,identityFor} from './index.js';
import {eligible} from './resume.js';

const ctx={agentId:'main',sessionId:'conversation-A'};
function fixture() {
  const calls=[]; let fail=false;
  const run=createBridge({}, {load:async()=>JSON.stringify({url:'http://127.0.0.1:18796',token:'test'}),fetch:async(_url,options)=>{
    const p=JSON.parse(options.body); calls.push(p);
    if(fail && p.action==='call') throw Error('uncertain timeout');
    return {ok:true,json:async()=>p.action==='register'?{agent:p.agent,agent_token:p.agent}:p.action==='wait'?{lease:'lease-'+p.agent,task:{id:'t'}}:p.action==='call'?{content:[{type:'text',text:'observed'}]}:{saved:true}};
  }});
  return {run,calls,fail:()=>{fail=true;}};
}
test('separate conversations and resets have separate stable identities',()=>{
  assert.equal(identityFor(ctx),identityFor({...ctx}));
  assert.notEqual(identityFor(ctx),identityFor({...ctx,sessionId:'B'}));
  assert.throws(()=>identityFor({agentId:'main'}));
});
test('per conversation registration and lease, no forged identity from args',async()=>{
  const f=fixture(); await f.run(ctx,'phone_wait',{}); await f.run(ctx,'phone_checkpoint',{agent:'forged',lease:'forged'});
  await f.run({...ctx,sessionId:'B'},'phone_status',{});
  assert.equal(f.calls.filter(p=>p.action==='register').length,2);
  assert.equal(f.calls[2].agent,identityFor(ctx)); assert.equal(f.calls[2].lease,'lease-'+identityFor(ctx));
});
test('failed input is called once and does not discard acquired lease',async()=>{
  const f=fixture(); await f.run(ctx,'phone_wait',{}); f.fail();
  assert.equal((await f.run(ctx,'phone_call',{name:'input',arguments:{}})).isError,true);
  await f.run(ctx,'phone_status',{});
  assert.equal(f.calls.filter(p=>p.action==='call').length,1);
  assert.equal(f.calls.at(-1).lease,'lease-'+identityFor(ctx));
});
test('unauthorized agent and non-loopback endpoint are rejected without fetch',async()=>{
  const f=fixture(); assert.equal((await f.run({...ctx,agentId:'worker'},'phone_status',{})).isError,true);assert.equal(f.calls.length,0);
  let calls=0;const run=createBridge({}, {load:async()=>JSON.stringify({url:'https://example.com',token:'secret'}),fetch:()=>{calls++;}});
  assert.equal((await run(ctx,'phone_status',{})).isError,true);assert.equal(calls,0);
});
test('continuation only wakes the original idle conversation after release, bounded to three attempts',()=>{
  const state={owner:'agent',device:{connected:true},lease_active:false,tasks:[{id:'a',agent:'original',status:'paused'}]};
  const binding={identity:'original'};
  assert.equal(eligible(state,binding,false,{}),true);
  for(const s of [{...state,owner:'human'},{...state,owner:'paused'},{...state,lease_active:true},{...state,device:{connected:false}}])assert.equal(eligible(s,binding,false,{}),false);
  assert.equal(eligible(state,{identity:'other'},false,{}),false);
  assert.equal(eligible(state,binding,true,{}),false);
  assert.equal(eligible(state,binding,false,{a:3}),false);
});

test('resume service waits for idle, uses host admission, and renews allowance only after human control',async()=>{
  const fs=await import('node:fs/promises');const os=await import('node:os');const path=await import('node:path');
  const {createResumeService}=await import('./resume.js');
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'phone-resume-test-'));
  let tick,active=true,run,admitted=false;
  const identity=identityFor(ctx), state={owner:'human',generation:1,device:{connected:true},lease_active:false,tasks:[{id:'task',agent:identity,status:'queued'}]};
  await fs.writeFile(path.join(dir,'endpoint.json'),JSON.stringify({url:'http://127.0.0.1:18796',token:'test',pid:1}));
  const api={pluginConfig:{stateDir:dir,resumeOnRelease:true},logger:{warn:m=>assert.fail(m)},runtime:{config:{current:()=>({})},agent:{
    resolveAgentWorkspaceDir:()=>dir,runEmbeddedAgent:async p=>{run=p;},session:{getSessionEntry:()=>({sessionId:ctx.sessionId}),resolveStorePath:()=>dir,
    runWithWorkAdmission:async(p,fn)=>{assert.equal(p.sessionKey,'original');admitted=true;return fn(new AbortController().signal);}}}}};
  const service=createResumeService(api,identityFor,{fetch:async()=>({ok:true,json:async()=>state}),activeSession:()=>active?'running':undefined,
    setInterval:fn=>{tick=fn;return {unref(){}};},clearInterval:()=>{}});
  try{
    await service.start();await service.bind({...ctx,sessionKey:'original'});
    await tick();assert.equal(run,undefined);
    state.owner='agent';await tick();assert.equal(run,undefined);
    active=false;await tick();await new Promise(r=>setTimeout(r,15));
    assert.equal(admitted,true);assert.equal(run.sessionId,ctx.sessionId);assert.equal(run.sessionKey,'original');
    assert.equal(run.disableMessageTool,true);assert.equal(run.toolsAllow.includes('phone_submit'),false);assert.ok(run.abortSignal);
    let saved=JSON.parse(await fs.readFile(path.join(dir,'openclaw-resume.json'),'utf8'));
    assert.equal(saved[identity].attempts.task,1);
    state.owner='human';await tick();saved=JSON.parse(await fs.readFile(path.join(dir,'openclaw-resume.json'),'utf8'));
    assert.equal(saved[identity].attempts.task,0);
  }finally{await service.stop();await fs.rm(dir,{recursive:true,force:true});}
});

test('declared human/service wait suppresses automatic host continuation',()=>{
 const state={owner:'agent',device:{connected:true},lease_active:false,tasks:[{id:'a',agent:'owner',status:'paused',wait_reason:'user_decision'}]};
 assert.equal(eligible(state,{identity:'owner'},false,{}),false);
 state.tasks[0].wait_reason='';assert.equal(eligible(state,{identity:'owner'},false,{}),true);
});
