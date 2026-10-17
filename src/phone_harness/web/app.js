'use strict';
const $ = id => document.getElementById(id);
const canvas = $('screen'), context = canvas.getContext('2d', {alpha:false});
const actionOverlay = new ActionOverlay($('actionLayer'),canvas,$('actionCaption'));
try{$('showActions').checked=localStorage.getItem('phone-actions-visible')!=='false';const size=localStorage.getItem('phone-actions-size');if(['44','64','88'].includes(size))$('actionSize').value=size;}catch{}
function configureActions(){actionOverlay.configure($('showActions').checked,Number($('actionSize').value));try{localStorage.setItem('phone-actions-visible',String($('showActions').checked));localStorage.setItem('phone-actions-size',$('actionSize').value);}catch{}}
$('showActions').onchange=configureActions;$('actionSize').onchange=configureActions;configureActions();
let state = null, socket = null, decoder = null, config = null, needKey = true;
let rendered = 0, lastFrame = 0, frameWindow = 0, fps = 0, packetSize = {width:0,height:0};
let showHistory = false;
let toastTimer, queueSignature = '', detailId = null, controlBusy = false, pointer = null;
let panelBusy = false, previousPanel = 'unknown', stateReceivedAt = 0;
const labels = {queued:'等待执行',running:'正在执行',paused:'已暂停',done:'已完成',blocked:'需要处理',cancelled:'已结束'};
function toast(text) { $('toast').textContent = text; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('toast').hidden=true,6000); }
function element(tag, cls, text) { const node=document.createElement(tag); if(cls)node.className=cls; if(text!==undefined)node.textContent=text; return node; }
async function api(path, body) {
 const response = await fetch('/api/'+path, {method:body?'POST':'GET', headers:{'X-Phone-Token':window.PHONE_TOKEN,'Content-Type':'application/json'}, ...(body?{body:JSON.stringify(body)}:{})});
 const result=await response.json(); if(!response.ok)throw Error(result.error||'本地服务请求失败'); return result;
}
async function control(action, data={}) {
 if(controlBusy)return;
 controlBusy=true;
 try { state=await api('control',{action,...data}); stateReceivedAt=performance.now(); render(); if(state.notice)toast(state.notice); }
 catch(error){toast(error.message);}
 finally {controlBusy=false;}
}
function show(id){$(id).showModal();}
document.querySelectorAll('[data-close]').forEach(button=>button.onclick=()=>button.closest('dialog').close());
document.querySelectorAll('dialog').forEach(dialog=>dialog.addEventListener('click',event=>{if(event.target===dialog){const rect=dialog.getBoundingClientRect();if(event.clientX<rect.left||event.clientX>rect.right||event.clientY<rect.top||event.clientY>rect.bottom)dialog.close();}}));
function taskPane(open){$('taskPane').classList.toggle('collapsed',!open);$('toggleTasks').setAttribute('aria-expanded',String(open));$('toggleTasks').setAttribute('aria-label',open?'收起任务队列':'展开任务队列');$('toggleTasks').title=open?'收起任务队列':'展开任务队列';}
$('toggleTasks').onclick=()=>{document.body.classList.remove('focus');$('focus').setAttribute('aria-pressed','false');taskPane($('taskPane').classList.contains('collapsed'));};
$('railHistory').onclick=()=>{document.body.classList.remove('focus');$('focus').setAttribute('aria-pressed','false');taskPane(true);showHistory=true;renderQueue();};
$('queueTab').onclick=()=>{showHistory=false;renderQueue();};
$('historyTab').onclick=()=>{showHistory=true;renderQueue();};
$('closePauses').onchange=()=>control('close_preference',{enabled:$('closePauses').checked});
$('focus').onclick=()=>{const focused=document.body.classList.toggle('focus');$('focus').setAttribute('aria-pressed',String(focused));};
$('settingsOpen').onclick=()=>show('settings');
$('integrationOpen').onclick=()=>show('integration');
for (const action of ['connect','takeover','release','pause','reconnect','rotate']) $(action).onclick=()=>control(action);
$('panelPower').onclick=async()=>{if(controlBusy||panelBusy)return;const on=panelState()==='off';panelBusy=true;renderPanel();try{await control('panel_power',{on});}finally{panelBusy=false;renderPanel();}};
$('disconnect').onclick=async()=>{await control('disconnect');$('settings').close();};
$('addOpen').onclick=()=>{
 const agents=state?.agents||[];
 if(!agents.length){show('integration');return;}
 $('agentSelect').replaceChildren(...agents.map(agent=>{const option=element('option','',agent.name);option.value=agent.id;return option;}));
 show('newTask');
};
$('newTaskForm').onsubmit=async event=>{event.preventDefault();try{state=await api('control',{action:'add',title:$('taskTitle').value,instruction:$('taskInstruction').value,agent:$('agentSelect').value});$('newTask').close();$('newTaskForm').reset();render();}catch(error){toast(error.message);}};
function send(data){if(socket?.readyState!==WebSocket.OPEN){toast('视频连接未就绪，请重新连接。');return false;}socket.send(JSON.stringify({...data,generation:state?.generation}));return true;}
function hasControl(){return state?.owner==='human'&&state?.device.connected;}
function panelState(){const t=state?.device.telemetry;if(!state?.device.connected||performance.now()-stateReceivedAt>3500||t?.panel_age==null||t.panel_age+(performance.now()-stateReceivedAt)/1000>5)return 'unknown';return ['on','off'].includes(t.panel)?t.panel:'unknown';}
function renderPanel(){
 const panel=panelState(), button=$('panelPower'), label={on:'已亮屏',off:'已息屏',unknown:'待确认'}[panel];
 button.className='panel-power '+panel+(panelBusy?' pending':'');button.disabled=!state?.device.connected||panelBusy;
 $('panelLabel').textContent=panelBusy?'核验中':label;$('panelAction').textContent=panel==='off'?'点击亮屏':'点击息屏';
 button.setAttribute('aria-label','实体屏幕'+label+'，'+$('panelAction').textContent);
 if(panel==='unknown')button.removeAttribute('aria-pressed');else button.setAttribute('aria-pressed',String(panel==='on'));
 button.title=panel==='unknown'?'实体面板状态暂时无法确认；点击明确发送息屏指令':label+' · 手机系统读回 · '+$('panelAction').textContent+'，投屏继续';
 $('panelStatus').textContent='实体屏幕 '+label;$('panelStatus').className=panel;
 if(panel==='on'&&previousPanel!=='on')toast('实体屏幕亮着，身边的人可以看到。点右侧指示灯可息屏。');
 if(panel!=='on'&&$('toast').textContent==='实体屏幕亮着，身边的人可以看到。点右侧指示灯可息屏。')$('toast').hidden=true;
 previousPanel=panel;
}
let healthTab='audio', previousActivity='';
const healthNames={audio:'静音细项',battery:'充电与电池',verified:'最后核验时间',privacy:'摄像头、麦克风与闪光灯'};
for(const key of Object.keys(healthNames))$(key+'Status').onclick=()=>openHealth(key);
$('quiet').onclick=()=>openHealth('audio');
$('activityBanner').onclick=()=>openHealth('privacy');
$('applyQuiet').onclick=()=>control('quiet');
function healthGroup(key){
 const g=state?.device.health?.[key], age=(g?.age??Infinity)+(performance.now()-stateReceivedAt)/1000;
 const fresh=!!(state?.device.connected&&g?.fresh&&performance.now()-stateReceivedAt<=3500&&age<=(['battery','settings'].includes(key)?20:7));
 return {data:fresh?g.data:{},fresh,at:g?.at,age};
}
function openHealth(key){healthTab=key;renderHealth();if(!$('healthDetail').open)show('healthDetail');}
function healthRow(label,text,tone=''){const row=element('div','health-row');row.append(element('span','',label),element('strong',tone,text));return row;}
function routeLabel(route){if(!route)return '待核验';return route.replace(/bluetooth_sco/g,'蓝牙通话').replace(/bluetooth_a2dp/g,'蓝牙媒体').replace(/wired_headset/g,'有线耳麦').replace(/wired_headphone/g,'有线耳机').replace(/usb_headset/g,'USB 耳机').replace(/earpiece/g,'手机听筒').replace(/speaker/g,'手机扬声器').replace(/\([0-9a-fx]+\)/g,'');}
function timeLabel(at){return at?new Date(at).toLocaleString('zh-CN',{hour12:false}):'尚未核验';}
function renderHealth(){
 const audio=healthGroup('audio'), a=audio.data, settings=healthGroup('settings'), q=settings.data;
 const battery=healthGroup('battery'), b=battery.data, camera=healthGroup('camera'), projection=healthGroup('projection'), torch=healthGroup('torch');
 const signals=[['手电筒',torch.data.active,[]],['摄像头',camera.data.active,camera.data.apps],['麦克风',a.microphone?.active,a.microphone?.apps],['系统录屏',projection.data.active,projection.data.apps],['通话音频',a.call_active,[]]];
 const activeLabel=label=>label+(label==='手电筒'?'正在亮灯':'正在使用');
 const active=signals.filter(x=>x[1]===true), unknown=signals.some(x=>x[1]==null);
 const basic=audio.fresh&&a.basic_silent===true&&settings.fresh&&q.zen_mode===2;
 function icon(key,label,tone){const el=$(key+'Status');el.className='health-icon '+tone;el.title=label;el.setAttribute('aria-label',healthNames[key]+'：'+label);}
 const callMuted=a.streams?.VOICE_CALL?.silent===true&&a.streams?.BLUETOOTH_SCO?.silent===true;
 icon('audio',!audio.fresh?'静音状态待核验':basic?(callMuted?'基础与通话通道当前已静音；接通后需再次核验':'基础音频已静音；通话仍可能出声'):'基础静音需检查',audio.fresh?(basic&&callMuted?'good':'warning'):'unknown');
 const chargeNames={charging:'正在充电',discharging:'电池供电',not_charging:'已接电，未充电',full:'已充满',unknown:'充电状态待核验'};
 const charge=battery.fresh?(b.protection_paused?'充电保护已暂停':chargeNames[b.status]||'待核验'):'待核验';
 icon('battery',(b.percent==null?'电量待核验':b.percent+'%')+' · '+charge,battery.fresh&&b.plugged!=null?'good':'unknown');
 icon('privacy',active.length?active.map(x=>activeLabel(x[0])).join(' · '):unknown?'部分设备使用状态待核验':'手电筒已关闭；未检测到设备活动 · 点开查看检测范围',active.length?'alert':unknown?'unknown':'good');
 const groups=[['实体屏幕',state?.device.telemetry?.panel_at,panelState()!=='unknown'],...Object.entries({audio:'音频与麦克风',settings:'静音开关',battery:'充电与电池',camera:'摄像头',torch:'手电筒',projection:'系统录屏'}).map(([k,label])=>[label,healthGroup(k).at,healthGroup(k).fresh])];
 const verified=groups.every(x=>x[2]);
 icon('verified',verified?'读数有效 · 点击查看各项核验时间':'有读数过期或未取得 · 点击查看',verified?'good':'unknown');
 const banner=$('activityBanner');banner.hidden=!active.length;
 const activityText=active.map(x=>activeLabel(x[0])+(x[2]?.length?' · '+x[2].join('、'):'')).join('  /  ')+(a.call_active?' · 通话仍可能从手机发声':'');
 banner.textContent='● '+activityText+'  ›';
 if(active.length&&activityText!==previousActivity)toast(activityText);
 previousActivity=activityText;
 $('healthTitle').textContent=healthNames[healthTab];
 $('applyQuiet').hidden=healthTab!=='audio';$('applyQuiet').disabled=!state?.device.connected||controlBusy;
 const rows=[];let note='';
 if(healthTab==='audio'){
  rows.push(healthRow('基础静音',basic?'已读回确认':audio.fresh?'需检查或恢复':'待核验',basic?'good':'warning'));
  const names={MUSIC:'媒体',RING:'铃声',NOTIFICATION:'通知',ALARM:'闹钟',SYSTEM:'触摸音效',DTMF:'拨号音频',SYSTEM_ENFORCED:'系统强制音',VOICE_CALL:'电话听筒／通话',BLUETOOTH_SCO:'蓝牙通话通道'};
  for(const [key,label]of Object.entries(names)){
   const s=a.streams?.[key], text=s?.silent===true?'已静音':s?.volume!=null?s.volume+' / '+s.max+' · 未静音':'待核验';
   rows.push(healthRow(label,text+(s?.route?' · '+routeLabel(s.route):''),s?.silent===true?'good':s?.silent===false?'warning':''));
  }
  rows.push(healthRow('通话状态',({MODE_NORMAL:'当前无通话音频',MODE_IN_CALL:'系统电话通话中',MODE_IN_COMMUNICATION:'应用通话中',MODE_RINGTONE:'来电响铃中',MODE_CALL_SCREENING:'通话筛选中'}[a.mode]||(a.mode?'其他通话音频模式':'待核验')),a.call_active?'warning':''));
  rows.push(healthRow(a.call_active?'当前通话输出':'预选通话输出',routeLabel(a.communication_route)));
  rows.push(healthRow('勿扰 / 铃声模式',q.zen_mode==null?'待核验':(q.zen_mode===2?'全部勿扰':'非全部勿扰')+' / '+({SILENT:'静音',VIBRATE:'振动',NORMAL:'响铃'}[a.ringer]||'未知')));
  const names2={dtmf_tone:'拨号按键音',sound_effects_enabled:'触摸提示音',haptic_feedback_enabled:'系统触感',vibrate_when_ringing:'来电振动',keyboard_vibration_enabled:'系统键盘振动',notification_vibration_intensity:'通知振动',ring_vibration_intensity:'铃声振动',alarm_vibration_intensity:'闹钟振动',charging_sounds_enabled:'充电提示音',charging_vibration_enabled:'充电振动'};
  for(const [key,label]of Object.entries(names2)){const v=q[key];rows.push(healthRow(label,v==null?'设备未提供或待核验':v===0?'已关闭':'开启 / 强度 '+v,v===0?'good':v!=null?'warning':''));}
  note='已单独处理通话音频；接通或切换输出可能重新改变静音，持续显示实际状态。当前软件读回不是拨号后或现场听音证明。通话进行中点击恢复仅处理基础音频；通话通道在空闲时静音，不挂断、不关闭麦克风。第三方键盘振动需另行核验。';
 }else if(healthTab==='battery'){
  rows.push(healthRow('电量',b.percent==null?'待核验':b.percent+'%'),healthRow('充电状态',charge),healthRow('电源接入',b.plugged===true?'已接电 · '+b.sources.join(' / '):b.plugged===false?'未接电':'待核验'),healthRow('充电保护',b.protection_limit?b.protection_limit+'% 上限'+(b.protection_paused?' · 已暂停充电':''):'设备未提供'),healthRow('电池温度',b.temperature==null?'待核验':b.temperature.toFixed(1)+' °C'),healthRow('电池电压',b.voltage_mv==null?'待核验':(b.voltage_mv/1000).toFixed(3)+' V'),healthRow('核验时间',timeLabel(battery.at)));
  note='接着 USB 数据线不等于电池正在充电；电源类型按手机报告显示。这里是电池温度，不是处理器温度。';
 }else if(healthTab==='verified'){
  for(const [label,at,fresh]of groups)rows.push(healthRow(label,(fresh?'有效 · ':'待核验 · ')+timeLabel(at),fresh?'good':''));
  note='时间表示实际成功读取手机系统的时间。连接断开、读取失败或数据过期会变灰，不把网页刷新当成核验。实体屏幕约 1.5 秒、设备活动约 2 秒、静音开关与电池约 10 秒采样一次。';
 }else{
  for(const [label,isActive,apps]of signals){
   const isTorch=label==='手电筒';
   const status=isActive===true?(isTorch?'正在亮灯':'正在使用')+(apps?.length?' · '+apps.join('、'):''):isActive===false?(isTorch?'已关闭 · 系统读回':'当前未检测到使用'):(isTorch&&torch.data.available===false?'系统暂不可用 · 亮灭未知':'待核验');
   rows.push(healthRow(label,status,isActive===true?'alert':isActive===false?'good':''));
  }
  rows.push(healthRow('拍照瞬时闪光','暂不支持可靠检测'),healthRow('手电筒核验时间',timeLabel(torch.at)));
  if(a.microphone?.active&&a.microphone.silenced===true)rows.push(healthRow('麦克风采样','应用正在请求；系统报告采样被静音','warning'));
  rows.push(healthRow(a.call_active?'当前通话输出':'预选通话输出',routeLabel(a.communication_route)));
  note='手电筒读取系统后置灯的状态；不等于相机拍照闪光或前置屏幕补光。相机占用、读取失败或过期时不推断灯已关闭。只读取活动状态，不保存画面或录音；约 2 秒轮询可能漏掉短暂亮灯。系统录屏不包含本控制台投屏，部分系统采音不在覆盖范围。';
 }
 $('healthContent').replaceChildren(...rows);$('healthNote').textContent=note;
}
function fitVideo(){const box=$('viewport');const w=canvas.width,h=canvas.height;if(!w||!h)return;const scale=Math.min((box.clientWidth-8)/w,(box.clientHeight-8)/h);canvas.style.width=Math.max(0,w*scale)+'px';canvas.style.height=Math.max(0,h*scale)+'px';}
new ResizeObserver(fitVideo).observe($('viewport'));
document.querySelectorAll('[data-key]').forEach(button=>button.onclick=()=>send({type:'key',code:Number(button.dataset.key)}));
$('textOpen').onclick=()=>{if(hasControl())show('textDialog');};
$('textForm').onsubmit=event=>{event.preventDefault();if(send({type:'text',text:$('phoneText').value})){$('textDialog').close();$('phoneText').value='';canvas.focus();}};
function detail(id){const task=state.tasks.find(task=>task.id===id);if(!task)return;detailId=id;$('detailTitle').textContent=task.title;const box=$('detailContent');box.replaceChildren(element('p','task-id',task.agent_name+' · '+labels[task.status]+' · '+task.id));for(const [label,value]of [['任务要求',task.instruction],['已保存进度',task.checkpoint],['当前动作',task.action],['结果',task.result]]){if(value)box.append(element('h3','',label),element('pre','',value));}if(!$('taskDetail').open)show('taskDetail');}
$('currentDetail').onclick=()=>detail(state.current);
function renderQueue(){
 const signature=JSON.stringify([state.tasks,state.agents,showHistory]);if(signature===queueSignature)return;queueSignature=signature;
 const box=$('taskList');box.replaceChildren();
 const tasks=state.tasks.filter(task=>showHistory?['done','cancelled'].includes(task.status):!['done','cancelled'].includes(task.status));
 if(showHistory)tasks.reverse();
 $('queueTab').classList.toggle('selected',!showHistory);$('queueTab').setAttribute('aria-pressed',String(!showHistory));$('historyTab').setAttribute('aria-pressed',String(showHistory));$('historyTab').classList.toggle('selected',showHistory);$('historyTab').textContent='记录 '+state.tasks.filter(t=>['done','cancelled'].includes(t.status)).length;
 if(!tasks.length)box.append(element('p','queue-empty','把需要手机完成的任务交给已接入的助手。任务、进度和结果都会留在这里。'));
 tasks.forEach((task,index)=>{
  const row=element('article','task '+task.status);row.tabIndex=0;row.setAttribute('aria-label',task.title+'，'+labels[task.status]);
  const top=element('div','task-top');top.append(element('span','task-index',String(index+1).padStart(2,'0')),element('span','task-agent',task.agent_name),element('span','task-status',labels[task.status]));row.append(top,element('div','task-title',task.title),element('div','task-action',task.action));
  const controls=element('div','task-controls');
  function button(text,action,args={}){const b=element('button','',text);b.onclick=event=>{event.stopPropagation();control(action,{id:task.id,...args});};controls.append(b);}
  if(['queued','paused'].includes(task.status)){button('↑','move',{direction:'up'});button('↓','move',{direction:'down'});button('优先执行','prioritize');}
  if(['queued','paused','running','blocked'].includes(task.status))button('结束','cancel');
  if(task.status==='blocked')button('重新排队','retry');
  if(controls.children.length)row.append(controls);row.onclick=()=>detail(task.id);row.onkeydown=event=>{if(event.key==='Enter'&&event.target===row)detail(task.id);};box.append(row);
 });
 const agents=$('agents');agents.replaceChildren();if(!state.agents.length)agents.textContent='尚无助手接入';
 for(const agent of state.agents){const pill=element('span','agent-pill '+(agent.online?'online':''));pill.append(element('i'),document.createTextNode(agent.name));pill.title=agent.online?'近期有调用':'等待助手调用';agents.append(pill);}
 if($('taskDetail').open&&detailId)detail(detailId);
}
function render(){
 if(!state)return;$('closePauses').checked=state.settings.close_pauses;const connected=state.device.connected, owner=state.owner, telemetry=state.device.telemetry||{}, current=state.tasks.find(task=>task.id===state.current), head=state.tasks.find(task=>['queued','paused','running'].includes(task.status));
 if(!connected)actionOverlay.clear();
 $('connection').textContent=connected?'USB 已连接':'USB 未连接';$('usbDot').className=connected?'online':'';
 $('ownerDot').className='owner-dot '+owner;
 const names={human:'你正在控制手机',agent:current?current.agent_name+' 正在操作':'助手控制已开启',paused:'手机任务已暂停',transition:'正在交接控制权'};
 $('ownerTitle').textContent=connected?(names[owner]||'等待连接'):'会话未开始';
 $('ownerDescription').textContent=!connected?(state.device.error||'连接 USB 手机，开始本地投屏'):owner==='human'?'助手已停止读取和输入，你可以直接操作':owner==='agent'?(current?.action||(head?'等待 '+head.agent_name+' 领取「'+head.title+'」':'等待助手添加手机任务')):owner==='transition'?'等待已发出的动作结束；后续动作已停止':'任务进度已保留，交回后重新观察当前画面';
 $('ownerTitle').title=$('ownerDescription').textContent;
 $('connect').hidden=connected;$('takeover').hidden=!connected||owner==='human';$('release').hidden=!connected||owner==='agent';$('pause').hidden=!connected||owner==='human'||owner==='paused';
 for(const button of document.querySelectorAll('[data-key],#textOpen,#rotate'))button.disabled=!hasControl();
 $('quiet').disabled=!connected;
 canvas.classList.toggle('controllable',hasControl());
 $('currentTitle').textContent=current?.title||(head?'下一项：'+head.title:'没有正在执行的手机任务');$('currentAction').textContent=current?.action||(head?head.agent_name+' · '+head.action:'可手动操作，也可以交给已接入的助手。');$('currentDetail').hidden=!current;
 $('currentTask').hidden=!current&&!head;
 const count=state.tasks.filter(t=>['queued','paused','running','blocked'].includes(t.status)).length;$('queueCount').textContent=count;$('queueCount').hidden=!count;
 $('orientationLabel').textContent=state.device.width>state.device.height?'转竖屏':'转横屏';
 renderPanel();
 renderHealth();
 if(!connected){canvas.hidden=true;$('emptyScreen').hidden=false;$('stageLabel').hidden=true;rendered=0;}
 else if(!rendered){$('stageLabel').hidden=false;$('stageLabel').textContent='正在接收实时画面…';}
 $('events').replaceChildren(...state.events.slice(-12).reverse().map(event=>{const row=element('div');row.append(element('time','',new Date(event.at).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})),document.createTextNode(event.message));return row;}));
 renderQueue();
}
async function poll(){try{state=await api('state');stateReceivedAt=performance.now();render();}catch(error){actionOverlay.clear();$('connection').textContent='本地服务已断开';$('stageLabel').hidden=false;$('stageLabel').textContent='连接中断，画面与输入已暂停';if(state){state.owner='paused';state.device.connected=false;}renderPanel();renderHealth();canvas.classList.remove('controllable');}finally{setTimeout(poll,1000);}}
function resetDecoder(){if(decoder&&decoder.state!=='closed')decoder.close();decoder=null;config=null;needKey=true;}
function configure(bytes){
 let offset=-1;for(let i=0;i<bytes.length-4;i++){if(bytes[i]===0&&bytes[i+1]===0){let n=bytes[i+2]===1?i+3:bytes[i+2]===0&&bytes[i+3]===1?i+4:-1;if(n>=0&&(bytes[n]&31)===7){offset=n;break;}}}
 if(offset<0)throw Error('视频 SPS 配置缺失');
 const codec='avc1.'+Array.from(bytes.slice(offset+1,offset+4),v=>v.toString(16).padStart(2,'0')).join('');
 resetDecoder();config=bytes;
 decoder=new VideoDecoder({output:frame=>{
  if(canvas.width!==frame.displayWidth||canvas.height!==frame.displayHeight){actionOverlay.clear();canvas.width=frame.displayWidth;canvas.height=frame.displayHeight;fitVideo();}
  context.drawImage(frame,0,0);frame.close();rendered++;frameWindow++;lastFrame=performance.now();canvas.dataset.frames=String(rendered);canvas.hidden=false;$('emptyScreen').hidden=true;$('stageLabel').hidden=true;
 },error:error=>{toast('视频解码失败：'+error.message);$('stageLabel').hidden=false;$('stageLabel').textContent='视频解码失败，请重新连接';}});
 decoder.configure({codec,optimizeForLatency:true});needKey=true;
}
function video(buffer){
 const bytes=new Uint8Array(buffer);if(bytes.length<12)return;const view=new DataView(buffer);const flags=view.getBigUint64(0);const data=bytes.slice(12);
 if(flags&(1n<<62n)){configure(data);return;}
 const key=!!(flags&(1n<<61n));if(!decoder||decoder.state!=='configured'||(needKey&&!key))return;
 if(decoder.decodeQueueSize>5){needKey=true;send({type:'refresh'});return;}
 let payload=data;if(key&&config){payload=new Uint8Array(config.length+data.length);payload.set(config);payload.set(data,config.length);}
 decoder.decode(new EncodedVideoChunk({type:key?'key':'delta',timestamp:Number(flags&((1n<<61n)-1n)),data:payload}));needKey=false;
}
function websocket(){
 socket=new WebSocket(location.origin.replace('http:','ws:')+'/stream?token='+encodeURIComponent(window.PHONE_TOKEN));socket.binaryType='arraybuffer';
 socket.onmessage=event=>{try{if(typeof event.data==='string'){const data=JSON.parse(event.data);if(data.type==='size'){pointer=null;actionOverlay.clear();packetSize={width:data.width,height:data.height};resetDecoder();}else if(data.type==='action')actionOverlay.receive(data);else if(data.type==='action_clear')actionOverlay.clear();else if(data.type==='error'){actionOverlay.clear();toast(data.message);}}else video(event.data);}catch(error){toast(error.message);}};
 socket.onclose=event=>{pointer=null;actionOverlay.clear();resetDecoder();$('stageLabel').hidden=false;$('stageLabel').textContent='视频连接断开（'+event.code+'），正在恢复观看通道…';setTimeout(websocket,2000);};
}
function coordinates(event){const rect=canvas.getBoundingClientRect();return{x:Math.round((event.clientX-rect.left)*packetSize.width/rect.width),y:Math.round((event.clientY-rect.top)*packetSize.height/rect.height),...packetSize};}
canvas.addEventListener('pointerdown',event=>{if(!hasControl())return toast('先点击「我来操作」');if(canvas.width!==packetSize.width||canvas.height!==packetSize.height)return toast('画面正在调整，请稍候');if(pointer!==null||event.button!==0)return;event.preventDefault();canvas.focus();canvas.setPointerCapture(event.pointerId);pointer=event.pointerId;send({type:'touch',action:0,...coordinates(event)});});
canvas.addEventListener('pointermove',event=>{if(pointer!==event.pointerId||!hasControl())return;send({type:'touch',action:2,...coordinates(event)});});
function pointerUp(event){if(pointer!==event.pointerId)return;pointer=null;if(hasControl())send({type:'touch',action:1,...coordinates(event)});}
canvas.addEventListener('pointerup',pointerUp);canvas.addEventListener('pointercancel',pointerUp);canvas.oncontextmenu=event=>event.preventDefault();
canvas.addEventListener('keydown',event=>{if(!hasControl())return;const codes={Escape:4,Home:3,Enter:66,Backspace:67,Tab:61,ArrowUp:19,ArrowDown:20,ArrowLeft:21,ArrowRight:22};if(codes[event.key]){event.preventDefault();send({type:'key',code:codes[event.key]});}else if(event.key.length===1&&!event.metaKey&&!event.ctrlKey&&!event.altKey&&!event.isComposing){event.preventDefault();send({type:'text',text:event.key});}});
setInterval(()=>{fps=frameWindow;frameWindow=0;$('videoStatus').textContent=rendered?'H.264 · '+packetSize.width+' × '+packetSize.height+' · '+(fps?fps+' fps':'静态画面'):'本机视频流';},1000);
setInterval(()=>{renderPanel();renderHealth();},500);
poll();if('VideoDecoder'in window)websocket();else{$('connect').disabled=true;toast('当前浏览器不支持 WebCodecs。请用最新版 Chrome 打开此本机地址。');}
