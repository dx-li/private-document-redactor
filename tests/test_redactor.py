import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import redactor as app


def sample_document(count=3):
    document=app.pdf.open()
    for i in range(count):
        page=document.new_page(width=360,height=480)
        page.insert_text((30,60),'SYNTHETIC SECRET')
        page.insert_text((30,150),f'Page {i+1}: visible amount 5000')
    document.set_metadata({'title':'PRIVATE SOURCE METADATA'})
    document.embfile_add('private.txt',b'PRIVATE ATTACHMENT')
    document[0].add_text_annot((200,100),'PRIVATE NOTE')
    return document


class ExportTests(unittest.TestCase):
    def test_fresh_pdf_has_only_burned_pixels(self):
        source=sample_document()
        original=source.tobytes()
        boxes=[[[.05,.05,.7,.2]] for _ in source]
        progress=[]
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'redacted.pdf'
            app.export_pdf(source,boxes,target,progress=lambda *event:progress.append(event))
            with app.pdf.open(target) as out:
                self.assertEqual(len(out),3)
                self.assertEqual(out.embfile_count(),0)
                self.assertNotIn('PRIVATE',str(out.metadata))
                for i,page in enumerate(out):
                    self.assertEqual(page.rect,source[i].rect)
                    self.assertFalse(page.get_text())
                    self.assertFalse(list(page.annots() or []))
                    self.assertFalse(list(page.widgets() or []))
                    image=app.page_image(page,72)
                    self.assertEqual(image.getpixel((60,60)),(0,0,0))
                    self.assertTrue(any(min(image.getpixel((x,y)))<100 for x in range(30,200) for y in range(140,155)))
            self.assertEqual(len(progress),4)
            # The source still contains its original objects and text.
            self.assertIn('SYNTHETIC SECRET',source[0].get_text())
            self.assertEqual(source.embfile_count(),1)
        source.close()

    def test_failed_worker_preserves_existing_destination(self):
        source=sample_document(1)
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'previous.pdf'
            target.write_bytes(b'PREVIOUS OUTPUT')
            header=json.dumps({'boxes':[],'destination':str(target),'dpi':200}).encode()+b'\n'
            result=subprocess.run([sys.executable,str(Path(app.__file__)),'--export-worker'],input=header+source.tobytes(),capture_output=True)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(target.read_bytes(),b'PREVIOUS OUTPUT')
        source.close()

    def test_template_rejects_invalid_coordinates(self):
        source=sample_document(1)
        data={'version':1,'pages':[{'size':[360,480],'boxes':[[0,0,2,1]]}]}
        with self.assertRaises(ValueError):
            app.validate_template(data,source)
        source.close()


class ReviewTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root=app.tk.Tk()
        except app.tk.TclError as error:
            self.skipTest(str(error))
        self.root.withdraw()
        self.ui=app.App(self.root)
        self.ui.doc=sample_document()
        self.ui.path=Path('synthetic.pdf')
        self.ui.boxes=[[],[],[]]
        self.ui.render()

    def tearDown(self):
        if hasattr(self,'ui'):
            self.ui.dirty=False
            self.ui.close()

    def mark(self):
        self.ui.reviewed.set(True)
        self.ui.toggle_review()

    def test_each_page_has_independent_review_and_edit_invalidation(self):
        self.mark()
        self.ui.move(1)
        self.assertFalse(self.ui.reviewed.get())
        self.mark()
        self.ui.checkpoint()
        self.ui.boxes[1].append([.1,.1,.2,.2])
        self.ui.render()
        self.assertEqual(self.ui.reviewed_pages,{0})
        self.ui.undo()
        self.assertEqual(self.ui.boxes[1],[])
        self.ui.redo()
        self.assertEqual(self.ui.boxes[1],[[.1,.1,.2,.2]])
        self.assertEqual(self.ui.reviewed_pages,{0})
        self.ui.move(-1)
        self.assertTrue(self.ui.reviewed.get())
        self.assertEqual(self.ui.page_heading.cget('text'),'Page 1 of 3')
        self.ui.next_unreviewed()
        self.assertEqual(self.ui.index,1)

    def test_export_requires_all_pages_and_pending_suggestions_resolved(self):
        self.mark()
        with patch.object(app.messagebox,'showinfo') as info, patch.object(app.filedialog,'asksaveasfilename',return_value='') as picker:
            self.ui.save()
            picker.assert_not_called()
            self.assertIn('2, 3',info.call_args.args[1])
            self.ui.reviewed_pages={0,1,2}
            self.ui.ocr_pending[2]=[{'text':'synthetic'}]
            self.ui.save()
            picker.assert_not_called()
            self.ui.ocr_pending.clear()
            self.ui.save()
            picker.assert_called_once()

    def test_pending_analysis_blocks_marking_reviewed(self):
        self.ui.ocr_pending[0]=[{'text':'synthetic'}]
        with patch.object(app.messagebox,'showinfo'):
            self.mark()
        self.assertFalse(self.ui.reviewed_pages)

    def test_loading_template_does_not_restore_review_approvals(self):
        self.ui.reviewed_pages={0,1,2}
        data={'version':1,'profile':'Bank statement','pages':[{'size':[360,480],'boxes':[]} for _ in range(3)]}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'layout.json'
            path.write_text(json.dumps(data))
            with patch.object(app.filedialog,'askopenfilename',return_value=str(path)),patch.object(app.messagebox,'showinfo'):
                self.ui.load_template()
        self.assertFalse(self.ui.reviewed_pages)
        self.assertEqual(self.ui.profile.get(),'Bank statement')

    def test_worker_keeps_event_loop_alive(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(app.messagebox,'showinfo'),patch.object(app.messagebox,'showerror') as error:
            ticks=[]
            self.ui.start_export(Path(folder)/'export.pdf')
            def heartbeat():
                ticks.append(1)
                if self.ui.saving:
                    self.root.after(10,heartbeat)
            self.root.after(10,heartbeat)
            deadline=time.monotonic()+30
            while self.ui.saving and time.monotonic()<deadline:
                self.root.update()
                time.sleep(.005)
            self.assertFalse(self.ui.saving)
            self.assertGreater(len(ticks),2)
            error.assert_not_called()


class OCRTests(unittest.TestCase):
    @unittest.skipUnless((Path(app.__file__).parent/'tessdata/eng.traineddata').exists(),'Run setup_local.py for English OCR data')
    def test_scanned_bank_and_id_fields_align(self):
        from PIL import ImageFont
        font=ImageFont.truetype('arial.ttf',26)
        image=app.Image.new('RGB',(1100,750),'white')
        draw=app.ImageDraw.Draw(image)
        for i,text in enumerate(['SAMPLE - FICTIONAL','Name: Example Person','Account number: 000123456789','Passport number: X12345678','Closing balance: $5000']):
            draw.text((40,40+i*85),text,font=font,fill='black')
        buf=io.BytesIO();image.save(buf,format='PNG')
        words=app.local_ocr.run(buf.getvalue())
        items=app.local_ocr.suggestions(words,'Mixed / general')
        self.assertEqual(len(items),2)
        self.assertTrue(app.local_ocr.match(words,'000123456789'))
        self.assertTrue(app.local_ocr.match(words,'X12345678'))
        self.assertFalse(any('5000' in item['text'] for item in items))


if __name__=='__main__':
    unittest.main()
