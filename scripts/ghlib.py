"""GitHub REST 客户端与凭证存储（仅标准库依赖）。"""
import base64
import json
import os
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
API_VERSION = "2022-11-28"

CONFIG_DIR = os.environ.get(
    "GITHUB_SKILL_CONFIG_DIR",
    os.path.join(os.path.expanduser("~"), ".config", "github-skill"),
)
CRED_FILE = os.path.join(CONFIG_DIR, "credentials.json")

DEFAULT_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID", "")


def _ensure_config_dir():
    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)


def load_cred():
    if not os.path.exists(CRED_FILE):
        return {}
    try:
        with open(CRED_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cred(data):
    _ensure_config_dir()
    with open(CRED_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(CRED_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def clear_cred():
    if os.path.exists(CRED_FILE):
        os.remove(CRED_FILE)


def get_token(required=False):
    token = os.environ.get("GITHUB_TOKEN") or load_cred().get("access_token") or ""
    if not token and required:
        sys.stderr.write(
            "ERR: 未登录。运行 `python3 scripts/gh.py auth login` 完成 GitHub 账号授权，"
            "或设置环境变量 GITHUB_TOKEN。\n"
        )
        sys.exit(2)
    return token


def mask(token):
    return (token[:4] + "..." + token[-4:]) if token and len(token) > 10 else "***"


def _request(method, url, token=None, body=None, accept="application/vnd.github+json",
             raw_text=False, timeout=30):
    headers = {
        "Accept": accept,
        "User-Agent": "github-skill",
        "X-GitHub-Api-Version": API_VERSION,
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
            status = resp.status
            hdrs = dict(resp.headers)
    except urllib.error.HTTPError as e:
        payload = e.read()
        status = e.code
        hdrs = dict(e.headers)
        if status in (401, 403) and token:
            detail = _safe_json(payload)
            msg = detail.get("message", "") if isinstance(detail, dict) else ""
            sys.stderr.write(
                "ERR: GitHub 返回 %s %s。常见原因：令牌过期/被撤销、权限 scope 不足、"
                "速率限制或该资源不可见。请重新 `auth login` 或确认令牌权限。\n"
                % (status, msg)
            )
            sys.exit(3)
    except urllib.error.URLError as e:
        sys.stderr.write("ERR: 网络请求失败：%s\n" % e.reason)
        sys.exit(4)

    if raw_text:
        return status, payload.decode("utf-8", "replace"), hdrs
    if status == 204 or not payload:
        return status, None, hdrs
    return status, _safe_json(payload), hdrs


def _safe_json(payload):
    try:
        return json.loads(payload.decode("utf-8", "replace"))
    except Exception:
        return payload.decode("utf-8", "replace")


def api(method, path, token=None, body=None, accept="application/vnd.github+json",
        params=None, raw_text=False, timeout=30, allow_404=False):
    url = API + path if path.startswith("/") else path
    url = urllib.parse.quote(url, safe="/:?&=%,+")
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    status, data, hdrs = _request(method, url, token, body, accept, raw_text, timeout)
    if status == 404 and allow_404:
        return None, hdrs
    if status >= 400:
        msg = data.get("message") if isinstance(data, dict) else str(data)
        sys.stderr.write("ERR: %s %s -> %s %s\n" % (method, url, status, msg))
        if isinstance(data, dict):
            sys.stderr.write(json.dumps(data, ensure_ascii=False)[:1200] + "\n")
        sys.exit(5)
    return data, hdrs


def paged_get(path, token=None, params=None, max_pages=5, per_page=100):
    p = dict(params or {})
    p.setdefault("per_page", per_page)
    out, page = [], 1
    while page <= max_pages:
        p["page"] = page
        data, _ = api("GET", path, token=token, params=p)
        if not isinstance(data, list) or not data:
            break
        out.extend(data)
        if len(data) < per_page:
            break
        page += 1
    return out


def get_scopes(token):
    req = urllib.request.Request(API + "/user", headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "User-Agent": "github-skill",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.headers.get("X-OAuth-Scopes", "")
    except Exception:
        return ""


def device_login(client_id=None, scope="repo,read:org,workflow", open_browser=True):
    cid = client_id or DEFAULT_CLIENT_ID or load_cred().get("client_id")
    if not cid:
        return {
            "ok": False,
            "reason": "no_client_id",
            "hint": (
                "Device Flow 需要一个 OAuth App 的 client_id。"
                "设置环境变量 GITHUB_CLIENT_ID 后重试，或直接用 PAT 登录："
                "`python3 scripts/gh.py auth login --token <PAT>`"
            ),
        }

    status, body, _ = _request(
        "POST", "https://github.com/login/device/code",
        body={"client_id": cid, "scope": scope}, accept="application/json",
    )
    if status != 200:
        return {"ok": False, "reason": "device_code_failed", "status": status, "raw": body}

    user_code = body.get("user_code")
    verify_url = body.get("verification_uri", "https://github.com/login/device")
    device_code = body.get("device_code")
    interval = int(body.get("interval", 5))
    expires = int(body.get("expires_in", 900))

    if open_browser:
        try:
            import webbrowser
            webbrowser.open(verify_url)
        except Exception:
            pass

    deadline = time.time() + expires
    while time.time() < deadline:
        time.sleep(interval)
        st, tok, _ = _request(
            "POST", "https://github.com/login/oauth/access_token",
            body={"client_id": cid, "device_code": device_code,
                  "grant_type": "urn:ietf:params:oauth:grant-type:device_code"},
            accept="application/json",
        )
        if st == 200 and isinstance(tok, dict):
            if tok.get("access_token"):
                save_cred({
                    "access_token": tok["access_token"],
                    "token_type": tok.get("token_type", "bearer"),
                    "scope": tok.get("scope", scope),
                    "login_method": "device_flow",
                    "client_id": cid,
                    "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                })
                return {"ok": True, "user_code": user_code, "verify_url": verify_url}
            err = tok.get("error")
            if err and err != "authorization_pending":
                return {"ok": False, "reason": err, "detail": tok.get("error_description", "")}
            if err == "slow_down":
                interval += 5
        elif st >= 400:
            return {"ok": False, "reason": "token_poll_failed", "status": st, "raw": tok}
    return {"ok": False, "reason": "expired"}


def read_local_file(path):
    with open(path, "rb") as f:
        return f.read()


def to_b64(raw_bytes):
    return base64.b64encode(raw_bytes).decode("ascii")
