import tempfile, unittest
from pathlib import Path
from src.domain import ConflictError, NotFoundError, PermissionDenied, ValidationError
from src.repository import Repository
from src.service import Service
from src.rules import STATES, TRANSITION_ROLES
class FailureTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.repo=Repository(str(Path(self.tmp.name)/"test.db")); self.service=Service(self.repo)
        self.item=self.service.create_item({"title":"failure item","description":"failure scenarios","severity":'high',"quantity":5,"threshold":10,"external_ref":"FAIL-1"},"creator",'assessor')
    def tearDown(self): self.repo.close(); self.tmp.cleanup()
    def test_permission_version_duplicate_and_invariant(self):
        with self.assertRaises(PermissionDenied): self.service.transition(self.item["id"],STATES[1],1,"attacker","viewer")
        with self.assertRaises(ConflictError): self.service.transition(self.item["id"],STATES[1],99,"reviewer",TRANSITION_ROLES[STATES[1]][0])
        payload={"kind":"action","detail":"same reference","external_ref":"DUP-1"}
        record=self.service.add_record(self.item["id"],payload,"recorder",'assessor')
        self.assertEqual(record["status"],"open")
        with self.assertRaises(ConflictError): self.service.add_record(self.item["id"],payload,"recorder",'assessor')
        current=self.service.get_item(self.item["id"],"viewer")
        for target in STATES[1:4]: current=self.service.transition(current["id"],target,current["version"],"reviewer",TRANSITION_ROLES[target][0])
        with self.assertRaises(ConflictError): self.service.transition(current["id"],"accepted",current["version"],"reviewer",TRANSITION_ROLES["accepted"][0])
        # 处置接口的失败路径
        with self.assertRaises(ValidationError): self.service.dispose_record(self.item["id"],record["id"],{"action":"close","note":"  "},"engineer",'structural_engineer')
        with self.assertRaises(ValidationError): self.service.dispose_record(self.item["id"],record["id"],{"action":"snooze","note":"x"},"engineer",'structural_engineer')
        with self.assertRaises(PermissionDenied): self.service.dispose_record(self.item["id"],record["id"],{"action":"close","note":"x"},"attacker","viewer")
        with self.assertRaises(NotFoundError): self.service.dispose_record(self.item["id"],9999,{"action":"close","note":"x"},"engineer",'structural_engineer')
        # 关闭后重复关闭冲突；关闭后验收放行
        self.service.dispose_record(self.item["id"],record["id"],{"action":"close","note":"rectified"},"engineer",'structural_engineer')
        with self.assertRaises(ConflictError): self.service.dispose_record(self.item["id"],record["id"],{"action":"close","note":"again"},"engineer",'structural_engineer')
        accepted=self.service.transition(current["id"],"accepted",current["version"]+1,"reviewer",TRANSITION_ROLES["accepted"][0])
        self.assertEqual(accepted["status"],"accepted")
        # 审核委员会仍可重开已验收项目中的失实处置
        reopened=self.service.dispose_record(self.item["id"],record["id"],{"action":"reopen","note":"抽验发现处置不实"},"board",'review_board')
        self.assertEqual(reopened["status"],"open")
if __name__=="__main__": unittest.main()
