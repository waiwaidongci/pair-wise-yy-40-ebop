import tempfile, unittest
from pathlib import Path
from src.domain import ConflictError, PermissionDenied
from src.repository import Repository
from src.service import Service
from src.rules import STATES, TRANSITION_ROLES
class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.repo=Repository(str(Path(self.tmp.name)/"test.db")); self.service=Service(self.repo)
    def tearDown(self): self.repo.close(); self.tmp.cleanup()
    def test_complete_workflow_and_audit(self):
        item=self.service.create_item({"title":"workflow item","description":"complete business flow","severity":'high',"quantity":12,"threshold":6,"external_ref":"WF-1"},"creator",'assessor')
        self.assertEqual(item["status"],STATES[0])
        record=self.service.add_record(item["id"],{"kind":"evidence","detail":"evidence registered","external_ref":"EV-1"},"recorder",'assessor')
        self.assertEqual(record["status"],"open")
        disposed=self.service.dispose_record(item["id"],record["id"],{"action":"close","note":"evidence verified and filed"},"recorder",'assessor')
        self.assertEqual(disposed["status"],"closed"); self.assertEqual(disposed["item_version"],2)
        current=self.service.get_item(item["id"],"viewer")
        for target in STATES[1:]:
            current=self.service.transition(current["id"],target,current["version"],"reviewer",TRANSITION_ROLES[target][0])
        self.assertEqual(current["status"],STATES[-1])
        records=self.service.list_records(current["id"],"viewer"); self.assertEqual(len(records),1)
        self.assertEqual(records[0]["events"][0]["action"],"close")
        events=self.service.audit("viewer",current["id"]); self.assertGreaterEqual(len(events),len(STATES)+2); self.assertTrue(self.repo.verify_audit_chain())

    def test_dispose_reopen_blocks_acceptance_and_version_conflict(self):
        item=self.service.create_item({"title":"disposition item","description":"close and reopen flow","severity":'medium',"external_ref":"WF-2"},"creator",'assessor')
        record=self.service.add_record(item["id"],{"kind":"finding","detail":"review finding"},"recorder",'assessor')
        # 处置推进项目版本；旧版本提交验收必须冲突
        self.service.dispose_record(item["id"],record["id"],{"action":"close","note":"fixed"},"engineer",'structural_engineer')
        self.service.transition(item["id"],"assessed",2,"reviewer",'assessor')
        self.service.transition(item["id"],"design",3,"reviewer",'structural_engineer')
        with self.assertRaises(ConflictError): self.service.transition(item["id"],"construction",3,"reviewer",'structural_engineer')
        # 审核委员会重开并要求写原因；待办再次挡住验收
        reopened=self.service.dispose_record(item["id"],record["id"],{"action":"reopen","note":"处置说明与现场不符"},"board",'review_board')
        self.assertEqual(reopened["status"],"open"); self.assertEqual(reopened["item_version"],5)
        current=self.service.transition(item["id"],"construction",5,"reviewer",'structural_engineer')
        with self.assertRaises(ConflictError): self.service.transition(item["id"],"accepted",current["version"],"reviewer",TRANSITION_ROLES["accepted"][0])
        # 待办仍开着：重复重开冲突、越权处置被拒
        with self.assertRaises(ConflictError): self.service.dispose_record(item["id"],record["id"],{"action":"reopen","note":"again"},"board",'review_board')
        with self.assertRaises(PermissionDenied): self.service.dispose_record(item["id"],record["id"],{"action":"close","note":"x"},"board",'review_board')
        with self.assertRaises(PermissionDenied): self.service.dispose_record(item["id"],record["id"],{"action":"reopen","note":"x"},"engineer",'structural_engineer')
        # 关闭最后一个待办会再推进版本：旧版本提交验收冲突，刷新后验收放行
        self.service.dispose_record(item["id"],record["id"],{"action":"close","note":"rectified and re-verified"},"engineer",'structural_engineer')
        with self.assertRaises(ConflictError): self.service.transition(item["id"],"accepted",current["version"],"reviewer",TRANSITION_ROLES["accepted"][0])
        current=self.service.get_item(item["id"],"viewer")
        current=self.service.transition(current["id"],"accepted",current["version"],"reviewer",TRANSITION_ROLES["accepted"][0])
        self.assertEqual(current["status"],"accepted")
        self.assertEqual(current["open_record_count"],0)
        detail=self.service.get_record(item["id"],record["id"],"viewer")
        self.assertEqual([e["action"] for e in detail["events"]],["close","reopen","close"])
        self.assertTrue(self.repo.verify_audit_chain())
if __name__=="__main__": unittest.main()
