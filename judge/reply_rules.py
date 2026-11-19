"""回复判据：什么样的回复算合格。一个文件，零外部依赖，谁都能拿走用。

## 这是什么

一套**纯函数**判据库。给它一段成稿，它告诉你哪几条不合格。
它不知道 Hermes、不知道 LiteLLM、不读配置、不写文件、不联网。
只要你用 Python 3.8+，把它拷走就能用：

    from reply_rules import review
    review("我改好了")        # ['完成类断言无本轮输出']
    review("我改好了，exit=0")  # []

## 为什么单独成文件

原来这 233 行混在一个 1114 行的平台钩子里。想把这套规范搬到别的平台，
得先把平台相关的东西全部剥掉——那就没人搬得动。抽出来之后：
- 平台侧只剩「什么时候调用它」；
- 判据侧只剩「什么算合格」。
两者互不牵连，换平台只需重写调用方。

## 判据怎么组织

按「最容易犯、代价最大」排：
1. **说了完成却没有证据**——最伤信任，优先判。
2. **数字凭空来**——最伤判断，且读者无从察觉。
3. **把活推回给用户**——最伤效率。
4. **话不好读**（日志堆砌、过程播报、AI 套话、指路式交付）。
5. **形状不对**（缺结论节、缺要点节、缺自检注脚）。

## 设计约束（改之前先读）

- **宁可漏判，不可误判。** 误判会让人把整条闸关掉，那就一条都剩不下。
  所以：引号里的内容一律豁免；否定句里的禁用词豁免；普通计数不查。
- **判据认「有没有交代」，不认「交代得对不对」。** 内容真假要人来看。
- **同一份判据只此一处。** 别的模块要判定，import 这里，不许抄正则。
"""
from __future__ import annotations

import re

__all__ = ["review", "LBL_CLAIM", "LBL_LAZY", "LBL_TOTAL", "LBL_NAY",
           "LBL_LOGDUMP", "LBL_POINTING", "LBL_ROLLBACK", "LBL_PLACE",
           "LBL_SLOP", "LBL_PROCESS", "LBL_NUM", "LBL_NOBANNER",
           "LBL_FOOTERJUNK", "LBL_WALL", "LBL_LONGPARA"]

# ════════════════════════════════════════════════════════════
#  一、引述与否定豁免
#  这两条必须先跑，否则「讨论规则本身」会被判违规——一讨论就误伤，
#  最后逼得人只能绕着说话，判据就成了笑话。
# ════════════════════════════════════════════════════════════

# 成对引号/反引号里的文字 = 在引用别人的话，不算自己违规。
QUOTE_RE = re.compile(
    r"[「『\"'`][^」』\"'`]{0,600}[」』\"'`]"
    # 中文弯引号是两个不同字符，必须成对列举，否则“已修好”这类被引述的断言照样算违规。
    r"|“[^”]{0,600}”|‘[^’]{0,600}’"
)

# 否定句里的禁用词不算推回（「到此没有任何待办项」是在报清零，不是把活推回去）。
NEG_RE = re.compile(
    r"(?:没有任何|没有|不存在|零|无)(?:的)?(?:(?:遗留|未决|其他|其它|任何|遗漏)(?:的)?)*"
    r"(?:下一步|待办|遗留|未决)(?:项|事项)?"
)

# ════════════════════════════════════════════════════════════
#  二、证据判据：说完成就得有本轮坐标
# ════════════════════════════════════════════════════════════

CLAIM_RE = re.compile(
    # 允许「已全部完成 / 都已经补齐 / 已基本收敛」这类副词插入，否则「已全部完成」漏判。
    r"(?:已|已经|均已|全都|都)(?:经)?[^，。；！？\n]{0,8}?"
    r"(?:补齐|收敛|修复|修好|改好|修完|改完|跑通|搞定|完成|配置|生效|落位|写入|到位|通过|覆盖|就绪|上线|迁移完)"
    r"|(?:全部|全量|全覆盖|全数)[^，。；！？\n]{0,4}?(?:完成|补齐|覆盖|到位|通过|就绪|落位)"
    # 口语常省略「已/都」：「改完了」「跑通了」。
    # 但裸词也出现在非断言位置（「修好的文件」「做完再跑一次」：一个当定语、一个当条件从句）。
    # 收紧为「后接 了，或止于句读」，既保住简称断言，又不误伤定语与从句。
    r"|(?:改完|修好|修完|跑通|搞定|做完|部署完)(?:了|(?=[，。；！？\n]|$))"
)

# 「证据」只认能回到本轮输出的坐标：退出码 / HTTP 码 / 哈希 / 文件:行号 / 通过数。
# 不认裸箭头、不认裸文件名——那两样谁都能打出来。
TRACE_RE = re.compile(
    r"exit\s*=?\s*\d|(?:退出码|返回码)\s*[:：=]?\s*\d"
    r"|\b(?:[A-Za-z][A-Za-z0-9_]*_)?[Rr][Cc]\s*=\s*\d|http\s*=\s*\d{3}|sha256[:=]\s*[0-9a-f]{6,}"
    r"|[\w./\\-]+\.(?:py|md|json|yaml|yml|txt|html|csv|sqlite3)[:：]\d+"
    # 表格里文件在表头、行号在单元格是常态，裸 文件:行号 也算；
    # 前置字符不能是数字/字母，避免把时间 11:37 当证据。
    r"|(?<![\d\w])[:：]\d{1,4}\b"
    r"|\b\d+/\d+\s*(?:passed|通过)\b"
    r"|\bL\d+\b|\b\d+\s*(?:行|lines)\b|MEDIA:/"
)

LBL_CLAIM = "完成类断言无本轮输出"
LBL_LAZY = "未调查即结论"
LBL_TOTAL = "全量断言无清单"

LAZY_RE = re.compile(r"根据经验|凭印象|无需调查|我记得|想当然|不用查也知道")
TOTAL_RE = re.compile(r"全部覆盖|无漏级|全覆盖|均已|全部到位|全部通过|五处|六处")

# ════════════════════════════════════════════════════════════
#  三、数字判据：不许凭空来
#
#  模型错数字不是态度问题，是能力问题——它模仿数字的形状，不做真实运算。
#  所以「要求它给计算说明」只提高发现率，不提高正确率：它照样能编一个像样的算式。
#  分三层治：引用型给出处、计算型给算式（由 numcheck 真复算）、估算型标「推断」。
# ════════════════════════════════════════════════════════════

NUM_UNIT_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|％|倍|万元|亿元|元|小时|分钟|天|月|年|GB|MB|条要求|次|人天)"
)
# 这些词一出，说明这句在「报账」，数字必须能追到源头。
NUM_CLAIM_RE = re.compile(r"占比|约为|合计|总计|平均|提升了|降低了|达到|节省|耗时|增长|下降")
# 算式写法：=0.05*65536*1.4= 4587
EXPR_RE = re.compile(r"=\s*[0-9+\-*/().\s]{3,60}?=")

LBL_NUM = "数字无依据或算式不复算"

# ════════════════════════════════════════════════════════════
#  四、推回与措辞判据
# ════════════════════════════════════════════════════════════

PUSHBACK_RE = re.compile(r"下一步|要不要我|等你确认|待办|如需继续|请告知我|你可以自己")
HEDGE_RE = re.compile(r"应该可以|理论上|大概是|估计没问题|应该是这样")

# 承诺未来动作只认「第一人称 + 时间副词 + 动作」这一种形态。
# 反例：`audit 立刻报错` 叙述的是刚发生的事，不该被当成承诺（误拦与漏放同罪）。
PROMISE_RE = re.compile(
    r"我接着做|稍后我会|待会儿(?:我)?[^，。；\n]{0,6}(?:再|补|补上|改|看|跑)"
    r"|(?:我|我们)[^，。；\n]{0,6}(?:马上|立刻|稍后|待会儿)[^，。；\n]{0,6}(?:补|改|做|跑|查|看|写|修)"
)

# 过程性否定：说「不行/做不到」却不给替代路径。
# 判定对象不是「有没有证据」，而是「有没有给方式方法」——所有问题都有解法。
NAY_RE = re.compile(
    r"(不行|做不了|做不成|解决不了|解不了|搞不定|弄不了|没法|无解|"
    r"做不到|办不到|无法(?:自动|完成|实现|获取|读取|支持|升级|更新|解决|处理)|"
    r"不支持|没有办法|不可能|不现实|行不通)"
)
PATH_RE = re.compile(
    r"(改用|改走|改成|换成|换一种|换条|换用|替代|代替|绕过|降级|拆成|拆分为|"
    r"分两步|分阶段|转用|另辟|变通|绕开|workaround|办法|方案是|"
    r"可以这么|用[^，。；\n]{1,18}(?:做|跑|取|实现|顶)|先[^，。；\n]{1,12}再)"
)
LBL_NAY = "过程性否定未给替代路径"
LBL_LOGDUMP = "结论用日志搬运代替人话"

# 「结论里放推断」（2026-11-19 兵哥定）：结论必须是本轮实测或读到的整段事实。
# 兵哥原话：「禁止推断：必须实测，必须沙箱实测」。推断可以留在要点/未解项，但绝不能当结论。
# 与上面 HEDGE_RE（未验证措辞）分家、各管一处：曾因共用同名互相遮蔽，C3 判失败。
CONCL_HEDGE_RE = re.compile(r"推断|取决于|有可能|或许|多半|大概|预计|估计|应该可以")
LBL_HEDGE = "结论含推断"
# 横幅只盖最终那一份成稿：一篇回复里出现两次，读者就分不清哪份是定的。
BANNER_ANY_RE = re.compile(r"(?m)^\s*>\s*✅\s*\*\*[^\n]{0,40}(?:审查已通过|质检已通过)")

# LX66 载体锚点：LX66 要求「执行中的障碍必须给替代路径」，判据就落在这两个正则上。
# token 写在这里而不是引用位置，是因为引用位置每轮都会挪，登记册指向固定常量更稳。
LX66 = "[LX66]"

# ════════════════════════════════════════════════════════════
#  五、交付判据：别把活推回给用户
# ════════════════════════════════════════════════════════════

# 指路式交付：把核对推给对方（「详见附件 / 你自己看 / 文件在这里」）。
POINTING_RE = re.compile(r"详见(?:附件|报告|文档)|见(?:上述)?文件|你自己(?:看|打开)|文件在这里")
# 宣告已部署/已切换，通篇却没有灾备与回滚。
LANDED_RE = re.compile(r"已(?:经)?(?:部署|切换|上线|替换|迁移)|完成(?:了)?(?:部署|切换|上线)")
ROLLBACK_RE = re.compile(r"回滚|回退|灾备|备份|恢复原样|退回原状")
# 敷衍占位：整行只写「略 / 见上文 / 自行查看」，等于没写。
# 整行匹配，避免「策略」「战略」误命中。
PLACEHOLDER_RE = re.compile(
    r"(?m)^[ \t>*-]*(?:见上文|同上|此处省略|（略）|略|自行查看|按需补充)[。；.]?[ \t]*$")
# 模板占位符照抄：真模型实测会把「x/100」「0.xx」原样搬进注脚，
# 读者看到的是一个没填的表单。数字栏位必须是真数字。
FILLED_RE = re.compile(r"（\s*\d+\s*/\s*100\s*[，,]\s*置信度\s*0?\.\d+\s*）")
PLACEHOLDER_NUM_RE = re.compile(r"[xX]\s*/\s*100|置信度\s*0?\.[xX]+|score\s*[xX]")

LBL_POINTING = "指路式交付未自含"
LBL_ROLLBACK = "落地未给回滚与灾备"
LBL_PLACE = "敷衍占位"
LBL_FILL = "评分栏位未填"

# ════════════════════════════════════════════════════════════
#  六、可读性判据：去 AI 味、禁过程播报
#
#  依据：维基百科 WP:AISIGNS（社区维护的「AI 写作特征」清单）
#  与微软/谷歌写作规范（说人话、少修饰、别复述）。
#  只收「一眼假」的四类，宁缺不滥。
#  故意不拦破折号与三段式排比：被认可的回复本身就用破折号，拦了就是误伤正确风格。
# ════════════════════════════════════════════════════════════

SLOP_OPEN = re.compile(r"(?:这是一个非常好的问题|好问题[！!]|很高兴(?:为你|为您)(?:解答|回答))")
SLOP_CLOSE = re.compile(r"(?:希望(?:以上|这)(?:对|能对)(?:你|您)(?:有|有所)帮助|"
                        r"如有(?:其他|其它)?(?:疑问|问题)[，,]?[^。！!\n]{0,12}(?:欢迎|随时))")
SLOP_RESTATE = re.compile(r"(?m)^[ \t>*-]*(?:综上所述|总而言之|总的来说|总的来说就是)")
SLOP_PUFF = re.compile(r"(?:至关重要|深刻(?:的)?意义|里程碑(?:式)?|赋能|抓手|赋予[^，。\n]{0,8}新(?:的)?(?:活力|内涵))")

LBL_SLOP = "AI味套话"

# 机器横幅污染：插件曾把「铁律自检（自动追加）」贴进正文，重复且机器味重。
# 这类文本只该进账本与 trace，不许进回复。
BANNER_RE = re.compile(r"铁律自检（自动追加）|合并闸未通过")
LBL_BANNER = "机器横幅污染正文"

# 形状判据（模板长什么样）。这部分依赖调用方的模板约定，
# 但结论是同一个——所以也放这里，只是门槛（多长起判）由调用方传。
SHAPE_MIN_CHARS = 400
BOUNDARY_RE = re.compile(r"(?m)^#{0,4}\s*⚠️?\s*边界")
FOOTER_RULE_RE = re.compile(r"(?m)^---\s*$")
FOOTER_SELF_RE = re.compile(
    r"(?m)^>\s*\*\*[^\n]*(?:铁律质检|自检)[^\n]*(?:\d{1,3}/100|0\.\d+|\d{1,3}%)")
FOOTER_EXTRA = ("回滚点", "复盘四问", "任务锚")

# ── 正式回复横幅（2026-11-19 定）────────────────────────────
# 读者拿到一屏文字，第一眼要能判断「这是审过的成稿，还是过程话」。
# 用引用块+状态符做横幅，不依赖 HTML、不依赖颜色——markdown 到哪都渲染成一条横幅；
# 桌面端能加粗，聊天端退化成引用条，最差也读得出「已通过」三个字。
BANNER_OK_RE = re.compile(
    r"\A\s*>\s*✅\s*\*\*[^\n]{0,40}(?:审查已通过|质检已通过)")
LBL_NOBANNER = "缺正式回复横幅"

# ── 注脚要体面（2026-11-19 定）──────────────────────────────
# 注脚是给读者的最后一句人话，不是给程序的日志尾巴。
# 出现 hits[]、exit=0、换行被吞掉的分隔线，读者只会问「这是什么」。
FOOTER_JUNK_RE = re.compile(
    r"hits\s*\[|hits\s*=|exit\s*=\s*\d|退出码\s*\d|字符数|bytes|sha1?=|\\n")
LBL_FOOTERJUNK = "注脚混入机器串"

# ── 正文层级与精简（2026-11-19 定）──────────────────────────
# 阈值来自实测：上一版被认可的成稿里，最长正文段落 248 字（粗体引导+一句解释），
# 表格行不算段落。所以 260 字是「超过就该拆」的线，不是拍的。
PARA_MAX_CHARS = 260
LIST_ITEM_RE = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
# 要点节里没有粗体引导也没有表格 = 一堵文字墙，层级全平。
SECTION_LEAD_RE = re.compile(r"(?m)^\s*(?:(?:[-*]\s*)?\*\*[^*\n]{2,40}\*\*|\|)")
LBL_WALL = "要点未分层：无粗体引导也无表格"
LBL_LONGPARA = "正文段落过长：拆成一条一事"

# 「结论用日志搬运代替人话」：结论节通篇拿脚本、路径、退出码、函数名当解释。
LOGSYM_RE = re.compile(
    r"[\\/][\w.\-/]*\.(?:py|md|json|ya?ml|db|log|txt|sh|ps1)\b|\b(?:exit|rc|status)=")
HUMANWHY_RE = re.compile(r"因为|由于|目的|负责|调用|触发|导致|为了|结果")

# 过程播报：写给自己看的句子混进正文（「定稿 hits[]，正式回复如下」「草稿已过闸」）。
# 审查是内部动作，读者只该看结论。
# 注意：这是「对自己说话」的句式，不是禁词——判前先剥引述，否则一讨论就误伤。
PROCESS_NOISE_RE = re.compile(
    r"(?:定稿|草稿)[^。\n]{0,12}(?:hits|通过|已过闸)|正式回复如下|以下是我的回复|"
    r"我先(?:跑|看|读|查)了[^。\n]{0,10}(?:脚本|文件|配置)"
)
LBL_PROCESS = "正文混入过程播报"

# ════════════════════════════════════════════════════════════
#  判定主体
# ════════════════════════════════════════════════════════════

CLAIM_LABELS = (LBL_CLAIM, LBL_LAZY, LBL_TOTAL, LBL_LOGDUMP)


def _strip_quotes(text: str) -> str:
    """抹掉引述内容，留下「自己说的话」。

    用「。」而不是空格填充：引述被抽走后，前后两截会拼接在一起，
    例如「A 与 `B` 都报了（`失败 3 项`）」剥离后变成「A 与  都报了（  ：基线通过」，
    中间只剩空格，于是「都报了…通过」被当成一句完成类断言——而它的坐标刚好在反引号里被抽走。
    填空格等于伪造了一句自己没说过的话；填句号让它止于边界。
    """
    return QUOTE_RE.sub("。", text or "")


def units(text: str) -> list:
    """切判定单元：表格行连成一块（文件在表头、行号在单元格），其余按句切。

    为什么要切：整篇判会出现「一句 exit=0 给另外五句编造作保」——一处证据罩全篇。
    """
    out = []
    buf = []
    for line in (text or "").splitlines():
        if line.lstrip().startswith("|"):
            buf.append(line)
            continue
        if buf:
            out.append("\n".join(buf))
            buf = []
        out.extend(s for s in re.split(r"[。！？；]", line) if s.strip())
    if buf:
        out.append("\n".join(buf))
    return out


def claim_offenders(text: str) -> list:
    """有完成类断言、但同一单元内没有坐标的那些单元（返回截断串，便于指认）。"""
    # 横幅是程序盖的章（「审查已通过，以下是正文」），不是人写的完成断言。
    # 必须整行摘掉——只摘匹配到的那半句，剩下的「，以下正式回复**」会变成
    # 一句无坐标的完成断言，判据自己把新版式判死（沙箱实测过）。
    head = BANNER_OK_RE.match(text)
    if head:
        nl = text.find("\n", head.end())
        text = text[nl + 1:] if nl >= 0 else ""
    bad = []
    for u in units(text):
        if CLAIM_RE.search(_strip_quotes(u)) and not TRACE_RE.search(u):
            bad.append(re.sub(r"\s+", " ", u).strip()[:80])
    return bad


def _load_numcheck():
    """找复算器。找不到就返回 None——判据不因为缺它而假装判过。"""
    try:
        import numcheck  # 同目录
        return numcheck
    except ImportError:
        pass
    try:
        import importlib.util
        from pathlib import Path

        spec = importlib.util.spec_from_file_location(
            "numcheck", Path(__file__).with_name("numcheck.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def _num_hits(text: str, numcheck=None) -> list:
    """数字判据：算式复算不上账，或报账数字既无出处也无算式。"""
    hits = []
    text = text or ""
    checker = numcheck if numcheck is not None else _load_numcheck()
    if checker is not None and checker.scan(text):
        return [LBL_NUM]  # 算错了，先报这个，别的不用查了
    for u in units(text):
        plain = _strip_quotes(u)
        if not NUM_CLAIM_RE.search(plain) or not NUM_UNIT_RE.search(plain):
            continue
        if TRACE_RE.search(u) or EXPR_RE.search(u):
            continue
        hits.append(LBL_NUM)
        break
    return hits


def _check_evidence(text: str, core: str) -> list:
    """① 证据：说了完成就得给坐标；凭印象下结论要拦；全量断言要配清单。"""
    hits = []
    if claim_offenders(text):
        hits.append(LBL_CLAIM)
    if LAZY_RE.search(core):
        hits.append(LBL_LAZY)
    if TOTAL_RE.search(core):
        # 清单本身也是证据：文件名常写在反引号里，判 core 会把清单抹空。
        named = set(re.findall(r"[\w./\\-]+\.(?:py|md|json|yaml|yml|txt|html|csv)", text or ""))
        counted = re.search(r"\d+\s*(?:处|个|项|条|份)", text or "")
        if len(named) < 2 and not counted:
            hits.append(LBL_TOTAL)
    return hits


def _check_wording(core: str, text: str) -> list:
    """② 措辞：别把活推回去（下一步/要不要我）、别未验证就说准、别许空头承诺。"""
    hits = []
    for rx, label in ((PUSHBACK_RE, "推回话术"),
                      (HEDGE_RE, "未验证措辞"),
                      (PROMISE_RE, "承诺未来动作")):
        if rx.search(core):
            hits.append(label)
    if NAY_RE.search(core) and not PATH_RE.search(text or ""):
        hits.append(LBL_NAY)
    return hits


def _check_delivery(core: str, text: str) -> list:
    """③ 交付：别让读者自己去找、别省略成占位、说了已部署就得给回滚。"""
    hits = []
    if PLACEHOLDER_RE.search(text or "") or PLACEHOLDER_NUM_RE.search(text or ""):
        hits.append(LBL_PLACE)
    if POINTING_RE.search(core) and "MEDIA:" not in (text or "") \
            and not re.search(r"[A-Za-z]:[\\/]", text or ""):
        hits.append(LBL_POINTING)
    if LANDED_RE.search(core) and not ROLLBACK_RE.search(text or ""):
        hits.append(LBL_ROLLBACK)
    return hits


def _check_readability(text: str, core: str) -> list:
    """④ 可读性：去 AI 套话、禁过程播报、去机器横幅。"""
    hits = []
    if BANNER_RE.search(text or ""):
        hits.append(LBL_BANNER)
    if (SLOP_OPEN.search(text or "") or SLOP_CLOSE.search(text or "")
            or SLOP_RESTATE.search(text or "") or SLOP_PUFF.search(text or "")):
        hits.append(LBL_SLOP)
    if PROCESS_NOISE_RE.search(core):
        hits.append(LBL_PROCESS)
    return hits


def _check_shape(text: str) -> list:
    """⑤ 形状：横幅在最前、结论在前、要点在后、末尾有体面注脚。短问答不查。"""
    text = text or ""
    if len(text) <= SHAPE_MIN_CHARS:
        return []
    hits = []
    i_c, i_p = text.find("🎯"), text.find("📌")
    if i_c < 0:
        hits.append("缺结论节")
    elif i_p < 0:
        hits.append("缺点要节")
    elif i_c > i_p:
        hits.append("模板乱序：🎯 须在 📌 之前")
    if BOUNDARY_RE.search(text):
        hits.append("边界节已废弃：风险并入要点")
    # 两条独立判：都缺就都报（旧版就是两条独立 if，迁移时不能悄悄合并成二选一）
    if not FOOTER_RULE_RE.search(text):
        hits.append("缺质检注脚的分隔线")
    if not FOOTER_SELF_RE.search(text):
        hits.append("缺质检注脚")
    if "收尾备注" in text:
        for lab in FOOTER_EXTRA:
            if not re.search(r"(?m)^>\s*\*\*[^\n]*" + lab, text):
                hits.append("收尾备注缺" + lab)
    # 结论节拿技术符号当解释，等于没解释
    rest = text[i_c:] if i_c >= 0 else text
    m = re.search(r"(?m)^#{0,4}\s*📌", rest)
    concl = rest[:m.start()] if m else rest
    tech = len(LOGSYM_RE.findall(concl)) + len(re.findall(r"\b\w+\(\)", concl))
    if tech >= 3 and not HUMANWHY_RE.search(concl):
        hits.append(LBL_LOGDUMP)
    # 结论节不许出现推断：读者拿它当事实用，推断混进去就成了假事实
    if CONCL_HEDGE_RE.search(_strip_quotes(concl)):
        hits.append(LBL_HEDGE)
    return hits


def _check_looks(text: str) -> list:
    """⑥ 好不好看：横幅、注脚体面、分层、段落长度。全是短问答豁免。

    为什么单独一组：这四条错在「读起来累」，不在「说得不对」。
    和证据、措辞混在一起，整改时人分不清该补证据还是该排版。
    """
    text = text or ""
    if len(text) <= SHAPE_MIN_CHARS:
        return []
    hits = []

    # 横幅：只盖在「成篇」的最终稿上。过程稿、半成品、追问草稿挂横幅，
    # 等于把草稿盖成终稿——兵哥 2026-11-19：「只有最后一个通过审查的才增加，
    # 否则如何确定哪个是最终的回复？」
    has_foot = "铁律质检" in text and bool(re.search(r"(?m)^\s*---\s*$", text))
    has_concl = bool(re.search(r"(?m)^#{0,4}\s*🎯", text))
    if not BANNER_OK_RE.match(text):
        if has_foot and has_concl:          # 成篇却没横幅，才是真缺
            hits.append(LBL_NOBANNER)
    elif not (has_foot and has_concl):
        hits.append("横幅盖在过程稿上")      # 有横幅却不成篇：草稿被盖了章
    # 横幅只盖最终那一份：重复出现就是「两份都说是终稿」，读者没法判断哪份算数
    if len(BANNER_ANY_RE.findall(text)) > 1:
        hits.append("横幅重复出现")

    # 注脚：分隔线之后那段不许有机器串（程序话留给账本，读者只该看人话）。
    m_rule = None
    for m in FOOTER_RULE_RE.finditer(text):
        m_rule = m
    if m_rule:
        tail = text[m_rule.end():]
        if FOOTER_JUNK_RE.search(tail):
            hits.append(LBL_FOOTERJUNK)

    # 分层：📌 要点节里既无粗体引导也无表格 = 一堵墙，扫不出结构。
    i_p = text.find("📌")
    if i_p >= 0:
        seg = text[i_p:]
        seg = re.split(r"(?m)^---\s*$", seg)[0]
        if not SECTION_LEAD_RE.search(seg):
            hits.append(LBL_WALL)

    # 精简：正文段落超过 PARA_MAX_CHARS 字就该拆。表格、代码块、引用块不算段落。
    body = re.split(r"(?m)^---\s*$", text)[0]
    body = re.sub(r"```.*?```", "", body, flags=re.S)
    body = re.sub(r"(?m)^\s*\|.*$", "", body)
    body = re.sub(r"(?m)^\s*>.*$", "", body)
    for para in re.split(r"\n\s*\n", body):
        # 列表项天生一行一条：整段都是列表就逐行量，不把它们拼成一堵墙。
        # 节标题（📌 要点）常与第一条列表粘在一起，先剔掉标题行再看。
        lines = [l.strip() for l in para.splitlines() if l.strip()]
        lines = [l for l in lines if not l.startswith("#") and not l.startswith("📌")]
        if not lines:
            continue
        if all(LIST_ITEM_RE.match(l) for l in lines):
            if any(len(l) > PARA_MAX_CHARS for l in lines):
                hits.append(LBL_LONGPARA)
                break
            continue
        p = para.strip()
        if p.startswith("#"):
            continue
        if len(p) > PARA_MAX_CHARS:
            hits.append(LBL_LONGPARA)
            break
    return hits


def review(text: str, numcheck=None) -> list:
    """审一段成稿，返回不合格标签列表；空列表＝通过。

    幂等：同一段文本反复调用结果一致（事前退回与事后记账共用这一份，结论必须相同）。

    参数 numcheck 可注入（测试时给替身），正常情况自动找同目录的 numcheck.py。

    七组判据各自独立、互不影响，一组挂了不会让别的组失声：
    证据 → 数字 → 措辞 → 交付 → 可读性 → 形状 → 好看。
    """
    if not (text or "").strip():
        return []
    # 横幅整行摘掉再判：它剩下的半句会被当成无坐标的完成断言（沙箱实测过）。
    head = BANNER_OK_RE.match(text)
    if head:
        nl = text.find("\n", head.end())
        body = text[nl + 1:] if nl >= 0 else ""
    else:
        body = text
    core = NEG_RE.sub(" ", _strip_quotes(body))
    hits = []
    hits += _check_evidence(body, core)
    hits += [h for h in _num_hits(body, numcheck) if h not in hits]
    hits += _check_wording(core, body)
    hits += _check_delivery(core, body)
    hits += _check_readability(body, core)
    hits += _check_shape(body)
    hits += _check_looks(text)
    # 去重保序
    seen = set()
    return [h for h in hits if not (h in seen or seen.add(h))]
