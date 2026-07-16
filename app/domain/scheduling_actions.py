import hashlib
import json
from typing import Any


def confirmation_fingerprint(data: dict[str, Any]) -> str:
    canonical = json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
