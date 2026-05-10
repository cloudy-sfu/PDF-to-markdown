import os

# HuggingFace model identifier (used by pdf_install.py to download).
MODEL_REPO = "datalab-to/chandra-ocr-2"

# Local directory the model is downloaded to and loaded from.
# pdf_predict.py points transformers at this directory so no network
# access is ever required at inference time.
MODEL_DIR = "./pdf_ocr_chandra"

# Image / inference settings
IMAGE_DPI = 192
MIN_PDF_IMAGE_DIM = 1024
MIN_IMAGE_DIM = 1536
MAX_OUTPUT_TOKENS = 12384
BBOX_SCALE = 1000

# Torch backend
TORCH_DEVICE = None
TORCH_ATTN = None

# MODEL_CHECKPOINT is what chandra/model/hf.py reads.
# Resolve it to MODEL_DIR if that directory exists, otherwise fall back
# to the repo id (only useful while installing).
if os.path.isdir(MODEL_DIR):
    MODEL_CHECKPOINT = MODEL_DIR
else:
    MODEL_CHECKPOINT = MODEL_REPO
