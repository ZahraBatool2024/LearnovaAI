"""
File -> plain text extraction. One job: given a path, return text.
Supports PDF, DOCX, PPTX, TXT/MD. Old binary .doc/.ppt are rejected
with a clear message, same as in the earlier prototypes.
"""

import os


class UnsupportedFileError(Exception):
    pass


def extract_text_from_path(path: str) -> str:
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    if ext == "pdf":
        return _extract_pdf(path)
    if ext == "docx":
        return _extract_docx(path)
    if ext == "pptx":
        return _extract_pptx(path)
    if ext in ("txt", "md"):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    raise UnsupportedFileError(
        f"Unsupported format '.{ext}'. Use PDF, DOCX, PPTX, or TXT — "
        f"old .doc/.ppt files need to be re-saved first."
    )


def _extract_pdf(path: str) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError("PDF support needs: pip install pypdf")
    reader = PdfReader(path)
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def _extract_docx(path: str) -> str:
    try:
        import docx  # python-docx
    except ImportError:
        raise RuntimeError("DOCX support needs: pip install python-docx")
    document = docx.Document(path)
    return "\n".join(p.text for p in document.paragraphs)


def _extract_pptx(path: str) -> str:
    try:
        from pptx import Presentation
    except ImportError:
        raise RuntimeError("PPTX support needs: pip install python-pptx")
    prs = Presentation(path)
    slides_text = []
    for slide in prs.slides:
        runs = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    for run in para.runs:
                        runs.append(run.text)
        slides_text.append(" ".join(runs))
    return "\n\n".join(slides_text)
