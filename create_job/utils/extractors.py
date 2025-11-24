import fitz
from docx import Document
from docx2python import docx2python
import mammoth
from io import BytesIO

def extract_text_from_pdf(file_obj):
    data = file_obj.read()
    if not data:
        return "", {"error": "empty_stream"}
    doc = fitz.open(stream=data, filetype="pdf")
    text = ""
    for page in doc:
        text += page.get_text() + "\n"
    return text, {"method": "pymupdf", "bytes": len(data)}

def extract_text_from_docx(file_obj):
    """
    Tries multiple ways to extract text from a DOCX file-like object.
    Returns (text, diagnostics_dict).
    diagnostics_dict contains: bytes, tried_methods, success_method (or error)
    """
    tried = []
    errors = {}
    # Read bytes once (some DRF file objects aren't seekable)
    file_bytes = file_obj.read()
    diagnostics = {"bytes": len(file_bytes), "tried": [], "errors": {}}

    if not file_bytes:
        diagnostics["errors"]["read"] = "empty file bytes"
        return "", diagnostics

    # Helper to create a fresh BytesIO for each library
    def bstream():
        return BytesIO(file_bytes)

    # 1) python-docx
    try:
        diagnostics["tried"].append("python-docx")
        b = bstream()
        doc = Document(b)
        paragraphs = [p.text for p in doc.paragraphs if p.text and p.text.strip()]
        text = "\n".join(paragraphs).strip()
        if text:
            diagnostics["success"] = "python-docx"
            return text, diagnostics
        else:
            diagnostics["errors"]["python-docx"] = "no text extracted"
    except Exception as e:
        diagnostics["errors"]["python-docx"] = repr(e)

    # 2) docx2python (can extract from some odd docx variants)
    try:
        diagnostics["tried"].append("docx2python")
        b = bstream()
        # docx2python returns a complex object; .text flattens it
        res = docx2python(b)
        # res.text is a list of lists sometimes; convert to string
        raw = ""
        try:
            # prefer res.text if available
            if hasattr(res, "text"):
                if isinstance(res.text, (list, tuple)):
                    # flatten nested lists
                    def flatten(x):
                        out = []
                        for e in x:
                            if isinstance(e, (list, tuple)):
                                out += flatten(e)
                            else:
                                out.append(str(e))
                        return out
                    flat = flatten(res.text)
                    raw = "\n".join([s for s in flat if s and s.strip()])
                else:
                    raw = str(res.text)
            else:
                # fallback to str(res)
                raw = str(res)
        except Exception:
            raw = str(res)
        raw = raw.strip()
        if raw:
            diagnostics["success"] = "docx2python"
            return raw, diagnostics
        else:
            diagnostics["errors"]["docx2python"] = "no text extracted"
    except Exception as e:
        diagnostics["errors"]["docx2python"] = repr(e)

    # 3) mammoth (another fallback)
    try:
        diagnostics["tried"].append("mammoth")
        b = bstream()
        # mammoth.extract_raw_text accepts a file-like object
        result = mammoth.extract_raw_text(b)
        if hasattr(result, "value"):
            raw = result.value.strip()
        else:
            raw = str(result).strip()
        if raw:
            diagnostics["success"] = "mammoth"
            return raw, diagnostics
        else:
            diagnostics["errors"]["mammoth"] = "no text extracted"
    except Exception as e:
        diagnostics["errors"]["mammoth"] = repr(e)

    # nothing worked
    diagnostics["error"] = "no extractor succeeded"
    return "", diagnostics
