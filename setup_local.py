"""Download optional public dependencies, never documents. Run during setup only."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import urllib.request
import zipfile
from runtime_paths import APP_DIR,RESOURCE_DIR

BASE=APP_DIR
OCR_URL='https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/87416418657359cb625c412a48b6e1d6d41c29bd/eng.traineddata'
OCR_SHA='7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2'

def download(url,destination,sha=None):
    destination=Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    with urllib.request.urlopen(url,timeout=90) as response, destination.open('wb') as stream:
        while chunk:=response.read(1024*1024):
            stream.write(chunk)
    with destination.open('rb') as stream:
        actual=hashlib.file_digest(stream,'sha256').hexdigest()
    if sha and actual!=sha:
        destination.unlink(missing_ok=True)
        raise RuntimeError('Download checksum mismatch. Please retry setup.')

def setup(ai=False):
    target=RESOURCE_DIR/'tessdata/eng.traineddata'
    if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest()!=OCR_SHA:
        print('Downloading English OCR data (about 4 MB)...',flush=True)
        download(OCR_URL,target,OCR_SHA)
    print('English OCR is ready.',flush=True)
    if not ai:
        return
    if os.name!='nt':
        raise RuntimeError('The bundled AI installer currently supports Windows only.')
    executable=BASE/'runtime/ollama.exe'
    if not executable.exists():
        print('Downloading the optional Ollama runtime (about 1.6 GB)...',flush=True)
        request=urllib.request.Request('https://api.github.com/repos/ollama/ollama/releases/tags/v0.40.8',headers={'User-Agent':'Private-Document-Redactor-Setup'})
        with urllib.request.urlopen(request,timeout=60) as response:
            release=json.load(response)
        asset=next(a for a in release['assets'] if a['name']=='ollama-windows-amd64.zip')
        digest=asset.get('digest','')
        if not digest.startswith('sha256:'):
            raise RuntimeError('The upstream runtime checksum is unavailable. Runtime was not installed.')
        with tempfile.TemporaryDirectory(prefix='redactor-setup-') as temporary:
            archive=Path(temporary)/'runtime.zip'
            download(asset['browser_download_url'],archive,digest.split(':',1)[1])
            destination=(BASE/'runtime').resolve()
            with zipfile.ZipFile(archive) as z:
                for member in z.infolist():
                    if any(s in member.filename for s in ('cuda_v12/','cuda_v13/','vulkan/')):
                        continue
                    resolved=(destination/member.filename).resolve()
                    if not resolved.is_relative_to(destination):
                        raise RuntimeError('Invalid runtime archive path.')
                    z.extract(member,destination)
    import local_ai
    local_ai.ensure_server()
    print('Downloading Qwen3-VL 2B Instruct (about 1.9 GB)...',flush=True)
    subprocess.run([str(executable),'pull',local_ai.MODEL],env=local_ai.environment(),check=True)
    print('Local-only AI is ready.',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ai',action='store_true',help='also install the optional local vision model')
    args=parser.parse_args()
    setup(args.ai)
