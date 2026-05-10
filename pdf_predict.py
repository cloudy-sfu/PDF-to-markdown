import logging
import os
import re
import sys
import uuid
from html import unescape

from chandra.input import load_file
from chandra.model.hf import load_model, generate_hf
from chandra.model.schema import BatchInputItem
from chandra.output import parse_chunks

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
    stream=sys.stdout,
)
model = load_model()
logging.info("Model loaded.")


def predict(input_path, output_dir, page_range=None, layout=True):
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
    output_markdown = []
    for i, batch in enumerate(pages):
        model_output = generate_hf([batch], model)
        html = model_output[0].raw
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
                    text = re.sub(r"<math[^>]*>(.*?)</math>", r"$\1$", content, flags=re.DOTALL)
                    text = re.sub(r"<(?!/?math\b)[^>]+>", "", text).strip()
                    output_markdown.append(f"## {text}\n")
                case "Caption":
                    text = re.sub(r"<math[^>]*>(.*?)</math>", r"$\1$", content, flags=re.DOTALL)
                    text = re.sub(r"</?p[^>]*>", "", text).strip()
                    output_markdown.append(f"*{text}*\n")
                case "Footnote":
                    text = re.sub(r"<math[^>]*>(.*?)</math>", r"$\1$", content, flags=re.DOTALL)
                    text = re.sub(r"</?p[^>]*>", "", text).strip()
                    output_markdown.append(f"> {text}\n")
                case "Code-Block":
                    m = re.search(r"<code[^>]*>(.*?)</code>", content, re.DOTALL)
                    code = unescape(m.group(1)) if m else re.sub(r"<[^>]+>", "", content)
                    output_markdown.append(f"```\n{code}\n```\n")
                case "Equation-Block":
                    # Convert <math>...</math> to $$...$$ display math
                    eq = re.sub(r"<math[^>]*>(.*?)</math>", r"$\1$", content, flags=re.DOTALL)
                    eq = re.sub(r"</?p[^>]*>", "", eq).strip()
                    output_markdown.append(f"{eq}\n")
                case "Text":
                    # Strip <p> wrapper for cleaner markdown
                    text = re.sub(r"^\s*<p[^>]*>|</p>\s*$", "", content, flags=re.DOTALL).strip()
                    # Convert simple inline tags
                    text = re.sub(r"<b>(.*?)</b>", r"**\1**", text, flags=re.DOTALL)
                    text = re.sub(r"<i>(.*?)</i>", r"*\1*", text, flags=re.DOTALL)
                    text = re.sub(r"<math[^>]*>(.*?)</math>", r"$\1$", text, flags=re.DOTALL)
                    output_markdown.append(f"{text}\n")
                case "Table" | "List-Group" | "Form" | "Table-Of-Contents" | "Bibliography" | "Complex-Block":
                    # Markdown supports raw HTML, so pass through.
                    # Convert inline <math>...</math> to $...$ for inline LaTeX.
                    html_ = re.sub(r"<math[^>]*>(.*?)</math>", r"$\1$", content, flags=re.DOTALL)
                    output_markdown.append(f"{html_}\n")
                case _:
                    # Unknown label: pass through raw content as fallback
                    output_markdown.append(f"{content}\n")
        logging.info(f"Completed recognizing page {i+1}/{n_pages}.")
    output_markdown = "\n".join(output_markdown)
    with open(os.path.join(output_dir, "main.md"), "w") as f:
        f.write(output_markdown)
