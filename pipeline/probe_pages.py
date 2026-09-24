#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""结构探针：从 paper.aux 的 \newlabel 记录读出锚点 → 页码／编号。

为什么要它：本机 AI 无视觉输入，PDF 版式不能靠肉眼确认；而改动正文会让分页移动，
使上一轮登记过的探针页码失效。把锚点页码变成可解析、可复跑的事实，就能在改动前后
逐条对比“哪些页码动了”，避免用“撤销已验证状态”换不确定收益。

用法：<python3> pipeline/probe_pages.py
输出：命令行表格 + out/experiment/page-probe.json；末行 RESULT: PASS/CHECK。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUX = ROOT / "paper.aux"
OUT = ROOT / "out" / "experiment"

KEY = [
    "fig:gradient", "tab:failures", "tab:gradient", "tab:injection",
    "sec:failure", "sec:mutex", "sec:metrics", "sec:experiment", "sec:checklist",
]


def main():
    text = AUX.read_text(encoding="utf-8", errors="replace")
    pat = re.compile(r"\\newlabel\{([^}]*)\}\{\{([^}]*)\}\{([0-9]+)\}")
    labels = {}
    dup = []
    for m in pat.finditer(text):
        key, num, page = m.group(1), m.group(2), int(m.group(3))
        if key in labels:
            dup.append({"label": key, "first": labels[key], "second": {"number": num, "page": page}})
        labels[key] = {"number": num, "page": page}

    probe = {k: labels[k] for k in KEY if k in labels}
    missing = [k for k in KEY if k not in labels]
    same_number = {}
    for k in KEY:
        if k in labels:
            same_number.setdefault(labels[k]["number"], []).append(k)
    suspicious = {n: ks for n, ks in same_number.items() if len(ks) > 1}

    res = {"total_labels": len(labels), "probe": probe, "missing": missing,
           "duplicate_labels": dup, "shared_numbers": suspicious}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "page-probe.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    for k in KEY:
        if k in labels:
            print("%-16s 编号=%-6s 页码=p%s" % (k, labels[k]["number"], labels[k]["page"]))
    if missing:
        print("MISSING: " + ", ".join(missing))
    if dup:
        print("DUPLICATE-LABEL: " + json.dumps(dup, ensure_ascii=False))
    if suspicious:
        print("SHARED-NUMBER: " + json.dumps(suspicious, ensure_ascii=False))
    print("RESULT: %s" % ("PASS" if not missing and not dup else "CHECK"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
