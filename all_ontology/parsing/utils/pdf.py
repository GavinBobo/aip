import threading

import sopdf
import numpy as np
import cv2


# PDFium requires process-wide exclusion, even for separate documents.
_PDFIUM_LOCK = threading.Lock()


def pdf_to_images(
    pdf_bytes: bytes,
    dpi: int = 150,
    page_range: tuple[int, int] | None = None,
) -> list[np.ndarray]:
    """Convert PDF bytes to OpenCV images, optionally a 1-based page range.

    ``page_range`` is inclusive and clipped by the document. It exists so a
    person can preview the first pages of a 300-page scan without paying for the
    whole document, and so a retry can target a smaller window.
    """
    with _PDFIUM_LOCK:
        images = []
        with sopdf.open(stream=pdf_bytes) as doc:
            for page_number, page in enumerate(doc.pages, start=1):
                if page_range is not None and not (
                    page_range[0] <= page_number <= page_range[1]
                ):
                    continue
                png_bytes = page.render(dpi=dpi)
                nparr = np.frombuffer(png_bytes, np.uint8)
                cv_image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                images.append(cv_image)
        return images
