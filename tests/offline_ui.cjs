const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const root=path.resolve(__dirname,'../src/mopu/web');
 let state=JSON.parse(fs.readFileSync(process.env.MOPU_UI_FIXTURE,'utf8')),submits=[];
 const browser=await chromium.launch({headless:true,executablePath:process.env.MOPU_TEST_BROWSER});
 const page=await browser.newPage({viewport:{width:1280,height:950}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>{window.WebSocket=class{static OPEN=1;constructor(){this.readyState=0;}close(){}send(){}};});
 await page.route('**/*',async route=>{
  const u=new URL(route.request().url());
  assert.equal(u.hostname,'mopu.test','No real network allowed');
  if(u.pathname==='/api/state')return route.fulfill({json:state});
  if(u.pathname==='/api/control'){
   const body=route.request().postDataJSON();submits.push(body);assert.equal(body.action,'review_approve');
   if(submits.length===1)return route.fulfill({status:409,json:{error:'任务或证据已变化，请重新检查'}});
   assert.equal(body.budget,20);assert.equal(body.max_deliveries,3);assert.equal(body.checked_progress,true);assert.equal(body.checked_uncertainty,true);assert.equal(body.review_version,state.tasks[0].continuation.version);
   state.tasks[0].status='queued';state.tasks[0].long_task=true;
   return route.fulfill({json:state});
  }
  const f=u.pathname==='/'?'index.html':path.basename(u.pathname);
  assert.ok(['index.html','app.js','actions.js','style.css'].includes(f));
  await route.fulfill({body:fs.readFileSync(path.join(root,f)),contentType:f.endsWith('.js')?'text/javascript':f.endsWith('.css')?'text/css':'text/html'});
 });
 await page.goto('http://mopu.test/');await page.getByRole('button',{name:'展开任务队列',exact:true}).click();
 await page.locator('.task').first().click();if(await page.locator('#detailContent .task-more:not([open])').count())await page.locator('#detailContent .task-more > summary').click();await page.locator('#detailContent').getByRole('button',{name:'检查并续接',exact:true}).click();
 const modal=page.locator('dialog').filter({has:page.getByRole('heading',{name:'人工阶段检查',exact:true})});
 await modal.getByLabel('检查结论（已确认进度、最后动作及不确定项）').fill('合成验收：已检查既有记录和未确认动作，不读取真实手机。');
 await modal.getByLabel('仅本阶段的范围与停止条件').fill('仅离线合成3项目；遇不确定结果即停止新增。');
 await modal.getByLabel('本阶段调用上限（2–200）').fill('20');
 await modal.getByLabel('本阶段发送项上限（0–20，0禁止发送）').fill('3');
 await modal.getByLabel('我已检查已有进度与去重记录').check();
 await modal.getByLabel('我已检查最后动作；未确认发送只允许先核验，不重发').check();
 await modal.getByRole('button',{name:'批准此有限阶段'}).click();
 await modal.getByText(/任务或证据已变化/).waitFor();assert.equal(submits.length,1);
 await page.screenshot({path:path.join(process.env.MOPU_UI_OUTPUT,'人工阶段检查-离线合成.png'),fullPage:true});
 await modal.getByRole('button',{name:'取消',exact:true}).click();
 if(await page.locator('#detailContent .task-more:not([open])').count())await page.locator('#detailContent .task-more > summary').click();await page.locator('#detailContent').getByRole('button',{name:'检查并续接',exact:true}).click();
 const m=page.locator('dialog').filter({has:page.getByRole('heading',{name:'人工阶段检查',exact:true})});
 await m.getByLabel('检查结论（已确认进度、最后动作及不确定项）').fill('重新检查通过');await m.getByLabel('仅本阶段的范围与停止条件').fill('离线合成3项');
 await m.getByLabel('本阶段调用上限（2–200）').fill('20');await m.getByLabel('本阶段发送项上限（0–20，0禁止发送）').fill('3');
 await m.getByLabel('我已检查已有进度与去重记录').check();await m.getByLabel('我已检查最后动作；未确认发送只允许先核验，不重发').check();
 await m.getByRole('button',{name:'批准此有限阶段'}).click();await page.getByText('有限阶段已批准；仍由你控制手机，交回后原助手先观察。',{exact:true}).waitFor();
 assert.equal(state.owner,'human');assert.equal(submits.length,2);assert.deepEqual(errors,[]);
 fs.writeFileSync(path.join(process.env.MOPU_UI_OUTPUT,'ui-offline-result.json'),JSON.stringify({passed:true,synthetic:true,network:'all requests intercepted; no device or service',checks:['stale review error visible','required checks and bounded form','approval leaves human ownership','no JS errors'],submits:submits.length},null,2));
 await browser.close();console.log('offline browser checks passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
