# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 构建配置：单文件、无控制台窗口的 MediaInsight.exe
from PyInstaller.utils.hooks import collect_data_files

datas = [("assets/icon.ico", "assets")]
datas += collect_data_files("jieba")                    # 分词词典
datas += collect_data_files("googleapiclient")          # API discovery 文档（离线构建服务）

a = Analysis(
    ["main.py"],
    pathex=["."],
    datas=datas,
    hiddenimports=["matplotlib.backends.backend_tkagg", "PIL._tkinter_finder",
                   "google_auth_oauthlib.flow", "googleapiclient.discovery"],
    excludes=["PyQt5", "PyQt6", "PySide2", "PySide6", "IPython", "notebook", "pytest", "scipy"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="MediaInsight",
    icon="assets/icon.ico",
    console=False,
    upx=False,
    runtime_tmpdir=None,
)
