# Private Document Redactor

A local desktop tool for redacting PDFs and scanned images. Draw boxes, use local OCR to locate sensitive fields, review every page, and export a fresh PDF containing only the redacted page images.

## Install on Windows

1. Install **Python 3.12** from [python.org](https://www.python.org/downloads/) with tkinter and the Python launcher.
2. Download or clone this repository and unzip it into a local folder.
3. Double-click **Setup.cmd**. This installs the Python libraries and downloads English OCR data.
4. Double-click **Start Redactor.cmd**.

Manual redaction and OCR work offline after setup. For optional vision suggestions, run **Setup Local AI.cmd** once. It downloads an Ollama CPU runtime and Qwen3-VL 2B Instruct; allow roughly 4 GB for those downloads plus installation space. AI is optional and runs on your computer. Windows is the tested desktop platform.

## Use

1. Open a PDF, PNG, or JPEG. Select **Paystub**, **Bank statement**, **Driver's license / passport**, or **Mixed / general**.
2. Drag over sensitive information. Right-click a box to remove it. Undo and redo work separately on each page.
3. Optionally run **OCR all pages**. Open **Review page OCR**, select suggestions to preview their outlines, and accept only those you have inspected. **Suggest sensitive areas** adds optional local vision analysis for the current page.
4. Use the clickable page list or Page Up / Page Down. The heading shows the current and total page counts; the review counter tracks completion. **Fit page** displays the full page, and **Next unreviewed page** takes you to the next page needing attention.
5. Tick **I reviewed this page** on every page, including pages needing no redaction. Edits clear that page's review. OCR, preset changes, or loading a template also require renewed review. Export is blocked until all pages are reviewed and pending suggestions have been accepted or discarded.
6. Save a new redacted PDF. Standard quality is 200 DPI; Fine is 300 DPI. Export runs in a separate local process with progress updates.

**Save template** stores coordinates, dimensions, and the preset so the boxes can be reused. It stores no document text or page images. Check alignment each time; layouts can shift. Templates do not carry over review approvals. Multiple documents/pages in one PDF are supported, including several stubs on one page. Page order and sizes are preserved.

Keyboard shortcuts: **Ctrl+O** open, **Ctrl+S** export, **Ctrl+Z** undo, **Ctrl+Y** redo, **Page Up / Page Down** navigate.

## Privacy and redaction

The tool renders each page, replaces marked pixels with solid black, and constructs a new image-only PDF. It does not copy the original text layer, OCR layer, attachments, forms, annotations, metadata, or digital signatures. It checks exports for unexpected text and embedded content before replacing the destination. Originals remain unchanged. Export uses a memory pipe; its temporary output contains only already-redacted pages.

OCR runs in an isolated local process. Optional AI uses a fixed loopback endpoint at `127.0.0.1:11439`, disables Ollama cloud features, bypasses proxies for document requests, and rejects redirects. There is no cloud fallback. Setup downloads software/model files; analysis does not upload documents. Source documents, model files, OCR data, templates, and logs are excluded from Git tracking.

Local processing does not control operating-system backups, cloud-synced folders, other software, or the original file. Choose a non-synced folder when appropriate. Check every exported page for incomplete coverage and repeated information elsewhere.

## Limits

OCR and small vision models can miss or misread details. Approximate locations are labeled. Scans with faint, skewed, tiny, or sideways text may need manual boxes. Only English OCR data is installed. Signatures, QR codes, barcodes, and passport machine-readable zones need visual inspection; OCR does not decode barcodes. Bank transaction descriptions, names, photos, addresses, and birth dates are not hidden by default. Add boxes manually where appropriate and retain fields required by the recipient.

The application does not provide automatic legal compliance or a guarantee that a document contains no other sensitive information. Exports have no selectable text, interactive fields, or valid source signatures. Large PDFs can require substantial memory. The local AI server remains running after use; its model unloads after two minutes idle.

## Tests

With dependencies installed, run `python -m unittest discover -s tests -v`. Tests generate synthetic data locally; no personal documents are included. OCR integration tests run when the English OCR data has been installed.

## License

AGPL-3.0-only; see [LICENSE](LICENSE). Third-party libraries and model data retain their own licenses; see [THIRD_PARTY.md](THIRD_PARTY.md).
