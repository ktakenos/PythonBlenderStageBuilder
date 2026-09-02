#!/usr/bin/env bash
# ポータブル化: 本スクリプトがあるディレクトリを作業ディレクトリにする
set -e
cd "$(dirname "$(readlink -f "$0")")"

# Blender 5.x のパス（環境に合わせて編集、または BLENDER_EXE 環境変数で上書き）
BLENDER_EXE="${BLENDER_EXE:-blender}"

if ! command -v "$BLENDER_EXE" >/dev/null 2>&1 && [ ! -x "$BLENDER_EXE" ]; then
  echo "[ERROR] Blender not found: $BLENDER_EXE"
  echo "Please set BLENDER_EXE=/path/to/blender and retry."
  exit 1
fi

"$BLENDER_EXE" --background \
  --python drummer_lipsync_unified.py -- \
    --midi      drum_pattern.mid \
    --base-midi bass_pattern.mid \
    --musicxml  vocal_melody.musicxml \
    --base      Drummer_Home-Position_Face.blend \
    --output    final_output.blend \
    --fps       60 \
    --stage     stage_output.blend \
    --camera    off \
  > unified_test_log.txt 2>&1

EXIT_CODE=$?
echo ""
echo "=== EXIT CODE: ${EXIT_CODE} ==="
tail -n 200 unified_test_log.txt
exit ${EXIT_CODE}