import logging
import os
import re
import sys
import uuid
from datetime import datetime, UTC

from PIL import Image
from pypdfium2 import PdfDocument
from pypdfium2.raw import FPDFPage_Flatten, FLAT_NORMALDISPLAY, FLATTEN_FAIL

from chandra import settings
from chandra.model.hf import load_model, generate_hf
from chandra.model.schema import BatchInputItem
from chandra.output import parse_chunks, md_converter

model = load_model()
logging.info("Model loaded.")
_SEGMENT = r'[1-9]\d*(?:-(?:[1-9]\d*)?)?'
_LINE_RANGE_RE = re.compile(rf'^{_SEGMENT}(?:,{_SEGMENT})*$')
_PARSE_RE = re.compile(r'^([1-9]\d*)(?:-([1-9]\d*)?)?$')


def parse_page_range(page_ranges, n):
    r"""
    Parse range of pages.
    :param page_ranges: Page ranges, must fit the following regex.
    '^[1-9]\d*(?:-(?:[1-9]\d*)?)?(?:,[1-9]\d*(?:-(?:[1-9]\d*)?)?)*$'
    :param n: Total number of pages
    :return:
    """
    match = _LINE_RANGE_RE.match(page_ranges)
    if not match:
        raise Exception(f"Page ranges \"{page_ranges}\" is not valid.")
    lines_no = set()
    for seg in page_ranges.split(','):
        match = _PARSE_RE.match(seg)  # guaranteed to match since validation passed
        start = int(match.group(1))
        if "-" in seg:
            end_str = match.group(2)
            if end_str:
                end = int(end_str)
            else:
                end = n
            lines_no.update(range(start, end + 1))
        else:
            lines_no.add(start)
    lines_idx = sorted([i - 1 for i in lines_no])
    return lines_idx


def predict_pdf(input_path, output_dir, page_range=None, layout=True):
    logging.info(f"Task: {input_path} -> {output_dir}")
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"File not found: {input_path}")
    if os.path.exists(output_dir) and os.path.isfile(output_dir):
        raise FileExistsError("Output directory name is occupied by a file.")
    input_base_name = os.path.splitext(os.path.basename(input_path))[0]
    os.makedirs(output_dir, exist_ok=True)
    output_assets_abs_dir = os.path.join(output_dir, "assets")
    output_assets_rel_dir = "./assets"
    os.makedirs(output_assets_abs_dir, exist_ok=True)

    # Preprocess: Load images from PDF using input.py
    doc = PdfDocument(input_path)
    doc.init_forms()
    n = len(doc)
    pages_idx = parse_page_range(page_range, n)
    images = []
    for i in pages_idx:
        page = doc[i]
        min_page_dim = min(page.get_width(), page.get_height())
        scale_dpi = (settings.MIN_PDF_IMAGE_DIM / min_page_dim) * 72
        scale_dpi = max(scale_dpi, settings.IMAGE_DPI)
        # Flatten annotations / form fields on page
        rc = FPDFPage_Flatten(page, FLAT_NORMALDISPLAY)
        if rc == FLATTEN_FAIL:
            logging.warning(f"Failed to flatten annotations or form fields on page.")
        pil_image = page.render(scale=scale_dpi / 72).to_pil().convert("RGB")
        images.append(pil_image)
    doc.close()
    n_pages = len(images)

    # Delete all existed content in the output file.
    with open(os.path.join(output_dir, f"{input_base_name}.md"), "w"):
        pass
    # Generate/Predict in smaller chunks (Method 2: Reduce Batch Size)
    for i, image in enumerate(images):
        logging.info(f"  Page: {i + 1}/{n_pages}")
        start_time = datetime.now(tz=UTC)
        model_output = generate_hf(
            BatchInputItem(image=image, layout=layout), model)
        html = model_output[0].raw
        logging.info(f"    Output tokens: {model_output[0].token_count}")
        chunks = parse_chunks(html, image)
        output_markdown = []
        for chunk in chunks:
            label = chunk["label"]
            content = chunk["content"].strip()
            bbox = chunk["bbox"]
            match label:
                case "Blank-Page" | "Page-Header" | "Page-Footer":
                    # Skip non-content blocks
                    continue
                case "Image" | "Figure" | "Diagram" | "Chemical-Block":
                    # Image-like blocks: crop from img and link
                    fn = f"{label.lower()}_{uuid.uuid4().hex[:8]}.png"
                    fp_abs = os.path.join(output_assets_abs_dir, fn)
                    image.crop(bbox).save(fp_abs)
                    output_markdown.append(f"![{label}]({output_assets_rel_dir}/{fn})\n")
                case "Section-Header":
                    text = md_converter.convert(content).lstrip("#").strip()
                    output_markdown.append(f"## {text}\n")
                case "Caption":
                    output_markdown.append(f"*{md_converter.convert(content).strip()}*\n")
                case "Footnote":
                    text = md_converter.convert(content).replace("\n", " ").strip()
                    output_markdown.append(f"> {text}\n")
                case "Equation-Block":
                    # Display math: convert inline $...$ from <math> to $$...$$
                    eq = md_converter.convert(content).strip()
                    if eq.startswith("$") and eq.endswith("$") and not eq.startswith("$$"):
                        eq = f"${eq}$"
                    output_markdown.append(f"{eq}\n")
                case "Code-Block" | "Text" | "Table" | "List-Group" | "Form" | \
                     "Table-Of-Contents" | "Bibliography" | "Complex-Block":
                    output_markdown.append(f"{md_converter.convert(content).strip()}\n")
                case _:
                    output_markdown.append(f"{md_converter.convert(content).strip()}\n")
        output_markdown = "\n".join(output_markdown) + "\n"
        with open(os.path.join(output_dir, f"{input_base_name}.md"), "a") as f:
            f.write(output_markdown)
        end_time = datetime.now(tz=UTC)
        logging.info(f"    Elapsed time: {end_time - start_time}")
        logging.info("  Page completed.")
    logging.info("Task completed.")


def predict_image(input_path, output_dir, layout=True):
    start_time = datetime.now(tz=UTC)
    logging.info(f"Task: {input_path} -> {output_dir}")
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"File not found: {input_path}")
    if os.path.exists(output_dir) and os.path.isfile(output_dir):
        raise FileExistsError("Output directory name is occupied by a file.")
    input_base_name = os.path.splitext(os.path.basename(input_path))[0]
    os.makedirs(output_dir, exist_ok=True)
    output_assets_abs_dir = os.path.join(output_dir, "assets")
    output_assets_rel_dir = "./assets"
    os.makedirs(output_assets_abs_dir, exist_ok=True)

    image = Image.open(input_path).convert("RGB")
    if image.width < settings.MIN_IMAGE_DIM or image.height < settings.MIN_IMAGE_DIM:
        scale = settings.MIN_IMAGE_DIM / min(image.width, image.height)
        new_size = (int(image.width * scale), int(image.height * scale))
        image = image.resize(new_size, Image.Resampling.LANCZOS)

    model_output = generate_hf(
        BatchInputItem(image=image, layout=layout), model)
    html = model_output[0].raw
    logging.info(f"  Output tokens: {model_output[0].token_count}")
    chunks = parse_chunks(html, image)
    output_markdown = []
    for chunk in chunks:
        label = chunk["label"]
        content = chunk["content"].strip()
        bbox = chunk["bbox"]
        match label:
            case "Blank-Page" | "Page-Header" | "Page-Footer":
                # Skip non-content blocks
                continue
            case "Image" | "Figure" | "Diagram" | "Chemical-Block":
                # Image-like blocks: crop from img and link
                fn = f"{label.lower()}_{uuid.uuid4().hex[:8]}.png"
                fp_abs = os.path.join(output_assets_abs_dir, fn)
                image.crop(bbox).save(fp_abs)
                output_markdown.append(f"![{label}]({output_assets_rel_dir}/{fn})\n")
            case "Section-Header":
                text = md_converter.convert(content).lstrip("#").strip()
                output_markdown.append(f"## {text}\n")
            case "Caption":
                output_markdown.append(f"*{md_converter.convert(content).strip()}*\n")
            case "Footnote":
                text = md_converter.convert(content).replace("\n", " ").strip()
                output_markdown.append(f"> {text}\n")
            case "Equation-Block":
                # Display math: convert inline $...$ from <math> to $$...$$
                eq = md_converter.convert(content).strip()
                if eq.startswith("$") and eq.endswith("$") and not eq.startswith("$$"):
                    eq = f"${eq}$"
                output_markdown.append(f"{eq}\n")
            case "Code-Block" | "Text" | "Table" | "List-Group" | "Form" | \
                 "Table-Of-Contents" | "Bibliography" | "Complex-Block":
                output_markdown.append(f"{md_converter.convert(content).strip()}\n")
            case _:
                output_markdown.append(f"{md_converter.convert(content).strip()}\n")
    output_markdown = "\n".join(output_markdown) + "\n"
    with open(os.path.join(output_dir, f"{input_base_name}.md"), "w") as f:
        f.write(output_markdown)
    end_time = datetime.now(tz=UTC)
    logging.info(f"  Elapsed time: {end_time - start_time}")
    logging.info("Task completed.")
