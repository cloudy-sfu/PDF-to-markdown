from typing import List

import torch
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor

from chandra import settings
from chandra.model.schema import BatchInputItem, GenerationResult
from chandra.prompts import OCR_PROMPT, OCR_LAYOUT_PROMPT


def generate_hf(
    batch: BatchInputItem,
    model,
    max_output_tokens=None,
) -> List[GenerationResult]:
    if max_output_tokens is None:
        max_output_tokens = settings.MAX_OUTPUT_TOKENS

    conversations = [[process_batch_element(batch)]]

    inputs = model.processor.apply_chat_template(
        conversations,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
        processor_kwargs={"padding": True},
    )
    inputs = inputs.to(model.device)

    # Include both <|endoftext|> and <|im_end|> as stop tokens.
    # generation_config only has <|endoftext|>, but the model emits <|im_end|> at turn boundaries.
    eos_token_id = model.generation_config.eos_token_id
    im_end_id = model.processor.tokenizer.convert_tokens_to_ids("<|im_end|>")
    if isinstance(eos_token_id, int):
        eos_token_id = [eos_token_id]
    if im_end_id is not None and im_end_id not in eos_token_id:
        eos_token_id.append(im_end_id)

    generated_ids = model.generate(
        **inputs, 
        max_new_tokens=max_output_tokens, 
        eos_token_id=eos_token_id,
        pad_token_id=model.processor.tokenizer.pad_token_id
    )
    generated_ids_trimmed = [
        out_ids[len(in_ids) :]
        for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
    ]
    output_text = model.processor.batch_decode(
        generated_ids_trimmed,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )
    results = [
        GenerationResult(raw=out, token_count=len(ids), error=False)
        for out, ids in zip(output_text, generated_ids_trimmed)
    ]
    return results


def scale_to_fit(img, max_size=(3072, 2048), min_size=(1792, 28), grid_size=28):
    resample_method = Image.Resampling.LANCZOS
    width, height = img.size

    # Check for empty or invalid image
    if width <= 0 or height <= 0:
        return img

    original_ar = width / height
    current_pixels = width * height
    max_pixels = max_size[0] * max_size[1]
    min_pixels = min_size[0] * min_size[1]

    # 1. Determine ideal float scale based on pixel bounds
    scale = 1.0
    if current_pixels > max_pixels:
        scale = (max_pixels / current_pixels) ** 0.5
    elif current_pixels < min_pixels:
        scale = (min_pixels / current_pixels) ** 0.5

    # 2. Convert dimensions to integer "grid blocks"
    w_blocks = max(1, round((width * scale) / grid_size))
    h_blocks = max(1, round((height * scale) / grid_size))

    # 3. Refinement Loop: Ensure we are under the max limit
    while (w_blocks * h_blocks * grid_size * grid_size) > max_pixels:
        if w_blocks == 1 and h_blocks == 1:
            break

        if w_blocks == 1:
            h_blocks -= 1
            continue
        if h_blocks == 1:
            w_blocks -= 1
            continue

        # Compare distortion: Which move preserves Aspect Ratio better?
        ar_w_loss = abs(((w_blocks - 1) / h_blocks) - original_ar)
        ar_h_loss = abs((w_blocks / (h_blocks - 1)) - original_ar)

        if ar_w_loss < ar_h_loss:
            w_blocks -= 1
        else:
            h_blocks -= 1

    # 4. Calculate final pixel dimensions
    new_width = w_blocks * grid_size
    new_height = h_blocks * grid_size

    # Return original if no changes were needed
    if (new_width, new_height) == (width, height):
        return img

    return img.resize((new_width, new_height), resample=resample_method)


def process_batch_element(item: BatchInputItem):
    prompt = item.prompt or (OCR_LAYOUT_PROMPT if item.layout else OCR_PROMPT)
    content = []
    image = scale_to_fit(item.image)  # Guarantee max size
    content.append({"type": "image", "image": image})
    content.append({"type": "text", "text": prompt})
    return {"role": "user", "content": content}


def load_model():
    device_map = "auto"
    if settings.TORCH_DEVICE:
        device_map = {"": settings.TORCH_DEVICE}

    kwargs = {
        "dtype": torch.bfloat16,
        "device_map": device_map,
    }
    if settings.TORCH_ATTN:
        kwargs["attn_implementation"] = settings.TORCH_ATTN

    model = AutoModelForImageTextToText.from_pretrained(
        settings.MODEL_CHECKPOINT, **kwargs
    )
    model = model.eval()
    processor = AutoProcessor.from_pretrained(settings.MODEL_CHECKPOINT)
    processor.tokenizer.padding_side = "left"
    model.processor = processor
    return model