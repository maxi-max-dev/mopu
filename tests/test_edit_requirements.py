import copy
import tempfile
import unittest
from pathlib import Path
from mopu.tasks import Queue

class EditTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.q=Queue(Path(self.temp.name)/'queue.json');self.q.owner='human'
        self.t=self.q.get(self.q.add('Before','Old scope','test','Test')['id'])
    def edit(self, **kw):
        args=dict(ident=self.t['id'],title='After',instruction='New scope',expected_title='Before',expected_instruction='Old scope');args.update(kw);self.q.edit(**args)
    def test_history_persistence_and_progress_preserved(self):
        self.t.update(steps=190,checkpoint='Keep progress',pending_delivery='pending-key',deliveries=[{'key':'pending-key','outcome':'pending'}])
        before=copy.deepcopy(self.t);self.edit();fresh=Queue(self.q.path).get(self.t['id'])
        for key in ('steps','checkpoint','pending_delivery','deliveries','id','agent','status'):self.assertEqual(before[key],fresh[key])
        self.assertEqual(fresh['instruction'],'New scope');self.assertEqual(fresh['requirement_history'][0]['instruction'],'Old scope')
    def test_stale_edit_rejected(self):
        self.t['instruction']='Changed elsewhere'
        with self.assertRaises(ValueError):self.edit()
        self.assertNotIn('requirement_history',self.t)
    def test_active_lease_rejected(self):
        self.q.owner='agent';self.q.claim('test')
        with self.assertRaises(PermissionError):self.edit()
    def test_new_requirements_invalidate_approved_stage(self):
        self.t.update(long_task=True,reviews=[{'state':'approved','ceiling':200,'expires_at':9999999999}])
        self.edit();self.assertEqual(self.t['reviews'][0]['state'],'closed');self.assertEqual(self.t['status'],'blocked');self.assertEqual(self.t['steps'],0)
    def test_finished_and_empty_rejected(self):
        with self.assertRaises(ValueError):self.edit(instruction=' ')
        self.t['status']='done'
        with self.assertRaises(ValueError):self.edit()
