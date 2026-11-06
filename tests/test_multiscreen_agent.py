import unittest
from mopu.multiscreen_agent import validate,evidence_matches
class AdaptiveSafetyTests(unittest.TestCase):
 def setUp(self):
  self.tree={'nodes':[{'node':3,'text':'搜索','package':'app.test','enabled':True,'visible':True,'editable':True,'scrollable':False,'password':False}]}
  self.d={'action':'text','node':3,'value':'Android','summary':'搜索','risk':'search','evidence':[]}
 def test_fresh_visible_editable_search(self):self.assertEqual(validate(self.d,self.tree,'app.test','搜索文档')['node'],3)
 def test_other_app_rejected(self):
  with self.assertRaises(PermissionError):validate(self.d,self.tree,'other.app','搜索文档')
 def test_external_actions_rejected(self):
  self.d['risk']='external'
  with self.assertRaises(PermissionError):validate(self.d,self.tree,'app.test','发消息')
 def test_password_rejected(self):
  self.tree['nodes'][0]['password']=True
  with self.assertRaises(ValueError):validate(self.d,self.tree,'app.test','搜索文档')
 def test_delete_label_rejected_even_if_model_calls_it_navigation(self):
  self.tree['nodes'][0]['text']='删除';self.d['risk']='navigate'
  with self.assertRaises(PermissionError):validate(self.d,self.tree,'app.test','查看文档')
 def test_ime_submit_requires_search(self):
  self.d.update(action='ime_enter',risk='navigate')
  with self.assertRaises(PermissionError):validate(self.d,self.tree,'app.test','查看文档')
 def test_completion_requires_actual_text_not_model_claim(self):
  self.assertFalse(evidence_matches(self.tree,[]));self.assertFalse(evidence_matches(self.tree,['Python教程']));self.assertTrue(evidence_matches(self.tree,['搜索']))
