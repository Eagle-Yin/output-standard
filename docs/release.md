# 上线清单 · 从本地提交到开源可见

> 这份清单存在的理由只有一条：**别把「本地能跑」说成「已发布」**。
> 三种状态必须分开说，混说一次就是一次事故。

## 三种状态，不许混

| 状态 | 含义 | 怎么证明 |
|---|---|---|
| 本地提交 | 只在你这台机器上，别人看不到 | `git log` 有条目，`git remote -v` 为空 |
| 已推送到远端 | 代码到了 GitHub，但别人还没找到它 | `git ls-remote` 能列出对应分支哈希 |
| 远端可见 | 有地址、有版本、别人能打开 | 浏览器打开仓库地址返回 200，Release 页在 |

**说「已发布」必须给第三种的证据**（可打开的地址）。只做到第二种，就说「已推送，仓库还没建好/没公开」。

## 发布前：五件事必须全绿

```bash
python tests/smoke.py
python tests/test_reply_hits.py
python tests/test_looks.py
python tests/test_loop.py
python tests/test_portable.py
python tests/test_second_machine.py
python tests/test_doc_truth.py
python tests/test_publish_path.py
python tests/test_publish_api.py
```

任何一套红，都不发布——发出去的是别人要读的东西，不是自己练手的。

## 发布：一条命令

需要先有令牌（见下节）。令牌只从环境变量读，不落盘、不进 shell 历史。

```bash
export GH_TOKEN=<token>
python publish.py --dry-run      # 先看：账号对不对、仓库会不会被新建
python publish.py                # 真发：建公开仓库 → 推主线 → 打标签 → 建 Release
```

脚本做四件事，每步失败都停：

1. 用令牌换账号名，令牌无效立刻退出（不会建半个仓库）。
2. 仓库不存在就建公开仓库，已存在就复用（**不覆盖**任何已有内容）。
3. 推主线：先试 `--force-with-lease`，失败退回普通 push（首次推送就是这种情况）。
4. 按 `judge/__init__.py` 的版本号打标签、建 Release。

**两条车道，脚本自己选。** 有些机器上程序拉不起 git 进程（命令行里 git 却正常），这时脚本自动改走 GitHub 的 REST 接口：把文件、树、提交、引用一步步建出来，最后回读分支头核对——核不上就判失败，不报成功。代价写在明处：这条车道只能整树快照，没有历史与合并能力，适合首次发布与纯追加；日常迭代仍走 git。

**工作流文件要额外权限。** `.github/workflows/` 下的文件（CI 配置）除了 `repo` 权限，还要令牌带 `workflow` 权限，缺它建树一律 404（实测）。缺权限时脚本跳过该文件、其余照发，并在输出里点名——不静默丢，也不把 404 当成功。要补这个文件，按路线 A 生成令牌时把 **Workflows: Read and write** 一起勾上。

**令牌安全**：只出现在一条命令的地址里，推完立刻把远端地址换回不带令牌的形式；任何输出里的令牌都替换成 `[REDACTED]`。

## 需要人做的那一件：申请令牌（照着点就行）

生成令牌等于授权某个程序代表账号写代码，是账号持有人的决定——执行者不问、不猜、不代填。三条路选一条（界面入口若挪了，在 GitHub 顶部搜索 personal access tokens 即达）：

**路线 A：细粒度令牌（推荐，权限最小、自带过期）**

1. 浏览器登录 github.com → 右上角头像 → **Settings**。
2. 左栏拉到最底 → **Developer settings**。
3. **Personal access tokens → Fine-grained tokens** → **Generate new token**。
4. **Token name** 随意（建议 output-standard-publish）；**Expiration** 选 7 天——发完即弃，不用回头清理。
5. **Resource owner** 选自己的账号；**Repository access** 选 **All repositories**（仓库由脚本新建，发令牌时它还不存在，选不了单个仓库）。
6. **Permissions → Repository permissions** 只勾两项：**Administration: Read and write**（建仓库用）、**Contents: Read and write**（推代码用）。其余一概不勾。
7. **Generate token** 后复制以 `github_pat_` 开头的一串——只显示这一次，当场复制。

**路线 B：经典令牌（最快）**

1. 同上进入 Developer settings → **Tokens (classic)** → **Generate new token (classic)**。
2. **Note** 随意、**Expiration** 选 7 天、只勾 **repo** 一项，其余不勾。
3. Generate 后复制以 `ghp_` 开头的一串。

**路线 C：设备码登录（令牌不进聊天窗口）**

1. 对执行者说一句「走设备码」。
2. 执行者起登录流程，屏幕给出一串 8 位码和网址。
3. 浏览器打开 github.com/login/device → 输码 → 点授权，结束。

**怎么交、怎么处置**：

- 令牌贴在对话里交给执行者（会留在聊天记录），所以选 7 天期；发布完当天回到第 3 步的令牌列表页，点该令牌的 **Delete/Revoke** 撤销。
- 交令牌时带一句仓库名；不说就按默认 `output-standard`——挂在你的账号下、公开仓库。

**为什么这一步只能人做**：生成 token 等于授权某个程序代表账号写代码，是账号持有人的决定。执行者不问、不猜、不代填。

## 发完之后

- 回读一次：浏览器打开仓库地址，确认 200 且能看到 README；`git ls-remote` 的哈希与本地 `rev-parse HEAD` 一致。
- 记一行到 CHANGELOG：版本、日期、一句话说清这版改了什么。
- 令牌用完即弃：如果是临时令牌，去 GitHub 撤销。

## 常见坑

| 症状 | 原因 | 处理 |
|---|---|---|
| `remote: Permission to ... denied` | 令牌权限不够或过期 | 重新生成，勾 `repo` |
| `src refspec main does not match any` | 本地分支不叫 main | 脚本自动取当前分支名，不要手改 |
| 推上去但仓库打不开 | 建的是私有仓库 | 到仓库 Settings 改 Public |
| `git` 起不来（Windows） | 某些受保护目录里的 git 只允许特定进程执行 | 换一个普通安装的 git，或用 `gh` 推送 |
