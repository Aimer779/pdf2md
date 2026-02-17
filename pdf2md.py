"""PDF 按页切割转 Markdown 工具。

将文字型 PDF 按页提取文本，识别标题层级，输出合并的 Markdown 文件。
"""

import argparse
import re
import sys
import unicodedata
import warnings
from collections import Counter
from pathlib import Path

import pymupdf


class PageRangeError(ValueError):
    """页码范围解析错误。"""


def parse_page_ranges(spec: str, total: int) -> list[int]:
    """解析页码范围字符串，返回 0-based 页码列表。

    支持格式: "1-5,8,10-12"
    """
    pages = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            try:
                start, end = int(start_s), int(end_s)
            except ValueError:
                raise PageRangeError(f"无效的页码范围: {part}")
            if start < 1 or end > total:
                raise PageRangeError(f"页码范围 {part} 越界，PDF 共 {total} 页")
            if start > end:
                raise PageRangeError(f"无效的页码范围: {part}")
            pages.extend(range(start - 1, end))
        else:
            try:
                n = int(part)
            except ValueError:
                raise PageRangeError(f"无效的页码: {part}")
            if n < 1 or n > total:
                raise PageRangeError(f"页码 {n} 越界，PDF 共 {total} 页")
            pages.append(n - 1)
    return pages


def is_cjk_char(ch: str) -> bool:
    """判断字符是否为 CJK 字符。"""
    try:
        name = unicodedata.name(ch, "")
    except ValueError:
        return False
    return "CJK" in name or "HIRAGANA" in name or "KATAKANA" in name or "HANGUL" in name


def is_cjk_text(text: str) -> bool:
    """检测文本是否以 CJK 字符为主（占比 >30%）。"""
    if not text:
        return False
    total = sum(1 for ch in text if not ch.isspace())
    if total == 0:
        return False
    cjk_count = sum(1 for ch in text if is_cjk_char(ch))
    return cjk_count / total > 0.3


def collect_font_stats(doc: pymupdf.Document, page_indices: list[int]) -> Counter:
    """第一遍扫描：统计每个字体大小出现的字符数量。"""
    size_counter: Counter[float] = Counter()
    for idx in page_indices:
        page = doc[idx]
        data = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)
        for block in data["blocks"]:
            if block["type"] != 0:  # 只处理文本块
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span["text"].strip()
                    if text:
                        size = round(span["size"], 1)
                        size_counter[size] += len(text)
    return size_counter


def build_heading_map(size_counter: Counter, body_size: float) -> dict[float, int]:
    """构建字体大小到标题层级的映射。

    大于正文字体的大小按降序映射为 h1~h6。
    """
    heading_sizes = sorted(
        (s for s in size_counter if s > body_size),
        reverse=True,
    )
    heading_map = {}
    for i, size in enumerate(heading_sizes):
        level = min(i + 1, 6)
        heading_map[size] = level
    return heading_map


def process_line(line: dict) -> tuple[str, float]:
    """处理一行，返回合并文本和该行最大字体大小。"""
    texts = []
    max_size = 0.0
    for span in line["spans"]:
        text = span["text"]
        if text.strip():
            texts.append(text)
            max_size = max(max_size, round(span["size"], 1))
    merged = "".join(texts).strip()
    return merged, max_size


def merge_lines(lines: list[str], cjk_mode: bool) -> str:
    """合并连续的普通文本行为段落。"""
    if cjk_mode:
        return "".join(lines)
    return " ".join(lines)


def process_page(
    page: pymupdf.Page,
    heading_map: dict[float, int],
    body_size: float,
) -> str:
    """处理单页，返回该页的 Markdown 文本。"""
    data = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_WHITESPACE)
    page_parts: list[str] = []

    for block in data["blocks"]:
        if block["type"] != 0:
            continue

        block_parts: list[str] = []
        pending_lines: list[str] = []  # 待合并的普通文本行

        for line in block["lines"]:
            text, max_size = process_line(line)
            if not text:
                continue

            level = heading_map.get(max_size)
            if level is not None:
                # 遇到标题行，先 flush 暂存的普通文本
                if pending_lines:
                    cjk = is_cjk_text("".join(pending_lines))
                    block_parts.append(merge_lines(pending_lines, cjk))
                    pending_lines = []
                block_parts.append(f"{'#' * level} {text}")
            else:
                pending_lines.append(text)

        # flush 剩余普通文本
        if pending_lines:
            cjk = is_cjk_text("".join(pending_lines))
            block_parts.append(merge_lines(pending_lines, cjk))

        if block_parts:
            page_parts.append("\n\n".join(block_parts))

    return "\n\n".join(page_parts)


def convert(
    input_path: str,
    page_indices: list[int],
    page_sep: str,
) -> str:
    """主转换函数：两遍扫描，输出完整 Markdown 文本。"""
    doc = pymupdf.open(input_path)

    if not page_indices:
        page_indices = list(range(len(doc)))

    # 第一遍：字体统计
    size_counter = collect_font_stats(doc, page_indices)

    if not size_counter:
        warnings.warn("未提取到任何文本，可能是扫描件 PDF，需要 OCR 处理")
        doc.close()
        return ""

    body_size = size_counter.most_common(1)[0][0]
    heading_map = build_heading_map(size_counter, body_size)

    # 第二遍：逐页提取
    sections: list[str] = []
    for i, idx in enumerate(page_indices):
        page_num = idx + 1  # 1-based 显示用
        page = doc[idx]
        content = process_page(page, heading_map, body_size)

        parts: list[str] = []
        if i > 0:
            parts.append("---")
            parts.append("")
        parts.append(page_sep.format(n=page_num))
        parts.append("")
        if content:
            parts.append(content)
        sections.append("\n".join(parts))

    doc.close()
    return "\n\n".join(sections) + "\n"


def extract_title(markdown: str) -> str | None:
    """从 Markdown 文本中提取第一个 h1 标题。"""
    m = re.search(r'^# (.+)$', markdown, re.MULTILINE)
    return m.group(1).strip() if m else None


def build_output_name(pdf_stem: str, title: str | None) -> str:
    """根据 PDF 文件名和提取的标题生成输出文件名。"""
    if title:
        sanitized = re.sub(r'[\\/:*?"<>|]', '', title).strip()
        if not sanitized:
            sanitized = "untitled"
        sanitized = sanitized[:80]
        return f"{pdf_stem}_{sanitized}.md"
    return f"{pdf_stem}_untitled.md"


def main():
    parser = argparse.ArgumentParser(
        description="将文字型 PDF 按页转换为 Markdown 文件",
    )
    parser.add_argument("input", help="输入 PDF 文件路径")
    parser.add_argument("-o", "--output", help="输出 Markdown 路径（默认: 同名.md）")
    parser.add_argument("-p", "--pages", help='页码范围，如 "1-5,8,10-12"（默认: 全部）')
    parser.add_argument(
        "--page-sep",
        default="<!-- Page {n} -->",
        help="页面分隔符模板，{n} 替换为页码（默认: <!-- Page {n} -->）",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"错误: 文件不存在: {input_path}", file=sys.stderr)
        sys.exit(1)

    try:
        doc = pymupdf.open(str(input_path))
        total_pages = len(doc)
        doc.close()
    except pymupdf.FileDataError:
        print(f"错误: 无法打开 PDF 文件，文件可能已损坏: {input_path}", file=sys.stderr)
        sys.exit(1)

    page_indices: list[int] = []
    if args.pages:
        try:
            page_indices = parse_page_ranges(args.pages, total_pages)
        except PageRangeError as e:
            print(f"错误: {e}", file=sys.stderr)
            sys.exit(1)

    try:
        result = convert(str(input_path), page_indices, args.page_sep)
    except pymupdf.FileDataError:
        print(f"错误: PDF 文件读取失败: {input_path}", file=sys.stderr)
        sys.exit(1)

    if args.output:
        output_path = Path(args.output)
    else:
        title = extract_title(result)
        output_name = build_output_name(input_path.stem, title)
        output_path = input_path.parent / output_name

    try:
        output_path.write_text(result, encoding="utf-8")
    except PermissionError:
        print(f"错误: 无法写入输出文件: {output_path}", file=sys.stderr)
        sys.exit(1)

    print(f"已转换 {len(page_indices) or total_pages} 页 -> {output_path}")


if __name__ == "__main__":
    main()
