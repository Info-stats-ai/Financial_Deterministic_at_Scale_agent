"""Redaction at the persistence boundary."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from interface_ai.safety.policy import RedactionPolicy

REDACTED = "[REDACTED]"


class Redactor:
    def __init__(self, policy: RedactionPolicy) -> None:
        self.sensitive_keys = {key.lower() for key in policy.sensitive_keys}
        self.patterns = [(item.name, re.compile(item.regex)) for item in policy.patterns]

    def redact_text(self, value: str) -> str:
        redacted = value
        for name, pattern in self.patterns:
            redacted = pattern.sub(f"[REDACTED:{name}]", redacted)
        return self._redact_url_query(redacted)

    def _redact_url_query(self, value: str) -> str:
        if "://" not in value:
            return value
        try:
            parsed = urlsplit(value)
            query = [
                (key, REDACTED if key.lower() in self.sensitive_keys else item)
                for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            ]
            return urlunsplit(
                (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
            )
        except ValueError:
            return value

    def redact(self, value: Any, *, parent_key: str | None = None) -> Any:
        if parent_key and parent_key.lower() in self.sensitive_keys:
            return REDACTED
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, Mapping):
            return {str(key): self.redact(item, parent_key=str(key)) for key, item in value.items()}
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [self.redact(item) for item in value]
        return value
