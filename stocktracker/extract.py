from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader


def extract_pdf_text(content: bytes, max_pages: int = 40, max_chars: int = 120_000) -> str:
    reader = PdfReader(BytesIO(content))
    chunks: list[str] = []
    size = 0
    for page in reader.pages[:max_pages]:
        text = page.extract_text() or ""
        chunks.append(text)
        size += len(text)
        if size >= max_chars:
            break
    return "\n".join(chunks)[:max_chars]

