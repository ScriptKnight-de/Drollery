"""The upload progress bar sends its form with a script (so it can count the bytes). A script cannot see a redirect, it
just follows it, which would use up the one-time message that goes with it. So when the page asks for it (header
`X-Drollery-Upload`), a redirect is answered as a small JSON note, {"redirect": "<where to go>"}, with the same cookies,
and the script goes there itself. Everything else passes through untouched."""
from __future__ import annotations

import json

REQUEST_HEADER = b"x-drollery-upload"
REDIRECTS = {301, 302, 303, 307, 308}


class UploadRedirects:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not any(k == REQUEST_HEADER for k, _ in scope.get("headers", [])):
            await self.app(scope, receive, send)
            return
        held = {"location": None, "cookies": []}

        async def wrapped(message):
            if message["type"] == "http.response.start" and message["status"] in REDIRECTS:
                headers = message.get("headers", [])
                held["location"] = next((v for k, v in headers if k.lower() == b"location"), None)
                held["cookies"] = [(k, v) for k, v in headers if k.lower() == b"set-cookie"]
                if held["location"] is not None:
                    body = json.dumps({"redirect": held["location"].decode("latin-1")}).encode()
                    await send({"type": "http.response.start", "status": 200,
                                "headers": [(b"content-type", b"application/json"), (b"cache-control", b"no-store"),
                                            (b"content-length", str(len(body)).encode()), *held["cookies"]]})
                    held["body"] = body
                    return
            if held["location"] is not None:
                if message["type"] == "http.response.body":
                    await send({"type": "http.response.body", "body": held.pop("body", b""), "more_body": False})
                    held["location"] = None
                return                                   # the redirect's own (empty) body is dropped
            await send(message)

        await self.app(scope, receive, wrapped)
