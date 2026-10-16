#!/usr/bin/env bash
# v1.18.15 —— 离线待发队列行为测试（RT11815）的编译与运行
#
# 两个环境坑（都已在项目 MEMORY.md 记录）：
#   1. **javac 不吃非 ASCII 路径** —— 仓库在 E:\工作缓存\... 下，
#      必须先把源码 staging 到纯 ASCII 的临时目录再编译。
#   2. **android.jar 的方法全是 throw new RuntimeException("Stub!")** ——
#      我们自己的 tests/stub/android/os/Handler.java 必须在 classpath 中
#      排在 android.jar **之前**，否则 FlashApp 的 Handler 会直接炸。
set -e
cd "$(dirname "$0")/.."

ROOT="$(pwd -W)"
SDK="C:/Users/Administrator/tools/android-sdk"
JAVA_HOME="C:/Users/Administrator/tools/jdk/jdk-17.0.2"
JAVAC="$JAVA_HOME/bin/javac.exe"
JAVA="$JAVA_HOME/bin/java.exe"
PLAT="$SDK/platforms/android-34/android.jar"

STAGE='C:/Users/Administrator/AppData/Local/Temp/fd_rt11815'
rm -rf "$STAGE"
mkdir -p "$STAGE/src" "$STAGE/classes"

SRC="app/src/main/java/com/flashdrop/app"
for f in FlashNode FdProto FdUtil Prefs FlashApp FdAnim CrashTrap; do
  cp "$SRC/$f.java" "$STAGE/src/" || true
done
cp tests/stub/R.java "$STAGE/src/"
cp tests/RT11815.java "$STAGE/src/"
# stub 的 org/json 与 android/os 保持包目录结构
mkdir -p "$STAGE/src/org/json" "$STAGE/src/android/os"
cp tests/stub/org/json/*.java "$STAGE/src/org/json/"
cp tests/stub/android/os/*.java "$STAGE/src/android/os/"

cd "$STAGE"
find src -name '*.java' > args.txt
"$JAVAC" -nowarn -encoding UTF-8 -cp "$PLAT" -d classes "@args.txt" 2>&1 \
  | grep -viE "deprecat|^ע|^Note|warning" || true

if [ ! -f "classes/RT11815.class" ]; then
  echo "!! 编译失败（未产出 RT11815.class）"
  exit 2
fi

# classes 里已含我们的 android/os/Handler，必须排在 android.jar 前面
"$JAVA" -Dfile.encoding=UTF-8 -cp "classes;$PLAT" RT11815