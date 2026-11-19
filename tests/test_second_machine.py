"""第二台机器的仿真：在一个空 home、空环境变量、空目录里，完整跑一遍
「病稿 → 判据拦 → 按整改要求改写 → 复判放行」，证明包离开本机也能活。

不依赖本机任何路径：容器里只有 /work 一份拷贝。
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

JUDGE = Path(sys.argv[1] if len(sys.argv) > 1 else "judge/reply_rules.py")
REPORT = {"steps": [], "ok": True}


def step(name, passed, detail=""):
    REPORT["steps"].append({"name": name, "passed": bool(passed), "detail": detail})
    if not passed:
        REPORT["ok"] = False


def load_judge(mod_file: Path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("judge_rules", mod_file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 1. 判据必须能单文件加载（不 import 包内其它东西）
try:
    J = load_judge(JUDGE)
    step("judge loads standalone", True, "review() 可用")
except Exception as e:  # noqa: BLE001
    step("judge loads standalone", False, f"{type(e).__name__}: {e}")
    print(json.dumps(REPORT, ensure_ascii=False, indent=1))
    raise SystemExit(1)

BANNER = "> ✅ **输出规范审查已通过，以下正式回复**\n\n"

# 2. 病稿：无横幅、有完成类断言无证据、段落超长
sick = "本次已经全部补齐并验证通过，覆盖了所有渠道。" * 12
hits1 = J.review(sick)
step("sick draft is rejected", len(hits1) > 0, f"命中 {len(hits1)} 条：{hits1[:3]}")

# 3. 按整改要求改写：加横幅、给可复核坐标、拆段
fixed = (
    BANNER
    + "## 🎯 结论：渠道全通\n\n"
    + "## 📌 要点\n"
    + "- **是什么**：两个渠道的长连接在 18:00 恢复，网关日志 25070 行之后无 ERROR。\n"
    + "- **代价**：飞书首次建链最长等 30 秒，超时会自动重试，最多退避到 120 秒。\n"
    + "- **未验**：企微在没有移动端在线时的推送成功率没测。\n\n"
    + "---\n\n"
    + "> **🔍 铁律质检**　通过（92/100，置信度 0.86）\n"
    + "> 结论来自网关状态文件与日志两处独立读回；企微推送成功率未测，是这份结论唯一的缺口。\n"
)
hits2 = J.review(fixed)
step("rewritten draft is accepted", not hits2, f"剩余命中：{hits2}")

# 4. 空目录里跑：不读环境变量、不读家目录配置也能出同样结论
env = {k: v for k, v in os.environ.items() if not k.startswith(("HERMES", "KB_", "LITELLM"))}
with tempfile.TemporaryDirectory() as td:
    p = Path(td) / "r.py"
    p.write_text(JUDGE.read_text(encoding="utf-8"), encoding="utf-8")
    r = subprocess.run([sys.executable, "-c",
                        "import importlib.util,sys;"
                        "s=importlib.util.spec_from_file_location('j',%r);"
                        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
                        "print(len(m.review('本次已全部完成')))" % str(p)],
                       capture_output=True, text=True, env=env, timeout=120,
                       encoding="utf-8", errors="replace")
    step("runs with env stripped", r.returncode == 0, (r.stdout or "").strip() or (r.stderr or "")[-160:])

print(json.dumps(REPORT, ensure_ascii=False, indent=1))
raise SystemExit(0 if REPORT["ok"] else 1)
