"""容器内自检脚本：拷进容器里跑，不靠 shell 转义。
之前用 shell 内联 python 字符串，转义把样本毁了，报出假失败。
"""
import sys

sys.path.insert(0, "judge")
import reply_rules as r  # noqa: E402

SHORT = "🎯 改好了。"
LONG = (
    "> ✅ **输出规范审查已通过，以下正式回复**\n\n"
    "🎯 结论：改完了，`exit=0`。\n\n"
    "📌 要点\n"
    "- **是什么**：一句话。\n"
    "- **为什么**：一句话。\n"
    + "- **细节**：补一行。\n" * 20
    + "\n---\n\n> **🔍 铁律质检**　判据全过（95/100，置信度 0.95）\n"
)

print("短问答 len=%d hits=%s" % (len(SHORT), r.review(SHORT)))
print("长成稿 len=%d banner=%s hits=%s" % (len(LONG), bool(r.BANNER_OK_RE.match(LONG)), r.review(LONG)))
assert r.review(SHORT) == [], "短问答被误伤"
assert r.review(LONG) == [], "合格长稿被误伤"
print("JUDGE OK")
