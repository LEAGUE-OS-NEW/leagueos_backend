#!/usr/bin/env python3
"""Generate a Postman collection from the OpenAPI schema."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
OPENAPI_FILE = BASE_DIR / "docs" / "openapi.yml"
POSTMAN_FILE = BASE_DIR / "docs" / "postman" / "LeagueOS.postman_collection.json"


def load_openapi() -> dict:
    with OPENAPI_FILE.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def sanitize_name(name: str) -> str:
    return name.replace("/", "_").replace("<", "").replace(">", "").replace(":", "_").strip("_")


def build_request(operation: dict, path: str, method: str, tag: str) -> dict:
    headers = [{"key": "Content-Type", "value": "application/json"}]
    if method.lower() in {"post", "put", "patch"} and "requestBody" in operation:
        content = operation["requestBody"].get("content", {})
        if "application/json" in content:
            headers = [{"key": "Content-Type", "value": "application/json"}]

    url = "/".join(
        part if not part.startswith("{") else f":{part[1:-1]}"
        for part in path.strip("/").split("/")
    )
    url = f"/{url}"

    request = {
        "name": operation.get("summary", operation.get("operationId", sanitize_name(path))),
        "request": {
            "method": method.upper(),
            "header": headers,
            "url": {
                "raw": "{{base_url}}" + url,
                "host": ["{{base_url}}"],
                "path": [part.lstrip(":") for part in path.strip("/").split("/")],
            },
        },
        "response": [],
    }

    if method.lower() in {"post", "put", "patch"} and "requestBody" in operation:
        content = operation["requestBody"].get("content", {})
        json_content = content.get("application/json", {})
        if json_content:
            schema = json_content.get("schema", {})
            example = {}
            if "properties" in schema:
                for prop_name, prop_schema in schema["properties"].items():
                    if "example" in prop_schema:
                        example[prop_name] = prop_schema["example"]
                    elif prop_schema.get("type") == "string":
                        example[prop_name] = "string"
                    elif prop_schema.get("type") == "integer":
                        example[prop_name] = 0
                    elif prop_schema.get("type") == "boolean":
                        example[prop_name] = False
                    elif prop_schema.get("type") == "array":
                        example[prop_name] = []
                    elif "$ref" in prop_schema:
                        example[prop_name] = {}
                    else:
                        example[prop_name] = ""
            request["request"].setdefault("body", {})
            request["request"]["body"] = {
                "mode": "raw",
                "raw": json.dumps(example, indent=2),
                "options": {"raw": {"language": "json"}},
            }

    request["request"]["url"]["raw"] = "{{base_url}}" + url

    return request


def build_collection(spec: dict) -> dict:
    tags = spec.get("tags", [])
    tag_map = {tag["name"]: tag.get("description", "") for tag in tags if "name" in tag}

    paths = spec.get("paths", {})
    collection = {
        "info": {
            "name": spec.get("info", {}).get("title", "LeagueOS API"),
            "description": spec.get("info", {}).get("description", ""),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "item": [],
        "auth": {
            "type": "bearer",
            "bearer": [
                {"key": "token", "value": "{{access_token}}", "type": "string"},
            ],
        },
        "event": [],
        "variable": [
            {"key": "base_url", "value": "http://127.0.0.1:8000"},
            {"key": "access_token", "value": ""},
            {"key": "refresh_token", "value": ""},
        ],
    }

    tag_folders: dict[str, list] = {}

    for path, methods in paths.items():
        for method, operation in methods.items():
            if method.lower() in {"get", "post", "put", "patch", "delete", "options", "head"}:
                operation_tags = operation.get("tags", ["General"])
                tag = operation_tags[0] if operation_tags else "General"
                folder = tag_folders.setdefault(tag, [])
                folder.append(build_request(operation, path, method, tag))

    for tag, folder_name in tag_map.items():
        if tag in tag_folders:
            collection["item"].append({"name": tag, "item": tag_folders[tag]})

    for tag, items in tag_folders.items():
        if tag not in tag_map:
            collection["item"].append({"name": tag, "item": items})

    return collection


def main() -> None:
    spec = load_openapi()
    collection = build_collection(spec)
    POSTMAN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with POSTMAN_FILE.open("w", encoding="utf-8") as fh:
        json.dump(collection, fh, indent=2)
    print(f"Postman collection written to {POSTMAN_FILE}")


if __name__ == "__main__":
    main()
