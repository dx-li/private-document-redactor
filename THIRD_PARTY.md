# Third-party components

Dependencies are installed separately; model/runtime binaries and OCR weights are not committed to this repository.

| Component | Purpose | License/source |
| --- | --- | --- |
| PyMuPDF | PDF rendering, embedded Tesseract OCR, export | AGPL/commercial; https://pymupdf.io/ |
| Pillow | Image rendering and permanent pixel redaction | HPND; https://python-pillow.github.io/ |
| Tesseract / tessdata_fast English | Local text recognition | Apache-2.0; https://github.com/tesseract-ocr/tessdata_fast |
| Ollama (optional) | Local model runtime | MIT, with bundled third-party notices; https://github.com/ollama/ollama |
| Qwen3-VL 2B Instruct (optional) | Vision suggestions | Apache-2.0; https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct |

Review the upstream license files when redistributing dependencies. The Ollama download contains notices under its runtime library directory.
