import json

from app.cli.queue_status import format_text


def test_text_output_does_not_contain_pii() -> None:
    output = format_text(_status())

    assert "5534999999999" not in output
    assert "Ola" not in output


def test_json_output_is_valid() -> None:
    output = json.dumps(_status())

    assert json.loads(output)["inbound"]["counts"]["pending"] == 1


def _status() -> dict[str, object]:
    section = {
        "counts": {"pending": 1, "processing": 0, "completed": 0, "failed": 0},
        "stuck_items": 0,
        "oldest_pending_at": None,
        "failed_last_24h": 0,
    }
    return {
        "inbound": section,
        "outbound": {"counts": {"pending": 0}, "stuck_items": 0, "oldest_pending_at": None, "failed_last_24h": 0},
        "media": {"counts": {"pending": 0}, "stuck_items": 0, "oldest_pending_at": None, "failed_last_24h": 0},
        "scheduling_actions": {"counts": {}, "stuck_items": 0, "oldest_pending_at": None, "failed_last_24h": 0},
    }
