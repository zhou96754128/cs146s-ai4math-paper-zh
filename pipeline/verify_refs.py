#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文献核验与 bib 自动生成脚本（防「引用造假」红线的机制保障）

机制：
  1) 用 arXiv 官方 API (export.arxiv.org/api/query?id_list=...) 拉取题录：标题、全部作者、首次提交日期、journal_ref、doi
  2) 用 Crossref API (api.crossref.org/works?query.bibliographic=...) 反查发表venue与正式 DOI
  3) 只有「arXiv 命中」或「Crossref 命中」的条目才会进入 references.bib
     —— 未命中的条目一律只写进「未核验」清单，绝不进入 bib

输出：
  lit/refs.json                  原始核验记录（可审计）
  lit/参考文献核验记录.md        人可读的核验报告（含命中/未命中）
  lit/references-verified.bib    仅由已核验条目生成的 BibTeX
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

LIT = "/Users/xiaowo/.cogseed-dev/userWorkSpace/我的挑战有哪些/C2-AI4Math论文/lit"
UA = "C2-ref-verify/1.0 (academic course assignment; contact: student)"
NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

# 待核验的 arXiv 条目
ARXIV_IDS = [
    # (A) 自然语言推理链 + 自我修正批判
    "2201.11903", "2205.11916", "2310.01798", "2310.12397", "2402.01817",
    # (G)/(H) 过程级验证与基准
    "2305.20050", "2211.14275", "2110.14168", "2103.03874", "2410.05229",
    # (B) 程序辅助推理
    "2211.10435", "2211.12588", "2308.07921",
    # (C) 工具增强 / 神经符号
    "2302.04761",
    # (F) 自动形式化与形式化间隙
    "2205.12615", "2403.18120", "2210.12283",
    # (E) LLM + 形式化定理证明
    "2009.03393", "2306.15626", "2109.00110", "2408.08152", "2310.04353", "2308.14306",
    # (I) 可复现性与数据污染
    "2405.14782", "2310.18018",
]

# 待核验的 DOI（非 arXiv 条目：证明助手、数学库、Curry-Howard、Nature 论文等）
CROSSREF_DOIS = [
    "10.1007/978-3-030-79876-5_37",   # Lean 4 (CADE-28)
    "10.1145/3372885.3373824",        # The Lean mathematical library (CPP 2020)
    "10.1145/2699407",                # Wadler, Propositions as Types (CACM)
    "10.1007/978-3-030-53518-6_1",    # Szegedy, towards autoformalization (CICM 2020)
    "10.1038/s41586-023-06747-5",     # AlphaGeometry (Nature)
    "10.1007/978-3-662-07964-5",      # Coq'Art (Bertot & Casteran)
]

# 待用「标题检索」在 Crossref 反查 venue 的条目（arXiv 元数据常缺会议信息）
TITLE_LOOKUPS = [
    "Chain-of-Thought Prompting Elicits Reasoning in Large Language Models",
    "Large Language Models are Zero-Shot Reasoners",
    "Large Language Models Cannot Self-Correct Reasoning Yet",
    "Let's Verify Step by Step",
    "Program of Thoughts Prompting: Disentangling Computation from Reasoning for Numerical Reasoning Tasks",
    "PAL: Program-aided Language Models",
    "Toolformer: Language Models Can Teach Themselves to Use Tools",
    "Autoformalization with Large Language Models",
    "Draft, Sketch, and Prove: Guiding Formal Theorem Provers with Informal Proofs",
    "Don't Trust: Verify -- Grounding LLM Quantitative Reasoning with Autoformalization",
    "LeanDojo: Theorem Proving with Retrieval-Augmented Language Models",
    "MiniF2F: a cross-system benchmark for formal Olympiad-level mathematics",
    "Training Verifiers to Solve Math Word Problems",
    "Measuring Mathematical Problem Solving With the MATH Dataset",
    "GSM-Symbolic: Understanding the Limitations of Mathematical Reasoning in Large Language Models",
    "Solving math word problems with process- and outcome-based feedback",
    "LLMs Can't Plan, But Can Help Planning in LLM-Modulo Frameworks",
    "Lessons from the Trenches on Reproducible Evaluation of Language Models",
    "NLP Evaluation in trouble: On the Need to Measure LLM Data Contamination for each Benchmark",
]


def http_get(url, timeout=45):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def toks(s):
    return set(norm(s).split())


def sim(a, b):
    """标题相似度：token 交集 / 较短串的长度"""
    ta, tb = toks(a), toks(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(1, min(len(ta), len(tb)))


def split_name(n):
    """'Jason Wei' -> 'Wei, Jason'"""
    parts = (n or "").strip().split()
    if len(parts) == 1:
        return parts[0]
    return parts[-1] + ", " + " ".join(parts[:-1])


def fetch_arxiv(ids):
    out = {}
    url = ("http://export.arxiv.org/api/query?id_list=" + ",".join(ids) + "&max_results=200")
    raw = http_get(url)
    root = ET.fromstring(raw)
    for e in root.findall("a:entry", NS):
        idu = (e.findtext("a:id", default="", namespaces=NS) or "").strip()
        m = re.search(r"abs/([0-9]+\.[0-9]+)v?(\d*)", idu)
        if not m:
            continue
        base = m.group(1)
        title = " ".join((e.findtext("a:title", default="", namespaces=NS) or "").split())
        authors = [" ".join((a.findtext("a:name", default="", namespaces=NS) or "").split())
                   for a in e.findall("a:author", NS)]
        published = (e.findtext("a:published", default="", namespaces=NS) or "")[:10]
        jr = (e.findtext("arxiv:journal_ref", default="", namespaces=NS) or "").strip()
        doi = (e.findtext("arxiv:doi", default="", namespaces=NS) or "").strip()
        out[base] = {"arxiv_id": base, "title": title, "authors": authors,
                     "published": published, "journal_ref": jr, "arxiv_doi": doi,
                     "abs_url": "https://arxiv.org/abs/" + base}
    return out


def fetch_crossref_doi(doi):
    try:
        raw = http_get("https://api.crossref.org/works/" + urllib.parse.quote(doi))
        msg = json.loads(raw.decode("utf-8"))["message"]
    except Exception as ex:
        return {"doi": doi, "ok": False, "error": str(ex)}
    return cr_normalize(msg, doi)


def fetch_crossref_title(title):
    q = urllib.parse.quote(title)
    url = ("https://api.crossref.org/works?query.bibliographic=" + q +
           "&rows=4&select=DOI,title,author,container-title,issued,type,event,page,volume,issue,publisher,short-container-title")
    try:
        raw = http_get(url)
        items = json.loads(raw.decode("utf-8"))["message"]["items"]
    except Exception as ex:
        return {"ok": False, "error": str(ex), "query_title": title}
    best, best_s = None, 0.0
    for it in items:
        t = (it.get("title") or [""])[0]
        s = sim(title, t)
        if s > best_s:
            best, best_s = it, s
    if best is None or best_s < 0.92:
        return {"ok": False, "query_title": title,
                "best_sim": round(best_s, 3),
                "best_title": ((best or {}).get("title") or [""])[0]}
    r = cr_normalize(best, best.get("DOI", ""))
    r["match_sim"] = round(best_s, 3)
    r["query_title"] = title
    return r


def cr_normalize(msg, doi):
    authors = []
    for a in msg.get("author", []) or []:
        fam = a.get("family") or ""
        giv = a.get("given") or ""
        if fam:
            authors.append(fam + (", " + giv if giv else ""))
        elif a.get("name"):
            authors.append(a["name"])
    cont = (msg.get("container-title") or [""])
    yr = None
    iss = msg.get("issued", {}).get("date-parts") or [[None]]
    if iss and iss[0]:
        yr = iss[0][0]
    return {
        "ok": True,
        "doi": msg.get("DOI", doi),
        "title": (msg.get("title") or [""])[0],
        "authors": authors,
        "container": cont[0] if cont else "",
        "publisher": msg.get("publisher", ""),
        "year": yr,
        "type": msg.get("type", ""),
        "volume": msg.get("volume", ""),
        "issue": msg.get("issue", ""),
        "page": msg.get("page", ""),
        "event": (msg.get("event") or {}).get("name", ""),
    }


def bib_key(entry, year):
    a = (entry.get("authors") or ["anon"])[0]
    a = re.sub(r"^(the|a|an)\s+", "", a.strip(), flags=re.I)  # "The mathlib Community" -> "mathlib Community"
    fam = re.split(r"[,\s]", a)[0].lower()
    fam = re.sub(r"[^a-z]", "", fam) or "anon"
    stop = {"a", "an", "the", "on", "of", "for", "in", "to", "with", "and", "is", "are", "can", "not"}
    w = ""
    for t in re.findall(r"[A-Za-z]+", entry["title"]):
        if t.lower() not in stop and len(t) > 2:
            w = t.lower()
            break
    return "%s%s%s" % (fam, year, w)


def bib_escape(s):
    return (s or "").replace("&", r"\&").replace("%", r"\%").replace("_", r"\_")


def main():
    os.makedirs(LIT, exist_ok=True)
    report = {"arxiv": {}, "crossref_doi": {}, "title_lookup": {}, "generated_at": time.strftime("%Y-%m-%d %H:%M:%S")}

    print("== 1/3 arXiv 批量核验 ==")
    ax = fetch_arxiv(ARXIV_IDS)
    report["arxiv"] = ax
    for i in ARXIV_IDS:
        if i in ax:
            e = ax[i]
            print("HIT  %-12s %-4s  authors=%-2d  %s" % (i, e["published"][:4], len(e["authors"]), e["title"][:64]))
        else:
            print("MISS %-12s <-- 该 arXiv 编号不存在或无返回" % i)
    time.sleep(1)

    print("\n== 2/3 Crossref DOI 核验 ==")
    for d in CROSSREF_DOIS:
        r = fetch_crossref_doi(d)
        report["crossref_doi"][d] = r
        if r.get("ok"):
            print("HIT  %-34s %-4s  %s | %s" % (d, r.get("year"), r.get("title", "")[:50], r.get("container", "")[:38]))
        else:
            print("MISS %-34s %s" % (d, r.get("error")))
        time.sleep(1)

    print("\n== 3/3 Crossref 标题反查 venue ==")
    for t in TITLE_LOOKUPS:
        r = fetch_crossref_title(t)
        report["title_lookup"][t] = r
        if r.get("ok"):
            print("HIT  sim=%.2f  %-4s  %s | %s" % (r.get("match_sim", 0), r.get("year"), r.get("title", "")[:46], r.get("container", "")[:40]))
        else:
            print("MISS sim=%s  %s" % (r.get("best_sim"), t[:60]))
        time.sleep(1)

    with open(os.path.join(LIT, "refs.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)

    # ---- 生成 bib（仅已核验条目） ----
    print("\n== 生成 references-verified.bib ==")
    entries, used, skipped = [], set(), []
    for i in ARXIV_IDS:
        e = ax.get(i)
        if not e:
            skipped.append(("arxiv-not-found", i, ""))
            continue
        year = int(e["published"][:4])
        tl = report["title_lookup"].get(e["title"])
        # 优先用 Crossref 反查到的正式发表信息
        ent = {"title": e["title"], "authors": [split_name(a) for a in e["authors"]],
               "year": year, "kind": "misc", "note": "arXiv:%s" % i, "url": e["abs_url"]}
        if tl and tl.get("ok"):
            ent["year"] = tl.get("year") or year
            if tl.get("authors"):
                ent["authors"] = tl["authors"]
            if tl.get("container") and tl.get("type") in ("proceedings-article", "book-chapter"):
                ent["kind"] = "inproceedings"
                ent["booktitle"] = tl["container"]
            elif tl.get("type") == "journal-article":
                ent["kind"] = "article"
                ent["journal"] = tl["container"]
            ent["doi"] = tl.get("doi", "")
            ent["volume"] = tl.get("volume", "")
            ent["number"] = tl.get("issue", "")
            ent["pages"] = tl.get("page", "")
        elif e.get("journal_ref"):
            ent["kind"] = "article"
            ent["journal"] = e["journal_ref"]
            ent["doi"] = e.get("arxiv_doi", "")
        entries.append(ent)

    for d, r in report["crossref_doi"].items():
        if not r.get("ok"):
            skipped.append(("crossref-not-found", d, r.get("error", "")))
            continue
        kind = "inproceedings"
        if r.get("type") == "journal-article":
            kind = "article"
        elif r.get("type") in ("book", "monograph"):
            kind = "book"
        ent = {"title": r["title"], "authors": r["authors"], "year": r["year"],
               "kind": kind, "doi": r["doi"], "url": "https://doi.org/" + r["doi"]}
        cont = r.get("event") or r.get("container") or ""
        if kind == "inproceedings":
            ent["booktitle"] = cont
        elif kind == "article":
            ent["journal"] = cont
        else:
            ent["publisher"] = r.get("publisher", "")
        ent["volume"] = r.get("volume", "")
        ent["number"] = r.get("issue", "")
        ent["pages"] = r.get("page", "")
        entries.append(ent)

    lines = ["% 由 pipeline/verify_refs.py 依据 arXiv / Crossref 实际返回结果自动生成",
             "% 生成时间：" + report["generated_at"],
             "% 未核验条目不会出现在本文件中（见 参考文献核验记录.md）", ""]
    for ent in entries:
        y = ent.get("year") or 0
        k = bib_key(ent, y)
        while k in used:
            k += "x"
        used.add(k)
        ent["bibkey"] = k
        lines.append("@%s{%s," % (ent["kind"], k))
        lines.append("  title = {%s}," % bib_escape(ent["title"]))
        if ent.get("authors"):
            lines.append("  author = {%s}," % " and ".join(bib_escape(a) for a in ent["authors"]))
        lines.append("  year = {%s}," % y)
        if ent.get("booktitle"):
            lines.append("  booktitle = {%s}," % bib_escape(ent["booktitle"]))
        if ent.get("journal"):
            lines.append("  journal = {%s}," % bib_escape(ent["journal"]))
        if ent.get("publisher"):
            lines.append("  publisher = {%s}," % bib_escape(ent["publisher"]))
        if ent.get("volume"):
            lines.append("  volume = {%s}," % ent["volume"])
        if ent.get("number"):
            lines.append("  number = {%s}," % ent["number"])
        if ent.get("pages"):
            lines.append("  pages = {%s}," % ent["pages"])
        if ent.get("doi"):
            lines.append("  doi = {%s}," % ent["doi"])
        if ent.get("note"):
            lines.append("  note = {%s}," % ent["note"])
        if ent.get("url"):
            lines.append("  url = {%s}," % ent["url"])
        lines.append("}\n")

    with open(os.path.join(LIT, "references-verified.bib"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # ---- 人可读核验报告 ----
    rep = ["# 参考文献核验记录", "",
           "> 由 `pipeline/verify_refs.py` 自动生成，数据来源：arXiv 官方 API 与 Crossref API。",
           "> 生成时间：%s" % report["generated_at"], "",
           "## 1. arXiv 条目核验（题录来自 arXiv API 实际返回）", "",
           "| arXiv ID | 首次提交 | 作者数 | 标题 | journal_ref |", "| --- | --- | --- | --- | --- |"]
    for i in ARXIV_IDS:
        e = ax.get(i)
        if e:
            rep.append("| %s | %s | %d | %s | %s |" % (i, e["published"], len(e["authors"]), e["title"].replace("|", "/"), e["journal_ref"] or "—"))
        else:
            rep.append("| %s | **未核验（API 无返回）** | — | — | — |" % i)
    rep += ["", "## 2. Crossref DOI 核验", "", "| DOI | 年份 | 标题 | 发表venue |", "| --- | --- | --- | --- |"]
    for d, r in report["crossref_doi"].items():
        if r.get("ok"):
            rep.append("| %s | %s | %s | %s |" % (d, r.get("year"), r.get("title", "").replace("|", "/"), (r.get("container") or r.get("publisher") or "—").replace("|", "/")))
        else:
            rep.append("| %s | **未核验** | %s | — |" % (d, r.get("error", "")[:60].replace("|", "/")))
    rep += ["", "## 3. Crossref 标题反查发表venue", "", "| 检索标题 | 相似度 | 命中标题 | venue | 年份 |", "| --- | --- | --- | --- | --- |"]
    for t, r in report["title_lookup"].items():
        if r.get("ok"):
            rep.append("| %s | %.2f | %s | %s | %s |" % (t.replace("|", "/"), r.get("match_sim", 0), r.get("title", "").replace("|", "/"), (r.get("container") or r.get("publisher") or "—").replace("|", "/"), r.get("year")))
        else:
            rep.append("| %s | %s | %s | **未命中** | — |" % (t.replace("|", "/"), r.get("best_sim"), (r.get("best_title") or "").replace("|", "/")))
    rep += ["", "## 4. 未核验清单（一律不得进入论文引用）", ""]
    if skipped:
        for kind, k, msg in skipped:
            rep.append("- `%s` %s %s" % (k, kind, msg))
    else:
        rep.append("- （无）")
    rep += ["", "## 5. 进入 references.bib 的条目（%d 条）" % len(entries), ""]
    for ent in entries:
        rep.append("- **%s** — %s (%s) %s" % (ent.get("bibkey"), ent["title"], ent.get("year"), ent.get("doi") or ent.get("note", "")))
    with open(os.path.join(LIT, "参考文献核验记录.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(rep) + "\n")

    print("\n写入：")
    print("  %s/refs.json" % LIT)
    print("  %s/参考文献核验记录.md" % LIT)
    print("  %s/references-verified.bib （%d 条）" % (LIT, len(entries)))
    print("未核验：%d 条" % len(skipped))


if __name__ == "__main__":
    main()
