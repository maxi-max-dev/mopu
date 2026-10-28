'use strict';
const $ = id => document.getElementById(id);
const canvas = $('screen'), context = canvas.getContext('2d', {alpha:false});
const actionOverlay = new ActionOverlay($('actionLayer'),canvas,$('actionCaption'));
try{$('showActions').checked=localStorage.getItem('phone-actions-visible')!=='false';const size=localStorage.getItem('phone-actions-size');if(['44','64','88'].includes(size))$('actionSize').value=size;}catch{}
function configureActions(){actionOverlay.configure($('showActions').checked,Number($('actionSize').value));try{localStorage.setItem('phone-actions-visible',String($('showActions').checked));localStorage.setItem('phone-actions-size',$('actionSize').value);}catch{}}
$('showActions').onchange=configureActions;$('actionSize').onchange=configureActions;configureActions();
let state = null, socket = null, decoder = null, config = null, needKey = true;
let rendered = 0, lastFrame = 0, frameWindow = 0, fps = 0, packetSize = {width:0,height:0};
let taskView='queue', searchText='', selectedTasks=new Set(), visibleTasks=[], deleteIds=[], orderId=null, orderIds=[];
let toastTimer, queueSignature = '', detailId = null, controlBusy = false, pointer = null;
let panelBusy = false, previousPanel = 'unknown', stateReceivedAt = 0;
const labels = {queued:'等待执行',running:'正在执行',paused:'已暂停',done:'已完成',unverified:'结果待核验',blocked:'需要处理',cancelled:'已结束'};
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
function taskPane(open){$('taskPane').classList.toggle('collapsed',!open);$('toggleTasks').setAttribute('aria-expanded',String(open));$('toggleTasks').setAttribute('aria-label',open?'收起任务队列':'展开任务队列');$('toggleTasks').title=open?'收起任务队列':'展开任务队列';fitVideo();}
$('toggleTasks').onclick=()=>{document.body.classList.remove('focus');$('focus').setAttribute('aria-pressed','false');taskPane($('taskPane').classList.contains('collapsed'));};
$('closeTasks').onclick=$('drawerScrim').onclick=()=>{taskPane(false);$('toggleTasks').focus();};
$('railHistory').onclick=()=>{document.body.classList.remove('focus');$('focus').setAttribute('aria-pressed','false');taskPane(true);switchTaskView('history');};
$('queueTab').onclick=()=>switchTaskView('queue');
$('trashTab').onclick=()=>switchTaskView('trash');
$('historyTab').onclick=()=>{switchTaskView('history');};
$('closePauses').onchange=()=>control('close_preference',{enabled:$('closePauses').checked});
$('focus').onclick=()=>{const focused=document.body.classList.toggle('focus');$('focus').setAttribute('aria-pressed',String(focused));if(focused)taskPane(false);fitVideo();};
$('settingsOpen').onclick=()=>show('settings');
$('capabilitiesOpen').onclick=()=>{renderCapabilities();show('capabilitiesDetail');};
$('integrationOpen').onclick=()=>{renderIntegration();show('integration');};
function renderIntegration(){const online=(state?.agents||[]).filter(a=>a.online);$('integrationStatus').textContent=online.length?`近期有响应：${online.map(a=>a.name).join('、')}。这不代表正在执行。`:'尚无助手响应。请将配置放进原AI客户端，再回这里检查连接。';}
$('integrationCheck').onclick=async()=>{try{state=await api('state');renderIntegration();}catch(e){$('integrationStatus').textContent=e.message;}};
for(const [button,source]of [['copyMcp','mcpCommand'],['copyCli','cliCommand']])$(button).onclick=async()=>{try{await navigator.clipboard.writeText($(source).textContent);toast('命令已复制；请替换为此聊天的独立标识。');}catch(e){toast('复制不可用，请选中上方命令手动复制。');}};
for (const action of ['connect','takeover','release','pause','reconnect','rotate']) $(action).onclick=()=>control(action);
$('panelPower').onclick=async()=>{if(controlBusy||panelBusy)return;const on=panelState()==='off';panelBusy=true;renderPanel();try{await control('panel_power',{on});}finally{panelBusy=false;renderPanel();}};
$('disconnect').onclick=async()=>{await control('disconnect');$('settings').close();};
$('addOpen').onclick=()=>{
 const agents=[...(state?.agents||[])].sort((a,b)=>Number(b.online)-Number(a.online));
 if(!agents.length){show('integration');return;}
 $('agentSelect').replaceChildren(...agents.map(agent=>{const option=element('option','',agent.name+(agent.online?' · 在线':' · 离线，需回原聊天继续'));option.value=agent.id;return option;}));
 updateNewTaskHint();show('newTask');
};
function updateNewTaskHint(){const a=state.agents.find(x=>x.id===$('agentSelect').value);$('newTaskHint').textContent=a?.online?'只加入队列。请在原聊天授权任务，助手会自行领取。':'此助手离线。添加后仅保存到队列，请回原聊天继续；不会自动启动AI。';}
$('agentSelect').onchange=updateNewTaskHint;
$('newTaskForm').onsubmit=async event=>{event.preventDefault();try{state=await api('control',{action:'add',title:$('taskTitle').value,instruction:$('taskInstruction').value,agent:$('agentSelect').value});$('newTask').close();$('newTaskForm').reset();taskView='queue';searchText='';$('taskSearch').value='';selectedTasks.clear();taskPane(true);render();toast('任务已加入队列，等待原助手领取。');}catch(error){toast(error.message);}};
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
$('inputActivityStatus').onclick=async()=>{renderInputActivity();show('inputActivityDetail');await control('activity_seen');};
$('inputActivityEnabled').onchange=()=>control('activity_preference',{enabled:$('inputActivityEnabled').checked});
$('inputNotifyTest').onclick=()=>control('activity_notify_test');
let activityTab='apps';
$('appVisitsTab').onclick=()=>{activityTab='apps';renderInputActivity();};
$('inputCountsTab').onclick=()=>{activityTab='inputs';renderInputActivity();};
function visitDuration(seconds){
 const s=Math.max(0,Math.floor(seconds||0));
 return s<1?'不足 1 秒':s<60?s+' 秒':s<3600?Math.floor(s/60)+' 分 '+s%60+' 秒':Math.floor(s/3600)+' 小时 '+Math.floor(s%3600/60)+' 分';
}
function renderInputActivity(){
 const a=state?.activity||{}, online=state?.device.connected&&performance.now()-stateReceivedAt<=3500;
 const names={disabled:'记录已关闭',offline:'离线 · 无法监测',probing:'正在核实输入通道',unavailable:'输入通道不可用',listening:a.verified?'正在监听本体输入':'通道可读 · 待实体触摸实测'};
 const status=!a.enabled?'disabled':!online?'offline':a.status||'unavailable';
 const label=names[status]||'状态待确认',icon=$('inputActivityStatus');
 icon.className='health-icon '+(a.unread?'alert':status==='listening'&&a.verified?'good':'unknown');
 icon.title=label+' · 点击查看活动记录';icon.setAttribute('aria-label','手机活动：'+label+(a.unread?' · 有新设备输入':''));
 $('inputActivityState').textContent=label;$('inputActivityEnabled').checked=!!a.enabled;$('inputActivityEnabled').disabled=controlBusy;
 $('inputActivityHint').textContent=a.error||(!a.verified?'正式告警尚未启用。完成实体触摸与远程输入对照后才能确认来源。':'只在远程人工与助手均未操作时提醒；无法判断操作者身份。');
 const test=a.test?.status;
 $('inputDeliveryState').textContent=!a.notifications_configured?'飞书未配置':test==='sent'?'飞书测试已发送':test==='unknown'?'上次投递结果未知，不自动重发':test==='failed'?'飞书测试失败':test==='sending'?'飞书测试发送中':'飞书通道已配置';
 $('inputNotifyTest').disabled=controlBusy||!a.notifications_configured||['sent','sending','unknown'].includes(test);
 const kinds={tap:'点击',swipe:'滑动',long_press:'长按',double_tap:'双击',key:'导航按键',text:'文字输入',app:'打开应用或链接',power:'电源键',volume:'音量键'};
 const notices={pending:'合并记录中',sending:'提醒发送中',sent:'已发送飞书提醒',failed:'提醒失败',unknown:'投递结果未知',cooldown:'冷却期间 · 仅记录',held_unverified:'来源待实测 · 未提醒',unconfigured:'未配置通知',expired:'历史事件 · 未补发'};
 const showApps=activityTab==='apps';
 $('appVisitsTab').setAttribute('aria-selected',String(showApps));$('inputCountsTab').setAttribute('aria-selected',String(!showApps));
 const appState=!a.enabled?'disabled':!online?'offline':a.apps?.status||'unknown';
 const appStates={known:'前台应用读数有效 · 时长按连续取样估算',locked:'手机已锁屏 · 已停止 App 计时',asleep:'手机逻辑休眠 · 已停止 App 计时',offline:'连接中断 · 已停止计时',disabled:'记录已关闭',unknown:'前台应用暂时无法核验 · 已停止计时',interrupted:'会话结束 · 已停止计时'};
 $('appVisitsState').hidden=!showApps;$('appVisitsState').textContent=appStates[appState]||'前台应用待核验';
 const rows=showApps?(a.apps?.visits||[]).slice().reverse().map(v=>{
  const row=element('article','input-activity-row'),head=element('div','input-activity-head');
  const stamp=t=>new Date(t*1000).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});
  const ongoing=v.ongoing&&appState==='known';
  head.append(element('strong','',v.label||v.package),element('span','visit-duration','前台约 '+visitDuration(v.seconds)));row.append(head);
  row.append(element('small','',stamp(v.first)+' → '+(ongoing?'当前前台':stamp(v.last))));
  if(v.label!==v.package)row.append(element('small','visit-package',v.package));
  const inputs=Object.entries(v.inputs||{}).map(([source,counts])=>({human:'远程人工',agent:'助手',device:'设备输入'}[source]||'未知')+'：'+Object.entries(counts).map(([k,n])=>(kinds[k]||'操作')+' '+n+' 次').join('、'));
  row.append(element('p','',inputs.join(' · ')||'未记录到输入；不代表无人操作'));
  const endings={switched:'已切换 App',locked:'锁屏后停止计时',asleep:'休眠后停止计时',gap:'取样中断，未累计空白时间',offline:'断线后停止计时',unknown:'读数中断',disabled:'记录已关闭',interrupted:'会话中断'};
  if(!ongoing)row.append(element('small','',endings[v.end_reason]||'截至最后有效读数'));
  return row;
 }):(a.records||[]).slice().reverse().map(r=>{
  const row=element('article','input-activity-row'),head=element('div','input-activity-head');
  head.append(element('strong','',({human:'你的远程操作',agent:'助手操作',device:r.verified?'手机本体输入':'设备输入 · 待确认'})[r.source]||'未知来源'),element('time','',new Date(r.first*1000).toLocaleTimeString('zh-CN',{hour12:false})));
  row.append(head,element('p','',Object.entries(r.counts).map(([k,v])=>(kinds[k]||'操作')+' '+v+' 次').join(' · ')));
  const note=r.source==='device'?(r.idle?(notices[r.notification]||'已记录'):'远程操作期间 · 仅记录'):'输入已发出，不代表任务完成';
  row.append(element('small','',note));return row;
 });
 if(!rows.length)rows.push(element('p','activity-empty',showApps?'尚无 App 停留记录。开启后从新的有效读数开始。':'尚无活动记录。开启后记录新操作。'));
 $('inputActivityRecords').replaceChildren(...rows);
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
function fitVideo(){
 const box=$('viewport'), w=canvas.width, h=canvas.height;
 const gutter=innerWidth<=600?62:88;
 const scale=w&&h?Math.max(0,Math.min((box.clientWidth-gutter*2)/w,(box.clientHeight-8)/h)):0;
 const width=w*scale;
 $('phoneStage').style.setProperty('--activity-inset',box.offsetTop+'px');
 canvas.style.width=width+'px';canvas.style.height=h*scale+'px';
 $('phoneTools').style.left=`calc(50% + ${width/2+16}px)`;
 const open=!$('taskPane').classList.contains('collapsed')&&!document.body.classList.contains('focus');
 const overlay=open&&(box.clientWidth-width)/2<$('taskPane').offsetWidth+32;
 document.body.classList.toggle('task-overlay',overlay);
 $('drawerScrim').hidden=!overlay;
 box.inert=overlay;$('phoneTools').inert=overlay;
}

new ResizeObserver(fitVideo).observe($('viewport'));
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!$('drawerScrim').hidden&&!document.querySelector('dialog[open]')){event.preventDefault();event.stopPropagation();taskPane(false);$('toggleTasks').focus();}},true);
document.querySelectorAll('[data-key]').forEach(button=>button.onclick=()=>send({type:'key',code:Number(button.dataset.key)}));
$('textOpen').onclick=()=>{if(hasControl())show('textDialog');};
$('textForm').onsubmit=event=>{event.preventDefault();if(send({type:'text',text:$('phoneText').value})){$('textDialog').close();$('phoneText').value='';canvas.focus();}};
function taskLabel(task){
 if(task.deleted_at)return '已删除';
 if(task.user_held)return '你已暂停';
 if(task.status==='done')return task.receipt?.verification==='assistant_verified'?'原助手已核验':'历史完成 · 无结构化回执';
 return task.wait?.label||labels[task.status]||task.status;
}
function renderCapabilities(){
 const box=$('capabilitiesContent'),c=state?.capabilities;box.replaceChildren();
 if(!c){box.append(element('p','note','当前服务尚未提供能力目录，请更新服务后重载。'));return;}
 for(const x of c.items){
  const row=element('section','capability-row');
  row.append(element('strong','',x.label),element('span','capability-state',({provided:'设备已提供',unconfirmed:'设备尚未确认',unavailable:'设备未提供'})[x.availability]));
  row.append(element('p','',`${x.route==='direct'?'直接能力':'界面操作'} · ${x.access==='read'?'读取':'会改变手机状态'} · 需本任务控制权`));
  row.append(element('p','note',x.result_semantics),element('code','',x.name));box.append(row);
 }
 box.append(element('p','note',c.health),element('p','note',c.limits.join('；')));
}
let editingTask=null;
function editTask(task){
 editingTask={id:task.id,expected_title:task.title,expected_instruction:task.instruction};
 $('editTitle').value=task.title;$('editInstruction').value=task.instruction;$('editError').textContent='';show('editTask');
}
$('editTaskForm').onsubmit=async event=>{
 event.preventDefault();const button=event.submitter;button.disabled=true;
 try{state=await api('control',{action:'edit',...editingTask,title:$('editTitle').value,instruction:$('editInstruction').value});$('editTask').close();render();toast('要求已保存；原助手下次领取时读取。');}
 catch(error){$('editError').textContent=error.message;}finally{button.disabled=false;}
};
function switchTaskView(view){taskView=view;selectedTasks.clear();queueSignature='';renderQueue();}
$('taskSearch').oninput=()=>{searchText=$('taskSearch').value.trim().toLocaleLowerCase();selectedTasks.clear();renderQueue();};
$('clearSearch').onclick=()=>{$('taskSearch').value='';searchText='';selectedTasks.clear();renderQueue();$('taskSearch').focus();};
$('selectVisible').onchange=()=>{selectedTasks=$('selectVisible').checked?new Set(visibleTasks.map(t=>t.id)):new Set();renderSelection();document.querySelectorAll('.task-select').forEach(c=>c.checked=selectedTasks.has(c.value));};
$('clearSelection').onclick=()=>{selectedTasks.clear();queueSignature='';renderQueue();};
function renderSelection(){
 const items=state.tasks.filter(t=>selectedTasks.has(t.id));
 $('selectionCount').textContent=items.length?`已选 ${items.length} 项`:`${visibleTasks.length} 项`;
 $('selectVisible').checked=!!visibleTasks.length&&items.length===visibleTasks.length;
 $('selectVisible').indeterminate=items.length>0&&items.length<visibleTasks.length;
 $('selectVisible').disabled=!visibleTasks.length;$('clearSelection').hidden=!items.length;$('batchActions').hidden=!items.length;
 $('batchRestore').hidden=taskView!=='trash';$('batchTrash').hidden=taskView==='trash';
 $('batchHold').hidden=taskView!=='queue';$('batchResume').hidden=taskView!=='queue';
 $('batchHold').disabled=!items.some(t=>!t.user_held);$('batchResume').disabled=!items.some(t=>t.user_held);
 $('clearSearch').hidden=!searchText;
}
async function manageTasks(action,ids){
 try{state=await api('control',{action,ids});selectedTasks.clear();render();toast({trash:'已移入回收站，可随时恢复。',restore:'已恢复；未结束的任务保持暂停。',hold:'已暂停所选任务，其他等待任务不变。',resume:'已取消单独暂停；需要检查的任务仍先检查。'}[action]);return true;}
 catch(error){toast(error.message);return false;}
}
function askDelete(ids){
 deleteIds=[...ids];const tasks=state.tasks.filter(t=>deleteIds.includes(t.id));
 $('deleteSummary').textContent=`将 ${tasks.length} 个任务移入回收站？`;
 $('deleteNames').replaceChildren(...tasks.map(t=>element('li','',t.title)));
 $('deleteCaution').textContent=tasks.some(t=>t.id===state.current)?'包含正在执行的任务：会先停止并交回你控制，已发出的动作可能已经完成。':tasks.some(t=>t.pending_delivery||t.continuation?.required)?'包含待核验或待检查任务：删除不会清除这些记录，也不会解除原有续接检查。':'';
 $('deleteError').textContent='';show('deleteTasks');
}
$('confirmTrash').onclick=async()=>{
 const b=$('confirmTrash');b.disabled=true;
 try{state=await api('control',{action:'trash',ids:deleteIds});$('deleteTasks').close();if(deleteIds.includes(detailId))$('taskDetail').close();selectedTasks.clear();render();toast('已移入回收站，可随时恢复。');}
 catch(error){$('deleteError').textContent=error.message;}finally{b.disabled=false;}
};
$('batchTrash').onclick=()=>askDelete([...selectedTasks]);
$('batchRestore').onclick=()=>manageTasks('restore',[...selectedTasks]);
$('batchHold').onclick=()=>manageTasks('hold',state.tasks.filter(t=>selectedTasks.has(t.id)&&!t.user_held).map(t=>t.id));
$('batchResume').onclick=()=>manageTasks('resume',state.tasks.filter(t=>selectedTasks.has(t.id)&&t.user_held).map(t=>t.id));
function waitingTasks(){return state.tasks.filter(t=>!t.deleted_at&&!t.user_held&&['queued','paused'].includes(t.status));}
function openOrder(task){
 const waiting=waitingTasks();orderId=task.id;orderIds=waiting.map(t=>t.id);$('orderName').textContent=task.title;$('orderError').textContent='';
 $('orderPosition').replaceChildren(...waiting.map((t,i)=>{const o=element('option','',`${i+1}${i===0?' · 最前':i===waiting.length-1?' · 最后':''}${t.id===task.id?'（当前位置）':''}`);o.value=i+1;return o;}));
 $('orderPosition').value=waiting.findIndex(t=>t.id===task.id)+1;show('orderTask');
}
$('orderForm').onsubmit=async e=>{e.preventDefault();const b=e.submitter;b.disabled=true;try{state=await api('control',{action:'position',id:orderId,expected_order:orderIds,position:Number($('orderPosition').value)});$('orderTask').close();render();toast('等待顺序已保存。');}catch(error){$('orderError').textContent=error.message;}finally{b.disabled=false;}};
async function beginEdit(task){
 if(state.owner!=='human'||state.lease_active){await control('takeover');if(state.owner!=='human'||state.lease_active)return;}
 editTask(state.tasks.find(t=>t.id===task.id));
}
function deliveryText(task){
 const d=task.delivery_summary;
 if(!d||d.coverage==='unrecorded')return '发送数量未知 · 尚无逐条记录';
 return `已核验 ${d.verified} · 待确认 ${d.pending} · 未发送 ${d.not_sent}（仅记录项）`;
}
function taskActions(task,full=false){
 const controls=element('div','task-controls');
 const more=element('details','task-more'),summary=element('summary','','更多');more.append(summary);
 more.onclick=e=>e.stopPropagation();more.onkeydown=e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();more.open=false;summary.focus();}};
 function add(text,fn,disabled=false,cls='',primary=false){const b=element('button',primary?'task-main':cls,text);b.disabled=disabled;b.onclick=e=>{e.stopPropagation();fn();};(primary?controls:more).append(b);}
 const active=!['done','cancelled'].includes(task.status);
 if(task.deleted_at){add('恢复任务',()=>manageTasks('restore',[task.id]),false,'',true);if(!full)add('查看记录',()=>detail(task.id));controls.append(more);return controls;}
 if(task.status==='running')add('暂停任务',()=>manageTasks('hold',[task.id]),false,'',true);
 else if(!full)add(task.status==='unverified'||task.pending_delivery?'查看待核验项':task.user_held?'查看暂停原因':active?'查看任务':'查看结果',()=>detail(task.id),false,'',true);
 if(!full&&task.status==='running')add('查看详情',()=>detail(task.id));
 if(active){
  add(state.owner==='human'&&!state.lease_active?'编辑要求':'接管并编辑',()=>beginEdit(task));
  if(task.status!=='running')add(task.user_held?'取消单独暂停':'暂停任务',()=>manageTasks(task.user_held?'resume':'hold',[task.id]));
 }
 if(!task.user_held&&['queued','paused'].includes(task.status))add('调整顺序',()=>openOrder(task));
 if(!task.user_held&&task.reviews?.at(-1)?.kind!=='whole_task'&&task.continuation&&['blocked','paused','unverified'].includes(task.status)&&(task.long_task||task.continuation.required))add('检查并续接',()=>openContinuationReview(task),state.owner!=='human'||state.lease_active);
 if(!task.user_held&&!task.pending_delivery&&!task.long_task&&!task.continuation?.required&&(['blocked','unverified'].includes(task.status)||(task.status==='paused'&&task.wait_reason)))add('处理后重新排队',()=>control('retry',{id:task.id}));
 add('移入回收站',()=>askDelete([task.id]),false,'danger');controls.append(more);
 return controls;
}
function detail(id){
 const task=state.tasks.find(task=>task.id===id);if(!task)return;detailId=id;$('detailTitle').textContent=task.title;
 const box=$('detailContent');box.replaceChildren(element('p','task-id',task.agent_name+' · '+taskLabel(task)+' · '+task.id));
 box.append(element('p','delivery-summary',deliveryText(task)));
 const responsible=state.agents.find(a=>a.id===task.agent);
 box.append(element('p','note',`执行助手：${task.agent_name} · ${responsible?.online?'近期有响应':'离线，需回原聊天继续'}`));
 const actions=taskActions(task,true);actions.classList.add('detail-actions');box.append(actions);
 if(state.owner!=='human')box.append(element('p','note','需要编辑要求或检查续接时，请先在主界面接管手机。'));
 for(const [label,value]of [['任务要求',task.instruction],['已保存进度',task.checkpoint],['当前动作',task.action],['继续方式',task.wait?.next_action],[task.receipt?.verification==='assistant_verified'?'助手报告（已关联读回）':'助手报告（未核验）',task.result]]){
  if(value)box.append(element('h3','',label),element('pre','',value));
 }
 if(task.continuation){
  const c=task.continuation;
  const technical=element('details','task-ledger');technical.append(element('summary','','调用与授权详情'),element('p','',`累计调用 ${c.total_calls} · 当前剩余 ${c.remaining_calls}`));box.append(technical);
  if(c.pending_delivery)box.append(element('p','receipt-unresolved','未确认发送：'+c.pending_delivery+'；只允许读取核验，禁止重发。'));
  const ledger=element('details','task-ledger');ledger.append(element('summary','',task.deliveries?`逐条发送记录 · ${task.deliveries.length} 项`:'逐条发送记录 · 未记录'));box.append(ledger);
  for(const d of task.deliveries||[]){
   const entry=element('details');entry.append(element('summary','',d.key+' · '+d.outcome));
   for(const check of d.receipt?.checks||[])entry.append(element('p','',check.criterion+'：'+check.observed),element('small','',check.observed_at+' · '+check.tool));
   if(!d.receipt)entry.append(element('p','receipt-unresolved','尚无送达核验，禁止重发。'));ledger.append(entry);
  }
  const reviews=element('details','task-ledger');reviews.append(element('summary','',`授权历史 · ${(task.reviews||[]).length} 次`));technical.append(reviews);
  for(const review of task.reviews||[])reviews.append(element('pre','',`${review.scope}\n${review.state} · ${review.budget}调用 · 最多${review.max_deliveries}发送项\n来源：${review.source==='assistant_user_attestation'?'当前聊天授权（助手转述）':'控制台阶段检查'}\n${review.user_authorization||review.review_note||''}`));

 }
 if(task.milestones?.length){
  box.append(element('h3','','已验收阶段'),element('p','note','以下为发生时的读回，最终结果仍需重新核验。'));
  for(const m of task.milestones){const row=element('section','receipt-check');row.append(element('strong','',m.key));for(const c of m.checks)row.append(element('p','',c.criterion+'：'+c.observed));row.append(element('small','',new Date(m.recorded_at).toLocaleString()));box.append(row);}
 }
 const r=task.receipt;
 if(r){
  box.append(element('h3','','完成回执'),element('p','note',r.scope));
  for(const c of r.checks){const row=element('section','receipt-check');row.append(element('strong','',(c.passed?'✓ ':'待处理 · ')+c.criterion),element('p','',c.observed),element('small','',`${new Date(c.observed_at).toLocaleString()} · ${c.tool}`));box.append(row);}
  if(!r.checks.length)box.append(element('p','note','尚无与手机读回关联的验收项。'));
  for(const issue of r.unresolved)box.append(element('p','receipt-unresolved','未解决：'+issue));
 }
 if(task.management_history?.length){const h=element('details','task-ledger');h.append(element('summary','',`管理记录 · ${task.management_history.length} 次`));for(const m of task.management_history)h.append(element('p','',new Date(m.at).toLocaleString()+' · '+({trash:'移入回收站',restore:'从回收站恢复',hold:'单独暂停',resume:'取消单独暂停'}[m.action]||m.action)));box.append(h);}
 if(task.requirement_history?.length){const history=element('details','task-ledger');history.append(element('summary','',`要求修改历史 · ${task.requirement_history.length} 次`));for(const old of task.requirement_history)history.append(element('pre','',old.at+'\n'+old.title+'\n'+old.instruction));box.append(history);}
 if(task.attempts?.length){const history=element('details');history.append(element('summary','',`此前尝试 ${task.attempts.length} 次`));for(const a of task.attempts)history.append(element('pre','',a.result||'未完成'));box.append(history);}
 if(!$('taskDetail').open){show('taskDetail');$('taskDetail').scrollTop=0;}
}
function renderQueue(){
 // Keep an open action menu stable while live progress updates arrive.
 if(document.querySelector('.task-more[open]'))return;
 const signature=JSON.stringify([state.tasks,state.agents,state.owner,state.lease_active,taskView,searchText,[...selectedTasks]]);if(signature===queueSignature)return;queueSignature=signature;
 const box=$('taskList');box.replaceChildren();
 let tasks=state.tasks.filter(t=>taskView==='trash'?t.deleted_at:!t.deleted_at&&(taskView==='history'?['done','cancelled'].includes(t.status):!['done','cancelled'].includes(t.status)));
 if(searchText)tasks=tasks.filter(t=>[t.title,t.instruction,t.agent_name].some(v=>(v||'').toLocaleLowerCase().includes(searchText)));
 const group=t=>t.user_held?'你已暂停':['blocked','unverified'].includes(t.status)?'需要处理':'执行队列';
 if(taskView==='queue'){const rank={'执行队列':0,'需要处理':1,'你已暂停':2};tasks.sort((a,b)=>rank[group(a)]-rank[group(b)]);}
 else tasks.reverse();
 visibleTasks=tasks;selectedTasks=new Set([...selectedTasks].filter(id=>tasks.some(t=>t.id===id)));
 for(const [id,view,label]of [['queueTab','queue','任务'],['historyTab','history','已结束'],['trashTab','trash','回收站']]){
  const count=state.tasks.filter(t=>view==='trash'?t.deleted_at:!t.deleted_at&&(view==='history'?['done','cancelled'].includes(t.status):!['done','cancelled'].includes(t.status))).length;
  $(id).classList.toggle('selected',taskView===view);$(id).setAttribute('aria-pressed',String(taskView===view));$(id).textContent=label+' '+count;
 }
 renderSelection();
 if(!tasks.length)box.append(element('p','queue-empty',searchText?'没有匹配的任务。试试任务名、要求中的关键词或助手名。':taskView==='trash'?'回收站是空的。删除的任务会保留在这里，可以恢复。':taskView==='history'?'还没有已结束的任务。':'没有待办任务。点右上角「＋」添加手机任务。'));
 let lastGroup='';
 const order=state.tasks.filter(t=>!t.deleted_at&&!t.user_held&&['queued','paused','running'].includes(t.status));
 tasks.forEach(task=>{
  const heading=taskView==='queue'?group(task):'';
  if(heading!==lastGroup){box.append(element('h3','queue-group',heading));lastGroup=heading;}
  const row=element('article','task '+task.status);row.tabIndex=0;row.setAttribute('aria-label',task.title+'，'+taskLabel(task));
  const top=element('div','task-top'),check=element('input','task-select');check.type='checkbox';check.value=task.id;check.checked=selectedTasks.has(task.id);check.setAttribute('aria-label','选择任务：'+task.title);
  check.onclick=e=>e.stopPropagation();check.onchange=()=>{check.checked?selectedTasks.add(task.id):selectedTasks.delete(task.id);renderSelection();};
  const pos=order.findIndex(t=>t.id===task.id);top.append(check,element('span','task-index',taskView==='queue'&&pos>=0?String(pos+1).padStart(2,'0'):''),element('span','task-agent',task.agent_name),element('span','task-status',taskLabel(task)));
  row.append(top,element('div','task-title',task.title),element('div','task-action',task.deleted_at?task.wait?.next_action:['done','cancelled'].includes(task.status)?task.result||task.action:task.wait?.code==='running'?task.action:task.wait?.next_action||task.action));
  if(task.deleted_at&&(task.pending_delivery||task.continuation?.required))row.append(element('p','note','原任务待检查，仍可能阻止同一助手继续。请恢复原任务处理；删除不清除未确认发送。'));
  row.append(element('p','task-progress',deliveryText(task)));
  const updated=task.finished_at||task.checkpoint_at||task.created_at;
  if(updated)row.append(element('p','task-updated','更新于 '+new Date(updated).toLocaleString()));
  row.append(taskActions(task));row.onclick=()=>detail(task.id);row.onkeydown=e=>{if(e.key==='Enter'&&e.target===row)detail(task.id);};box.append(row);
 });
 const agents=$('agents');agents.replaceChildren();if(!state.agents.length)agents.textContent='等待原助手连接；请回原聊天继续';
 for(const agent of state.agents.filter(a=>a.online)){const pill=element('span','agent-pill online');pill.append(element('i'),document.createTextNode(agent.name));pill.title=agent.online?'近期有调用':'等待助手调用';agents.append(pill);}
 const offline=state.agents.filter(a=>!a.online).length;if(offline)agents.append(element('span','note',`${offline} 位助手离线 · 请回原聊天继续`));
 if($('taskDetail').open&&detailId)detail(detailId);
}

function render(){
 renderInputActivity();
 if(!state)return;$('runtimeVersion').textContent='v'+(state.server_version||'版本待核验');$('closePauses').checked=state.settings.close_pauses;const connected=state.device.connected, owner=state.owner, telemetry=state.device.telemetry||{}, current=state.tasks.find(task=>task.id===state.current), head=state.tasks.find(task=>!task.deleted_at&&!task.user_held&&['queued','paused','running'].includes(task.status));
 if(!connected)actionOverlay.clear();
 $('connection').textContent=connected?'USB 已连接':'USB 未连接';$('usbDot').className=connected?'online':'';
 $('ownerDot').className='owner-dot '+owner;
 const headOnline=state.agents.some(a=>a.id===(current||head)?.agent&&a.online);
 const names={human:'你正在控制手机',agent:current?(headOnline?current.agent_name+' 持有手机':'原助手未响应，等待续接'):'手机可由助手领取',paused:'手机任务已暂停',transition:'正在交接控制权'};
 $('ownerTitle').textContent=connected?(names[owner]||'等待连接'):'会话未开始';
 $('ownerDescription').textContent=!connected?(state.device.error||'连接 USB 手机，开始本地投屏'):owner==='human'?'助手已停止读取和输入，你可以直接操作':owner==='agent'?(current?.wait?.label&&current.wait.code!=='running'?current.wait.label+' · '+current.wait.next_action:current?.action||(head?'等待 '+head.agent_name+' 领取「'+head.title+'」':'等待助手添加手机任务')):owner==='transition'?'等待已发出的动作结束；后续动作已停止':'任务进度已保留，交回后重新观察当前画面';
 if(connected&&owner==='human')$('ownerDescription').textContent=head?(head.agent_name+(headOnline?'近期有响应':'离线')+' · 当前未执行'):'当前没有任务执行';
 $('ownerTitle').title=$('ownerDescription').textContent;
 $('release').textContent=head&&!headOnline?'允许助手领取':'交回助手';
 $('release').title='只交出手机控制权，不会启动AI；一次授权任务可由原聊天调用phone_start直接开始';
 $('connect').hidden=connected;$('takeover').hidden=!connected||owner==='human';$('release').hidden=!connected||owner==='agent';$('pause').hidden=!connected||owner==='human'||owner==='paused';
 for(const button of document.querySelectorAll('[data-key],#textOpen,#rotate'))button.disabled=!hasControl();
 $('quiet').disabled=!connected;
 canvas.classList.toggle('controllable',hasControl());
 const count=state.tasks.filter(t=>!t.deleted_at&&['queued','paused','running','blocked','unverified'].includes(t.status)).length;$('queueCount').textContent=count;$('queueCount').hidden=!count;
 $('orientationLabel').textContent=state.device.width>state.device.height?'转竖屏':'转横屏';
 renderPanel();
 renderHealth();
 if(!connected){canvas.hidden=true;$('emptyScreen').hidden=false;$('stageLabel').hidden=true;rendered=0;}
 else if(!rendered){$('stageLabel').hidden=false;$('stageLabel').textContent='正在接收实时画面…';}
 $('events').replaceChildren(...state.events.slice(-12).reverse().map(event=>{const row=element('div');row.append(element('time','',new Date(event.at).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})),document.createTextNode(event.message));return row;}));
 renderQueue();
 if($('capabilitiesDetail').open)renderCapabilities();
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
setInterval(()=>{renderPanel();renderHealth();if(performance.now()-stateReceivedAt>3500)renderInputActivity();},500);
poll();if('VideoDecoder'in window)websocket();else{$('connect').disabled=true;toast('当前浏览器不支持 WebCodecs。请用最新版 Chrome 打开此本机地址。');}

function openContinuationReview(task){
 const dialog=element('dialog');const form=element('form');
 form.append(element('h2','','人工阶段检查'),element('p','',task.title),element('pre','',task.checkpoint||'尚无进度记录'),element('pre','',task.result||'尚无结果记录'));
 form.append(element('p','',`累计调用 ${task.continuation.total_calls}；未确认发送：${task.pending_delivery||'无记录（仍需检查最后动作）'}`));
 function field(label,tag,type,value){const row=element('label','',label);const input=element(tag);if(type)input.type=type;input.required=true;if(value!==undefined)input.value=value;row.append(input);form.append(row);return input;}
 const note=field('检查结论（已确认进度、最后动作及不确定项）','textarea');note.maxLength=2000;
 const scope=field('仅本阶段的范围与停止条件','textarea');scope.maxLength=2000;
 const budget=field('本阶段调用上限（2–200）','input','number','200');budget.min=2;budget.max=200;
 const count=field('本阶段发送项上限（0–20，0禁止发送）','input','number','0');count.min=0;count.max=20;
 const progress=field('我已检查已有进度与去重记录','input','checkbox');
 const uncertainty=field('我已检查最后动作；未确认发送只允许先核验，不重发','input','checkbox');
 const error=element('p','receipt-unresolved');form.append(error);
 const approve=element('button','primary','批准此有限阶段');approve.type='submit';
 const cancel=element('button','','取消');cancel.type='button';cancel.onclick=()=>dialog.close();form.append(approve,cancel);
 const generation=state.generation, version=task.continuation.version;
 form.onsubmit=async event=>{event.preventDefault();approve.disabled=true;
  try{state=await api('control',{action:'review_approve',id:task.id,expected_generation:generation,review_version:version,review_note:note.value,scope:scope.value,budget:Number(budget.value),max_deliveries:Number(count.value),checked_progress:progress.checked,checked_uncertainty:uncertainty.checked});render();dialog.close();toast('有限阶段已批准；仍由你控制手机，交回后原助手先观察。');}
  catch(e){error.textContent=e.message+'。若状态变化，请关闭并重新检查。';approve.disabled=false;}
 };
 dialog.append(form);dialog.addEventListener('close',()=>dialog.remove());document.body.append(dialog);dialog.showModal();
}
