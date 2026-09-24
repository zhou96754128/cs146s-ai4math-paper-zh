#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 C2 论文工作区发布到 GitHub（GitHub REST Contents API，不依赖 git/gh/Xcode CLT）。
无可用令牌时退出码 3，且不做任何改动。
"""
import base64, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_FILES = [
    "/Users/xiaowo/.cogseed-dev/userWorkSpace/我的挑战有哪些/gh_token.txt",
    os.path.join(ROOT, "gh_token.txt"),
]
OWNER, REPO, BRANCH = "zhou96754128", "cs146s-ai4math-paper-zh", "main"
EXCLUDE_DIRS = {"_smoke", ".git", "__pycache__"}
EXCLUDE_REL_DIRS = ("out/render", "_smoke")
EXCLUDE_FILES = {"paper.aux", "paper.log", "paper.out", "paper.blg", "paper.xdv",
                 "pipeline/render_page.py", ".DS_Store", "README.md.bak"}
KEEP_MATERIALS = {"materials/CHALLENGE.md", "materials/rubric.json"}


def load_token():
    for tf in TOKEN_FILES:
        if os.path.exists(tf):
            for line in open(tf, encoding="utf-8", errors="ignore").read().splitlines():
                s = line.strip()
                if re.match(r"^(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})$", s):
                    return s
    return os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")


def api(url, method="GET", payload=None, token=None, retries=4):
    last = (0, {})
    for i in range(retries):
        req = urllib.request.Request(url, headers={
            "User-Agent": "c2-publish", "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json"}, method=method)
        if payload is not None:
            req.data = json.dumps(payload).encode("utf-8")
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            raw = e.read()[:400]
            try:
                body = json.loads(raw)
            except Exception:
                body = {"raw": raw.decode("utf-8", "ignore")}
            last = (e.code, body)
            if e.code in (403, 429, 500, 502, 503, 504) and i < retries - 1:
                time.sleep(3 * (i + 1))
                continue
            return last
        except Exception as e:
            last = ("ERR", str(e)[:200])
            time.sleep(2)
    return last


def collect():
    out = []
    for dp, dns, fns in os.walk(ROOT):
        rel_dir = os.path.relpath(dp, ROOT).replace(os.sep, "/")
        dns[:] = [d for d in dns if d not in EXCLUDE_DIRS]
        if any(rel_dir == x or rel_dir.startswith(x + "/") for x in EXCLUDE_REL_DIRS):
            dns[:] = []
            continue
        for fn in fns:
            rel = (fn if rel_dir == "." else rel_dir + "/" + fn)
            if rel in EXCLUDE_FILES or fn in EXCLUDE_FILES or ".synctex.gz" in rel:
                continue
            if rel.startswith("materials/") and rel not in KEEP_MATERIALS:
                continue
            if re.match(r"^publish.*\.py$", fn):
                continue
            out.append((rel, os.path.join(dp, fn)))
    return sorted(out)


def main():
    tok = load_token()
    if not tok:
        print("NO_TOKEN: 未找到可用令牌，未做任何改动")
        return 3
    files = collect()
    total = sum(os.path.getsize(p) for _, p in files)
    print("待发布: %d 个文件, 合计 %.2f MB" % (len(files), total / 1048576.0))
    biggest = max(files, key=lambda x: os.path.getsize(x[1]))
    print("最大文件: %s (%.2f MB)" % (biggest[0], os.path.getsize(biggest[1]) / 1048576.0))

    base = "https://api.github.com/repos/%s/%s" % (OWNER, REPO)
    s, d = api(base + "/git/trees/%s?recursive=1" % BRANCH, token=tok)
    existing = {}
    if s == 200:
        for it in d.get("tree", []):
            if it.get("type") == "blob":
                existing[it["path"]] = it["sha"]
    print("远端分支 %s 已有 %d 个文件" % (BRANCH, len(existing)))

    ok = fail = 0
    errors = []
    for i, (rel, ap) in enumerate(files, 1):
        payload = {"message": "add " + rel,
                   "content": base64.b64encode(open(ap, "rb").read()).decode("ascii"),
                   "branch": BRANCH}
        if rel in existing:
            payload["sha"] = existing[rel]
            payload["message"] = "update " + rel
        code, body = api(base + "/contents/" + urllib.parse.quote(rel),
                         method="PUT", payload=payload, token=tok)
        if code in (200, 201):
            ok += 1
        else:
            fail += 1
            errors.append((rel, code, str(body)[:150]))
        if i % 8 == 0 or i == len(files):
            print("  进度 %d/%d  成功 %d 失败 %d" % (i, len(files), ok, fail))
        time.sleep(0.85)

    print("-" * 46)
    print("上传完成: 成功 %d, 失败 %d" % (ok, fail))
    for e in errors:
        print("  FAIL %s -> %s %s" % e)
    s, d = api(base + "/git/trees/%s?recursive=1" % BRANCH, token=tok)
    if s == 200:
        blobs = [t for t in d.get("tree", []) if t.get("type") == "blob"]
        print("远端核验: %d 个文件, 总 %d 字节" % (len(blobs), sum(t.get("size", 0) for t in blobs)))
    else:
        print("远端核验失败:", s)
    s, d = api(base, token=tok)
    if s == 200:
        print("仓库: %s (%s) default=%s size=%sKB" % (d["full_name"], "private" if d["private"] else "public", d["default_branch"], d["size"]))
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
