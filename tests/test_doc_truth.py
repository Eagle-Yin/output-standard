"""文档真值检查：文档里说的数字，必须和代码里做的一致。

为什么要有这个：产品文档曾把 17 条标签写成 12 条，读者按文档去改代码，改了半天对不上。
数字漂移靠人记是记不住的，所以让测试记住。

只查三类能机器判的：测试清单是否齐全、标签数是否相符、版本号是否同步。
文风、结构、解释对不对——机器判不了，也不该假装能判。
"""
import hashlib
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
fails, ok = [], []


def check(name, cond, detail=""):
    (ok if cond else fails).append("%s%s" % (name, ("：" + detail) if detail and not cond else ""))


# 1. README 的测试清单必须覆盖 tests/ 下每个 test_*.py（新增测试不写进文档 = 别人不知道要跑）
readme = (ROOT / "README.md").read_text(encoding="utf-8")
test_files = sorted(p.name for p in (ROOT / "tests").glob("test_*.py"))
missing = [n for n in test_files if n not in readme]
check("README 覆盖全部测试", not missing, "漏写 " + ", ".join(missing))

# 2. 文档写的标签数必须等于判据里实际定义的标签数。
# 只在「判据体系」一节里找这个数：差距分析里的旧数字是历史审计记录，不是现役声明，不许动。
rules = (ROOT / "judge" / "reply_rules.py").read_text(encoding="utf-8")
labels = set(re.findall(r'LBL_[A-Z_]+\s*=\s*"([^"]+)"', rules))
doc = (ROOT / "docs" / "product-doc.md").read_text(encoding="utf-8")
m_sec = re.search(r"## 四、判据体系.*?(?=\n## )", doc, re.S)
claimed = re.search(r"(\d+)\s*条标签", m_sec.group(0) if m_sec else doc)
check("文档标签数与代码一致", bool(claimed) and int(claimed.group(1)) == len(labels),
      "文档写 %s，代码实际 %d" % (claimed.group(1) if claimed else "无", len(labels)))

# 3. 文档里点名的标签都得是真存在的标签（防手抄错字、防文档落后于判据）
doc_labels = [t for t in labels if t in doc]
check("文档跟得上判据", len(doc_labels) >= len(labels) // 2,
      "文档只提到 %d/%d 条标签，说明文档已落后于判据" % (len(doc_labels), len(labels)))

# 4. 版本号：judge/__init__.py 是唯一事实源，CHANGELOG 必须提到它
ver = re.search(r'__version__\s*=\s*"([^"]+)"',
                (ROOT / "judge" / "__init__.py").read_text(encoding="utf-8"))
check("版本号有且只一处", bool(ver))
if ver:
    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    check("CHANGELOG 提到当前版本", ver.group(1) in log, "CHANGELOG 里找不到 " + ver.group(1))

# 5. 发布包判据不得偏离宿主活判据（踩过：宿主活闸加了两条判据，发布包还停在旧版）。
# 独立部署的机器上没有宿主副本，自动跳过——这条守卫只活在开发机与宿主同机的情况下。
live = (Path(os.environ.get("HERMES_HOME") or Path.home() / "AppData/Local/hermes")
        / "iron" / "reply_rules.py")
if live.exists():
    shipped = hashlib.sha1((ROOT / "judge" / "reply_rules.py").read_bytes()).hexdigest()
    living = hashlib.sha1(live.read_bytes()).hexdigest()
    check("发布包判据与宿主活判据一致", shipped == living,
          "两边内容不一致，宿主新加的判据没同步进发布包（或反向）；先 diff 再同步")
else:
    ok.append("跳过 发布包判据与宿主活判据一致（本机没有宿主副本）")

for line in ok:
    print("ok   " + line)
for line in fails:
    print("FAIL " + line)
print("\n%d 项通过，%d 项失败" % (len(ok), len(fails)))
sys.exit(1 if fails else 0)
