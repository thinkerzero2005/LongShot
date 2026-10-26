# -*- mode: python ; coding: utf-8 -*-

# 体积裁剪（阶段一）：只剔除确定未使用的模块与二进制，不改动业务代码。
#
# 1) 模块层面：无网络、无 yaml、无 tkinter，PIL 的 avif/webp 解码器也不参与保存
EXCLUDES = [
    'ssl',
    '_ssl',
    '_hashlib',
    'yaml',
    'pyreadline3',
    'PIL._avif',
    'PIL._webp',
    'numpy.testing',
    'numpy.f2py',
    'tkinter',
]

# 2) 文件层面：DLL / Qt 插件 / 翻译文件。匹配的是打包目标路径（小写子串匹配）
EXCLUDE_BINARIES = (
    'opencv_videoio_ffmpeg',   # OpenCV 视频编解码，本项目从不调用
    'opengl32sw.dll',          # 软件 OpenGL 兜底，QtWidgets 用不到
    'qt6pdf.dll',
    'qt6network.dll',
    'qt6svg.dll',
    'qsvgicon',
    'qwebp.dll',
    'qtiff.dll',
    'qgif.dll',
    'qicns.dll',
    'qoffscreen',
    'qminimal',
    'qtuiotouchplugin',
    'qmodernwindowsstyle',
    'translations',            # 96 个 Qt 语言包，界面文案全部自带
    '_avif',
    '_webp',
    'libssl',
    'libcrypto',
    'yaml',
)


def _keep_binary(entry):
    """entry 为 TOC 三元组 (dest_name, src_path, typecode)。"""
    dest = entry[0].lower()
    return not any(pattern in dest for pattern in EXCLUDE_BINARIES)


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('resources', 'resources')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=2,
)

a.binaries = [b for b in a.binaries if _keep_binary(b)]
a.datas = [d for d in a.datas if _keep_binary(d)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='长截图',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['resources\\icon.ico'],
)
