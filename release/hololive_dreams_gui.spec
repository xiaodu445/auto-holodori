# PyInstaller onedir specification. Build from Game_agent with:
#   python release/build_release.py --pyinstaller
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

PROJECT = Path(SPECPATH).parent
hiddenimports = collect_submodules("modular_agent")
a = Analysis(
    [str(PROJECT / "gui" / "hololive_dreams_gui.py")],
    pathex=[str(PROJECT / "src"), str(PROJECT / "gui")],
    binaries=[],
    datas=[(str(PROJECT / "src"), "src"), (str(PROJECT / "domains"), "domains"), (str(PROJECT / "gui"), "gui")],
    hiddenimports=hiddenimports,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="HololiveDreamsGUI", console=True)

