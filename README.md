# 从自然语言到可验证推理：基于语义规约的 AI 数学可靠性框架

> Stanford Vibe Coding 挑战 **C2 · AI for Math 论文** 交付仓库
> 作者：周同学 · 2026 年 9 月 · 共 16 页，31 条参考文献

## 一句话摘要

本文提出一个**三层可验证性框架**（自然语言层 → 语义规约层 → 形式验证层），
用来回答一个具体问题：*为什么大模型在数学推理上"看起来对、实际错"，以及哪些环节
可以用机械手段把错误拦住*。核心贡献是把"验证"从二值判断细化成**验证梯度 V0–V3**
与三个可观测指标（V-rate、保真度 Fidelity、反例检出率 CDR），并给出一份十条可执行清单。

## 交付物

| 文件 | 说明 |
|---|---|
| `paper.tex` | 论文主文件（`\input` 各节） |
| `references.bib` | 参考文献库（31 条，全部经 API 核验存在） |
| `AI日志/AI日志.md` | AI 协作日志：多轮迭代、prompt 优化、**AI 误导案例与对策** |
| `七维AAR复盘.md` | 七维 AAR 复盘（含 ΔR 归因与未达成项） |
| `paper.pdf` | 编译产物（16 页） |

## 如何编译

本仓库使用 **tectonic**（自带依赖的 LaTeX 引擎，本机无 MacTeX 时可直接跑）：

```bash
tectonic -X compile paper.tex --keep-logs
```

`paper.tex` 通过 `\input{parts/...}` 引入 8 个分节文件；
参考文献用 `natbib` + `plainnat`，BibTeX 步骤由 tectonic 自动完成。

## 目录结构

```
paper.tex              主文件（preamble + abstract + \input 各节）
parts/                 01-preamble … 08-discussion（8 个分节）
references.bib         参考文献库（31 条）
lit/                   引文核验产物：refs.json / 参考文献核验记录.md / references-verified.bib
pipeline/verify_refs.py 可复用核验脚本（arXiv + Crossref API，输出证据表）
选题与问题定义.md        选题、贡献点 C-1…C-4、结论边界
AI日志/AI日志.md        AI 协作日志
七维AAR复盘.md          七维复盘
out/                   编译与核验的中间报告
```

## 引用可核验性（针对"引用造假"红线）

`pipeline/verify_refs.py` 对每条文献做**机器可查**的核验：arXiv ID 精确查询
`export.arxiv.org/api/query?id_list=…`，DOI 走 Crossref；只有命中条目的条目才会写入
`lit/references-verified.bib`，未命中者进入未核验清单，**不猜、不补**。
当前状态：31 条全部核验通过，未核验 0 条；`paper.bbl` 31 条 bibitem，
"未被引用条目"与"被引但库中缺失"均为空。

## 结论边界（如实声明）

1. 本文是**框架 + 定义 + 指标设计**，**不含大规模实验测量**；V-rate / Fidelity / CDR
   给出的是定义与采集口径，不是实测数值。
2. 框架的完备性不成立：V0–V3 是工程化分层，不是可证明的完备刻画。
3. 因此本文不主张任何"规模效应"或"通用可靠性提升"的经验结论。
