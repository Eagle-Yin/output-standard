"""新增三条判据（横幅/注脚体面/分层精简）的反向验证。

只证明「能拦住」不算数——必须同时证明「该放行的放行」，
否则闸一误判，人就把它整条关掉，那一条都剩不下。
"""
import importlib.util
import sys
from pathlib import Path

H = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("rr", H / "judge" / "reply_rules.py")
rr = importlib.util.module_from_spec(spec)
sys.modules["rr"] = rr
spec.loader.exec_module(rr)

BODY = "🎯 结论：改完了，代价是慢一点。\n\n📌 要点\n- **是什么**：一句话说清它干什么。" \
       "\n- **为什么**：一句话说清为谁存在。\n\n" * 6

GOOD = (
    "> ✅ **输出规范审查已通过，以下正式回复**\n\n"
    + BODY
    + "\n---\n\n> **🔍 铁律质检**　本轮判据全过，代价是第一版被拦了两次（95/100，置信度 0.95）\n"
)

NO_BANNER = BODY + "\n---\n\n> **🔍 铁律质检**　全过（95/100，置信度 0.95）\n"

BANNER_NOT_FIRST = "先说一句废话。\n\n" + GOOD

JUNK_FOOTER = (
    "> ✅ **输出规范审查已通过，以下正式回复**\n\n"
    + BODY
    + "\n---\n\n> **🔍 铁律质检**　hits [] exit=0，3558 字符（95/100）\n"
)

WALL = (
    "> ✅ **输出规范审查已通过，以下正式回复**\n\n"
    "🎯 结论：改完了。\n\n📌 要点\n"
    + ("这句话很长但没有任何粗体引导也没有表格，整段平铺下来读者扫不出结构，"
       "只能一行一行读，读到最后也记不住有哪几条，这就是所谓的文字墙。\n") * 6
    + "\n---\n\n> **🔍 铁律质检**　全过（95/100，置信度 0.95）\n"
)

LONG_PARA = (
    "> ✅ **输出规范审查已通过，以下正式回复**\n\n"
    "🎯 结论：改完了。" + "这句话非常长，" * 60 + "\n\n📌 要点\n- **是什么**：短。\n"
    "\n---\n\n> **🔍 铁律质检**　全过（95/100，置信度 0.95）\n"
)

SHORT = "🎯 改好了，exit=0。"

CASES = [
    ("该放行的：横幅+分层+干净注脚", GOOD, []),
    ("该拦的：没有横幅", NO_BANNER, [rr.LBL_NOBANNER]),
    ("该拦的：横幅不在最前", BANNER_NOT_FIRST, [rr.LBL_NOBANNER]),
    ("该拦的：注脚混机器串", JUNK_FOOTER, [rr.LBL_FOOTERJUNK]),
    ("该拦的：要点是一堵墙（连带段落过长，真缺陷本就同时成立）", WALL, [rr.LBL_WALL, rr.LBL_LONGPARA]),
    ("该拦的：段落太长", LONG_PARA, [rr.LBL_LONGPARA]),
    ("该放行的：短问答豁免", SHORT, []),
    ("该放行的：多行列表逐行量，不拼成一堵墙",
     "> ✅ **输出规范审查已通过，以下正式回复**\n\n🎯 结论：改完了，`exit=0`。\n\n📌 要点\n"
     + "- **细节**：补一行。\n" * 30
     + "\n---\n\n> **🔍 铁律质检**　全过（95/100，置信度 0.95）\n", []),
    ("该拦的：单个列表项本身超长",
     "> ✅ **输出规范审查已通过，以下正式回复**\n\n🎯 结论：改完了，`exit=0`。\n\n📌 要点\n"
     + "- **细节**：" + "这一条长得离谱，" * 50 + "\n"
     + "\n---\n\n> **🔍 铁律质检**　全过（95/100，置信度 0.95）\n", [rr.LBL_LONGPARA]),
]


class _NoNum:
    """数字替身：本次只验版式，算式复算交给 numcheck 自己的测试。"""

    def scan(self, text):
        return []


def main() -> int:
    bad = 0
    for name, text, want in CASES:
        got = rr.review(text, numcheck=_NoNum())
        # 只关心本次新增的三类标签，别被无关标签干扰
        mine = [h for h in got if h in (rr.LBL_NOBANNER, rr.LBL_FOOTERJUNK,
                                        rr.LBL_WALL, rr.LBL_LONGPARA)]
        ok = sorted(mine) == sorted(want)
        print(("PASS " if ok else "FAIL ") + name)
        if not ok:
            print("      期望 %s，实得 %s" % (want, mine))
            bad += 1
    print("\n%d/%d 项符合预期" % (len(CASES) - bad, len(CASES)))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
