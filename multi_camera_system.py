"""
Multi-Camera System
===================
JSON駆動の複数カメラ切り替えシステム。

- JSON の `cameras` セクションでカメラ定義（位置/角度/レンズ/パンチ）
- JSON の `shots` セクションでフレーム範囲ごとのカメラ切替
- 旧形式（配列のみ `[{cam, start, end}, ...]`）も後方互換で読取
- 微動(角度sin波) + ドラムパンチを各カメラにキーフレーム
- frame_change_post handler で scene.camera を切替

Usage:
    from multi_camera_system import build_multi_camera_system
    build_multi_camera_system(
        drum_events=drum_events,
        frame_end=scene_end,
        midi_bpm=midi_bpm,
        center=drummer_center,
        shots_json_path="shots_sample.json",
    )
"""

import bpy
import json
import math
import os
import sys
from dataclasses import dataclass
from typing import List, Optional, Tuple

# 確保: WORKSPACE が sys.path にあるか
_WORKSPACE = os.path.dirname(os.path.abspath(__file__))
if _WORKSPACE not in sys.path:
    sys.path.insert(0, _WORKSPACE)

# =====================================================================
# Defaults (JSON未指定時のフォールバック)
# =====================================================================

DEFAULT_CAMERAS = {
    "Cam_Wide": {
        'angle_center_deg': -90.0,
        'swing_half_deg':   5.0,
        'height_offset':    -0.8,
        'radius':           12.0,
        'lens_mm':          24.0,
        'punch_scale':      0.3,
        'zoom_depth':       0.05,       # ±5% lens variation
        'zoom_period_beats': 32.0,      # 32 beats per full zoom cycle
    },
    "Cam_Medium": {
        'angle_center_deg': -45.0,
        'swing_half_deg':   4.0,
        'height_offset':    -1.2,
        'radius':           8.0,
        'lens_mm':          35.0,
        'punch_scale':      0.5,
        'zoom_depth':       0.08,       # ±8% lens variation
        'zoom_period_beats': 16.0,      # 16 beats per full zoom cycle
    },
    "Cam_Close": {
        'angle_center_deg': -90.0,
        'swing_half_deg':   2.0,
        'height_offset':    -1.5,
        'radius':           4.0,
        'lens_mm':          65.0,
        'punch_scale':      0.8,
        'zoom_depth':       0.10,       # ±10% lens variation
        'zoom_period_beats': 8.0,       # 8 beats per full zoom cycle
    },
    "Cam_OverShoulder": {
        'angle_center_deg': -135.0,
        'swing_half_deg':   3.0,
        'height_offset':    -0.5,
        'radius':           6.0,
        'lens_mm':          45.0,
        'punch_scale':      0.4,
        'zoom_depth':       0.06,       # ±6% lens variation
        'zoom_period_beats': 32.0,      # 32 beats per full zoom cycle
    },
    "Cam_Top": {
        'angle_center_deg': -90.0,
        'swing_half_deg':   8.0,
        'height_offset':    3.0,
        'radius':           7.0,
        'lens_mm':          30.0,
        'punch_scale':      0.2,
        'zoom_depth':       0.03,       # ±3% lens variation
        'zoom_period_beats': 64.0,      # 64 beats per full zoom cycle
    },
}

FOCUS_NAME = "MultiCam_Focus"
DOF_FSTOP = 2.8


@dataclass
class CameraShot:
    """1ショットの定義.

    - フレーム指定 (旧形式): start_frame / end_frame を直接指定
    - 小節指定 (新形式): measure = このショットが「開始する小節」(1始まり)。
      start/end は build_multi_camera_system() が frames_per_measure と
      全曲小節数(total_measures)を使ってフレームに展開する。
    """
    cam_name: str
    start_frame: int = 0
    end_frame: int = 0
    measure: Optional[int] = None   # None ならフレーム指定(旧形式)


# =====================================================================
# JSON 読取
# =====================================================================

def load_camera_config(json_path: Optional[str] = None) -> Tuple[dict, List[CameraShot]]:
    """JSONからカメラ定義 + ショットリストを読み取る。

    新形式 (2層):
        {
          "cameras": { "Cam_Wide": {...}, ... },
          "shots":   [ {"cam":"Cam_Wide","start":1,"end":960}, ... ]
        }

    旧形式 (配列のみ):
        [ {"cam":"Cam_Wide","start":1,"end":960}, ... ]

    Returns:
        (cameras_dict, shots_list)
        cameras_dict: {name: preset_dict} — JSON未記載のカメラは DEFAULT_CAMERAS から補完
        shots_list:   sorted List[CameraShot]
    """
    cameras = dict(DEFAULT_CAMERAS)  # フォールバック既定
    shots: List[CameraShot] = []

    if not json_path or not os.path.exists(json_path):
        # JSON未指定: 既定カメラのみ、ショットなし (自動生成は呼び出し側)
        print("  [MULTI-CAM] No JSON specified, using DEFAULT_CAMERAS")
        return cameras, shots

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 旧形式: 配列
    if isinstance(data, list):
        print(f"  [MULTI-CAM] Legacy array format: {len(data)} shots")
        for s in data:
            shots.append(CameraShot(
                cam_name=s["cam"],
                start_frame=int(s["start"]),
                end_frame=int(s["end"]),
            ))
        # 旧形式では JSON にカメラ定義が無いため、ショットに参照された名前は既定値を使用
        used_cams = {s.cam_name for s in shots}
        for name in used_cams:
            if name not in cameras:
                print(f"  [MULTI-CAM][WARN] '{name}' not in DEFAULT_CAMERAS, using Cam_Wide preset")
                cameras[name] = dict(DEFAULT_CAMERAS.get("Cam_Wide", DEFAULT_CAMERAS[list(DEFAULT_CAMERAS.keys())[0]]))
    # 新形式: dict
    elif isinstance(data, dict):
        # cameras セクション
        if "cameras" in data and isinstance(data["cameras"], dict):
            for name, preset in data["cameras"].items():
                cameras[name] = preset
            print(f"  [MULTI-CAM] Loaded {len(data['cameras'])} camera definitions from JSON")
        # shots セクション
        if "shots" in data and isinstance(data["shots"], list):
            for s in data["shots"]:
                cam = s["cam"]
                # 新形式: "measure" 指定 (小節数で切替制御)
                if "measure" in s:
                    shots.append(CameraShot(
                        cam_name=cam,
                        measure=int(s["measure"]),
                    ))
                # 旧形式: "start" / "end" フレーム指定
                elif "start" in s and "end" in s:
                    shots.append(CameraShot(
                        cam_name=cam,
                        start_frame=int(s["start"]),
                        end_frame=int(s["end"]),
                    ))
                else:
                    print(f"  [MULTI-CAM][WARN] Shot entry missing 'measure' or 'start/end': {s}")
            # ショットに参照されたが cameras に無い名前は既定値で補完
            used_cams = {s.cam_name for s in shots}
            for name in used_cams:
                if name not in cameras:
                    print(f"  [MULTI-CAM][WARN] Shot references '{name}' but no definition found; "
                          f"falling back to Cam_Wide preset")
                    cameras[name] = dict(DEFAULT_CAMERAS.get("Cam_Wide", {}))
            print(f"  [MULTI-CAM] Loaded {len(shots)} shots from JSON")
        else:
            print("  [MULTI-CAM] No 'shots' section in JSON")
    else:
        raise ValueError(f"Unsupported JSON format: {type(data).__name__}")

    shots.sort(key=lambda s: s.start_frame)
    return cameras, shots


# =====================================================================
# Internal helpers
# =====================================================================

def _focus_empty(center) -> bpy.types.Object:
    """共通フォーカスEmptyを生成/取得."""
    existing = bpy.data.objects.get(FOCUS_NAME)
    if existing:
        return existing
    focus = bpy.data.objects.new(FOCUS_NAME, None)
    focus.empty_display_size = 0.15
    focus.empty_display_type = 'PLAIN_AXES'
    focus.location = (center.x, center.y - 0.55, 1.80)
    bpy.context.scene.collection.objects.link(focus)
    return focus


def _keyframe_camera_motion(cam, center, preset, shot_start, shot_end,
                            frames_per_beat, drum_events, punch_scale):
    """カメラのショット範囲内に微動sin波 + ドラムパンチ + ズーム(sin波)のキーフレームを挿入."""
    swing_center = math.radians(preset['angle_center_deg'])
    swing_half = math.radians(preset['swing_half_deg'])
    radius = preset['radius']
    height = preset['height_offset']
    base_lens = preset.get('lens_mm', 35.0)
    punch_frames = max(2, int(round(4.0 * frames_per_beat)))  # 4拍で減衰

    # 微動周期: 既定16拍で1往復 (JSON preset の swing_period_beats で上書き可)
    swing_period_beats = float(preset.get('swing_period_beats', 16.0))
    swing_period_frames = swing_period_beats * frames_per_beat

    # ズーム設定
    zoom_depth = preset.get('zoom_depth', 0.0)
    zoom_period_beats = preset.get('zoom_period_beats', 32.0)
    zoom_period_frames = zoom_period_beats * frames_per_beat

    def _angle_at(frame):
        # 絶対フレーム基準の位相 → 2回目以降の登場時に「既に動いている」ように見える
        phase = 2.0 * math.pi * frame / swing_period_frames
        return swing_center + swing_half * math.sin(phase)

    def _pos_at(frame, r, h):
        th = _angle_at(frame)
        return (
            center.x + r * math.cos(th),
            center.y + r * math.sin(th),
            center.z + h,
        )

    def _lens_at(frame):
        """sin波によるレンズ焦点距離変化 (zoom_depth=0なら固定).
        絶対フレーム基準の位相 → 切替時にズームの途中から見える."""
        if zoom_depth <= 0.0:
            return base_lens
        phase = 2.0 * math.pi * frame / zoom_period_frames
        return base_lens * (1.0 + zoom_depth * math.sin(phase))

    if cam.animation_data is None:
        cam.animation_data_create()

    # [PERF] 全フレームキーフレームはメモリ枯渇でBlenderクラッシュする。
    # → 4拍間隔のベース + ドラムパンチ/回復フレームのみキーフレーム。
    #   BEZIER補間で滑らかな曲線になる。
    frame_data = {}  # frame -> (radius, lens)

    # 微動ベース: 4拍間隔 + ショット先頭/末尾
    interval = max(1, int(round(frames_per_beat * 4)))
    for fr in range(shot_start, shot_end + 1, interval):
        frame_data[fr] = (radius, _lens_at(fr))
    frame_data[shot_start] = (radius, _lens_at(shot_start))
    frame_data[shot_end] = (radius, _lens_at(shot_end))

    # ドラムパンチ: hitで外側→回復
    if drum_events:
        for ev in drum_events:
            hit = max(1, int(round(ev['frame'])))
            if hit < shot_start or hit > shot_end:
                continue
            vel = ev.get('velocity', 96) / 127.0
            punch_r = radius * (1.0 + 0.3 * punch_scale * vel)
            frame_data[hit] = (punch_r, _lens_at(hit))
            fr_back = min(shot_end, hit + punch_frames)
            if fr_back > hit:
                frame_data[fr_back] = (radius, _lens_at(fr_back))

    # キーフレームをソート順に挿入
    for fr in sorted(frame_data.keys()):
        r, lens_val = frame_data[fr]
        px, py, pz = _pos_at(fr, r, height)
        cam.location = (px, py, pz)
        cam.keyframe_insert(data_path='location', frame=fr)
        if zoom_depth > 0.0:
            cam.data.lens = lens_val
            cam.data.keyframe_insert(data_path='lens', frame=fr)

    print(f"  [KEYFRAME] {cam.name}: {len(frame_data)} kf "
          f"(shot {shot_start}-{shot_end}, interval={interval}f)")

    # BEZIER 補間 (location + lens)
    if cam.animation_data.action:
        act = cam.animation_data.action
        try:
            for layer in act.layers:
                for lstrip in layer.strips:
                    for cb in lstrip.channelbags:
                        for fc in cb.fcurves:
                            if fc.data_path in ('location', 'location.x', 'location.y',
                                                'location.z', 'lens'):
                                for kp in fc.keyframe_points:
                                    kp.interpolation = 'BEZIER'
        except (AttributeError, TypeError):
            pass


def _iter_scene_camera_fcurves(scene):
    """scene.action の camera F-Curve をイテレート (Blender 4.x/5.0 両対応)."""
    ad = scene.animation_data
    if ad is None or ad.action is None:
        return
    act = ad.action
    # 旧API (Blender 4.0-4.3): action.fcurves
    try:
        if act.fcurves:
            for fc in act.fcurves:
                if fc.data_path == "camera":
                    yield fc
            return
    except (AttributeError, TypeError):
        pass
    # 新API (Blender 4.4+/5.0): layers/strips/channelbags
    try:
        for layer in act.layers:
            for strip in layer.strips:
                for cb in strip.channelbags:
                    for fc in cb.fcurves:
                        if fc.data_path == "camera":
                            yield fc
    except (AttributeError, TypeError):
        pass


def _set_camera_fcurve_constant(scene):
    """scene.camera の F-Curve を全キーフレーム CONSTANT 補間に設定."""
    for fc in _iter_scene_camera_fcurves(scene):
        for kp in fc.keyframe_points:
            kp.interpolation = 'CONSTANT'


def _count_camera_fcurve_keys(scene) -> int:
    """scene.camera の F-Curve キーフレーム数をカウント."""
    n = 0
    for fc in _iter_scene_camera_fcurves(scene):
        n += len(fc.keyframe_points)
    return n


def _register_camera_switch_handler(shot_list: List[CameraShot],
                                     frame_end: int = 0):
    """frame_change_post handler + scene.camera キーフレームでカメラ切替を確立する。

    - GUI スラブ/プレビュー: frame_change_post ハンドラ
    - GUI レンダリング / 別プロセス / CLI: scene.camera キーフレーム（データ）
    """
    scene = bpy.context.scene

    # --- 既存handlerを削除 (重複防止) ---
    for fn in list(bpy.app.handlers.frame_change_post):
        if getattr(fn, '_multi_cam_switch', False):
            bpy.app.handlers.frame_change_post.remove(fn)

    # --- シーンプロパティに保存 ---
    shot_json = json.dumps([
        {"cam": s.cam_name, "start": s.start_frame, "end": s.end_frame}
        for s in shot_list
    ])
    scene["multi_cam_shots"] = shot_json

    # --- テキストブロックにも保存 (.blend同梱) ---
    if "MultiCam_ShotList" in bpy.data.texts:
        bpy.data.texts.remove(bpy.data.texts["MultiCam_ShotList"])
    txt = bpy.data.texts.new("MultiCam_ShotList")
    txt.write(shot_json)

    # =========================================================
    # [A] frame_change_post ハンドラ (GUIスクラブ/プレビュー用)
    # =========================================================
    def _switch(sc, depsgraph=None):
        try:
            frame = sc.frame_current
            shots = json.loads(sc.get("multi_cam_shots", "[]"))
            for s in shots:
                if s["start"] <= frame <= s["end"]:
                    target = bpy.data.objects.get(s["cam"])
                    if target and sc.camera != target:
                        sc.camera = target
                    break
            else:
                if shots:
                    target = bpy.data.objects.get(shots[0]["cam"])
                    if target and sc.camera != target:
                        sc.camera = target
        except Exception:
            pass

    _switch._multi_cam_switch = True
    bpy.app.handlers.frame_change_post.append(_switch)

    # =========================================================
    # [B] scene.camera は animatable なプロパティではないため、
    #     キーフレームによる切替は不可能。
    #     frame_change_post ハンドラのみで切替を行う。
    # =========================================================
    if not shot_list:
        print("  [MULTI-CAM] No shots defined, handler will use first camera as default")
        return _switch

    # 最初のショットのカマラを初期値として設定
    first_cam = bpy.data.objects.get(shot_list[0].cam_name)
    if first_cam:
        scene.camera = first_cam

    print(f"  [MULTI-CAM] Handler registered (frame_change_post)")
    print(f"  [MULTI-CAM] NOTE: scene.camera is NOT animatable in Blender.")
    print(f"  [MULTI-CAM] Camera switching is handled by the Python handler at runtime.")
    print(f"  [MULTI-CAM] → Render within the same Blender session (Ctrl+F12).")
    return _switch


# =====================================================================
# Public API
# =====================================================================

def build_multi_camera_system(drum_events, frame_end, midi_bpm=None,
                              center=None, shots_json_path=None,
                              skip_frame_set=False,
                              total_measures=None):
    """マルチカメラシステムを構築。

    Args:
        drum_events:  MIDIドラムイベントリスト (dict: note/action/velocity/frame)
        frame_end:    シーン最終フレーム
        midi_bpm:     BPM (Noneなら推定 — 呼び出し側が既に計算済みの値を渡す推奨)
        center:       ドラマー中心 mathutils.Vector (外部から渡す)
        shots_json_path: JSONファイルパス (Noneなら4小節等分割で自動生成)
        skip_frame_set: Trueなら末尾の frame_set(1) をスキップ (メモリ節約)
        total_measures: MIDI全曲小節数 (小節形式のshots展開に使用)
    """
    # タイムラインは 60fps 前提 (drummer_lipsync_unified.py と統一)
    # scene.render.fps に依存しない: 24fps等設定で周期が2.5倍速くなる不具合を防止
    fps = 60.0

    # --- [1] 既存カメラを削除 ---
    for obj in list(bpy.data.objects):
        if obj.type == 'CAMERA':
            try:
                data = obj.data
                bpy.data.objects.remove(obj, do_unlink=True)
                if data:
                    bpy.data.cameras.remove(data)
            except Exception as e:
                print(f"  [MULTI-CAM] camera remove warn: {e}")

    # 既存フォーカスEmptyも削除
    old_focus = bpy.data.objects.get(FOCUS_NAME)
    if old_focus:
        bpy.data.objects.remove(old_focus, do_unlink=True)

    # --- [2] ドラマー中心 ---
    if center is None:
        raise ValueError("center parameter is required (mathutils.Vector)")

    # --- [3] BPM計算 ---
    if midi_bpm and midi_bpm > 0:
        bpm = float(midi_bpm)
    else:
        bpm = 120.0
    sec_per_beat = 60.0 / bpm
    frames_per_beat = sec_per_beat * fps
    frames_per_measure = int(frames_per_beat * 4)  # 4/4拍

    # --- [4] ショットリスト取得 ---
    cameras, shot_list = load_camera_config(shots_json_path)

    # --- [4.5] 小節形式 → フレーム展開 ---
    # measure 指定のショットを frames_per_measure + total_measures でフレームに展開
    if any(s.measure is not None for s in shot_list):
        if total_measures is None or total_measures < 1:
            # total_measures 未指定時: frame_end から逆算
            estimated = max(1, int(frame_end / frames_per_measure))
            print(f"  [MULTI-CAM] total_measures not provided, estimated from frame_end: {estimated}")
            total_measures = estimated

        # measure を昇順にソート
        shot_list.sort(key=lambda s: s.measure if s.measure is not None else 999999)

        for i, s in enumerate(shot_list):
            if s.measure is None:
                continue  # フレーム指定のショットはそのまま
            # このショットの開始フレーム
            s.start_frame = (s.measure - 1) * frames_per_measure + 1
            # 終了フレーム = 次ショットの開始前 (最後は frame_end)
            if i + 1 < len(shot_list) and shot_list[i + 1].measure is not None:
                next_start = (shot_list[i + 1].measure - 1) * frames_per_measure + 1
                s.end_frame = next_start - 1
            else:
                s.end_frame = int(frame_end)
            # クランプ: シーン範囲内
            s.start_frame = max(1, s.start_frame)
            s.end_frame = min(int(frame_end), s.end_frame)

        # 展開後、フレーム指定のショットとも混在する場合に start_frame で再ソート
        shot_list.sort(key=lambda s: s.start_frame)
        print(f"  [MULTI-CAM] Expanded {sum(1 for s in shot_list if s.measure is not None)} "
              f"measure-based shots to frames (total_measures={total_measures}, "
              f"frames_per_measure={frames_per_measure})")

    if not shot_list:
        # 自動生成: cameras の順で4小節ずつ循環
        cam_names = list(cameras.keys())
        shot_length = frames_per_measure * 4  # 4小節
        frame = 1
        i = 0
        while frame <= frame_end:
            cam = cam_names[i % len(cam_names)]
            end = min(frame_end, frame + shot_length - 1)
            shot_list.append(CameraShot(cam, frame, end))
            frame = end + 1
            i += 1
        shot_list.sort(key=lambda s: s.start_frame)
        print(f"  [MULTI-CAM] Auto-generated {len(shot_list)} shots "
              f"({shot_length} frames each, 4/4 measures)")

    # --- [5] フォーカスEmpty生成 ---
    focus = _focus_empty(center)

    # --- [6] カメラ生成 ---
    cameras_objs = []
    for cam_name, preset in cameras.items():
        cam_data = bpy.data.cameras.new(cam_name)
        cam_data.lens = preset.get('lens_mm', 35.0)
        cam_data.dof.use_dof = True
        cam_data.dof.focus_object = focus
        try:
            cam_data.dof.aperture_fstop = DOF_FSTOP
        except Exception:
            pass

        cam = bpy.data.objects.new(cam_name, cam_data)
        bpy.context.scene.collection.objects.link(cam)

        # Track To
        con = cam.constraints.new('TRACK_TO')
        con.target = focus
        con.track_axis = 'TRACK_NEGATIVE_Z'
        con.up_axis = 'UP_Y'

        cameras_objs.append(cam)

        # ショット範囲を検索
        cam_shots = [s for s in shot_list if s.cam_name == cam_name]
        if cam_shots:
            for shot in cam_shots:
                _keyframe_camera_motion(
                    cam, center, preset,
                    shot.start_frame, shot.end_frame,
                    frames_per_beat, drum_events,
                    preset.get('punch_scale', 0.5),
                )
            _zd = preset.get('zoom_depth', 0.0)
            _zp = preset.get('zoom_period_beats', 32.0)
            print(f"  [MULTI-CAM] {cam_name}: {len(cam_shots)} shots, "
                  f"lens={preset.get('lens_mm', 35.0)}mm, "
                  f"r={preset.get('radius', 8.0)}m, "
                  f"ang={preset.get('angle_center_deg', -90.0)}°"
                  f"±{preset.get('swing_half_deg', 4.0)}°"
                  + (f", zoom=±{_zd:.0%}/{_zp:.0f}beats" if _zd > 0.0 else ""))
        else:
            # ショットリストにないカメラ: 静止配置 (+ズームは適用)
            th = math.radians(preset.get('angle_center_deg', -90.0))
            r = preset.get('radius', 8.0)
            h = preset.get('height_offset', -1.0)
            cam.location = (
                center.x + r * math.cos(th),
                center.y + r * math.sin(th),
                center.z + h,
            )
            # 静止カメラにもズームsin波を適用 (4拍間隔でキー)
            zoom_depth = preset.get('zoom_depth', 0.0)
            if zoom_depth > 0.0:
                base_lens = preset.get('lens_mm', 35.0)
                z_period_beats = preset.get('zoom_period_beats', 32.0)
                z_period_frames = z_period_beats * frames_per_beat
                if cam.data.animation_data is None:
                    cam.data.animation_data_create()
                z_interval = max(1, int(round(frames_per_beat * 4)))
                for fr in range(1, int(frame_end) + 1, z_interval):
                    phase = 2.0 * math.pi * (fr - 1) / z_period_frames
                    cam.data.lens = base_lens * (1.0 + zoom_depth * math.sin(phase))
                    cam.data.keyframe_insert(data_path='lens', frame=fr)
                cam.data.lens = base_lens * (1.0 + zoom_depth * math.sin(2.0 * math.pi * (int(frame_end) - 1) / z_period_frames))
                cam.data.keyframe_insert(data_path='lens', frame=int(frame_end))
            print(f"  [MULTI-CAM] {cam_name}: no shots assigned, static"
                  + (f" (zoom ±{zoom_depth:.0%})" if zoom_depth > 0.0 else ""))

    # --- [7] 初期カメラ = 最初のショットのカメラ ---
    if shot_list:
        first_cam = bpy.data.objects.get(shot_list[0].cam_name)
        if first_cam:
            bpy.context.scene.camera = first_cam

    # --- [8] frame_change handler + scene.camera キーフレーム ---
    _register_camera_switch_handler(shot_list, frame_end=int(frame_end))

    # --- [9] frame_set(1) で handler 発火 ---
    if skip_frame_set:
        print(f"  [MULTI-CAM] frame_set(1) skipped (skip_frame_set=True)")
    else:
        bpy.context.scene.frame_set(1)

    print(f"\n  [MULTI-CAM] === {len(cameras)}-camera system built ===")
    print(f"  [MULTI-CAM] BPM={bpm:.1f}, {frames_per_beat:.0f} frames/beat, "
          f"FPS={fps}")
    print(f"  [MULTI-CAM] Shots: {len(shot_list)}")
    for s in shot_list[:12]:
        print(f"    {s.start_frame:>5d} - {s.end_frame:>5d} : {s.cam_name}")
    if len(shot_list) > 12:
        print(f"    ... ({len(shot_list) - 12} more)")
    print(f"  [MULTI-CAM] Handler registered (frame_change_post)")
    return cameras_objs


# =====================================================================
# [ZOOM CAM] 固定角度カメラ + ドラムパンチ駆動レンズズーム (後退なし)
# =====================================================================

def build_beat_reactive_camera(drum_events, frame_end, midi_bpm=None,
                               center=None, settings=None):
    """パンチ時、カメラ後退なしでレンズ焦点距離を拡大して「遠退き」を表現。

    - 位置: 固定 (半径・角度・高さすべて一定)
    - ズーム: hitフレームで lens *= (1 + zoom_max), punch_beats で減衰
    - 可変周期ズーム (zoom_period_beats) で自然な息遣い

    Args:
        drum_events: MIDIドラムイベントリスト
        frame_end: シーン最終フレーム
        midi_bpm: BPM (Noneなら120)
        center: ドラマー中心 mathutils.Vector
        settings: 上書き辞書 (base_lens_mm, zoom_max, punch_beats, ...)
    Returns:
        bpy.types.Object (カメラオブジェクト)
    """
    if settings is None:
        settings = {}

    base_lens   = float(settings.get('base_lens_mm', 28.0))
    zoom_max    = float(settings.get('zoom_max', 0.12))
    punch_beats = float(settings.get('punch_beats', 4.0))
    zoom_period_beats = float(settings.get('zoom_period_beats', 32.0))
    radius      = float(settings.get('radius', 10.0))
    height_off  = float(settings.get('height_offset', -1.5))
    ang_deg     = float(settings.get('angle_center_deg', -90.0))
    cam_name    = str(settings.get('cam_name', 'ZoomCam'))
    focus_name  = str(settings.get('focus_name', 'ZoomCam_Focus'))
    dof_fstop   = float(settings.get('dof_aperture', 1.4))

    fps = 60.0  # 60fps前提 (drummer timeline と統一)

    if center is None:
        raise ValueError("center parameter is required (mathutils.Vector)")

    # --- [1] 既存カメラ/フォーカスEmptyを削除 ---
    for obj in list(bpy.data.objects):
        if obj.type == 'CAMERA':
            data = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if data:
                bpy.data.cameras.remove(data)
    for obj in list(bpy.data.objects):
        if obj.name in (focus_name, FOCUS_NAME):
            bpy.data.objects.remove(obj, do_unlink=True)

    # --- [2] フォーカスEmpty ---
    focus = bpy.data.objects.new(focus_name, None)
    focus.empty_display_size = 0.15
    focus.empty_display_type = 'PLAIN_AXES'
    focus.location = (center.x, center.y - 0.55, 1.80)
    bpy.context.scene.collection.objects.link(focus)

    # --- [3] カメラ (固定位置) ---
    cam_data = bpy.data.cameras.new(cam_name)
    cam_data.lens = base_lens
    cam_data.dof.use_dof = True
    cam_data.dof.focus_object = focus
    try:
        cam_data.dof.aperture_fstop = dof_fstop
    except Exception:
        pass

    cam = bpy.data.objects.new(cam_name, cam_data)
    bpy.context.scene.collection.objects.link(cam)

    con = cam.constraints.new('TRACK_TO')
    con.target = focus
    con.track_axis = 'TRACK_NEGATIVE_Z'
    con.up_axis = 'UP_Y'

    bpy.context.scene.camera = cam

    # --- [4] 固定位置 (全フレーム同一) ---
    th = math.radians(ang_deg)
    cam.location = (
        center.x + radius * math.cos(th),
        center.y + radius * math.sin(th),
        center.z + height_off,
    )
    cam.keyframe_insert(data_path='location', frame=1)

    # --- [5] ズームキーフレーム ---
    if midi_bpm and midi_bpm > 0:
        bpm = float(midi_bpm)
    else:
        bpm = 120.0
    frames_per_beat = (60.0 / bpm) * fps
    punch_frames = max(2, int(round(punch_beats * frames_per_beat)))
    zoom_period_frames = zoom_period_beats * frames_per_beat

    if cam.data.animation_data is None:
        cam.data.animation_data_create()

    # [5a] 4拍間隔の基本ズームsin波 (全フレームはメモリ枯渇→クラッシュ)
    z_interval = max(1, int(round(frames_per_beat * 4)))
    for fr in range(1, int(frame_end) + 1, z_interval):
        phase = 2.0 * math.pi * (fr - 1) / zoom_period_frames
        cam.data.lens = base_lens * (1.0 + zoom_max * math.sin(phase))
        cam.data.keyframe_insert(data_path='lens', frame=fr)
    # 末尾フレームも確実に
    fr_end = int(frame_end)
    if fr_end % z_interval != 0:
        phase_end = 2.0 * math.pi * (fr_end - 1) / zoom_period_frames
        cam.data.lens = base_lens * (1.0 + zoom_max * math.sin(phase_end))
        cam.data.keyframe_insert(data_path='lens', frame=fr_end)

    # [5b] ドラムパンチ: hitでズーム最大、punch後で基本値
    if drum_events:
        for ev in drum_events:
            hit = max(1, int(round(ev['frame'])))
            if hit > int(frame_end):
                continue
            vel = ev.get('velocity', 96) / 127.0
            punch_lens = base_lens * (1.0 + zoom_max * vel)
            cam.data.lens = punch_lens
            cam.data.keyframe_insert(data_path='lens', frame=hit)
            fr_back = min(int(frame_end), hit + punch_frames)
            phase_back = 2.0 * math.pi * (fr_back - 1) / zoom_period_frames
            cam.data.lens = base_lens * (1.0 + zoom_max * math.sin(phase_back))
            cam.data.keyframe_insert(data_path='lens', frame=fr_back)

    # [5c] BEZIER補間
    if cam.data.animation_data.action:
        act = cam.data.animation_data.action
        try:
            for layer in act.layers:
                for lstrip in layer.strips:
                    for cb in lstrip.channelbags:
                        for fc in cb.fcurves:
                            if fc.data_path in ('lens', 'lens.x'):
                                for kp in fc.keyframe_points:
                                    kp.interpolation = 'BEZIER'
        except (AttributeError, TypeError):
            pass

    print(f"  [ZOOM-CAM] created '{cam_name}' (fixed position, lens-driven punch)")
    print(f"  [ZOOM-CAM] lens={base_lens}mm base, zoom_max=+{zoom_max:.0%}, "
          f"punch={punch_beats}beats, period={zoom_period_beats}beats")
    print(f"  [ZOOM-CAM] pos=({cam.location.x:.2f},{cam.location.y:.2f},"
          f"{cam.location.z:.2f}) angle={ang_deg}°")
    print(f"  [ZOOM-CAM] BPM={bpm:.1f}, {frames_per_beat:.0f} frames/beat, "
          f"punch={punch_frames} frames")
    print(f"  [ZOOM-CAM] punch on {len(drum_events)} drum hits (lens zoom, NO camera retract)")
    return cam


def build_zoom_camera(drum_events, frame_end, midi_bpm=None, center=None,
                      settings=None):
    """build_beat_reactive_camera の別名 (後方互換/明示的呼び出し用)."""
    return build_beat_reactive_camera(
        drum_events, frame_end,
        midi_bpm=midi_bpm, center=center, settings=settings
    )
