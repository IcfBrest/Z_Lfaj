"""简历本地文本抽取：PDF / DOCX / Markdown。零 LLM 成本。"""

import io

from fastapi import HTTPException


def extract_pdf(data: bytes) -> str:
    import fitz  # PyMuPDF

    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise HTTPException(400, f"无法读取 PDF 文件：{exc}") from exc
    pages = [page.get_text("text") for page in doc]
    doc.close()
    return "\n".join(pages).strip()


def extract_docx(data: bytes) -> str:
    from docx import Document

    try:
        doc = Document(io.BytesIO(data))
    except Exception as exc:
        raise HTTPException(400, f"无法读取 DOCX 文件：{exc}") from exc
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            parts.extend(cell.text for cell in row.cells if cell.text.strip())
    return "\n".join(parts).strip()


def extract_text(data: bytes, file_format: str) -> str:
    if file_format == "pdf":
        text = extract_pdf(data)
    elif file_format == "docx":
        text = extract_docx(data)
    elif file_format == "md":
        try:
            text = data.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise HTTPException(400, "Markdown 文件必须是 UTF-8 编码") from exc
    else:
        raise HTTPException(400, f"不支持的格式：{file_format}")
    if not text:
        raise HTTPException(400, "未抽取到任何文本（可能是扫描件/图片型文件），请换文本型文件")
    return text
