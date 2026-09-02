@echo off
setlocal
rem ============================================================
rem  run_stage.bat
rem  run_stage.py を既定設定で実行し、ステージ一式を生成する
rem  出力: stage_output.blend (本ファイルと同じディレクトリ)
rem ============================================================

rem ポータブル化: 本batファイルがあるディレクトリを作業ディレクトリにする
cd /d "%~dp0"

rem Blender 5.x のパス（環境に合わせて修正してください）
set "BLENDER_EXE=C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"

if not exist "%BLENDER_EXE%" (
  echo [ERROR] Blender not found at: %BLENDER_EXE%
  echo Please edit this .bat and set BLENDER_EXE to your Blender 5.x executable.
  exit /b 1
)

"%BLENDER_EXE%" --background --python run_stage.py -- --output stage_output.blend > stage_build_log.txt 2>&1

echo.
echo === EXIT CODE: %ERRORLEVEL% ===
type stage_build_log.txt
endlocal
