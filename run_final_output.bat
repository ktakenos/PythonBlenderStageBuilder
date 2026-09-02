@echo off
setlocal
rem ポータブル化: 本batファイルがあるディレクトリを作業ディレクトリにする
cd /d "%~dp0"

rem Blender 5.x のパス（環境に合わせて修正してください）
set "BLENDER_EXE=C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"

if not exist "%BLENDER_EXE%" (
  echo [ERROR] Blender not found at: %BLENDER_EXE%
  echo Please edit this .bat and set BLENDER_EXE to your Blender 5.x executable.
  exit /b 1
)

"%BLENDER_EXE%" --background --python drummer_lipsync_unified.py -- --midi drum_pattern.mid --base-midi bass_pattern.mid --musicxml vocal_melody.musicxml --base Drummer_Home-Position_Face.blend --output final_output.blend --fps 60 --stage stage_output.blend --camera off > unified_test_log.txt 2>&1

echo.
echo === EXIT CODE: %ERRORLEVEL% ===
type unified_test_log.txt
endlocal