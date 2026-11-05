"""Validate the installed Redis transport, optionally with a disposable queue.

The broker check publishes only a synthetic message to a unique, expiring
queue. It does not send application tasks or expose connection settings.
"""

import argparse
import json
import os
from importlib.metadata import version
from types import SimpleNamespace
from uuid import uuid4


def check_transport():
    from kombu.transport.redis import Channel

    # Channel construction uses this compatibility gate before any network IO.
    # Importing Celery alone does not check the installed Redis client version.
    Channel._get_client(SimpleNamespace(global_keyprefix=""))


def check_broker():
    from kombu import Connection

    url = os.environ.get("CELERY_BROKER_URL")
    if not url or not url.startswith(("redis://", "rediss://")):
        raise ValueError("A Redis CELERY_BROKER_URL is required")
    token = uuid4().hex
    with Connection(
        url,
        connect_timeout=5,
        transport_options={"socket_connect_timeout": 5, "socket_timeout": 5},
    ) as connection:
        connection.ensure_connection(max_retries=0)
        queue = connection.SimpleQueue(
            "leagueos.runtime-probe." + token,
            queue_opts={"durable": False, "auto_delete": True, "expires": 60},
            exchange_opts={"durable": False, "auto_delete": True},
        )
        try:
            queue.put({"probe": token}, serializer="json")
            message = queue.get(block=True, timeout=5)
            if message.payload != {"probe": token}:
                raise RuntimeError("Broker probe payload mismatch")
            message.ack()
        finally:
            try:
                queue.queue.delete()
            finally:
                queue.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--broker", action="store_true")
    args = parser.parse_args()
    report = {"versions": {p: version(p) for p in ("celery", "kombu", "redis")}}
    try:
        check_transport()
        report["transport"] = "ok"
        if args.broker:
            check_broker()
            report["broker_roundtrip"] = "ok"
    except Exception as error:
        # Connection failures can include credentials; print only the class.
        report.update(result="FAIL", error_type=type(error).__name__)
        print(json.dumps(report))
        return 1
    report["result"] = "PASS"
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
