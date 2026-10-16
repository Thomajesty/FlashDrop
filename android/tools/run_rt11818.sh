#!/usr/bin/env bash
# v1.18.18 —— 断点续传核心（FdResume 位图）测试
#
# 关键约定（踩过的坑）：
#  · javac 不吃非 ASCII 路径 -> staging 到纯ASCII 目录
#  · 我们自己的 stub（android/os/Handler、org/json）必须排在 android.jar **前面**
#  · android.jar 含 java/util/ 若干类会遮蔽 JDK -> 只用 android.jar 里有的类
set -e
cd "$(dirname "$0")/.."

SDK="C:/Users/Administrator/tools/android-sdk"
JAVA_HOME="C:/Users/Administrator/tools/jdk/jdk-17.0.2"
JAVAC="$JAVA_HOME/bin/javac.exe"
JAVA="$JAVA_HOME/bin/java.exe"
PLAT="$SDK/platforms/android-34/android.jar"

STAGE='C:/Users/Administrator/AppData/Local/Temp/fd_rt11818'
rm -rf "$STAGE"
mkdir -p "$STAGE/src" "$STAGE/classes"

SRC="app/src/main/java/com/flashdrop/app"
# ★ 只拷纯逻辑文件：FdResume 是零 IO 依赖（除 android.util.Base64），
#   不牵进 FlashNode/FdProto，避免整包编译时踩 android.jar 的坑
cp "$SRC/FdResume.java" "$STAGE/src/"
cp tests/RT11818.java "$STAGE/src/"

mkdir -p "$STAGE/src/android/util" "$STAGE/src/org/json"
cp tests/stub/org/json/*.java "$STAGE/src/org/json/" 2>/dev/null || true
# Base64 是 android.jar 里的真类（不是 stub），用 android.jar 自带的即可

cd "$STAGE"
find src -name '*.java' > args.txt
# ★ 先把原始输出落盘：直接管道给 grep 会把中文错误信息（GBK）
#   变成二进制流，导致真正的原因（"找不到符号"之类）完全看不到。
set +e
"$JAVAC" -nowarn -encoding UTF-8 -cp "$PLAT" -d classes "@args.txt" > javac.log 2>&1
rc=$?
set -e
grep -viE "deprecat|warning|^Note|һ��$" javac.log | head -40 || true
echo "javac exit=$rc"

if [ ! -f "classes/RT11818.class" ]; then
  echo "!! 编译失败（未产出 RT11818.class）"; exit 2
fi

"$JAVA" -Dfile.encoding=UTF-8 -cp "classes;$PLAT" RT11818