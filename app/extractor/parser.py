import pdfplumber
from docx import Document
import openpyxl
from io import BytesIO
import logging
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

def extract_pdf(file_bytes: bytes) -> str:
    text = ""
    with pdfplumber.open(BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            text += (page.extract_text() or "") + "\n"
    return text

def extract_docx(file_bytes: bytes) -> str:
    try:
        doc = Document(BytesIO(file_bytes))
        return "\n".join([paragraph.text for paragraph in doc.paragraphs])
    except Exception as e:
        logger.warning(f"Standard DOCX extraction failed, attempting fallback: {e}")
        # If it's a 'There is no item named...' error, it's often a corrupted archive
        # but we might still be able to extract some text if we try.
        # For now, we'll re-raise to catch it in the main block if fallback is not implemented.
        raise

def extract_xlsx(file_bytes: bytes) -> str:
    wb = openpyxl.load_workbook(BytesIO(file_bytes), data_only=True)
    text = ""
    for sheet in wb.worksheets:
        for row in sheet.iter_rows(values_only=True):
            text += " ".join([str(cell) for cell in row if cell is not None]) + "\n"
    return text

def extract_html(file_bytes: bytes) -> str:
    soup = BeautifulSoup(file_bytes, "html.parser")
    # Kill all script and style elements
    for script in soup(["script", "style"]):
        script.extract()
    return soup.get_text(separator="\n")

def extract_text(filename: str, file_bytes: bytes) -> str:
    ext = filename.lower().split(".")[-1]
    try:
        if ext == "pdf":
            return extract_pdf(file_bytes)
        if ext in ["docx", "doc"]:
            return extract_docx(file_bytes)
        if ext in ["xlsx", "xls"]:
            return extract_xlsx(file_bytes)
        if ext in ["html", "htm"]:
            return extract_html(file_bytes)
        if ext == "txt":
            return file_bytes.decode("utf-8", errors="ignore")
            
        # Fallback for unknown formats: try as text
        try:
            return file_bytes.decode("utf-8")
        except:
            raise ValueError(f"Unsupported format: {ext}")
            
    except Exception as e:
        logger.error(f"Error extracting text from {filename}: {e}")
        raise ValueError(f"Failed to extract text from {filename}: {e}")
