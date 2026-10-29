"""Local pairing, host/origin validation, and process-scoped API sessions."""
import hmac
import ipaddress
import json
import logging
import time
import uuid
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse
from backend.config import settings
from shared.version import VERSION

COOKIE = 'prism_session'
LOCAL_HOSTS = {'127.0.0.1', 'localhost', '::1'}
logger = logging.getLogger('prism.requests')


def matches(value: str) -> bool:
    return bool(value and value.isascii() and hmac.compare_digest(value, settings.API_SESSION_TOKEN))


def authenticated(request: Request) -> bool:
    authorization = request.headers.get('authorization', '')
    return matches(authorization.removeprefix('Bearer ')) if authorization.startswith('Bearer ') else matches(request.cookies.get(COOKIE, ''))


def allowed_origin(origin: str, host: str) -> bool:
    # Development is deliberately same-host: cookies do not cross localhost /
    # 127.0.0.1. Never trust an arbitrary configured external CORS origin.
    try:
        parsed = urlsplit(origin)
        return (parsed.scheme == 'http' and parsed.hostname == host and
                parsed.port in ({settings.PORT, 5173} if settings.DEV_FRONTEND else {settings.PORT}) and not parsed.username and
                not parsed.password and parsed.path in {'', '/'} and not parsed.query and not parsed.fragment)
    except ValueError:
        return False


def denied(code: str, message: str, status: int):
    return JSONResponse({'error': {'code': code, 'message': message, 'retryable': False}}, status_code=status)


class LocalSessionMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        request = Request(scope)
        try:
            authority = urlsplit('http://' + request.headers.get('host', ''))
            host = authority.hostname
            valid_host = (len(request.headers.getlist('host')) == 1 and host in LOCAL_HOSTS
                          and authority.port == settings.PORT and not authority.username and not authority.password
                          and not authority.path and not authority.query and not authority.fragment)
        except ValueError:
            valid_host = False
            host = None
        response = None
        if not valid_host:
            response = denied('INVALID_HOST', 'Use the configured loopback address and port.', 400)
        elif (origin := request.headers.get('origin')) and not allowed_origin(origin, host):
            response = denied('INVALID_ORIGIN', 'This browser origin is not allowed.', 403)
        elif request.headers.get('sec-fetch-site') == 'cross-site':
            response = denied('INVALID_ORIGIN', 'Cross-site requests are not allowed.', 403)
        elif not authenticated(request) and not (request.method == 'GET' and request.url.path == '/') and request.url.path != '/api/session':
            response = denied('UNAUTHORIZED', 'Open Prism through the local launcher to pair this browser.', 401)
        # A cookie mutation must carry a trusted browser Origin. Native clients
        # use Bearer authentication; Origin alone never authenticates a client.
        elif request.method not in {'GET', 'HEAD', 'OPTIONS'} and not request.headers.get('authorization', '').startswith('Bearer ') and not origin:
            response = denied('INVALID_ORIGIN', 'A trusted browser Origin is required.', 403)
        request_id = uuid.uuid4().hex
        started = time.monotonic()

        async def secure_send(message):
            if message['type'] == 'http.response.start':
                headers = list(message.get('headers', []))
                headers += [(b'cache-control', b'no-store'), (b'x-content-type-options', b'nosniff'),
                            (b'referrer-policy', b'no-referrer'), (b'x-frame-options', b'DENY'),
                            (b'x-request-id', request_id.encode())]
                if not any(key.lower() == b'content-security-policy' for key, _ in headers):
                    # Untrusted model Markdown must not auto-load remote images
                    # or media containing captured text in a tracking URL.
                    headers.append((b'content-security-policy', b"img-src 'self' data: blob:; media-src 'self' data: blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"))
                message['headers'] = headers
                logger.info(json.dumps({'request_id': request_id, 'method': scope['method'],
                    'status': message['status'], 'duration_ms': round((time.monotonic() - started) * 1000), 'version': VERSION}))
            await send(message)
        if response:
            await response(scope, receive, secure_send)
        else:
            await self.app(scope, receive, secure_send)


def require_loopback(host: str):
    try:
        if host != 'localhost' and not ipaddress.ip_address(host).is_loopback:
            raise ValueError
    except ValueError:
        raise ValueError('Prism must listen on a loopback address.') from None
