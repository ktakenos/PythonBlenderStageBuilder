"""
Multi-Camera Handler 再登録 + テストレンダリング
==================================================
.blend を開いた後、Scripting ワークスペースで Run Script する。
レンダリング設定 + カメラ切替ハンドラ登録 + アニメーションレンダリングを
一括で行う。

Usage (Blender GUI):
  1. final_output.blend を開く
  2. Scripting → Open → register_multicam_handler.py → Run Script
  3. コンソールに "[MULTI-CAM] Handler registered" が出たらレンダリング開始
  4. 出力: workspace直下の MP4
"""
import bpy
import json

# =====================================================
# [1] レンダリング設定 (動作確認用: 低解像度・低サンプル)
# =====================================================
scene = bpy.context.scene

# 解像度
scene.render.resolution_x = 960
scene.render.resolution_y = 540
scene.render.resolution_percentage = 100

# FPS
scene.render.fps = 60
scene.render.fps_base = 1.0

# Eevee (高速テストレンダリング)
try:
    scene.render.engine = 'BLENDER_EEVEE_NEXT'  # Blender 4.2+
except Exception:
    scene.render.engine = 'BLENDER_EEVEE'  # Blender 4.0/4.1
scene.eevee.taa_render_samples = 32
print(f"  [RENDER] Engine: {scene.render.engine}, samples: {scene.eevee.taa_render_samples}")

# 出力形式・フォルダは GUI (Output Properties) で事前に設定する
# Video → MP4 / フォルダ指定 を GUI で済ませてからこのスクリプトを実行
print(f"  [RENDER] Output: {bpy.context.scene.render.filepath} (GUIで設定済)")
print(f"  [RENDER] Format: {bpy.context.scene.render.image_settings.file_format}")

# =====================================================
# [2] カメラ切替ハンドラ登録
# =====================================================
def _switch(scene, depsgraph=None):
    frame = scene.frame_current
    shots = json.loads(scene.get("multi_cam_shots", "[]"))
    for s in shots:
        if s["start"] <= frame <= s["end"]:
            target = bpy.data.objects.get(s["cam"])
            if target and scene.camera != target:
                scene.camera = target
            break
    else:
        if shots:
            target = bpy.data.objects.get(shots[0]["cam"])
            if target and scene.camera != target:
                scene.camera = target

# 既存ハンドラを除去 (重複防止)
for fn in list(bpy.app.handlers.frame_change_post):
    if getattr(fn, '_multi_cam_switch', False):
        bpy.app.handlers.frame_change_post.remove(fn)

_switch._multi_cam_switch = True
bpy.app.handlers.frame_change_post.append(_switch)

# =====================================================
# [3] 確認表示
# =====================================================
shots = json.loads(bpy.context.scene.get("multi_cam_shots", "[]"))
print(f"\n[MULTI-CAM] Handler registered: {len(shots)} shots")
for s in shots:
    print(f"  {s['start']:>5d} - {s['end']:<5d} : {s['cam']}")

if not shots:
    print("[MULTI-CAM][ERROR] No shots found in scene['multi_cam_shots']!")
    print("  → drummer_lipsync_unified.py で --camera multi を実行済みか確認")

# =====================================================
# [4] テスト範囲設定 (最初のショット=960フレーム=16秒)
# =====================================================
# テスト用: レンダリング範囲を短縮
scene.frame_start = 1
scene.frame_end = 960  # 16秒分 (60fps)
# フル尺レンダリングする場合:
# scene.frame_end = 3840

# =====================================================
# [5] 完了 (レンダリングは Ctrl+F12 で開始)
# =====================================================
print(f"\n{'='*50}")
print(f"  [READY] レンダリング準備完了")
print(f"  範囲: {scene.frame_start} - {scene.frame_end} ({(scene.frame_end-scene.frame_start+1)/60:.0f}秒)")
print(f"  出力: {scene.render.filepath}")
print(f"  形式: {scene.render.image_settings.file_format}")
print(f"")
print(f"  >>> Ctrl+F12 でレンダリング開始 <<<")
print(f"  >>> Esc でキャンセル可能 <<<")
print(f"{'='*50}")
