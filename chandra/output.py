import logging
import re
from dataclasses import dataclass, asdict

from PIL import Image
from bs4 import BeautifulSoup
from markdownify import MarkdownConverter

from chandra import settings


class ChandraMarkdownConverter(MarkdownConverter):
    """Markdownify converter extended to handle non-standard tags emitted by the model."""

    def convert_math(self, el, text, parent_tags):
        # Model emits <math>...</math> with raw LaTeX inside. Map to inline $...$.
        # Caller wraps in $$...$$ for display equations.
        # Use get_text() so HTML entities (&gt;, &lt;, &amp;) are unescaped to
        # raw LaTeX characters (>, <, &).
        inner = el.get_text()
        inner = re.sub(r"\s+", " ", inner).strip()
        return f"${inner}$"

    def convert_code(self, el, text, parent_tags):
        # Some model outputs use <code> blocks outside <pre>; let parent handle <pre>.
        if el.parent and el.parent.name == "pre":
            return text
        return super().convert_code(el, text, parent_tags)


md_converter = ChandraMarkdownConverter(
    heading_style="ATX",
    bullets="-",
    code_language="",
    escape_asterisks=False,
    escape_underscores=False,
    escape_misc=False,
)


@dataclass
class LayoutBlock:
    bbox: list[int]
    label: str
    content: str


def parse_chunks(html: str, image: Image.Image, bbox_scale=settings.BBOX_SCALE):
    soup = BeautifulSoup(html, "html.parser")
    top_level_divs = soup.find_all("div", recursive=False)
    width, height = image.size
    width_scaler = width / bbox_scale
    height_scaler = height / bbox_scale
    layout_blocks = []
    for div in top_level_divs:
        label = div.get("data-label")
        if label == "Blank-Page":
            continue

        bbox = div.get("data-bbox")

        try:
            bbox = bbox.split(" ")
            bbox = list(map(int, bbox))
            assert len(bbox) == 4, "Invalid bbox length"
        except Exception:
            logging.warning(f"Invalid bbox format: {bbox}, defaulting to full image")
            bbox = [0, 0, 1, 1]

        # Normalize bbox
        bbox = [
            max(0, int(bbox[0] * width_scaler)),
            max(0, int(bbox[1] * height_scaler)),
            min(int(bbox[2] * width_scaler), width),
            min(int(bbox[3] * height_scaler), height),
        ]
        if not label:
            label = "block"
        content = str(div.decode_contents())

        # Strip nested data-bbox attributes (not needed in open source)
        content_soup = BeautifulSoup(content, "html.parser")
        for tag in content_soup.find_all(attrs={"data-bbox": True}):
            del tag["data-bbox"]
        content = str(content_soup)
        block = LayoutBlock(bbox=bbox, label=label, content=content)
        block = asdict(block)
        layout_blocks.append(block)

    return layout_blocks
