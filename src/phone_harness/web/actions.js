'use strict';
// Display-only feedback, separate from decoded phone frames and phone input.
class ActionOverlay {
 constructor(layer, screen, caption) {
  this.layer=layer; this.screen=screen; this.caption=caption; this.ctx=layer.getContext('2d');
  this.traces=new Map(); this.frame=0; this.latest=null; this.enabled=true; this.size=64;
  this.reduced=matchMedia('(prefers-reduced-motion: reduce)');
 }
 configure(enabled,size) {this.enabled=enabled;this.size=size;if(!enabled)this.clear();}
 clear() {this.traces.clear();this.latest=null;this.caption.hidden=true;cancelAnimationFrame(this.frame);this.frame=0;this.ctx.clearRect(0,0,this.layer.width,this.layer.height);}
 opacity(cue,t) {
  if(cue.retiredAt!==undefined)return cue.retiredAlpha*Math.max(0,(cue.until-t)/(cue.until-cue.retiredAt));
  return cue.phase==='touch'?1:Math.max(0,Math.min(1,(cue.until-t)/cue.fade));
 }
 receive(event) {
  if(!this.enabled||!['sent','touch','returned','uncertain'].includes(event.phase)||Date.now()-event.at>2500)return;
  const t=performance.now();
  for(const [id,cue]of this.traces)if(t>=cue.until)this.traces.delete(id);
  const existing=this.traces.get(event.id), completion=['returned','uncertain'].includes(event.phase);
  // A completion updates a visible action; it never replays an expired gesture.
  if((completion&&!existing)||existing?.retiredAt!==undefined)return;
  if(!existing){
   // Keep only the preceding gesture, fading from its current opacity.
   for(const [id,old]of this.traces){
    if(old.retiredAt!==undefined){this.traces.delete(id);continue;}
    old.retiredAlpha=this.opacity(old,t);old.retiredAt=t;old.until=Math.min(old.until,t+120);
   }
  }
  const human=event.source==='human',live=event.phase==='touch';
  const cue={...event,began:existing?.began??t,until:t+(live?10000:human?450:900),fade:human?320:550};
  if(completion)cue.until=existing.until;
  this.traces.set(event.id,cue);
  if(!existing||this.latest?.id===event.id){
   const until=completion?this.latest.until:t+(live?10000:human?650:1200);
   this.latest={...cue,until,fade:human?180:250};
   const status={touch:'操作中',sent:'已发送',returned:'待画面核验',uncertain:'结果未确认'}[event.phase];
   this.caption.textContent=(event.actor||'助手')+' · '+event.label+'  /  '+status;
   this.caption.className='action-caption '+(event.source==='human'?'human':'agent')+(event.phase==='uncertain'?' uncertain':'');
   this.caption.hidden=false;this.caption.style.opacity=String(this.opacity(this.latest,t));
  }
  if(!this.frame)this.frame=requestAnimationFrame(now=>this.draw(now));
 }
 draw(t) {
  this.frame=0;
  const outer=this.layer.getBoundingClientRect(),screen=this.screen.getBoundingClientRect(),ratio=devicePixelRatio||1;
  const w=Math.round(outer.width*ratio),h=Math.round(outer.height*ratio);
  if(this.layer.width!==w||this.layer.height!==h){this.layer.width=w;this.layer.height=h;}
  const ctx=this.ctx;ctx.setTransform(ratio,0,0,ratio,0,0);ctx.clearRect(0,0,outer.width,outer.height);
  for(const [id,cue]of this.traces){
   if(t>cue.until){this.traces.delete(id);continue;}
   if(this.screen.hidden||cue.video?.[0]!==this.screen.width||cue.video?.[1]!==this.screen.height)continue;
   const points=(cue.points||[]).filter(p=>p.length===2&&p.every(n=>Number.isFinite(n)&&n>=0&&n<=1)).map(([x,y])=>[screen.left-outer.left+x*screen.width,screen.top-outer.top+y*screen.height]);
   if(!points.length)continue;
   const age=t-cue.began, alpha=this.opacity(cue,t);
   const color=cue.phase==='uncertain'?'#ffb2ab':cue.source==='human'?'#f2c07c':'#b3bdff';
   ctx.save();ctx.globalAlpha=Math.max(0,alpha);ctx.lineCap='round';ctx.lineJoin='round';
   let point=points.at(-1);
   if(cue.kind==='swipe'&&points.length>1){
    for(const [stroke,width]of [['#0d1120dd',8],[color,4]]){
     ctx.beginPath();points.forEach(([x,y],i)=>i?ctx.lineTo(x,y):ctx.moveTo(x,y));ctx.strokeStyle=stroke;ctx.lineWidth=width;ctx.stroke();
    }
    const end=points.at(-1),prev=points.at(-2),a=Math.atan2(end[1]-prev[1],end[0]-prev[0]);
    ctx.beginPath();ctx.moveTo(end[0]-13*Math.cos(a-.5),end[1]-13*Math.sin(a-.5));ctx.lineTo(...end);ctx.lineTo(end[0]-13*Math.cos(a+.5),end[1]-13*Math.sin(a+.5));ctx.strokeStyle=color;ctx.lineWidth=4;ctx.stroke();
    if(cue.source==='agent'&&!this.reduced.matches){const f=Math.min(age/650,1);point=[points[0][0]+(end[0]-points[0][0])*f,points[0][1]+(end[1]-points[0][1])*f];}
   }
   const radius=this.size/2, pulse=this.reduced.matches?0:Math.min(age/500,1)*12;
   ctx.beginPath();ctx.arc(...point,radius,0,Math.PI*2);ctx.fillStyle=color+'12';ctx.fill();
   ctx.strokeStyle='#0d1120cc';ctx.lineWidth=6;ctx.stroke();ctx.strokeStyle='#ffffff';ctx.lineWidth=2;ctx.stroke();
   ctx.beginPath();ctx.arc(...point,radius+pulse,0,Math.PI*2);ctx.strokeStyle=color;ctx.lineWidth=2.5;ctx.stroke();
   if(cue.kind==='double'){ctx.beginPath();ctx.arc(...point,radius+8+pulse,0,Math.PI*2);ctx.lineWidth=1.5;ctx.stroke();}
   ctx.beginPath();ctx.arc(...point,7,0,Math.PI*2);ctx.fillStyle=color;ctx.fill();ctx.strokeStyle='#101626';ctx.lineWidth=2;ctx.stroke();
   ctx.restore();
  }
  if(this.latest&&t>this.latest.until){this.latest=null;this.caption.hidden=true;}
  if(this.latest)this.caption.style.opacity=String(this.opacity(this.latest,t));
  if(this.traces.size||this.latest)this.frame=requestAnimationFrame(now=>this.draw(now));
 }
}
window.ActionOverlay=ActionOverlay;
