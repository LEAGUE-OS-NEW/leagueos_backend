#!/usr/bin/env python3
"""Inject authentication scripts into the Postman collection."""

from __future__ import annotations

import json
from pathlib import Path

POSTMAN_FILE = Path(__file__).resolve().parent.parent / "docs" / "postman" / "LeagueOS.postman_collection.json"

LOGIN_SCRIPT = """if (pm.response.code === 200) {
    const json = pm.response.json();
    const access = json.access || json.data?.access;
    const refresh = json.refresh || json.data?.refresh;
    if (access) pm.environment.set('access_token', access);
    if (refresh) pm.environment.set('refresh_token', refresh);
}"""

REFRESH_SCRIPT = """if (pm.response.code === 200) {
    const json = pm.response.json();
    const access = json.access || json.data?.access;
    if (access) pm.environment.set('access_token', access);
}"""


def inject_scripts() -> None:
    with POSTMAN_FILE.open("r", encoding="utf-8") as fh:
        collection = json.load(fh)

    for item in collection.get("item", []):
        _inject_into_folder(item)

    with POSTMAN_FILE.open("w", encoding="utf-8") as fh:
        json.dump(collection, fh, indent=2)


def _inject_into_folder(folder: dict) -> None:
    if "item" in folder:
        for child in folder["item"]:
            _inject_into_folder(child)
        return

    request = folder.get("request", {})
    url = request.get("url", {})
    path = "/".join(url.get("path", []))

    if path.endswith("login/") or path.endswith("token-refresh/"):
        script = LOGIN_SCRIPT if path.endswith("login/") else REFRESH_SCRIPT
        folder.setdefault("event", []).append(
            {
                "listen": "test",
                "script": {
                    "type": "text/javascript",
                    "exec": [script],
                },
            }
        )


if __name__ == "__main__":
    inject_scripts()
    print(f"Injected auth scripts into {POSTMAN_FILE}")
