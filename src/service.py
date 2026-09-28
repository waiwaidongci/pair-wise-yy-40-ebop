from __future__ import annotations

from typing import Any, Dict, Optional

from .domain import (ConflictError, ValidationError, ensure_role,
                     normalize_severity, require_number, require_text)
from .repository import Repository
from .rules import (AUDIT_ROLES, CREATE_ROLES, DISPOSE_ACTIONS, DISPOSE_ROLES,
                    ENTITY, RECORD_ROLES, REOPEN_ROLES, TERMINAL_STATES,
                    VIEW_ROLES, completion_blockers, escalation_required,
                    priority_score, response_deadline_hours, role_for_transition,
                    validate_transition)


class Service:
    def __init__(self, repository: Repository):
        self.repository = repository

    def _view(self, role: str) -> None:
        ensure_role(role, VIEW_ROLES)

    def create_item(self, payload: Dict[str, Any], actor: str, role: str) -> Dict[str, Any]:
        ensure_role(role, CREATE_ROLES)
        actor = require_text(actor, "actor", 100)
        title = require_text(payload.get("title"), "title", 200)
        description = require_text(payload.get("description"), "description")
        severity = normalize_severity(payload.get("severity"))
        quantity = require_number(payload.get("quantity", 0), "quantity")
        threshold = require_number(payload.get("threshold", 1), "threshold", 0.000001)
        external_ref = payload.get("external_ref")
        if external_ref is not None:
            external_ref = require_text(external_ref, "external_ref", 100)
        item = self.repository.create_item(title, description, severity, quantity,
                                           threshold, external_ref, actor)
        self.repository.append_audit("create", ENTITY, item["id"], actor, {
            "title": title, "severity": severity, "quantity": quantity,
            "priority": priority_score(severity, quantity, threshold),
        })
        return self.enrich(item, 0)

    def add_record(self, item_id: int, payload: Dict[str, Any], actor: str,
                   role: str) -> Dict[str, Any]:
        ensure_role(role, RECORD_ROLES)
        actor = require_text(actor, "actor", 100)
        kind = require_text(payload.get("kind"), "kind", 100)
        detail = require_text(payload.get("detail"), "detail")
        status = payload.get("status", "open")
        if status not in ("open", "closed"):
            raise ValidationError("status必须是open或closed")
        external_ref = payload.get("external_ref")
        if external_ref is not None:
            external_ref = require_text(external_ref, "external_ref", 100)
        record = self.repository.add_record(item_id, kind, detail, status,
                                            external_ref, actor)
        self.repository.append_audit("record", ENTITY, item_id, actor, {
            "record_id": record["id"], "kind": kind, "status": status,
        })
        return record

    def transition(self, item_id: int, target: str, expected_version: int,
                   actor: str, role: str) -> Dict[str, Any]:
        actor = require_text(actor, "actor", 100)
        item = self.repository.get_item(item_id)
        validate_transition(item["status"], target)
        ensure_role(role, role_for_transition(target))
        if not isinstance(expected_version, int) or isinstance(expected_version, bool) \
                or expected_version < 1:
            raise ValidationError("expected_version必须是正整数")
        open_records = self.repository.open_record_count(item_id)
        blockers = completion_blockers(target, open_records)
        if blockers:
            raise ConflictError("；".join(blockers))
        updated = self.repository.transition_item(item_id, target, expected_version, actor)
        self.repository.append_audit("transition", ENTITY, item_id, actor, {
            "from": item["status"], "to": target,
            "escalation_required": escalation_required(
                item["severity"], item["quantity"], item["threshold"]),
        })
        return self.enrich(updated, open_records)

    def dispose_record(self, record_id: int, payload: Dict[str, Any], actor: str,
                       role: str) -> Dict[str, Any]:
        """按事项编号提交处理说明并关闭，或重开并填写原因；每次处置推进项目版本。"""
        actor = require_text(actor, "actor", 100)
        action = payload.get("action")
        if action not in DISPOSE_ACTIONS:
            raise ValidationError("action必须是close或reopen")
        note = require_text(payload.get("note"), "note")
        expected_version = payload.get("expected_version")
        if not isinstance(expected_version, int) or isinstance(expected_version, bool) \
                or expected_version < 1:
            raise ValidationError("expected_version必须是正整数")
        roles = DISPOSE_ROLES if action == "close" else REOPEN_ROLES
        ensure_role(role, roles)
        result = self.repository.dispose_record(record_id, action, note,
                                                expected_version, actor)
        record, item = result["record"], result["item"]
        audit_note_key = "处理说明" if action == "close" else "重开原因"
        self.repository.append_audit("disposition", ENTITY, item["id"], actor, {
            "record_id": record["id"], "kind": record["kind"], "action": action,
            audit_note_key: note, "project_version": item["version"],
        })
        result["item"] = self.enrich(item, self.repository.open_record_count(item["id"]))
        return result

    def get_item(self, item_id: int, role: str) -> Dict[str, Any]:
        self._view(role)
        item = self.repository.get_item(item_id)
        return self.enrich(item, self.repository.open_record_count(item_id))

    def list_items(self, role: str, status: Optional[str] = None) -> list:
        self._view(role)
        items = self.repository.list_items(status)
        result = []
        for item in items:
            result.append(self.enrich(item,
                                      self.repository.open_record_count(item["id"])))
        return result

    def list_records(self, item_id: int, role: str,
                     status: Optional[str] = None) -> list:
        self._view(role)
        records = self.repository.list_records(item_id)
        if status:
            records = [r for r in records if r["status"] == status]
        return records

    def list_dispositions(self, record_id: int, role: str) -> list:
        self._view(role)
        self.repository.get_record(record_id)
        return self.repository.list_dispositions(record_id)

    def blocking_records(self, item_id: int, role: str) -> list:
        """列出仍挡住验收的待办事项。"""
        self._view(role)
        return [self.repository.get_record(rid)
                for rid in self.repository.open_record_ids(item_id)]

    def audit(self, role: str, item_id: Optional[int] = None) -> list:
        ensure_role(role, AUDIT_ROLES)
        return self.repository.list_audit(item_id)

    @staticmethod
    def enrich(item: Dict[str, Any], open_records: int = 0) -> Dict[str, Any]:
        result = dict(item)
        open_records = int(open_records)
        result["open_record_count"] = open_records
        result["acceptance_blocked"] = item["status"] not in TERMINAL_STATES \
            and open_records > 0
        result["priority"] = priority_score(
            item["severity"], item["quantity"], item["threshold"], open_records)
        result["deadline_hours"] = response_deadline_hours(
            item["severity"], item["quantity"], item["threshold"])
        result["escalation_required"] = escalation_required(
            item["severity"], item["quantity"], item["threshold"])
        return result
