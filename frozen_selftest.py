"""Synthetic smoke checks for a packaged build; no network or user files."""
import io
import json
from pathlib import Path
import subprocess
import tempfile
import redactor as app
from runtime_paths import worker_command

def run():
    from PIL import ImageFont
    image=app.Image.new('RGB',(1100,700),'white')
    draw=app.ImageDraw.Draw(image)
    font=ImageFont.truetype('arial.ttf',28)
    for i,text in enumerate(['SAMPLE DOCUMENT','Account number: 000123456789','Closing balance: $5000']):
        draw.text((40,40+i*100),text,font=font,fill='black')
    buf=io.BytesIO();image.save(buf,format='PNG')
    words=app.local_ocr.run(buf.getvalue())
    suggestions=app.local_ocr.suggestions(words,'Bank statement')
    assert len(suggestions)==1 and '000123456789' in suggestions[0]['text']
    source=app.pdf.open()
    for i in range(2):
        page=source.new_page(width=612,height=792)
        page.insert_text((40,90),'SYNTHETIC SECRET')
        page.insert_text((40,200),'Visible amount: 5000')
    source.set_metadata({'title':'PRIVATE SOURCE'})
    source.embfile_add('private.txt',b'PRIVATE ATTACHMENT')
    with tempfile.TemporaryDirectory(prefix='redactor-smoke-') as folder:
        target=Path(folder)/'result.pdf'
        header=json.dumps({'boxes':[[[.04,.06,.7,.15]],[[.04,.06,.7,.15]]],
                           'destination':str(target),'dpi':200,'email':True}).encode()+b'\n'
        process=subprocess.run(worker_command('--export-worker'),input=header+source.tobytes(),capture_output=True,
                               creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=120)
        assert process.returncode==0,process.stderr.decode(errors='replace')
        assert target.stat().st_size<=app.EMAIL_LIMIT
        with app.pdf.open(target) as out:
            assert len(out)==2 and out.embfile_count()==0
            assert not any(page.get_text() for page in out)
            assert 'PRIVATE' not in str(out.metadata)
            assert max(app.page_image(out[0],72).getpixel((80,90)))<10
    source.close()
    print(json.dumps({'ok':True,'checks':['packaged OCR worker','packaged export worker','burned pixels','hidden content removal','email size']}),flush=True)
