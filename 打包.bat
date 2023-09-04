@echo off
CHCP 65001
env\Scripts\pyinstaller.exe --onefile  --add-binary="D:\txt_to_video\env\Library\bin\libssl-1_1-x64.dll;." --add-binary="D:\txt_to_video\env\Library\bin\libcrypto-1_1-x64.dll;." --add-binary="D:\txt_to_video\env\Library\bin\ffi.dll;." --add-data="D:\txt_to_video\dist2;dist2"  --add-binary="D:\txt_to_video\env\Lib\site-packages\azure\cognitiveservices\speech\Microsoft.CognitiveServices.Speech.core.dll;azure/cognitiveservices/speech" --add-binary="D:\txt_to_video\env\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win64-v4.2.2.exe;." --exclude-module pkg_resources --exclude-module lzma --exclude-module bz2 --exclude-module _tkinter --exclude-module sqlite3 拾光推文1.3.py
echo 构建完成，将继续打包
timeout /T 1 >NUL
env\Scripts\pyinstaller.exe 拾光推文1.3.spec
echo 打包完成！
pause
