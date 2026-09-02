#!/usr/bin/env bash
# ============================================================
#  run_stage.sh
#  run_stage.py を既定設定で実行し、ステージ一式を生成する
#  出力: stage_output.blend (本ファイルと同じディレクトリ)
# ============================================================

# ポータブル化: 本スクリプトがあるディレクトリを作業ディレクトリにする
cd "$(dirname "$(readlink -f "$0")")"

# Blender 5.x のパス（環境に合わせて編集、または BLENDER_EXE 環境変数で上書き）
BLENDER_EXE="${BLENDER_EXE:-blender}"

if ! command -v "$BLENDER_EXE" >/dev/null 2>&1 && [ ! -x "$BLENDER_EXE" ]; then
  echo "[ERROR] Blender not found: $BLENDER_EXE"
  echo "Please set BLENDER_EXE=/path/to/blender and retry."
  exit 1
fi

# 注: 意図的に `set -e` を使わず、blender の終了コードを以下で取得している
"$BLENDER_EXE" --background --python run_stage.py -- --output stage_output.blend > stage_build_log.txt 2>&1
EXIT_CODE=$?

echo ""
echo "=== EXIT CODE: ${EXIT_CODE} ==="
tail -n 200 stage_build_log.txt
exit ${EXIT_CODE}
