"""Offline redactor with optional AI on a loopback-only local server."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / 'lib'))
import io
import json
import math
import os
import tempfile
import threading
import queue
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import pymupdf as pdf
from PIL import Image, ImageDraw, ImageTk
import local_ai
import local_ocr
import profiles


def ground_suggestion(page, item):
    text = item['text'].strip()
    hits = page.search_for(text) if text and page.rotation == 0 else []
    label_only = text.lower().rstrip(': ') in {
        'ssn', 'social security number', 'bank account', 'account number',
        'routing number', 'employee id', 'confidential client', 'client',
        'customer', 'project', 'internal deal pricing'}
    if hits and label_only:
        # A model may return a field label alone. Never silently hide only the
        # label while leaving its value visible. Ground to the containing line.
        lines = [line for block in page.get_text('dict')['blocks'] if 'lines' in block for line in block['lines']]
        expanded = []
        for hit in hits:
            for line in lines:
                rect = pdf.Rect(line['bbox'])
                content = ' '.join(span['text'] for span in line['spans']).lower()
                if rect.intersects(hit) and not any(word in content for word in ('gross pay','net pay','year to date','ytd','total earnings')):
                    expanded.append(rect)
        hits = expanded
    if not hits:
        return [dict(item, location='approximate; check value coverage')]
    result = []
    for hit in hits:
        box = [max(0,(hit.x0-2)/page.rect.width),max(0,(hit.y0-2)/page.rect.height),min(1,(hit.x1+2)/page.rect.width),min(1,(hit.y1+2)/page.rect.height)]
        result.append(dict(item, box=box, location='text line matched' if label_only else 'text matched'))
    return result


def page_image(page, dpi=200):
    pix = page.get_pixmap(dpi=dpi, alpha=False, colorspace=pdf.csRGB, annots=True)
    return Image.frombytes('RGB', (pix.width, pix.height), pix.samples)


def burn_boxes(image, boxes):
    image = image.copy()
    draw = ImageDraw.Draw(image)
    w, h = image.size
    for x0, y0, x1, y1 in boxes:
        # Cover outward-rounded boundaries plus a pixel for anti-aliasing.
        draw.rectangle((max(0, math.floor(x0*w)-1), max(0, math.floor(y0*h)-1),
                        min(w-1, math.ceil(x1*w)+1), min(h-1, math.ceil(y1*h)+1)), fill='black')
    return image


def export_pdf(source, boxes, destination, dpi=200, progress=None):
    """Copy only rendered, redacted pixels into a new PDF, never source objects."""
    out = pdf.open()
    temporary = None
    try:
        for i, page in enumerate(source):
            image = burn_boxes(page_image(page, dpi), boxes[i])
            # Pass only burned pixels, avoiding a PNG encode/decode round trip.
            pixels = pdf.Pixmap(pdf.csRGB, image.width, image.height, image.tobytes(), False)
            new = out.new_page(width=page.rect.width, height=page.rect.height)
            new.insert_image(new.rect, pixmap=pixels)
            del pixels, image
            if progress:
                progress(f'Preparing page {i+1} of {len(source)}', i+1)
        destination = Path(destination)
        fd, temporary = tempfile.mkstemp(prefix='.redacted-', suffix='.pdf', dir=destination.parent)
        os.close(fd)
        if progress:
            progress('Compressing and checking the PDF...', len(source))
        out.save(temporary, garbage=3, deflate=True)
        out.close()
        with pdf.open(temporary) as check:
            if len(check) != len(source) or any(p.get_text().strip() for p in check):
                raise ValueError('Export verification failed.')
            if check.embfile_count() or any(list(p.widgets() or []) or list(p.annots() or []) for p in check):
                raise ValueError('Unexpected embedded content in export.')
        os.replace(temporary, destination)
        temporary = None
    finally:
        if not out.is_closed:
            out.close()
        if temporary and os.path.exists(temporary):
            os.remove(temporary)


def validate_template(data, document):
    if data.get('version') != 1 or len(data.get('pages', [])) != len(document):
        raise ValueError('This template has a different page count or format.')
    result = []
    for saved, page in zip(data['pages'], document):
        if any(abs(a-b) > 1 for a, b in zip(saved['size'], (page.rect.width, page.rect.height))) or len(saved['size']) != 2:
            raise ValueError('Page sizes differ. Mark this layout manually.')
        boxes = saved['boxes']
        if len(boxes) > 1000:
            raise ValueError('Too many boxes in template.')
        for b in boxes:
            if len(b) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) and 0 <= v <= 1 for v in b) or not (b[0] < b[2] and b[1] < b[3]):
                raise ValueError('Invalid template coordinates.')
        result.append(boxes)
    return result


class App:
    def __init__(self, root):
        self.root = root
        root.title('Private Document Redactor | Offline | 3.0')
        root.geometry('1180x850')
        root.minsize(960, 680)
        root.configure(bg='#f4f3ef')
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 11), background='#f4f3ef', foreground='#202d2b')
        style.configure('TButton', padding=(12, 9))
        style.configure('Title.TLabel', font=('Segoe UI Semibold', 22))
        style.configure('Note.TLabel', foreground='#3d5c53')
        self.doc = None
        self.path = None
        self.boxes = []
        self.index = 0
        self.zoom = 1.0
        self.start = None
        self.drag_id = None
        self.ai_busy = False
        self.saving = False
        self.ocr_words = {}
        self.ocr_pending = {}
        self.reviewed_pages = set()
        self.undo_history = {}
        self.redo_history = {}
        self.preview_cache = {}
        self.dirty = False
        self.reviewed = tk.BooleanVar(value=False)
        header = ttk.Frame(root, padding=(24, 20, 24, 14))
        header.pack(fill='x')
        ttk.Label(header, text='Private Document Redactor', style='Title.TLabel').pack(anchor='w')
        ttk.Label(header, text='Works on this computer. No uploads. Your original stays intact.', style='Note.TLabel').pack(anchor='w', pady=(5, 0))
        preset = ttk.Frame(root, padding=(24,0,24,10))
        preset.pack(fill='x')
        ttk.Label(preset, text='Document type:').pack(side='left',padx=(0,10))
        self.profile = tk.StringVar(value='Paystub')
        selector = ttk.Combobox(preset,textvariable=self.profile,values=list(profiles.PROFILES),state='readonly',width=29)
        selector.pack(side='left')
        selector.bind('<<ComboboxSelected>>', self.profile_changed)
        ttk.Label(preset,text='Save quality:').pack(side='left',padx=(24,10))
        self.quality = tk.StringVar(value='Standard (200 DPI)')
        ttk.Combobox(preset,textvariable=self.quality,values=['Standard (200 DPI)','Fine (300 DPI)'],state='readonly',width=22).pack(side='left')
        tools = ttk.Frame(root, padding=(24, 0, 24, 12))
        tools.pack(fill='x')
        for label, command in [('Open document', self.open), ('Load template', self.load_template), ('Save template', self.save_template), ('Undo', self.undo), ('Redo', self.redo), ('Clear page', self.clear)]:
            ttk.Button(tools, text=label, command=command).pack(side='left', padx=(0, 8))
        self.ocr_button = ttk.Button(tools, text='OCR all pages', command=self.ocr_all)
        self.ocr_button.pack(side='left', padx=(0,8))
        ttk.Button(tools, text='Review page OCR', command=self.review_ocr).pack(side='left')
        pagebar = ttk.Frame(root, padding=(24,0,24,10))
        pagebar.pack(fill='x')
        self.page_heading = ttk.Label(pagebar,text='No document open',font=('Segoe UI Semibold',14))
        self.page_heading.pack(side='left')
        self.review_progress = ttk.Label(pagebar,text='')
        self.review_progress.pack(side='left',padx=20)
        ttk.Button(pagebar,text='Next unreviewed page',command=self.next_unreviewed).pack(side='right')
        body = ttk.Frame(root, padding=(24, 0, 24, 0))
        body.pack(fill='both', expand=True)
        sidebar=ttk.Frame(body)
        sidebar.pack(side='left',fill='y',padx=(0,12))
        ttk.Label(sidebar,text='Pages',font=('Segoe UI Semibold',11)).pack(anchor='w',pady=(0,6))
        self.page_list=tk.Listbox(sidebar,width=19,exportselection=False,font=('Segoe UI',11),activestyle='none')
        page_scroll=ttk.Scrollbar(sidebar,orient='vertical',command=self.page_list.yview)
        self.page_list.configure(yscrollcommand=page_scroll.set)
        page_scroll.pack(side='right',fill='y')
        self.page_list.pack(fill='both',expand=True)
        self.page_list.bind('<<ListboxSelect>>',self.select_page)
        preview=ttk.Frame(body)
        preview.pack(fill='both',expand=True)
        self.canvas = tk.Canvas(preview, bg='#dce1de', highlightthickness=0,cursor='crosshair')
        scroll = ttk.Scrollbar(preview, orient='vertical', command=self.canvas.yview)
        horizontal = ttk.Scrollbar(preview, orient='horizontal', command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        scroll.pack(side='right', fill='y')
        horizontal.pack(side='bottom', fill='x')
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<ButtonPress-1>', self.begin)
        self.canvas.bind('<B1-Motion>', self.drag)
        self.canvas.bind('<ButtonRelease-1>', self.end)
        self.canvas.bind('<Button-3>', self.remove_box)
        self.canvas.bind('<MouseWheel>', lambda e: self.canvas.yview_scroll(-int(e.delta/120), 'units'))
        self.canvas.create_text(520, 180, text='Open a PDF, PNG, or JPEG to begin.\n\nDrag over anything you want removed.', font=('Segoe UI', 17), fill='#304b43', justify='center')
        nav = ttk.Frame(root, padding=(24, 10))
        nav.pack(fill='x')
        for label, command in [('Previous', lambda: self.move(-1)), ('Next', lambda: self.move(1)), ('Zoom -', lambda: self.change_zoom(-0.25)), ('Zoom +', lambda: self.change_zoom(0.25))]:
            ttk.Button(nav, text=label, command=command).pack(side='left', padx=(0, 7))
        self.status = ttk.Label(nav, text='No document open')
        self.status.pack(side='left', padx=12)
        self.ai_button = ttk.Button(nav, text='Suggest sensitive areas', command=self.suggest)
        self.ai_button.pack(side='right')
        ttk.Button(nav,text='Fit page',command=self.fit_page).pack(side='right',padx=5)
        footer = ttk.Frame(root, padding=(24, 0, 24, 18))
        footer.pack(fill='x')
        self.guidance = ttk.Label(footer, text=profiles.PROFILES[self.profile.get()][0],wraplength=1000)
        self.guidance.pack(anchor='w')
        self.review_check=ttk.Checkbutton(footer,text='I reviewed this page: sensitive details are covered and required information is readable.',variable=self.reviewed,command=self.toggle_review)
        self.review_check.pack(anchor='w',pady=8)
        ttk.Label(footer,text='Drag to cover. Right-click a box to remove it. Ctrl+Z undo / Ctrl+Y redo. Page Up / Down to navigate.').pack(anchor='w')
        ttk.Button(footer, text='Save redacted PDF...', command=self.save).pack(anchor='e')
        root.bind('<Control-z>', lambda e: self.undo())
        root.bind('<Control-y>', lambda e: self.redo())
        root.bind('<Control-o>', lambda e: self.open())
        root.bind('<Control-s>', lambda e: self.save())
        root.bind('<Prior>',lambda e:self.move(-1))
        root.bind('<Next>',lambda e:self.move(1))
        root.protocol('WM_DELETE_WINDOW', self.close)

    def close(self):
        if self.saving:
            messagebox.showinfo('Saving in progress', 'The export is still running. Please wait for the progress window to finish.')
            return
        if self.dirty and not messagebox.askyesno('Unsaved redactions','Close without saving your changes? Use Save template to preserve editable boxes.'):
            return
        if self.doc:
            self.doc.close()
        self.root.destroy()

    def profile_changed(self, event=None):
        self.ocr_pending.clear()
        self.reviewed_pages.clear()
        self.reviewed.set(False)
        self.guidance.configure(text=profiles.PROFILES[self.profile.get()][0])
        self.render()

    def open(self):
        if self.dirty and not messagebox.askyesno('Unsaved redactions','Open another document and discard unsaved changes? Save a template first if you need these boxes.'):
            return
        path = filedialog.askopenfilename(filetypes=[('Documents', '*.pdf *.png *.jpg *.jpeg')])
        if not path:
            return
        try:
            doc = pdf.open(path)
            if doc.needs_pass:
                password = simpledialog.askstring('Password', 'Document password:', show='*')
                if not password or not doc.authenticate(password):
                    doc.close()
                    raise ValueError('The password was not accepted.')
            if not len(doc):
                doc.close()
                raise ValueError('This document has no pages.')
            if self.doc:
                self.doc.close()
            self.doc, self.path = doc, Path(path)
            self.boxes = [[] for _ in doc]
            self.ocr_words = {}
            self.ocr_pending = {}
            self.reviewed_pages.clear()
            self.undo_history.clear()
            self.redo_history.clear()
            self.preview_cache.clear()
            self.dirty=False
            self.index, self.zoom = 0, 1.0
            self.reviewed.set(False)
            self.render()
        except Exception as e:
            messagebox.showerror('Could not open document', str(e))

    def render(self):
        if self.doc is None:
            return
        if self.index not in self.preview_cache:
            if len(self.preview_cache)>=3:
                self.preview_cache.pop(next(iter(self.preview_cache)))
            self.preview_cache[self.index]=page_image(self.doc[self.index],120)
        self.original = self.preview_cache[self.index]
        width = max(120, int(850*self.zoom))
        height = round(self.original.height*width/self.original.width)
        shown = self.original.resize((width, height), Image.Resampling.LANCZOS)
        shown = burn_boxes(shown, self.boxes[self.index])
        self.photo = ImageTk.PhotoImage(shown)
        self.w, self.h = shown.size
        self.canvas.delete('all')
        self.canvas.create_image(16, 16, image=self.photo, anchor='nw')
        self.canvas.configure(scrollregion=(0, 0, self.w+32, self.h+32))
        pending = len(self.ocr_pending.get(self.index, []))
        self.status.configure(text=f'Page {self.index+1} / {len(self.doc)} | {len(self.boxes[self.index])} boxes | {pending} OCR suggestions')
        self.sync_pages()

    def sync_pages(self):
        if self.doc is None:
            return
        self.reviewed.set(self.index in self.reviewed_pages)
        self.page_heading.configure(text=f'Page {self.index+1} of {len(self.doc)}')
        self.review_progress.configure(text=f'{len(self.reviewed_pages)} of {len(self.doc)} pages reviewed')
        self.page_list.delete(0,'end')
        for i in range(len(self.doc)):
            state='Reviewed' if i in self.reviewed_pages else 'Review needed'
            self.page_list.insert('end',f'{i+1}. {state}')
        self.page_list.selection_set(self.index)
        self.page_list.see(self.index)

    def toggle_review(self):
        if self.doc is None:
            self.reviewed.set(False)
            return
        if self.reviewed.get() and (self.ai_busy or self.ocr_pending.get(self.index)):
            self.reviewed.set(False)
            messagebox.showinfo('Finish suggestions first','Wait for analysis and accept or discard this page\'s suggestions before marking it reviewed.')
            return
        if self.reviewed.get():
            self.reviewed_pages.add(self.index)
        else:
            self.reviewed_pages.discard(self.index)
        self.sync_pages()

    def invalidate_page(self,index=None):
        index=self.index if index is None else index
        self.reviewed_pages.discard(index)
        if index==self.index:
            self.reviewed.set(False)
        self.sync_pages()

    def checkpoint(self):
        self.undo_history.setdefault(self.index,[]).append([b[:] for b in self.boxes[self.index]])
        self.redo_history[self.index]=[]
        self.dirty=True
        self.invalidate_page()

    def select_page(self,event=None):
        selection=self.page_list.curselection()
        if selection and selection[0]!=self.index:
            self.move(selection[0]-self.index)

    def next_unreviewed(self):
        if self.doc is None:
            return
        for step in range(1,len(self.doc)+1):
            index=(self.index+step)%len(self.doc)
            if index not in self.reviewed_pages:
                self.move(index-self.index)
                return
        messagebox.showinfo('Review complete','All pages have been reviewed. You can save the redacted PDF.')

    def fit_page(self):
        if self.doc is None:
            return
        page=self.doc[self.index]
        width=min(self.canvas.winfo_width()-32,(self.canvas.winfo_height()-32)*page.rect.width/page.rect.height)
        self.zoom=max(.2,width/850)
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self.render()

    def remove_box(self,event):
        if self.doc is None:
            return
        x,y=self.point(event)
        for i in range(len(self.boxes[self.index])-1,-1,-1):
            a,b,c,d=self.boxes[self.index][i]
            if a<=x<=c and b<=y<=d:
                self.checkpoint()
                self.boxes[self.index].pop(i)
                self.render()
                return

    def point(self, event):
        return (min(1, max(0, (self.canvas.canvasx(event.x)-16)/self.w)),
                min(1, max(0, (self.canvas.canvasy(event.y)-16)/self.h)))

    def begin(self, event):
        if self.doc is None:
            return
        self.start = self.point(event)
        self.drag_id = self.canvas.create_rectangle(0, 0, 0, 0, outline='#bb4d22', width=2, fill='#333333', stipple='gray50')

    def drag(self, event):
        if self.start is None:
            return
        x, y = self.point(event)
        a, b = self.start
        self.canvas.coords(self.drag_id, a*self.w+16, b*self.h+16, x*self.w+16, y*self.h+16)

    def end(self, event):
        if self.start is None:
            return
        x, y = self.point(event)
        a, b = self.start
        self.start = None
        if abs(a-x)*self.w >= 3 and abs(b-y)*self.h >= 3:
            self.checkpoint()
            self.boxes[self.index].append([min(a,x), min(b,y), max(a,x), max(b,y)])
            self.reviewed.set(False)
        self.render()

    def move(self, delta):
        if self.doc is not None:
            self.index = max(0, min(len(self.doc)-1, self.index+delta))
            self.canvas.yview_moveto(0)
            self.render()

    def change_zoom(self, delta):
        self.zoom = max(0.2, min(3.0, self.zoom+delta))
        self.render()

    def undo(self):
        if self.doc is not None and self.undo_history.get(self.index):
            self.redo_history.setdefault(self.index,[]).append([b[:] for b in self.boxes[self.index]])
            self.boxes[self.index]=self.undo_history[self.index].pop()
            self.dirty=True
            self.invalidate_page()
            self.render()

    def redo(self):
        if self.doc is not None and self.redo_history.get(self.index):
            self.undo_history.setdefault(self.index,[]).append([b[:] for b in self.boxes[self.index]])
            self.boxes[self.index]=self.redo_history[self.index].pop()
            self.dirty=True
            self.invalidate_page()
            self.render()

    def clear(self):
        if self.doc is not None:
            self.checkpoint()
            self.boxes[self.index] = []
            self.reviewed.set(False)
            self.render()

    def suggest(self):
        if self.doc is None or self.ai_busy:
            return
        index, document = self.index, self.doc
        profile = self.profile.get()
        # Render on the UI thread; the worker never accesses the source PDF.
        image = burn_boxes(page_image(document[index], 200), self.boxes[index])
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        ocr_png = buffer.getvalue()
        image.thumbnail((1250, 1500))
        buffer = io.BytesIO()
        image.save(buffer, format='PNG')
        png = buffer.getvalue()
        results = queue.Queue()
        self.ai_busy = True
        self.ai_button.configure(state='disabled')
        self.status.configure(text='Local AI reviewing page... may take a few minutes')

        def worker():
            try:
                words = local_ocr.run(ocr_png)
                items = local_ai.suggest(png, profile)
                results.put(((items, words), None))
            except Exception as e:
                results.put((None, str(e)))

        def poll():
            try:
                payload, error = results.get_nowait()
            except queue.Empty:
                self.root.after(200, poll)
                return
            self.ai_busy = False
            self.ai_button.configure(state='normal')
            if self.doc is not document or self.index != index or self.profile.get() != profile:
                messagebox.showinfo('Page changed', 'AI results were discarded because you changed the document or page. Run suggestions on the page you want.')
                return
            self.render()
            if error:
                messagebox.showerror('Local AI unavailable', error+'\n\nManual redaction still works. No cloud fallback is used.')
                return
            items, words = payload
            self.ocr_words[index] = words
            self.invalidate_page(index)
            if not items:
                messagebox.showinfo('No suggestions', 'The model suggested no areas. This is not a privacy guarantee. Check the page yourself.')
                return
            grounded = []
            page = document[index]
            for item in items:
                hits = local_ocr.match(words, item['text'])
                if hits:
                    grounded.extend(dict(item, box=box, location='OCR matched') for box in hits)
                else:
                    grounded.extend(ground_suggestion(page, item))
            self.review_suggestions(grounded, index, document)

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(200, poll)

    def review_ocr(self):
        if self.doc is None:
            return
        items = self.ocr_pending.get(self.index, [])
        if not items:
            messagebox.showinfo('Page OCR', 'No pending suggestions for this page. Use OCR all pages, or draw boxes manually. OCR can miss sensitive details.')
            return
        self.review_suggestions(items, self.index, self.doc)

    def ocr_all(self):
        if self.doc is None or self.ai_busy:
            return
        document = self.doc
        profile = self.profile.get()
        self.ai_busy = True
        self.ai_button.configure(state='disabled')
        self.ocr_button.configure(state='disabled')
        def finish():
            self.ai_busy = False
            self.ai_button.configure(state='normal')
            self.ocr_button.configure(state='normal')
            self.render()
        def process(index):
            if self.doc is not document or self.profile.get() != profile:
                finish()
                return
            if index == len(document):
                finish()
                count=sum(len(items) for items in self.ocr_pending.values())
                messagebox.showinfo('OCR complete', f'Checked {len(document)} pages locally; {count} suggestions ready.\n\nUse Previous / Next and Review page OCR on each page. Nothing has been redacted automatically. Check for missed details, including multiple stubs on one page.')
                return
            self.status.configure(text=f'Local OCR: page {index+1} / {len(document)}')
            image=burn_boxes(page_image(document[index],200),self.boxes[index])
            buf=io.BytesIO(); image.save(buf,format='PNG')
            png=buf.getvalue()
            results=queue.Queue()
            def worker():
                try:
                    words=local_ocr.run(png)
                    results.put((words,None))
                except Exception as e:
                    results.put((None,str(e)))
            def poll():
                try:
                    words,error=results.get_nowait()
                except queue.Empty:
                    self.root.after(100,poll)
                    return
                if self.doc is not document or self.profile.get() != profile:
                    finish()
                    return
                if error:
                    finish()
                    messagebox.showerror('OCR stopped',f'Page {index+1}: {error}\nEarlier pages remain available for review. No cloud fallback is used.')
                    return
                self.ocr_words[index]=words
                self.ocr_pending[index]=local_ocr.suggestions(words, profile)
                self.invalidate_page(index)
                self.root.after(1,lambda:process(index+1))
            threading.Thread(target=worker,daemon=True).start()
            self.root.after(100,poll)
        self.root.after(1,lambda:process(0))

    def review_suggestions(self, items, index, document):
        profile = self.profile.get()
        dialog = tk.Toplevel(self.root)
        dialog.title('Review local AI suggestions')
        dialog.geometry('760x420')
        dialog.transient(self.root)
        ttk.Label(dialog, text='Select suggestions to inspect their orange outlines on the page.', padding=12).pack(anchor='w')
        ttk.Label(dialog, text='Locations can be wrong. Add only boxes you have checked; adjust with Undo and drawing.', padding=(12,0)).pack(anchor='w')
        choices = tk.Listbox(dialog, selectmode='extended', exportselection=False, font=('Segoe UI',11))
        choices.pack(fill='both', expand=True, padx=12, pady=12)
        for i,item in enumerate(items):
            choices.insert('end', f"{i+1}. {item['text']} | {item['reason']} | {item['location']}")
        def preview(event=None):
            self.render()
            if self.doc is not document or self.index != index or self.profile.get() != profile:
                return
            for i in choices.curselection():
                a,b,c,d = items[i]['box']
                self.canvas.create_rectangle(a*self.w+16,b*self.h+16,c*self.w+16,d*self.h+16,outline='#c54f18',width=3)
        choices.bind('<<ListboxSelect>>', preview)
        def close():
            if self.doc is document:
                self.ocr_pending.pop(index, None)
            dialog.destroy()
            self.render()
        def apply():
            if self.doc is document and self.index == index and self.profile.get() == profile:
                selected=choices.curselection()
                if selected:
                    self.checkpoint()
                    self.boxes[index].extend(items[i]['box'] for i in selected)
            close()
        actions = ttk.Frame(dialog,padding=12)
        actions.pack(fill='x')
        ttk.Button(actions,text='Discard suggestions',command=close).pack(side='left')
        ttk.Button(actions,text='Add selected boxes',command=apply).pack(side='right')
        dialog.protocol('WM_DELETE_WINDOW',close)

    def save_template(self):
        if self.doc is None:
            return
        path = filedialog.asksaveasfilename(defaultextension='.json', initialfile='paystub-layout.json', filetypes=[('Layout template', '*.json')])
        if path:
            try:
                data = {'version': 1, 'profile': self.profile.get(), 'pages': [{'size': [p.rect.width, p.rect.height], 'boxes': b} for p,b in zip(self.doc, self.boxes)]}
                Path(path).write_text(json.dumps(data, indent=2), encoding='utf-8')
                self.dirty=False
            except Exception as e:
                messagebox.showerror('Could not save template', str(e))

    def load_template(self):
        if self.doc is None:
            messagebox.showinfo('Open a document first', 'Open the new paystub, then load its layout template.')
            return
        path = filedialog.askopenfilename(filetypes=[('Layout template', '*.json')])
        if path:
            try:
                if Path(path).stat().st_size > 1_000_000:
                    raise ValueError('Template file is too large.')
                data = json.loads(Path(path).read_text(encoding='utf-8'))
                self.boxes = validate_template(data, self.doc)
                self.reviewed_pages.clear()
                self.undo_history.clear()
                self.redo_history.clear()
                self.ocr_pending.clear()
                self.dirty=False
                if data.get('profile') in profiles.PROFILES:
                    self.profile.set(data['profile'])
                    self.profile_changed()
                self.reviewed.set(False)
                self.render()
                messagebox.showinfo('Check this paystub', 'Template applied. Check every page before saving: text may have moved even when the page size matches.')
            except Exception as e:
                messagebox.showerror('Could not load template', str(e))

    def save(self):
        if self.doc is None:
            return
        if self.saving:
            return
        if self.ai_busy:
            messagebox.showinfo('Review is still running', 'Wait for the local OCR or AI review to finish before saving.')
            return
        pending = [str(i+1) for i,items in sorted(self.ocr_pending.items()) if items]
        if pending:
            messagebox.showinfo('Review remaining OCR suggestions', 'Accept or discard the pending OCR suggestions on pages '+', '.join(pending)+', then save.')
            return
        missing=[str(i+1) for i in range(len(self.doc)) if i not in self.reviewed_pages]
        if missing:
            messagebox.showinfo('Review each page', 'Mark each page reviewed before saving. Remaining pages: '+', '.join(missing))
            return
        path = filedialog.asksaveasfilename(defaultextension='.pdf', initialfile=self.path.stem+'-REDACTED.pdf', filetypes=[('PDF', '*.pdf')])
        if not path:
            return
        if Path(path).resolve() == self.path.resolve():
            messagebox.showerror('Keep the original', 'Choose a different filename. The original cannot be overwritten.')
            return
        self.start_export(path)

    def start_export(self, path):
        self.saving = True
        dialog = tk.Toplevel(self.root)
        dialog.title('Saving redacted PDF')
        dialog.geometry('460x160')
        dialog.transient(self.root)
        dialog.grab_set()
        label = ttk.Label(dialog,text='Preparing a local copy in memory...',padding=18)
        label.pack(anchor='w')
        bar = ttk.Progressbar(dialog,maximum=len(self.doc),mode='determinate')
        bar.pack(fill='x',padx=18,pady=8)
        ttk.Label(dialog,text='Your original stays intact. No uploads.',padding=(18,5)).pack(anchor='w')
        dialog.protocol('WM_DELETE_WINDOW',lambda:None)
        results = queue.Queue()
        self.root.update_idletasks()
        try:
            snapshot = self.doc.tobytes(encryption=pdf.PDF_ENCRYPT_NONE) if self.doc.is_pdf else self.doc.convert_to_pdf()
            settings = json.dumps({'boxes':self.boxes,'destination':str(path),
                                   'dpi':300 if self.quality.get().startswith('Fine') else 200}).encode()+b'\n'
        except Exception as e:
            dialog.destroy()
            self.saving=False
            messagebox.showerror('Could not prepare export',str(e))
            return
        def worker():
            try:
                process = subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--export-worker'],
                    stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                def feed():
                    try:
                        process.stdin.write(settings)
                        process.stdin.write(snapshot)
                        process.stdin.close()
                    except (OSError,ValueError):
                        pass
                threading.Thread(target=feed,daemon=True).start()
                for line in process.stdout:
                    results.put(json.loads(line))
                # The worker never prints document contents or raw exceptions.
                process.stderr.read()
                process.stdout.close()
                process.stderr.close()
                code=process.wait()
                results.put({'done':True,'ok':code==0})
            except Exception:
                results.put({'done':True,'ok':False})
        def poll():
            while True:
                try:
                    event=results.get_nowait()
                except queue.Empty:
                    self.root.after(100,poll)
                    return
                if event.get('done'):
                    self.saving=False
                    dialog.destroy()
                    if event.get('ok'):
                        self.dirty=False
                        messagebox.showinfo('Redacted copy saved','Saved and checked for hidden text and attachments.\n\nOpen the saved PDF locally and inspect every page before submitting it. The PDF is image-only; text cannot be selected.')
                    else:
                        messagebox.showerror('Could not save PDF','Export failed. Your original and any previous output were preserved. Check free space and folder permissions, then try again.')
                    return
                label.configure(text=event.get('message','Saving...'))
                bar.configure(value=event.get('page',0))
        threading.Thread(target=worker,daemon=True).start()
        self.root.after(100,poll)


if __name__ == '__main__':
    if '--export-worker' in sys.argv:
        try:
            settings=json.loads(sys.stdin.buffer.readline())
            data=sys.stdin.buffer.read()
            def report(message,page):
                print(json.dumps({'message':message,'page':page}),flush=True)
            with pdf.open(stream=data,filetype='pdf') as source:
                export_pdf(source,settings['boxes'],settings['destination'],settings['dpi'],report)
        except Exception:
            sys.exit(1)
    else:
        root = tk.Tk()
        App(root)
        root.mainloop()
