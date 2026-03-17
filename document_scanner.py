"""
document_scanner.py
──────────────────────────────────────────────────────────────────────
Document Scanning Pipeline for Indian Trade Intelligence Engine
Supports: PDF, PNG, JPG, JPEG

Extraction strategies (in order):
  1. pdfplumber        — selectable-text PDFs + tables
  2. PyMuPDF text      — selectable-text fallback
  3. PyMuPDF blocks    — raw character extraction (embedded fonts)
  4. Render + OCR      — scanned PDFs (needs Tesseract binary)

Install Python libs:  pip install pdfplumber pymupdf pytesseract Pillow
Tesseract binary:
  Windows : https://github.com/UB-Mannheim/tesseract/wiki
  Ubuntu  : sudo apt-get install tesseract-ocr
  macOS   : brew install tesseract

Strategies 1-3 work WITHOUT Tesseract for native PDFs.
──────────────────────────────────────────────────────────────────────
"""

import io
import os
import re
import logging
import shutil
from pathlib import Path

logger = logging.getLogger("document_scanner")


def _configure_tesseract() -> bool:
    """
    Auto-detect Tesseract binary and set pytesseract.tesseract_cmd explicitly.

    Priority order:
      1. TESSERACT_CMD env variable  (highest priority — set this in .env to override)
      2. TESSERACT_CMD in .env file  (if env var not loaded by the shell)
      3. Common Windows install paths (Program Files\\Tesseract-OCR)
      4. Common Linux / macOS paths
      5. shutil.which("tesseract")   (PATH — but we still set cmd explicitly)

    Always sets pytesseract.pytesseract.tesseract_cmd — never relies on PATH
    inheritance alone, which is unreliable inside Streamlit's subprocess.

    Returns True if a working Tesseract binary was found and configured.
    """
    try:
        import pytesseract

        def _try_path(path: str) -> bool:
            """Set tesseract_cmd to path and verify it actually works."""
            if not path or not os.path.isfile(path):
                return False
            pytesseract.pytesseract.tesseract_cmd = path
            try:
                pytesseract.get_tesseract_version()
                logger.info(f"Tesseract configured: {path}")
                return True
            except Exception:
                return False

        # 1. TESSERACT_CMD environment variable (highest priority)
        env_path = os.environ.get("TESSERACT_CMD", "").strip().strip('"').strip("'")
        if env_path and _try_path(env_path):
            return True

        # 2. TESSERACT_CMD in .env file (Streamlit may not load .env automatically)
        try:
            for candidate in [Path(".env"), Path(__file__).parent / ".env",
                               Path(__file__).parent.parent / ".env"]:
                if candidate.exists():
                    for line in candidate.read_text(encoding="utf-8").splitlines():
                        line = line.strip()
                        if line.startswith("TESSERACT_CMD="):
                            val = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if val and _try_path(val):
                                return True
                    break
        except Exception:
            pass

        # 3. Common Windows install paths (covers default UB-Mannheim installer)
        win_paths = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
            os.path.expanduser(r"~\AppData\Local\Tesseract-OCR\tesseract.exe"),
            r"C:\tools\Tesseract-OCR\tesseract.exe",
            r"C:\ProgramData\chocolatey\bin\tesseract.exe",
        ]
        for path in win_paths:
            if _try_path(path):
                return True

        # 4. Common Linux / macOS paths
        unix_paths = [
            "/usr/bin/tesseract",
            "/usr/local/bin/tesseract",
            "/opt/homebrew/bin/tesseract",    # macOS Homebrew (Apple Silicon)
            "/usr/local/Cellar/tesseract/*/bin/tesseract",  # Homebrew Intel
            "/opt/local/bin/tesseract",       # MacPorts
        ]
        for path in unix_paths:
            if "*" in path:
                import glob
                matches = sorted(glob.glob(path), reverse=True)
                for m in matches:
                    if _try_path(m):
                        return True
            elif _try_path(path):
                return True

        # 5. Fallback: PATH-based detection — still set cmd explicitly
        which_result = shutil.which("tesseract")
        if which_result:
            pytesseract.pytesseract.tesseract_cmd = which_result
            try:
                pytesseract.get_tesseract_version()
                logger.info(f"Tesseract found via PATH: {which_result}")
                return True
            except Exception:
                pass

        logger.warning(
            "Tesseract binary not found. "
            "Add TESSERACT_CMD=C:\\Program Files\\Tesseract-OCR\\tesseract.exe to your .env file, "
            "or install from https://github.com/UB-Mannheim/tesseract/wiki"
        )
        return False

    except ImportError:
        return False


# Configure Tesseract at module import time
_TESSERACT_AVAILABLE = _configure_tesseract()

SUPPORTED_FORMATS = ["pdf", "png", "jpg", "jpeg"]


def _try_import(module_name: str):
    try:
        import importlib
        return importlib.import_module(module_name)
    except ImportError:
        return None


# ════════════════════════════════════════════════════════════════════
# TEXT CLEANING
# ════════════════════════════════════════════════════════════════════

def _clean_extracted_text(raw: str) -> str:
    if not raw:
        return ""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\f", "\n--- PAGE BREAK ---\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?<=\d)O(?=\d)", "0", text)
    text = text.replace("\x00", "")
    return text.strip()


# ════════════════════════════════════════════════════════════════════
# PDF STRATEGIES
# ════════════════════════════════════════════════════════════════════

def _strategy1_pdfplumber(file_bytes: bytes):
    pdfplumber = _try_import("pdfplumber")
    if not pdfplumber:
        raise ImportError("pdfplumber not installed")
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        pages = []
        for i, page in enumerate(pdf.pages):
            page_text = page.extract_text() or ""
            tables = page.extract_tables() or []
            table_text = ""
            for table in tables:
                for row in table:
                    if row:
                        row_clean = [str(c).strip() if c else "" for c in row]
                        table_text += "  |  ".join(row_clean) + "\n"
            combined = page_text
            if table_text and table_text not in page_text:
                combined = page_text + "\n" + table_text
            if combined.strip():
                pages.append(f"[Page {i+1}]\n{combined}")
        return "\n\n".join(pages), len(pdf.pages)


def _strategy2_pymupdf_text(file_bytes: bytes):
    fitz = _try_import("fitz")
    if not fitz:
        raise ImportError("PyMuPDF not installed")
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text("text")
        if text.strip():
            pages.append(f"[Page {i+1}]\n{text}")
    n = len(doc)
    doc.close()
    return "\n\n".join(pages), n


def _strategy3_pymupdf_blocks(file_bytes: bytes):
    fitz = _try_import("fitz")
    if not fitz:
        raise ImportError("PyMuPDF not installed")
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages = []
    for i, page in enumerate(doc):
        blocks = page.get_text("blocks")
        lines = [b[4].strip() for b in blocks if len(b) >= 5 and b[4].strip()]
        if lines:
            pages.append(f"[Page {i+1}]\n" + "\n".join(lines))
    n = len(doc)
    doc.close()
    return "\n\n".join(pages), n


def _strategy4_render_ocr(file_bytes: bytes, enhance: bool = True):
    # Always re-run configure to pick up any newly installed binary or .env change.
    # This is cheap (file-exists checks) and fixes cases where Tesseract was
    # installed after the module was first imported.
    _configure_tesseract()

    fitz = _try_import("fitz")
    if not fitz:
        raise ImportError("PyMuPDF required for scanned PDF OCR")

    pytesseract = _try_import("pytesseract")
    if not pytesseract:
        raise ImportError(
            "pytesseract not installed. Run: pip install pytesseract\n"
            "Also install Tesseract binary:\n"
            "  Windows: https://github.com/UB-Mannheim/tesseract/wiki\n"
            "  Ubuntu:  sudo apt-get install tesseract-ocr"
        )

    try:
        pytesseract.get_tesseract_version()
    except Exception:
        raise RuntimeError(
            "Tesseract binary not found on your system.\n"
            "pip install pytesseract only installs the Python wrapper.\n"
            "You must also install the Tesseract engine:\n"
            "  Windows: https://github.com/UB-Mannheim/tesseract/wiki\n"
            "    (download .exe, install, add C:\\Program Files\\Tesseract-OCR\\ to PATH)\n"
            "  Ubuntu/WSL: sudo apt-get install tesseract-ocr\n"
            "  macOS: brew install tesseract\n"
            "Then restart your terminal and run: streamlit run app.py"
        )

    PIL_mod = _try_import("PIL.Image")
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    pages = []
    for i, page in enumerate(doc):
        mat = fitz.Matrix(3.0, 3.0)  # 216 DPI
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img_bytes = pix.tobytes("png")

        if PIL_mod and enhance:
            from PIL import Image as _PIL, ImageFilter, ImageEnhance
            img = _PIL.open(io.BytesIO(img_bytes)).convert("L")
            img = img.filter(ImageFilter.SHARPEN)
            img = ImageEnhance.Contrast(img).enhance(1.5)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            img_bytes = buf.getvalue()

        from PIL import Image as _PIL_raw
        text = pytesseract.image_to_string(
            _PIL_raw.open(io.BytesIO(img_bytes)),
            config="--oem 3 --psm 6",
            lang="eng",
        )
        if text.strip():
            pages.append(f"[Page {i+1}]\n{text}")

    n = len(doc)
    doc.close()
    return "\n\n".join(pages), n


def _extract_pdf(file_bytes: bytes, enhance: bool = True):
    errors = []

    for strategy_name, strategy_fn in [
        ("pdfplumber",    lambda: _strategy1_pdfplumber(file_bytes)),
        ("PyMuPDF text",  lambda: _strategy2_pymupdf_text(file_bytes)),
        ("PyMuPDF blocks",lambda: _strategy3_pymupdf_blocks(file_bytes)),
    ]:
        try:
            text, pages = strategy_fn()
            if len(text.strip()) > 50:
                logger.info(f"PDF extracted via {strategy_name}: {len(text)} chars, {pages} pages")
                return text, pages
            else:
                logger.debug(f"{strategy_name} returned <50 chars, trying next")
        except Exception as e:
            errors.append(f"{strategy_name}: {e}")
            logger.warning(f"{strategy_name} failed: {e}")

    # Strategy 4: OCR — raises RuntimeError with clear Tesseract message
    try:
        text, pages = _strategy4_render_ocr(file_bytes, enhance=enhance)
        if len(text.strip()) > 10:
            logger.info(f"PDF extracted via render+OCR: {len(text)} chars, {pages} pages")
            return text, pages
    except (RuntimeError, ImportError):
        raise  # Surface Tesseract error directly
    except Exception as e:
        errors.append(f"OCR: {e}")
        logger.warning(f"PDF OCR failed: {e}")

    raise RuntimeError(
        "All PDF extraction methods failed. "
        "Install: pip install pdfplumber pymupdf pytesseract | "
        + " | ".join(errors)
    )


# ════════════════════════════════════════════════════════════════════
# IMAGE EXTRACTION
# ════════════════════════════════════════════════════════════════════

def _extract_image(file_bytes: bytes, enhance: bool = True):
    # Re-run configure so a freshly installed Tesseract is picked up immediately.
    _configure_tesseract()

    pytesseract = _try_import("pytesseract")
    PIL_mod = _try_import("PIL.Image")

    if not pytesseract:
        raise ImportError("pytesseract not installed. Run: pip install pytesseract")
    if not PIL_mod:
        raise ImportError("Pillow not installed. Run: pip install Pillow")

    try:
        pytesseract.get_tesseract_version()
    except Exception:
        raise RuntimeError(
            "Tesseract binary not found.\n"
            "  Windows: https://github.com/UB-Mannheim/tesseract/wiki\n"
            "  Ubuntu:  sudo apt-get install tesseract-ocr"
        )

    from PIL import Image as _PIL, ImageFilter, ImageEnhance
    img = _PIL.open(io.BytesIO(file_bytes)).convert("RGB")

    if enhance:
        img = img.convert("L")
        w, h = img.size
        if w < 1000 or h < 1000:
            scale = max(1000 / w, 1000 / h, 1.0)
            img = img.resize((int(w * scale), int(h * scale)), _PIL.LANCZOS)
        img = img.filter(ImageFilter.SHARPEN)
        img = ImageEnhance.Contrast(img).enhance(1.8)
        img = ImageEnhance.Brightness(img).enhance(1.1)

    text = pytesseract.image_to_string(img, config="--oem 3 --psm 6", lang="eng")
    return text, 1


# ════════════════════════════════════════════════════════════════════
# PUBLIC API
# ════════════════════════════════════════════════════════════════════

TESSERACT_INSTALL_GUIDE = """
⚠️  Tesseract binary not found on your system.

pip install pytesseract  ← Python wrapper ONLY, does NOT install the OCR engine

INSTALL TESSERACT BINARY:

📥 Windows (most common fix):
   1. Download installer: https://github.com/UB-Mannheim/tesseract/wiki
      → Download: tesseract-ocr-w64-setup-5.x.x.exe
   2. During install: CHECK "Add to PATH" (important!)
   3. Default install path: C:\\Program Files\\Tesseract-OCR\\
   4. After install: CLOSE and REOPEN your terminal/PowerShell
   5. Verify: tesseract --version  (should show version number)
   6. If still not found: set env variable TESSERACT_CMD=C:\\Program Files\\Tesseract-OCR\\tesseract.exe

📥 Ubuntu / WSL:
   sudo apt-get update && sudo apt-get install -y tesseract-ocr
   sudo apt-get install -y tesseract-ocr-eng  (English language pack)

📥 macOS:
   brew install tesseract

After install: restart terminal → streamlit run app.py
"""


def scan_document(file_bytes: bytes, filename: str, enhance: bool = True,
                   force_ocr: bool = False) -> dict:
    """
    Scan and extract text from an uploaded document.

    Args:
      force_ocr: Skip text-layer extraction entirely and render pages as images
                 before OCR. Use for image-based PDFs where pdfplumber/PyMuPDF
                 return blank or garbled text.

    Returns dict:
      status       : "success" | "error"
      text         : extracted cleaned text
      char_count   : int
      pages        : int
      format       : "pdf" | "image"
      method       : extraction method used
      message      : error description if status == "error"
      install_hint : install instructions if dependency missing
    """
    if not file_bytes:
        return {"status": "error", "message": "No file data received.",
                "text": "", "char_count": 0, "pages": 0}

    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in SUPPORTED_FORMATS:
        return {"status": "error",
                "message": f"Unsupported format '.{ext}'. Supported: {', '.join(SUPPORTED_FORMATS)}",
                "text": "", "char_count": 0, "pages": 0}

    try:
        if ext == "pdf":
            if force_ocr:
                # Skip text extraction — go straight to render+OCR for image PDFs
                raw_text, num_pages = _strategy4_render_ocr(file_bytes, enhance=enhance)
                fmt, method = "pdf", "forced-ocr"
            else:
                raw_text, num_pages = _extract_pdf(file_bytes, enhance=enhance)
                fmt, method = "pdf", "pdf-extraction"
        else:
            raw_text, num_pages = _extract_image(file_bytes, enhance=enhance)
            fmt, method = "image", "ocr"

        clean_text = _clean_extracted_text(raw_text)

        if not clean_text.strip():
            return {"status": "error",
                    "message": "No text extracted. Document may be blank, encrypted, or too low quality.",
                    "text": "", "char_count": 0, "pages": num_pages,
                    "format": fmt, "method": method}

        return {"status": "success", "text": clean_text,
                "char_count": len(clean_text), "pages": num_pages,
                "format": fmt, "method": method, "message": ""}

    except RuntimeError as e:
        err = str(e)
        logger.error(f"Scan error '{filename}': {err}")
        is_tesseract = "Tesseract" in err or "tesseract" in err
        if is_tesseract:
            # Try one more time to auto-configure path
            if _configure_tesseract():
                try:
                    if ext == "pdf":
                        raw_text, num_pages = _strategy4_render_ocr(file_bytes, enhance=enhance)
                    else:
                        raw_text, num_pages = _extract_image(file_bytes, enhance=enhance)
                    clean_text = _clean_extracted_text(raw_text)
                    if clean_text.strip():
                        return {"status": "success", "text": clean_text,
                                "char_count": len(clean_text), "pages": num_pages,
                                "format": ext, "method": "ocr-retry", "message": ""}
                except Exception:
                    pass
        return {"status": "error", "message": err,
                "install_hint": TESSERACT_INSTALL_GUIDE if is_tesseract else None,
                "text": "", "char_count": 0, "pages": 0}

    except ImportError as e:
        missing = str(e)
        hints = {"pytesseract": "pip install pytesseract",
                 "pdfplumber":  "pip install pdfplumber",
                 "fitz":        "pip install pymupdf",
                 "Pillow":      "pip install Pillow"}
        hint = next((v for k, v in hints.items() if k in missing), f"pip install ...")
        logger.error(f"Missing lib: {missing}")
        return {"status": "error", "message": f"Library missing: {missing}",
                "install_hint": hint, "text": "", "char_count": 0, "pages": 0}

    except Exception as e:
        logger.error(f"Scan error '{filename}': {e}", exc_info=True)
        return {"status": "error", "message": f"Scanning failed: {e}",
                "text": "", "char_count": 0, "pages": 0}


def get_scanner_status() -> dict:
    """Return which scanning libraries and binaries are available."""
    pytesseract = _try_import("pytesseract")
    tesseract_binary = False
    tesseract_version = "not found"
    if pytesseract:
        try:
            tesseract_version = str(pytesseract.get_tesseract_version())
            tesseract_binary = True
        except Exception:
            pass

    return {
        "pdfplumber":        _try_import("pdfplumber") is not None,
        "pymupdf":           _try_import("fitz") is not None,
        "pytesseract_pkg":   pytesseract is not None,
        "tesseract_binary":  tesseract_binary,
        "tesseract_version": tesseract_version,
        "pillow":            _try_import("PIL") is not None,
        "supported_formats": SUPPORTED_FORMATS,
        "note": (
            "Strategies 1-3 (pdfplumber, PyMuPDF text, PyMuPDF blocks) work WITHOUT Tesseract "
            "for PDFs with a native text layer. "
            "Tesseract binary is only needed for fully scanned/image PDFs and image files."
        ),
    }