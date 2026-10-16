#!/usr/bin/env bash
# v1.18.18 —— 传输状态机端到端测试（真实 readerLoop + 内存管道）
#
# ★ 这个测试把 FlashNode 的接收/发送全链路跑起来 ——
#   Windows 端两个致命 bug（skip 语义写反 / md5 只喂跳过块）只有这类
#   端到端测试能抓到，纯算法测试全部绿灯也说明不了问题。
set -e
cd "$(dirname "$0")/.."

SDK="C:/Users/Administrator/tools/android-sdk"
JAVA_HOME="C:/Users/Administrator/tools/jdk/jdk-17.0.2"
JAVAC="$JAVA_HOME/bin/javac.exe"
JAVA="$JAVA_HOME/bin/java.exe"
PLAT="$SDK/platforms/android-34/android.jar"

STAGE='C:/Users/Administrator/AppData/Local/Temp/fd_rt11818n'
rm -rf "$STAGE"
mkdir -p "$STAGE/src" "$STAGE/classes"

SRC="app/src/main/java/com/flashdrop/app"
# ★ 编译产品类：FlashNode 依赖面广，编译错误按需补文件
for f in FlashNode FdProto FdResume FdUtil Prefs FdAnim; do
  cp "$SRC/$f.java" "$STAGE/src/" 2>/dev/null || true
done
cp tests/RT11818Node.java "$STAGE/src/"

# stub：classpath 必须排在 android.jar **前面**才能遮蔽 stub-only 类
mkdir -p "$STAGE/src/android/os" "$STAGE/src/android/content" \
         "$STAGE/src/android/media" "$STAGE/src/org/json"
cp tests/stub/android/os/*.java "$STAGE/src/android/os/"
cp tests/stub/android/content/*.java "$STAGE/src/android/content/"
cp tests/stub/android/media/*.java "$STAGE/src/android/media/"
cp tests/stub/org/json/*.java "$STAGE/src/org/json/"
cp tests/stub/R.java "$STAGE/src/" 2>/dev/null || true
# R.java 若声明 package com.flashdrop.app 就放对位置
if head -5 "$STAGE/src/R.java" 2>/dev/null | grep -q "package"; then
  mkdir -p "$STAGE/src_pkg"
fi

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

# fd.cache.dir / fd.save.dir：FdUtil 的测试注入点（生产代码为空走原路径）
"$JAVA" -Dfile.encoding=UTF-8 \
        -Dfd.cache.dir="$(cygpath -w "$STAGE/cache" 2>/dev/null || echo "$STAGE/cache")" \
        -cp "classes;$PLAT" com.flashdrop.app.RT11818Node