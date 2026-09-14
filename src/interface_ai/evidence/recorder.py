"""Append-only JSONL evidence writer with mandatory redaction."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from interface_ai.safety.redaction import REDACTED, Redactor


class EvidenceRecorder:
    def __init__(
        self,
        run_dir: Path,
        *,
        run_id: str,
        redactor: Redactor,
        secret_values: list[str] | None = None,
    ) -> None:
        self.run_dir = run_dir
        self.run_id = run_id
        self.redactor = redactor
        self.secret_values = [value for value in (secret_values or []) if value]
        self.events_path = run_dir / "events.jsonl"
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def add_secret_values(self, values: list[str]) -> None:
        for value in values:
            if value and value not in self.secret_values:
                self.secret_values.append(value)

    def _remove_runtime_secrets(self, value: Any) -> Any:
        if isinstance(value, str):
            result = value
            for secret in self.secret_values:
                result = result.replace(secret, REDACTED)
            return result
        if isinstance(value, dict):
            return {key: self._remove_runtime_secrets(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._remove_runtime_secrets(item) for item in value]
        return value

    def record(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "run_id": self.run_id,
            "event_type": event_type,
            "payload": payload,
        }
        sanitized = self.redactor.redact(self._remove_runtime_secrets(event))
        with self.events_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(sanitized, sort_keys=True, default=str) + "\n")

    def write_json(self, name: str, payload: Any) -> Path:
        path = self.run_dir / name
        sanitized = self.redactor.redact(self._remove_runtime_secrets(payload))
        path.write_text(
            json.dumps(sanitized, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        return path

    def write_bytes(self, name: str, payload: bytes) -> Path:
        path = self.run_dir / name
        path.write_bytes(payload)
        return path
