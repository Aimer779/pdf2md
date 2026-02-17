"""PDF 转 Markdown Web UI（基于 Gradio）。"""

import tempfile
import warnings
from pathlib import Path

import gradio as gr
import pymupdf

from pdf2md import PageRangeError, build_output_name, convert, extract_title, parse_page_ranges


def process_pdf(file_obj, page_range: str, custom_name: str) -> tuple[str, str, str | None, str]:
    """桥接 Gradio 组件与 pdf2md 核心逻辑。

    Returns: (raw_markdown, rendered_markdown, download_file_path, output_filename)
    """
    if file_obj is None:
        raise gr.Error("请先上传 PDF 文件")

    file_path = file_obj if isinstance(file_obj, str) else file_obj.name
    original_name = Path(file_path).stem

    try:
        doc = pymupdf.open(file_path)
        total_pages = len(doc)
        doc.close()
    except pymupdf.FileDataError:
        raise gr.Error("无法打开 PDF 文件，文件可能已损坏")

    page_indices: list[int] = []
    if page_range and page_range.strip():
        try:
            page_indices = parse_page_ranges(page_range.strip(), total_pages)
        except PageRangeError as e:
            raise gr.Error(str(e))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = convert(file_path, page_indices, "<!-- Page {n} -->")

    if caught:
        raise gr.Error(caught[0].message if isinstance(caught[0].message, str) else str(caught[0].message))

    title = extract_title(result)
    auto_name = build_output_name(original_name, title)

    if custom_name and custom_name.strip():
        final_name = custom_name.strip()
        if not final_name.endswith(".md"):
            final_name += ".md"
    else:
        final_name = auto_name

    tmp_path = Path(tempfile.gettempdir()) / final_name
    tmp_path.write_text(result, encoding="utf-8")

    return result, result, str(tmp_path), auto_name


def create_ui() -> gr.Blocks:
    """构建 Gradio Web UI。"""
    with gr.Blocks(title="PDF 转 Markdown", theme=gr.themes.Soft()) as app:
        gr.Markdown("# PDF 转 Markdown 工具")

        with gr.Row():
            with gr.Column(scale=1):
                file_input = gr.File(label="上传 PDF 文件", file_types=[".pdf"])
                page_range_input = gr.Textbox(
                    label="页码范围（可选）",
                    placeholder='例如: 1-5,8,10-12（留空表示全部页）',
                )
                output_name_input = gr.Textbox(
                    label="输出文件名（可选）",
                    placeholder="留空自动生成: pdf名_标题.md",
                )
                convert_btn = gr.Button("开始转换", variant="primary")

            with gr.Column(scale=2):
                with gr.Tabs():
                    with gr.TabItem("渲染预览"):
                        rendered_output = gr.Markdown(label="渲染预览")
                    with gr.TabItem("原始文本"):
                        raw_output = gr.Textbox(
                            label="原始 Markdown",
                            lines=20,
                            show_copy_button=True,
                        )
                download_output = gr.File(label="下载 Markdown 文件")

        convert_btn.click(
            fn=process_pdf,
            inputs=[file_input, page_range_input, output_name_input],
            outputs=[raw_output, rendered_output, download_output, output_name_input],
        )

    return app


if __name__ == "__main__":
    app = create_ui()
    app.launch(server_name="0.0.0.0", server_port=7860, inbrowser=True)
