import asyncio
import hashlib
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock
from mopu.app import Console
from mopu.transfers import Transfers, safe_local, CHUNK, NAMES
from test_control import CONFIG


class LocalTransport(Transfers):
    """Exercise the actual shell protocol against an isolated fake phone tree."""
    async def run(self, command, guard, data=None, timeout=48):
        guard()
        command = command.replace('/storage/emulated/0/Download', str(self.phone))
        # Linux stat spelling is not available on macOS.
        command = command.replace('stat -c %s', 'stat -f %z').replace('stat -c %i', 'stat -f %i').replace('sha256sum ', 'shasum -a 256 ')
        proc = await asyncio.create_subprocess_exec('/bin/sh','-c',command,stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
        out,err = await proc.communicate(data)
        guard()
        if proc.returncode: raise RuntimeError(err.decode())
        return out


class TransferTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name).resolve()
        self.source=self.root/'source';self.source.mkdir()
        self.dest=self.root/'destination';self.dest.mkdir()
        self.phone=self.root/'phone';self.phone.mkdir()
        self.c=Console({**CONFIG,'transfer_local_roots':[str(self.root)]}, self.root/'state')
        self.c.device.connected=True;self.c.device.lockfile=object()
        self.c.agents['test']={'name':'Test','token':'token','seen':time.monotonic()}
        self.task=self.c.queue.add('Files','Round trip test','test','Test')
        self.c.queue.owner='agent';self.lease=self.c.queue.claim('test')['lease']
        self.c.transfers=LocalTransport(self.root/'state',self.c.device);self.c.transfers.phone=self.phone
        await self.call('scope',source_root=str(self.source),destination_root=str(self.dest),user_authorization='test round trip')

    async def asyncTearDown(self):
        await self.c.transfer_jobs.close()
        self.tmp.cleanup()

    async def call(self, name, **args):
        import json
        r=await self.c.agent_request({'agent':'test','agent_token':'token','lease':self.lease,
            'action':'call','name':'mobile_transfer_'+name,'arguments':args})
        return json.loads(r['content'][0]['text'])

    async def upload(self, data=b'round trip'):
        (self.source/'sample').write_bytes(data)
        return await self.call('push',source='sample',sha256=hashlib.sha256(data).hexdigest())

    async def test_roundtrip_resume_manifest_and_scoped_cleanup(self):
        data=b'x'*(CHUNK+31)
        (self.phone/'original.txt').write_text('preserve')
        f=await self.upload(data);self.assertEqual(f['uploaded'], CHUNK)
        # Reconstruct transfer service to prove persisted offsets are sufficient.
        self.c.transfers=LocalTransport(self.root/'state',self.c.device);self.c.transfers.phone=self.phone
        f=await self.call('push',source='sample',sha256=f['sha256']);self.assertEqual(f['status'],'uploaded')
        self.assertTrue((await self.call('verify',transfer_id=f['id']))['matches'])
        p=await self.call('pull',transfer_id=f['id'],destination='result');self.assertEqual(p['pulled'],CHUNK)
        p=await self.call('pull',transfer_id=f['id'],destination='result');self.assertEqual(p['status'],'downloaded')
        self.assertEqual((self.dest/'result').read_bytes(),data)
        await self.call('cleanup',transfer_id=f['id'],recovery_evidence='test file restored and SHA256 verified')
        self.assertEqual(list(self.phone.iterdir()),[self.phone/'original.txt'])
        self.assertEqual((self.source/'sample').read_bytes(),data)

    async def test_background_job_continues_multiple_chunks_and_keeps_lease_expiry(self):
        data=b'background'*(CHUNK//10+10)
        (self.source/'sample').write_bytes(data)
        job=await self.call('start',operation='push',source='sample',sha256=hashlib.sha256(data).hexdigest())
        expiry=self.c.queue.lease['expires']
        await asyncio.gather(*self.c.transfer_jobs.workers)
        self.assertEqual(self.c.queue.lease['expires'],expiry)
        progress=await self.call('job',job_id=job['id'])
        self.assertEqual(progress['status'],'complete')
        self.assertEqual(progress['bytes_done'],len(data))
        verification=await self.call('start',operation='verify',transfer_id=progress['transfer_id'])
        await asyncio.gather(*self.c.transfer_jobs.workers)
        verified=await self.call('job',job_id=verification['id'])
        self.assertTrue(verified['result']['matches'])
        self.assertIn('id',verified['observation'])

    async def test_background_job_stops_on_takeover(self):
        (self.source/'sample').write_bytes(b'x')
        job=await self.call('start',operation='push',source='sample',sha256=hashlib.sha256(b'x').hexdigest())
        self.c.queue.invalidate('takeover');self.c.queue.owner='human'
        await asyncio.gather(*self.c.transfer_jobs.workers)
        self.assertEqual(self.c.transfer_jobs.jobs[job['id']]['status'],'interrupted')
        self.assertEqual(list(self.phone.iterdir()),[])

    async def test_paths_hash_and_foreign_ids(self):
        f=await self.upload()
        for args in ({'source':'../escape','sha256':f['sha256']},{'source':'/etc/passwd','sha256':f['sha256']}):
            with self.assertRaises(ValueError): await self.call('push',**args)
        (self.source/'link').symlink_to('/etc/passwd')
        with self.assertRaises(PermissionError): await self.call('push',source='link',sha256=f['sha256'])
        with self.assertRaises(PermissionError): await self.call('cleanup',transfer_id='foreign',recovery_evidence='test')
        await self.call('verify',transfer_id=f['id'])
        (self.dest/'existing').write_text('preserve')
        with self.assertRaises(FileExistsError): await self.call('pull',transfer_id=f['id'],destination='existing')
        with self.assertRaises(ValueError): await self.call('cleanup',transfer_id=f['id'],recovery_evidence='')
        self.assertEqual((self.dest/'existing').read_text(),'preserve')

    async def test_corruption_and_lease_loss(self):
        f=await self.upload()
        remote=self.phone/Path(f['directory']).name/'payload';remote.write_bytes(b'bad')
        self.assertFalse((await self.call('verify',transfer_id=f['id']))['matches'])
        with self.assertRaises(PermissionError): await self.call('pull',transfer_id=f['id'],destination='result')
        self.c.queue.invalidate('Human takeover');self.c.queue.owner='human'
        with self.assertRaises(PermissionError): await self.call('space')
        self.assertTrue(remote.exists())

    async def test_remote_link_and_unknown_contents_not_deleted(self):
        f=await self.upload();directory=self.phone/Path(f['directory']).name
        extra=directory/'original';extra.write_text('preserve')
        with self.assertRaises((RuntimeError,PermissionError)): await self.call('cleanup',transfer_id=f['id'],recovery_evidence='abandoned test')
        self.assertEqual(extra.read_text(),'preserve')
        (directory/'payload').symlink_to(extra)
        with self.assertRaises((RuntimeError,PermissionError)): await self.call('cleanup',transfer_id=f['id'],recovery_evidence='abandoned test')
        self.assertEqual(extra.read_text(),'preserve')

    async def test_wrong_scope_rejected_and_empty_file_supported(self):
        with self.assertRaises((PermissionError,ValueError)):
            await self.call('scope',source_root='/outside-allowed-root/private',destination_root=str(self.dest),user_authorization='x')
        f=await self.upload(b'');self.assertTrue((await self.call('verify',transfer_id=f['id']))['matches'])
        p=await self.call('pull',transfer_id=f['id'],destination='empty');self.assertEqual(p['status'],'downloaded')


class ProcessGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_timing_collects_only_counts_and_durations(self):
        from types import SimpleNamespace
        from mopu.transfers import PROFILE
        with tempfile.TemporaryDirectory() as tmp:
            script=Path(tmp)/'fake-adb'
            script.write_text('#!/bin/sh\nprintf measured\n');script.chmod(0o700)
            d=SimpleNamespace(config={'adb':str(script)},serial='fake',connected=True,lockfile=True)
            transfers=Transfers(tmp,d);profile={};token=PROFILE.set(profile)
            try:
                self.assertEqual(await transfers.run('sensitive-path',lambda:None),b'measured')
            finally: PROFILE.reset(token)
            self.assertEqual(profile['metadata_commands']['calls'],1)
            self.assertEqual(profile['metadata_commands']['output_bytes'],8)
            self.assertGreater(profile['metadata_commands']['seconds'],0)
            self.assertNotIn('sensitive-path',str(profile))

    async def test_lease_loss_kills_inflight_backend(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            script=Path(tmp)/'fake-adb'
            script.write_text('#!/bin/sh\nexec sleep 10\n');script.chmod(0o700)
            d=SimpleNamespace(config={'adb':str(script)},serial='fake',connected=True,lockfile=True)
            transfers=Transfers(tmp,d);started=time.monotonic()
            def guard():
                if time.monotonic()-started > .15: raise PermissionError('taken over')
            with self.assertRaises(PermissionError): await transfers.run('unused',guard)
            self.assertLess(time.monotonic()-started,1)
