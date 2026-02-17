# pdf2md

将文字型 PDF 按页提取文本，自动识别标题层级，输出 Markdown 文件。支持单文件转换和按书签批量切割两种模式，提供 CLI 和 Web UI。

> **注意：** 本工具仅支持文字型 PDF，扫描件 PDF 需要先 OCR 处理。

## 功能

- **单文件转换** — 将 PDF 全部或指定页码范围转换为一个 Markdown 文件
- **按书签批量切割** — 支持 XML 书签文件或 PDF 内置书签（目录），将 PDF 按章节切割为多个 Markdown 文件并打包为 ZIP
- **多级书签层级目录** — 嵌套书签自动生成层级目录结构
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

# 按 XML 书签批量切割（默认偏移 +1，适用于 WPS 导出的书签）
python pdf2md.py input.pdf -b bookmarks.xml

# 使用 PDF 内置书签批量切割（默认偏移 0）
python pdf2md.py input.pdf --toc

# PDF 内置书签 + 手动偏移
python pdf2md.py input.pdf --toc --page-offset 1

# 书签页码本身准确时，设置偏移为 0
python pdf2md.py input.pdf -b bookmarks.xml --page-offset 0

# 自定义页面分隔符
python pdf2md.py input.pdf --page-sep "<!-- P{n} -->"
```

> `-b` 和 `--toc` 不能同时使用。

#### 完整参数

| 参数 | 说明 | 默认值 |
|---|---|---|
| `input` | 输入 PDF 文件路径 | （必填） |
| `-o, --output` | 输出路径（`.md` 或 `.zip`） | 同名 `.md` / `.zip` |
| `-p, --pages` | 页码范围，如 `1-5,8,10-12` | 全部页 |
| `-b, --bookmarks` | 书签 XML 文件路径，启用批量切割模式 | — |
| `--toc` | 使用 PDF 内置书签（目录）进行批量切割 | — |
| `--page-offset` | 书签页码偏移量（`-b` 默认 1，`--toc` 默认 0） | 按模式自动 |
| `--page-sep` | 页面分隔符模板，`{n}` 替换为页码 | `<!-- Page {n} -->` |

### Web UI

```bash
python web.py
```

启动后浏览器自动打开 `http://localhost:7860`，包含两个 Tab：

- **单文件转换** — 上传 PDF，可选填页码范围和输出文件名，点击"开始转换"后在线预览和下载
- **按书签批量切割** — 上传 PDF，可选上传书签 XML；留空 XML 时自动使用 PDF 内置书签。上传/清除 XML 文件时页码偏移自动切换默认值

## 书签格式

### 扁平 XML 书签

书签文件为 XML 格式，每个 `<ITEM>` 代表一个章节：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<BOOKMARKS>
  <ITEM NAME="第一章 绪论" PAGE="0"/>
  <ITEM NAME="第二章 基础理论" PAGE="15"/>
  <ITEM NAME="第三章 实验方法" PAGE="42"/>
</BOOKMARKS>
```

### 嵌套 XML 书签

支持嵌套 `<ITEM>` 表示多级目录结构：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<BOOKMARKS>
  <ITEM NAME="第一部分 基础" PAGE="0">
    <ITEM NAME="第一章 绪论" PAGE="0">
      <ITEM NAME="1.1 研究背景" PAGE="0"/>
      <ITEM NAME="1.2 研究目的" PAGE="5"/>
    </ITEM>
    <ITEM NAME="第二章 理论" PAGE="10"/>
  </ITEM>
  <ITEM NAME="第二部分 实践" PAGE="30"/>
</BOOKMARKS>
```

### PDF 内置书签

使用 `--toc` 参数直接读取 PDF 文件中嵌入的书签（目录），无需外部 XML 文件。

- `NAME` — 章节名称，用作输出文件名
- `PAGE` — 页码值（经 `page_offset` 修正后对应 PDF 实际页码）

WPS 导出的书签 `PAGE` 值通常比实际页码小 1，因此 `-b` 模式默认 `page_offset=1`。`--toc` 模式下 `get_toc()` 返回的页码通常已正确，默认 `page_offset=0`。

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

批量切割模式（扁平书签）输出 ZIP：

```
01_第一章_绪论.md
02_第二章_基础理论.md
03_第三章_实验方法.md
```

批量切割模式（多级书签）输出 ZIP，按层级生成目录结构：

```
01_第一部分_基础.md
第一部分_基础/01_第一章_绪论.md
第一部分_基础/第一章_绪论/01_1.1_研究背景.md
第一部分_基础/第一章_绪论/02_1.2_研究目的.md
第一部分_基础/02_第二章_理论.md
02_第二部分_实践.md
```

## License

MIT
