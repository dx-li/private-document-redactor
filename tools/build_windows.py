"""Build and smoke-test the Windows portable bundle in a clean environment."""
import hashlib
import importlib.metadata
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]

def build():
    subprocess.run([sys.executable,'setup_local.py'],cwd=ROOT,check=True)
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','tools/windows.spec'],cwd=ROOT,check=True)
    bundle=ROOT/'dist/PrivateDocumentRedactor'
    for file in ['README.md','LICENSE','THIRD_PARTY.md']:
        shutil.copy2(ROOT/file,bundle/file)
    (bundle/'Setup Local AI.cmd').write_text('@echo off\ncd /d "%~dp0"\n"RedactorWorker.exe" --setup-ai\nif errorlevel 1 echo Optional local AI setup failed. Manual redaction and OCR still work.\npause\n')
    (bundle/'START HERE.txt').write_text('Extract the entire ZIP folder, then double-click PrivateDocumentRedactor.exe.\nKeep RedactorWorker.exe and _internal beside it. No Python installation is needed.\nManual redaction and English OCR are included and work offline.\nOptional AI: run Setup Local AI.cmd once; this downloads about 4 GB.\nThis is an unsigned Windows x64 portable build. See README.md for usage.\n')
    notices=bundle/'licenses'
    notices.mkdir(exist_ok=True)
    for package in ['PyMuPDF','Pillow','PyInstaller']:
        distribution=importlib.metadata.distribution(package)
        for file in distribution.files or []:
            if any(term in str(file).lower() for term in ('license','copying','copyright')):
                source=Path(distribution.locate_file(file))
                if source.is_file():
                    target=notices/package/str(file)
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(source,target)
    python_license=Path(sys.base_prefix)/'LICENSE.txt'
    if python_license.exists():shutil.copy2(python_license,notices/'PYTHON-LICENSE.txt')
    # Preserve OCR data licensing without shipping a second copy of its weights.
    with __import__('urllib.request',fromlist=['urlopen']).urlopen('https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/87416418657359cb625c412a48b6e1d6d41c29bd/LICENSE') as response:
        (notices/'TESSDATA-LICENSE.txt').write_bytes(response.read())
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    from urllib.parse import urlsplit
    remote=subprocess.check_output(['git','remote','get-url','origin'],cwd=ROOT,text=True).strip()
    parsed=urlsplit(remote)
    assert parsed.hostname=='github.com'
    source_url='https://github.com'+parsed.path.removesuffix('.git')+'/tree/'+revision
    (bundle/'SOURCE.txt').write_text('AGPL-3.0-only. Corresponding source and build recipe:\n'+source_url+'\nThe release also includes a matching source archive.\n')
    subprocess.run([str(bundle/'RedactorWorker.exe'),'--self-test'],check=True,timeout=180)
    subprocess.run([str(bundle/'PrivateDocumentRedactor.exe'),'--smoke-gui'],check=True,timeout=30)
    archive=ROOT/'dist/PrivateDocumentRedactor-Windows-x64.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for file in sorted(bundle.rglob('*')):
            if file.is_file():z.write(file,file.relative_to(bundle.parent))
    source=ROOT/'dist/PrivateDocumentRedactor-source.zip'
    subprocess.run(['git','archive','--format=zip','--prefix=private-document-redactor/','--output='+str(source),'HEAD'],cwd=ROOT,check=True)
    checksum=ROOT/'dist/SHA256SUMS.txt'
    checksum.write_text(''.join(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+path.name+'\n' for path in (archive,source)))
    print('Built:',archive.name,'bytes:',archive.stat().st_size,flush=True)

if __name__=='__main__':
    build()
