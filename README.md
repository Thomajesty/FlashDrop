# FlashDrop 工作目录说明

> Windows + Android 双端文件互传应用。本文件定义**固定目录规范**，后续每次更新都按此执行，避免再次变乱。

---

## 目录结构

```
FlashDrop/
├── windows/                 # Windows 端源码
│   ├── app/                 #   应用代码（ui/ 界面、core/ 协议与传输）
│   ├── assets/              #   微软 Fluent Emoji 资产（1592 张 PNG + 目录 JSON）
│   ├── tests/               #   回归测试脚本（verify_*.py / shots_*.py）
│   ├── main.py              #   入口
│   ├── FlashDrop.spec       #   PyInstaller 打包配置
│   └── dist/FlashDrop.exe   #   ★ 构建产物固定落这里
│
├── android/                 # Android 端源码
│   ├── app/src/main/        #   Java 代码 / res 资源 / assets 表情目录
│   ├── tests/               #   回归测试脚本
│   ├── keystore/            #   ★ 签名文件（勿删，删了无法覆盖安装）
│   ├── build_apk.bat        #   Windows 打包脚本
│   ├── _build_v11813.sh     #   当前打包脚本（staging 到 ASCII 路径，绕非 ASCII 路径问题）
│   └── dist/FlashDrop.apk   #   ★ 构建产物固定落这里
│
├── release/                 # ★★ 交付中心 —— 找安装包只看这里
│   ├── latest/              #   当前最新交付（滚动更新）
│   │   ├── FlashDrop_vX.Y.Z_win.exe
│   │   ├── FlashDrop_vX.Y.Z.apk
│   │   ├── md5.txt
│   │   ├── 验收报告.md
│   │   └── screenshots/     #   逐项验收截图
│   └── history/             #   历史版本归档 + 历史版本记录.md
│
├── docs/                    # 文档
│   ├── 使用说明.md
│   └── PROTOCOL.md          #   通信协议定义
│
├── tools/                   # 跨端工具脚本
│   └── make_overview.py     #   验收截图拼总览图
│
└── .workbuddy/              # 工作数据 / 记忆日志（★ 绝对不要删）
```

---

## 每次更新的标准流程

### 1. 改代码
只动 `windows/app/` 与 `android/app/src/main/`。

### 2. 改版本号（三处必须同步）
| 文件 | 字段 |
|---|---|
| `windows/app/__init__.py` | `__version__ = "X.Y.Z"` |
| `android/app/src/main/AndroidManifest.xml` | `versionCode`（自增 1）、`versionName` |
| `android/build_apk.bat` | `--version-code` / `--version-name` |

### 3. 跑回归
```bash
PY="C:/Users/Administrator/AppData/Local/Programs/Python/Python312/python.exe"
# Windows
cd windows && "$PY" tests/run_all_v1189.py
# Android
cd android && "$PY" tests/verify_v11813.py
```
> ⚠️ **必须用上面的 Python312**（PySide6 6.11.2 只装在这里）。
> 用 `.workbuddy` 托管版 3.13.x 会 `ModuleNotFoundError: PySide6`，导致**假失败**。

### 4. 打包
```bash
# Windows（不要加 --clean，沙箱会拦 safe-delete）
cd windows
rm -f dist/FlashDrop.exe
"$PY" -c "import shutil;shutil.rmtree('build',ignore_errors=True)"
"$PY" -m PyInstaller --noconfirm FlashDrop.spec

# Android
cd android && bash _build_v11813.sh
```
> ⚠️ **产物只落 `windows/dist/` 与 `android/dist/`**，不要再建 `distXXXX` / `buildXXXX` 目录。

### 5. 归档交付
```bash
# 1) 清空 release/latest（先把旧版挪进 history）
mv release/latest release/history/v{旧版本}
# 2) 放入新版
mkdir -p release/latest/screenshots
cp windows/dist/FlashDrop.exe release/latest/FlashDrop_v{X.Y.Z}_win.exe
cp android/dist/FlashDrop.apk release/latest/FlashDrop_v{X.Y.Z}.apk
# 3) 校验文件 + 验收报告 + 截图一并放入
# 4) 在 release/history/历史版本记录.md 追加一行 md5
```

### 6. 清理（每次打包后立刻做）
```bash
cd windows
rm -rf build dist                  # 下一版打包前再清；dist 里的 exe 已复制到 release
```
> 保持 `windows/` 下**只有** `build/` 和 `dist/` 两个构建目录，不再留版本后缀目录。

---

## 命名规范

| 类型 | 规则 | 示例 |
|---|---|---|
| 交付 EXE | `FlashDrop_v{版本}_win.exe` | `FlashDrop_v1.18.13_win.exe` |
| 交付 APK | `FlashDrop_v{版本}.apk` | `FlashDrop_v1.18.13.apk` |
| 验收报告 | `验收报告.md`（放 `release/latest/`） | — |
| 验收截图 | `NN_平台_内容.png` | `02_android_devbar.png` |
| 回归脚本 | `verify_v{版本号}.py`（新增，不覆盖旧的） | `verify_v11813.py` |
| 截图脚本 | `shots_v{版本号}.py` | `shots_v11813.py` |

---

## 红线

- ❌ 不要删除 `android/keystore/`（签名丢失 → 用户无法覆盖安装，必须卸载重装）
- ❌ 不要删除 `.workbuddy/`（项目记忆与工作数据）
- ❌ 不要删除 `windows/assets/fluent_emoji/`（1592 张表情 PNG，EXE 依赖它）
- ❌ 不要在 `windows/` 根目录留 `buildXXXX` / `distXXXX` 版本后缀目录
- ❌ 不要用 `--clean` 跑 PyInstaller（沙箱会因 safe-delete 失败）
- ❌ 不要用非 Python312 解释器跑回归（会假失败）
