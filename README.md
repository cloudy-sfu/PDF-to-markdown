# PDF to markdown

 Convert PDF to markdown

![](https://shields.io/badge/OS-Windows_11-navy)
![](https://shields.io/badge/dependencies-Python_3.14-blue)
![](https://shields.io/badge/dependencies-huggingface.co-blue)
![](https://shields.io/badge/dependencies-NVIDIA_CUDA_≥_13.0-green)
![](https://shields.io/badge/device-Graphic_memory_≥_12_GB-darkgreen)
![](https://shields.io/badge/device-Disk_space_≥_15_GB-darkgreen)
![](https://shields.io/badge/device-Memory_≥_8_GB-darkgreen)

This is an offline version of Chandra OCR 2, suitable for Windows personal computer. It only downloads the model once from huggingface.co when installing (about 13GB), then it's fully offline without any need of credits or Internet connection.

The major customization for Windows is `trition` package. Linux is even more native for this program, which means this program is easily to migrate to Linux operation systems.



## Acknowledgement

https://github.com/datalab-to/chandra

https://huggingface.co/datalab-to/chandra-ocr-2

https://qwen.ai/blog?id=qwen3.5

## Install

Create and activate a Python virtual environment.

Run the following command in terminal.

```
pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cu130
python pdf_install.py
```

