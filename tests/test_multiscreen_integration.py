"""Public broker integration; synthetic backend, no device or model calls."""
import asyncio
import tempfile
import time
import unittest
from unittest.mock import AsyncMock
from mopu.app import Console
from test_control import CONFIG

class Integration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.console = Console(CONFIG, self.tmp.name)
        self.console.agents['synthetic'] = {'name':'Synthetic', 'token':'fixture', 'seen':time.monotonic()}
        self.console.device.acquire = AsyncMock()
        self.console.device.quiet = AsyncMock()
        self.console.device.clear_actions = AsyncMock()
        self.console.device.release_touch = AsyncMock()
        self.lease = ''
        async def request(action, **args):
            return await self.console.agent_request(dict(action=action, agent='synthetic', agent_token='fixture', lease=self.lease, **args))
        self.request = request
        result = await request('start', title='Synthetic background', instruction='Read a synthetic page',
            user_authorization='Run the synthetic integration test', authorization_id='synthetic-background-grant',
            max_calls=20, max_deliveries=0, execution_mode='background')
        self.task_id = result['task_id']
        self.lease = (await request('wait'))['lease']

    async def asyncTearDown(self):
        await self.console.multiscreen_jobs.close()
        self.tmp.cleanup()

    async def test_start_runs_under_original_budget_and_finishes_with_evidence(self):
        class SyntheticBackend:
            def __init__(self, job, guard): self.guard = guard
            async def run(self):
                self.guard(1)
                return [{'verified':True, 'summary':'Synthetic page read'}]
            async def close(self): return {'display_absence_readback':True}
        self.console.multiscreen_jobs.backend = SyntheticBackend
        job = await self.request('multiscreen', operation='start', instruction='Read synthetic content')
        await asyncio.gather(*self.console.multiscreen_jobs.workers)
        result = await self.request('multiscreen', operation='status', job_id=job['id'])
        self.assertEqual(result['status'], 'complete')
        self.assertTrue(self.console.device.background_mode)
        self.console.device.quiet.assert_not_awaited()
        self.assertEqual(self.console.queue.get(self.task_id)['steps'], 1)
        finished = await self.request('finish', result='Synthetic result', checks=[{
            'criterion':'Synthetic task and cleanup', 'observed':'Synthetic page read',
            'observation_id':result['observation']['id'], 'passed':True}])
        self.assertEqual(finished['status'], 'done')
        self.assertIsNone(self.console.queue.lease)

    async def test_uncertain_external_action_blocks_multiscreen_creation(self):
        self.console.queue.get(self.task_id)['pending_delivery'] = {'key':'synthetic-pending'}
        with self.assertRaises(PermissionError):
            await self.request('multiscreen', operation='start', instruction='Read synthetic content')
        self.assertEqual(self.console.multiscreen_jobs.jobs, {})
