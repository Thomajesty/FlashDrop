# 闪传 FlashDrop

> Windows + Android 双端局域网文件互传应用 —— 不用数据线、不走互联网服务器，同一 WiFi 即可互传文本、图片与任意文件。

📦 **[下载最新版](https://github.com/Thomajesty/FlashDrop/releases/latest)** ｜ 📖 [使用说明](docs/使用说明.md) ｜ 🔌 [通信协议](docs/PROTOCOL.md)

---

## 功能特性

- **局域网直连互传** —— UDP 广播/组播自动发现设备，TCP 直连传输，不经过任何服务器
- **多路由器级联** —— 设备分属不同子网（路由器 A 下挂路由器 B）也能自动找到彼此
- **文本 / 图片 / 任意文件** —— 512KB 分块传输，MD5 校验，可取消；文件传输支持断点续传
- **表情面板** —— 1592 个微软 Fluent Emoji，10 个分类，两端共用同一目录
- **离线待发队列** —— 对方不在线时消息与文件先入队，设备上线自动补发（确认送达才出队）
- **传输加密（TLS）** —— 两端同时开启时自动加密通信，未开启自动回退明文
- **软件更新** —— 两端内置检查更新（设置 → 检查更新），版本与安装包托管在 GitHub Releases，启动时每天自动静默检查一次

## 下载

| 平台 | 文件 | 说明 |
|---|---|---|
| Windows | `FlashDrop_vX.Y.Z_win.exe` | 单文件绿色版，免安装（Windows 10/11） |
| Android | `FlashDrop_vX.Y.Z.apk` | Android 7.0+，同一签名可直接覆盖升级 |

前往 [Releases](https://github.com/Thomajesty/FlashDrop/releases) 页面下载，两端版本可以不同（协议兼容），但建议保持最新。

## 更新日志与检查更新

所有版本发布在 [GitHub Releases](https://github.com/Thomajesty/FlashDrop/releases)，附更新说明与 MD5 校验。

两端应用内置更新检查（v1.18.30 起）：

- **手动**：设置 → 检查更新 → 显示版本对比与更新日志 → 一键下载
- **自动**：启动时每天静默检查一次，发现新版本才弹窗（可「跳过此版本」）
- 检查走 GitHub 公开 API，无需登录；国内网络访问较慢时会有 8 秒超时上限，失败不影响使用

## 快速开始

1. Windows 端双击 `FlashDrop_vX.Y.Z_win.exe`；Android 端安装 `FlashDrop_vX.Y.Z.apk`
2. 两端连接**同一 WiFi**（或同一路由器下的任意子网）
3. 设备会自动出现在列表里 → 点选设备即可发消息 / 传文件

## 自行构建

### Windows（Python + PySide6）

```bash
# 需要 Python 3.12 + PySide6 6.11.x
pip install PySide6 pyinstaller
cd windows
python -m PyInstaller --noconfirm FlashDrop.spec
# 产物：windows/dist/FlashDrop.exe
```

### Android（原生 Java，手工打包）

```bash
# 需要 JDK 17 + Android SDK build-tools 34（aapt2 / d8 / apksigner）
# 签名：用自己的 keystore 生成 android/keystore/flashdrop.keystore（勿提交！）
cd android
bash _build_v11817.sh        # Git Bash；Windows 下也可用 build_apk.bat
# 产物：android/dist/FlashDrop.apk
```

> ⚠️ `android/keystore/` 已被 `.gitignore` 排除——**签名密钥绝不进仓库**。
> 首次构建请自行生成：`keytool -genkey -v -keystore android/keystore/flashdrop.keystore -alias flashdrop -keyalg RSA -keysize 2048 -validity 10000`

## 目录结构（开发规范）

```
FlashDrop/
├── windows/                 # Windows 端源码
│   ├── app/                 #   应用代码（ui/ 界面、core/ 协议与传输）
│   ├── assets/              #   微软 Fluent Emoji 资产（1592 张 PNG + 目录 JSON）
│   ├── tests/               #   回归测试脚本（verify_*.py）
│   ├── main.py              #   入口
│   ├── FlashDrop.spec       #   PyInstaller 打包配置
│   └── dist/FlashDrop.exe   #   ★ 构建产物固定落这里
│
├── android/                 # Android 端源码
│   ├── app/src/main/        #   Java 代码 / res 资源 / assets 表情目录
│   ├── tests/               #   回归测试脚本
│   ├── keystore/            #   ★ 签名文件（勿删、勿提交；删了无法覆盖安装）
│   ├── build_apk.bat        #   Windows 打包脚本
│   ├── _build_v11817.sh     #   当前打包脚本（staging 到 ASCII 路径，绕非 ASCII 路径问题）
│   └── dist/FlashDrop.apk   #   ★ 构建产物固定落这里
│
├── release/                 # ★★ 交付中心（本地，不进仓库）
│   ├── latest/              #   当前最新交付（滚动更新）
│   └── history/             #   历史版本归档 + 历史版本记录.md
│
├── docs/                    # 文档
│   ├── 使用说明.md
│   └── PROTOCOL.md          #   通信协议定义
│
└── tools/                   # 跨端工具脚本
```

### 版本号位置（发版必须同步）

| 文件 | 字段 |
|---|---|
| `windows/app/__init__.py` | `__version__` |
| `android/app/src/main/AndroidManifest.xml` | `versionCode`（自增 1）、`versionName` |
| `android/app/src/main/java/com/flashdrop/app/FdUtil.java` | `APP_VERSION` |
| `android/build_apk.bat` 与 `android/_build_v11817.sh` | `--version-code` / `--version-name` |

### 验收测试

```bash
PY="python"   # 需 Python 3.12（PySide6 6.11.x）
for t in windows/tests/verify_v*.py; do "$PY" "$t"; done
```

| 套件 | 覆盖 |
|---|---|
| `verify_v11818_android_ui.py` | 安卓 UI 布局仿真 |
| `verify_v11824_search_contrast.py` | 搜索行 WCAG 对比度 |
| `verify_v11825_row_stability.py` | 设备栏形变行稳定性 |
| `verify_v11827_file_status_sync.py` | 文件状态与磁盘对齐 |
| `verify_v11829_emoji_assets.py` | 表情资产进包 + 加载失败可见 |
| `verify_v11830_update_check.py` | 更新功能 + 角标修复 |

## 红线

- ❌ 不要删除 `android/keystore/`（签名丢失 → 用户无法覆盖安装，必须卸载重装）
- ❌ 不要把签名密钥提交进仓库（`.gitignore` 已排除）
- ❌ 不要删除 `windows/assets/fluent_emoji/`（1592 张表情 PNG，EXE 依赖它）
- ❌ Android 打包时 aapt2 link **必须带 `-A assets`**，否则 `emoji_catalog.json` 不进 APK → 表情面板空白（v1.18.22~v1.18.28 踩过）

## License

本项目为个人作品，源码仅供学习交流。
