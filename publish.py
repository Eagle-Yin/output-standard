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
import shutil
import subprocess
import sys
import time
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


def git_exe():
    """找一个真能拉起来的 git。PATH 上第一个 git 可能是商店版别名，程序里被系统拒绝（WinError 5），
    但同机的独立安装能跑——所以逐个试，返回第一个能响应 --version 的，全不行返回 None。"""
    seen, cands = set(), []
    for c in [shutil.which("git"), os.path.expandvars(r"%LOCALAPPDATA%\hermes\git\cmd\git.exe"),
              r"C:\Program Files\Git\cmd\git.exe"]:
        if c and c not in seen:
            seen.add(c)
            cands.append(c)
    for c in cands:
        try:
            if subprocess.run([c, "--version"], capture_output=True, timeout=20).returncode == 0:
                return c
        except Exception:
            continue
    return None


def git(*args, check=True):
    exe = git_exe()
    if not exe:
        die("本机找不到能运行的 git")
    p = subprocess.run([exe, *args], cwd=str(PKG), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and p.returncode != 0:
        die("git %s -> %s" % (" ".join(args), (p.stderr or p.stdout).strip()[:300]))
    return (p.stdout or "").strip()


def git_available():
    """本机能否真正拉起 git 进程——真跑一次 --version，不猜。"""
    return git_exe() is not None


def read_version():
    """从 judge/__init__.py 读版本号——版本只写一处。"""
    text = (PKG / "judge" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not m:
        die("judge/__init__.py 里找不到 __version__")
    return m.group(1)


def push_via_api(owner, repo, token, desc, branch, tag):
    """不用本机 git，直接经 REST 接口把工作区文件提交上去。

    为什么要有这条路：某些机器上程序拉不起 git 进程（实测 WinError 5），
    而 HTTPS 到 api.github.com 是通的——那就绕开 git，把文件、树、提交、引用一步步建出来。
    代价：拿不到 git 的历史与合并能力，只能整树快照；适合首次发布与纯追加。

    返回 (ok, 说明)。
    """
    import base64
    import hashlib

    def call(path, method="GET", payload=None):
        last = ""
        for attempt in range(4):
            try:
                st, body = api(path, method, token, payload)
                if st < 500:
                    return st, body
                last = "HTTP %d" % st
            except Exception as e:  # 断连/超时
                last = "%s: %s" % (type(e).__name__, e)
            time.sleep(2 + 3 * attempt)
        return 0, {"message": "网络连续失败：" + last}

    # 1. 逐文件建 blob（跳过 .git、缓存，以及 .github/workflows/ 下的文件）
    #    .github/workflows/ 需要令牌额外带 workflow 权限，缺它建树一律 404（实测）；
    #    跳过而不是中断：其余文件先发布，CI 文件等拿到带该权限的令牌再补一条提交。
    tree, skipped = [], []
    for f in sorted(PKG.rglob("*")):
        if not f.is_file() or ".git" in f.parts or "__pycache__" in f.parts:
            continue
        rel = f.relative_to(PKG).as_posix()
        if rel.startswith(".github/workflows/"):
            skipped.append(rel)
            continue
        data = f.read_bytes()
        sha = hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()
        st, out = call("/repos/%s/%s/git/blobs" % (owner, repo), "POST",
                       {"content": base64.b64encode(data).decode(), "encoding": "base64"})
        if st not in (200, 201) or out.get("sha") != sha:
            # 工作流文件需要额外的 workflow 权限，缺权限时 GitHub 只回 404
            skipped.append(rel)
            continue
        tree.append({"path": rel, "mode": "100644", "type": "blob", "sha": sha})
    if not tree:
        return False, "一个文件都没上传成功"

    # 2. 树 + 提交（父提交取当前分支头，没有就建根提交）
    st, out = call("/repos/%s/%s/git/trees" % (owner, repo), "POST", {"tree": tree})
    if st not in (200, 201):
        return False, "建树失败 HTTP %s：%s" % (st, out.get("message", ""))
    tree_sha = out["sha"]
    st, head = call("/repos/%s/%s/git/ref/heads/%s" % (owner, repo, branch))
    parents = [head["object"]["sha"]] if st == 200 and head.get("object") else []
    st, cm = call("/repos/%s/%s/git/commits" % (owner, repo), "POST",
                  {"message": desc, "tree": tree_sha, "parents": parents})
    if st not in (200, 201):
        return False, "建提交失败 HTTP %s：%s" % (st, cm.get("message", ""))
    commit_sha = cm["sha"]

    # 3. 分支引用：已有就改指，没有就新建
    st, _ = call("/repos/%s/%s/git/refs/heads/%s" % (owner, repo, branch), "PATCH",
                 {"sha": commit_sha, "force": True})
    if st != 200:
        call("/repos/%s/%s/git/refs" % (owner, repo), "POST",
             {"ref": "refs/heads/" + branch, "sha": commit_sha})

    # 4. 标签与 Release
    call("/repos/%s/%s/git/refs" % (owner, repo), "POST",
         {"ref": "refs/tags/" + tag, "sha": commit_sha})
    st, rel = call("/repos/%s/%s/releases" % (owner, repo), "POST",
                   {"tag_name": tag, "name": tag, "body": desc, "draft": False,
                    "prerelease": False})

    # 5. 回读核对：远端这个分支头必须就是我们刚建的提交
    st, head = call("/repos/%s/%s/git/ref/heads/%s" % (owner, repo, branch))
    ok = st == 200 and head.get("object", {}).get("sha") == commit_sha
    note = "提交 %s，%d 个文件" % (commit_sha[:12], len(tree))
    if skipped:
        note += "；跳过 %d 个（需 workflow 权限）：%s" % (len(skipped), ", ".join(skipped))
    note += "；Release " + (rel.get("html_url") or "HTTP %s" % st)
    return ok, note


class FakeResult:
    """推送超时时用的替身结果：与 subprocess 返回值同形，好让上层照常判断失败。"""
    def __init__(self, returncode, stdout, stderr):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def push_branch(package_dir, remote_url, branch, token=None, runner=None):
    """把本地分支推到远端；token 只在这一句里出现，推完立刻用干净地址覆盖。

    返回 (ok, 输出)。远端不存在分支时退回普通 push —— 首次推送就是这种情况。
    runner 可注入（测试用假 git 验分支逻辑，不依赖本机有没有 git）。
    """
    run = runner or subprocess.run
    exe = git_exe() or "git"
    url = remote_url
    if token:
        url = remote_url.replace("https://", "https://x-access-token:" + token + "@")
    head = [exe, "push", url, "%s:%s" % (branch, branch)]

    def call(cmd):
        # 超时必须设：某些网络到 github.com 的 https 会静默挂 5 分钟，
        # 不设超时就是让整条发布卡死，用户看不出在等什么。shortcut: 120s 够一次推，
        # 仓库特别大（>1GB）时改大。
        try:
            return run(cmd, cwd=str(package_dir), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
        except subprocess.TimeoutExpired:
            return FakeResult(124, "", "推送超时（120s），网络不通或需要认证")

    p = call(head + ["--force-with-lease"])
    if p.returncode != 0:
        p = call(head)
    if token:  # 令牌不留在配置里
        run([exe, "remote", "set-url", "origin", remote_url],
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
    ap.add_argument("--remote", default=os.environ.get("PUBLISH_REMOTE", ""),
                    help="推送地址；默认用仓库的 https 地址。https 到 github 不通的机器上，"
                         "填 git@ssh.github.com:用户/仓库.git 走 443 端口 SSH")
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
    # 令牌只对 https 地址有意义；给了 --remote（如 443 端口 SSH）就用它推，但标签/Release 仍走接口
    push_url = a.remote or url

    version = read_version()
    tag = "v" + version

    # 3. 先走 git（有历史、可增量）；拉不起 git 或推不通时，改走 REST 接口（整树快照）
    pushed = False
    if git_available():
        git("config", "user.name", me.get("name") or owner)
        git("config", "user.email", "%s@users.noreply.github.com" % owner)
        branch = git("rev-parse", "--abbrev-ref", "HEAD") or "main"
        if git("remote", check=False):
            git("remote", "set-url", "origin", push_url)
        else:
            git("remote", "add", "origin", push_url)
        pushed, out = push_branch(PKG, push_url, branch,
                                  token=None if a.remote else token)
        git("remote", "set-url", "origin", push_url)  # 令牌绝不留在配置里
        if pushed:
            print("OK   已推送 %s 分支" % branch)
            tag_release(owner, a.repo, token, push_url, tag, a.desc,
                        auth=None if a.remote else token)
        else:
            print("WARN git 推送不通，改走 REST 接口直推：" + out[:160])
    else:
        print("WARN 本机拉不起 git 进程，改走 REST 接口直推")

    if not pushed:
        ok, note = push_via_api(owner, a.repo, token, a.desc,
                                repo.get("default_branch") or "master", tag)
        print(("OK   " if ok else "FAIL ") + note)
        if not ok:
            print("\n仓库地址 https://github.com/%s/%s" % (owner, a.repo))
            raise SystemExit(1)

    print("\n仓库地址 https://github.com/%s/%s" % (owner, a.repo))


def tag_release(owner, repo, token, url, tag, desc, auth=None):
    """git 车道推完之后补标签与 Release；版本号取自 judge/__init__.py，唯一事实源。

    auth 为空表示推的是 SSH 地址，标签不需要令牌；只有 https 地址才把令牌拼进 URL。
    """
    st, tags = api("/repos/%s/%s/tags" % (owner, repo), token=token)
    if any(t.get("name") == tag for t in (tags if isinstance(tags, list) else [])):
        return
    exe = git_exe() or "git"
    subprocess.run([exe, "tag", "-f", tag], cwd=str(PKG), check=False)
    tag_url = url.replace("https://", "https://x-access-token:" + auth + "@") if auth else url
    subprocess.run([exe, "push", tag_url, tag, "--force"],
                   cwd=str(PKG), capture_output=True, text=True, timeout=120)
    git("remote", "set-url", "origin", url)
    st3, rel = api("/repos/%s/%s/releases" % (owner, repo), "POST", token=token,
                   payload={"tag_name": tag, "name": tag,
                            "body": desc, "draft": False, "prerelease": False})
    print(("OK   Release %s" % rel.get("html_url")) if st3 in (200, 201)
          else "WARN Release 未建（HTTP %d），代码已推到位" % st3)


if __name__ == "__main__":
    main()
