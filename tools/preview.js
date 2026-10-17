/* UI-only fixture injected exclusively by tools/preview.py, never production. */
const demoPicture=new Image();demoPicture.src='/demo.svg';
function drawDemo(){
 if(!state?.device.connected)return;
 const w=state.device.width,h=state.device.height;
 canvas.width=w;canvas.height=h;packetSize={width:w,height:h};
 context.fillStyle='#f3f2ed';context.fillRect(0,0,w,h);
 if(w<h)context.drawImage(demoPicture,0,0,w,h);
 else{context.save();context.translate(w/2,h/2);context.rotate(-Math.PI/2);context.drawImage(demoPicture,-h/2,-w/2,h,w);context.restore();}
 canvas.hidden=false;$('emptyScreen').hidden=true;$('stageLabel').hidden=true;rendered=1;fitVideo();
}
demoPicture.onload=drawDemo;
setInterval(()=>{drawDemo();$('connection').textContent='示例预览 · 未连接设备';$('videoStatus').textContent='DEMO · 合成画面';},150);
taskPane(true);
socket={readyState:WebSocket.OPEN,send:()=>toast('这是界面示例，不会向手机发送输入。')};
