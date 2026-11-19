"""发布路径实测：两段验法，各自说清能验到什么。

A 段（任何机器都跑）：用假 git 记录命令，验分支逻辑——先 force-with-lease、
   失败退回普通 push、令牌只出现在命令行、推完立刻把带令牌地址换回干净地址、
   输出里令牌被打码。这段不依赖本机有没有 git。
B 段（本机有能被子进程拉起的 git 时才跑）：真造一个裸仓库当远端，真推一次、
   再推一次，确认远端真拿到提交。找不到可用的 git 时明确打 SKIP 并给原因，不假装通过。

为什么两段要分开：这台机器的 PATH 上第一个 git 是商店版执行别名，装在受保护的
WindowsApps 目录，子进程拉起会被拒绝访问（实测 WinError 5），而命令行里同一个
"git" 跑得好好的。同一台机器另有一份独立安装能跑——所以「用哪个 git」必须真试
（publish.git_exe），逻辑测试则不该依赖这件事。
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import publish  # noqa: E402  验的就是它

fails, oks, skips = [], [], []


def check(name, cond, detail=""):
    (oks if cond else fails).append(name + (("：" + detail) if detail and not cond else ""))


class FakeProc:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def fake_git(results):
    """按顺序返回预设结果，并记录每次调用的命令。"""
    calls = []

    def run(cmd, **kw):
        calls.append(list(cmd))
        return results[min(len(calls) - 1, len(results) - 1)]

    return run, calls


def part_a():
    # 1. 首次推送：lease 失败 -> 普通 push 成功
    run, calls = fake_git([FakeProc(1, stderr="stale"), FakeProc(0, stderr="done")])
    okd, out = publish.push_branch(ROOT, "https://example.com/x.git", "main", runner=run)
    check("lease 失败后重试成功", okd and len(calls) == 2, "调用次数 %d" % len(calls))
    check("第一次带 lease，第二次不带",
          "--force-with-lease" in calls[0] and "--force-with-lease" not in calls[1])

    # 2. 令牌只出现在 push 命令里，且推完立刻换回干净地址
    run, calls = fake_git([FakeProc(0)])
    okd, out = publish.push_branch(ROOT, "https://example.com/x.git", "main",
                                   token="ghp_fake123", runner=run)
    check("令牌进了 push 地址", any("ghp_fake123" in " ".join(c) for c in calls))
    check("推完把地址换回干净的",
          any(c[1:3] == ["remote", "set-url"] and c[-1] == "https://example.com/x.git"
              for c in calls), str(calls[-1][:3]))

    # 3. 输出里的令牌必须打码
    check("输出里令牌被打码", "ghp_fake123" not in out)

    # 4. 两次都失败时如实返回失败，不假装
    run, _ = fake_git([FakeProc(128, stderr="nope")])
    okd, out = publish.push_branch(ROOT, "https://example.com/x.git", "main", runner=run)
    check("全失败时返回 False", okd is False and "nope" in out)

    # 5. 版本号能读到
    v = publish.read_version()
    check("能读到版本号", bool(v) and v[0].isdigit(), v)


def part_b():
    exe = publish.git_exe()
    if exe is None:
        skips.append("B 段：本机没有能被子进程拉起的 git")
        return

    tmp = Path(tempfile.mkdtemp(prefix="pubtest-"))
    try:
        bare, work = tmp / "remote.git", tmp / "work"

        def git(*args, **kw):
            return subprocess.run([exe, *args], capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", **kw)

        git("init", "--bare", "-b", "main", str(bare))
        git("clone", str(bare), str(work))
        for k, v in (("user.email", "t@example.com"), ("user.name", "t")):
            git("config", k, v, cwd=str(work))
        (work / "a.txt").write_text("x\n", encoding="utf-8")
        git("add", "-A", cwd=str(work))
        git("commit", "-m", "init", cwd=str(work))

        okd, out = publish.push_branch(work, str(bare), "main")
        check("首次推送成功", okd, out[-160:])
        rc = git("--git-dir", str(bare), "rev-parse", "main")
        check("远端真有这个分支", rc.returncode == 0 and len(rc.stdout.strip()) == 40)

        (work / "b.txt").write_text("y\n", encoding="utf-8")
        git("add", "-A", cwd=str(work))
        git("commit", "-m", "second", cwd=str(work))
        okd, out = publish.push_branch(work, str(bare), "main")
        check("二次推送成功", okd, out[-160:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    part_a()
    part_b()
    for line in oks:
        print("ok   " + line)
    for line in skips:
        print("SKIP " + line)
    for line in fails:
        print("FAIL " + line)
    print("\n%d 项通过，%d 项失败，%d 项跳过" % (len(oks), len(fails), len(skips)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
