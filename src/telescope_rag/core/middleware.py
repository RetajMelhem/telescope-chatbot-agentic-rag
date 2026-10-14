"""Bounded ASGI request handling and non-content telemetry."""

import asyncio
import logging
from time import perf_counter
from uuid import uuid4

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from telescope_rag.core.errors import ApplicationError, error_payload


class RequestBoundaryMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        max_body_bytes: int,
        timeout_seconds: float,
        cors_allowed_origins: tuple[str, ...],
        logger: logging.Logger,
    ) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.timeout_seconds = timeout_seconds
        self.cors_allowed_origins = cors_allowed_origins
        self.logger = logger

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        started_at = perf_counter()
        status_code = 500
        response_started = False

        async def tracked_send(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != b"x-request-id"
                ]
                message = {
                    **message,
                    "headers": [*headers, (b"x-request-id", request_id.encode("ascii"))],
                }
            await send(message)

        async def fail(code: int, reason: str, message: str) -> None:
            if not response_started:
                response = JSONResponse(
                    error_payload(request_id, reason, message), status_code=code
                )
                # These failures occur outside the inner CORS middleware. Keep them
                # readable by allowed origins without granting any new origin access.
                origin = Headers(scope=scope).get("origin")
                if origin in self.cors_allowed_origins:
                    response.headers["Access-Control-Allow-Origin"] = origin
                    response.headers["Access-Control-Expose-Headers"] = "X-Request-ID"
                    response.headers.add_vary_header("Origin")
                await response(scope, receive, tracked_send)

        try:
            async with asyncio.timeout(self.timeout_seconds):
                self._check_declared_length(scope)
                body = bytearray()
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        status_code = 499
                        return
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > self.max_body_bytes:
                        raise ApplicationError(
                            413, "request_too_large", "Request body is too large."
                        )
                    body.extend(chunk)
                    if not message.get("more_body", False):
                        break

                consumed = False

                async def replay() -> Message:
                    nonlocal consumed
                    if not consumed:
                        consumed = True
                        return {"type": "http.request", "body": bytes(body), "more_body": False}
                    return await receive()

                await self.app(scope, replay, tracked_send)
        except ApplicationError as error:
            await fail(error.status_code, error.code, error.safe_message)
        except TimeoutError:
            await fail(504, "request_timeout", "The request could not finish within its deadline.")
        except Exception:
            # Never include the exception text or traceback: it can contain user/provider content.
            await fail(500, "internal_error", "The request could not be completed.")
        finally:
            route = scope.get("route")
            self.logger.info(
                "request_completed",
                extra={
                    "request_id": request_id,
                    "route": getattr(route, "path", "/unmatched"),
                    "status_code": status_code,
                    "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                },
            )

    def _check_declared_length(self, scope: Scope) -> None:
        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                try:
                    size = int(value)
                except ValueError:
                    raise ApplicationError(
                        422, "invalid_request", "The request headers are invalid."
                    ) from None
                if size < 0:
                    raise ApplicationError(
                        422, "invalid_request", "The request headers are invalid."
                    )
                if size > self.max_body_bytes:
                    raise ApplicationError(413, "request_too_large", "Request body is too large.")
