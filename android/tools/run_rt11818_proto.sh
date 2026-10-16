#!/usr/bin/env bash
# v1.18.18 —— 协议帧（0x43 带块号分块）测试
#
# 关键约定（踩过的坑）：
#  · javac 不吃非ASCII 路径 -> staging 到纯 ASCII 目录
#  · javac 的中文错误信息是 GBK，直接管道给 grep 会变成二进制流，
#    真正的原因（"找不到符号"之类）完全看不到 -> 先落盘再 iconv
#  · 我们自己的 stub（org/json）必须排在 android.jar 前面
set -e
cd "$(dirname "$0")/.."

SDK="C:/Users/Administrator/tools/android-sdk"
JAVA_HOME="C:/Users/Administrator/tools/jdk/jdk-17.0.2"
JAVAC="$JAVA_HOME/bin/javac.exe"
JAVA="$JAVA_HOME/bin/java.exe"
PLAT="$SDK/platforms/android-34/android.jar"

STAGE='C:/Users/Administrator/AppData/Local/Temp/fd_rt11818p'
rm -rf "$STAGE"
mkdir -p "$STAGE/src" "$STAGE/classes"

SRC="app/src/main/java/com/flashdrop/app"
cp "$SRC/FdResume.java" "$STAGE/src/"
cp "$SRC/FdProto.java" "$STAGE/src/"
cp tests/RT11818Proto.java "$STAGE/src/"

mkdir -p "$STAGE/src/org/json"
cp tests/stub/org/json/*.java "$STAGE/src/org/json/" 2>/dev/null || true

cd "$STAGE"
find src -name '*.java' > args.txt
set +e
"$JAVAC" -nowarn -encoding UTF-8 -cp "$PLAT" -d classes "@args.txt" > javac.log 2>&1
rc=$?
set -e
if [ ! -f "classes/RT11818Proto.class" ]; then
  echo "!! 编译失败："
  iconv -f GBK -t UTF-8 javac.log 2>/dev/null | grep -A 3 "错误" | head -40 \
    || head -40 javac.log
  exit 2
fi

"$JAVA" -Dfile.encoding=UTF-8 -cp "classes;$PLAT" RT11818Proto