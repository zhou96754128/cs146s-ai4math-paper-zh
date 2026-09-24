#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C2 离线引用静态核验器（不联网、可复跑、确定性）。

用法:
  python3 pipeline/check_refs_static.py [根目录] [--audit] [--json <输出路径>]

检查项:
  R1 悬空引用   正文 \\cite 的 key 在 references.bib 中不存在
  R2 幽灵条目   references.bib 中的条目从未被正文引用
  R3 重复 key   同一 key 在 references.bib 中出现多次
  R4 必填字段   条目缺 title / author / year
  R5 DOI 格式   doi 字段不满足 10.<4-9 位数字>/... 形式
  R6 无登记依据 条目无法在冻结登记快照 lit/refs.json 中定位
  R7 元数据错配 title / year 与登记快照不一致

退出码: 0 = 全部通过; 20 = 存在 FAIL 级发现。
本脚本不调用任何模型，同样输入永远同样输出。
"""
import argparse
import glob
import json
import os
import re
import sys
from difflib import SequenceMatcher

TITLE_FAIL = 0.85
TITLE_WARN = 0.95
YEAR_TOL = 1
DOI_RE = re.compile(r'^10\.\d{4,9}/\S+$')


def parse_bib(text):
    """返回 [{type, key, fields, start, end}]，用括号配对而非正则截断。"""
    entries = []
    i, n = 0, len(text)
    while True:
        at = text.find('@', i)
        if at < 0:
            break
        m = re.match(r'@(\w+)\s*\{\s*([^,\s]+)\s*,', text[at:])
        if not m:
            i = at + 1
            continue
        body_start = at + m.end()
        depth, j = 1, body_start
        while j < n and depth > 0:
            if text[j] == '{':
                depth += 1
            elif text[j] == '}':
                depth -= 1
            j += 1
        entries.append({'type': m.group(1).lower(), 'key': m.group(2),
                        'fields': parse_fields(text[body_start:j - 1]),
                        'start': at, 'end': j})
        i = j
    return entries


def parse_fields(body):
    """按 key = {value} 扫描，支持嵌套括号。"""
    out = {}
    pat = re.compile(r'([A-Za-z]+)\s*=\s*\{')
    i = 0
    while True:
        m = pat.search(body, i)
        if not m:
            break
        depth, j = 1, m.end()
        while j < len(body) and depth > 0:
            if body[j] == '{':
                depth += 1
            elif body[j] == '}':
                depth -= 1
            j += 1
        out[m.group(1).lower()] = body[m.end():j - 1].strip()
        i = j
    return out


def norm(s):
    s = (s or '').lower().replace('{', '').replace('}', '').replace('\\', '')
    s = re.sub(r'[^a-z0-9\u4e00-\u9fff]+', ' ', s)
    return ' '.join(s.split())


def sim(a, b):
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def load_parts(root, override=None):
    files = sorted(glob.glob(os.path.join(root, 'parts', '*.tex')))
    files.append(os.path.join(root, 'paper.tex'))
    d = {}
    for f in files:
        name = os.path.basename(f)
        d[name] = override[name] if (override and name in override) else open(f, encoding='utf-8').read()
    return d


def parse_cites(parts):
    keys = set()
    for text in parts.values():
        for m in re.finditer(r'\\cite[a-zA-Z]*\*?(?:\[[^\]]*\])*\{([^}]*)\}', text):
            for k in m.group(1).split(','):
                if k.strip():
                    keys.add(k.strip())
    return keys


def load_snapshot(root):
    p = os.path.join(root, 'lit', 'refs.json')
    if not os.path.exists(p):
        return {}
    with open(p, encoding='utf-8') as fh:
        return json.load(fh)


def registry_for(f, snap):
    """在冻结快照中定位该条目的登记依据；定位不到返回 None。"""
    doi = f.get('doi', '').strip()
    if doi and DOI_RE.match(doi):
        r = snap.get('crossref_doi', {}).get(doi)
        if isinstance(r, dict) and r.get('ok', True):
            return {'src': 'crossref:' + doi, 'title': r.get('title', ''), 'year': str(r.get('year', ''))}
    blob = ' '.join([f.get('note', ''), f.get('url', ''), f.get('eprint', ''), f.get('arxivid', '')])
    m = re.search(r'(\d{4}\.\d{4,5})', blob)
    if m:
        r = snap.get('arxiv', {}).get(m.group(1))
        if isinstance(r, dict):
            return {'src': 'arxiv:' + m.group(1), 'title': r.get('title', ''),
                    'year': (r.get('published', '') or '')[:4]}
    t = norm(f.get('title', ''))
    for k, v in snap.get('title_lookup', {}).items():
        if isinstance(v, dict) and norm(k) == t and v.get('ok', True):
            return {'src': 'title_lookup', 'title': v.get('title', ''), 'year': str(v.get('year', ''))}
    return None


def run_checks(root, bib_text=None, parts_override=None, snapshot=None):
    """返回 (findings, entries, cited)。findings 项: {code, level, key, detail}。"""
    bib_path = os.path.join(root, 'references.bib')
    if bib_text is None:
        bib_text = open(bib_path, encoding='utf-8').read()
    parts = load_parts(root, parts_override)
    cited = parse_cites(parts)
    entries = parse_bib(bib_text)
    snap = snapshot if snapshot is not None else load_snapshot(root)
    findings = []

    seen = {}
    for e in entries:
        if e['key'] in seen:
            findings.append({'code': 'R3', 'level': 'FAIL', 'key': e['key'],
                             'detail': 'key 在 references.bib 中重复出现'})
        seen[e['key']] = e

    for k in sorted(cited - set(seen)):
        findings.append({'code': 'R1', 'level': 'FAIL', 'key': k, 'detail': '正文引用但库中不存在（悬空引用）'})
    for k in sorted(set(seen) - cited):
        findings.append({'code': 'R2', 'level': 'FAIL', 'key': k, 'detail': '库中存在但正文从未引用（幽灵条目）'})

    for k, e in seen.items():
        f = e['fields']
        for req in ('title', 'author', 'year'):
            if not f.get(req):
                findings.append({'code': 'R4', 'level': 'FAIL', 'key': k, 'detail': '缺必填字段 %s' % req})
        doi = f.get('doi', '').strip()
        if doi and not DOI_RE.match(doi):
            findings.append({'code': 'R5', 'level': 'FAIL', 'key': k, 'detail': 'DOI 格式非法: %s' % doi})
        reg = registry_for(f, snap)
        if reg is None:
            findings.append({'code': 'R6', 'level': 'FAIL', 'key': k,
                             'detail': '在冻结登记快照中无登记依据（疑似编造/无法核验）'})
            continue
        ratio = sim(f.get('title', ''), reg['title'])
        if ratio < TITLE_FAIL:
            findings.append({'code': 'R7', 'level': 'FAIL', 'key': k,
                             'detail': '标题与登记依据不符 (sim=%.3f vs %s)' % (ratio, reg['src'])})
        dy = 0
        if reg['year'].isdigit() and f.get('year', '').strip().isdigit():
            dy = abs(int(reg['year']) - int(f['year'].strip()))
            if dy > YEAR_TOL:
                findings.append({'code': 'R7', 'level': 'FAIL', 'key': k,
                                 'detail': '年份与登记依据差 %d 年 (bib %s vs %s %s)'
                                           % (dy, f['year'].strip(), reg['src'], reg['year'])})
    return findings, entries, cited


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('root', nargs='?', default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument('--audit', action='store_true', help='逐条打印标题/年份与登记依据的实测差异')
    ap.add_argument('--json', dest='json_out', default=None)
    a = ap.parse_args()
    root = a.root
    findings, entries, cited = run_checks(root)
    snap = load_snapshot(root)

    if a.audit:
        print('%-34s %-6s %-6s %s' % ('key', 'sim', 'Δ年', '登记依据'))
        for e in entries:
            reg = registry_for(e['fields'], snap)
            if reg is None:
                print('%-34s %-6s %-6s %s' % (e['key'], '-', '-', 'NONE'))
                continue
            dy = ''
            if reg['year'].isdigit() and e['fields'].get('year', '').strip().isdigit():
                dy = abs(int(reg['year']) - int(e['fields']['year'].strip()))
            print('%-34s %-6.3f %-6s %s' % (e['key'], sim(e['fields'].get('title', ''), reg['title']), dy, reg['src']))
        print()

    fails = [f for f in findings if f['level'] == 'FAIL']
    print('条目 %d / 被引 key %d / FAIL 级发现 %d' % (len(entries), len(cited), len(fails)))
    for f in fails:
        print('  [%s] %s: %s' % (f['code'], f['key'], f['detail']))
    if a.json_out:
        with open(a.json_out, 'w', encoding='utf-8') as fh:
            json.dump({'entries': len(entries), 'cited': len(cited), 'findings': findings},
                      fh, ensure_ascii=False, indent=2)
    print('RESULT: ' + ('PASS' if not fails else 'FAIL'))
    return 0 if not fails else 20


if __name__ == '__main__':
    sys.exit(main())
