import pymupdf


def extract_pdf_pages(pdf_bytes):
    pages = []

    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        for page_number, page in enumerate(document, start=1):
            pages.append(
                {
                    "page_number": page_number,
                    "text": page.get_text("text", sort=True).strip(),
                }
            )

    return pages
