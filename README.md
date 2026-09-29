# docx-embed

在 Word `.docx` 的指定段落位置嵌入**真正的附件对象**（OLE Package，显示为图标），不是超链接。

## 安装

```bash
pip install -e .
# 开发测试
pip install -e ".[dev]"
```

## 用法

```python
from docx_embed import DocxEmbedder

emb = DocxEmbedder("input.docx")

# 插入到某一级标题之后（作为正文段落）
emb.insert_after_heading(
    "report.pdf",
    level=1,              # Heading 1 / 标题1
    title="附录",         # 可选：按标题文本精确匹配
    occurrence=1,         # 第几个匹配
)

# 或按段落索引（0-based，默认插在该段落后）
emb.insert_at_paragraph("notes.txt", index=3)

emb.save("output.docx")
```

## 原理简述

`.docx` 是 OPC（ZIP + XML）。本库会：

1. 把附件打成 OLE Package（`word/embeddings/oleObjectN.bin`，CFB + `\x01Ole10Native`）
2. 写入图标 EMF（`word/media/imageN.emf`）
3. 更新 `document.xml.rels` 与 `[Content_Types].xml`
4. 在 `document.xml` 目标位置插入带 `o:OLEObject ProgID="Package" DrawAspect="Icon"` 的段落

标题识别支持：

- 样式名 `Heading1`…`Heading9` / `标题1`…`标题9`
- 段落上的 `w:outlineLvl`（0-based → 级别 +1）

## 限制

- 需要用 Microsoft Word / WPS 等支持 OLE 包对象的客户端打开；纯在线预览器可能只显示图标
- 图标为内置简易 EMF，不是系统文件类型图标
- 最小依赖：仅 Python 标准库

## 许可证

MIT
