# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/down_arrow.png', 'assets'),
           ('assets/check.png', 'assets'),
           ('assets/weixin_qr.png', 'assets'),
           ('assets/alipay_qr.png', 'assets'),
           ('assets/fd_tls_cert.pem', 'assets'),
           ('assets/fd_tls_key.pem', 'assets'),
           # ★ v1.18.10：微软 Fluent Emoji 资产（1592 张 72px PNG + 目录 JSON）
           # 必须显式列出目录，否则 PyInstaller 不会带上 1592 个子文件
           ('assets/fluent_emoji', 'assets/fluent_emoji'),
           ('assets/emoji_catalog.json', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='FlashDrop',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/icon.ico'],
)
