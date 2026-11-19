"""代码体检：把「优雅、简练、稳健、好读」拆成能机器判的东西。

## 为什么要有它

「精简优化、增加优雅度、增加稳健度、让人一看就懂」——这些是形容词。
形容词没法验收，所以每次我都能说「做了」，你也每次都问「真做了吗」。
这个工具的作用是把形容词换成数字和事实：几行、几处重复、几个函数超长、
有没有依赖平台、有没有吞错。答不上来的，就是没做。

## 八条判据（每条都能一句话说清为什么）

| 编号 | 查什么 | 为什么定这条 |
|---|---|---|
| C1 | 单文件 ≤ 900 行（>600 提醒） | 一次通读超一屏几十倍，改一处要滚很久，实测漏改过 |
| C2 | 标了「可移植」的文件不许依赖平台 | 不然别人拿不走，等于没开源 |
| C3 | 同一判据常量只许定义一处 | 两处各判一套，改一边另一边不动 |
| C4 | 不许裸 except 吞错 | 出问题查不出是哪一步挂的 |
| C5 | 单函数 ≤ 60 行（>100 直接判失败） | 一屏放不下，读的人会跳过 |
| C6 | 公开函数必须有说明 | 「一看就懂」里能判定的那部分 |
| C7 | 不许写死家目录路径 | 换台机器一行都跑不动 |
| C8 | 连续 8 行以上重复 → 提醒 | 同一段逻辑抄两遍，改一处必漏一处 |

## 用法

    python iron/codecheck.py                  # 查本机制的活代码
    python iron/codecheck.py --all            # 加上网关与脚本
    python iron/codecheck.py 某文件.py ...    # 只查指定文件
    python iron/codecheck.py --json           # 给门禁用

退出码：0 无失败项（提醒不算失败）；1 有失败项。
"""
from __future__ import annotations

import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

H = Path(__file__).resolve().parent.parent

# 本机制要有话说的文件。不扫整个仓库：扫全仓会把别人的历史问题算到我头上，
# 结果就是天天红、人人关闸。
DEFAULT_TARGETS = [
    "iron/reply_rules.py",
    "iron/numcheck.py",
    "iron/gap_check.py",
    "iron/codecheck.py",
    "plugins/output-standard/__init__.py",
    "plugins/output-standard/inject.py",
    "plugins/output-standard/standard.py",
    "plugins/output-standard/selftest.py",
]
EXTRA_TARGETS = [
    "iron/iron_hook.py",
    "litellm-hooks/gw_standard.py",
    "litellm-hooks/build_rules.py",
    "litellm-hooks/gw_standard_ctl.py",
]

# 声明「零依赖、可单独拷走」的文件。它们一旦 import 平台模块，承诺就作废。
PORTABLE = {"iron/reply_rules.py", "iron/numcheck.py"}
PLATFORM_MODULES = ("hermes", "hermes_constants", "agent", "cli", "gateway", "plugins")

MAX_FILE_LINES = 900        # 超过就是「一个文件干太多事」，该拆
WARN_FILE_LINES = 600
MAX_FUNC_LINES = 100        # 超过读不下去
WARN_FUNC_LINES = 60
DUP_BLOCK = 8               # 连续 8 行一样，基本就是抄的

# 家目录写死：换台机器直接跑不动（本轮实测踩过）。
# 这条规则本身要描述路径形状，所以全部用拼接组装——否则它把自己判死（连踩两次）。
_HD_WIN = "[A-Za-z]:[\\\\/]" + "User" + "s" + "[\\\\/][^\\\\/'\"\\s]+"
_HD_NIX = "/" + "home" + "/[^/'\"\\s]+"
HOMEDIR_RE = re.compile("(?:" + _HD_WIN + "|" + _HD_NIX + ")")


def _strip_comment(line: str) -> str:
    """去掉行尾注释，避免注释里提到路径就误报。"""
    s = line.split("#", 1)[0]
    return s


def check_file(rel: str) -> list:
    """查一个文件，返回问题列表：[(级别, 编号, 说明, 定位)]。"""
    # 相对路径先按当前目录找，再按仓库根找。
    # 为什么：文件被单独拷到别的目录（换台机器、给别人用）时，仓库根不存在，
    # 拿仓库根拼出来的路径必然「文件不存在」——本轮沙箱实测踩到，等于承诺搬走即废。
    if Path(rel).is_absolute():
        p = Path(rel)
    elif Path(rel).exists():
        p = Path(rel)
    else:
        p = H / rel
    out = []
    if not p.exists():
        return [("fail", "C0", "文件不存在", rel)]
    src = p.read_text(encoding="utf-8", errors="replace")
    lines = src.splitlines()
    short_rel = p.name if Path(rel).is_absolute() else rel

    # C1 规模
    if len(lines) > MAX_FILE_LINES:
        out.append(("fail", "C1", "文件 %d 行，超过 %d" % (len(lines), MAX_FILE_LINES), short_rel))
    elif len(lines) > WARN_FILE_LINES:
        out.append(("warn", "C1", "文件 %d 行，已过 %d（该拆职责了）" % (len(lines), WARN_FILE_LINES), short_rel))

    # C2 可移植承诺
    if rel.replace("\\", "/") in PORTABLE:
        for i, ln in enumerate(lines, 1):
            m = re.match(r"\s*(?:from|import)\s+([\w.]+)", ln)
            if m and m.group(1).split(".")[0] in PLATFORM_MODULES:
                out.append(("fail", "C2", "标了可移植却依赖平台模块 %s" % m.group(1),
                            "%s:%d" % (short_rel, i)))

    # C3 判据常量唯一（同文件里同名 re.compile 出现两次也算）
    seen_const = defaultdict(list)
    for i, ln in enumerate(lines, 1):
        m = re.match(r"\s*([A-Z][A-Z0-9_]{2,})\s*=\s*re\.compile", ln)
        if m:
            seen_const[m.group(1)].append(i)
    for name, where in seen_const.items():
        if len(where) > 1:
            out.append(("fail", "C3", "常量 %s 定义了 %d 次" % (name, len(where)),
                        "%s 行 %s" % (short_rel, where)))

    # C4 裸吞错
    for i, ln in enumerate(lines, 1):
        if re.search(r"except\s+Exception\s*:", ln) and "noqa" not in ln:
            out.append(("warn", "C4", "except Exception 未注明原因（吞错难查）",
                        "%s:%d" % (short_rel, i)))

    # C7 写死家目录
    for i, ln in enumerate(lines, 1):
        code = _strip_comment(ln)
        if HOMEDIR_RE.search(code):
            out.append(("fail", "C7", "写死家目录路径", "%s:%d" % (short_rel, i)))

    # C5 / C6 走语法树
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        out.append(("fail", "C0", "语法错误：%s" % exc, short_rel))
        return out
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        n = (node.end_lineno or node.lineno) - node.lineno + 1
        if n > MAX_FUNC_LINES:
            out.append(("fail", "C5", "函数 %s 有 %d 行" % (node.name, n),
                        "%s:%d" % (short_rel, node.lineno)))
        elif n > WARN_FUNC_LINES:
            out.append(("warn", "C5", "函数 %s 有 %d 行（该拆）" % (node.name, n),
                        "%s:%d" % (short_rel, node.lineno)))
        public = not node.name.startswith("_")
        if public and not ast.get_docstring(node):
            out.append(("warn", "C6", "公开函数 %s 没有说明" % node.name,
                        "%s:%d" % (short_rel, node.lineno)))

    # C8 重复代码块（跨文件一起算）
    return out


def dup_blocks(files: dict) -> list:
    """跨文件找连续重复行：同一段逻辑抄两遍，改一处必漏一处。"""
    index = defaultdict(list)
    for rel, lines in files.items():
        norm = [_strip_comment(l).strip() for l in lines]
        for i in range(len(norm) - DUP_BLOCK + 1):
            window = [l for l in norm[i:i + DUP_BLOCK]]
            if sum(1 for l in window if l) < DUP_BLOCK - 1:
                continue  # 空行太多不算抄袭
            if all(len(l) < 4 for l in window if l):
                continue
            key = "\n".join(window)
            index[key].append("%s:%d" % (rel, i + 1))
    out = []
    reported = set()
    for key, where in index.items():
        if len(where) < 2:
            continue
        first = key.splitlines()[0][:40]
        if first in reported:
            continue
        reported.add(first)
        out.append(("warn", "C8", "有 %d 处连续 %d 行相同（起点：%s）" % (len(where), DUP_BLOCK, first),
                    "、".join(where[:4])))
    return out


def run(targets: list, include_dups: bool = True) -> dict:
    issues = []
    files = {}
    for rel in targets:
        p = H / rel if not Path(rel).is_absolute() else Path(rel)
        if p.exists():
            files[rel] = p.read_text(encoding="utf-8", errors="replace").splitlines()
        issues.extend(check_file(rel))
    if include_dups:
        issues.extend(dup_blocks(files))
    fails = [i for i in issues if i[0] == "fail"]
    warns = [i for i in issues if i[0] == "warn"]
    return {"ok": not fails, "fails": fails, "warns": warns,
            "files": len(targets), "lines": sum(len(v) for v in files.values())}


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    targets = args or (DEFAULT_TARGETS + EXTRA_TARGETS if "--all" in sys.argv else DEFAULT_TARGETS)
    res = run(targets)
    if "--json" in sys.argv:
        print(json.dumps({"ok": res["ok"],
                          "fail_count": len(res["fails"]),
                          "warn_count": len(res["warns"]),
                          "fails": [list(x) for x in res["fails"][:20]]},
                         ensure_ascii=False))
        return 0 if res["ok"] else 1

    print("查了 %d 个文件、共 %d 行" % (res["files"], res["lines"]))
    if res["warns"]:
        print("\n提醒 %d 处（不阻断，但该收拾）：" % len(res["warns"]))
        for lvl, code, msg, where in res["warns"]:
            print("  %s %s  %s" % (code, msg, where))
    if res["fails"]:
        print("\n失败 %d 处：" % len(res["fails"]))
        for lvl, code, msg, where in res["fails"]:
            print("  %s %s  %s" % (code, msg, where))
        return 1
    print("\n全部通过（%d 处提醒是我该清理的债，不是失败）" % len(res["warns"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
