# -*- coding: utf-8 -*-
"""run_stage.py — 1ステージ(本番ステージ)一式をステージングライブラリから生成するスクリプト。

本ファイルは `archive/__pycache__/run_stage.cpython-310.pyc` の復号 + 現行
`stage_output.blend` のオブジェクト実測値(位置・寸法・ライトパラメータ)から
再構築された再現時点版です。

使い方 (Blender 5.x ヘッドレス):
    blender -b -P run_stage.py
    # 出力先を変える場合:
    blender -b -P run_stage.py -- --output D:\\path\\to\\stage_output.blend

生成内容 (staging パッケージの API を利用):
    1. ステージプラットフォーム (9m x 6m, 高さ1m, 階段・手すり付き)
    2. トラスシステム (10m x 6m, 高さ5m)
    3. スピーカー類 (PA x2, ギター/ベースアンプ, フロアモニター x5)
    4. スポットライト (フロント5 + バック5 + サイド2、ハウジングメッシュ付き)
    5. ドラムセット + ドラム椅子
    6. マイクスタンド (ボーカル x6, ドラム x2)
    7. 後方壁・サイド壁・天井 (サイクロ)
    8. カーテン x6
    9. 客席フロア
   10. Volume Scatter ボックス (光のビーム用)
   11. カメラ + 天井面光源
   => stage_output.blend を保存
"""

import bpy
import math
import os
import sys

# 相対パッケージ(staging)を確実にimport可能にする
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# =============================================================================
# CONFIG — 現行 stage_output.blend の実測値で再構築した数値
# =============================================================================

# --- 1. ステージプラットフォーム (Stage_Platform, Stage_*Stair, Stage_*Railing)
STAGE_WIDTH = 9.0
STAGE_DEPTH = 6.0
STAGE_HEIGHT = 1.0

# --- 2. トラス (Truss_System)
TRUSS_WIDTH = 10.0
TRUSS_DEPTH = 6.0
TRUSS_HEIGHT = 5.0
TRUSS_FRAME_INTERVAL = 1.0
TRUSS_LOCATION = (-5.25, -3.5, 0.5)

# --- 3. スピーカー (type, location) — location はキャビネット中心
SPEAKERS = [
    ("pa",         (-5.0, -3.9, 3.5)),   # PA_Speaker
    ("pa",         ( 5.0, -3.9, 3.5)),   # PA_Speaker.001
    ("guitar_amp", ( 2.5,  1.0, 1.45)),  # Guitar_Amp
    ("bass_amp",   (-2.5,  1.0, 1.40)),  # Bass_Amp
    ("monitor",    (-3.0, -1.8, 1.20)),  # Floor_Monitor
    ("monitor",    ( 1.0, -1.8, 1.20)),  # Floor_Monitor.001
    ("monitor",    (-1.0, -1.8, 1.20)),  # Floor_Monitor.002
    ("monitor",    ( 3.0, -1.8, 1.20)),  # Floor_Monitor.003
    ("monitor",    ( 1.2,  1.0, 1.20)),  # Floor_Monitor.004
]

# --- 4. スポットライト rigs (create_full_lighting_rig 呼び出し順)
#     light_names: 生成後にライトオブジェクトに付ける名前
LIGHT_RIGS = [
    # フロント5灯 (SP1..SP5_Spotlight_Housing / SP_Front_1..5)
    dict(count=5, spacing=1.5, start_x=-3.0, start_y=-3.0, start_z=4.3,
         rotation_angle_deg=50.0, energy=150.0,
         spot_size=math.radians(35.0),
         light_names=[f"SP_Front_{i+1}" for i in range(5)]),
    # バック5灯 (SP1..SP5_Spotlight_Housing.001 / SP_Back_1..5)
    dict(count=5, spacing=1.5, start_x=-3.0, start_y=3.0, start_z=4.3,
         rotation_angle_deg=-70.0, energy=500.0,
         spot_size=math.radians(15.0),
         light_names=[f"SP_Back_{i+1}" for i in range(5)]),
    # サイド左 (SP1_Spotlight_Housing.002 / SP_Side_L)
    dict(count=1, start_x=-5.0, start_y=-12.0, start_z=4.5,
         rotation_angle_deg=75.0, rotation_z_deg=-15.0, energy=1000.0,
         spot_size=math.radians(15.0),
         light_names=["SP_Side_L"]),
    # サイド右 (SP1_Spotlight_Housing.003 / SP_Side_R)
    dict(count=1, start_x=5.0, start_y=-12.0, start_z=4.5,
         rotation_angle_deg=75.0, rotation_z_deg=15.0, energy=1000.0,
         spot_size=math.radians(15.0),
         light_names=["SP_Side_R"]),
]

# --- 5. ドラムセット (Drum_Set, origin=(0, 0.8, 1.2794) 実測)
DRUM_STAGE_WIDTH = 9.0
DRUM_STAGE_DEPTH = 6.0
DRUM_LOCATION_OFFSET = (0.0, 2.4, 1.0)  # center_y = 2.4 - 6*0.3 = 0.6, base_z = 1.0 (ステージ上面)
# ドラム椅子 (Drummer_Chair, シート中心 z=1.35 実測)
CHAIR_LOCATION = (0.0, 1.7, 1.0)  # z は床面(ステージ上面)
CHAIR_SEAT_HEIGHT = 0.35

# --- 6. マイクスタンド (MicStand_Base x8) — 作成順がファイルの .001.. と一致
#     各スタンドの正確なパラメータは参考blendのdimensions/rotationから逆算
VOCAL_MIC_POSITIONS = [  # .000-.002 フロント3本 (straight, H=1.5, 向かい0°)
    (-2.0, -1.5, 1.0),
    ( 0.0, -1.5, 1.0),
    ( 2.0, -1.5, 1.0),
]
# .003/.004 アンプ側 (guitar_pickup boom, H=1.0, L=0.35, 水平, 内側へ±70°)
AMP_MIC_BOOM = [
    dict(location=( 2.8,  0.5, 1.0), rotation_z_deg=-70.0),
    dict(location=(-2.8,  0.5, 1.0), rotation_z_deg= 70.0),
]
# .005 中央ドラム方向 (vocal boom, H=1.0, L=0.25, 上向き30°, 180°)
CENTER_MIC_BOOM = dict(location=(0.0, 0.5, 1.0), rotation_z_deg=180.0)
DRUM_MIC_POSITIONS = [  # .006/.007 スネア (snare boom, L=0.3, 55°, 180°)
    (-0.42, 0.6, 1.0),
    ( 0.42, 0.6, 1.0),
]

# --- 7. 壁・天井 (Cyclorama_Mat)
WALL_BACK = dict(name="Wall_Back", width=12.0, height=6.0, location=(0.0, 4.0, 0.0))
WALL_SIDE_L = dict(name="Wall_Side_L", width=14.0, height=6.0,
                   location=(-5.5, -10.0, 0.0), rotation=(0.0, 0.0, math.radians(90.0)))
WALL_SIDE_R = dict(name="Wall_Side_R", width=14.0, height=6.0,
                   location=(5.5, -10.0, 0.0), rotation=(0.0, 0.0, math.radians(90.0)))
CEILING = dict(width=12.0, depth=16.0, location=(0.0, -4.0, 6.0))

# --- 8. カーテン x6 (Curtain, .001.. — 作成順がファイルと一致)
#     参考 stage_output.blend 実測: SCALE=[0.05,3.0,4.3], LOCAL X=[-1,+1],
#     DIMENSIONS.x=0.1。すなわち「薄い基底(0.05m) + 波(世界振幅±0.025m)」構成。
CURTAIN_HEIGHT = 4.3
CURTAIN_BASE_THICKNESS = 0.05   # 基底スラブ厚 (world m, 参考 SCALE.x に一致)
CURTAIN_FOLDS = 5               # 波の数 (参考 wave3m fit 5.35 に合わせる)
CURTAIN_FOLD_DEPTH = 0.025      # 波のピーク振幅 (world m, 参考 LOCAL X[-1,+1] に相当)
CURTAINS = [
    dict(location=( 4.6, -2.0, 0.1), width=3.0),
    dict(location=( 4.6,  2.0, 0.1), width=3.0),
    dict(location=(-4.6, -2.0, 0.1), width=3.0),
    dict(location=(-4.6,  2.0, 0.1), width=3.0),
    dict(location=( 3.2,  3.1, 0.1), width=2.5,
         rotation=(0.0, 0.0, math.radians(90.0))),
    dict(location=(-3.2,  3.1, 0.1), width=2.5,
         rotation=(0.0, 0.0, math.radians(90.0))),
]

# --- 9. 客席フロア (Audience_Floor, 中心 (0, -10, 0.1) 実測)
AUDIENCE_FLOOR = dict(width=12.0, depth=14.0, thickness=0.2, stage_front_y=-3.0)

# --- 10. Volume Scatter (Stage_Volume_Box, 中心 (0, -6, 3.5) 実測)
STAGE_VOLUME = dict(width=14.0, depth=18.0, height=8.0, location=(0.0, -6.0, 3.5))

# --- 11. カメラ / 天井面光源
CAMERA_LOCATION = (0.0, -14.0, 2.0)
CAMERA_ROTATION_X = 1.507  # rad (実測値、約86.3° — ステージ中央上方面へ)
CAMERA_LENS = 24.0
AREA_LIGHT_LOCATION = (0.0, -3.0, 5.5)
AREA_LIGHT_ENERGY = 200.0
AREA_LIGHT_COLOR = (1.0, 0.98, 0.95)
AREA_LIGHT_SIZE = 12.0


# =============================================================================
# Helpers
# =============================================================================

def _get_output_path():
    """出力先 .blend パス。--output <path> で上書き可。"""
    argv = sys.argv
    if "--" in argv:
        after = argv[argv.index("--") + 1:]
        if "--output" in after:
            idx = after.index("--output")
            if idx + 1 < len(after):
                return os.path.abspath(after[idx + 1])
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "stage_output.blend")


def clear_scene():
    """シーン内の全オブジェクトを削除する。"""
    if bpy.context.scene is None:
        return
    bpy.ops.object.select_all(action="DESELECT")
    for obj in list(bpy.context.scene.objects):
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.delete(use_global=False)
    for block in (bpy.data.meshes, bpy.data.lights, bpy.data.cameras, bpy.data.materials):
        for item in list(block):
            if item.users == 0:
                block.remove(item)


# =============================================================================
# Stage build steps
# =============================================================================

def build_stage():
    """ステージプラットフォーム (床・階段・手すり)。"""
    from staging import create_stage_platform, apply_materials_to_stage
    create_stage_platform(width=STAGE_WIDTH, depth=STAGE_DEPTH, height=STAGE_HEIGHT)
    apply_materials_to_stage()


def build_truss():
    """トラスシステム。"""
    from staging import create_full_stage_truss, apply_materials_to_truss
    create_full_stage_truss(width=TRUSS_WIDTH, depth=TRUSS_DEPTH, height=TRUSS_HEIGHT,
                            frame_interval=TRUSS_FRAME_INTERVAL, location=TRUSS_LOCATION)
    apply_materials_to_truss()


def build_speakers():
    """PA / アンプ / モニター。"""
    from staging import create_speaker
    for speaker_type, location in SPEAKERS:
        create_speaker(speaker_type, location)


def build_lighting():
    """スポットライト rigs (ハウジング + ライト)。ライト名を現行構成に合わせてリネーム。"""
    from staging import create_full_lighting_rig, apply_materials_to_spotlights
    for rig in LIGHT_RIGS:
        objs = create_full_lighting_rig(
            count=rig["count"],
            spacing=rig.get("spacing", 1.0),
            start_x=rig["start_x"],
            start_y=rig["start_y"],
            start_z=rig["start_z"],
            rotation_angle_deg=rig["rotation_angle_deg"],
            rotation_z_deg=rig.get("rotation_z_deg", 0.0),
            energy=rig["energy"],
            spot_size=rig["spot_size"],
        )
        lights = [o for o in objs if o.type == "LIGHT"]
        for light_obj, new_name in zip(lights, rig["light_names"]):
            light_obj.name = new_name
    apply_materials_to_spotlights()


def build_drums():
    """ドラムセット + ドラム椅子。"""
    from staging import create_full_drum_set
    from staging.drum_set_system import create_drummer_chair
    create_full_drum_set(stage_width=DRUM_STAGE_WIDTH, stage_depth=DRUM_STAGE_DEPTH,
                         location_offset=DRUM_LOCATION_OFFSET)
    create_drummer_chair(location=CHAIR_LOCATION, seat_height=CHAIR_SEAT_HEIGHT)


def build_mics():
    """マイクスタンド (ボーカル3 + アンプ2 + 中央1 + ドラム2)。"""
    from staging import create_vocal_mic, create_drum_mic, create_mic_stand
    for pos in VOCAL_MIC_POSITIONS:
        create_vocal_mic(location=pos, height=1.5, rotation_z_deg=0.0)
    for cfg in AMP_MIC_BOOM:
        create_mic_stand(location=cfg["location"], stand_type="boom",
                         height=1.0, base_radius=0.12, boom_length=0.35, boom_angle_deg=0.0,
                         rotation_z_deg=cfg["rotation_z_deg"], clip_type="guitar_pickup")
    create_mic_stand(location=CENTER_MIC_BOOM["location"], stand_type="boom",
                     height=1.0, base_radius=0.12, boom_length=0.25, boom_angle_deg=30.0,
                     rotation_z_deg=CENTER_MIC_BOOM["rotation_z_deg"], clip_type="vocal")
    for pos in DRUM_MIC_POSITIONS:
        create_drum_mic(location=pos, drum_type="snare", boom_length=0.3,
                        boom_angle_deg=55.0, rotation_z_deg=180.0)


def build_walls():
    """後方壁 / サイド壁 / 天井 (サイクロ)。"""
    from staging import create_back_wall
    from staging.back_wall import create_wall, create_ceiling
    create_back_wall(width=WALL_BACK["width"], height=WALL_BACK["height"],
                     location=WALL_BACK["location"])
    create_wall(name=WALL_SIDE_L["name"], width=WALL_SIDE_L["width"],
                height=WALL_SIDE_L["height"], location=WALL_SIDE_L["location"],
                rotation=WALL_SIDE_L["rotation"])
    create_wall(name=WALL_SIDE_R["name"], width=WALL_SIDE_R["width"],
                height=WALL_SIDE_R["height"], location=WALL_SIDE_R["location"],
                rotation=WALL_SIDE_R["rotation"])
    create_ceiling(width=CEILING["width"], depth=CEILING["depth"],
                   location=CEILING["location"])


def build_curtains():
    """カーテン x6 (側面4 + 後方2)。"""
    from staging import create_curtain, clear_curtain_objects
    clear_curtain_objects()
    for c in CURTAINS:
        create_curtain(
            location=c["location"],
            width=c["width"],
            height=CURTAIN_HEIGHT,
            thickness=CURTAIN_BASE_THICKNESS,
            folds=CURTAIN_FOLDS,
            fold_depth=CURTAIN_FOLD_DEPTH,
            rotation=c.get("rotation", (0.0, 0.0, 0.0)),
        )


def build_audience_floor():
    """客席フロア。"""
    from staging import create_audience_floor
    create_audience_floor(**AUDIENCE_FLOOR)


def build_volume():
    """Volume Scatter ボックス (光のビーム可視化用)。"""
    from staging.volume_scatter import create_stage_volume
    create_stage_volume(bpy.context.scene, **STAGE_VOLUME)


def setup_camera():
    """カメラ (24mm, ステージ向かい) と天井面光源を設置。"""
    cam_data = bpy.data.cameras.new("Camera")
    cam = bpy.data.objects.new("Camera", cam_data)
    bpy.context.collection.objects.link(cam)
    cam.location = CAMERA_LOCATION
    cam.rotation_euler = (CAMERA_ROTATION_X, 0.0, 0.0)
    cam_data.lens = CAMERA_LENS
    bpy.context.scene.camera = cam

    area_data = bpy.data.lights.new("Ceiling_Area_Light", type='AREA')
    area_data.energy = AREA_LIGHT_ENERGY
    area_data.color = AREA_LIGHT_COLOR
    area_data.size = AREA_LIGHT_SIZE
    area = bpy.data.objects.new("Ceiling_Area_Light", area_data)
    bpy.context.collection.objects.link(area)
    area.location = AREA_LIGHT_LOCATION


# =============================================================================
# main
# =============================================================================

def main():
    import time
    t0 = time.time()
    print("=" * 60)
    print("[run_stage] stage build start")
    print(f"[run_stage] Blender: {bpy.app.version_string}, Python: {sys.version.split()[0]}")
    print("=" * 60)

    out_path = _get_output_path()

    clear_scene()
    build_stage()
    build_truss()
    build_speakers()
    build_lighting()
    build_drums()
    build_mics()
    build_walls()
    build_curtains()
    build_audience_floor()
    build_volume()
    setup_camera()

    scene = bpy.context.scene
    print(f"[run_stage] objects: {len(scene.objects)} "
          f"(MESH={sum(1 for o in scene.objects if o.type == 'MESH')}, "
          f"LIGHT={sum(1 for o in scene.objects if o.type == 'LIGHT')}, "
          f"CAMERA={sum(1 for o in scene.objects if o.type == 'CAMERA')})")

    bpy.ops.wm.save_as_mainfile(filepath=out_path)
    print(f"[run_stage] saved: {out_path}")
    print(f"[run_stage] done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
