const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function setup(){
 let clock=1000;
 const arcs=[],ctx=new Proxy({arc:(...a)=>arcs.push(a)},{get:(o,k)=>o[k]??(()=>{})});
 const sandbox={window:{},Date,performance:{now:()=>clock},matchMedia:()=>({matches:false}),devicePixelRatio:2,requestAnimationFrame:()=>1,cancelAnimationFrame:()=>{}};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../src/mopu/web/actions.js'),'utf8'),sandbox);
 const layer={width:0,height:0,getContext:()=>ctx,getBoundingClientRect:()=>({left:0,top:0,width:1000,height:900})};
 const screen={hidden:false,width:720,height:1600,getBoundingClientRect:()=>({left:100,top:10,width:360,height:800})};
 const caption={hidden:true,style:{}};const overlay=new sandbox.window.ActionOverlay(layer,screen,caption);
 const event={id:'one',at:Date.now(),kind:'tap',label:'点击',phase:'sent',source:'agent',actor:'Codex',points:[[.5,.5]],video:[720,1600]};
 return {overlay,event,arcs,screen,caption,setTime:t=>clock=t};
}
test('normalized phone point follows scaled and letterboxed video',()=>{const {overlay,event,arcs}=setup();overlay.receive(event);overlay.draw(1200);assert.equal(arcs[0][0],280);assert.equal(arcs[0][1],410);});
test('rotated geometry invalidates old point',()=>{const {overlay,event,arcs,screen}=setup();overlay.receive(event);screen.width=1600;screen.height=720;overlay.draw(1200);assert.equal(arcs.length,0);});
test('stale network input is not replayed',()=>{const {overlay,event,caption}=setup();overlay.receive({...event,at:Date.now()-3000});assert.equal(overlay.traces.size,0);assert.equal(caption.hidden,true);});
test('completion does not restart or resurrect gesture animation',()=>{const {overlay,event}=setup();overlay.receive(event);const first=overlay.traces.get('one');overlay.receive({...event,phase:'returned'});assert.equal(overlay.traces.get('one').began,first.began);assert.equal(overlay.traces.get('one').until,first.until);overlay.clear();overlay.receive({...event,phase:'returned'});assert.equal(overlay.traces.size,0);});
test('hide and takeover clear all traces and text',()=>{const {overlay,event,caption}=setup();overlay.receive(event);overlay.configure(false,88);overlay.receive(event);assert.equal(overlay.traces.size,0);assert.equal(caption.hidden,true);});
test('unknown result is labelled without claiming success',()=>{const {overlay,event,caption}=setup();overlay.receive(event);overlay.receive({...event,phase:'uncertain'});assert.match(caption.textContent,/结果未确认/);assert.match(caption.className,/uncertain/);});
test('input labels also fade and traces stay bounded',()=>{const {overlay,event,caption}=setup();for(let i=0;i<10;i++)overlay.receive({...event,id:String(i)});assert.equal(overlay.traces.size,2);overlay.draw(10000);assert.equal(overlay.traces.size,0);assert.equal(caption.hidden,true);});
test('manual feedback clears quickly while agent feedback is briefly readable',()=>{
 const a=setup(),b=setup();a.overlay.receive({...a.event,source:'human'});b.overlay.receive(b.event);
 a.overlay.draw(1500);b.overlay.draw(1500);assert.equal(a.overlay.traces.size,0);assert.equal(b.overlay.traces.size,1);
 a.overlay.draw(1700);b.overlay.draw(1700);assert.equal(a.caption.hidden,true);assert.equal(b.caption.hidden,false);
 b.overlay.draw(2300);assert.equal(b.overlay.traces.size,0);assert.equal(b.caption.hidden,true);
});
test('new gesture fades the old one without brightening it or accumulating a click history',()=>{
 const {overlay,event,setTime,caption}=setup();overlay.receive({...event,source:'human'});
 setTime(1400);const previous=overlay.traces.get('one'),alpha=overlay.opacity(previous,1400);
 overlay.receive({...event,id:'two',source:'human'});assert.equal(overlay.opacity(previous,1400),alpha);
 overlay.draw(1460);assert.ok(overlay.opacity(previous,1460)<alpha);assert.equal(overlay.traces.size,1);
 for(let i=0;i<20;i++){setTime(1500+i*30);overlay.receive({...event,id:'fast'+i,label:'点击'+i});assert.ok(overlay.traces.size<=2);}
 assert.match(caption.textContent,/点击19/);overlay.draw(2200);assert.equal(overlay.traces.size,1);
 assert.equal([...overlay.traces.keys()][0],'fast19');
});
test('next gesture retires a held pointer and old completion cannot replace the latest label',()=>{
 const {overlay,event,setTime,caption}=setup();overlay.receive({...event,phase:'touch',source:'human'});
 setTime(1050);overlay.receive({...event,id:'next',label:'向上滑动'});
 const until=overlay.traces.get('one').until;
 setTime(1100);overlay.receive({...event,phase:'returned',label:'旧动作'});
 assert.equal(overlay.traces.get('one').until,until);assert.match(caption.textContent,/向上滑动/);
 overlay.draw(1200);assert.equal(overlay.traces.has('one'),false);
});
test('completion does not extend the caption or revive an expired gesture before the next frame',()=>{
 const {overlay,event,setTime,caption}=setup();overlay.receive(event);const until=overlay.latest.until;
 setTime(1400);overlay.receive({...event,phase:'returned'});assert.equal(overlay.latest.until,until);
 setTime(2000);overlay.receive({...event,phase:'uncertain'});assert.equal(overlay.traces.size,0);assert.doesNotMatch(caption.textContent,/结果未确认/);
});
