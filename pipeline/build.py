#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""编译前硬门禁：引用核验不通过，就不允许编译。

链路（前一环非零即中止，不进入下一环）：
  1. 引用核验   pipeline/check_refs_static.py   失败 → 中止，退出码 20
  2. 编译        tectonic -X compile paper.tex  失败 → 中止，退出码 20
  3. 产物复核    页数下限 / 参考文献条目数 / 未定义引用 / 排版告警计数
  4. 报告        out/experiment/gate-report.json + 单行 RESULT

设计要点：门禁是流程约束而不是事后检查——第 1 环失败时第 2 环根本不会执行，
因此“核验不通过的稿子进不了编译产物”是可从退出码核对的机械事实。

用法：
  <python3> pipeline/build.py              # 完整门禁（核验 + 编译 + 复核）
  <python3> pipeline/build.py --gate-only  # 只跑核验环（快，不编译）
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIPELINE = ROOT / "pipeline"
OUT = ROOT / "out" / "experiment"

PAGE_FLOOR = 16  # 页数下限：低于此值说明章节丢失
BIB_FLOOR = 31   # 参考文献条目下限：任何一条被丢掉都应被拦住

TECTONIC_CANDIDATES = [
    os.environ.get("TECTONIC", ""),
    "/Users/xiaowo/.cache/c2latex/tectonic",
    shutil.which("tectonic") or "",
]


def find_tectonic():
    for cand in TECTONIC_CANDIDATES:
        if cand and Path(cand).exists():
            return cand
    return None


def run(cmd):
    p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    tail = (p.stdout or p.stderr or "").strip().splitlines()[-3:]
    return p.returncode, tail


def step_verify_citations():
    return run([sys.executable, str(PIPELINE / "check_refs_static.py")])


def step_compile(tectonic):
    return run([tectonic, "-X", "compile", "paper.tex", "--keep-logs", "--keep-intermediates"])


def step_inspect():
    log = (ROOT / "paper.log").read_text(encoding="utf-8", errors="replace")
    bbl = (ROOT / "paper.bbl").read_text(encoding="utf-8", errors="replace")
    m = re.search(r"Output written on paper\.(?:pdf|xdv) \((\d+) pages", log)
    undefined = log.count("undefined on input line")
    if "There were undefined references" in log:
        undefined = max(undefined, 1)
    return {
        "pages": int(m.group(1)) if m else 0,
        "bibitems": len(re.findall(r"\\bibitem", bbl)),
        "undefined_refs": undefined,
        "underfull_hbox": log.count("Underfull \\hbox"),
        "overfull_hbox": log.count("Overfull \\hbox"),
        "pdf_bytes": (ROOT / "paper.pdf").stat().st_size if (ROOT / "paper.pdf").exists() else 0,
    }


def main():
    gate_only = "--gate-only" in sys.argv
    report = {"gate_only": gate_only, "tectonic": find_tectonic()}
    reasons = []
    ok = True

    rc, tail = step_verify_citations()
    report["citation_gate"] = {"exit_code": rc, "tail": tail}
    print("[1/3] 引用核验 -> exit %d (%s)" % (rc, "PASS" if rc == 0 else "FAIL"))
    if rc != 0:
        ok = False
        reasons.append("引用核验未通过（exit %d）：按硬门禁中止，不进入编译" % rc)

    if ok and not gate_only and not report["tectonic"]:
        ok = False
        reasons.append("找不到 tectonic 可执行文件，无法编译")

    if ok and not gate_only:
        rc, tail = step_compile(report["tectonic"])
        report["compile"] = {"exit_code": rc, "tail": tail}
        print("[2/3] 编译 paper.tex -> exit %d" % rc)
        if rc != 0:
            ok = False
            reasons.append("编译失败（exit %d）" % rc)

    if ok and not gate_only:
        info = step_inspect()
        report["artifacts"] = info
        print("[3/3] 产物复核 pages=%d bibitems=%d undefined=%d underfull=%d overfull=%d"
              % (info["pages"], info["bibitems"], info["undefined_refs"],
                 info["underfull_hbox"], info["overfull_hbox"]))
        if info["pages"] < PAGE_FLOOR:
            ok = False
            reasons.append("页数 %d 低于下限 %d（疑似章节丢失）" % (info["pages"], PAGE_FLOOR))
        if info["bibitems"] < BIB_FLOOR:
            ok = False
            reasons.append("参考文献条目 %d 低于下限 %d" % (info["bibitems"], BIB_FLOOR))
        if info["undefined_refs"]:
            ok = False
            reasons.append("存在未定义引用 %d 处" % info["undefined_refs"])
        if info["underfull_hbox"] or info["overfull_hbox"]:
            reasons.append("排版告警：underfull %d、overfull %d（不阻断，但需记录）"
                           % (info["underfull_hbox"], info["overfull_hbox"]))

    report["result"] = "PASS" if ok else "FAIL"
    report["reasons"] = reasons
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "gate-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in reasons:
        print("  - " + r)
    print("RESULT: %s" % report["result"])
    return 0 if ok else 20


if __name__ == "__main__":
    sys.exit(main())
