"""PDF 按页切割转 Markdown 工具。

将文字型 PDF 按页提取文本，识别标题层级，输出合并的 Markdown 文件。
"""

import argparse
import re
import sys
import unicodedata
import warnings
import zipfile
from collections import Counter
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree

import pymupdf


class PageRangeError(ValueError):
    """页码范围解析错误。"""


class BookmarkError(ValueError):
    """书签解析错误。"""


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
    sanitized = sanitize_filename(title) if title else "untitled"
    return f"{pdf_stem}_{sanitized}.md"


def sanitize_filename(name: str) -> str:
    """清理文件名：去除非法字符，空白替换为下划线，截断到 80 字符。"""
    sanitized = re.sub(r'[\\/:*?"<>|]', '', name).strip()
    sanitized = re.sub(r'\s+', '_', sanitized)
    sanitized = sanitized[:80]
    return sanitized if sanitized else "untitled"


def _walk_xml_items(element, depth=1):
    """递归遍历 XML 树，捕获嵌套深度。"""
    results = []
    for item in element.findall("ITEM"):  # 仅直接子节点
        name = item.get("NAME", "").strip()
        page_str = item.get("PAGE", "")
        if name and page_str:
            results.append((name, page_str, depth))
        results.extend(_walk_xml_items(item, depth + 1))
    return results


def _compute_page_ranges(items, total_pages):
    """将 [(name, page_1based, level), ...] 转换为 [(name, start_0, end_0, level), ...]。"""
    items.sort(key=lambda x: x[1])
    chapters = []
    for i, (name, page, level) in enumerate(items):
        start = page - 1
        end = (max(items[i + 1][1] - 2, start) if i + 1 < len(items) else total_pages - 1)
        chapters.append((name, start, end, level))
    return chapters


def parse_bookmarks(xml_path: str, total_pages: int, page_offset: int = 1) -> list[tuple[str, int, int, int]]:
    """解析 XML 书签文件，返回章节列表 [(name, start_0based, end_0based, level), ...]。"""
    tree = ElementTree.parse(xml_path)
    root = tree.getroot()

    raw_items = _walk_xml_items(root)
    if not raw_items:
        raise BookmarkError("书签文件中未找到任何 ITEM 条目")

    items = []
    for name, page_str, depth in raw_items:
        try:
            page = int(page_str)
        except ValueError:
            raise BookmarkError(f"无效的页码: {page_str}（章节: {name}）")
        page += page_offset
        if page < 1 or page > total_pages:
            raise BookmarkError(f"页码 {page} 越界，PDF 共 {total_pages} 页（章节: {name}）")
        items.append((name, page, depth))

    return _compute_page_ranges(items, total_pages)


def parse_bookmarks_from_toc(pdf_path: str, total_pages: int, page_offset: int = 0) -> list[tuple[str, int, int, int]]:
    """从 PDF 内嵌书签（目录）读取章节列表，返回 [(name, start_0based, end_0based, level), ...]。"""
    doc = pymupdf.open(pdf_path)
    toc = doc.get_toc(simple=True)  # [[level, title, page_1based], ...]
    doc.close()

    if not toc:
        raise BookmarkError("PDF 文件中未找到内置书签（目录）")

    items = []
    for level, title, page_1based in toc:
        name = title.strip()
        if not name:
            continue
        page = page_1based + page_offset
        if page < 1 or page > total_pages:
            raise BookmarkError(f"页码 {page} 越界，PDF 共 {total_pages} 页（章节: {name}）")
        items.append((name, page, level))

    if not items:
        raise BookmarkError("PDF 内置书签中未找到有效条目")

    return _compute_page_ranges(items, total_pages)


def batch_convert_to_zip(pdf_path: str, page_sep: str, chapters: list[tuple[str, int, int, int]]) -> bytes:
    """按书签将 PDF 批量切割为 Markdown 文件，打包为 ZIP 返回 bytes。"""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        path_context = {}   # level -> sanitized_name
        counters = {}       # parent_path -> seq_number

        for name, start, end, level in chapters:
            # 清除 >= level 的旧路径上下文
            for k in list(path_context):
                if k >= level:
                    del path_context[k]

            # 从祖先节点构建目录路径
            parent_parts = [path_context[l] for l in sorted(path_context) if l < level]
            parent_key = "/".join(parent_parts)

            # 同级顺序编号
            counters[parent_key] = counters.get(parent_key, 0) + 1
            seq = counters[parent_key]

            filename = f"{seq:02d}_{sanitize_filename(name)}.md"
            full_path = f"{parent_key}/{filename}" if parent_key else filename

            path_context[level] = sanitize_filename(name)

            page_indices = list(range(start, end + 1))
            md_text = convert(pdf_path, page_indices, page_sep)
            zf.writestr(full_path, md_text)

    return buf.getvalue()


def main():
    parser = argparse.ArgumentParser(
        description="将文字型 PDF 按页转换为 Markdown 文件",
    )
    parser.add_argument("input", help="输入 PDF 文件路径")
    parser.add_argument("-o", "--output", help="输出路径（默认: 同名.md 或 .zip）")
    parser.add_argument("-p", "--pages", help='页码范围，如 "1-5,8,10-12"（默认: 全部）')
    parser.add_argument("-b", "--bookmarks", help="书签 XML 文件路径，启用按书签批量切割模式")
    parser.add_argument(
        "--toc",
        action="store_true",
        help="使用 PDF 内置书签（目录）进行批量切割",
    )
    parser.add_argument(
        "--page-sep",
        default="<!-- Page {n} -->",
        help="页面分隔符模板，{n} 替换为页码（默认: <!-- Page {n} -->）",
    )
    parser.add_argument(
        "--page-offset",
        type=int,
        default=None,
        help="书签页码偏移量（-b 默认 1，--toc 默认 0）",
    )
    args = parser.parse_args()

    if args.bookmarks and args.toc:
        print("错误: -b/--bookmarks 和 --toc 不能同时使用", file=sys.stderr)
        sys.exit(1)

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

    if args.bookmarks or args.toc:
        # 书签批量切割模式
        if args.pages:
            print("警告: 书签模式下忽略 --pages 参数", file=sys.stderr)

        try:
            if args.bookmarks:
                bookmark_path = Path(args.bookmarks)
                if not bookmark_path.exists():
                    print(f"错误: 书签文件不存在: {bookmark_path}", file=sys.stderr)
                    sys.exit(1)
                page_offset = args.page_offset if args.page_offset is not None else 1
                chapters = parse_bookmarks(str(bookmark_path), total_pages, page_offset=page_offset)
            else:
                page_offset = args.page_offset if args.page_offset is not None else 0
                chapters = parse_bookmarks_from_toc(str(input_path), total_pages, page_offset=page_offset)

            zip_bytes = batch_convert_to_zip(str(input_path), args.page_sep, chapters)
        except BookmarkError as e:
            print(f"错误: {e}", file=sys.stderr)
            sys.exit(1)
        except pymupdf.FileDataError:
            print(f"错误: PDF 文件读取失败: {input_path}", file=sys.stderr)
            sys.exit(1)

        if args.output:
            output_path = Path(args.output)
        else:
            output_path = input_path.with_suffix(".zip")

        try:
            output_path.write_bytes(zip_bytes)
        except PermissionError:
            print(f"错误: 无法写入输出文件: {output_path}", file=sys.stderr)
            sys.exit(1)

        print(f"已按书签切割 -> {output_path}")
    else:
        # 原有单文件模式
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
