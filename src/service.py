from __future__ import annotations

from typing import Any, Dict, Optional

from .domain import (ConflictError, ValidationError, ensure_role,
                     normalize_severity, require_number, require_text)
from .repository import Repository
from .rules import (AUDIT_ROLES, CREATE_ROLES, DISPOSITION_ROLES, ENTITY,
                    RECORD_ROLES, REOPEN_ROLES, TITLE, VIEW_ROLES,
                    completion_blockers, escalation_required, priority_score,
                    response_deadline_hours, role_for_transition,
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
        return self.enrich(item)

    def add_record(self, item_id: int, payload: Dict[str, Any], actor: str,
                   role: str) -> Dict[str, Any]:
        ensure_role(role, RECORD_ROLES)
        actor = require_text(actor, "actor", 100)
        kind = require_text(payload.get("kind"), "kind", 100)
        detail = require_text(payload.get("detail"), "detail")
        # 复核事项一律以待办状态建立，关闭只能通过处置接口完成
        external_ref = payload.get("external_ref")
        if external_ref is not None:
            external_ref = require_text(external_ref, "external_ref", 100)
        record = self.repository.add_record(item_id, kind, detail,
                                            external_ref, actor)
        self.repository.append_audit("record", ENTITY, item_id, actor, {
            "record_id": record["id"], "kind": kind, "status": "open",
        })
        return self._record_view(item_id, record, role)

    def dispose_record(self, item_id: int, record_id: int, payload: Dict[str, Any],
                       actor: str, role: str) -> Dict[str, Any]:
        action = payload.get("action")
        if action == "close":
            ensure_role(role, DISPOSITION_ROLES)
            note = require_text(payload.get("note"), "note（处理说明）")
        elif action == "reopen":
            ensure_role(role, REOPEN_ROLES)
            note = require_text(payload.get("note"), "note（重开原因）")
        else:
            raise ValidationError("action必须是close或reopen")
        actor = require_text(actor, "actor", 100)
        before = self.repository.get_item(item_id)
        record = self.repository.get_record(item_id, record_id)
        updated = self.repository.dispose_record(item_id, record_id, action, note, actor)
        after = self.repository.get_item(item_id)
        self.repository.append_audit(f"record_{action}", ENTITY, item_id, actor, {
            "record_id": record_id, "from": record["status"], "to": updated["status"],
            "note": note, "version_from": before["version"], "version_after": after["version"],
            "open_records": self.repository.open_record_count(item_id),
        })
        return self._record_view(item_id, updated, role, after)

    def transition(self, item_id: int, target: str, expected_version: int,
                   actor: str, role: str) -> Dict[str, Any]:
        actor = require_text(actor, "actor", 100)
        item = self.repository.get_item(item_id)
        validate_transition(item["status"], target)
        ensure_role(role, role_for_transition(target))
        if not isinstance(expected_version, int) or expected_version < 1:
            raise ValueError("expected_version必须是正整数")
        blockers = completion_blockers(target, self.repository.open_record_count(item_id))
        if blockers:
            raise ConflictError("；".join(blockers))
        updated = self.repository.transition_item(item_id, target, expected_version, actor)
        self.repository.append_audit("transition", ENTITY, item_id, actor, {
            "from": item["status"], "to": target,
            "escalation_required": escalation_required(
                item["severity"], item["quantity"], item["threshold"]),
        })
        return self.enrich(updated)

    def get_item(self, item_id: int, role: str) -> Dict[str, Any]:
        self._view(role)
        return self.enrich(self.repository.get_item(item_id))

    def list_items(self, role: str, status: Optional[str] = None) -> list:
        self._view(role)
        return [self.enrich(item) for item in self.repository.list_items(status)]

    def list_records(self, item_id: int, role: str, status: Optional[str] = None) -> list:
        self._view(role)
        if status is not None and status not in ("open", "closed"):
            raise ValidationError("status只能是open或closed")
        return [self._record_view(item_id, record, role)
                for record in self.repository.list_records(item_id, status)]

    def get_record(self, item_id: int, record_id: int, role: str) -> Dict[str, Any]:
        self._view(role)
        return self._record_view(
            item_id, self.repository.get_record(item_id, record_id), role)

    def audit(self, role: str, item_id: Optional[int] = None) -> list:
        ensure_role(role, AUDIT_ROLES)
        return self.repository.list_audit(item_id)

    def _record_view(self, item_id: int, record: Dict[str, Any], role: str,
                     item: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        del role
        result = dict(record)
        result["events"] = self.repository.list_record_events(item_id, record["id"])
        if item is None:
            item = self.repository.get_item(item_id)
        result["item_version"] = item["version"]
        result["open_record_count"] = self.repository.open_record_count(item_id)
        result["acceptance_blocked"] = result["open_record_count"] > 0
        return result

    def enrich(self, item: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(item)
        result["priority"] = priority_score(
            item["severity"], item["quantity"], item["threshold"])
        result["deadline_hours"] = response_deadline_hours(
            item["severity"], item["quantity"], item["threshold"])
        result["escalation_required"] = escalation_required(
            item["severity"], item["quantity"], item["threshold"])
        result["open_record_count"] = self.repository.open_record_count(item["id"])
        result["acceptance_blocked"] = result["open_record_count"] > 0
        return result
