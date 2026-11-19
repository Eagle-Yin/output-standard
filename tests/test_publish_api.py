"""REST 直推车道（publish.push_via_api）的行为回归：不发真请求，用假接口验请求形状与三条关键行为。

为什么要有这个：这台机器上程序拉不起 git 进程，发布只能走 REST。而 REST 车道要「拼」出一个提交，
拼错了远端就是一堆散文件——所以用假接口把它每一步的请求都看清，再用回读核对兜住。
"""
import base64
import hashlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import publish  # noqa: E402

ok, fails = [], []


def check(name, cond, detail=""):
    (ok if cond else fails).append(name if cond else "%s：%s" % (name, detail))


def fake_api(calls, head_after=None):
    """假接口：按路径返回合理响应，并把每次调用记进 calls。"""
    def api(path, method="GET", token=None, payload=None):
        calls.append((method, path, payload))
        if path.endswith("/git/blobs"):
            data = base64.b64decode(payload["content"])
            sha = hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()
            return 201, {"sha": sha}
        if path.endswith("/git/trees"):
            return 201, {"sha": "tree000"}
        if path.endswith("/git/ref/heads/master"):
            return (200, {"object": {"sha": head_after}}) if head_after else (404, {})
        if path.endswith("/git/commits"):
            return 201, {"sha": "commit000"}
        if path.endswith("/releases"):
            return 201, {"html_url": "https://example.test/release"}
        return 200, {}
    return api


def run_case(files, head_after=None):
    tmp = Path(tempfile.mkdtemp())
    for rel, body in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    calls = []
    real_pkg, real_api = publish.PKG, publish.api
    publish.PKG, publish.api = tmp, fake_api(calls, head_after)
    try:
        return publish.push_via_api("o", "r", "tok", "desc", "master", "v1"), calls
    finally:
        publish.PKG, publish.api = real_pkg, real_api


# 1. 工作流文件被跳过，其余照发，且跳过项在说明里点名（不静默丢）
(okflag, note), calls = run_case({
    "a.py": "x = 1\n",
    "docs/b.md": "hi\n",
    ".github/workflows/ci.yml": "on: push\n",
    "__pycache__/c.pyc": "junk",
}, head_after="commit000")
paths = [c[2] for c in calls if c[1].endswith("/git/blobs")]
check("跳过工作流文件", len(paths) == 2, "实际上传 %d 个" % len(paths))
check("跳过项在说明里点名", "workflows" in note, note)
check("成功且回读核对通过", okflag, note)

# 2. 已有分支头时，新提交要挂父提交；没有就建根提交
_, calls = run_case({"a.py": "x\n"}, head_after="prev111")
commit = [c for c in calls if c[1].endswith("/git/commits")][0][2]
check("提交挂父提交", commit["parents"] == ["prev111"], str(commit["parents"]))
_, calls = run_case({"a.py": "x\n"}, head_after=None)
commit = [c for c in calls if c[1].endswith("/git/commits")][0][2]
check("无分支头时建根提交", commit["parents"] == [], str(commit["parents"]))

# 3. 回读不一致必须判失败（否则「推上去了」又是一句推断）
(okflag, note), _ = run_case({"a.py": "x\n"}, head_after="someone-else")
check("回读不一致判失败", not okflag, note)

for line in ok:
    print("ok   " + line)
for line in fails:
    print("FAIL " + line)
print("\n%d 项通过，%d 项失败" % (len(ok), len(fails)))
sys.exit(1 if fails else 0)
