#!/usr/bin/env python3
import base64
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_URL = os.environ.get("STALWART_BASE_URL", "https://example.com").rstrip("/")
ADMIN_EMAIL = os.environ.get("STALWART_ADMIN_EMAIL", "")
ADMIN_PASSWORD = os.environ.get("STALWART_ADMIN_PASSWORD", "")
DOMAIN = os.environ.get("MAIL_DOMAIN", "example.com").lower()
API_KEY = os.environ.get("MAIL_API_KEY", "")
HOST = os.environ.get("MAIL_API_HOST", "127.0.0.1")
PORT = int(os.environ.get("MAIL_API_PORT", "8765"))

TOKEN_CACHE = {}
DOMAIN_ID_CACHE = None
EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


class ApiError(Exception):
    def __init__(self, status, message, detail=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.detail = detail


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def http_json(url, method="GET", headers=None, body=None):
    headers = dict(headers or {})
    data = None
    if body is not None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        elif isinstance(body, str):
            data = body.encode("utf-8")
        else:
            data = body

    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            detail = json.loads(raw)
        except Exception:
            detail = raw
        raise ApiError(exc.code, "Upstream request failed", detail)
    except Exception as exc:
        raise ApiError(502, "Upstream request failed", str(exc))


def get_token(email, password):
    key = (email, password)
    cached = TOKEN_CACHE.get(key)
    if cached and cached["expires_at"] > time.time() + 60:
        return cached["access_token"]

    verifier = b64url(os.urandom(48))
    challenge = b64url(hashlib.sha256(verifier.encode()).digest())
    redirect_uri = BASE_URL + "/oauth/callback"
    auth = http_json(
        BASE_URL + "/api/auth",
        method="POST",
        headers={"Accept": "application/json"},
        body={
            "type": "authCode",
            "accountName": email,
            "accountSecret": password,
            "clientId": "stalwart-webui",
            "redirectUri": redirect_uri,
            "codeChallenge": challenge,
            "codeChallengeMethod": "S256",
        },
    )
    if not auth or auth.get("type") != "authenticated" or not auth.get("client_code"):
        raise ApiError(401, "Stalwart authentication failed", auth)

    form = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": auth["client_code"],
            "code_verifier": verifier,
            "client_id": "stalwart-webui",
            "redirect_uri": redirect_uri,
        }
    )
    token = http_json(
        BASE_URL + "/auth/token",
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=form,
    )
    access = token.get("access_token") if token else None
    if not access:
        raise ApiError(401, "Could not obtain access token", token)

    TOKEN_CACHE[key] = {
        "access_token": access,
        "expires_at": time.time() + int(token.get("expires_in", 3600)),
    }
    return access


def session_for(access):
    sess = http_json(BASE_URL + "/jmap/session", headers={"Authorization": "Bearer " + access})
    primary = sess.get("primaryAccounts") or {}
    account_id = primary.get("urn:stalwart:jmap") or primary.get("urn:ietf:params:jmap:core")
    if not account_id:
        accounts = sess.get("accounts") or {}
        account_id = next(iter(accounts.keys()), None)
    if not account_id:
        raise ApiError(500, "No JMAP account available", sess)

    api_url = sess.get("apiUrl") or "/jmap/"
    if not api_url.startswith("http"):
        api_url = BASE_URL + api_url
    return account_id, api_url


def jmap(access, calls):
    account_id, api_url = session_for(access)
    patched = []
    for idx, call in enumerate(calls):
        name, args, cid = call
        args = dict(args or {})
        args.setdefault("accountId", account_id)
        patched.append([name, args, cid if cid is not None else str(idx)])

    return http_json(
        api_url,
        method="POST",
        headers={"Authorization": "Bearer " + access, "Content-Type": "application/json"},
        body={
            "using": [
                "urn:ietf:params:jmap:core",
                "urn:stalwart:jmap",
                "urn:ietf:params:jmap:mail",
                "urn:ietf:params:jmap:submission",
            ],
            "methodCalls": patched,
        },
    )


def admin_access():
    if not ADMIN_EMAIL or not ADMIN_PASSWORD:
        raise ApiError(500, "Stalwart admin credentials are not configured")
    return get_token(ADMIN_EMAIL, ADMIN_PASSWORD)


def get_domain_id():
    global DOMAIN_ID_CACHE
    if DOMAIN_ID_CACHE:
        return DOMAIN_ID_CACHE

    access = admin_access()
    res = jmap(
        access,
        [
            ["x:Domain/query", {"filter": {"name": DOMAIN}}, "0"],
            [
                "x:Domain/get",
                {"#ids": {"resultOf": "0", "name": "x:Domain/query", "path": "/ids"}},
                "1",
            ],
        ],
    )
    domain = res["methodResponses"][1][1].get("list", [])
    if not domain:
        raise ApiError(500, "Mail domain not found in Stalwart", {"domain": DOMAIN})
    DOMAIN_ID_CACHE = domain[0]["id"]
    return DOMAIN_ID_CACHE


def normalize_email(email):
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise ApiError(400, "Invalid email address")
    if email.split("@", 1)[1] != DOMAIN:
        raise ApiError(400, "Email domain is not allowed", {"allowedDomain": DOMAIN})
    return email


def create_account(payload):
    email = normalize_email(payload.get("email"))
    password = payload.get("password") or ""
    if len(password) < 12:
        raise ApiError(400, "Password must be at least 12 characters")

    local = email.split("@", 1)[0]
    access = admin_access()
    account = {
        "@type": "User",
        "name": local,
        "domainId": get_domain_id(),
        "credentials": {
            "0": {
                "@type": "Password",
                "secret": password,
                "expiresAt": None,
                "allowedIps": {},
            }
        },
        "memberGroupIds": {},
        "memberTenantId": None,
        "roles": {"@type": "User"},
        "permissions": {"@type": "Inherit"},
        "quotas": {},
        "aliases": {},
        "description": payload.get("name"),
        "locale": payload.get("locale") or "en_US",
        "timeZone": payload.get("timeZone"),
        "encryptionAtRest": {"@type": "Disabled"},
    }
    res = jmap(access, [["x:Account/set", {"create": {"account": account}}, "0"]])
    out = res["methodResponses"][0][1]
    if out.get("notCreated"):
        err = out["notCreated"].get("account") or {}
        raise ApiError(400, err.get("description", "Could not create account"), err)

    created = out.get("created", {}).get("account")
    if not created:
        raise ApiError(500, "Could not create account", out)
    return {"success": True, "email": email, "id": created["id"]}


def login_user(email, password):
    email = normalize_email(email)
    if not password:
        raise ApiError(400, "Password is required")
    access = get_token(email, password)
    session_for(access)
    return access


def list_messages(email, password, page, page_size):
    access = login_user(email, password)
    position = max(page - 1, 0) * page_size
    res = jmap(
        access,
        [
            [
                "Email/query",
                {
                    "filter": {},
                    "sort": [{"property": "receivedAt", "isAscending": False}],
                    "position": position,
                    "limit": page_size,
                },
                "q",
            ],
            [
                "Email/get",
                {
                    "#ids": {"resultOf": "q", "name": "Email/query", "path": "/ids"},
                    "properties": [
                        "id",
                        "threadId",
                        "mailboxIds",
                        "keywords",
                        "from",
                        "to",
                        "cc",
                        "bcc",
                        "replyTo",
                        "subject",
                        "receivedAt",
                        "sentAt",
                        "size",
                        "preview",
                    ],
                },
                "g",
            ],
        ],
    )
    query_resp = None
    get_resp = None
    for name, data, cid in res.get("methodResponses", []):
        if name == "Email/query":
            query_resp = data
        if name == "Email/get":
            get_resp = data
    if query_resp is None or get_resp is None:
        raise ApiError(500, "Could not query messages", res)

    return {
        "success": True,
        "email": email,
        "page": page,
        "pageSize": page_size,
        "total": query_resp.get("total"),
        "position": query_resp.get("position"),
        "messages": get_resp.get("list", []),
    }


def forward_message(email, password, message_id, to_list, comment=""):
    if not message_id:
        raise ApiError(400, "messageId is required")
    access = login_user(email, password)
    if isinstance(to_list, str):
        to_list = [to_list]
    if not isinstance(to_list, list) or not to_list:
        raise ApiError(400, "to must be a non-empty email or email list")

    recipients = []
    for addr in to_list:
        addr = (addr or "").strip()
        if not EMAIL_RE.match(addr):
            raise ApiError(400, "Invalid recipient email", {"email": addr})
        recipients.append({"email": addr})

    msg = jmap(
        access,
        [
            [
                "Email/get",
                {
                    "ids": [message_id],
                    "properties": [
                        "id",
                        "from",
                        "to",
                        "subject",
                        "textBody",
                        "htmlBody",
                        "bodyValues",
                    ],
                },
                "0",
            ]
        ],
    )
    messages = msg["methodResponses"][0][1].get("list", [])
    if not messages:
        raise ApiError(404, "Message not found")

    original = messages[0]
    subject = original.get("subject") or ""
    if not subject.lower().startswith("fwd:"):
        subject = "Fwd: " + subject

    text = comment.strip() + "\n\n" if comment else ""
    text += "---------- Forwarded message ----------\n"
    if original.get("from"):
        text += "From: " + ", ".join([item.get("email", "") for item in original["from"]]) + "\n"
    text += "Subject: " + (original.get("subject") or "") + "\n\n"

    body_values = original.get("bodyValues") or {}
    body_part = None
    for part in original.get("textBody") or []:
        if part.get("partId") in body_values:
            body_part = body_values[part["partId"]].get("value")
            break
    if not body_part:
        for part in original.get("htmlBody") or []:
            if part.get("partId") in body_values:
                body_part = body_values[part["partId"]].get("value")
                break
    text += body_part or ""

    create_email = {
        "mailboxIds": {},
        "keywords": {"$draft": True},
        "from": [{"email": email}],
        "to": recipients,
        "subject": subject,
        "bodyValues": {"text": {"value": text, "charset": "utf-8"}},
        "textBody": [{"partId": "text", "type": "text/plain"}],
    }
    res = jmap(
        access,
        [
            ["Email/set", {"create": {"draft": create_email}}, "0"],
            [
                "EmailSubmission/set",
                {
                    "create": {
                        "send": {
                            "emailId": "#draft",
                            "identityId": None,
                            "envelope": None,
                        }
                    },
                    "onSuccessDestroyEmail": ["#send.emailId"],
                },
                "1",
            ],
        ],
    )
    return {
        "success": True,
        "email": email,
        "messageId": message_id,
        "forwardedTo": to_list,
        "upstream": res,
    }


DOC_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Stalwart Mail API</title>
  <style>
    body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;max-width:980px;margin:40px auto;padding:0 20px;line-height:1.6;color:#111}
    pre{background:#f6f8fa;padding:16px;border-radius:8px;overflow:auto}
    code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
    .badge{display:inline-block;background:#111;color:#fff;border-radius:6px;padding:2px 8px;font-size:12px}
    h2{margin-top:34px}
  </style>
</head>
<body>
  <h1>Stalwart Mail API <span class="badge">REST wrapper</span></h1>
  <p>Base URL: <code>/mail-api</code></p>
  <p>所有接口请求需要带上 <code>Authorization: Bearer &lt;MAIL_API_KEY&gt;</code>。</p>
  <h2>创建邮箱</h2>
  <pre>POST /mail-api/v1/accounts
Content-Type: application/json
Authorization: Bearer &lt;key&gt;

{
  "email": "test@example.com",
  "password": "River-Cedar-Quartz-7291!",
  "name": "Test User"
}</pre>
  <h2>分页获取邮件</h2>
  <pre>POST /mail-api/v1/messages/search
Content-Type: application/json
Authorization: Bearer &lt;key&gt;

{
  "email": "test@example.com",
  "password": "River-Cedar-Quartz-7291!",
  "page": 1,
  "pageSize": 20
}</pre>
  <h2>转发邮件</h2>
  <pre>POST /mail-api/v1/messages/forward
Content-Type: application/json
Authorization: Bearer &lt;key&gt;

{
  "email": "test@example.com",
  "password": "River-Cedar-Quartz-7291!",
  "messageId": "message-id-from-list",
  "to": "target@example.com",
  "comment": "Please check this email."
}</pre>
  <h2>健康检查</h2>
  <pre>GET /mail-api/health</pre>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "StalwartMailAPI/1.0"

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))

    def send_json(self, status, obj):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_html(self, html):
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > 1024 * 1024:
            raise ApiError(413, "Request body too large")
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            return json.loads(raw or "{}")
        except Exception:
            raise ApiError(400, "Invalid JSON body")

    def require_auth(self):
        if not API_KEY:
            raise ApiError(500, "MAIL_API_KEY is not configured")
        if self.headers.get("Authorization") != "Bearer " + API_KEY:
            raise ApiError(401, "Unauthorized")

    def handle(self):
        try:
            super().handle()
        except BrokenPipeError:
            pass

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
        try:
            if path in ["/mail-api", "/mail-api/docs"]:
                self.send_html(DOC_HTML)
                return
            if path == "/mail-api/health":
                self.send_json(200, {"success": True, "service": "stalwart-mail-api", "domain": DOMAIN})
                return
            self.send_json(404, {"success": False, "error": "Not found"})
        except ApiError as exc:
            self.send_json(exc.status, {"success": False, "error": exc.message, "detail": exc.detail})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path.rstrip("/")
        try:
            self.require_auth()
            body = self.read_body()
            if path == "/mail-api/v1/accounts":
                self.send_json(200, create_account(body))
                return
            if path == "/mail-api/v1/messages/search":
                page = max(int(body.get("page") or 1), 1)
                page_size = min(max(int(body.get("pageSize") or 20), 1), 100)
                self.send_json(200, list_messages(body.get("email"), body.get("password"), page, page_size))
                return
            if path == "/mail-api/v1/messages/forward":
                self.send_json(
                    200,
                    forward_message(
                        body.get("email"),
                        body.get("password"),
                        body.get("messageId"),
                        body.get("to"),
                        body.get("comment") or "",
                    ),
                )
                return
            self.send_json(404, {"success": False, "error": "Not found"})
        except ApiError as exc:
            self.send_json(exc.status, {"success": False, "error": exc.message, "detail": exc.detail})
        except Exception as exc:
            self.send_json(500, {"success": False, "error": "Internal server error", "detail": str(exc)})


if __name__ == "__main__":
    print("Starting stalwart-mail-api on %s:%s for %s" % (HOST, PORT, DOMAIN))
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
