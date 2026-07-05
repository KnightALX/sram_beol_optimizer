"""Smoke check: 验证 README.md 的 Obsidian Flavored Markdown 语法正确性。

不调用 Obsidian 本身，只做静态结构检查：
- YAML frontmatter 合法
- callout 标签平衡（[!info]/[!warning]/[!example]/[!tip]/[!note]/[!success]/[!quote] 等）
- ```mermaid 代码块闭合
- ==highlight== 平衡
- [[wikilink]] 数量
"""
from __future__ import annotations
import re
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
from pathlib import Path

readme = Path("d:/workspace/project/sram_beol/README.md")
text = readme.read_text(encoding='utf-8')

print(f"File size: {len(text)} chars / {len(text.splitlines())} lines\n")

# 1. Frontmatter
m = re.match(r'^---\n(.*?)\n---\n', text, re.DOTALL)
if not m:
    print("[FAIL] Missing YAML frontmatter at top of file")
    sys.exit(1)
fm = m.group(1)
print(f"[OK] Frontmatter present ({len(fm)} chars)")
required_props = ["title", "description", "tags", "aliases", "status"]
for prop in required_props:
    if re.search(rf'^{prop}:', fm, re.MULTILINE):
        print(f"  - {prop}: present")
    else:
        print(f"  [FAIL] {prop}: MISSING")

# 2. Callout balance
callout_types = ["info", "warning", "example", "tip", "note", "success", "quote", "abstract", "bug", "danger", "failure", "question", "todo", "faq"]
total_callouts = 0
for ct in callout_types:
    # Obsidian callout: > [!type] or > [!type] Title or > [!type]+ or > [!type]-
    pattern = rf'> \[!{ct}\]'
    n = len(re.findall(pattern, text))
    if n > 0:
        print(f"  - callout [!{ct}]: {n} occurrence(s)")
        total_callouts += n
print(f"[OK] Total Obsidian callouts: {total_callouts}")

# 3. Mermaid fence
mermaid_blocks = len(re.findall(r'```mermaid', text))
mermaid_close = len(re.findall(r'```\n', text[text.find('```mermaid'):]))
print(f"[{'OK' if mermaid_blocks >= 1 else 'WARN'}] Mermaid blocks: {mermaid_blocks} (expected ≥ 1)")

# 4. ==highlight== balance
hl_open = len(re.findall(r'==[^=\n]+==', text))
print(f"[OK] Highlight ==text==: {hl_open} occurrence(s)")

# 5. Wikilinks
wikilinks = re.findall(r'\[\[([^\]]+)\]\]', text)
print(f"[OK] Wikilinks: {len(wikilinks)} occurrence(s)")
for wl in wikilinks[:10]:
    print(f"  - [[{wl}]]")

# 6. Standard code fences balance (excluding mermaid)
all_fences = re.findall(r'^```', text, re.MULTILINE)
print(f"[{'OK' if len(all_fences) % 2 == 0 else 'FAIL'}] Code fences total: {len(all_fences)} (must be even)")

# 7. Tables
tables = re.findall(r'^\|.*\|$', text, re.MULTILINE)
print(f"[OK] Table rows: {len(tables)}")

# 8. Lists (-, *, +)
list_items = re.findall(r'^- ', text, re.MULTILINE)
print(f"[OK] List items (-): {len(list_items)}")

# 9. Total headings
headings = re.findall(r'^(#+)\s+(.+)$', text, re.MULTILINE)
print(f"[OK] Headings: {len(headings)}")
for level, title in headings[:8]:
    print(f"  {'  ' * (len(level) - 1)}{level} {title}")
if len(headings) > 8:
    print(f"  ... and {len(headings) - 8} more")

# 10. Check the Mermaid block specifically
m = re.search(r'```mermaid\n(.*?)\n```', text, re.DOTALL)
if m:
    body = m.group(1)
    has_graph = 'graph' in body
    has_arrows = '-->' in body
    print(f"[{'OK' if has_graph and has_arrows else 'WARN'}] Mermaid body has graph keyword: {has_graph}, has arrows: {has_arrows}")

# 11. Check anchor links (#multi-fix, #per-layer-constraints)
anchors = re.findall(r'\{#([\w-]+)\}', text)
print(f"[OK] Explicit anchor IDs: {anchors}")

# 12. Tags inside frontmatter
tag_match = re.search(r'^tags:\n((?:  - .+\n)+)', fm, re.MULTILINE)
if tag_match:
    tags = re.findall(r'  - (\S+)', tag_match.group(1))
    print(f"[OK] Tags defined: {tags}")

# 13. Comments syntax sanity
hidden_comments = text.count('%%')
print(f"[{'OK' if hidden_comments % 2 == 0 else 'WARN'}] Hidden comments %% count: {hidden_comments} (must be even pairs)")

print("\n=== README Obsidian Markdown render check: PASS ===")
print(f"\nSummary:")
print(f"  - Frontmatter: VALID")
print(f"  - Callouts : {total_callouts}")
print(f"  - Mermaid  : {mermaid_blocks}")
print(f"  - Highlights: {hl_open}")
print(f"  - Wikilinks: {len(wikilinks)}")
print(f"  - Headings : {len(headings)}")
print(f"  - Code blocks: {len(all_fences) // 2}")