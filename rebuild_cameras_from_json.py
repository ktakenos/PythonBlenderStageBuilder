"""
Camera Rebuild from JSON
========================
.blend を開いた状態で実行すると、JSONからカメラ定義を読み直して
カメラだけ再構築する。フルビルド不要。

前提:
  - drummer_lipsync_unified.py が一度だけ実行済み（シーンプロパティに
    drum_events_json / midi_bpm / cam_scene_end が保存済み）
  - shots_sample.json (または別のJSON) が同フォルダにある

Usage (Blender GUI):
  1. final_output.blend を開く
  2. Scripting → Open → rebuild_cameras_from_json.py → Run Script
  3. コンソールに "[DONE] Camera rebuilt + saved" が出る
  4. Ctrl+F12 でレンダリング確認

オプション:
  上部の SHOTS_JSON を別のJSONパスに変更すれば
  別のカメラ構成をテストできる。

[IMPORTANT]
  本スクリプトは Blender GUI (Run Script) で実行することを想定している。
  raise SystemExit / sys.exit を使用すると、Blender 本体に埋め込まれた
  Python インタープリターが Py_FinalizeEx を実行し Blender 自体が
  クラッシュする。そのため、エラー時は一律 return で関数を抜ける。
"""
import bpy
import json
import os
import shutil
import sys

# =====================================================
# 設定
# =====================================================
SHOTS_JSON = "shots_sample.json"  # ← 変更したいJSONファイルを指定


def _resolve_workspace():
    """Blender Scripting タブ実行時に __file__ が不安定なため、
    bpy.data.filepath (開いている .blend の場所) を優先して作業ディレクトリを解決する."""
    candidates = []

    # [優先1] bpy.data.filepath → .blend の親ディレクトリ
    try:
        blend_path = bpy.data.filepath
        if blend_path and os.path.isfile(blend_path):
            candidates.append(os.path.dirname(os.path.abspath(blend_path)))
        elif blend_path and os.path.isdir(blend_path):
            candidates.append(os.path.abspath(blend_path))
    except Exception:
        pass

    # [優先2] __file__ の親ディレクトリ (従来ロジック)
    try:
        wf = os.path.dirname(os.path.abspath(__file__))
        # blendファイル名が混入していないかチェック
        if not os.path.basename(wf).endswith('.blend') and os.path.isdir(wf):
            candidates.append(wf)
    except Exception:
        pass

    # [優先3] CWD
    cwd = os.getcwd()
    if cwd not in candidates:
        candidates.append(cwd)

    # 各候補で SHOTS_JSON が存在するか確認
    for c in candidates:
        test = os.path.join(c, SHOTS_JSON) if not os.path.isabs(SHOTS_JSON) else SHOTS_JSON
        if os.path.exists(test):
            print(f"[REBUILD] WORKSPACE resolved: {c}")
            return c

    # 全候補でJSONが見つからない場合は優先1を返す (エラー時DIAG用)
    fallback = candidates[0] if candidates else "."
    print(f"[REBUILD][WARN] JSON not found in any candidate, using: {fallback}")
    print(f"[REBUILD] Candidates tried: {candidates}")
    return fallback


WORKSPACE = _resolve_workspace()
if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)


def _clear_pycache():
    """__pycache__ を削除して古い .pyc が使われないようにする."""
    pycache = os.path.join(WORKSPACE, "__pycache__")
    if os.path.isdir(pycache):
        shutil.rmtree(pycache)
        print(f"[REBUILD] Cleared __pycache__: {pycache}")
    # sys.modules に残る古いモジュールも除去
    for mod_name in list(sys.modules.keys()):
        if mod_name.startswith('multi_camera_system'):
            del sys.modules[mod_name]


def _clear_scene_camera_action():
    """scene.animation_data.action を完全削除 (旧キーフレームの上書き保証)."""
    scene = bpy.context.scene
    if scene.animation_data is None:
        return 0
    removed = 0
    if scene.animation_data.action:
        # 旧API: action.fcurves からカウント
        try:
            fcs = list(scene.animation_data.action.fcurves)
            removed = sum(1 for fc in fcs if fc.data_path == "camera")
        except (AttributeError, TypeError):
            pass
        # 新API: layers/strips/channelbags からカウント
        if removed == 0:
            try:
                act = scene.animation_data.action
                for layer in act.layers:
                    for strip in layer.strips:
                        for cb in strip.channelbags:
                            for fc in cb.fcurves:
                                if fc.data_path == "camera":
                                    removed += 1
            except (AttributeError, TypeError):
                pass
    # Action を完全破棄 (NLA tracks もクリア)
    scene.animation_data.action = None
    while len(scene.animation_data.nla_tracks) > 0:
        scene.animation_data.nla_tracks.remove(scene.animation_data.nla_tracks[0])
    return removed


def _verify_camera_setup():
    """再構築後の検証: カメラ一覧 + scene.camera キーフレーム確認."""
    scene = bpy.context.scene
    print("\n" + "=" * 60)
    print("[VERIFY] Camera system verification")
    print("=" * 60)

    # [1] カメラオブジェクト一覧
    cams = [o for o in bpy.data.objects if o.type == 'CAMERA']
    print(f"  Cameras: {len(cams)}")
    for c in sorted(cams, key=lambda x: x.name):
        pos = (round(c.location.x, 2), round(c.location.y, 2), round(c.location.z, 2))
        lens = round(c.data.lens, 1) if c.data else '?'
        n_kf = 0
        if c.animation_data and c.animation_data.action:
            act = c.animation_data.action
            try:
                n_kf = len(act.fcurves)
            except (AttributeError, TypeError):
                for layer in act.layers:
                    for strip in layer.strips:
                        for cb in strip.channelbags:
                            n_kf += len(cb.fcurves)
        print(f"    {c.name:24s} pos={pos} lens={lens}mm kf_fcurves={n_kf}")

    # [2] frame_change_post ハンドラ確認
    print(f"  scene.camera (current): {scene.camera.name if scene.camera else 'None'}")
    handler_found = any(
        getattr(fn, '_multi_cam_switch', False)
        for fn in bpy.app.handlers.frame_change_post
    )
    print(f"  Camera switch handler: {'REGISTERED ✓' if handler_found else 'NOT FOUND ✗'}")
    if not handler_found:
        print(f"  [WARN] frame_change_post ハンドラが未登録です！")
        print(f"         カメラ切替は機能しません。")

    # [3] シーンフレーム範囲
    print(f"  Scene frame range: {scene.frame_start} - {scene.frame_end}")

    # [4] シーンプロパティ (multi_cam_shots)
    shots_json = scene.get("multi_cam_shots", "")
    if shots_json:
        shots = json.loads(shots_json)
        print(f"  Shot list ({len(shots)} shots):")
        for s in shots[:12]:
            print(f"    {s['start']:>5d}-{s['end']:>5d} : {s['cam']}")
        if len(shots) > 12:
            print(f"    ... ({len(shots) - 12} more)")

    print("=" * 60 + "\n")
    return handler_found


def _determine_total_measures(scene, json_data=None):
    """MIDI全曲小節数(M_total)を3層フォールバックで決定する。

    Layer 1: シーンプロパティ scene['midi_total_measures']
    Layer 2: シーンプロパティ scene['midi_ref'] → midoで小節数計算
    Layer 3: JSON の "midi_ref" フィールド → midoで小節数計算
    """
    # [Layer 1] シーンプロパティ
    m = scene.get("midi_total_measures")
    if m and int(m) >= 1:
        print(f"  [M_TOTAL] Layer 1: scene['midi_total_measures'] = {m}")
        return int(m)

    # [Layer 2] シーンプロパティ midi_ref → mido
    midi_ref = scene.get("midi_ref")
    if midi_ref:
        midi_path = midi_ref
        if not os.path.isabs(midi_path):
            midi_path = os.path.join(WORKSPACE, midi_path)
        if os.path.isfile(midi_path):
            try:
                import mido
                mid = mido.MidiFile(midi_path)
                max_abs_tick = 0
                for track in mid.tracks:
                    abs_tick = 0
                    for msg in track:
                        if hasattr(msg, 'time'):
                            abs_tick += msg.time
                        if abs_tick > max_abs_tick:
                            max_abs_tick = abs_tick
                tpb = max(1, mid.ticks_per_beat)
                m = max(1, int(round((max_abs_tick / tpb) / 4.0)))
                print(f"  [M_TOTAL] Layer 2: scene['midi_ref']={midi_ref} → measures={m}")
                return m
            except Exception as e:
                print(f"  [M_TOTAL][WARN] Layer 2 mido read failed: {e}")

    # [Layer 3] JSON の "midi_ref"
    if json_data and isinstance(json_data, dict) and "midi_ref" in json_data:
        midi_ref_json = json_data["midi_ref"]
        if not os.path.isabs(midi_ref_json):
            midi_ref_json = os.path.join(WORKSPACE, midi_ref_json)
        if os.path.isfile(midi_ref_json):
            try:
                import mido
                mid = mido.MidiFile(midi_ref_json)
                max_abs_tick = 0
                for track in mid.tracks:
                    abs_tick = 0
                    for msg in track:
                        if hasattr(msg, 'time'):
                            abs_tick += msg.time
                        if abs_tick > max_abs_tick:
                            max_abs_tick = abs_tick
                tpb = max(1, mid.ticks_per_beat)
                m = max(1, int(round((max_abs_tick / tpb) / 4.0)))
                print(f"  [M_TOTAL] Layer 3: JSON 'midi_ref'={midi_ref_json} → measures={m}")
                return m
            except Exception as e:
                print(f"  [M_TOTAL][WARN] Layer 3 mido read failed: {e}")

    print("  [M_TOTAL][WARN] Could not determine total measures from any source!")
    return None


def main():
    scene = bpy.context.scene

    # =====================================================
    # [1] シーンプロパティからデータを復元
    # =====================================================
    drum_events_json = scene.get("drum_events_json")
    if not drum_events_json:
        print("\n" + "=" * 60)
        print("[ERROR] scene['drum_events_json'] not found!")
        print("=" * 60)
        print("  drummer_lipsync_unified.py を一度だけ実行して .blend を保存")
        print("  するか、シーンプロパティが正しく設定されているか確認。")
        print("\n  [DIAG] 現在のシーンプロパティキー一覧:")
        for key in sorted(scene.keys()):
            val = scene.get(key)
            if isinstance(val, str) and len(val) > 80:
                preview = val[:80] + "..."
            else:
                preview = repr(val)
            print(f"    {key!r}: {preview}")
        print("=" * 60 + "\n")
        return

    drum_events = json.loads(drum_events_json)
    midi_bpm = float(scene.get("midi_bpm", 120.0))
    frame_end = int(scene.get("cam_scene_end", scene.frame_end))

    print(f"\n[REBUILD] [STEP 1/7] Loaded {len(drum_events)} drum events, "
          f"BPM={midi_bpm}, frame_end={frame_end}")

    # [1.5] MIDI全曲小節数決定 (3層フォールバック)
    # JSON の midi_ref を取得 (Layer 3 用)
    _json_data = None
    _json_path_tmp = SHOTS_JSON
    if not os.path.isabs(_json_path_tmp):
        _json_path_tmp = os.path.join(WORKSPACE, _json_path_tmp)
    if os.path.isfile(_json_path_tmp):
        try:
            with open(_json_path_tmp, 'r', encoding='utf-8') as f:
                _json_data = json.load(f)
        except Exception:
            pass
    midi_total_measures = _determine_total_measures(scene, json_data=_json_data)
    if midi_total_measures:
        print(f"  [REBUILD] M_total = {midi_total_measures} measures")
    else:
        print(f"  [REBUILD] M_total = None (will estimate from frame_end)")

    # =====================================================
    # [2] ドラマー中心を取得
    # =====================================================
    def _drummer_center():
        for o in bpy.data.objects:
            if o.type == 'ARMATURE':
                import mathutils
                return mathutils.Vector(o.matrix_world.translation)
        return None

    center = _drummer_center()
    if center is None:
        print("\n[ERROR] [STEP 2/7] No ARMATURE found in scene!")
        print("  シーンにアーマチュアオブジェクトが存在しません。")
        print("  [DIAG] 現在のオブジェクト一覧:")
        for o in bpy.data.objects:
            print(f"    {o.name!r} (type={o.type})")
        return
    print(f"[REBUILD] [STEP 2/7] Drummer center: "
          f"{tuple(round(c, 3) for c in center)}")

    # =====================================================
    # [3] JSONパス解決
    # =====================================================
    json_path = SHOTS_JSON
    if not os.path.isabs(json_path):
        json_path = os.path.join(WORKSPACE, json_path)
    if not os.path.exists(json_path):
        print(f"\n[ERROR] [STEP 3/7] JSON not found: {json_path}")
        print(f"  SHOTS_JSON = {SHOTS_JSON!r} (WORKSPACE={WORKSPACE!r})")
        print(f"  [DIAG] WORKSPACE 以下のファイル一覧:")
        if os.path.isdir(WORKSPACE):
            for f in sorted(os.listdir(WORKSPACE)):
                print(f"    {f}")
        else:
            print(f"    (WORKSPACE ディレクトリが存在しません)")
        return
    print(f"[REBUILD] [STEP 3/7] Using JSON: {json_path}")

    # =====================================================
    # [4] __pycache__ クリア + 旧モジュール除去
    # =====================================================
    print(f"[REBUILD] [STEP 4/7] Clearing __pycache__ + old modules...")
    _clear_pycache()

    # =====================================================
    # [5] 既存の scene.camera アニメーションをクリア
    # =====================================================
    print(f"[REBUILD] [STEP 5/7] Clearing existing scene.camera keyframes...")
    removed = _clear_scene_camera_action()
    if removed:
        print(f"  [REBUILD] Removed old scene camera action ({removed} fcurve keys)")
    else:
        print(f"  [REBUILD] No existing scene camera animation (fresh)")

    # =====================================================
    # [6] マルチカメラを再構築
    # =====================================================
    # 60fps前提: drummer timeline と整合性を保つ
    scene.render.fps = 60
    scene.render.fps_base = 1.0
    print(f"[REBUILD] [STEP 6/7] FPS set to {scene.render.fps}, calling build_multi_camera_system()...")
    try:
        import multi_camera_system  # ← __pycache__ 除去後に import
        multi_camera_system.build_multi_camera_system(
            drum_events,
            frame_end,
            midi_bpm=midi_bpm,
            center=center,
            shots_json_path=json_path,
            skip_frame_set=True,  # フルシーン評価をスキップ→メモリ枯渇回避
            total_measures=midi_total_measures,  # 小節形式shots展開用
        )
    except Exception as e:
        import traceback
        print(f"\n[ERROR] [STEP 6/7] build_multi_camera_system FAILED: "
              f"{type(e).__name__}: {e}")
        traceback.print_exc()
        print("=" * 60)
        return

    # =====================================================
    # [7] 検証 + 保存
    # =====================================================
    print(f"[REBUILD] [STEP 7/7] Verifying + Saving...")
    verified = _verify_camera_setup()

    bpy.ops.file.make_paths_relative()
    try:
        bpy.ops.wm.save_mainfile()
        print(f"  [REBUILD] Saved: {bpy.data.filepath}")
    except Exception as e:
        print(f"  [REBUILD][WARN] save_mainfile failed: {e}")
        print(f"  → 手動で Ctrl+S で保存してください")

    if verified:
        print("\n[DONE] Camera rebuilt + verified + saved. Ctrl+F12 でレンダリング確認\n")
    else:
        print("\n[WARN] Camera rebuilt but frame_change_post handler NOT registered!")
        print("  [WARN] レンダリング時にカメラ切替が起きません。")
        print("         コンソールログの [STEP 6/7] 出力を確認してください。\n")


# ---- Entry point ----
# 直接実行時（Blender GUI / background）のみ main() を呼ぶ。
# import 時には何も実行しない（テスト用モジュール import 対応）。
if __name__ == "__main__":
    main()