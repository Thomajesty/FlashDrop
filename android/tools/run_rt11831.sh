#!/usr/bin/env bash
# v1.18.31 —— 「连接过的设备不能在设备列表删除」行为测试（RT11831）
#
# 覆盖两层：
#   A 区 Prefs.blockedPeers 状态机（真实 Prefs + 内存 SharedPreferences）
#   B 区 FlashNode 过滤（peerBlocked / touchPeer / enforceBlocklist）
#
# 环境坑（同 RT11818Node）：
#   · javac 不吃非 ASCII 路径 → staging 到 ASCII 临时目录
#   · android.jar 方法全是 Stub! → tests/stub 必须在 classpath 里**排在**
#     android.jar 前面（javac -cp 的顺序 + java -cp 的顺序都算）
set -e
cd "$(dirname "$0")/.."

SDK="C:/Users/Administrator/tools/android-sdk"
JAVA_HOME="C:/Users/Administrator/tools/jdk/jdk-17.0.2"
JAVAC="$JAVA_HOME/bin/javac.exe"
JAVA="$JAVA_HOME/bin/java.exe"
PLAT="$SDK/platforms/android-34/android.jar"

STAGE='C:/Users/Administrator/AppData/Local/Temp/fd_rt11831'
rm -rf "$STAGE"
mkdir -p "$STAGE/src" "$STAGE/classes"

SRC="app/src/main/java/com/flashdrop/app"
for f in FlashNode FdProto FdResume FdUtil Prefs FdAnim; do
  cp "$SRC/$f.java" "$STAGE/src/" 2>/dev/null || true
done
cp tests/RT11831.java "$STAGE/src/"

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

"$JAVA" -Dfile.encoding=UTF-8 -cp "classes;$PLAT" com.flashdrop.app.RT11831
