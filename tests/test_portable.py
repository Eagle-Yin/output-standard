"""可移植性实测：把 reply_rules.py 单独拷到一个临时空目录，脱离本机环境跑。

为什么必须这么测：说「可开源给别人用」最容易被自己骗——本机跑得通，
是因为旁边的 iron_hook、numcheck、config.yaml 都在。真正拷到别处才知道漏了什么。
这个测试模拟的是「另一个人 git clone 之后只拿这一个文件」。

三档：
  ① 只拷 reply_rules.py，不拷 numcheck → 必须仍能判（数字算式跳过，其余照判）；
  ② 拷上 numcheck.py → 数字算式复算也生效；
  ③ 全程不碰本机 HERMES_HOME，验证零依赖。
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

H = Path(__file__).resolve().parents[1]
PY = sys.executable

PROBE = (
    "import sys; sys.path.insert(0, sys.argv[1]);"
    "import reply_rules as r;"
    "print(r.review('我改好了，全部完成。'));"
    "print(r.review('我改好了，exit=0'));"
    "print(r.review('这次优化让耗时下降了 37%，效果明显。'));"
)


def run_probe(tmp: Path) -> str:
    env = dict(os.environ)
    env.pop("HERMES_HOME", None)  # 完全不依赖本机环境
    r = subprocess.run([PY, "-c", PROBE, str(tmp)], capture_output=True, text=True,
                       timeout=120, env=env)
    if r.returncode != 0:
        return "ERR " + (r.stderr or "")[:200]
    return r.stdout.strip()


bad = 0
tmp = Path(tempfile.mkdtemp(prefix="rr_portable_"))
try:
    # ① 只拷判据文件
    shutil.copy2(H / "judge" / "reply_rules.py", tmp / "reply_rules.py")
    out = run_probe(tmp)
    ok1 = "完成类断言无本轮输出" in out and "数字无依据或算式不复算" in out
    print(("ok   " if ok1 else "FAIL ") + "裸拷单一文件即可用（不依赖本机任何东西）")
    print("       输出:", out.replace("\n", " | ")[:160])
    bad += 0 if ok1 else 1

    # ② 加上复算器，算式应能被判
    shutil.copy2(H / "judge" / "numcheck.py", tmp / "numcheck.py")
    probe2 = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "import reply_rules as r;"
        "print('BAD', r.review('预算 =10*3= 31 字符。'));"
        "print('OK', r.review('预算 =10*3= 30 字符。'));"
    )
    env = dict(os.environ)
    env.pop("HERMES_HOME", None)
    res = subprocess.run([PY, "-c", probe2, str(tmp)], capture_output=True, text=True,
                         timeout=120, env=env)
    ok2 = "BAD ['数字无依据或算式不复算']" in res.stdout and "OK []" in res.stdout
    print(("ok   " if ok2 else "FAIL ") + "带上复算器后，算错必抓、算对放行")
    print("       输出:", res.stdout.strip().replace("\n", " | ")[:160])
    bad += 0 if ok2 else 1
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n失败 %d 项" % bad)
sys.exit(1 if bad else 0)
