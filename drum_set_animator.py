# -*- coding: utf-8 -*-
print("[drum_set_animator] >>>> FILE LOADED - v3 2026-08-21 22:46 <<<<")
"""drum_set_animator.py - ドラム部品の物理アニメーション(OHH開閉 / シンバル揺れ / バスドラヘッドたわみ)

設計:
  - staging/drum_set_system.py の実在APIを使用し、結合しないドラムセットを生成。
  - アニメ対象(ハイハットトップ/クラッシュ/ライド/バスヘッド)は個別にキーフレーム。
  - MIDIイベント(v6: load_midi_drum_track)をトリガーに同期。
  - 座標は世界座標で直接配置（root Empty不要）。

使い方:
    import drum_set_animator as dsa
    handles = dsa.build_animated_drum_set(events, frame_end=scene.frame_end)
"""

import bpy
import math
import sys
import os

# staging ディレクトリを直接 sys.path に追加（パッケージ __init__.py を回避）
_WS = os.path.dirname(os.path.abspath(__file__))
_STAGING_DIR = os.path.join(_WS, "staging")
for _p in (_WS, _STAGING_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from drum_set_system import (
    create_bass_drum,
    create_kick_pedal,
    create_snare_drum,
    create_snare_stand,
    create_tom_tom,
    create_tom_mount_only,
    create_tom_hbar,
    create_floor_tom,
    create_hihat,
    create_cymbal_with_stand,
)

INCH = 0.0254


# =============================================================================
# 座標定義 (ステージプラットフォーム上: base_z=1.0, center_xy=(0, 0.6))
# バスドラ中心 = (0, 0.8, 1.2794)
# =============================================================================
BASE_Z = 1.0
CX = 0.0
CY = 0.6

# Bass drum
BASS_POS = (CX, CY + 0.2, 22 * INCH / 2 + BASE_Z)          # (0, 0.8, 1.2794)
KICK_PEDAL_POS = (CX, CY + 0.6, 0.015 + BASE_Z)             # (0, 1.2, 1.015)

# Tom mount
_BASS_TOP_Z = 22 * INCH + BASE_Z    # 1.5588
_MOUNT_Z = _BASS_TOP_Z + 0.15       # 1.7088
_POLE_TOP_Z = _MOUNT_Z + 0.15       # 1.8588

TOM_MOUNT_POS = (CX, CY + 0.2, _MOUNT_Z)                    # (0, 0.8, 1.7088)
TOM10_POS = (CX + 0.2, CY + 0.27, _POLE_TOP_Z - 4 * INCH)  # (0.2, 0.87, ~1.757)
TOM12_POS = (CX - 0.25, CY + 0.3, _POLE_TOP_Z - 5 * INCH)  # (-0.25, 0.9, ~1.732)

# Snare
SNARE_STAND_POS = (CX + 0.25, CY + 0.65, 0.30 + BASE_Z)    # (0.25, 1.25, 1.3)
SNARE_DRUM_POS = (CX + 0.25, CY + 0.65, 0.376 + BASE_Z)    # (0.25, 1.25, 1.376)

# Floor Tom
FLOOR_TOM_POS = (CX - 0.3, CY + 0.65, 0.3 + BASE_Z)        # (-0.3, 1.25, 1.3)

# Hi-Hat
HIHAT_POS = (CX + 0.45, CY + 0.8, 0.65 + BASE_Z)           # (0.45, 1.4, 1.65)

# Ride
RIDE_STAND_BASE = (CX - 0.6, CY + 0.1)                     # (-0.6, 0.7)
RIDE_CYMBAL_POS = (CX - 0.5, CY + 0.4, 1.1 + BASE_Z)       # (-0.5, 1.0, 2.1)

# Crash
CRASH_STAND_BASE = (CX + 0.6, CY + 0.1)                    # (0.6, 0.7)
CRASH_CYMBAL_POS = (CX + 0.4, CY + 0.5, 1.1 + BASE_Z)      # (0.4, 1.1, 2.1)


# MIDI コード (v6 NOTE_TO_ACTION と整合)
HIHAT_CODES = (42, 46)
BASS_CODES = (36, 38)
RIDE_CODE = 53
CRASH_LIKE_CODES = (49, 51, 57)


# =============================================================================
# アニメーションヘルパー
# =============================================================================
def _key_cymbal_swing(objs, frame, velocity, max_deg=12.0):
    """シンバルのZ軸回転スイング(減衰振動)をキーフレーム化。

    Args:
        objs: アニメ対象のオブジェクトリスト (例: [Crash_Body, Crash_Boss])
    """
    amp = math.radians(min(max_deg, 2.0 + velocity * 0.18))
    decay = 0.84
    freq = 0.50
    n = 48

    for obj in objs:
        for i in range(n + 1):
            if i < n:
                val = amp * (decay ** i) * math.sin(freq * i)
            else:
                val = 0.0
            obj.rotation_euler[2] = val
            obj.keyframe_insert(data_path='rotation_euler', index=2, frame=frame + i)


def _key_ohh_open(objs, frame, velocity, max_gap=0.04, dur=15):
    """オープンハイハット: 上限(gap_max)まで開き、脚の動きに合わせて durフレームで閉じる。

    カーブ: gap(i) = gap_max * sin(pi * i / dur)
      i=0      -> 0        (クローズ位置)
      i=dur/2  -> gap_max  (上限)
      i=dur    -> 0        (クローズ位置)

    Args:
        objs: [HihatTop_Body, HihatTop_Boss]
    """
    gap_max = 0.03 + (max(0, min(127, velocity)) / 127.0) * (max_gap - 0.03)

    for obj in objs:
        base_z = obj.location[2]
        for i in range(dur + 1):
            g = gap_max * math.sin(math.pi * i / dur) if 0 < i < dur else 0.0
            obj.location[2] = base_z + g
            obj.keyframe_insert(data_path='location', index=2, frame=frame + i)


def _key_ohh_close(objs, frame):
    """クローズハイハット: 下限(クローズ位置)に固定。前のopenの残りを潰す。

    以降フレームはキーを打たず、このキーで base_z に保持される。
    """
    for obj in objs:
        base_z = obj.location[2]
        obj.location[2] = base_z
        obj.keyframe_insert(data_path='location', index=2, frame=frame)


def _key_bass_head(obj, frame, velocity):
    """バスドラ前方ヘッドの定在波振動（凸→凹→減衰）をShape Keyで表現。

    Shape Key "Dome" の value を
        value(t) = amp * e^(-lambda*t) * sin(omega*t)
    の減衰振動カーブでキーフレーム化し、
    打撃後にヘッドが凸→凹→（小さく凸）→平面収束の定在波で振動する。

    振幅(amp): velocity依存で 0.5〜1.0
    周期: ~5フレーム（omega = 2π/5）
    減衰: e^(-0.25*t) → 16フレームで振幅の~2%まで収束

    Args:
        obj: Bass_Head_Top オブジェクト（Shape Key "Dome" を持つ）
        frame: 開始フレーム
        velocity: MIDIベロシティ (0-127)
    """
    vel_norm = max(0, min(127, velocity)) / 127.0

    # 振幅係数（弱打0.5、強打1.0）
    amp = 0.5 + vel_norm * 0.5

    # 振動パラメータ
    omega = 2.0 * math.pi / 5.0   # 周期 ~5フレーム
    lam = 0.25                    # 減衰定数（16fで e^-4≈0.018）
    n = 16                        # キーフレーム総数（~3周期）

    dome_key = obj.data.shape_keys.key_blocks["Dome"]

    for i in range(n + 1):
        t = i
        value = amp * math.exp(-lam * t) * math.sin(omega * t)
        dome_key.value = value
        dome_key.keyframe_insert(data_path="value", frame=frame + i)

    # 最終フレームで完全に平面へ戻す（残留値をゼロに強制）
    dome_key.value = 0.0
    dome_key.keyframe_insert(data_path="value", frame=frame + n)

    bpy.context.view_layer.update()


# =============================================================================
# §11-3: ドラム円筒のスムージング
# =============================================================================
# 適用対象: Bass_/Snare_/Tom_/FloorTom_/Hihat/Crash_/Ride_/Pedal_/Stand_ 等の
#           ドラム部品メッシュ (cylinder / torus / sphere)。
# 手段   : bpy.ops.object.shade_smooth_by_angle (Blender 4.1+/5.x で利用可能)。
#           - 全ポリゴンを smooth にしながら、指定角度(30°)を越えるエッジは
#             ハードエッジとして保持（シェルとヘッド接合部、リム部など）。
#           - Blender 5.0 では mesh.use_auto_smooth は廃止されており、この
#             オペレーター（または GeometryNodeSmoothByAngle ノード）が正解。
# 注意   : Shape Key "Dome"（Bass_Head_Top）は頂点位置ベースなので、エッジマーキング
#           とは干渉しない。
_SMOOTH_PREFIXES = (
    'Bass_', 'Snare_', 'Tom_', 'FloorTom_', 'Hihat',
    'Crash_', 'Ride_', 'Pedal_', 'Stand_', 'TomMount_', 'Tom_HBar',
)


def _smooth_drum_meshes(angle_deg: float = 30.0) -> int:
    """全ドラムメッシュに平滑シェーディング＋角度ベースハードエッジを適用（§11-3）。"""
    targets = [o for o in bpy.context.scene.objects
               if o.type == 'MESH'
               and any(o.name.startswith(p) for p in _SMOOTH_PREFIXES)]
    if not targets:
        print("[drum_set_animator] no drum mesh to smooth")
        return 0

    angle_rad = math.radians(angle_deg)

    # shade_smooth_by_angle は選択ベースなので、対象をまとめて選択する
    bpy.ops.object.select_all(action='DESELECT')
    for o in targets:
        o.select_set(True)
    bpy.context.view_layer.objects.active = targets[0]

    try:
        bpy.ops.object.shade_smooth_by_angle(angle=angle_rad)
    except Exception as e:
        # フォールバック: フルスムーシー（円柱プリミティブでは見た目上十分）
        bpy.ops.object.shade_smooth()
        print(f"[drum_set_animator] (fallback to shade_smooth: {e})")

    bpy.ops.object.select_all(action='DESELECT')
    print(f"[drum_set_animator] smooth shading applied to {len(targets)} drum mesh(es) "
          f"(angle={angle_deg}°)")
    return len(targets)


def make_kick_pivot(pivot_ref_obj, moving_objs):
    """キックペダルの支点 Empty を1回だけ作成し、剛体をその子に付ける。

    支点は Pedal_HorizontalRod の世界位置に置く。剛体はワールド位置を保持する。

    Returns:
        支点 Empty
    """
    pivot = bpy.data.objects.new("Kick_SwingPivot", None)
    bpy.context.collection.objects.link(pivot)
    pivot.location = pivot_ref_obj.location
    pivot.rotation_euler = (0.0, 0.0, 0.0)

    for obj in moving_objs:
        # 子の世界位置（=現在親なしなのでローカル位置）を保存
        world_loc = obj.location.copy()
        obj.parent = pivot
        # 親の位置を引いて、正しいローカル位置を直接設定
        obj.location = world_loc - pivot.location
    return pivot


def _key_kick_pedal(pivot, frame, velocity, amp_deg=24.0):
    """キックペダル(アーム+ビーター)を支点周りでスウィングさせる。

    平行移動だと「伸び縮み」に見えるため、支点 Empty 周りの回転で踏み込みを表現する。

    Args:
        pivot: make_kick_pivot() が作った支点 Empty (親)
    """
    amp = math.radians(min(amp_deg, 8.0 + velocity * 0.14))
    n = 6

    # 支点周りのX軸回転でスウィング(ビーターがバスドラ方向(Y-)へ踏み込む→戻る)
    for i in range(n + 1):
        ang = amp * math.sin(math.pi * i / n)   # 0 → 最大踏み込み(バスドラ側) → 0
        pivot.rotation_euler = (ang, 0.0, 0.0)
        pivot.keyframe_insert(data_path='rotation_euler', index=0, frame=frame + i)
    pivot.rotation_euler = (0.0, 0.0, 0.0)
    pivot.keyframe_insert(data_path='rotation_euler', index=0, frame=frame + n)
    return pivot


# =============================================================================
# メイン: アニメ可ドラムセット生成
# =============================================================================
def build_animated_drum_set(events, frame_end=None):
    """個別化ドラムセットを生成し、MIDIイベントに反応する物理キーフレームを挿入する。

    Args:
        events: load_midi_drum_track() の戻り値 [{frame, code, velocity}, ...]
        frame_end: 上限フレーム(Noneなら10000)
    Returns:
        dict: 検証用に各アニメ対象オブジェクト
    """
    max_frame = int(frame_end) if frame_end else 10000

    # =====================================================================
    # 各パーツ生成（結合しない）
    # =====================================================================

    # --- Bass Drum ---
    bass_objs = create_bass_drum(location=BASS_POS)

    # --- Kick Pedal ---
    kick_pedal_objs = create_kick_pedal(location=KICK_PEDAL_POS)

    # --- Tom Mount Poles ---
    create_tom_mount_only(tom_radius_inch=10, location=TOM_MOUNT_POS, side="right", pole_length=0.3)
    create_tom_mount_only(tom_radius_inch=12, location=TOM_MOUNT_POS, side="left", pole_length=0.3)

    # --- 10" Tom (right) ---
    create_tom_tom(radius_inch=10, height_inch=8, location=TOM10_POS,
                   rotation=(math.radians(-15), 0, 0))

    # --- 12" Tom (left) ---
    create_tom_tom(radius_inch=12, height_inch=10, location=TOM12_POS,
                   rotation=(math.radians(-15), 0, 0))

    # --- H-bars ---
    create_tom_hbar(location=(CX + 0.125, CY + 0.2, _POLE_TOP_Z), rotation=(0, 0, 0), bar_length=0.18)
    create_tom_hbar(location=(CX - 0.15, CY + 0.2, _POLE_TOP_Z), rotation=(0, 0, 0), bar_length=0.20)

    # --- Snare Stand + Snare Drum ---
    create_snare_stand(location=SNARE_STAND_POS)
    create_snare_drum(radius_inch=14, depth_inch=6, location=SNARE_DRUM_POS)

    # --- Floor Tom ---
    create_floor_tom(16, 14, location=FLOOR_TOM_POS, ground_z=BASE_Z)

    # --- Hi-Hat ---
    hihat_objs = create_hihat(location=HIHAT_POS, pedal_angle_deg=60)

    # --- Ride Cymbal ---
    ride_objs = create_cymbal_with_stand(
        "Ride", 20, 0.005,
        stand_base_xy=RIDE_STAND_BASE,
        cymbal_location=RIDE_CYMBAL_POS,
        rotation=(0, 0, 0),
        stand_height=1.1, tilt_angle=-15)

    # --- Crash Cymbal ---
    crash_objs = create_cymbal_with_stand(
        "Crash", 16, 0.004,
        stand_base_xy=CRASH_STAND_BASE,
        cymbal_location=CRASH_CYMBAL_POS,
        rotation=(0, 0, 0),
        stand_height=1.2, tilt_angle=-20)

    # =====================================================================
    # アニメ対象の特定
    # =====================================================================
    handles = {}

    # Hi-Hat top cymbal (Body + Boss)
    hihat_top = [o for o in hihat_objs if o.name.startswith("HihatTop_")]
    if hihat_top:
        handles['ohh_top'] = hihat_top

    # Crash cymbal (Body + Boss)
    crash_cymbal = [o for o in crash_objs if o.name.startswith("Crash_")]
    if crash_cymbal:
        handles['crash'] = crash_cymbal

    # Ride cymbal (Body + Boss)
    ride_cymbal = [o for o in ride_objs if o.name.startswith("Ride_")]
    if ride_cymbal:
        handles['ride'] = ride_cymbal

    # Bass drum head top
    bass_head_top = [o for o in bass_objs if "Head_Top" in o.name]
    if bass_head_top:
        handles['bass_head'] = bass_head_top[0]

    # Kick pedal: moving = Arm + Beater, 支点Emptyは1回だけ作成して再利用
    kick_arm = [o for o in kick_pedal_objs if o.name in ("Pedal_Arm", "Pedal_BeaterBlock")]
    kick_pivot = [o for o in kick_pedal_objs if o.name == "Pedal_HorizontalRod"]
    if kick_arm and kick_pivot:
        kick_pivot_empty = make_kick_pivot(kick_pivot[0], kick_arm)
        handles['kick_pedal'] = kick_pivot_empty

    # =====================================================================
    # MIDIイベント → 物理キーフレーム
    # =====================================================================
    last = {'ohh': -9999, 'crash': -9999, 'ride': -9999, 'bass': -9999, 'kick': -9999}

    for ev in events:
        frame = int(ev['frame'])
        code = int(ev['note'])
        vel = int(ev.get('velocity', 80))
        if frame < 1 or frame > max_frame:
            continue

        if code in HIHAT_CODES and 'ohh_top' in handles:
            if frame - last['ohh'] < 2:
                continue
            last['ohh'] = frame
            if code == 46:
                # オープン: 脚に合わせて上限(gap)まで開閉 (15フレームカーブ)
                _key_ohh_open(handles['ohh_top'], frame, vel, max_gap=0.04, dur=15)
            else:
                # クローズ: 下限に固定 (前のopenの残りを潰す)
                _key_ohh_close(handles['ohh_top'], frame)

        elif code in CRASH_LIKE_CODES and 'crash' in handles:
            if frame - last['crash'] < 2:
                continue
            last['crash'] = frame
            _key_cymbal_swing(handles['crash'], frame, vel, max_deg=16.0)

        elif code == RIDE_CODE and 'ride' in handles:
            if frame - last['ride'] < 2:
                continue
            last['ride'] = frame
            _key_cymbal_swing(handles['ride'], frame, vel, max_deg=11.0)

        elif code in BASS_CODES:
            if frame - last['bass'] < 2:
                continue
            last['bass'] = frame
            if 'bass_head' in handles:
                _key_bass_head(handles['bass_head'], frame, vel)
            if 'kick_pedal' in handles:
                _key_kick_pedal(handles['kick_pedal'], frame, vel)

    # 補間をスムーズにする(キーフレーム全体をベジェ化)
    # keyframe_insert のデフォルトは既に BEZIER なので、これはオプションの補強。
    # Blender 5.0 の Action API は多層的なため、失敗しても無視する。
    try:
        for objs in handles.values():
            obj_list = objs if isinstance(objs, list) else [objs]
            for obj in obj_list:
                if obj.animation_data and obj.animation_data.action:
                    action = obj.animation_data.action
                    fcurves = []
                    if hasattr(action, 'layers') and action.layers:
                        for layer in action.layers:
                            for strip in layer.strips:
                                for cb in strip.channelbags:
                                    fcurves.extend(cb.fcurves)
                    elif hasattr(action, 'fcurves'):
                        fcurves = list(action.fcurves)
                    for fc in fcurves:
                        for kp in fc.keyframe_points:
                            kp.interpolation = 'BEZIER'
    except Exception as _be:
        print(f"[drum_set_animator] (補間更新をスキップ: {_be})")

    total = len(bass_objs) + len(hihat_objs) + len(ride_objs) + len(crash_objs)
    # §11-3: ドラム円筒部品の平滑シェーディングを適用（Shape Key "Dome" とは干渉しない）
    try:
        _smooth_drum_meshes(angle_deg=30.0)
    except Exception as _sm_e:
        print(f"[drum_set_animator] (smooth shading skipped: {_sm_e})")

    print(f"[drum_set_animator] built animated drum set: "
          f"ohh={'Y' if handles.get('ohh_top') else 'N'} "
          f"crash={'Y' if handles.get('crash') else 'N'} "
          f"ride={'Y' if handles.get('ride') else 'N'} "
          f"bass={'Y' if handles.get('bass_head') else 'N'} "
          f"kick={'Y' if handles.get('kick_pedal') else 'N'}")
    print(f"[drum_set_animator] bass center at {BASS_POS}")
    return handles


def remove_static_drum_set():
    """既存の結合済み(静的)ドラムセットを削除する。"""
    targets = [o for o in bpy.context.scene.objects
               if o.name == 'Drum_Set']
    if targets:
        bpy.ops.object.select_all(action='DESELECT')
        for o in targets:
            o.select_set(True)
        bpy.context.view_layer.objects.active = targets[0]
        bpy.ops.object.delete(use_global=False)
        print(f"[drum_set_animator] removed {len(targets)} static drum object(s)")
    else:
        print("[drum_set_animator] no static Drum_Set found to remove")


def clear_animated_drum():
    """前回生成したアニメ可ドラムセットの全オブジェクトを削除（再実行用）。"""
    prefixes = ['Bass_', 'Snare_', 'Tom_', 'FloorTom_', 'Hihat',
                'Crash_', 'Ride_', 'Pedal_', 'Stand_', 'TomMount_', 'Tom_HBar']
    to_delete = []
    for obj in bpy.context.scene.objects:
        # Empty(支点)とメッシュの両方を削除
        if any(obj.name.startswith(p) for p in prefixes) or obj.name == 'Kick_SwingPivot':
            to_delete.append(obj)

    if to_delete:
        bpy.ops.object.select_all(action='DESELECT')
        for obj in to_delete:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = to_delete[0]
        bpy.ops.object.delete(use_global=False)
        print(f"[drum_set_animator] cleared {len(to_delete)} animated drum objects")
    else:
        print("[drum_set_animator] no animated drum objects to clear")


# =============================================================================
# 直接実行: Blender テキストエディタから実行した場合のみドラムセットを生成する。
# 注意: import 時は絶対に実行しない（import 時にテストセットを生成・保存し、
#       setup_drum_in_blender.py 等の呼び出し側を汚染するバグを回避）。
# =============================================================================
def _run_standalone_test():
    print("[drum_set_animator] === 実行開始 ===")
    clear_animated_drum()
    _test_events = [
        {'frame': 10, 'note': 36, 'velocity': 100},   # Bass
        {'frame': 20, 'note': 42, 'velocity': 80},    # Closed HH
        {'frame': 30, 'note': 49, 'velocity': 90},    # Crash
        {'frame': 40, 'note': 53, 'velocity': 70},    # Ride
        {'frame': 50, 'note': 46, 'velocity': 85},    # Open HH
        {'frame': 60, 'note': 36, 'velocity': 95},    # Bass
        {'frame': 70, 'note': 42, 'velocity': 75},    # Closed HH
        {'frame': 80, 'note': 51, 'velocity': 88},    # Crash-like
    ]
    build_animated_drum_set(_test_events)
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "drum_set_animated.blend")
    bpy.ops.wm.save_mainfile(filepath=output_path)
    print(f"[drum_set_animator] .blendファイルを保存しました: {output_path}")
    print("[drum_set_animator] === 実行完了 ===")
    print("[drum_set_animator] タイムラインを 10〜80 frame までスクラブして確認してください")


if __name__ == "__main__":
    try:
        _run_standalone_test()
    except Exception as e:
        print(f"[drum_set_animator] *** 実行エラー: {type(e).__name__}: {e} ***")
        import traceback
        traceback.print_exc()
        raise
