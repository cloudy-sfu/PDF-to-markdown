import logging
from typing import List

import filetype
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from PIL import Image

from chandra import settings


def load_file(filepath: str, config: dict) -> List[Image.Image]:
    page_range = config.get("page_range")

    # 1. Parse range string
    if page_range and isinstance(page_range, str):
        range_lst = page_range.split(",")
        page_lst = []
        for i in range_lst:
            if "-" in i:
                start, end = i.split("-")
                page_lst += list(range(int(start), int(end) + 1))
            else:
                page_lst.append(int(i))
        page_range = sorted(
            list(set(page_lst)))  # Deduplicate page numbers and sort in order

    input_type = filetype.guess(filepath)
    if input_type and input_type.extension == "pdf":
        # 2. Load PDF images
        doc = pdfium.PdfDocument(filepath)
        doc.init_forms()

        images = []
        for page in range(len(doc)):
            if not page_range or page in page_range:
                page_obj = doc[page]
                min_page_dim = min(page_obj.get_width(), page_obj.get_height())
                scale_dpi = (settings.MIN_PDF_IMAGE_DIM / min_page_dim) * 72
                scale_dpi = max(scale_dpi, settings.IMAGE_DPI)

                # 3. Flatten annotations / form fields on page
                rc = pdfium_c.FPDFPage_Flatten(page_obj, pdfium_c.FLAT_NORMALDISPLAY)
                if rc == pdfium_c.FLATTEN_FAIL:
                    logging.warning(
                        f"Failed to flatten annotations / form fields on page {page}.")

                page_obj = doc[page]
                pil_image = page_obj.render(scale=scale_dpi / 72).to_pil().convert("RGB")
                images.append(pil_image)

        doc.close()
    else:
        # 4. Load single image
        image = Image.open(filepath).convert("RGB")
        if image.width < settings.MIN_IMAGE_DIM or image.height < settings.MIN_IMAGE_DIM:
            scale = settings.MIN_IMAGE_DIM / min(image.width, image.height)
            new_size = (int(image.width * scale), int(image.height * scale))
            image = image.resize(new_size, Image.Resampling.LANCZOS)
        images = [image]

    return images