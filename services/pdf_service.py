import pymupdf


class PdfValidationError(ValueError):
    """Raised when an uploaded PDF cannot be read or parsed safely."""


def extract_pdf_pages(pdf_bytes):
    """Extract per-page text from PDF bytes.

    Returns a list of {"page_number": int, "text": str} in document order so
    page numbers used for RAG evidence always match the real PDF pages.
    Pages without extractable text are kept with empty text (callers decide
    whether that is fatal), so numbering is never shifted.

    Raises PdfValidationError with a user-friendly message if the bytes are
    not a readable PDF.
    """
    if not pdf_bytes:
        raise PdfValidationError("The uploaded file is empty.")

    try:
        document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as error:
        raise PdfValidationError(f"Could not read the PDF file: {error}")

    pages = []

    try:
        with document:
            if document.page_count == 0:
                raise PdfValidationError("The PDF does not contain any pages.")

            for page_number, page in enumerate(document, start=1):
                pages.append(
                    {
                        "page_number": page_number,
                        "text": page.get_text("text", sort=True).strip(),
                    }
                )
    except PdfValidationError:
        raise
    except Exception as error:
        raise PdfValidationError(f"Could not read the PDF file: {error}")

    return pages