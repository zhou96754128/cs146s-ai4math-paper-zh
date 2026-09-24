#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""硬门禁负向验证：引用核验不通过时，编译环必须不执行。

为什么需要：pipeline/build.py 声称“核验失败即中止”，
但“声称”不是证据。本脚本用对照实验把它变成可核对的机械事实。

对照设计（同一环境、同一脚本、同一命令）：
  A 未变异（基线）  ：期望 result=PASS，且报告中存在 compile 环
  B 变异（未登记引用）：期望 result=FAIL，退出码 20，报告中不存在 compile 环
  C 变异（标题与登记不符）：同上；仅当 B 未能触发核验失败时执行

三个副本都放在临时目录，真实仓库只落一份证据：
  out/experiment/gate-negative-test.txt

用法： <python3> pipeline/gate_negative_test.py
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "experiment"
BAD_CITE = "zzz_gate_negative_probe_2026"


def make_copy():
    tmp = Path(tempfile.mkdtemp(prefix="c2-gate-neg-"))
    work = tmp / "proj"
    shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return work


def run_gate(work):
    p = subprocess.run([sys.executable, str(work / "pipeline" / "build.py")],
                       cwd=str(work), capture_output=True, text=True)
    text = (p.stdout or "") + (p.stderr or "")
    rp = work / "out" / "experiment" / "gate-report.json"
    rep = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else {}
    return {
        "exit_code": p.returncode,
        "result": rep.get("result"),
        "citation_exit": (rep.get("citation_gate") or {}).get("exit_code"),
        "compile_ring_present": "compile" in rep,
        "compile_ring_printed": "[2/3]" in text,
        "citation_tail": (rep.get("citation_gate") or {}).get("tail"),
        "tail_text": text.strip().splitlines()[-12:],
    }


def mutate_bad_cite(work):
    f = work / "paper.tex"
    src = f.read_text(encoding="utf-8")
    if "\\bibliography{references}" not in src:
        return False
    f.write_text(src.replace("\\bibliography{references}",
                             "\\cite{%s}\n\\bibliography{references}" % BAD_CITE),
                 encoding="utf-8")
    return True


def mutate_bad_title(work):
    f = work / "references.bib"
    src = f.read_text(encoding="utf-8")
    new, n = re.subn(r"title\s*=\s*\{[^}]*\}", "title = {Nonsense Title Qqq}", src, count=1)
    f.write_text(new, encoding="utf-8")
    return n == 1


def main():
    attempts = []

    base = run_gate(make_copy())
    attempts.append(("A 基线（未变异）", base, {"result": "PASS", "compile": True}))

    w1 = make_copy()
    mutate_bad_cite(w1)
    b = run_gate(w1)
    attempts.append(("B 变异：正文注入未登记引用 \\cite{%s}" % BAD_CITE, b,
                     {"result": "FAIL", "exit": 20, "compile": False}))

    if b["result"] != "FAIL":
        w2 = make_copy()
        mutate_bad_title(w2)
        c = run_gate(w2)
        attempts.append(("C 变异：references.bib 标题与登记不符", c,
                         {"result": "FAIL", "exit": 20, "compile": False}))

    def verdict(label, got, want):
        if label.startswith("A"):
            return got["result"] == "PASS" and got["compile_ring_present"]
        return (got["result"] == "FAIL" and got["exit_code"] == 20
                and not got["compile_ring_present"] and not got["compile_ring_printed"])

    results = [(label, got, verdict(label, got, want)) for label, got, want in attempts]
    ok = all(v for _, _, v in results) and any(l.startswith("B") for l, _, _ in results)

    lines = ["# 硬门禁负向验证：引用核验失败 ⇒ 编译环不执行", "",
             "结论：**%s**" % ("PASS —— 门禁是流程约束，不是事后检查" if ok else "FAIL —— 门禁未短路，需修"),
             "",
             "同一环境、同一 `pipeline/build.py`、同一命令，仅改输入：", ""]
    for label, got, v in results:
        lines += ["## %s —— %s" % (label, "符合预期" if v else "不符合预期"), "",
                  "| 观测项 | 值 |", "|---|---|",
                  "| build.py 退出码 | `%s` |" % got["exit_code"],
                  "| 报告 result | `%s` |" % got["result"],
                  "| 引用核验环退出码 | `%s` |" % got["citation_exit"],
                  "| 报告中存在 compile 环 | `%s` |" % got["compile_ring_present"],
                  "| 输出出现 `[2/3]` 编译环 | `%s` |" % got["compile_ring_printed"], "",
                  "核验环 tail：", "", "```",
                  json.dumps(got["citation_tail"], ensure_ascii=False, indent=2), "```", "",
                  "build.py 输出末尾：", "", "```"] + got["tail_text"] + ["```", ""]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "gate-negative-test.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for label, got, v in results:
        print("%-52s exit=%s result=%s citation=%s compile_ran=%s -> %s"
              % (label, got["exit_code"], got["result"], got["citation_exit"],
                 got["compile_ring_present"], "OK" if v else "MISMATCH"))
    print("RESULT: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 20


if __name__ == "__main__":
    sys.exit(main())
