import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from mopu.app import Console, secure, agent
from mopu.client import call_tool
from test_control import CONFIG


class ShellClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.c=Console(CONFIG,self.tmp.name)
        self.c.device.connected=True;self.c.device.clear_actions=AsyncMock();self.c.device.release_touch=AsyncMock()
        self.c.queue.owner='human'
        app=web.Application(middlewares=[secure]);app['console']=self.c;app.router.add_post('/api/agent',agent)
        self.http=TestClient(TestServer(app));await self.http.start_server()
        self.c.origin=str(self.http.make_url('/')).rstrip('/')
        Path(self.tmp.name,'endpoint.json').write_text(json.dumps({'url':self.c.origin,'token':self.c.token}))
    async def asyncTearDown(self):await self.http.close();self.tmp.cleanup()
    async def cli(self,tool,args=None):
        # Each invocation is a fresh process, as used by remote shell AI clients.
        import sys
        process=await asyncio.create_subprocess_exec(sys.executable,'-m','mopu.cli','--state',self.tmp.name,'call','--agent','brand-new-ai',tool,'--json',json.dumps(args or {}),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        out,err=await process.communicate()
        self.assertEqual(process.returncode,0,err.decode());return json.loads(out)
    async def test_fresh_cli_processes_keep_lease_and_identity_without_bridge(self):
        tools=await self.cli('list');self.assertIn('phone_start',[t['name'] for t in tools['tools']])
        start=await self.cli('phone_start',{'title':'No-send client test','instruction':'Synthetic only','user_authorization':'Test without sending','authorization_id':'cli-synthetic-001','max_calls':1000,'max_deliveries':0})
        await self.cli('phone_wait');token=self.c.agents['brand-new-ai']['token'];lease=self.c.queue.lease['token']
        heartbeat=await self.cli('phone_heartbeat');self.assertTrue(heartbeat['renewed'])
        self.assertEqual(self.c.agents['brand-new-ai']['token'],token);self.assertEqual(self.c.queue.lease['token'],lease)
        session=await self.cli('phone_session');self.assertEqual(session['tasks'][0]['id'],start['task_id'])
        self.assertEqual(self.c.queue.get(start['task_id'])['steps'],0)
        for p in Path(self.tmp.name,'clients').glob('*.json'):self.assertEqual(p.stat().st_mode&0o777,0o600)
        await self.cli('phone_finish',{'result':'No external sends; synthetic test finished'})
        self.assertEqual(self.c.queue.owner,'human');self.assertIsNone(self.c.queue.lease)
    async def test_standard_stdio_mcp_start_wait_heartbeat_finish(self):
        import sys
        process=await asyncio.create_subprocess_exec(sys.executable,'-m','mopu.cli','--state',self.tmp.name,'mcp','--agent','fresh-mcp-ai',stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        async def rpc(ident,method,params=None):
            process.stdin.write((json.dumps({'jsonrpc':'2.0','id':ident,'method':method,'params':params or {}})+'\n').encode());await process.stdin.drain()
            return json.loads(await asyncio.wait_for(process.stdout.readline(),5))['result']
        try:
            init=await rpc(1,'initialize');self.assertEqual(init['serverInfo']['name'],'mopu')
            listing=await rpc(2,'tools/list');self.assertIn('phone_start',[x['name'] for x in listing['tools']])
            for i,(name,args) in enumerate([
                ('phone_start',{'title':'MCP no-send','instruction':'Synthetic only','user_authorization':'Synthetic test only','authorization_id':'mcp-synthetic-001','max_calls':1000,'max_deliveries':0}),
                ('phone_wait',{}),('phone_heartbeat',{}),('phone_finish',{'result':'Synthetic only'})],3):
                result=await rpc(i,'tools/call',{'name':name,'arguments':args})
                self.assertFalse(result.get('isError'),result)
            self.assertEqual(self.c.queue.owner,'human')
            self.assertEqual(len(self.c.queue.data['tasks']),1)
        finally:
            process.stdin.close();await asyncio.wait_for(process.wait(),5)

    async def test_serialization_rejects_concurrent_calls_without_dispatch(self):
        import fcntl, hashlib
        folder=Path(self.tmp.name,'clients');folder.mkdir()
        path=folder/(hashlib.sha256(b'locked').hexdigest()+'.lock')
        with path.open('w') as f:
            fcntl.flock(f,fcntl.LOCK_EX)
            with self.assertRaisesRegex(RuntimeError,'in-flight'):
                await call_tool(self.tmp.name,'locked','Locked','phone_session',{})
        self.assertNotIn('locked',self.c.agents)

if __name__=='__main__':unittest.main()
