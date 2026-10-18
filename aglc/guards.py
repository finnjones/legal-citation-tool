"""HTTP-level protections for the web server: a request body cap, security headers, and
keeping session ids (which unlock paid documents) out of the access log.

    AGLC_MAX_UPLOAD_MB   largest .docx accepted, in MB (default 10)
"""

from __future__ import annotations

import json
import logging
import os
import re

#: room for the multipart boundaries and the small form fields around the file
MULTIPART_OVERHEAD = 64 * 1024

_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def max_upload_bytes() -> int:
    try:
        mb = float(os.environ.get("AGLC_MAX_UPLOAD_MB") or 10)
    except ValueError:
        mb = 10
    return int(mb * 1024 * 1024)


def too_large_message() -> str:
    return f"That file is too large. The limit is {max_upload_bytes() // (1024 * 1024)} MB."


class GuardMiddleware:
    """Refuse (413) a request body over the upload limit as it streams in, without reading
    the rest, and add security headers to every response.

    Starlette spools a multipart upload to disk before the endpoint runs, so the endpoint
    alone can't stop a huge upload; this sits in front of it. A declared Content-Length over
    the limit is refused before any of the body is read; a chunked body is counted as it
    arrives and cut off once over."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = max_upload_bytes() + MULTIPART_OVERHEAD
        api = scope.get("path", "").startswith("/api/")

        async def send_with_headers(message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                extra = [(b"referrer-policy", b"no-referrer"), (b"x-content-type-options", b"nosniff")]
                if api:  # results are a student's own work: don't leave them in shared caches
                    extra.append((b"cache-control", b"no-store"))
                headers += [(k, v) for k, v in extra if k not in present]
                message = {**message, "headers": headers}
            await send(message)

        declared = dict(scope.get("headers", [])).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await _too_large(send_with_headers)
            return

        received, exceeded, started = 0, False, False

        async def limited_receive():
            nonlocal received, exceeded
            if exceeded:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    return {"type": "http.disconnect"}  # the app stops reading; we answer below
            return message

        async def guarded_send(message) -> None:
            nonlocal started
            if exceeded and not started:
                return  # whatever the app makes of the cut-off body, the answer is 413
            started = True
            await send_with_headers(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            if not exceeded:
                raise
        if exceeded and not started:
            await _too_large(send_with_headers)


async def _too_large(send) -> None:
    body = json.dumps({"detail": too_large_message()}).encode()
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                            (b"connection", b"close")]})
    await send({"type": "http.response.body", "body": body})


def redact_ids(text: str) -> str:
    """Session ids are the key to a (paid) document: log only enough to tell them apart."""
    return _UUID.sub(lambda m: m[0][:8] + "…", text)


class RedactSessionIds(logging.Filter):
    """For uvicorn's access log, whose lines carry the request path and query string."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(redact_ids(a) if isinstance(a, str) else a for a in record.args)
        elif isinstance(record.msg, str):
            record.msg = redact_ids(record.msg)
        return True


def install_log_redaction() -> None:
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactSessionIds) for f in access.filters):
        access.addFilter(RedactSessionIds())
