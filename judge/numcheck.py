"""算数交给机器：模型只负责交算式，Python 负责算，算不对就当场报错。

为什么需要它（2026-11-19 兵哥问「数字幻觉怎么防」）：
模型错数字的根因不是它不肯讲道理，而是它本来就不会算——它模仿数字的形状，不做真实的运算。
所以「要求它给计算说明」只能提高发现率，不能提高正确率：它照样能编一个看着像对的算式。
唯一真正可靠的办法是把算术从模型手里拿走，交给确定的计算器。

规则（三层里的第三层，最根本的一层）：
  · 回复里写成 `=算式= 结果` 的数字，机器会复算，不一致就报错；
  · 没写算式的百分比/倍数/合计类数字，由 iron_hook 判据要求给依据或算式；
  · 普通计数（「21 条要求」）不管，避免吵到没法用。

用法（命令行）：
    python iron/numcheck.py "0.05*65536*1.4"
    python iron/numcheck.py --scan reply.md      # 扫一份文稿里的 =算式= 结果
"""
from __future__ import annotations

import ast
import operator
import re
import sys
from pathlib import Path

# 只允许四则运算与取整：够用，且不给执行任意代码的口子。
_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("只认数字")
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("不支持的算式成分：%s" % type(node).__name__)


def compute(expr: str) -> float:
    """算一个纯算式。只接受数字与四则运算，其它一律拒绝——这不是限制，是安全边界。"""
    return _eval(ast.parse(expr, mode="eval"))


# 文稿里的写法： =0.05*65536*1.4= 4587
SCAN_RE = re.compile(r"=\s*([0-9+\-*/().\s]{3,60}?)\s*=\s*([0-9][0-9,]*(?:\.[0-9]+)?)")


def scan(text: str) -> list[tuple[str, str, str]]:
    """扫文稿里的「=算式= 结果」，返回对不上的那些：[(算式, 声称结果, 实际结果)]。

    容差：相对误差 1% 或绝对 0.5 以内都算对。
    为什么给容差：正文里的数字常带四舍五入（4587 vs 4586.6），卡死会天天误报，
    而误报多了人就把它关掉——那样等于没有。
    """
    bad = []
    for m in SCAN_RE.finditer(text or ""):
        expr, claimed = m.group(1), m.group(2).replace(",", "")
        try:
            real = compute(expr)
        except Exception:
            continue  # 不是真算式（比如表格里的等号），跳过而不是报错
        try:
            c = float(claimed)
        except ValueError:
            continue
        tol = max(0.5, abs(real) * 0.01)
        if abs(real - c) > tol:
            bad.append((expr.strip(), claimed, ("%.6g" % real)))
    return bad


def main() -> int:
    """命令行入口：算一个算式，或扫一份文稿里的「=算式= 结果」。"""
    args = sys.argv[1:]
    if not args:
        print("用法：numcheck.py \"算式\"  或  numcheck.py --scan 文件名")
        return 2
    if args[0] == "--scan":
        p = Path(args[1])
        bad = scan(p.read_text(encoding="utf-8", errors="replace"))
        if not bad:
            print("ok 文稿里的算式与结果都对得上")
            return 0
        print("发现 %d 处算错：" % len(bad))
        for e, c, r in bad:
            print("  =%s=  写的是 %s，实际 %s" % (e, c, r))
        return 1
    try:
        print("%.10g" % compute(" ".join(args)))
        return 0
    except Exception as exc:  # noqa: BLE001
        print("算不了：%s" % exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
