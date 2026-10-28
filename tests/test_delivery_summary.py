import unittest
from mopu.continuation import Continuation

class DeliverySummaryTests(unittest.TestCase):
    def test_missing_ledger_is_unknown_not_zero(self):
        result=Continuation.delivery_summary({'result':'Assistant claimed 13 sends'})
        self.assertEqual(result['coverage'],'unrecorded')
        self.assertIsNone(result['verified']);self.assertIsNone(result['pending'])
        self.assertTrue(result['report_available'])
    def test_recorded_outcomes_are_separate(self):
        result=Continuation.delivery_summary({'deliveries':[{'outcome':'delivered'},{'outcome':'uncertain'},{'outcome':'not_sent'}]})
        self.assertEqual((result['verified'],result['pending'],result['not_sent']),(1,1,1))
    def test_empty_initialized_ledger_is_recorded_zero(self):
        self.assertEqual(Continuation.delivery_summary({'deliveries':[]})['verified'],0)
