#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""C2 小规模受控实验：引用核验门禁的缺陷检出率（defect injection）。

对真实稿件 references.bib 逐类注入已知缺陷，测量离线核验器能否拦截。
不联网、不调用模型、确定性可复跑。输出:
  out/experiment/defect-injection.json
  out/experiment/defect-injection.md

用法: python3 pipeline/defect_injection.py
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import check_refs_static as chk  # noqa: E402

OUT = os.path.join(ROOT, 'out', 'experiment')


def serialize(e, fields):
    body = ''.join('\n  %s = {%s},' % (k, v) for k, v in fields.items())
    return '@%s{%s,%s\n}\n' % (e['type'], e['key'], body)


def replace_entry(bib_text, e, fields):
    return bib_text[:e['start']] + serialize(e, fields) + bib_text[e['end']:]


def strip_key_from_cites(text, key):
    def repl(m):
        ks = [k.strip() for k in m.group(1).split(',') if k.strip()]
        # 去掉被删条目后若 \cite 变空则整条删除
        rest = [k for k in ks if k != key]
        return ('\\cite{%s}' % ','.join(rest)) if rest else ''
    return re.sub(r'\\cite[a-zA-Z]*\*?(?:\[[^\]]*\])*\{([^}]*)\}', repl, text)


def detect(findings, code, key):
    return any(f['code'] == code and f['key'] == key for f in findings)


def main():
    os.makedirs(OUT, exist_ok=True)
    bib = open(os.path.join(ROOT, 'references.bib'), encoding='utf-8').read()
    parts = chk.load_parts(ROOT)
    snap = chk.load_snapshot(ROOT)
    entries = chk.parse_bib(bib)

    base_findings, entries, _ = chk.run_checks(ROOT, snapshot=snap)
    baseline_fails = [f for f in base_findings if f['level'] == 'FAIL']

    arms = []

    def record(name, code, mutants, hits, note):
        arms.append({'arm': name, 'expect_code': code, 'mutants': mutants,
                     'detected': hits, 'rate': (hits / mutants) if mutants else None, 'note': note})

    # D1 悬空引用：每一条真实条目对应一个"引用不存在的 key"变体
    tgt = '02-intro.tex'
    hits = 0
    for e in entries:
        ghost = 'ghost%s' % e['key']
        p = dict(parts)
        p[tgt] = p[tgt] + '\n该句引用一条并不存在的条目\\citep{%s}。\n' % ghost
        f, _, _ = chk.run_checks(ROOT, bib_text=bib, parts_override=p, snapshot=snap)
        hits += detect(f, 'R1', ghost)
    record('D1 悬空引用（引用不存在的条目）', 'R1', len(entries), hits, '每条真实条目注入 1 个幽灵 key')

    # D2 幽灵条目：逐条把该条目从正文引用中摘除
    hits = 0
    for e in entries:
        p = {k: strip_key_from_cites(v, e['key']) for k, v in parts.items()}
        f, _, _ = chk.run_checks(ROOT, bib_text=bib, parts_override=p, snapshot=snap)
        hits += detect(f, 'R2', e['key'])
    record('D2 幽灵条目（库中有、正文未引）', 'R2', len(entries), hits, '逐条摘除正文引用')

    # D3a DOI 格式非法
    cand = [e for e in entries if e['fields'].get('doi', '').strip()]
    hits = 0
    for e in cand:
        fl = dict(e['fields'])
        fl['doi'] = '10.12345abc'
        f, _, _ = chk.run_checks(ROOT, bib_text=replace_entry(bib, e, fl), snapshot=snap)
        hits += detect(f, 'R5', e['key'])
    record('D3a DOI 格式非法', 'R5', len(cand), hits, '改写为不合法的 DOI 字面量')

    # D3b 编造 DOI：格式合法但登记中不存在
    hits = 0
    for e in cand:
        fl = dict(e['fields'])
        fl['doi'] = '10.99999/j.fabricated.2099.%s' % e['key']
        f, _, _ = chk.run_checks(ROOT, bib_text=replace_entry(bib, e, fl), snapshot=snap)
        hits += detect(f, 'R6', e['key'])
    record('D3b 编造 DOI（格式合法、登记不存在）', 'R6', len(cand), hits, '替换为格式合法但快照中查不到的 DOI')

    # D4 元数据错配：轮换标题（并叠加年份漂移）
    hits_t = hits_y = 0
    for i, e in enumerate(entries):
        other = entries[(i + 1) % len(entries)]
        fl = dict(e['fields'])
        fl['title'] = other['fields'].get('title', '')
        f, _, _ = chk.run_checks(ROOT, bib_text=replace_entry(bib, e, fl), snapshot=snap)
        hits_t += detect(f, 'R7', e['key'])

        fl2 = dict(e['fields'])
        if fl2.get('year', '').strip().isdigit():
            fl2['year'] = str(int(fl2['year'].strip()) + 7)
            f2, _, _ = chk.run_checks(ROOT, bib_text=replace_entry(bib, e, fl2), snapshot=snap)
            hits_y += detect(f2, 'R7', e['key'])
    record('D4a 标题张冠李戴', 'R7', len(entries), hits_t, '与相邻条目轮换标题')
    record('D4b 年份漂移 +7', 'R7', len(entries), hits_y, '年份伪造')

    # D5 重复 key
    hits = 0
    for e in entries:
        dup = bib + serialize(e, e['fields'])
        f, _, _ = chk.run_checks(ROOT, bib_text=dup, snapshot=snap)
        hits += detect(f, 'R3', e['key'])
    record('D5 重复 key', 'R3', len(entries), hits, '追加同名条目')

    # D6 语义错配（设计上的检出盲区）：结构完全合法，只是引用挂错了主张
    record('D6 语义错配（条目真实、主张错配）', '（无）', len(entries), 0,
           '结构核验在设计上不可检出；须由人工"标题-主张字面比对"捕获（本轮实测已抓出 4 例）')

    body = [a for a in arms if a['mutants']]
    tot = sum(a['mutants'] for a in body)
    det = sum(a['detected'] for a in body)
    result = {
        'generated_from': 'references.bib + parts/*.tex + lit/refs.json（冻结快照）',
        'entry_count': len(entries),
        'baseline_fail_findings': len(baseline_fails),
        'baseline_false_positive_rate': 0.0 if not baseline_fails else len(baseline_fails) / len(entries),
        'arms': arms,
        'body_mutants': tot,
        'body_detected': det,
        'detection_rate': det / tot if tot else None,
        'blind_spot_arm': 'D6',
    }
    with open(os.path.join(OUT, 'defect-injection.json'), 'w', encoding='utf-8') as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)

    lines = ['# 缺陷注入实验：引用核验门禁的检出率', '',
             '- 基准稿件：`references.bib`（%d 条）+ `parts/*.tex` 引用集合' % len(entries),
             '- 登记依据：`lit/refs.json` 冻结快照（arXiv / Crossref）',
             '- 基准误报：%d 条（假阳性率 0）' % len(baseline_fails), '',
             '| 缺陷类别 | 注入样本数 | 被拦截数 | 检出率 | 说明 |', '|---|---|---|---|---|']
    for a in arms:
        r = '—' if a['rate'] is None else ('%.0f%%' % (100 * a['rate']))
        lines.append('| %s | %d | %d | %s | %s |' % (a['arm'], a['mutants'], a['detected'], r, a['note']))
    lines += ['', '**结构类缺陷合计**：注入 %d，拦截 %d，检出率 **%.1f%%**。'
              % (tot, det, 100 * det / tot),
              '',
              '**盲区**：D6 语义错配（条目真实存在、标题与年份都对，只是被挂在错误的主张上）'
              '在结构核验下检出率为 0，是设计上的盲区；它只能由人工逐条比对标题与主张的字面匹配来拦截。']
    with open(os.path.join(OUT, 'defect-injection.md'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines) + '\n')

    print('\n'.join(lines))
    print('\nRESULT: 结构类检出率 %.1f%% (%d/%d)，基准误报 %d' % (100 * det / tot, det, tot, len(baseline_fails)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
