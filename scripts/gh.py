#!/usr/bin/env python3
"""GitHub Skill 统一 CLI。

用法：
  python3 scripts/gh.py <group> <action> [参数]

group: auth / repo / file / commit / issue / pr / search / run
全局参数：--md(表格) --limit N --max-bytes N
"""
import argparse
import base64
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ghlib as G

DEFAULT_BRANCH_CACHE = {}


def j(data):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def md(rows, cols):
    if not rows:
        print("(空)")
        return
    head = "| " + " | ".join(c[0] for c in cols) + " |"
    sep = "|" + "|".join(["---"] * len(cols)) + "|"
    lines = [head, sep]
    for r in rows:
        cells = []
        for _, key in cols:
            v = key(r) if callable(key) else r.get(key)
            v = "" if v is None else str(v)
            v = v.replace("\n", " ").replace("|", "\\|")
            cells.append(v[:120])
        lines.append("| " + " | ".join(cells) + " |")
    print("\n".join(lines))


def emit(data, as_md, md_cols=None):
    if as_md and md_cols and isinstance(data, list):
        md(data, md_cols)
    else:
        j(data)


def default_branch(owner, repo, token, ref=None):
    if ref:
        return ref
    key = "%s/%s" % (owner, repo)
    if key in DEFAULT_BRANCH_CACHE:
        return DEFAULT_BRANCH_CACHE[key]
    d, _ = G.api("GET", "/repos/%s/%s" % (owner, repo), token=token, allow_404=True)
    br = (d or {}).get("default_branch", "main")
    DEFAULT_BRANCH_CACHE[key] = br
    return br


# ==========================================================================
def cmd_auth(a):
    if a.action == "login":
        if a.token:
            user, _ = G.api("GET", "/user", token=a.token, allow_404=True)
            if not user:
                sys.stderr.write("ERR: 该令牌无法读取 /user，请检查令牌是否有效。\n")
                sys.exit(3)
            scopes = G.get_scopes(a.token)
            G.save_cred({
                "access_token": a.token,
                "token_type": "bearer",
                "scope": scopes,
                "login_method": "pat",
                "saved_at": G.time.strftime("%Y-%m-%d %H:%M:%S"),
            })
            j({"ok": True, "login": user.get("login"), "name": user.get("name"),
               "scope": scopes, "method": "pat", "token_shown": G.mask(a.token)})
        else:
            j(G.device_login(client_id=a.client_id, scope=a.scope))
        return

    if a.action == "status":
        cred = G.load_cred()
        token = G.get_token()
        if not token:
            j({"authenticated": False, "hint": "运行 `auth login` 登录"})
            return
        user, _ = G.api("GET", "/user", token=token, allow_404=True)
        rl, _ = G.api("GET", "/rate_limit", token=token, allow_404=True)
        core = ((rl or {}).get("resources") or {}).get("core", {})
        j({
            "authenticated": bool(user),
            "login": (user or {}).get("login"),
            "name": (user or {}).get("name"),
            "method": cred.get("login_method", "env"),
            "scope": cred.get("scope", ""),
            "token": G.mask(token),
            "rate_limit": {"remaining": core.get("remaining"), "limit": core.get("limit")},
        })
        return

    if a.action == "whoami":
        token = G.get_token(required=True)
        user, _ = G.api("GET", "/user", token=token)
        j({k: user.get(k) for k in ("login", "name", "html_url", "public_repos", "type",
                                    "private_repos", "created_at")})
        return

    if a.action == "logout":
        G.clear_cred()
        j({"ok": True, "cleared": True})
        return


# ==========================================================================
def cmd_repo(a):
    token = G.get_token()
    if a.action == "get":
        d, _ = G.api("GET", "/repos/%s/%s" % (a.owner, a.name), token=token)
        j({k: d.get(k) for k in (
            "full_name", "description", "html_url", "default_branch", "language",
            "stargazers_count", "forks_count", "open_issues_count", "visibility",
            "private", "size", "topics", "license", "pushed_at", "created_at", "archived")})
        return

    if a.action == "list":
        path = "/users/%s/repos" % a.user if a.user else "/user/repos"
        params = {"sort": a.sort, "per_page": min(a.limit, 100)}
        if not a.user:
            params["type"] = a.type
        rows = G.paged_get(path, token=token, params=params,
                           max_pages=max(1, a.limit // 100 + 1))
        rows = rows[: a.limit]
        emit(rows, a.md, [("仓库", "full_name"), ("语言", "language"),
                          ("星", "stargazers_count"), ("私有", "private"),
                          ("更新", "pushed_at"),
                          ("说明", lambda r: (r.get("description") or "")[:60])])
        return

    if a.action == "create":
        body = {"name": a.name, "private": a.private, "auto_init": a.auto_init}
        for k, v in (("description", a.description), ("homepage", a.homepage)):
            if v:
                body[k] = v
        if a.gitignore:
            body["gitignore_template"] = a.gitignore
        if a.license:
            body["license_template"] = a.license
        path = "/orgs/%s/repos" % a.org if a.org else "/user/repos"
        d, _ = G.api("POST", path, token=token, body=body)
        j({"ok": True, "full_name": d.get("full_name"), "html_url": d.get("html_url"),
           "private": d.get("private"), "default_branch": d.get("default_branch"),
           "clone_url": d.get("clone_url")})
        return

    if a.action == "delete":
        G.api("DELETE", "/repos/%s/%s" % (a.owner, a.name), token=token)
        j({"ok": True, "deleted": "%s/%s" % (a.owner, a.name)})
        return

    if a.action == "edit":
        body = {}
        for k in ("description", "homepage", "name"):
            v = getattr(a, k, None)
            if v is not None:
                body[k] = v
        if a.private is True:
            body["private"] = True
        elif a.public is True:
            body["private"] = False
        if not body:
            sys.stderr.write("ERR: repo edit 至少给一个待改字段（--description/--name/--homepage/--private/--public）。\n")
            sys.exit(8)
        d, _ = G.api("PATCH", "/repos/%s/%s" % (a.owner, a.name), token=token, body=body)
        j({"ok": True, "full_name": d.get("full_name"), "name": d.get("name"),
           "description": d.get("description"), "html_url": d.get("html_url"),
           "private": d.get("private")})
        return

    if a.action == "tree":
        br = default_branch(a.owner, a.name, token, a.ref)
        d, _ = G.api("GET", "/repos/%s/%s/git/trees/%s" % (a.owner, a.name, br),
                     token=token, params={"recursive": "1"})
        items = d.get("tree", [])
        if a.path:
            items = [i for i in items if i["path"].startswith(a.path)]
        items = [i for i in items if i["type"] == "blob"][: a.limit]
        emit(items, a.md, [("路径", "path"), ("大小", "size")])
        return

    if a.action == "readme":
        d, _ = G.api("GET", "/repos/%s/%s/readme" % (a.owner, a.name), token=token, allow_404=True)
        if not d:
            print("(该仓库没有 README)")
            return
        print(base64.b64decode(d["content"]).decode("utf-8", "replace")[: a.max_bytes])
        return

    if a.action == "branches":
        rows = G.paged_get("/repos/%s/%s/branches" % (a.owner, a.name), token=token,
                           params={"per_page": min(a.limit, 100)})
        emit(rows[: a.limit], a.md, [("分支", "name"),
                                     ("最新提交", lambda r: r["commit"]["sha"][:8])])
        return

    if a.action == "commits":
        rows = G.paged_get("/repos/%s/%s/commits" % (a.owner, a.name), token=token,
                           params={"per_page": min(a.limit, 100), "sha": a.ref, "path": a.path})
        emit(rows[: a.limit], a.md, [
            ("SHA", lambda r: r["sha"][:8]),
            ("作者", lambda r: ((r.get("commit") or {}).get("author") or {}).get("name", "")),
            ("时间", lambda r: ((r.get("commit") or {}).get("author") or {}).get("date", "")),
            ("说明", lambda r: ((r.get("commit") or {}).get("message") or "").split("\n")[0][:70])])
        return

    if a.action == "star":
        G.api("PUT" if a.on else "DELETE", "/user/starred/%s/%s" % (a.owner, a.name), token=token)
        j({"ok": True, "starred": a.on, "repo": "%s/%s" % (a.owner, a.name)})
        return


# ==========================================================================
def cmd_file(a):
    token = G.get_token()
    base = "/repos/%s/%s/contents" % (a.owner, a.name)

    if a.action == "get":
        d, _ = G.api("GET", "%s/%s" % (base, a.path), token=token,
                     params={"ref": a.ref}, allow_404=True)
        if not d:
            sys.stderr.write("ERR: 文件不存在：%s\n" % a.path)
            sys.exit(6)
        if isinstance(d, list):
            emit(d, a.md, [("名称", "name"), ("类型", "type"), ("大小", "size")])
            return
        content = base64.b64decode(d["content"]).decode("utf-8", "replace")
        if a.save:
            os.makedirs(os.path.dirname(os.path.abspath(a.save)) or ".", exist_ok=True)
            with open(a.save, "w", encoding="utf-8") as f:
                f.write(content)
            j({"ok": True, "saved": a.save, "bytes": len(content), "sha": d["sha"]})
        else:
            print(content[: a.max_bytes])
        return

    if a.action == "put":
        raw = G.read_local_file(a.file) if a.file else sys.stdin.buffer.read()
        b64 = G.to_b64(raw)
        br = default_branch(a.owner, a.name, token, a.ref)
        existing, _ = G.api("GET", "%s/%s" % (base, a.path), token=token,
                            params={"ref": br}, allow_404=True)
        body = {"message": a.message, "content": b64, "branch": br}
        if existing and isinstance(existing, dict) and existing.get("sha"):
            if not a.overwrite:
                sys.stderr.write(
                    "ERR: %s 已存在，加 --overwrite 覆盖，或用 commit push 做多文件提交。\n" % a.path)
                sys.exit(7)
            body["sha"] = existing["sha"]
        d, _ = G.api("PUT", "%s/%s" % (base, a.path), token=token, body=body)
        j({"ok": True, "path": d["content"]["path"], "html_url": d["content"].get("html_url"),
           "commit": d["commit"]["sha"][:8], "branch": br,
           "action": "updated" if existing else "created"})
        return

    if a.action == "delete":
        br = default_branch(a.owner, a.name, token, a.ref)
        existing, _ = G.api("GET", "%s/%s" % (base, a.path), token=token,
                            params={"ref": br}, allow_404=True)
        if not existing or not existing.get("sha"):
            sys.stderr.write("ERR: 文件不存在：%s\n" % a.path)
            sys.exit(6)
        G.api("DELETE", "%s/%s" % (base, a.path), token=token,
              body={"message": a.message, "sha": existing["sha"], "branch": br})
        j({"ok": True, "deleted": a.path, "branch": br})
        return


# ==========================================================================
def cmd_commit(a):
    token = G.get_token()
    repo_path = "/repos/%s/%s" % (a.owner, a.name)
    br = default_branch(a.owner, a.name, token, a.ref)

    ref_data, _ = G.api("GET", "%s/git/ref/heads/%s" % (repo_path, br), token=token, allow_404=True)
    if not ref_data:
        if not a.create_branch:
            sys.stderr.write("ERR: 分支 %s 不存在。加 --create-branch 从默认分支新建。\n" % br)
            sys.exit(6)
        base_br = default_branch(a.owner, a.name, token, None)
        b_ref, _ = G.api("GET", "%s/git/ref/heads/%s" % (repo_path, base_br), token=token)
        base_sha = b_ref["object"]["sha"]
    else:
        base_sha = ref_data["object"]["sha"]

    commit_data, _ = G.api("GET", "%s/git/commits/%s" % (repo_path, base_sha), token=token)
    base_tree = commit_data["tree"]["sha"]

    tree_items = []
    for spec in a.files:
        if ":" in spec and not os.path.exists(spec):
            local, remote = spec.split(":", 1)
        else:
            local, remote = spec, spec.lstrip("./")
        if a.strip_prefix and remote.startswith(a.strip_prefix):
            remote = remote[len(a.strip_prefix):]
        raw = G.read_local_file(local)
        tree_items.append({"path": remote, "mode": "100644", "type": "blob",
                           "content": raw.decode("utf-8", "replace")})

    tree_data, _ = G.api("POST", "%s/git/trees" % repo_path, token=token,
                         body={"base_tree": base_tree, "tree": tree_items})
    new_commit, _ = G.api("POST", "%s/git/commits" % repo_path, token=token,
                          body={"message": a.message, "tree": tree_data["sha"],
                                "parents": [base_sha]})
    sha = new_commit["sha"]

    if ref_data:
        G.api("PATCH", "%s/git/refs/heads/%s" % (repo_path, br), token=token, body={"sha": sha})
        ref_note = "updated"
    else:
        G.api("POST", "%s/git/refs" % repo_path, token=token,
              body={"ref": "refs/heads/%s" % br, "sha": sha})
        ref_note = "created"

    j({"ok": True, "branch": br, "ref_action": ref_note, "commit": sha[:8],
       "files": [t["path"] for t in tree_items],
       "html_url": "https://github.com/%s/%s/commit/%s" % (a.owner, a.name, sha)})


# ==========================================================================
def cmd_issue(a):
    token = G.get_token()
    base = "/repos/%s/%s/issues" % (a.owner, a.name)

    if a.action == "list":
        rows = G.paged_get(base, token=token,
                           params={"state": a.state, "labels": a.label, "creator": a.creator,
                                   "per_page": min(a.limit, 100)})
        rows = [r for r in rows if "pull_request" not in r][: a.limit]
        emit(rows, a.md, [("#", "number"), ("标题", "title"), ("状态", "state"),
                          ("作者", lambda r: (r.get("user") or {}).get("login", "")),
                          ("评论", "comments"), ("更新", "updated_at")])
        return

    if a.action == "get":
        d, _ = G.api("GET", "%s/%s" % (base, a.number), token=token, allow_404=True)
        if not d:
            sys.stderr.write("ERR: issue #%s 不存在\n" % a.number)
            sys.exit(6)
        comments, _ = G.api("GET", "%s/%s/comments" % (base, a.number), token=token,
                            params={"per_page": 100})
        j({"number": d["number"], "title": d["title"], "state": d["state"],
           "user": (d.get("user") or {}).get("login"),
           "labels": [l["name"] for l in d.get("labels", [])],
           "created_at": d["created_at"], "updated_at": d["updated_at"],
           "body": (d.get("body") or "")[: a.max_bytes],
           "comments": [{"user": (c.get("user") or {}).get("login"),
                         "created_at": c.get("created_at"),
                         "body": (c.get("body") or "")[:2000]} for c in comments]})
        return

    if a.action == "create":
        body = {"title": a.title, "body": a.body or ""}
        if a.labels:
            body["labels"] = [s.strip() for s in a.labels.split(",") if s.strip()]
        if a.assignees:
            body["assignees"] = [s.strip() for s in a.assignees.split(",") if s.strip()]
        d, _ = G.api("POST", base, token=token, body=body)
        j({"ok": True, "number": d["number"], "html_url": d["html_url"], "state": d["state"]})
        return

    if a.action == "comment":
        d, _ = G.api("POST", "%s/%s/comments" % (base, a.number), token=token, body={"body": a.body})
        j({"ok": True, "comment_url": d.get("html_url")})
        return

    if a.action == "close":
        d, _ = G.api("PATCH", "%s/%s" % (base, a.number), token=token, body={"state": a.state})
        j({"ok": True, "number": d["number"], "state": d["state"]})
        return


# ==========================================================================
def cmd_pr(a):
    token = G.get_token()
    base = "/repos/%s/%s" % (a.owner, a.name)

    if a.action == "list":
        rows = G.paged_get("%s/pulls" % base, token=token,
                           params={"state": a.state, "per_page": min(a.limit, 100)})
        emit(rows[: a.limit], a.md, [("#", "number"), ("标题", "title"), ("状态", "state"),
                                     ("作者", lambda r: (r.get("user") or {}).get("login", "")),
                                     ("分支", lambda r: "%s→%s" % (r["head"]["ref"], r["base"]["ref"])),
                                     ("更新", "updated_at")])
        return

    if a.action == "get":
        d, _ = G.api("GET", "%s/pulls/%s" % (base, a.number), token=token, allow_404=True)
        if not d:
            sys.stderr.write("ERR: PR #%s 不存在\n" % a.number)
            sys.exit(6)
        j({"number": d["number"], "title": d["title"], "state": d["state"],
           "user": (d.get("user") or {}).get("login"),
           "head": d["head"]["ref"], "base": d["base"]["ref"],
           "mergeable": d.get("mergeable"), "merged": d.get("merged"),
           "additions": d.get("additions"), "deletions": d.get("deletions"),
           "changed_files": d.get("changed_files"),
           "body": (d.get("body") or "")[: a.max_bytes], "html_url": d["html_url"]})
        return

    if a.action == "files":
        rows = G.paged_get("%s/pulls/%s/files" % (base, a.number), token=token,
                           params={"per_page": 100})
        emit(rows, a.md, [("文件", "filename"), ("状态", "status"),
                          ("+", "additions"), ("-", "deletions")])
        return

    if a.action == "diff":
        rows = G.paged_get("%s/pulls/%s/files" % (base, a.number), token=token,
                           params={"per_page": 100})
        buf = []
        for r in rows:
            buf.append("### %s (%s +%s/-%s)" % (r["filename"], r["status"],
                                                r.get("additions"), r.get("deletions")))
            if r.get("patch"):
                buf.append(r["patch"])
        print("\n".join(buf)[: a.max_bytes])
        return

    if a.action == "create":
        body = {"title": a.title, "head": a.head, "base": a.base, "body": a.body or ""}
        if a.draft:
            body["draft"] = True
        d, _ = G.api("POST", "%s/pulls" % base, token=token, body=body)
        j({"ok": True, "number": d["number"], "html_url": d["html_url"], "state": d["state"]})
        return

    if a.action == "comment":
        d, _ = G.api("POST", "/repos/%s/%s/issues/%s/comments" % (a.owner, a.name, a.number),
                     token=token, body={"body": a.body})
        j({"ok": True, "comment_url": d.get("html_url")})
        return

    if a.action == "merge":
        body = {}
        if a.title:
            body["commit_title"] = a.title
        body["merge_method"] = a.method
        d, _ = G.api("PUT", "%s/pulls/%s/merge" % (base, a.number), token=token, body=body)
        j({"ok": True, "merged": d.get("merged"), "message": d.get("message"), "sha": d.get("sha")})
        return


# ==========================================================================
def cmd_search(a):
    token = G.get_token()
    if a.action == "repos":
        q = a.query
        if a.language:
            q += " language:%s" % a.language
        if a.min_stars:
            q += " stars:>=%d" % a.min_stars
        if a.pushed_after:
            q += " pushed:>=%s" % a.pushed_after
        d, _ = G.api("GET", "/search/repositories", token=token,
                     params={"q": q, "sort": a.sort, "per_page": min(a.limit, 100)})
        emit(d.get("items", [])[: a.limit], a.md,
             [("仓库", "full_name"), ("星", "stargazers_count"), ("语言", "language"),
              ("更新", "pushed_at"), ("说明", lambda r: (r.get("description") or "")[:70])])
        return

    if a.action == "code":
        q = a.query
        if a.repo:
            q += " repo:%s" % a.repo
        if a.language:
            q += " language:%s" % a.language
        d, _ = G.api("GET", "/search/code", token=token,
                     params={"q": q, "per_page": min(a.limit, 100)})
        emit(d.get("items", [])[: a.limit], a.md,
             [("路径", "path"), ("仓库", lambda r: r["repository"]["full_name"])])
        return

    if a.action == "issues":
        q = a.query
        if a.repo:
            q += " repo:%s" % a.repo
        if a.state:
            q += " state:%s" % a.state
        if a.type:
            q += " type:%s" % a.type
        d, _ = G.api("GET", "/search/issues", token=token,
                     params={"q": q, "sort": a.sort, "per_page": min(a.limit, 100)})
        emit(d.get("items", [])[: a.limit], a.md,
             [("#", "number"), ("标题", "title"), ("状态", "state"),
              ("仓库", lambda r: r["repository_url"].split("/repos/")[-1])])
        return

    if a.action == "users":
        d, _ = G.api("GET", "/search/users", token=token,
                     params={"q": a.query, "per_page": min(a.limit, 100)})
        emit(d.get("items", [])[: a.limit], a.md, [("登录名", "login"), ("类型", "type")])
        return


# ==========================================================================
def cmd_run(a):
    token = G.get_token()
    base = "/repos/%s/%s/actions" % (a.owner, a.name)
    if a.action == "list":
        d, _ = G.api("GET", "%s/runs" % base, token=token,
                     params={"per_page": min(a.limit, 100), "branch": a.branch, "status": a.status})
        emit(d.get("workflow_runs", [])[: a.limit], a.md,
             [("ID", "id"), ("工作流", "name"), ("状态", "status"),
              ("结论", "conclusion"), ("分支", "head_branch"), ("时间", "updated_at")])
        return
    if a.action == "get":
        d, _ = G.api("GET", "%s/runs/%s" % (base, a.id), token=token)
        j({k: d.get(k) for k in ("id", "name", "status", "conclusion", "html_url",
                                 "head_branch", "created_at", "updated_at")})
        return
    if a.action == "logs":
        d, _ = G.api("GET", "%s/runs/%s/logs" % (base, a.id), token=token, raw_text=True, timeout=60)
        print(d[: a.max_bytes] if isinstance(d, str) else d)
        return


# ==========================================================================
WRITE_ACTIONS = {
    ("repo", "create"), ("repo", "delete"), ("repo", "edit"), ("repo", "star"),
    ("file", "put"), ("file", "delete"), ("commit", "push"),
    ("issue", "create"), ("issue", "comment"), ("issue", "close"),
    ("pr", "create"), ("pr", "comment"), ("pr", "merge"),
}


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--md", action="store_true", help="列表输出成 Markdown 表格")
    common.add_argument("--limit", type=int, default=30)
    common.add_argument("--max-bytes", type=int, default=20000)

    def add(parent, name, **kw):
        return parent.add_parser(name, parents=[common], **kw)

    p = argparse.ArgumentParser(prog="gh.py", description="GitHub Skill CLI", parents=[common])
    sub = p.add_subparsers(dest="group", required=True)

    s = add(sub, "auth")
    s2 = s.add_subparsers(dest="action", required=True)
    lg = add(s2, "login")
    lg.add_argument("--token")
    lg.add_argument("--client-id")
    lg.add_argument("--scope", default="repo,read:org,workflow")
    add(s2, "status")
    add(s2, "whoami")
    add(s2, "logout")

    s = add(sub, "repo")
    s2 = s.add_subparsers(dest="action", required=True)
    g = add(s2, "get"); g.add_argument("owner"); g.add_argument("name")
    g = add(s2, "list"); g.add_argument("--user"); g.add_argument("--sort", default="pushed")
    g.add_argument("--type", default="owner")
    g = add(s2, "create"); g.add_argument("name"); g.add_argument("--description")
    g.add_argument("--private", action="store_true"); g.add_argument("--auto-init", action="store_true")
    g.add_argument("--gitignore"); g.add_argument("--license"); g.add_argument("--org"); g.add_argument("--homepage")
    g = add(s2, "delete"); g.add_argument("owner"); g.add_argument("name")
    g = add(s2, "edit"); g.add_argument("owner"); g.add_argument("name")
    g.add_argument("--description"); g.add_argument("--name"); g.add_argument("--homepage")
    g.add_argument("--private", action="store_true"); g.add_argument("--public", action="store_true")
    g = add(s2, "tree"); g.add_argument("owner"); g.add_argument("name")
    g.add_argument("--path"); g.add_argument("--ref")
    g = add(s2, "readme"); g.add_argument("owner"); g.add_argument("name")
    g = add(s2, "branches"); g.add_argument("owner"); g.add_argument("name")
    g = add(s2, "commits"); g.add_argument("owner"); g.add_argument("name")
    g.add_argument("--ref"); g.add_argument("--path")
    g = add(s2, "star"); g.add_argument("owner"); g.add_argument("name")
    g.add_argument("--off", action="store_true")

    s = add(sub, "file")
    s2 = s.add_subparsers(dest="action", required=True)
    g = add(s2, "get"); g.add_argument("owner"); g.add_argument("name"); g.add_argument("path")
    g.add_argument("--ref"); g.add_argument("--save")
    g = add(s2, "put"); g.add_argument("owner"); g.add_argument("name"); g.add_argument("path")
    g.add_argument("--file"); g.add_argument("--message", required=True)
    g.add_argument("--ref"); g.add_argument("--overwrite", action="store_true")
    g = add(s2, "delete"); g.add_argument("owner"); g.add_argument("name"); g.add_argument("path")
    g.add_argument("--message", required=True); g.add_argument("--ref")

    s = add(sub, "commit")
    s2 = s.add_subparsers(dest="action", required=True)
    g = add(s2, "push"); g.add_argument("owner"); g.add_argument("name")
    g.add_argument("--files", nargs="+", required=True)
    g.add_argument("--message", required=True); g.add_argument("--ref")
    g.add_argument("--strip-prefix"); g.add_argument("--create-branch", action="store_true")

    s = add(sub, "issue")
    s2 = s.add_subparsers(dest="action", required=True)
    g = add(s2, "list"); g.add_argument("owner"); g.add_argument("name")
    g.add_argument("--state", default="open"); g.add_argument("--label"); g.add_argument("--creator")
    g = add(s2, "get"); g.add_argument("owner"); g.add_argument("name"); g.add_argument("number", type=int)
    g = add(s2, "create"); g.add_argument("owner"); g.add_argument("name"); g.add_argument("title")
    g.add_argument("--body"); g.add_argument("--labels"); g.add_argument("--assignees")
    g = add(s2, "comment"); g.add_argument("owner"); g.add_argument("name")
    g.add_argument("number", type=int); g.add_argument("--body", required=True)
    g = add(s2, "close"); g.add_argument("owner"); g.add_argument("name")
    g.add_argument("number", type=int); g.add_argument("--state", default="closed")

    s = add(sub, "pr")
    s2 = s.add_subparsers(dest="action", required=True)
    g = add(s2, "list"); g.add_argument("owner"); g.add_argument("name"); g.add_argument("--state", default="open")
    g = add(s2, "get"); g.add_argument("owner"); g.add_argument("name"); g.add_argument("number", type=int)
    g = add(s2, "files"); g.add_argument("owner"); g.add_argument("name"); g.add_argument("number", type=int)
    g = add(s2, "diff"); g.add_argument("owner"); g.add_argument("name"); g.add_argument("number", type=int)
    g = add(s2, "create"); g.add_argument("owner"); g.add_argument("name"); g.add_argument("title")
    g.add_argument("--head", required=True); g.add_argument("--base", required=True)
    g.add_argument("--body"); g.add_argument("--draft", action="store_true")
    g = add(s2, "comment"); g.add_argument("owner"); g.add_argument("name")
    g.add_argument("number", type=int); g.add_argument("--body", required=True)
    g = add(s2, "merge"); g.add_argument("owner"); g.add_argument("name")
    g.add_argument("number", type=int)
    g.add_argument("--method", default="merge", choices=["merge", "squash", "rebase"])
    g.add_argument("--title")

    s = add(sub, "search")
    s2 = s.add_subparsers(dest="action", required=True)
    g = add(s2, "repos"); g.add_argument("query"); g.add_argument("--language")
    g.add_argument("--min-stars", type=int); g.add_argument("--pushed-after")
    g.add_argument("--sort", default="stars")
    g = add(s2, "code"); g.add_argument("query"); g.add_argument("--repo"); g.add_argument("--language")
    g = add(s2, "issues"); g.add_argument("query"); g.add_argument("--repo")
    g.add_argument("--state"); g.add_argument("--type", choices=["issue", "pr"]); g.add_argument("--sort")
    g = add(s2, "users"); g.add_argument("query")

    s = add(sub, "run")
    s2 = s.add_subparsers(dest="action", required=True)
    g = add(s2, "list"); g.add_argument("owner"); g.add_argument("name")
    g.add_argument("--branch"); g.add_argument("--status")
    g = add(s2, "get"); g.add_argument("owner"); g.add_argument("name"); g.add_argument("id", type=int)
    g = add(s2, "logs"); g.add_argument("owner"); g.add_argument("name"); g.add_argument("id", type=int)

    return p


def main():
    parser = build_parser()
    a = parser.parse_args()
    if (a.group, a.action) in WRITE_ACTIONS and not G.get_token():
        sys.stderr.write(
            "ERR: 该操作需要登录。运行 `python3 scripts/gh.py auth login` 授权 GitHub 账号，"
            "或设置环境变量 GITHUB_TOKEN。\n")
        sys.exit(2)
    fn = {"auth": cmd_auth, "repo": cmd_repo, "file": cmd_file, "commit": cmd_commit,
          "issue": cmd_issue, "pr": cmd_pr, "search": cmd_search, "run": cmd_run}[a.group]
    fn(a)


if __name__ == "__main__":
    main()
