# yuanbao-github-skill

元宝（Yuanbao）的 GitHub Skill：连接你的 GitHub 账号，在对话里直接查仓库、读代码、管 issue / PR、搜索项目、上传文件并自动提交。

## 能力

- **看仓库与代码**：仓库信息、README、文件树、任意文件内容、分支与提交历史
- **issue 与 PR**：列表 / 详情 / diff / 提 issue / 评论 / 关闭 / 开 PR / 合并
- **搜索与发现**：搜仓库、搜代码、搜 issue / PR、搜用户，支持语言、星数、时间过滤
- **写操作与自动化**：建仓库、上传或修改文件、多文件一次提交、新建分支、查看 Actions 运行状态

## 安装

把整个目录放到 skill 目录下即可：

```
<skill 目录>/github/
├── SKILL.md          # 技能说明：登录流程、命令速查、使用铁律
└── scripts/
    ├── gh.py         # 统一 CLI 入口
    └── ghlib.py      # REST 客户端与凭证存储
```

依赖：Python 3.8+，仅用标准库，无需 pip 安装。

## 登录

写操作与私有仓库需要登录。两种登录方式：

```bash
python3 scripts/gh.py auth login --token <PAT>   # Personal Access Token
python3 scripts/gh.py auth login                 # Device Flow（需 GITHUB_CLIENT_ID）
python3 scripts/gh.py auth status                # 查看登录态与剩余配额
```

生成 PAT：<https://github.com/settings/tokens> → Generate new token (classic)，勾选 `repo`、`workflow`、`read:org`。

凭证保存在 `~/.config/github-skill/credentials.json`，文件权限 600。

## 用法

```bash
# 查仓库
python3 scripts/gh.py repo get octocat Hello-World
python3 scripts/gh.py repo readme owner repo --max-bytes 6000

# 搜索（--md 输出 Markdown 表格）
python3 scripts/gh.py search repos "llm agent" --min-stars 20000 --limit 10 --md

# 上传文件
python3 scripts/gh.py file put owner repo README.md --file ./README.md --message "update"

# 多文件一次提交（本地路径:仓库内路径）
python3 scripts/gh.py commit push owner repo --files a.py:src/a.py --message "feat: ..."

# issue / PR
python3 scripts/gh.py issue list owner repo --state open --md
python3 scripts/gh.py pr diff owner repo 42 --max-bytes 20000
```

完整命令见 `SKILL.md` 的命令速查表。

## 说明

写操作（建/删仓库、上传、提交、开 PR、合并等）会真实改动远端，执行前需确认。
