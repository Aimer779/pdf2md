# pdf2md

将文字型 PDF 按页提取文本，自动识别标题层级，输出 Markdown 文件。支持单文件转换和按书签批量切割两种模式，提供 CLI 和 Web UI。

> **注意：** 本工具仅支持文字型 PDF，扫描件 PDF 需要先 OCR 处理。

## 功能

- **单文件转换** — 将 PDF 全部或指定页码范围转换为一个 Markdown 文件
- **按书签批量切割** — 配合 XML 书签文件，将 PDF 按章节切割为多个 Markdown 文件并打包为 ZIP
- **标题自动识别** — 基于字体大小统计，自动将大于正文的字体映射为 `h1`~`h6`
- **页码偏移修正** — 支持配置 `page_offset`，修正 WPS 等导出的书签页码偏差
- **Web UI** — 基于 Gradio 的浏览器界面，上传即用

## 安装

```bash
pip install -r requirements.txt
```

依赖：

| 包 | 最低版本 | 用途 |
|---|---|---|
| PyMuPDF | 1.25.0 | PDF 文本提取 |
| gradio | 5.0.0 | Web UI（仅 `web.py` 需要） |

## 使用方法

### CLI

```bash
# 基本用法 — 转换全部页面
python pdf2md.py input.pdf

# 指定页码范围
python pdf2md.py input.pdf -p "1-5,8,10-12"

# 指定输出路径
python pdf2md.py input.pdf -o output.md

# 按书签批量切割（默认偏移 +1，适用于 WPS 导出的书签）
python pdf2md.py input.pdf -b bookmarks.xml

# 书签页码本身准确时，设置偏移为 0
python pdf2md.py input.pdf -b bookmarks.xml --page-offset 0

# 自定义页面分隔符
python pdf2md.py input.pdf --page-sep "<!-- P{n} -->"
```

#### 完整参数

| 参数 | 说明 | 默认值 |
|---|---|---|
| `input` | 输入 PDF 文件路径 | （必填） |
| `-o, --output` | 输出路径（`.md` 或 `.zip`） | 同名 `.md` / `.zip` |
| `-p, --pages` | 页码范围，如 `1-5,8,10-12` | 全部页 |
| `-b, --bookmarks` | 书签 XML 文件路径，启用批量切割模式 | — |
| `--page-offset` | 书签页码偏移量（实际页 = PAGE + offset） | `1` |
| `--page-sep` | 页面分隔符模板，`{n}` 替换为页码 | `<!-- Page {n} -->` |

### Web UI

```bash
python web.py
```

启动后浏览器自动打开 `http://localhost:7860`，包含两个 Tab：

- **单文件转换** — 上传 PDF，可选填页码范围和输出文件名，点击"开始转换"后在线预览和下载
- **按书签批量切割** — 上传 PDF 和书签 XML，调整页码偏移值，点击"批量切割"后下载 ZIP

## 书签 XML 格式

书签文件为 XML 格式，每个 `<ITEM>` 代表一个章节：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<BOOKMARKS>
  <ITEM NAME="第一章 绪论" PAGE="0"/>
  <ITEM NAME="第二章 基础理论" PAGE="15"/>
  <ITEM NAME="第三章 实验方法" PAGE="42"/>
</BOOKMARKS>
```

- `NAME` — 章节名称，用作输出文件名
- `PAGE` — 页码值（经 `page_offset` 修正后对应 PDF 实际页码）

WPS 导出的书签 `PAGE` 值通常比实际页码小 1，因此默认 `page_offset=1`。如果书签页码已经准确，使用 `--page-offset 0`。

## 输出示例

单文件模式输出格式：

```markdown
<!-- Page 1 -->

# 第一章 绪论

正文内容...

---

<!-- Page 2 -->

## 1.1 研究背景

正文内容...
```

批量切割模式输出 ZIP，内含按序号命名的 Markdown 文件：

```
01_第一章_绪论.md
02_第二章_基础理论.md
03_第三章_实验方法.md
```

## License

MIT
