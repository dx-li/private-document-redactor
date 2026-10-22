# Build from the repository root with: pyinstaller --clean tools/windows.spec
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

root=Path(SPECPATH).parent
data=[(str(root/'tessdata/eng.traineddata'),'tessdata')]
data+=collect_data_files('pymupdf')
binaries=collect_dynamic_libs('pymupdf')
a=Analysis([str(root/'launcher.py')],pathex=[str(root)],binaries=binaries,datas=data,
           hiddenimports=['PIL.ImageTk','_tkinter'],hookspath=[],runtime_hooks=[],excludes=[])
pyz=PYZ(a.pure)
gui=EXE(pyz,a.scripts,[],exclude_binaries=True,name='PrivateDocumentRedactor',console=False,upx=False)
worker=EXE(pyz,a.scripts,[],exclude_binaries=True,name='RedactorWorker',console=True,upx=False)
bundle=COLLECT(gui,worker,a.binaries,a.datas,name='PrivateDocumentRedactor',upx=False)
