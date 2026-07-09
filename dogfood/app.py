"""Small task-queue app used for keyhole dogfooding."""

import json
import logging
import time

logger = logging.getLogger("app")

DEFAULT_TIMEOUT = 60
RETRY_LIMIT = 3
BATCH_SIZE = 100
QUEUE_NAME = "tasks-main"


def load_config(path):
    """Load JSON config from path, with defaults filled in."""
    with open(path) as fh:
        cfg = json.load(fh)
    cfg.setdefault("timeout", DEFAULT_TIMEOUT)
    cfg.setdefault("retries", RETRY_LIMIT)
    cfg.setdefault("queue", QUEUE_NAME)
    return cfg


def connect(cfg):
    url = cfg.get("url", "amqp://localhost:5672")
    logger.info("connecting to %s", url)
    return FakeConnection(url, timeout=cfg["timeout"])


class FakeConnection:
    def __init__(self, url, timeout=DEFAULT_TIMEOUT):
        self.url = url
        self.timeout = timeout
        self.attempts = 0

    def send(self, payload):
        body = json.dumps(payload)
        self.attempts += 1
        if self.attempts > RETRY_LIMIT:
            raise RuntimeError("too many attempts")
        logger.debug("sent %d bytes", len(body))
        return True


def process(conn, items):
    ok = 0
    for item in items:
        if conn.send(item):
            ok += 1
        time.sleep(0.01)
    logger.info("processed %d/%d items", ok, len(items))
    return ok


def main():
    cfg = load_config("config.json")
    conn = connect(cfg)
    items = [{"id": i} for i in range(10)]
    process(conn, items)


if __name__ == "__main__":
    main()
