import tempfile
import time
import unittest
from unittest.mock import AsyncMock
from mopu.app import Console
from mopu.mcp import TOOLS
from test_control import CONFIG


class AuthorizedControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.c = Console(CONFIG, self.tmp.name)
        self.c.device.connected = True
        self.c.device.release_touch = AsyncMock()
        self.c.device.clear_actions = AsyncMock()
        self.c.agents['codex'] = {'name':'Codex', 'token':'token', 'seen':time.monotonic()}
        self.task = self.c.queue.add('Read SSD offers', 'Read only', 'codex', 'Codex')
        self.c.queue.owner = 'human'

    async def asyncTearDown(self): self.tmp.cleanup()

    def request(self, **overrides):
        return {'agent':'codex','agent_token':'token','action':'request_control',
                'task_id':self.task['id'],'expected_generation':self.c.queue.generation,
                'user_authorization':'明确授权这次手机查询，直接接管',
                'authorization_id':'user-message-20261025-1', **overrides}

    async def test_grant_requires_normal_lease_and_fresh_observation(self):
        self.c.device.observed_at = time.monotonic()
        result = await self.c.agent_request(self.request())
        self.assertTrue(result['granted'])
        self.assertIsNone(self.c.queue.lease)
        self.assertEqual(self.c.device.observed_at, 0)
        lease = self.c.queue.claim('codex')['lease']
        self.assertEqual(self.c.queue.check('codex', lease)['id'], self.task['id'])
        await self.c.transition_to('human', 'User takeover')
        with self.assertRaises(PermissionError): self.c.queue.check('codex', lease)
        self.assertIsNone(self.c.queue.claim('codex'))
        with self.assertRaises(PermissionError): await self.c.agent_request(self.request())
        self.assertEqual(self.c.queue.owner, 'human')
        # A genuinely NEW human instruction may request control again.
        await self.c.agent_request(self.request(authorization_id='user-message-20261025-2'))
        self.assertEqual(self.c.queue.owner, 'agent')

    async def test_missing_authorization_stale_generation_wrong_task_rejected(self):
        for args, error in [({'user_authorization':''}, ValueError),
                            ({'expected_generation':-1}, PermissionError),
                            ({'expected_generation':True}, ValueError),
                            ({'agent_token':'invalid'}, PermissionError)]:
            with self.assertRaises(error): await self.c.agent_request(self.request(**args))
        self.c.queue.add('Other', 'Read', 'claude', 'Claude')
        self.c.queue.prioritize(self.c.queue.data['tasks'][-1]['id'])
        with self.assertRaises(PermissionError): await self.c.agent_request(self.request())
        self.c.device.clear_actions.assert_not_awaited()

    async def test_blocked_original_task_resumes_without_duplicate_or_lost_receipt(self):
        task = self.c.queue.get(self.task['id'])
        task.update(status='blocked',result='Previously blocked',receipt={'verification':'unverified'},steps=3)
        await self.c.agent_request(self.request())
        self.assertEqual(len(self.c.queue.data['tasks']), 1)
        self.assertEqual(task['status'], 'queued')
        self.assertEqual(task['attempts'][0]['result'], 'Previously blocked')
        self.assertEqual(task['prior_steps'], 3)
        self.assertEqual(task['steps'], 0)

    async def test_inflight_lease_not_preempted(self):
        self.c.queue.owner = 'agent'
        lease = self.c.queue.claim('codex')['lease']
        with self.assertRaises(PermissionError): await self.c.agent_request(self.request())
        self.c.queue.check('codex', lease)

    async def test_failed_connection_consumes_grant_and_does_not_retry(self):
        self.c.device.connected = False
        self.c.device.connect = AsyncMock(side_effect=RuntimeError('offline'))
        with self.assertRaises(RuntimeError): await self.c.agent_request(self.request())
        self.assertEqual(self.c.queue.owner, 'paused')
        with self.assertRaises(PermissionError): await self.c.agent_request(self.request())
        self.c.device.connect.assert_awaited_once()

    async def test_explicit_idle_queue_switch_preserves_other_task(self):
        old = self.c.queue.get(self.task['id'])
        old.update(checkpoint='keep original',status='paused')
        selected = self.c.queue.add('Transfer','Authorized test','codex','Codex')
        with self.assertRaises(PermissionError):
            await self.c.agent_request(self.request(task_id=selected['id']))
        with self.assertRaises(PermissionError):
            await self.c.agent_request(self.request(task_id=selected['id'],expected_head='stale',queue_switch_authorization='Switch to transfer'))
        await self.c.agent_request(self.request(task_id=selected['id'],expected_head=old['id'],queue_switch_authorization='Switch to transfer'))
        self.assertEqual(self.c.queue.head()['id'],selected['id'])
        self.assertEqual(old['checkpoint'],'keep original')
        self.assertEqual(old['status'],'paused')
        self.assertIsNone(self.c.queue.lease)

    def test_tool_exposes_required_authorization_fields(self):
        tool = next(t for t in TOOLS if t['name']=='phone_request_control')
        self.assertEqual(set(tool['inputSchema']['required']),
                         {'task_id','expected_generation','authorization_id','user_authorization'})


class AuthorizedControlHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import json
        from pathlib import Path
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        from mopu.app import secure, state, agent, authorized_control
        self.tmp = tempfile.TemporaryDirectory()
        self.c = Console(CONFIG, self.tmp.name)
        self.c.device.connected = True
        self.c.device.release_touch = AsyncMock()
        self.c.device.clear_actions = AsyncMock()
        app = web.Application(middlewares=[secure]); app['console'] = self.c
        app.router.add_get('/api/state', state); app.router.add_post('/api/agent', agent)
        app.router.add_post('/api/request-control', authorized_control)
        self.c.agents['codex'] = {'name':'Codex','token':'original-token','seen':time.monotonic()}
        self.http = TestClient(TestServer(app)); await self.http.start_server()
        self.c.origin = str(self.http.make_url('/')).rstrip('/')
        Path(self.tmp.name, 'endpoint.json').write_text(json.dumps({'url':self.c.origin,'token':self.c.token}))
        self.task = self.c.queue.add('SSD', 'Read', 'codex', 'Codex')
        self.c.queue.owner = 'human'

    async def asyncTearDown(self):
        await self.http.close(); self.tmp.cleanup()

    async def cli(self):
        import asyncio, sys
        proc = await asyncio.create_subprocess_exec(sys.executable, '-m', 'mopu.cli',
            '--state', self.tmp.name, 'request-control', '--agent', 'codex',
            '--task-id', self.task['id'], '--expected-generation', str(self.c.queue.generation),
            '--authorization-id', 'direct-user-message-1', '--user-authorization', '明确授权这次查SSD',
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await proc.communicate()
        return proc.returncode, stdout.decode(), stderr.decode()

    async def test_cli_grants_through_authenticated_broker_without_device_input(self):
        import json
        code, out, err = await self.cli()
        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)['granted'])
        self.assertEqual(self.c.agents['codex']['token'], 'original-token')
        self.assertIsNone(self.c.queue.lease)
        grant = self.c.queue.get(self.task['id'])['control_authorizations'][0]
        self.assertEqual(grant['user_authorization'], '明确授权这次查SSD')

    async def test_compatibility_endpoint_still_requires_console_authentication(self):
        response = await self.http.post('/api/request-control', json={'agent':'codex'})
        self.assertEqual(response.status, 403)
        response = await self.http.post('/api/request-control',
            headers={'X-Phone-Token':self.c.token,'Origin':'https://untrusted.example'},json={'agent':'codex'})
        self.assertEqual(response.status, 403)
        self.assertEqual(self.c.queue.owner, 'human')

    async def test_cli_does_not_register_over_active_named_client(self):
        self.c.agents['codex'] = {'name':'Codex','token':'original-token','seen':time.monotonic()}
        self.c.queue.owner = 'agent'
        lease = self.c.queue.claim('codex')['lease']
        code, out, err = await self.cli()
        self.assertNotEqual(code, 0)
        self.assertEqual(self.c.agents['codex']['token'], 'original-token')
        self.c.queue.check('codex', lease)
