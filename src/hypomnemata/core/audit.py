"""Audit log: one JSON line per action taken by a tool or a model.

Every action of the core is recorded so that a run can be reviewed later:
what happened, when, with which inputs and results. The log is the basis
for improving the harness over time.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any


class AuditLog:
    def __init__(self, directory: Path) -> None:
        self.path = directory / "audit.jsonl"

    def record(self, event: str, **data: Any) -> None:
        entry = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "event": event,
            **data,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as log:
            log.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
