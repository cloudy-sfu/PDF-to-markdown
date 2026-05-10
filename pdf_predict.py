import logging
import os
import sys
import uuid
from datetime import datetime, UTC

from chandra.input import load_file
from chandra.model.hf import load_model, generate_hf
from chandra.model.schema import BatchInputItem
from chandra.output import parse_chunks, md_converter

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
    stream=sys.stdout,
)
model = load_model()
logging.info("Model loaded.")


def predict(input_path, output_dir, page_range=None, layout=True):
    logging.info(f"Task: {input_path} -> {output_dir}")
    """
    Predict the content of a PDF or image file.
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"File not found: {input_path}")
    if os.path.exists(output_dir) and os.path.isfile(output_dir):
        raise FileExistsError("Output directory name is occupied by a file.")
    os.makedirs(output_dir, exist_ok=True)
    output_assets_abs_dir = os.path.join(output_dir, "assets")
    output_assets_rel_dir = "./assets"
    os.makedirs(output_assets_abs_dir, exist_ok=True)

    # Preprocess: Load images from PDF using input.py
    images = load_file(input_path, config={"page_range": page_range})
    # Create batches items
    if layout:
        prompt_type = "ocr_layout"
    else:
        prompt_type = "ocr"
    pages = [BatchInputItem(image=img, prompt_type=prompt_type) for img in images]
    n_pages = len(pages)

    # Generate/Predict in smaller chunks (Method 2: Reduce Batch Size)
    with open(os.path.join(output_dir, "main.md"), "w"):
        pass
    for i, page in enumerate(pages):
        logging.info(f"  Page: {i + 1}/{n_pages}")
        start_time = datetime.now(tz=UTC)
        output_markdown = []
        model_output = generate_hf([page], model)
        html = model_output[0].raw
        logging.info(f"    Output tokens: {model_output[0].token_count}")
        img = images[i]
        chunks = parse_chunks(html, img)

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
                    img.crop(bbox).save(fp_abs)
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
        with open(os.path.join(output_dir, "main.md"), "a") as f:
            f.write(output_markdown)
        end_time = datetime.now(tz=UTC)
        logging.info(f"    Elapsed time: {end_time - start_time}")
        logging.info("  Page completed.")
    logging.info("Task completed.")
