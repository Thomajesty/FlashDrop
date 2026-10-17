@echo off
rem FlashDrop APK build (aapt2 + javac + d8 + zipalign + apksigner)
setlocal enabledelayedexpansion
set SDK=C:\Users\Administrator\tools\android-sdk
set BT=%SDK%\build-tools\34.0.0
set PLAT=%SDK%\platforms\android-34\android.jar
set JAVA_HOME=C:\Users\Administrator\tools\jdk\jdk-17.0.2
set PATH=%JAVA_HOME%\bin;%PATH%

set SRC=%~dp0app\src\main
set BUILD=%~dp0app\build
set DIST=%~dp0dist

echo == 1. clean ==
if exist "%BUILD%" rmdir /s /q "%BUILD%"
mkdir "%BUILD%\gen" "%BUILD%\classes" "%BUILD%\dex"
if not exist "%DIST%" mkdir "%DIST%"

echo == 2. aapt2 compile ==
call "%BT%\aapt2.exe" compile --dir "%SRC%\res" -o "%BUILD%\res.zip" || goto :err

echo == 3. aapt2 link ==
rem ★ -A "%SRC%\assets" 才会把 assets/ 打进 APK。
rem   缺了它 assets/emoji_catalog.json 不会进包 → 表情面板读到空目录、
rem   打开就是一块空白（v1.18.22~v1.18.28 实际踩坑：用户反馈"表情包不显示"）。
call "%BT%\aapt2.exe" link -o "%BUILD%\unsigned.apk" -I "%PLAT%" --manifest "%SRC%\AndroidManifest.xml" "%BUILD%\res.zip" -A "%SRC%\assets" --java "%BUILD%\gen" --auto-add-overlay --min-sdk-version 24 --target-sdk-version 34 --version-code 61 --version-name 1.18.32 || goto :err

echo == 4. javac ==
dir /s /b "%SRC%\java\*.java" > "%BUILD%\sources.txt"
dir /s /b "%BUILD%\gen\*.java" >> "%BUILD%\sources.txt"
javac -encoding UTF-8 -classpath "%PLAT%" -d "%BUILD%\classes" @"%BUILD%\sources.txt" || goto :err

echo == 5. d8 dex ==
"%JAVA_HOME%\bin\jar.exe" cf "%BUILD%\classes.jar" -C "%BUILD%\classes" . || goto :err
call "%BT%\d8.bat" --release --lib "%PLAT%" --min-api 24 --output "%BUILD%\dex" "%BUILD%\classes.jar" || goto :err

echo == 6. package classes.dex ==
"%JAVA_HOME%\bin\jar.exe" --update --file "%BUILD%\unsigned.apk" -C "%BUILD%\dex" classes.dex || goto :err

echo == 7. zipalign ==
call "%BT%\zipalign.exe" -f 4 "%BUILD%\unsigned.apk" "%BUILD%\aligned.apk" || goto :err

echo == 8. keystore (persistent, signature must stay identical for upgrade install) ==
set KEYSTORE=%~dp0keystore\flashdrop.keystore
if not exist "%~dp0keystore" mkdir "%~dp0keystore"
if not exist "%KEYSTORE%" (
  "%JAVA_HOME%\bin\keytool.exe" -genkeypair -keystore "%KEYSTORE%" -storepass flashdrop123 -keypass flashdrop123 -alias flashdrop -keyalg RSA -keysize 2048 -validity 10950 -dname "CN=FlashDrop, O=FlashDrop" || goto :err
)

echo == 9. sign ==
rem Enable v1+v2+v3 explicitly: some local ROM installers still use the v1 (JAR) path,
rem signing v2 only can break install/launch on certain models.
call "%BT%\apksigner.bat" sign --ks "%KEYSTORE%" --ks-pass pass:flashdrop123 --key-pass pass:flashdrop123 --v1-signing-enabled true --v2-signing-enabled true --v3-signing-enabled true --out "%DIST%\FlashDrop.apk" "%BUILD%\aligned.apk" || goto :err

echo == 10. verify ==
call "%BT%\apksigner.bat" verify --verbose --min-sdk-version 24 --print-certs "%DIST%\FlashDrop.apk" || goto :err

echo BUILD_OK
exit /b 0

:err
echo BUILD_FAILED
exit /b 1
