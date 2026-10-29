#!/usr/bin/env python3
"""Build pcbworld/index.html from pcbworld/report.md (python -m pip install markdown).

    python3 build.py

The two figures are inline SVG drawn here; the markdown marks where they go with
<!--ARCH--> and <!--CURVE-->.
"""
from __future__ import annotations

import re
from pathlib import Path

import markdown

ROOT = Path(__file__).parent

# seed 42 validation fp (mean final potential on 128 D2 val boards x 10 rollouts), every 20 iters
ITERS = list(range(20, 301, 20))
CURVES = [
    ("per-step", "muted", [-0.822, 0.246, 0.436, 0.771, 0.800, 0.739, 0.770, 0.822, 0.821, 0.734, 0.791, 0.792, 0.803, 0.755, 0.811]),
    ("terminal γ=1（修复版）", "accent", [-2.287, -2.924, -1.518, -0.602, 0.192, 0.470, 0.672, 0.612, 0.597, 0.505, 0.485, 0.442, 0.466, 0.299, 0.255]),
    ("terminal 论文配方", "dashed", [-16.423, -16.191, -14.922, -14.889, -15.066, -15.125, -15.197, -15.547, -14.775, -15.104, -14.874, -15.129, -14.855, -14.951, -14.403]),
]


def arch_svg() -> str:
    W, H, y0 = 160, 104, 88
    xs = [24, 208, 392, 576]
    mid, bot = y0 + H / 2, y0 + H
    boxes = [
        ("智能体", ["RL 策略或 LLM", "输出动作类型", "+ 候选点 + mode"], False),
        ("PCBWorld 环境", ["Python / Gymnasium", "查掩码、组观测", "算 Φ 奖励、判终止"], False),
        ("Engine Server", ["独立子进程", "unix socket 通信", "GPL 代码隔离在此"], False),
        ("KiCad 9.0.8 引擎", ["PNS 推挤 / 绕行布线器", "KiCad 自己的 DRC", "改写真实 .kicad_pcb"], True),
    ]
    out = [f'<svg viewBox="0 0 760 292" role="img" aria-label="交互环境架构">',
           '<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
           '<path d="M0 0L10 5L0 10z" fill="var(--chart-axis)"/></marker></defs>',
           '<text x="24" y="30" font-size="15" font-weight="600" fill="var(--ink)">智能体只选点和模式，画线和检查都由 KiCad 完成</text>',
           '<g fill="none" stroke="var(--chart-axis)" stroke-width="1.25">']
    for a, b in zip(xs, xs[1:]):
        out.append(f'<path d="M{a + W} {mid}H{b}" marker-end="url(#arr)"/>')
    out.append(f'<path d="M{xs[3] + W / 2} {bot}V{bot + 30}H{xs[1] + W / 2 + 40}V{bot}" marker-end="url(#arr)"/>')
    out.append(f'<path d="M{xs[1] + W / 2 - 40} {bot}V{bot + 70}H{xs[0] + W / 2}V{bot}" marker-end="url(#arr)"/>')
    out.append('</g>')
    for x, label in zip(xs[:3], ["动作", "socket 调用", "fix_route 等"]):
        out.append(f'<text x="{x + W + 12}" y="{y0 - 10}" text-anchor="middle" font-size="11.5" fill="var(--muted)">{label}</text>')
    out.append(f'<text x="{(xs[1] + W / 2 + 40 + xs[3] + W / 2) / 2}" y="{bot + 22}" text-anchor="middle" font-size="11.5" fill="var(--muted)">走线结果、连通性、DRC 违规</text>')
    out.append(f'<text x="{(xs[0] + W / 2 + xs[1] + W / 2 - 40) / 2}" y="{bot + 62}" text-anchor="middle" font-size="11.5" fill="var(--muted)">新观测 + 奖励 + 是否结束</text>')
    for x, (name, lines, main) in zip(xs, boxes):
        fill = 'fill="var(--accent-soft)" stroke="var(--accent)" stroke-width="2"' if main else 'fill="var(--surface)" stroke="var(--chart-axis)" stroke-width="1.25"'
        out.append(f'<rect x="{x}" y="{y0}" width="{W}" height="{H}" rx="8" {fill}/>')
        out.append(f'<text x="{x + 12}" y="{y0 + 24}" font-size="13" font-weight="600" fill="var(--ink)">{name}</text>')
        for i, line in enumerate(lines):
            out.append(f'<text x="{x + 12}" y="{y0 + 48 + 18 * i}" font-size="11.5" fill="var(--ink)">{line}</text>')
    out.append('</svg>')
    return ('<figure>' + ''.join(out) +
            '<figcaption>每一步动作从左往右传到 KiCad，由 KiCad 实际画线并跑 DRC；结果再经环境整理成观测和奖励返回给智能体。</figcaption></figure>')


def curve_svg() -> str:
    left, right, y0, y1 = 64, 540, 70, 320
    X = lambda i: left + i / 300 * (right - left)
    Y = lambda v: y0 + (2 - v) / 19 * (y1 - y0)
    out = ['<svg viewBox="0 0 760 370" role="img" aria-label="PPO terminal 修复前后的验证曲线">',
           '<text x="24" y="28" font-size="15" font-weight="600" fill="var(--ink)">γ=1 修复后 PPO terminal 和 per-step 一样学得起来，论文配方停在 −15 左右</text>',
           '<text x="24" y="50" font-size="11.5" fill="var(--muted)">seed 42，验证集平均最终势函数 fp（D2 val 128 块 × 10 次），每 20 次迭代评一次</text>']
    for v in (0, -5, -10, -15):
        stroke = "var(--chart-axis)" if v == 0 else "var(--chart-grid)"
        out.append(f'<line x1="{left}" x2="{right}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{stroke}"/>')
        out.append(f'<text x="{left - 8}" y="{Y(v) + 4:.1f}" text-anchor="end" font-size="11.5" fill="var(--muted)">{v}</text>')
    for i in (0, 100, 200, 300):
        out.append(f'<text x="{X(i):.1f}" y="{y1 + 20}" text-anchor="middle" font-size="11.5" fill="var(--muted)">{i}</text>')
    out.append(f'<text x="{(left + right) / 2}" y="{y1 + 40}" text-anchor="middle" font-size="11.5" fill="var(--muted)">训练迭代</text>')
    dy = {"muted": -4, "accent": 14, "dashed": 4}
    for name, kind, ys in CURVES:
        col = "var(--accent)" if kind == "accent" else "var(--chart-muted)"
        width = 2.5 if kind == "accent" else 1.5
        dash = ' stroke-dasharray="5 4"' if kind == "dashed" else ""
        d = "".join(f'{"L" if j else "M"}{X(it):.1f} {Y(v):.1f}' for j, (it, v) in enumerate(zip(ITERS, ys)))
        out.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{width}"{dash}/>')
        for it, v in zip(ITERS, ys):
            out.append(f'<circle cx="{X(it):.1f}" cy="{Y(v):.1f}" r="3" fill="{col}"><title>{name}，第 {it} 次迭代：fp {v}</title></circle>')
        weight = 600 if kind == "accent" else 400
        ink = "var(--ink)" if kind == "accent" else "var(--muted)"
        out.append(f'<text x="{right + 10}" y="{Y(ys[-1]) + dy[kind]:.1f}" font-size="12" font-weight="{weight}" fill="{ink}">{name} {ys[-1]:+.2f}</text>')
    out.append('</svg>')
    return ('<figure>' + ''.join(out) +
            '<figcaption>数据来自三次训练的日志。论文配方（虚线）从头到尾停在 −15 左右；修复版（蓝线）在第 100 次迭代左右转正，和 per-step 走势一致。</figcaption></figure>')


PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PCBWorld 复现报告 · chip-ai-agent</title>
<meta name="description" content="PCBWorld（KDD 2026）RL 方法的 4-seed 复现：交互环境、数据、模型、训练、评测与结果。">
<link rel="icon" href="../assets/logo.svg">
<link rel="stylesheet" href="../assets/style.css">
</head>
<body>
<header class="topbar"><div class="wrap">
  <a class="brand" href="../"><img class="brand-mark" src="../assets/logo.svg" alt="">chip-ai-agent</a>
  <nav class="nav"><a href="../">主页</a><a class="on" href="./">PCBWorld 复现</a><a href="https://github.com/chip-ai-agent">GitHub</a></nav>
</div></header>
<main class="wrap doc">
{body}
</main>
<footer><div class="wrap">chip-ai-agent · 论文与代码版权归原作者（LG AI Research，PCBWorld），本页只记录我们的复现。</div></footer>
</body>
</html>
"""


def build() -> None:
    src = (ROOT / "pcbworld" / "report.md").read_text()
    html = markdown.markdown(src, extensions=["tables", "fenced_code", "toc"])
    html = html.replace("<p><!--ARCH--></p>", arch_svg()).replace("<!--ARCH-->", arch_svg())
    html = html.replace("<p><!--CURVE--></p>", curve_svg()).replace("<!--CURVE-->", curve_svg())
    html = re.sub(r"<table>", '<div class="table-scroll"><table>', html)
    html = html.replace("</table>", "</table></div>")
    # table of contents from h2s, inserted after the overview's lead
    heads = re.findall(r'<h2 id="([^"]+)">(.*?)</h2>', html)
    toc = '<nav class="toc"><b>目录</b><ol>' + "".join(f'<li><a href="#{i}">{t}</a></li>' for i, t in heads) + "</ol></nav>"
    html = html.replace("<h2 ", toc + "<h2 ", 1)
    (ROOT / "pcbworld" / "index.html").write_text(PAGE.replace("{body}", html))
    print("wrote pcbworld/index.html")


if __name__ == "__main__":
    build()
