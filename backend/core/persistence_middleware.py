"""Honest per-request persistence acknowledgments, without claiming rollback."""
import json
from core.gcs_sync import begin_request_persistence, end_request_persistence


class PersistenceAcknowledgementMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token, events = begin_request_persistence()
        replacement_body = None
        replacement_sent = False

        async def persistence_send(message):
            nonlocal replacement_body, replacement_sent
            if message["type"] == "http.response.start" and events:
                states = [event["state"] for event in events]
                failure = any(state in {"conflict", "untracked", "unavailable", "error"} for state in states)
                pending = "pending" in states
                label = "failed" if failure else "pending" if pending else "durable" if all(state == "synced" for state in states) else "unknown"
                headers = [(key, value) for key, value in message.get("headers", []) if key.lower() != b"x-mfi-persistence"]
                headers.append((b"x-mfi-persistence", label.encode()))
                message = {**message, "headers": headers}
                if 200 <= message["status"] < 400:
                    if failure:
                        replacement_body = json.dumps({"detail": "Persistence was not confirmed. Changes may exist locally; no rollback is implied. Reconcile state before retrying.", "persistence": "failed", "changes_may_exist_locally": True}).encode()
                        message["status"] = 503
                        message["headers"] = [(key, value) for key, value in headers if key.lower() not in {b"content-type", b"content-length", b"content-encoding", b"etag", b"location"}]
                        message["headers"].extend([(b"content-type", b"application/json"), (b"content-length", str(len(replacement_body)).encode()), (b"cache-control", b"no-store")])
                    elif pending:
                        message["status"] = 202
            elif message["type"] == "http.response.body" and replacement_body is not None:
                if not replacement_sent:
                    await send({"type": "http.response.body", "body": replacement_body, "more_body": False})
                    replacement_sent = True
                return
            await send(message)

        try:
            await self.app(scope, receive, persistence_send)
        finally:
            end_request_persistence(token)
