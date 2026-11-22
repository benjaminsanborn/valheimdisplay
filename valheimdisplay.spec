# PyInstaller recipe for the single-file valheimdisplay executable.
#   uv run pyinstaller valheimdisplay.spec   ->  dist/valheimdisplay(.exe)
import glob
import os
from PyInstaller.utils.hooks import collect_all

tools = [os.path.splitext(os.path.basename(p))[0] for p in glob.glob('tools/*.py')]
datas, binaries, hidden = [], [], list(tools)
# UnityPy and its texture/audio decoders ship native code and data files that PyInstaller can't see by itself
for pkg in ('UnityPy', 'texture2ddecoder', 'etcpak', 'astc_encoder', 'fmod_toolkit', 'pyfmodex', 'tpk_ar', 'brotli', 'lz4', 'archspec'):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hidden += h
    except Exception:
        pass
# the website (generated assets are made at run time from the user's own game files)
for p in glob.glob('web/**/*', recursive=True):
    if os.path.isfile(p) and not p.startswith(os.path.join('web', 'assets')):
        datas.append((p, os.path.dirname(p)))

a = Analysis(['tools/valheimdisplay.py'], pathex=['tools'], binaries=binaries, datas=datas, hiddenimports=hidden,
             excludes=['tkinter', 'matplotlib', 'IPython', 'pytest'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='valheimdisplay', console=True, upx=False,
          runtime_tmpdir=None, strip=False)
