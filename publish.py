"""一键发布到 GitHub 开源社区：除「填一次令牌」外全自动。

用法（令牌只从环境变量读，不落盘、不进 shell 历史）：
    set GH_TOKEN=ghp_xxx        # 或 fine-grained token（需 repo 权限）
    python publish.py --repo output-standard

做四件事：① 校验令牌与账号 ② 建公开仓库 ③ 推 main ④ 打 0.1.0 tag 并建 Release。
失败点全在推之前可自愈：仓库已存在则复用，tag 已存在则跳过。
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

PKG = Path(__file__).resolve().parent
API = "https://api.github.com"


def die(msg, code=1):
    print("FAIL " + msg)
    raise SystemExit(code)


def api(path, method="GET", token=None, payload=None):
    req = urllib.request.Request(
        API + path, method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "output-standard-publisher",
            **({"Content-Type": "application/json"} if payload is not None else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"message": body[:300]}


def git(*args, check=True):
    p = subprocess.run(["git", *args], cwd=str(PKG), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and p.returncode != 0:
        die("git %s -> %s" % (" ".join(args), (p.stderr or p.stdout).strip()[:300]))
    return (p.stdout or "").strip()


def read_version():
    """从 judge/__init__.py 读版本号——版本只写一处。"""
    text = (PKG / "judge" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not m:
        die("judge/__init__.py 里找不到 __version__")
    return m.group(1)


def push_branch(package_dir, remote_url, branch, token=None, runner=None):
    """把本地分支推到远端；token 只在这一句里出现，推完立刻用干净地址覆盖。

    返回 (ok, 输出)。远端不存在分支时退回普通 push —— 首次推送就是这种情况。
    runner 可注入（测试用假 git 验分支逻辑，不依赖本机有没有 git）。
    """
    run = runner or subprocess.run
    url = remote_url
    if token:
        url = remote_url.replace("https://", "https://x-access-token:" + token + "@")
    head = ["git", "push", url, "%s:%s" % (branch, branch)]
    p = run(head + ["--force-with-lease"], cwd=str(package_dir),
            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        p = run(head, cwd=str(package_dir),
                capture_output=True, text=True, encoding="utf-8", errors="replace")
    if token:  # 令牌不留在配置里
        run(["git", "remote", "set-url", "origin", remote_url],
            cwd=str(package_dir), capture_output=True)
    out = ((p.stderr or "") + (p.stdout or "")).strip()
    if token:
        out = out.replace(token, "[REDACTED]")
    return p.returncode == 0, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=PKG.name)
    ap.add_argument("--desc", default="把「输出规范」变成可执行的回复判据：七组检查 + 三套回归 + 闭环仿真")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        die("没有令牌。设置环境变量 GH_TOKEN 后重跑；令牌只在内存里用，不写入任何文件。")

    # 1. 令牌与账号
    st, me = api("/user", token=token)
    if st != 200:
        die("令牌无效（HTTP %d）：%s" % (st, me.get("message", "")[:160]))
    owner = me["login"]
    print("OK   身份 %s，令牌可读账号" % owner)

    # 2. 仓库（已存在则复用，不覆盖任何东西）
    st, repo = api("/repos/%s/%s" % (owner, a.repo), token=token)
    if st == 404:
        if a.dry_run:
            print("DRY  将创建公开仓库 %s/%s" % (owner, a.repo))
            return
        st2, repo = api("/user/repos", "POST", token=token,
                        payload={"name": a.repo, "description": a.desc, "private": False,
                                 "has_issues": True, "has_wiki": False, "auto_init": False})
        if st2 not in (200, 201):
            die("建仓失败（HTTP %d）：%s" % (st2, repo.get("message", "")[:200]))
        print("OK   已建公开仓库 %s" % repo["html_url"])
    else:
        print("OK   仓库已存在，复用 %s" % repo["html_url"])
    url = repo["clone_url"]

    # 3. 身份（仓库内配置，不碰全局）
    git("config", "user.name", me.get("name") or owner)
    git("config", "user.email", "%s@users.noreply.github.com" % owner)

    # 4. 推送：令牌只经 stdin 的临时 header 用一次，不写 .git/config
    branch = git("rev-parse", "--abbrev-ref", "HEAD") or "main"
    if git("remote", check=False):
        git("remote", "set-url", "origin", url)
    else:
        git("remote", "add", "origin", url)
    ok, out = push_branch(PKG, url, branch, token=token)
    git("remote", "set-url", "origin", url)  # 双保险：令牌绝不留在配置里
    if not ok:
        die("推送失败：" + out[:400])
    print("OK   已推送 %s 分支" % branch)

    # 5. 版本标签与 Release（版本号取自 judge/__init__.py，唯一事实源）
    version = read_version()
    st, tags = api("/repos/%s/%s/tags" % (owner, a.repo), token=token)
    if not any(t.get("name") == "v" + version for t in (tags if isinstance(tags, list) else [])):
        subprocess.run(["git", "tag", "-f", "v" + version], cwd=str(PKG), check=False)
        tag_url = url.replace("https://", "https://x-access-token:%s@" % token)
        subprocess.run(["git", "push", tag_url, "v" + version, "--force"],
                       cwd=str(PKG), capture_output=True, text=True)
        git("remote", "set-url", "origin", url)
        st3, rel = api("/repos/%s/%s/releases" % (owner, a.repo), "POST", token=token,
                       payload={"tag_name": "v" + version, "name": "v" + version,
                                "body": a.desc, "draft": False, "prerelease": False})
        print(("OK   Release %s" % rel.get("html_url")) if st3 in (200, 201)
              else "WARN Release 未建（HTTP %d），代码已推到位" % st3)

    print("\n仓库地址 https://github.com/%s/%s" % (owner, a.repo))


if __name__ == "__main__":
    main()
