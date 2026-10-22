"""Local Tesseract OCR. Subprocess isolation keeps PyMuPDF thread-safe."""
from pathlib import Path
import sys
BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / 'lib'))
import io
import json
import re
import subprocess
import pymupdf as pdf
import profiles


def normalize(text):
    return re.sub(r'[^a-z0-9]', '', text.lower())


def recognize(png):
    # OCR a rendered page with no PDF rotation. Coordinates map directly to
    # the displayed image even for rotated PDF pages or mixed page sizes.
    with pdf.open(stream=png, filetype='png') as image:
        with pdf.open(stream=image.convert_to_pdf(), filetype='pdf') as doc:
            page = doc[0]
            tp = page.get_textpage_ocr(language='eng', dpi=200, full=True,
                                       tessdata=str(BASE / 'tessdata'))
            words = page.get_text('words', textpage=tp)
            return [{'text':w[4], 'box':[w[0]/page.rect.width,w[1]/page.rect.height,
                    w[2]/page.rect.width,w[3]/page.rect.height],
                    'line':[w[5],w[6]]} for w in words]


def run(png):
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker'],
        input=png, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0), timeout=180)
    if result.returncode:
        raise RuntimeError('Local OCR failed. Check that tessdata/eng.traineddata is present; try a clearer scan.')
    return json.loads(result.stdout)


def union(words, padding=.003):
    return [max(0,min(w['box'][0] for w in words)-padding),
            max(0,min(w['box'][1] for w in words)-padding),
            min(1,max(w['box'][2] for w in words)+padding),
            min(1,max(w['box'][3] for w in words)+padding)]


def match(words, text):
    target = normalize(text)
    if len(target) < 3:
        return []
    hits = []
    for start in range(len(words)):
        combined = ''
        for end in range(start, min(len(words), start+18)):
            if words[end]['line'] != words[start]['line']:
                break
            combined += normalize(words[end]['text'])
            if combined == target:
                hits.append(union(words[start:end+1]))
                break
            if len(combined) > len(target):
                break
    return hits


def suggestions(words, profile='Paystub'):
    groups = {}
    for word in words:
        groups.setdefault(tuple(word['line']), []).append(word)
    result = []
    patterns = profiles.patterns(profile)
    for line in groups.values():
        text = ' '.join(w['text'] for w in line)
        spans=[]
        for pattern, reason in patterns:
            hit=re.search(pattern,text,re.I)
            if hit:
                spans.append((hit.start(1),hit.end(1),reason))
        for hit in re.finditer(r'\b\d{3}[- ]\d{2}[- ]\d{4}\b',text):
            spans.append((hit.start(),hit.end(),'Social Security number'))
        if profile in ("Driver's license / passport", 'Mixed / general') and '<' in text and len(text.replace(' ', '')) >= 25:
            spans.append((0,len(text),'Machine-readable zone'))
        for start,end,reason in spans:
            selected=[]; offset=0
            for word in line:
                stop=offset+len(word['text'])
                if stop>start and offset<end:
                    selected.append(word)
                offset=stop+1
            # A shared line with income or employer information needs manual
            # marking; do not suggest obscuring the remainder of that line.
            value=text[start:end]
            if selected and not re.search(r'\b(gross|net|ytd|earnings|employer|balance|deposits|withdrawals|date of birth|expiry|expiration)\b',value,re.I):
                item={'text':value, 'reason':reason, 'box':union(selected), 'location':'OCR matched'}
                if not any(existing['box']==item['box'] for existing in result):
                    result.append(item)
    return result


if __name__ == '__main__' and '--worker' in sys.argv:
    try:
        data=recognize(sys.stdin.buffer.read())
        sys.stdout.buffer.write(json.dumps(data).encode('utf-8'))
    except Exception:
        sys.exit(1)
