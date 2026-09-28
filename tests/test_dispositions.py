import tempfile, unittest
from pathlib import Path
from src.domain import ConflictError, PermissionDenied, ValidationError
from src.repository import Repository
from src.service import Service
from src.rules import STATES, TRANSITION_ROLES


class DispositionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repository(str(Path(self.tmp.name) / "test.db"))
        self.service = Service(self.repo)
        self.item = self.service.create_item(
            {"title": "review item", "description": "disposition lifecycle",
             "severity": "high", "quantity": 5, "threshold": 10,
             "external_ref": "DISP-1"}, "creator", "assessor")
        # 推进到施工阶段（验收前最后一步），并提两条待办事项
        current = self.item
        for target in STATES[1:4]:
            current = self.service.transition(
                current["id"], target, current["version"], "reviewer",
                TRANSITION_ROLES[target][0])
        self.item = current
        self.rec1 = self.service.add_record(
            self.item["id"], {"kind": "finding", "detail": "梁箍筋不足",
                              "status": "open"}, "recorder", "assessor")
        self.rec2 = self.service.add_record(
            self.item["id"], {"kind": "finding", "detail": "节点裂缝",
                              "status": "open"}, "recorder", "assessor")

    def tearDown(self):
        self.repo.close()
        self.tmp.cleanup()

    def test_open_items_block_acceptance_and_listed(self):
        detail = self.service.get_item(self.item["id"], "viewer")
        self.assertEqual(detail["open_record_count"], 2)
        self.assertTrue(detail["acceptance_blocked"])
        blocking = self.service.blocking_records(self.item["id"], "viewer")
        self.assertEqual({r["id"] for r in blocking},
                         {self.rec1["id"], self.rec2["id"]})
        with self.assertRaises(ConflictError):
            self.service.transition(
                self.item["id"], "accepted", self.item["version"], "board",
                "review_board")

    def test_close_requires_note_roles_and_bumps_version(self):
        with self.assertRaises(PermissionDenied):
            self.service.dispose_record(
                self.rec1["id"], {"action": "close", "note": "已加固",
                                  "expected_version": self.item["version"]},
                "board", "review_board")
        with self.assertRaises(ValidationError):
            self.service.dispose_record(
                self.rec1["id"], {"action": "close", "note": "  ",
                                  "expected_version": self.item["version"]},
                "eng", "structural_engineer")
        result = self.service.dispose_record(
            self.rec1["id"], {"action": "close", "note": "已补箍筋并复验",
                              "expected_version": self.item["version"]},
            "eng", "structural_engineer")
        self.assertEqual(result["record"]["status"], "closed")
        self.assertEqual(result["record"]["disposition_note"], "已补箍筋并复验")
        self.assertEqual(result["record"]["disposition_by"], "eng")
        self.assertEqual(result["item"]["version"], self.item["version"] + 1)
        self.assertEqual(result["item"]["open_record_count"], 1)
        # 处置历史已登记
        history = self.service.list_dispositions(self.rec1["id"], "viewer")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["action"], "close")
        self.assertEqual(history[0]["to_version"], self.item["version"] + 1)
        # 不能重复关闭
        with self.assertRaises(ConflictError):
            self.service.dispose_record(
                self.rec1["id"], {"action": "close", "note": "再次关闭",
                                  "expected_version": result["item"]["version"]},
                "eng", "structural_engineer")

    def test_reopen_only_by_board_with_reason(self):
        result = self.service.dispose_record(
            self.rec1["id"], {"action": "close", "note": "已处理",
                              "expected_version": self.item["version"]},
            "assessor", "assessor")
        # 工程师不能重开
        with self.assertRaises(PermissionDenied):
            self.service.dispose_record(
                self.rec1["id"], {"action": "reopen", "note": "处置不实",
                                  "expected_version": result["item"]["version"]},
                "eng", "structural_engineer")
        # 重开原因必填
        with self.assertRaises(ValidationError):
            self.service.dispose_record(
                self.rec1["id"], {"action": "reopen", "note": "",
                                  "expected_version": result["item"]["version"]},
                "board", "review_board")
        reopened = self.service.dispose_record(
            self.rec1["id"], {"action": "reopen",
                              "note": "现场复核发现处理说明与实际不符",
                              "expected_version": result["item"]["version"]},
            "board", "review_board")
        self.assertEqual(reopened["record"]["status"], "open")
        self.assertEqual(reopened["record"]["reopen_reason"],
                         "现场复核发现处理说明与实际不符")
        self.assertEqual(reopened["item"]["version"],
                         self.item["version"] + 2)
        # 重新挡住验收
        self.assertTrue(reopened["item"]["acceptance_blocked"])
        self.assertEqual(reopened["item"]["open_record_count"], 2)

    def test_stale_version_conflicts_on_disposition_and_acceptance(self):
        stale = self.item["version"]
        self.service.dispose_record(
            self.rec1["id"], {"action": "close", "note": "已处理",
                              "expected_version": stale},
            "eng", "structural_engineer")
        # 版本已推进，旧版本处置冲突
        with self.assertRaises(ConflictError):
            self.service.dispose_record(
                self.rec2["id"], {"action": "close", "note": "已处理",
                                  "expected_version": stale},
                "eng", "structural_engineer")
        # 关闭剩余事项（使用最新版本）
        current = self.service.get_item(self.item["id"], "viewer")
        result = self.service.dispose_record(
            self.rec2["id"], {"action": "close", "note": "裂缝已注胶",
                              "expected_version": current["version"]},
            "eng", "structural_engineer")
        # 关闭最后一个待办后才能验收；旧版本提交验收冲突
        with self.assertRaises(ConflictError):
            self.service.transition(
                self.item["id"], "accepted", stale, "board", "review_board")
        accepted = self.service.transition(
            self.item["id"], "accepted", result["item"]["version"], "board",
            "review_board")
        self.assertEqual(accepted["status"], "accepted")
        self.assertFalse(accepted["acceptance_blocked"])

    def test_audit_records_dispositions(self):
        self.service.dispose_record(
            self.rec1["id"], {"action": "close", "note": "已处理",
                              "expected_version": self.item["version"]},
            "eng", "structural_engineer")
        events = self.service.audit("viewer", self.item["id"])
        self.assertIn("disposition", [e["action"] for e in events])
        self.assertTrue(self.repo.verify_audit_chain())


if __name__ == "__main__":
    unittest.main()
