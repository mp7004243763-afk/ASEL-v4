"""Safe, bounded extraction of user-provided chat attachments."""
from __future__ import annotations

import csv
import io
import os
from pathlib import PurePath

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TEXT_CHARS = 60_000
ALLOWED = {".pdf", ".docx", ".txt", ".md", ".csv", ".xlsx", ".pptx",
           ".jpg", ".jpeg", ".png", ".webp"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


class AttachmentError(ValueError):
    pass


def _check_signature(name: str, data: bytes) -> None:
    ext = PurePath(name).suffix.lower()
    if not data:
        raise AttachmentError("Файл пустой.")
    if len(data) > MAX_FILE_BYTES:
        raise AttachmentError("Файл превышает лимит 20 МБ.")
    if ext not in ALLOWED:
        raise AttachmentError(f"Формат {ext or 'без расширения'} не поддерживается.")
    if ext == ".pdf" and not data.startswith(b"%PDF-"):
        raise AttachmentError("Файл не похож на PDF.")
    if ext in IMAGE_EXTENSIONS:
        signatures = {
            ".jpg": data.startswith(b"\xff\xd8\xff"),
            ".jpeg": data.startswith(b"\xff\xd8\xff"),
            ".png": data.startswith(b"\x89PNG\r\n\x1a\n"),
            ".webp": len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP",
        }
        if not signatures[ext]:
            raise AttachmentError("Содержимое изображения не соответствует расширению.")
    if ext in {".docx", ".xlsx", ".pptx"} and not data.startswith(b"PK\x03\x04"):
        raise AttachmentError("Файл Office повреждён или имеет неверный формат.")


def extract_attachment(name: str, data: bytes) -> tuple[str, str]:
    """Return (kind, extracted text). Never executes embedded content."""
    _check_signature(name, data)
    ext = PurePath(name).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image", ""

    try:
        if ext in {".txt", ".md"}:
            text = data.decode("utf-8-sig")
        elif ext == ".csv":
            decoded = data.decode("utf-8-sig")
            rows = list(csv.reader(io.StringIO(decoded)))
            text = "\n".join(" | ".join(row) for row in rows[:5000])
        elif ext == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise AttachmentError("PDF защищён паролем. Сними защиту и загрузи снова.")
            chunks = []
            for page in reader.pages[:200]:
                chunks.append(page.extract_text() or "")
            text = "\n\n".join(chunks)
        elif ext == ".docx":
            from docx import Document
            doc = Document(io.BytesIO(data))
            chunks = [p.text for p in doc.paragraphs if p.text]
            for table in doc.tables[:30]:
                for row in table.rows[:300]:
                    chunks.append(" | ".join(cell.text for cell in row.cells))
            text = "\n".join(chunks)
        elif ext == ".xlsx":
            from openpyxl import load_workbook
            book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            chunks = []
            for sheet in book.worksheets[:20]:
                chunks.append(f"Лист: {sheet.title}")
                for row in sheet.iter_rows(min_row=1, max_row=2000, values_only=True):
                    values = ["" if v is None else str(v) for v in row[:40]]
                    if any(values):
                        chunks.append(" | ".join(values))
            book.close()
            text = "\n".join(chunks)
        elif ext == ".pptx":
            from pptx import Presentation
            deck = Presentation(io.BytesIO(data))
            chunks = []
            for i, slide in enumerate(deck.slides[:150], 1):
                chunks.append(f"Слайд {i}")
                for shape in slide.shapes:
                    if getattr(shape, "has_text_frame", False) and shape.text.strip():
                        chunks.append(shape.text.strip())
                    if getattr(shape, "has_table", False):
                        for row in shape.table.rows:
                            chunks.append(" | ".join(cell.text for cell in row.cells))
            text = "\n".join(chunks)
        else:
            raise AttachmentError("Этот формат пока не поддерживается.")
    except AttachmentError:
        raise
    except Exception as exc:
        raise AttachmentError(f"Не удалось прочитать файл {os.path.basename(name)} ({type(exc).__name__}).") from exc

    text = text.strip()
    if not text:
        text = "[В документе не найден извлекаемый текст. Возможно, это скан или документ без текстового слоя.]"
    return "document", text[:MAX_TEXT_CHARS]
