#!/usr/bin/env bash
# v1.18.33 —— 「离线待发图片不显示」行为测试（RT11833）
#
# 覆盖：emitSendState 事件必须带 src（sendFileSync 补发路径的图片气泡
# 图片源）；sendInfo 缺 src 时容错。rebuildPendingMsgs 照片模式由
# verify_v11833_gallery_fix.py 静态断言把关。
#
# 环境坑（同 RT11831）：
#   · javac 不吃非 ASCII 路径 → staging 到 ASCII 临时目录
#   · android.jar 方法全是 Stub! → tests/stub 必须排在 android.jar 前面
set -e
cd "$(dirname "$0")/.."

SDK="C:/Users/Administrator/tools/android-sdk"
JAVA_HOME="C:/Users/Administrator/tools/jdk/jdk-17.0.2"
JAVAC="$JAVA_HOME/bin/javac.exe"
JAVA="$JAVA_HOME/bin/java.exe"
PLAT="$SDK/platforms/android-34/android.jar"

STAGE='C:/Users/Administrator/AppData/Local/Temp/fd_rt11833'
rm -rf "$STAGE"
mkdir -p "$STAGE/src" "$STAGE/classes"

SRC="app/src/main/java/com/flashdrop/app"
for f in FlashNode FdProto FdResume FdUtil Prefs FdAnim; do
  cp "$SRC/$f.java" "$STAGE/src/" 2>/dev/null || true
done
cp tests/RT11833.java "$STAGE/src/"

mkdir -p "$STAGE/src/android/os" "$STAGE/src/android/content" \
         "$STAGE/src/android/media" "$STAGE/src/org/json"
cp tests/stub/android/os/*.java "$STAGE/src/android/os/"
cp tests/stub/android/content/*.java "$STAGE/src/android/content/"
cp tests/stub/android/media/*.java "$STAGE/src/android/media/"
cp tests/stub/org/json/*.java "$STAGE/src/org/json/"
cp tests/stub/R.java "$STAGE/src/"

cd "$STAGE"
find src -name '*.java' > args.txt
set +e
"$JAVAC" -nowarn -encoding UTF-8 -cp "$PLAT" -d classes "@args.txt" > javac.log 2>&1
rc=$?
set -e
if [ $rc -ne 0 ]; then
  echo "!! 编译失败："
  iconv -f GBK -t UTF-8 javac.log 2>/dev/null | grep -A 3 "错误" | head -50 \
    || head -50 javac.log
  exit 2
fi

"$JAVA" -Dfile.encoding=UTF-8 -cp "classes;$PLAT" com.flashdrop.app.RT11833
