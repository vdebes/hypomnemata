import json
from pathlib import Path

from hypomnemata.core.audit import AuditLog


def test_appends_one_json_line_per_event(tmp_path: Path) -> None:
    audit = AuditLog(tmp_path / "var" / "log")
    audit.record("first", path=tmp_path / "a.md")
    audit.record("second", note="é")

    lines = audit.path.read_text(encoding="utf-8").splitlines()
    events = [json.loads(line) for line in lines]
    assert [event["event"] for event in events] == ["first", "second"]
    assert events[0]["path"] == str(tmp_path / "a.md")
    assert events[1]["note"] == "é"
    assert all("ts" in event for event in events)
