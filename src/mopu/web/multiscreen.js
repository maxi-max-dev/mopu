'use strict';
// This view never grants a task, resumes a revoked lease or starts a model.
(() => {
 const open=document.getElementById('multiscreenOpen'),dialog=document.getElementById('multiscreenView'),grid=document.getElementById('multiscreenGrid'),note=document.getElementById('multiscreenNote');
 let busy=false,epoch=0,cards=new Map(),currentJob=null;
 const make=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;};
 async function call(job,op,display,body){
  const response=await fetch(`/api/multiscreen/${encodeURIComponent(job)}/${op}/${display}`,{method:body?'POST':'GET',headers:{'X-Phone-Token':window.PHONE_TOKEN,'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});
  if(!response.ok){const x=await response.json();throw Error(x.error||'请求失败');}return response;
 }
 async function act(op,display){if(!currentJob)return;try{await call(currentJob,op,display,{});await update();}catch(e){note.textContent=e.message;}}
 function card(id){
  const box=make('article'),title=make('h3'),meta=make('p'),img=make('img'),stamp=make('small'),buttons=make('div'),take=make('button','接管'),back=make('button','交还');
  box.className='multiscreen-card';img.alt=id===0?'主屏实时画面':'副屏实时画面';buttons.className='multiscreen-buttons';buttons.append(take,back);box.append(title,meta,img,stamp,buttons);grid.append(box);
  take.onclick=()=>act('takeover',id===0?-1:id);back.onclick=()=>act('return',id===0?-1:id);
  const c={box,title,meta,img,stamp,take,back,url:null,paused:false};
  img.onclick=async e=>{if(id===0||!c.paused)return;const rect=img.getBoundingClientRect();try{await call(currentJob,'tap',id,{x:Math.floor((e.clientX-rect.left)*img.naturalWidth/rect.width),y:Math.floor((e.clientY-rect.top)*img.naturalHeight/rect.height)});}catch(error){note.textContent=error.message;}};
  cards.set(id,c);return c;
 }
 async function update(){
  if(!dialog.open||busy)return;busy=true;const version=epoch;
  try{
   const response=await fetch('/api/state',{headers:{'X-Phone-Token':window.PHONE_TOKEN}}),state=await response.json();
   const job=(state.multiscreen_jobs||[]).find(j=>!j.finished_at&&['starting','running'].includes(j.status));
   if(!job){currentJob=null;note.textContent='当前没有运行中的副屏任务。由电脑端助手通过 MCP 启动后，画面会出现在这里。';for(const c of cards.values()){if(c.url)URL.revokeObjectURL(c.url);c.box.remove();}cards.clear();return;}
   currentJob=job.id;const inventory=await (await call(job.id,'list',0)).json();
   note.textContent='主屏始终由你使用；主屏接管会暂停全部副屏。副屏接管后可点画面操作；交还后助手重新观察。关闭此视图不停止任务。';
   const rows=[{display:0,app:'主屏',step:'只读预览 · 不唤醒、不解锁',status:'你在使用'},...inventory.screens];
   for(const [id,c] of cards)if(!rows.some(r=>r.display===id)){if(c.url)URL.revokeObjectURL(c.url);c.box.remove();cards.delete(id);}
   await Promise.all(rows.map(async row=>{
    const c=cards.get(row.display)||card(row.display);c.paused=row.paused;c.title.textContent=`${row.display===0?'主屏':'副屏'} ${row.display} · ${row.app||'准备中'}`;
    c.meta.textContent=`${row.step||'等待启动'} · ${row.paused?'已接管':row.status||'运行中'}`;c.back.disabled=!!row.phone_paused;
    c.back.title=row.phone_paused?'手机端接管须在手机端交还':'';
    try{const r=await call(job.id,'frame',row.display);const blob=await r.blob();if(version!==epoch)return;const url=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(blob);});if(version!==epoch)return;c.url=null;c.img.src=url;
     const age=Date.now()/1000-Number(r.headers.get('X-Frame-Time'));c.stamp.textContent=age>5?`最近帧 ${Math.round(age)} 秒前 · 静态画面可能不更新`:'实时画面 · 约每秒刷新';
    }catch(e){c.stamp.textContent=e.message;}
   }));
  }catch(e){note.textContent=e.message;}finally{busy=false;}
 }
 dialog.querySelector('[data-close]').onclick=()=>dialog.close();
 open.onclick=()=>{dialog.showModal();update();};
 document.getElementById('multiscreenAll').onclick=()=>act('takeover',-1);
 dialog.addEventListener('close',()=>{epoch++;for(const c of cards.values())if(c.url)URL.revokeObjectURL(c.url);grid.replaceChildren();cards.clear();});
 setInterval(update,1000);
})();
