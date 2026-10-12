---
name: github
description: GitHub 账号连接与仓库操作。用于查仓库信息、读 README/目录/文件内容、看提交历史、列与管理 issue 和 PR（含 diff、评论、合并）、搜索仓库/代码/issue/用户、创建仓库（添加库）、上传或修改文件并提交、创建分支、查看 Actions 运行状态。触发词：GitHub、仓库、repo、issue、PR/pull request、提 issue、开 PR、搜代码、上传文件到 GitHub、建仓库、提交代码、Actions 流水线。命中这些需求时禁止用 web_search 或浏览器抓取网页替代。
---

# GitHub Skill

统一 CLI：`python3 /data/skills/github/scripts/gh.py <组> <动作> [参数]`
全局参数 `--md`（列表输出成 Markdown 表格）、`--limit N`、`--max-bytes N`，可写在命令任意位置。
输出默认是结构化 JSON，直接读，**禁止**用 `| grep`/`| head` 过滤或写脚本二次解析。

```bash
python3 /data/skills/github/scripts/gh.py repo get octocat Hello-World
python3 /data/skills/github/scripts/gh.py search repos "llm agent" --min-stars 20000 --limit 10 --md
python3 /data/skills/github/scripts/gh.py repo readme owner repo --max-bytes 6000
```

## 一、登录

先跑 `auth status`；`authenticated: false` 时引导用户登录。未登录只能读公开仓库（匿名限速 60 次/小时，登录 5000 次/小时）。当前已登录账号可直接用。

```bash
python3 scripts/gh.py auth status          # 是否已登录 + 剩余配额
python3 scripts/gh.py auth whoami
python3 scripts/gh.py auth login --token <PAT>   # 方式 1：令牌登录
python3 scripts/gh.py auth login                 # 方式 2：Device Flow（需 GITHUB_CLIENT_ID）
python3 scripts/gh.py auth logout
```

引导登录的话术要点（已登录就不用讲）：
1. 打开 <https://github.com/settings/tokens> → Generate new token (classic) → 勾 `repo`（私有仓库读写）、`workflow`（Actions）、`read:org`（组织仓库），复制令牌。
2. 把令牌发到对话里，由你执行 `auth login --token <PAT>`。凭证只存本地（`~/.config/github-skill/credentials.json`，权限 600），**回复里不要回显令牌原文**，只用 `auth status` 的掩码确认。
3. Device Flow（网页输设备码授权）需自备 OAuth App `client_id`：设置环境变量 `GITHUB_CLIENT_ID` 后跑 `auth login`，脚本给出验证码与验证网址。

令牌失效时命令以退出码 3 报 401/403，此时提示用户重新登录，不要凭记忆补数据。

## 二、命令速查

| 场景 | 命令 |
|---|---|
| 仓库信息 | `repo get <owner> <repo>` |
| 我的/某人仓库 | `repo list [--user <login>] --limit 30 --md` |
| 建仓库（添加库） | `repo create <name> [--description ""] [--private] [--auto-init] [--gitignore Python] [--license MIT] [--org <组织>]` |
| 删仓库 | `repo delete <owner> <repo>` |
| 改仓库信息 | `repo edit <owner> <repo> [--description ""] [--name 新名] [--homepage] [--private\|--public]` |
| 文件树 | `repo tree <owner> <repo> [--path src] [--ref <分支>] --limit 100 --md` |
| README | `repo readme <owner> <repo> --max-bytes N` |
| 分支 / 提交历史 | `repo branches`、`repo commits <owner> <repo> [--ref] [--path]` |
| 加/取消 star | `repo star <owner> <repo> [--off]` |
| 读文件 | `file get <owner> <repo> <路径> [--ref] [--save 本地路径]`（路径为目录时列出目录） |
| 上传/改单文件 | `file put <owner> <repo> <仓库内路径> --file <本地文件> --message "提交说明" [--overwrite] [--ref]` |
| 删文件 | `file delete <owner> <repo> <路径> --message ""` |
| 多文件一次提交 | `commit push <owner> <repo> --files a.py b.md --message "" [--ref 分支] [--create-branch]`；路径映射写 `本地路径:仓库内路径` |
| issue 列表/详情 | `issue list <owner> <repo> [--state open] [--label] --md`、`issue get <owner> <repo> <number>` |
| 提 issue | `issue create <owner> <repo> "<标题>" --body "" [--labels "bug,urgent"] [--assignees u1]` |
| 评论 / 关闭 | `issue comment ... <number> --body ""`、`issue close ... <number>` |
| PR 列表/详情 | `pr list`、`pr get <owner> <repo> <number>` |
| PR 改动 | `pr files ... <number> --md`、`pr diff ... <number> --max-bytes 20000` |
| 开 PR | `pr create <owner> <repo> "<标题>" --head 分支 --base main [--body] [--draft]` |
| PR 评论/合并 | `pr comment ... <number> --body ""`、`pr merge ... <number> --method merge\|squash\|rebase` |
| 搜仓库 | `search repos "<关键词>" [--language Python] [--min-stars N] [--pushed-after YYYY-MM-DD] --sort stars --md` |
| 搜代码 | `search code "<关键词>" [--repo owner/name] [--language]`（**必须登录**） |
| 搜 issue/PR | `search issues "<关键词>" [--repo owner/name] [--state open] [--type issue\|pr]` |
| 搜用户 | `search users "<关键词>"` |
| Actions | `run list <owner> <repo> [--branch] [--status] --md`、`run get ... <id>`、`run logs ... <id>` |

## 三、铁律

1. **禁止绕过**：查 GitHub 数据一律走本 CLI，禁止 `web_search`、禁止自己 curl GitHub 网页或 api.github.com。
2. **写操作先确认**：`repo create/delete`、`file put/delete`、`commit push`、`pr create/merge`、`issue close` 会真实改动远端，**执行前必须说清要改什么并等用户点头**；只读命令可直接跑。
3. **未知对象先查再写**：不确定仓库/分支是否存在，先 `repo get` / `repo branches`；`file put` 遇到已存在文件默认拒绝，需显式 `--overwrite`，或改用 `commit push`。
4. **路径与分支**：`--ref` 省略时用仓库默认分支；推到不存在的分支会报错，要新建分支加 `--create-branch`。`commit push` 的仓库内路径默认等于本地路径，用 `本地路径:仓库内路径` 或 `--strip-prefix` 调整。
5. **大内容控量**：读文件、diff、README 一律带 `--max-bytes`（默认 20000）；`--limit` 控制列表长度，默认 30。
6. **不编造**：报错按信息处理（401/403→重新登录；404→对象不存在或无权访问；422→参数/校验问题），不凭记忆补数据。
7. **正文里不输出令牌原文、凭证路径等内部信息**，只说"已登录为 xxx"这类用户可见结论。
