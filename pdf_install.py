import logging
import os
import sys

from chandra import settings

# Enable hf_transfer for maximized download speed and a detailed speed progress bar.
# Ref: https://huggingface.co/docs/huggingface_hub/main/en/guides/download#faster-downloads
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
from huggingface_hub import snapshot_download

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logging.info(f"Downloading model {settings.MODEL_REPO} to {settings.MODEL_DIR}...")
os.makedirs(settings.MODEL_DIR, exist_ok=True)

# Filter for minimum required execution files.
# This automatically excludes README.md, .gitattributes, and redundant .bin/.h5 weights.
allow_patterns = [
    "*.json",
    "*.safetensors",
    "*.model",
    "*.txt",
    "*.py",
    "chat_template.jinja",
]

snapshot_download(
    repo_id=settings.MODEL_REPO,
    local_dir=settings.MODEL_DIR,
    allow_patterns=allow_patterns,
)
logging.info("Installation complete. Model is ready for prediction.")
