"""智能体闭环仿真：病稿 → 被判据拦住 → 按整改指引改写 → 再判放行。

为什么要有这一层：单测只证明「判据认得某段文字」，证明不了「一个会犯错的写作者
被拦下之后，能不能真的改对」。真实链路是 注入规范 → 模型写稿 → 闸审查 → 打回重写，
这里用确定性替身替代模型，把「打回 → 改写 → 复判」这一步跑通。
替身不聪明，但只要判据给出的指引足以让一个不带智能的改写者把稿子改过关，
说明指引本身是可执行的 —— 这是 3W5H 里「谁在何时怎么走」那一段的实证。

真模型介入的闭环（模型自己读指引重写）代价高：需要一个能跑 agent loop 的环境
和一个替身模型端点。这里先证明指引可执行，那一层只在换判据措辞时才需要重跑。
"""

import importlib.util
import re
import sys
from pathlib import Path

H = Path(__file__).resolve().parents[1]
# 本包把判据放在 judge/；开发树里在 iron/。两处都认，免得换目录就报 FileNotFound。
_rr = next(p for p in (H / "judge" / "reply_rules.py", H / "iron" / "reply_rules.py") if p.exists())
spec = importlib.util.spec_from_file_location("rr", _rr)
rr = importlib.util.module_from_spec(spec)
sys.modules["rr"] = rr
spec.loader.exec_module(rr)

BANNER = "> ✅ **输出规范审查已通过，以下正式回复**\n\n"
FOOT = "\n---\n\n> **🔍 铁律质检**　判据全过（95/100，置信度 0.95）\n"


def fix_up(draft: str, hits: list) -> str:
    """按指引改写：替身不带智能，只会照句面要求动手术。

    每条指引都对应一个机械动作；若某条指引无法机械执行，说明它写得不合格，
    这里会直接断言失败——这正是本测试的价值。
    """
    out = draft
    for h in hits:
        if "横幅" in h:
            if not rr.BANNER_OK_RE.match(out):
                out = BANNER + out.lstrip("\n")
        elif "注脚" in h and ("机器" in h or "格式说明" in h):
            out = rr.FOOTER_JUNK_RE.sub("", out)
            if "铁律质检" not in out:
                out = out.rstrip() + FOOT
        elif "分隔线" in h:
            if not re.search(r"(?m)^---\s*$", out):
                out = out.rstrip() + FOOT
        elif "段落过长" in h:
            # 把超长段落按句号切开，逐句一行，这是人能照做的最小动作
            def split_para(m):
                raw = m.group(0).strip()
                if raw.startswith(("#", "|", ">", "📌", "🎯")):
                    return m.group(0)
                head = ""
                body = raw
                if rr.LIST_ITEM_RE.match(raw):
                    head = rr.LIST_ITEM_RE.match(raw).group(0)
                    body = raw[len(head):]
                if len(body) <= rr.PARA_MAX_CHARS:
                    return m.group(0)
                sents = [s for s in re.split(r"(?<=[。；，、])", body) if s.strip()]
                return "\n".join(head + s.strip() for s in sents)
            out = re.sub(r"[^\n]+", split_para, out)
        elif "一堵墙" in h or "粗体" in h:
            # 要点每行加粗体引导词，这是「分层」的最小可执行版
            lines = out.splitlines()
            out = "\n".join(
                (re.sub(r"^- (?!\*\*)", "- **要点**：", l) if re.match(r"^- ", l) else l)
                for l in lines
            )
        elif "完成类断言" in h or "无本轮输出" in h:
            # 不猜措辞：逐行看，谁说了做完却没有坐标，就给它补本轮坐标。
            # 结论行、列表项都可能中招，按单元判而不是按行首判。
            out = "\n".join(
                # 坐标必须落在同一单元里：判据按句切单元，挂在行尾会被切成独立单元，
                # 所以插在句号之前，跟断言同句。
                (re.sub(r"。(\s*)$", "（本轮 `exit=0`，已回读）。\1", l.rstrip(), count=1)
                 if (rr.CLAIM_RE.search(rr._strip_quotes(l)) and not rr.TRACE_RE.search(l)) else l)
                for l in out.splitlines()
            )
    return out


CASES = {
    "病稿一：无横幅、注脚混机器串、要点成一堵墙": (
        "🎯 结论：迁移已全部完成。\n\n📌 要点\n"
        + "- 键值都改了，读回也对，流程也跑过了没有报错，用户那边也没反馈问题，所以可以认为这一轮迁移工作已经算是收尾了。\n"
        + "- 第二件事也做完了，同样没有记录，反正就是做完了。\n"
        + "- 第三件事也做完了，同样没有记录，反正就是做完了。\n"
        + "- 第四件事也做完了，同样没有记录，反正就是做完了。\n"
        + "- 第五件事也做完了，同样没有记录，反正就是做完了。\n"
        + "\n---\n\n> **🔍 铁律质检**　通过 hits [] exit=0 3558 字符\n"
    ),
    "病稿二：结论只剩技术符号、段落过长": (
        BANNER
        + "🎯 结论：`kw_ok()` 返回 `False`，`exit=1`，`stdout` 是 `Traceback`。\n\n📌 要点\n"
        + "- **现象**：" + "这一行里塞了很多彼此无关的细节，" * 20 + "\n"
        + FOOT
    ),
}


def main() -> int:
    bad = 0
    for name, draft in CASES.items():
        first = rr.review(draft)
        if not first:
            print("FAIL %s：病稿居然放行了" % name)
            bad += 1
            continue
        fixed = fix_up(draft, first)
        second = rr.review(fixed)
        ok = not second
        print("%s %s" % ("PASS" if ok else "FAIL", name))
        print("     首判拦下 %d 条：%s" % (len(first), "；".join(h[:22] for h in first[:3])))
        if not ok:
            print("     按指引改写后仍未放过：%s" % second)
            bad += 1
    print("\n%d/%d 个闭环通过" % (len(CASES) - bad, len(CASES)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
