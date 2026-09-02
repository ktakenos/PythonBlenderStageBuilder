"""
Drummer Lipsync Unified Animator
================================
1 script, 2 animation systems, 1 fully-animated figure .blend.

  [ドラム系統]  MIDI  -> Armature NLA (v6 merged-track logic, Blender5.0 REPLACE bug safe)
  [口パク系統]  MusicXML -> Face material MixRGB chain fcurves (Mouth A/I/U/O/E/SHUT + Eyes)

These two systems touch completely separate data blocks (Armature NLA vs Material
node-tree fcurves), so they do not conflict and can both be baked into the same
static base figure at once.

CLI (passed after `--`):
  --midi     <drum.mid>        MIDI drum part            [default: drum_pattern.mid]
  --musicxml <vocal.musicxml>  MusicXML with lyrics+CTRL [default: vocal_melody.musicxml]
  --base     <base.blend>      static base (no NLA, has Face) [default: Drummer_Home-Position_Face.blend]
  --output   <out.blend>       output blend              [default: final_output.blend]
  --fps      60
  --bpm-master midi|musicxml   which BPM wins            [default: midi]

Usage:
  blender --background --python drummer_lipsync_unified.py -- \
      --midi drum_pattern.mid --musicxml vocal_melody.musicxml \
      --base Drummer_Home-Position_Face.blend --output final_output.blend
"""

import bpy
import os
import re
import sys
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Optional, Tuple

import mido

# ========== Configuration / CLI ==========
WORKSPACE = os.path.dirname(os.path.abspath(__file__))
if WORKSPACE not in sys.path:
    sys.path.insert(0, WORKSPACE)
# [ドラムセット物理] 個別化ドラムセット生成器（アーマチャNLAと独立、干渉しない）
import drum_set_animator as dsa
# [スポットライト] MIDI駆動ライティング
import Midi2BlenderSpotlight as spotlight
DEFAULTS = {
    'midi':     'drum_pattern.mid',
    'musicxml': 'vocal_melody.musicxml',
    'base':     'Drummer_Home-Position_Face.blend',
    'output':   'final_output.blend',
    'fps':      '60',
    'bpm-master': 'midi',
    'stage':    'stage_output.blend',
    'base-midi': 'bass_pattern.mid',   # §11-4 ベースMIDI (アンビエント呼吸レイヤー)
    'camera':  'multi',                      # カメラ: multi | beat-reactive | off
    'shots-json': '',                        # カスタムショットリストJSONパス (multiモード時)
}

def _resolve(p):
    return p

def parse_args():
    """Parse CLI args that come after Blender's `--` separator."""
    cfg = dict(DEFAULTS)
    argv = sys.argv
    if '--' in argv:
        argv = argv[argv.index('--') + 1:]
    else:
        argv = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith('--') and len(a) > 2:
            key = a[2:]
            if i + 1 < len(argv) and not argv[i + 1].startswith('--'):
                cfg[key] = argv[i + 1]
                i += 2
            else:
                cfg[key] = True
                i += 1
        else:
            i += 1
    return cfg

CFG = parse_args()
MIDI_FILE   = _resolve(str(CFG['midi']))
MUSICXML    = _resolve(str(CFG['musicxml']))
BASE_BLEND  = _resolve(str(CFG['base']))
OUTPUT      = _resolve(str(CFG['output']))
FPS         = float(CFG['fps'])
BPM_MASTER  = str(CFG['bpm-master']).lower()
BPM_DEFAULT = 120.0
STAGE_BLEND = _resolve(str(CFG['stage']))
BASE_MIDI   = _resolve(str(CFG['base-midi']))


# =====================================================================
# [ドラム系統]  NLA: shared constants (from v6)
# =====================================================================
# Action hit frame (1-indexed within the action)
HIT_LOCAL_FRAME = 8
ACTION_TOTAL_FRAMES = 15

# MIDI note -> default (on-beat) Action name mapping.
NOTE_TO_ACTION = {
    36: "ActionKick",
    42: "ActionHHat",
    46: "ActionHHatOpen",
    38: "ActionSnare",
    50: "ActionHighTom",
    47: "ActionMidTom",
    41: "ActionLowTom",
    53: "ActionRide",
    49: "ActionCrash",
}

# Off-beat 16th hand-swap mapping
OFFBEAT_SIXTEENTH_SWAP = {
    38: "ActionSnare.Right",
    50: "ActionHighTomLeft",
    47: "ActionMidTomLeft",
}

# ========== NLA: Track Groups ==========
# Merge by arm to avoid Blender 5.0 NLA REPLACE-mode cross-track override bug.
# All right-arm actions share the same bones -> must be on ONE track (same for
# left arm and kick). This is the bug-avoidance track split we MUST keep.
TRACK_GROUPS = {
    "KickTrack":     ["ActionKick"],
    "LeftArmTrack":  ["ActionSnare", "ActionMidTom",
                      "ActionHighTomLeft", "ActionMidTomLeft"],
    "RightArmTrack": ["ActionHHat", "ActionHHatOpen",
                      "ActionCrash", "ActionRide",
                      "ActionHighTom", "ActionLowTom",
                      "ActionSnare.Right"],
}

# Bone whitelist (which bones each action is allowed to animate)
ACTION_WHITELIST = {
    "ActionHHat":        ["Shoulder.R", "Arm.R", "Wrist.R", "Hand.R"],
    "ActionHHatOpen":    ["Shoulder.R", "Arm.R", "Wrist.R", "Hand.R",
                          "Thigh.L", "Leg.L"],
    "ActionHighTom":     ["Shoulder.R", "Arm.R", "Wrist.R", "Hand.R"],
    "ActionLowTom":      ["Shoulder.R", "Arm.R", "Wrist.R", "Hand.R"],
    "ActionCrash":       ["Shoulder.R", "Arm.R", "Wrist.R", "Hand.R"],
    "ActionRide":        ["Shoulder.R", "Arm.R", "Wrist.R", "Hand.R"],
    "ActionSnare.Right": ["Shoulder.R", "Arm.R", "Wrist.R", "Hand.R"],
    "ActionSnare":       ["Shoulder.L", "Arm.L", "Wrist.L", "Hand.L"],
    "ActionMidTom":      ["Shoulder.L", "Arm.L", "Wrist.L", "Hand.L"],
    "ActionHighTomLeft": ["Shoulder.L", "Arm.L", "Wrist.L", "Hand.L"],
    "ActionMidTomLeft":  ["Shoulder.L", "Arm.L", "Wrist.L", "Hand.L"],
    "ActionKick":        ["Thigh.R", "Leg.R", "Chest", "Neck"],
}


def ticks_to_frame(mid, tick, bpm):
    beats = tick / mid.ticks_per_beat
    seconds = beats * (60.0 / bpm)
    return seconds * FPS

def is_offbeat_sixteenth(tick, tpb):
    frac = (tick / tpb) % 1.0
    idx = int(round(frac * 4)) % 4
    return idx == 2

def resolve_action_for_event(note, tick, tpb):
    if note in OFFBEAT_SIXTEENTH_SWAP and is_offbeat_sixteenth(tick, tpb):
        return OFFBEAT_SIXTEENTH_SWAP[note]
    return NOTE_TO_ACTION.get(note)

def load_midi_drum_track(midi_path):
    """Return (drum_events, bpm, mid)."""
    mid = mido.MidiFile(midi_path)
    drum_events = []
    bpm = None
    for track in mid.tracks:
        for msg in track:
            if msg.type == 'set_tempo':
                bpm = 60000000.0 / msg.tempo
                break
        if bpm:
            break
    if bpm is None:
        bpm = 120.0

    # 全トラックの最終絶対tick（全曲長の算出に利用）
    max_abs_tick = 0
    for track in mid.tracks:
        abs_tick = 0
        for msg in track:
            if hasattr(msg, 'time'):
                abs_tick += msg.time
            if abs_tick > max_abs_tick:
                max_abs_tick = abs_tick

    # 小節数推定: max_abs_tick / ticks_per_beat / beats_per_measure(4/4)
    tpb = max(1, mid.ticks_per_beat)
    beats_total = max_abs_tick / float(tpb)
    measures_total = int(round(beats_total / 4.0))  # 4/4拍
    if measures_total < 1:
        measures_total = 1

    for track in mid.tracks:
        abs_tick = 0
        for msg in track:
            if hasattr(msg, 'time'):
                abs_tick += msg.time
            if msg.type == 'note_on' and msg.velocity > 0:
                action_name = resolve_action_for_event(msg.note, abs_tick, mid.ticks_per_beat)
                if action_name is not None:
                    frame = ticks_to_frame(mid, abs_tick, bpm)
                    drum_events.append({
                        'note': msg.note,
                        'action': action_name,
                        'velocity': msg.velocity,
                        'frame': frame,
                    })

    drum_events.sort(key=lambda e: e['frame'])
    print(f"[DRUM] Found {len(drum_events)} drum events "
          f"(BPM={bpm:.1f}, total_beats={beats_total:.1f}, "
          f"total_measures={measures_total})")
    return drum_events, bpm, mid, max_abs_tick, tpb, measures_total


def open_base_and_find_armature():
    bpy.ops.wm.open_mainfile(filepath=BASE_BLEND)
    armature = None
    for obj in bpy.context.scene.objects:
        if obj.type == 'ARMATURE':
            armature = obj
            break
    if not armature:
        print("[ERROR] No armature found in base scene!")
        sys.exit(1)
    print(f"[INFO] Armature: {armature.name}")
    return armature


def _iter_fcurves(action):
    # Old API (<=4.3)
    try:
        if action.fcurves:
            for fc in action.fcurves:
                yield fc
            return
    except (AttributeError, TypeError):
        pass
    # New API (4.4+/5.0)
    try:
        for layer in action.layers:
            for strip in layer.strips:
                for cb in strip.channelbags:
                    for fc in cb.fcurves:
                        yield fc
    except (AttributeError, TypeError):
        pass


def _get_bone_name(fcurve):
    path = fcurve.data_path
    if "pose.bones[" in path:
        raw = path.split("pose.bones[")[1].split("]")[0]
        return raw.strip('"').strip("'")
    return None


def clean_action_whitelist(action, action_name):
    whitelist = ACTION_WHITELIST.get(action_name, [])
    if not whitelist:
        print(f"  [WARN] No whitelist for '{action_name}'")

    new_action = action.copy()
    new_action.name = action.name + "_clean"

    total_count = 0
    to_remove = []
    for fc in _iter_fcurves(new_action):
        total_count += 1
        path = fc.data_path
        if "rotation_quaternion" not in path:
            to_remove.append(fc)
            continue
        if whitelist:
            bone = _get_bone_name(fc)
            if bone not in whitelist:
                to_remove.append(fc)

    removed = 0
    # Need to remove via channelbags because fcurves live inside channelbags
    for layer in new_action.layers:
        for strip in layer.strips:
            for cb in strip.channelbags:
                for fc in list(cb.fcurves):
                    if fc in to_remove:
                        try:
                            cb.fcurves.remove(fc)
                            removed += 1
                        except Exception:
                            pass

    remaining_bones = set()
    for fc in _iter_fcurves(new_action):
        bone = _get_bone_name(fc)
        if bone:
            remaining_bones.add(bone)

    print(f"  [CLEAN] {action.name}: {total_count} fcurves -> {total_count - removed} "
          f"(bones: {sorted(remaining_bones)})")
    return new_action


def _create_trimmed_action(source_action, win_start, win_end, name_suffix=""):
    new_action = source_action.copy()
    new_action.name = source_action.name + name_suffix
    offset = win_start - 1.0

    to_remove = []
    for fc in _iter_fcurves(new_action):
        for kp in fc.keyframe_points:
            if kp.co.x < (win_start - 0.01) or kp.co.x > (win_end + 0.01):
                to_remove.append((fc, kp))

    # Remove out-of-window keyframes via channelbags
    for layer in new_action.layers:
        for lstrip in layer.strips:
            for cb in lstrip.channelbags:
                for fc in list(cb.fcurves):
                    for kp in list(fc.keyframe_points):
                        if (fc, kp) in to_remove:
                            try:
                                fc.keyframe_points.remove(kp)
                            except Exception:
                                pass

    for fc in _iter_fcurves(new_action):
        for kp in fc.keyframe_points:
            kp.co[0] -= offset
            kp.handle_left[0] -= offset
            kp.handle_right[0] -= offset

    new_action.frame_range = (1.0, float(round(win_end - win_start + 1)))
    return new_action


def create_nla_animation(armature, drum_events):
    """Build the 3-track merged NLA. Returns drum_total_frames (for reconciliation)."""
    if armature.animation_data is None:
        armature.animation_data_create()

    while len(armature.animation_data.nla_tracks) > 0:
        armature.animation_data.nla_tracks.remove(armature.animation_data.nla_tracks[0])
    armature.animation_data.action = None

    track_objs = {}
    for track_name, action_names in TRACK_GROUPS.items():
        t = armature.animation_data.nla_tracks.new()
        t.name = track_name
        track_objs[track_name] = t

    action_dict = {act.name: act for act in bpy.data.actions}
    print(f"\n[INFO] Actions in blend ({len(action_dict)}):")
    for name in sorted(action_dict.keys()):
        fr = action_dict[name].frame_range
        print(f"  - {name} (frames {fr[0]:.0f}-{fr[1]:.0f})")

    print(f"\n[CLEAN] Cleaning actions:")
    clean_action_dict = {}
    for track_name, action_names in TRACK_GROUPS.items():
        for action_name in action_names:
            if action_name in action_dict:
                orig = action_dict[action_name]
                cleaned = clean_action_whitelist(orig, action_name)
                clean_action_dict[action_name] = cleaned
            else:
                print(f"  [WARN] Action '{action_name}' not found!")

    # Group events by TRACK (not by action)
    events_by_track = {tn: [] for tn in TRACK_GROUPS}
    for event in drum_events:
        action_name = event.get('action') or NOTE_TO_ACTION.get(event['note'])
        if not action_name or action_name not in clean_action_dict:
            continue
        for track_name, action_names in TRACK_GROUPS.items():
            if action_name in action_names:
                events_by_track[track_name].append(event)
                break

    trimmed_cache = {}
    strip_count = 0
    skip_count = 0

    for track_name, evts in events_by_track.items():
        evts.sort(key=lambda e: e['frame'])
        track = track_objs[track_name]
        track_strips = 0

        for i, ev in enumerate(evts):
            action_name = ev['action']
            hit_frame = max(1, int(round(ev['frame'])))

            gaps = []
            if i > 0:
                gaps.append(evts[i]['frame'] - evts[i - 1]['frame'])
            if i < len(evts) - 1:
                gaps.append(evts[i + 1]['frame'] - evts[i]['frame'])

            if not gaps:
                d = 7
            else:
                min_gap = int(min(gaps))
                d = min(7, max(1, (min_gap - 1) // 2))

            win_start = max(1, HIT_LOCAL_FRAME - d)
            win_end = min(ACTION_TOTAL_FRAMES, HIT_LOCAL_FRAME + d)

            cache_key = (action_name, d)
            if cache_key not in trimmed_cache:
                trimmed_cache[cache_key] = _create_trimmed_action(
                    clean_action_dict[action_name], win_start, win_end, f"_d{d}"
                )
            trimmed = trimmed_cache[cache_key]

            hit_offset = HIT_LOCAL_FRAME - win_start
            strip_start = max(1, hit_frame - hit_offset)

            try:
                strip = track.strips.new(action_name, strip_start, trimmed)
                strip.influence = 1.0
                strip.blend_in = 0
                strip.blend_out = 0
                strip.blend_type = 'REPLACE'
                track_strips += 1
                strip_count += 1
            except RuntimeError as e:
                skip_count += 1
                print(f"  [SKIP] {action_name} hit={hit_frame} D={d}: {e}")

        print(f"  [TRACK] {track_name:22s}: {track_strips} strips")

    print(f"\n[DRUM] Total: {strip_count} NLA strips, {skip_count} skipped")

    # drum total frames (for scene reconciliation)
    if drum_events:
        max_frame = max(e['frame'] for e in drum_events)
        drum_total_frames = int(max_frame) + 30
    else:
        drum_total_frames = 1
    return drum_total_frames


# =====================================================================
# [口パク系統]  MusicXML -> Face material MixRGB chain fcurves
# (verified implementation from lipsync_animator.py)
# =====================================================================
# 口パク: state_key -> 画像ファイル名
MOUTH_STATES = ["A", "I", "U", "O", "E", "SHUT"]
MOUTH_FILES = {
    "A":    "ZundamonMiniMouthA.png",
    "I":    "ZundamonMiniMouthI.png",
    "U":    "ZundamonMiniMouthU.png",
    "O":    "ZundamonMiniMouthO.png",
    "E":    "ZundamonMiniMouthE.png",
    "SHUT": "ZundamonMiniMouthShut.png",
}

# 目: state_key -> 画像ファイル名
EYE_STATES = ["OPEN", "CLOSED", "WINK"]
EYE_FILES = {
    "OPEN":   "ZundamonMiniEyes.png",
    "CLOSED": "ZundamonMiniEyesClosed.png",
    "WINK":   "ZundamonMiniEyeWink.png",
}

# §11-5 Roughness マップ (母音/目状態ごとに同期切り替わる)
MOUTH_ROUGH_FILES = {
    "A":    "ZundamonMiniMouthA_Roughness.png",
    "I":    "ZundamonMiniMouthI_Roughness.png",
    "U":    "ZundamonMiniMouthU_Roughness.png",
    "O":    "ZundamonMiniMouthO_Roughness.png",
    "E":    "ZundamonMiniMouthE_Roughness.png",
    "SHUT": "ZundamonMiniMouthShut_Roughness.png",
}
EYE_ROUGH_FILES = {
    "OPEN":   "ZundamonMiniEyesRoughness.png",
    "CLOSED": "ZundamonMiniEyesClosedRoughness.png",
    "WINK":   "ZundamonMiniEyeWinkRoughness.png",
}

# 周期瞬き (auto-blink) 設定
BLINK_INTERVAL_SEC = 4.0
BLINK_DURATION_SEC = 0.15

# Face 部品 (object -> material)
# 注: Mouth と Eyes のマテリアルは同一オブジェクトに付いている（.001 は存在しない）
MOUTH_OBJ_NAME = "ZundamonMiniHead.002"
EYES_OBJ_NAME  = "ZundamonMiniHead.002"


# ---- 母音解析 ----
VOWEL_GROUPS = {
    "A": set(list("あかさたなはまやらわがざだばぱぁゃゎアカサタナハマヤラワガザダバパァャヮぁゃゎ")),
    "I": set(list("いきしちにひみりぎじぢびぴぃイキシチニヒミリギジヂビピィ")),
    "U": set(list("うくすつぬふむゆるぐずづぶぷぅゅウクスツヌフムユルグズヅブプゥュ")),
    "E": set(list("えけせてねへめれげぜでべぺぇエケセテネヘメレゲゼデベペェ")),
    "O": set(list("おこそとのほもよろをとごぞどぼぽぉょオコソトノホモヨロゴゾドボポォョ")),
}
SMALL_KANA = set(list("ゃゅょぁぃぅぇぉャュョァィゥェォ"))
LONG_MARK = "ー"

def normalize_lyric(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"[ \t\r\n]+", "", s)
    s = re.sub(r"[、。・,.\-!！?？「」『』（）()\[\]{}]", "", s)
    return s

def pick_vowel(text: str) -> Optional[str]:
    if not text or text in ("ん", "ン"):
        return None
    chars = list(text)
    for i in range(len(chars) - 1, -1, -1):
        c = chars[i]
        if c == LONG_MARK or c in SMALL_KANA:
            continue
        for vg, charset in VOWEL_GROUPS.items():
            if c in charset:
                return vg
    m = re.findall(r"[aiueoAIUEO]", text)
    if m:
        return {"a": "A", "i": "I", "u": "U", "e": "E", "o": "O"}[m[-1].lower()]
    return None

def lyric_to_mouth_state(text: str) -> str:
    t = normalize_lyric(text)
    if not t:
        return "SHUT"
    vg = pick_vowel(t)
    if vg and vg in MOUTH_STATES:
        return vg
    return "SHUT"


# ---- MusicXML parse ----
@dataclass
class Segment:
    t0: float
    t1: float
    state: str

@dataclass
class EyeEvent:
    time_sec: float
    state: str          # "OPEN" | "CLOSED" | "WINK"
    duration_beats: float = 0.0

def parse_tempo_bpm(root: ET.Element, default_bpm: float = 120.0) -> float:
    for elem in root.iter():
        if elem.tag.endswith("sound"):
            tempo = elem.attrib.get("tempo")
            if tempo:
                try:
                    return float(tempo)
                except ValueError:
                    pass
    for elem in root.iter():
        if elem.tag.endswith("per-minute"):
            try:
                return float(elem.text.strip())
            except Exception:
                pass
    return default_bpm

def parse_segments(xml_path: str, default_bpm: float = 120.0) -> Tuple[List[Segment], float]:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    bpm = parse_tempo_bpm(root, default_bpm)
    sec_per_quarter = 60.0 / bpm

    parts = [e for e in root.findall(".//part")]
    if not parts:
        raise RuntimeError("No <part> found in MusicXML")
    part = parts[0]

    segments: List[Segment] = []
    t = 0.0
    divisions = 1
    time_beats, time_beat_type = 4, 4
    current_state = "SHUT"

    for measure in part.findall("./measure"):
        attrs = measure.find("./attributes")
        if attrs is not None:
            div = attrs.find("./divisions")
            if div is not None and div.text:
                try:
                    divisions = int(div.text.strip())
                except ValueError:
                    pass
            tm = attrs.find("./time")
            if tm is not None:
                b = tm.find("./beats")
                bt = tm.find("./beat-type")
                if b is not None and bt is not None and b.text and bt.text:
                    try:
                        time_beats = int(b.text.strip())
                        time_beat_type = int(bt.text.strip())
                    except ValueError:
                        pass

        if divisions <= 0:
            divisions = 1

        measure_quarter_len = float(time_beats) * (4.0 / float(time_beat_type))
        notes = measure.findall("./note")

        if not notes:
            dt = measure_quarter_len * sec_per_quarter
            segments.append(Segment(t, t + dt, "SHUT"))
            t += dt
            continue

        sum_quarters = 0.0
        for note in notes:
            is_rest = (note.find("./rest") is not None)
            dur_elem = note.find("./duration")
            if dur_elem is None or dur_elem.text is None:
                continue
            try:
                dur_div = int(dur_elem.text.strip())
            except ValueError:
                continue

            q = dur_div / float(divisions)
            dt = q * sec_per_quarter
            sum_quarters += q

            tie_elems = note.findall("./tie")
            tie_types = {te.attrib.get("type") for te in tie_elems if te is not None}
            has_tie_stop = "stop" in tie_types
            has_tie_start = "start" in tie_types

            lyric_text = None
            lyr = note.find("./lyric")
            if lyr is not None:
                tx = lyr.find("./text")
                if tx is not None and tx.text:
                    lyric_text = tx.text

            if is_rest:
                state = "SHUT"
            else:
                if lyric_text:
                    state = lyric_to_mouth_state(lyric_text)
                    current_state = state
                else:
                    if has_tie_stop and not has_tie_start:
                        state = current_state
                    else:
                        state = "SHUT"

            segments.append(Segment(t, t + dt, state))
            t += dt

        remainder_q = measure_quarter_len - sum_quarters
        implicit = (measure.attrib.get("implicit", "no").lower() == "yes")
        if (not implicit) and remainder_q > 1e-6:
            dt_pad = remainder_q * sec_per_quarter
            segments.append(Segment(t, t + dt_pad, "SHUT"))
            t += dt_pad

    return segments, t

CTRL_EYE_MAP = {
    "OPEN_EYES": "OPEN",
    "CLOSE_EYES": "CLOSED",
    "WINK":       "WINK",
}

def parse_eye_directives(xml_path: str, default_bpm: float = 120.0) -> Tuple[List[EyeEvent], float]:
    """Parse CTRL:OPEN_EYES/CLOSE_EYES/WINK from MusicXML direction elements."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    bpm = parse_tempo_bpm(root, default_bpm)
    sec_per_quarter = 60.0 / bpm

    parts = [e for e in root.findall(".//part")]
    if not parts:
        raise RuntimeError("No <part> found in MusicXML")
    part = parts[0]

    events: List[EyeEvent] = []
    t = 0.0
    divisions = 1
    time_beats, time_beat_type = 4, 4

    for measure in part.findall("./measure"):
        attrs = measure.find("./attributes")
        if attrs is not None:
            div = attrs.find("./divisions")
            if div is not None and div.text:
                try:
                    divisions = int(div.text.strip())
                except ValueError:
                    pass
            tm = attrs.find("./time")
            if tm is not None:
                b = tm.find("./beats")
                bt = tm.find("./beat-type")
                if b is not None and bt is not None and b.text and bt.text:
                    try:
                        time_beats = int(b.text.strip())
                        time_beat_type = int(bt.text.strip())
                    except ValueError:
                        pass

        if divisions <= 0:
            divisions = 1

        measure_quarter_len = float(time_beats) * (4.0 / float(time_beat_type))
        notes = measure.findall("./note")

        if not notes:
            t += measure_quarter_len * sec_per_quarter
            continue

        for mdir in measure.findall("./direction"):
            for dtype in mdir.findall(".//direction-type"):
                words = dtype.find(".//words")
                if words is not None and words.text:
                    ctrl_text = words.text.strip()
                    if ctrl_text.startswith("CTRL:"):
                        parts_ctrl = ctrl_text.split(":")
                        if len(parts_ctrl) >= 2:
                            action = parts_ctrl[1].strip()
                            dur_beats = 0.0
                            if len(parts_ctrl) >= 3:
                                try:
                                    dur_beats = float(parts_ctrl[2].strip())
                                except ValueError:
                                    pass
                            if action in CTRL_EYE_MAP:
                                state = CTRL_EYE_MAP[action]
                                events.append(EyeEvent(t, state, dur_beats))

        sum_q = 0.0
        for note in notes:
            dur_elem = note.find("./duration")
            if dur_elem is None or dur_elem.text is None:
                continue
            try:
                dur_div = int(dur_elem.text.strip())
            except ValueError:
                continue
            q = dur_div / float(divisions)
            sum_q += q

            direction = note.find("./direction")
            if direction is not None:
                for dtype in direction.findall(".//direction-type"):
                    words = dtype.find(".//words")
                    if words is not None and words.text:
                        ctrl_text = words.text.strip()
                        if ctrl_text.startswith("CTRL:"):
                            parts_ctrl = ctrl_text.split(":")
                            if len(parts_ctrl) >= 2:
                                action = parts_ctrl[1].strip()
                                dur_beats = 0.0
                                if len(parts_ctrl) >= 3:
                                    try:
                                        dur_beats = float(parts_ctrl[2].strip())
                                    except ValueError:
                                        pass
                                if action in CTRL_EYE_MAP:
                                    state = CTRL_EYE_MAP[action]
                                    events.append(EyeEvent(t, state, dur_beats))

            t += q * sec_per_quarter

        remainder_q = measure_quarter_len - sum_q
        implicit = (measure.attrib.get("implicit", "no").lower() == "yes")
        if (not implicit) and remainder_q > 1e-6:
            t += remainder_q * sec_per_quarter

    return events, t


# ---- Blender: MixRGBノードチェーン (verified) ----
def build_mixrgb_chain(nt, images: List, label: str, target_input_socket):
    """
    Build MixRGB chain for N images.
    State S (0-indexed): MixRGB[S-1].Fac=1, all others Fac=0 (S==0 -> all Fac=0).
    Returns list of MixRGB nodes.
    """
    n = len(images)
    if n == 1:
        tex = nt.nodes.new('ShaderNodeTexImage')
        tex.image = images[0]
        tex.location = (0, 0)
        nt.links.new(tex.outputs['Color'], target_input_socket)
        return []

    mix_nodes = []
    prev_output = None

    for i, img in enumerate(images):
        tex = nt.nodes.new('ShaderNodeTexImage')
        tex.image = img
        tex.location = (-400, -150 * i)
        tex.name = f"{label}_img_{i}"

        if i == 0:
            mix = nt.nodes.new('ShaderNodeMixRGB')
            mix.blend_type = 'MIX'
            mix.name = f"{label}_mix_{i}"
            mix.location = (100, -150 * i)
            nt.links.new(tex.outputs['Color'], mix.inputs['Color1'])
            mix_nodes.append(mix)
            prev_output = mix.outputs['Color']
        elif i == 1:
            nt.links.new(tex.outputs['Color'], mix_nodes[0].inputs['Color2'])
        else:
            mix = nt.nodes.new('ShaderNodeMixRGB')
            mix.blend_type = 'MIX'
            mix.name = f"{label}_mix_{i}"
            mix.location = (100 + 250 * (i - 1), -150 * i)
            nt.links.new(prev_output, mix.inputs['Color1'])
            nt.links.new(tex.outputs['Color'], mix.inputs['Color2'])
            mix_nodes.append(mix)
            prev_output = mix.outputs['Color']

    nt.links.new(prev_output, target_input_socket)
    return mix_nodes

def keyframe_state(mix_nodes: List, state_index: int, frame: int):
    """
    Keyframe MixRGB Fac values to select image[state_index].
    Chain logic: img[0]=Color1 of mix[0], img[S>=1]=Color2 of mix[S-1]
    So: if S==0, all Fac=0. If S>=1, mix[S-1].Fac=1, rest=0.
    """
    for i, mix in enumerate(mix_nodes):
        if state_index == 0:
            target = 0.0
        else:
            target = 1.0 if i == state_index - 1 else 0.0
        mix.inputs['Fac'].default_value = target
        mix.inputs['Fac'].keyframe_insert(data_path="default_value", frame=frame)

def set_constant_interpolation(node_tree):
    """Set CONSTANT interpolation on all fcurves in the node tree's action.
    Handles both old (<=4.3) and new (>=4.4/5.0) Action APIs."""
    ad = node_tree.animation_data
    if not ad or not ad.action:
        return
    action = ad.action
    try:
        fcs = list(action.fcurves)
        if fcs:
            for fc in fcs:
                for kp in fc.keyframe_points:
                    kp.interpolation = 'CONSTANT'
            return
    except (AttributeError, TypeError):
        pass
    try:
        for layer in action.layers:
            for strip in layer.strips:
                for cb in strip.channelbags:
                    for fc in cb.fcurves:
                        for kp in fc.keyframe_points:
                            kp.interpolation = 'CONSTANT'
        return
    except (AttributeError, TypeError):
        pass
    try:
        for fc in action.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = 'CONSTANT'
    except Exception:
        print("  WARNING: could not set CONSTANT interpolation (API mismatch)")


def _load_image_list(files_map: dict, states: List[str]) -> List:
    imgs = []
    for state in states:
        fname = files_map[state]
        # [PORTABILITY] 絶対パスで読み込み (Blender内部CWD問題回避)
        # 保存時に make_paths_relative() が相対パスに変換する
        abs_path = os.path.abspath(fname)
        if not os.path.exists(abs_path):
            print(f"  [LIPSYNC][WARN] {abs_path} not found, using placeholder")
            img = bpy.data.images.new(fname, 1, 1, alpha=True)
        else:
            img = bpy.data.images.load(abs_path, check_existing=True)
        imgs.append(img)
        print(f"  {state:6s} -> {fname}")
    return imgs


def _find_material(obj_name: str, mat_name: str):
    obj = bpy.data.objects.get(obj_name)
    if not obj:
        raise RuntimeError(f"Object '{obj_name}' not found!")
    for m in obj.data.materials:
        if m and m.name == mat_name:
            return m
    raise RuntimeError(f"Material '{mat_name}' not found on {obj_name}!")


def setup_face_lipsync(segments: List[Segment], eye_events: List[EyeEvent],
                       xml_bpm: float, total_sec: float):
    """
    Build Mouth & Eyes MixRGB chains and keyframe them.
    Returns lipsync_end_frame (int).
    """
    total_frames = int(total_sec * FPS)

    # --- images ---
    print("  [LIPSYNC] Loading images...")
    mouth_images = _load_image_list(MOUTH_FILES, MOUTH_STATES)
    eye_images   = _load_image_list(EYE_FILES,  EYE_STATES)
    # §11-5 Roughness マップ画像 (データマップとして Non-Color)
    mouth_rough_images = _load_image_list(MOUTH_ROUGH_FILES, MOUTH_STATES)
    eye_rough_images   = _load_image_list(EYE_ROUGH_FILES,  EYE_STATES)
    for _ri in (mouth_rough_images + eye_rough_images):
        try:
            _ri.colorspace_settings.name = 'Non-Color'
        except Exception:
            pass

    # --- Mouth material ---
    mouth_mat = _find_material(MOUTH_OBJ_NAME, "Mouth")
    nt = mouth_mat.node_tree
    bsdf, old_tex = None, None
    for node in nt.nodes:
        if node.type == 'BSDF_PRINCIPLED':
            bsdf = node
        if node.type == 'TEX_IMAGE':
            old_tex = node
    if not bsdf:
        raise RuntimeError("Principled BSDF not found in Mouth material!")
    base_color_socket = bsdf.inputs['Base Color']
    for link in list(base_color_socket.links):
        nt.links.remove(link)
    if old_tex:
        nt.nodes.remove(old_tex)
    mouth_mix_nodes = build_mixrgb_chain(nt, mouth_images, "Mouth", base_color_socket)
    print(f"  [LIPSYNC] Built {len(mouth_mix_nodes)} MixRGB nodes for {len(mouth_images)} mouth states")

    # §11-5 Mouth Roughness chain -> BSDF.Roughness socket (同indexで同期)
    rough_socket = bsdf.inputs['Roughness']
    for _link in list(rough_socket.links):
        nt.links.remove(_link)
    mouth_rough_nodes = build_mixrgb_chain(nt, mouth_rough_images, "MouthRough", rough_socket)
    print(f"  [LIPSYNC] Built {len(mouth_rough_nodes)} MixRGB nodes for mouth Roughness")

    # --- Eyes material ---
    eyes_mat = _find_material(EYES_OBJ_NAME, "Eyes")
    ent = eyes_mat.node_tree
    ebsdf, eold_tex = None, None
    for node in ent.nodes:
        if node.type == 'BSDF_PRINCIPLED':
            ebsdf = node
        if node.type == 'TEX_IMAGE':
            eold_tex = node
    if not ebsdf:
        raise RuntimeError("Principled BSDF not found in Eyes material!")
    ebase = ebsdf.inputs['Base Color']
    for link in list(ebase.links):
        ent.links.remove(link)
    if eold_tex:
        ent.nodes.remove(eold_tex)
    eye_mix_nodes = build_mixrgb_chain(ent, eye_images, "Eyes", ebase)
    print(f"  [LIPSYNC] Built {len(eye_mix_nodes)} MixRGB nodes for {len(eye_images)} eye states")

    # §11-5 Eyes Roughness chain -> BSDF.Roughness socket (同indexで同期)
    erough_socket = ebsdf.inputs['Roughness']
    for _link in list(erough_socket.links):
        ent.links.remove(_link)
    eye_rough_nodes = build_mixrgb_chain(ent, eye_rough_images, "EyesRough", erough_socket)
    print(f"  [LIPSYNC] Built {len(eye_rough_nodes)} MixRGB nodes for eye Roughness")

    # --- Mouth keyframes ---
    print("  [LIPSYNC] Keyframing mouth...")
    prev_state = None
    for seg in segments:
        frame = int(seg.t0 * FPS)
        if seg.state != prev_state:
            state_idx = MOUTH_STATES.index(seg.state)
            keyframe_state(mouth_mix_nodes, state_idx, frame)
            keyframe_state(mouth_rough_nodes, state_idx, frame)   # §11-5 Roughness同期
            prev_state = seg.state
    if prev_state is not None:
        keyframe_state(mouth_mix_nodes, MOUTH_STATES.index(prev_state), total_frames)
        keyframe_state(mouth_rough_nodes, MOUTH_STATES.index(prev_state), total_frames)
    keyframe_state(mouth_mix_nodes, 5, 0)  # SHUT at frame 0
    keyframe_state(mouth_rough_nodes, 5, 0)  # §11-5 Roughness: SHUT at frame 0
    set_constant_interpolation(mouth_mat.node_tree)

    # --- Eyes keyframes (CTRL directives + auto blink) ---
    print("  [LIPSYNC] Keyframing eyes (CTRL + auto blink)...")
    sec_per_beat = 60.0 / xml_bpm

    closed_intervals = []
    for ev in eye_events:
        if ev.state in ("CLOSED", "WINK") and ev.duration_beats > 0:
            end = min(ev.time_sec + ev.duration_beats * sec_per_beat, total_sec)
            closed_intervals.append((ev.time_sec, end, ev.state))
    closed_intervals.sort(key=lambda x: x[0])

    open_segments = []
    cursor = 0.0
    for (cs, ce, _st) in closed_intervals:
        if cs > cursor:
            open_segments.append((cursor, cs))
        cursor = max(cursor, ce)
    if cursor < total_sec:
        open_segments.append((cursor, total_sec))

    auto_blinks = []
    for (t0, t1) in open_segments:
        if (t1 - t0) < BLINK_INTERVAL_SEC:
            continue
        t = t0 + BLINK_INTERVAL_SEC
        while t + BLINK_DURATION_SEC <= t1 - 0.05:
            auto_blinks.append((t, t + BLINK_DURATION_SEC))
            t += BLINK_INTERVAL_SEC

    kf = [(0.0, 0)]
    for (cs, ce, st) in closed_intervals:
        kf.append((cs, EYE_STATES.index(st)))
        if ce < total_sec:
            kf.append((ce, 0))
    for (bs, be) in auto_blinks:
        kf.append((bs, EYE_STATES.index("CLOSED")))
        kf.append((be, 0))
    kf.append((total_sec, 0))
    kf.sort(key=lambda x: x[0])

    for (tsec, state_idx) in kf:
        frame = min(int(tsec * FPS), total_frames)
        keyframe_state(eye_mix_nodes, state_idx, frame)
        keyframe_state(eye_rough_nodes, state_idx, frame)   # §11-5 Roughness同期
    set_constant_interpolation(eyes_mat.node_tree)

    print(f"  [LIPSYNC] Eye auto-blinks: {len(auto_blinks)}, total eye keyframes: {len(kf)}")
    return total_frames + 10


# =====================================================================
# [ステージメッシュ] Stage MESH objects append helper
# =====================================================================
STAGE_MESH_EXCLUDE = {"Drum_Set"}  # 静的ドラムセットは dsa が再構築するので除外

STAGE_MESH_NAMES = [
    "Audience_Floor", "Bass_Amp", "Ceiling_Top",
    "Curtain", "Curtain.001", "Curtain.002", "Curtain.003", "Curtain.004", "Curtain.005",
    "Drummer_Chair",
    "Floor_Monitor", "Floor_Monitor.001", "Floor_Monitor.002", "Floor_Monitor.003", "Floor_Monitor.004",
    "Guitar_Amp",
    "MicStand_Base", "MicStand_Base.001", "MicStand_Base.002", "MicStand_Base.003",
    "MicStand_Base.004", "MicStand_Base.005", "MicStand_Base.006", "MicStand_Base.007",
    "PA_Speaker", "PA_Speaker.001",
    "SP1_Spotlight_Housing", "SP1_Spotlight_Housing.001", "SP1_Spotlight_Housing.002",
    "SP1_Spotlight_Housing.003",
    "SP2_Spotlight_Housing", "SP2_Spotlight_Housing.001",
    "SP3_Spotlight_Housing", "SP3_Spotlight_Housing.001",
    "SP4_Spotlight_Housing", "SP4_Spotlight_Housing.001",
    "SP5_Spotlight_Housing", "SP5_Spotlight_Housing.001",
    "Stage_LeftRailing", "Stage_LeftStair", "Stage_Platform",
    "Stage_RightRailing", "Stage_RightStair",
    "Stage_Volume_Box",
    "Truss_System",
    "Wall_Back", "Wall_Side_L", "Wall_Side_R",
]


def _append_stage_meshes(stage_blend_path):
    """Append all stage MESH objects from stage_output.blend into current scene.
    Uses bpy.data.libraries.load (Blender 5.0+ compatible).
    Excludes objects in STAGE_MESH_EXCLUDE (e.g. static Drum_Set replaced by dsa).
    
    Handles: pre-existing empty/hidden objects with the same name that would
    block the append (e.g. empty stub objects in the base blend file)."""
    # [PORTABILITY] bpy.data.libraries.load() はBlender内部CWD基準で解決するため絶対パスに変換
    stage_blend_path = os.path.abspath(stage_blend_path)
    if not os.path.exists(stage_blend_path):
        print(f"  [MESH] stage file not found: {stage_blend_path}")
        return 0

    # --- Pre-check: remove placeholder objects that would block append ---
    # An object "blocks" if it exists in bpy.data.objects but is NOT a valid
    # visible MESH (e.g. empty stub, wrong type, or hidden).
    removed_placeholders = []
    for name in STAGE_MESH_NAMES:
        if name in STAGE_MESH_EXCLUDE:
            continue
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue  # doesn't exist, fine
        # Check if it's a valid visible mesh
        is_valid_mesh = (
            obj.type == 'MESH'
            and obj.data is not None
            and len(obj.data.vertices) > 0
            and not obj.hide_render
        )
        if not is_valid_mesh:
            print(f"  [MESH] Removing placeholder '{name}' "
                  f"(type={obj.type}, verts={len(obj.data.vertices) if obj.data else 0}, "
                  f"hide_render={obj.hide_render})")
            bpy.data.objects.remove(obj, do_unlink=True)
            removed_placeholders.append(name)

    if removed_placeholders:
        print(f"  [MESH] Removed {len(removed_placeholders)} placeholder(s): "
              f"{removed_placeholders}")

    # --- Now compute what still needs appending ---
    existing_names = {o.name for o in bpy.data.objects}
    to_append = [n for n in STAGE_MESH_NAMES
                 if n not in existing_names and n not in STAGE_MESH_EXCLUDE]

    if not to_append:
        print(f"  [MESH] All {len(STAGE_MESH_NAMES)} stage meshes already exist, skipping")
        return 0

    # Snapshot before
    before = {str(o.name) for o in bpy.data.objects}
    to_append_copy = list(to_append)  # preserve strings (Blender may mutate list)

    # Load: pass names directly; Blender skips non-existent ones
    with bpy.data.libraries.load(stage_blend_path, link=False) as (data_from, data_to):
        data_to.objects = to_append_copy

    # Find newly loaded objects
    after = {str(o.name) for o in bpy.data.objects}
    new_names = after - before

    coll = bpy.context.scene.collection
    appended = 0
    for obj_name in new_names:
        obj = bpy.data.objects.get(obj_name)
        if obj and obj.type == 'MESH':
            # Link into scene collection if not already there
            if str(obj.name) not in {str(o.name) for o in coll.objects}:
                coll.objects.link(obj)
            # Force visibility (stage_output.blend should have them visible,
            # but ensure no carry-over of hidden flags)
            obj.hide_render = False
            obj.hide_viewport = False
            # Check View Layer membership (Blender 5.0 API)
            try:
                vl_obj = bpy.context.view_layer.objects.get(obj.name)
                if vl_obj is not None:
                    vl_obj.hide_viewport = False
            except AttributeError:
                pass
            appended += 1

    not_loaded = set(to_append_copy) - new_names
    if not_loaded:
        print(f"  [MESH] Not loaded (may not exist in stage): {sorted(str(x) for x in not_loaded)}")

    print(f"  [MESH] Appended {appended}/{len(to_append)} stage meshes "
          f"(excluded: {STAGE_MESH_EXCLUDE})")
    return appended


# =====================================================================
# [スポットライト] Stage LIGHT append helper
# =====================================================================
def _append_stage_lights(stage_blend_path):
    """Load stage_output.blend and append SP_ LIGHT objects into current scene.
    Uses bpy.data.libraries.load (Blender 5.0+ compatible)."""
    # [PORTABILITY] bpy.data.libraries.load() はBlender内部CWD基準で解決するため絶対パスに変換
    stage_blend_path = os.path.abspath(stage_blend_path)
    if not os.path.exists(stage_blend_path):
        print(f"  [SPOTLIGHT] stage file not found: {stage_blend_path}")
        return 0
    
    target_names = [
        "SP_Front_1", "SP_Front_2", "SP_Front_3", "SP_Front_4", "SP_Front_5",
        "SP_Back_1", "SP_Back_2", "SP_Back_3", "SP_Back_4", "SP_Back_5",
        "SP_Side_L", "SP_Side_R",
    ]
    
    existing_light_names = {o.name for o in bpy.data.objects if o.type == 'LIGHT'}
    to_append = [n for n in target_names if n not in existing_light_names]
    
    if not to_append:
        print(f"  [SPOTLIGHT] All {len(target_names)} SP_ lights already exist, skipping")
        return 0
    
    before = {str(o.name) for o in bpy.data.objects}
    to_append_copy = list(to_append)  # preserve strings (Blender may mutate list)
    
    with bpy.data.libraries.load(stage_blend_path, link=False) as (data_from, data_to):
        data_to.objects = to_append

    after = {str(o.name) for o in bpy.data.objects}
    new_names = after - before

    appended = 0
    for obj_name in new_names:
        obj = bpy.data.objects.get(obj_name)
        if obj and obj.type == 'LIGHT':
            coll = bpy.context.scene.collection
            if str(obj.name) not in {str(o.name) for o in coll.objects}:
                coll.objects.link(obj)
            appended += 1

    not_loaded = set(to_append_copy) - new_names
    if not_loaded:
        print(f"  [SPOTLIGHT] Not loaded (may not exist in stage): {sorted(str(x) for x in not_loaded)}")

    print(f"  [SPOTLIGHT] Appended {appended}/{len(to_append)} lights from stage")
    return appended


# =====================================================================
# [カメラ] Beat-Reactive カメラシステム
#   既存カメラを削除し、フォーカスEmpty(Track To) + 新規カメラを生成。
#   MIDIドラムの強さ/打鍵タイミングでレンズ焦点距離をパンチ駆動する。
#   (口パク・ドラムNLAとは独立したデータブロックにしか触れないため干渉しない)
# =====================================================================
import mathutils

CAMERA_SETTINGS = {
    'base_lens_mm':      28.0,            # 基本焦点距離: バスドラ手前(z≈1.0)〜頭頂(z≈2.61)がフレームに収まる中望遠
    'orbit_base_radius': 10.0,             # 基本軌道半径 (ドラマー中心からカメラ)
    'orbit_max_radius':  10.0,             # 最大パンチ半径 (velocity=1.0 時) — +40%
    'orbit_height':      -1.5,           # カメラ高さ=顔高さ (ドラマー中心 z=2.85 + (-1.01) → z≈1.84=頭中心)
    'subject_focus_z':   1.80,            # フォーカスEmptyのz=被写体(バスドラ手前〜頭頂)中心 → 顔高さからやや下向き
    'swing_center_deg':  -90.0,           # 中心角: ドラマー正面(=-Y方向)
    'swing_half_deg':     10.0,           # 往復の半開き ±60° (合計120°)
    'swing_period_beats': 32.0,           # 往復1周期 = 16拍 (sin往復)
    'punch_beats':       4.0,             # パンチの減衰期間 (1拍で基本半径へ戻す)
    'zoom_depth':        0.06,            # ズーム深度: ±6% lens variation
    'zoom_period_beats': 16.0,            # ズーム周期: 16拍で1往復 (sin波)
    'cam_name':          'BeatCam',
    'focus_name':        'BeatCam_Focus',
    'dof_aperture':      1.4,
}


def _camera_focus_point():
    """顔(口)のワールド座標をフォーカス基準として返す。
    親アーマチュア/ボーンに紐づいたオブジェクトでも matrix_world で正しく取得。"""
    # 現在のフレームで depsgraph 評価してワールド座標を得る
    depsgraph = bpy.context.evaluated_depsgraph_get()
    obj = bpy.data.objects.get(MOUTH_OBJ_NAME)
    if obj is not None:
        eval_obj = obj.evaluated_get(depsgraph)
        if eval_obj is not None:
            return mathutils.Vector(eval_obj.matrix_world.translation)
        # fallback: 直接 matrix_world
        if obj.matrix_world is not None:
            return mathutils.Vector(obj.matrix_world.translation)
    # フォールバック: ドラムアーマチャのhead/Neckボーン
    for o in bpy.data.objects:
        if o.type == 'ARMATURE' and o.pose:
            for bname in ("Head", "Neck"):
                if bname in o.pose.bones:
                    head = o.matrix_world @ o.pose.bones[bname].head
                    return mathutils.Vector(head)
    return mathutils.Vector((0.0, 0.0, 0.0))


def _camera_drummer_center():
    """ドラマー(アーマチュア)のワールド中心位置を取得。
    カメラ軌道の中心として使用する。顔より広い範囲(体全体)を見せるため
    アーマチュアの原点(通常はPelvis/Spine付近)を採用する。"""
    for o in bpy.data.objects:
        if o.type == 'ARMATURE':
            return mathutils.Vector(o.matrix_world.translation)
    # フォールバック: 顔の位置
    return _camera_focus_point()


def _estimate_bpm(drum_events, frame_end):
    """MIDIドラムイベントの間隔からBPMを推定。
    成功しなければ既定値 120 を返す。"""
    if not drum_events or len(drum_events) < 4:
        return 120.0
    frames = sorted(set(max(1, int(round(e['frame']))) for e in drum_events))
    gaps = [b - a for a, b in zip(frames, frames[1:])]
    if not gaps:
        return 120.0
    # 16分音符 = 拍/4 として推定
    from statistics import median
    med = median(gaps)
    if med < 2 or med > 120:
        return 120.0
    # med frames = 1拍/4 拍 なら bpm = (60 / (med/FPS)) * 4 / 4 -> 簡略化
    sec_per_gap = med / FPS
    # 最も多い刻みの仮定: 4分音符=1拍
    bpm_est = (60.0 / sec_per_gap) * 0.25  # gap=1/16拍 -> *0.25
    # 妥当範囲にクランプ
    bpm_est = max(60.0, min(200.0, bpm_est))
    return bpm_est


def build_beat_reactive_camera(drum_events, frame_end, midi_bpm=None):
    """既存カメラを削除し、Beat-Reactiveカメラ(ドラマー周りをMIDIビートと同期して
    軌道移動)を構築。レンズ焦点距離は固定(ズームなし)。
    ドラム打ち込みのvelocityで半径が外側にパンチし、1拍で基本半径に減衰。
    midi_bpmが与えられれば正確なBPMで同期(推定フォールバックは _estimate_bpm)。"""
    # --- [1] 既存カメラを削除 ---
    for obj in list(bpy.data.objects):
        if obj.type == 'CAMERA':
            try:
                data = obj.data
                bpy.data.objects.remove(obj, do_unlink=True)
                if data:
                    bpy.data.cameras.remove(data)
            except Exception as e:
                print(f"  [CAM] camera remove warn: {e}")

    # --- [2] 軌道中心 = ドラマー位置 ---
    center = _camera_drummer_center()

    # --- [3] フォーカスEmpty生成 (ドラマー位置) ---
    focus = bpy.data.objects.new(CAMERA_SETTINGS['focus_name'], None)
    focus.empty_display_size = 0.15
    focus.empty_display_type = 'PLAIN_AXES'
    # フォーカス = 被写体中心 (バスドラ手前 z≈1.0 〜 頭頂 z≈2.61 の中間).
    # カメラ(顔高さ z≈1.84)がこの点を向くことで「やや下向き」になり、
    # 画角にバスドラ手前からドラマーの頭までが収まる。
    focus.location = (center.x, center.y - 0.55, CAMERA_SETTINGS['subject_focus_z'])
    bpy.context.scene.collection.objects.link(focus)

    # --- [4] 新規カメラ生成 + Track To + DoF (レンズ固定) ---
    cam_data = bpy.data.cameras.new(CAMERA_SETTINGS['cam_name'])
    cam_data.lens = CAMERA_SETTINGS['base_lens_mm']
    cam_data.dof.use_dof = True
    cam_data.dof.focus_object = focus
    try:
        cam_data.dof.aperture_fstop = CAMERA_SETTINGS['dof_aperture']
    except Exception as _dof_e:
        print(f"  [CAM][WARN] aperture_fstop={CAMERA_SETTINGS['dof_aperture']} "
              f"set FAILED: {type(_dof_e).__name__}: {_dof_e} (keeping Blender default)")

    cam = bpy.data.objects.new(CAMERA_SETTINGS['cam_name'], cam_data)
    bpy.context.scene.collection.objects.link(cam)

    con = cam.constraints.new('TRACK_TO')
    con.target = focus
    con.track_axis = 'TRACK_NEGATIVE_Z'
    con.up_axis = 'UP_Y'

    bpy.context.scene.camera = cam

    # --- [5] 往復スイングキーフレーム (ビート同期) ---
    import math as _math
    if midi_bpm and midi_bpm > 0:
        bpm = float(midi_bpm)
    else:
        bpm = _estimate_bpm(drum_events, frame_end)
    sec_per_beat = 60.0 / bpm
    frames_per_beat = sec_per_beat * FPS

    base_r = CAMERA_SETTINGS['orbit_base_radius']
    max_r  = CAMERA_SETTINGS['orbit_max_radius']
    height = CAMERA_SETTINGS['orbit_height']
    punch_frames = max(2, int(round(CAMERA_SETTINGS['punch_beats'] * frames_per_beat)))

    swing_center = _math.radians(CAMERA_SETTINGS['swing_center_deg'])
    swing_half   = _math.radians(CAMERA_SETTINGS['swing_half_deg'])
    swing_period_frames = CAMERA_SETTINGS['swing_period_beats'] * frames_per_beat

    # ズーム設定
    zoom_depth = CAMERA_SETTINGS.get('zoom_depth', 0.0)
    zoom_period_frames = CAMERA_SETTINGS.get('zoom_period_beats', 32.0) * frames_per_beat
    base_lens = CAMERA_SETTINGS['base_lens_mm']

    # --- [5a] 全フレームで基本軌道位置を計算しキー ---
    if cam.animation_data is None:
        cam.animation_data_create()
    # 既存のlocation fcurvesをクリア (Blender 5.0: layers/strips/channelbags)
    if cam.animation_data.action:
        act = cam.animation_data.action
        for layer in act.layers:
            for lstrip in layer.strips:
                for cb in lstrip.channelbags:
                    for fc in list(cb.fcurves):
                        if fc.data_path in ('location', 'location.x', 'location.y', 'location.z'):
                            cb.fcurves.remove(fc)

    def _swing_angle_rad(frame):
        """往復スイングの角度 [rad]. sin波で往復する."""
        phase = 2.0 * _math.pi * (frame - 1) / swing_period_frames
        return swing_center + swing_half * _math.sin(phase)

    def _swing_pos(frame, radius, height_off):
        th = _swing_angle_rad(frame)
        x = center.x + radius * _math.cos(th)
        y = center.y + radius * _math.sin(th)
        z = center.z + height_off
        return (x, y, z)

    # 全フレームに往復スイング基本軌道 + ズームsin波をキー (1フレーム毎)
    n_frames = max(1, int(frame_end))
    for fr in range(1, n_frames + 1):
        px, py, pz = _swing_pos(fr, base_r, height)
        cam.location = (px, py, pz)
        cam.keyframe_insert(data_path='location', frame=fr)
        if zoom_depth > 0.0:
            phase = 2.0 * _math.pi * (fr - 1) / zoom_period_frames
            cam.data.lens = base_lens * (1.0 + zoom_depth * _math.sin(phase))
            cam.data.keyframe_insert(data_path='lens', frame=fr)

    # --- [5b] ドラムパンチ: hit で半径が外側に出る、hit+punch で基本半径に減衰 ---
    if drum_events:
        for ev in drum_events:
            hit = max(1, int(round(ev['frame'])))
            if hit > n_frames:
                continue
            vel = ev.get('velocity', 96) / 127.0
            punch_r = base_r + (max_r - base_r) * vel
            # hit 位置: スイング角度はそのフレームのまま、半径を punch_r に
            px, py, pz = _swing_pos(hit, punch_r, height)
            cam.location = (px, py, pz)
            cam.keyframe_insert(data_path='location', frame=hit)
            # hit+punch_frames で base_r に戻す (スイング角度はそのまま)
            fr_back = min(n_frames, hit + punch_frames)
            px, py, pz = _swing_pos(fr_back, base_r, height)
            cam.location = (px, py, pz)
            cam.keyframe_insert(data_path='location', frame=fr_back)

    # --- [5c] 滑らかな減衰 (bezier) ---
    if cam.animation_data.action:
        act = cam.animation_data.action
        for layer in act.layers:
            for lstrip in layer.strips:
                for cb in lstrip.channelbags:
                    for fc in cb.fcurves:
                        if fc.data_path in ('location', 'lens'):
                            for kp in fc.keyframe_points:
                                kp.interpolation = 'BEZIER'

    print(f"  [CAM] created '{cam.name}' orbit: center={tuple(round(c,3) for c in center)}")
    print(f"  [CAM] swing: center={CAMERA_SETTINGS['swing_center_deg']}° "
          f"half={CAMERA_SETTINGS['swing_half_deg']}° "
          f"period={CAMERA_SETTINGS['swing_period_beats']:.0f}beats")
    print(f"  [CAM] radius {base_r} -> {max_r} (punch on {len(drum_events)} drum hits)")
    if zoom_depth > 0.0:
        print(f"  [CAM] zoom: base={base_lens}mm ±{zoom_depth:.0%} "
              f"period={CAMERA_SETTINGS['zoom_period_beats']:.0f}beats")
    print(f"  [CAM] BPM={bpm:.1f}, {frames_per_beat:.0f} frames/beat")
    # [DIAG] 高さの実効値を明示: 次実行から「どのorbit_heightでビルドされたか」が一目で分かる
    print(f"  [CAM] orbit_height={height}  center.z={center.z:.4f}  => cam z = {center.z + height:.4f}")
    return cam

# [カメラ] マルチカメラシステム (multi_camera_system.py から import)
from multi_camera_system import build_multi_camera_system, build_zoom_camera




def reconcile_bpm(midi_bpm, xml_bpm):
    """Warn if BPMs differ; return the master BPM."""
    master = midi_bpm if BPM_MASTER == 'midi' else xml_bpm
    if abs(midi_bpm - xml_bpm) > 0.5:
        print(f"\n[WARN] BPM mismatch: MIDI={midi_bpm:.1f} XML={xml_bpm:.1f} "
              f"(master={BPM_MASTER} -> {master:.1f})")
        print("       The non-master side's timing will NOT be rescaled here; "
              "adjust the source file if sync is off.")
    else:
        print(f"\n[INFO] BPM consistent: MIDI={midi_bpm:.1f} XML={xml_bpm:.1f} "
              f"(master={BPM_MASTER} -> {master:.1f})")
    return master


# =====================================================================
# Main
# =====================================================================
def main():
    print("=" * 60)
    print("  Drummer Lipsync Unified Animator")
    print("=" * 60)
    print(f"  MIDI      : {MIDI_FILE}")
    print(f"  MusicXML  : {MUSICXML}")
    print(f"  Base      : {BASE_BLEND}")
    print(f"  Output    : {OUTPUT}")
    print(f"  FPS       : {FPS}")
    print(f"  BPM master: {BPM_MASTER}")
    print()

    for f in (MIDI_FILE, MUSICXML, BASE_BLEND):
        if not os.path.exists(f):
            print(f"[ERROR] File not found: {f}")
            sys.exit(1)

    # [1] Parse both data sources
    print("\n[1] Parsing MIDI (drum)...")
    drum_events, midi_bpm, _mid, _max_tick, _tpb, midi_total_measures = load_midi_drum_track(MIDI_FILE)

    print("\n[2] Parsing MusicXML (lipsync)...")
    segments, total_sec = parse_segments(MUSICXML, BPM_DEFAULT)
    eye_events, _ = parse_eye_directives(MUSICXML, BPM_DEFAULT)
    xml_bpm = parse_tempo_bpm(ET.parse(MUSICXML).getroot(), BPM_DEFAULT)
    print(f"  [LIPSYNC] {len(segments)} mouth segments, {len(eye_events)} eye events "
          f"(BPM={xml_bpm:.1f}, duration={total_sec:.2f}s)")

    # [3] Reconcile BPM
    reconcile_bpm(midi_bpm, xml_bpm)

    # [4] Open base + build NLA (drums)
    print("\n[3] Opening base + building NLA animation (drums)...")
    armature = open_base_and_find_armature()
    drum_end = create_nla_animation(armature, drum_events)

    # [5] Build lipsync (material fcurves) - uses same opened scene
    print("\n[4] Building lipsync material fcurves (face)...")
    lipsync_end = setup_face_lipsync(segments, eye_events, xml_bpm, total_sec)

    # [6] Reconcile scene frame range
    scene_end = max(drum_end, lipsync_end) + 5
    bpy.context.scene.frame_start = 1
    bpy.context.scene.frame_end = scene_end
    bpy.context.scene.frame_current = 1
    print(f"\n[INFO] Scene frame range: 1 - {scene_end} "
          f"(drum_end={drum_end}, lipsync_end={lipsync_end})")

    # [4.5] Build animated drum set (physical vibration) - same opened scene
    print("\n[4.5] Building animated drum set (cymbal/ohh/bass/kick physics)...")
    try:
        dsa.clear_animated_drum()
        dsa_handles = dsa.build_animated_drum_set(drum_events, frame_end=scene_end)
        print(f"  [DRUMSET] handles={list(dsa_handles.keys())} "
              f"bass_center={dsa.BASS_POS}")
    except Exception as e:
        import traceback
        print(f"  [DRUMSET] *** build_animated_drum_set FAILED: {type(e).__name__}: {e} ***")
        traceback.print_exc()
        dsa_handles = None

    # [6.5] Stage meshes - append all physical stage objects
    print("\n[6.5] Stage meshes: appending physical stage objects...")
    try:
        _append_stage_meshes(STAGE_BLEND)
    except Exception as e:
        import traceback
        print(f"  [MESH] *** Stage mesh append FAILED: {type(e).__name__}: {e} ***")
        traceback.print_exc()

    # [6] Spotlight - append LIGHT objects from stage + keyframe from MIDI
    print("\n[6] Spotlight: appending stage LIGHTs + building MIDI-driven keyframes...")
    try:
        _append_stage_lights(STAGE_BLEND)
        # §11-4 ベースMIDI: ドラム演出【前】にアンビエント呼吸レイヤーを敷き、
        # ドラムピーク(下面)がアクセントとして上書きする構造を作る
        if os.path.exists(BASE_MIDI):
            # ベース呼吸レイヤーを先に敷く（内部で全ライトを初期化/クリアする）
            spotlight.setup_base_midi_spotlights(base_midi_path=BASE_MIDI, fps=FPS)
            # ドラムピークを「追加」で打鍵（ベース呼吸レイヤーを保持）
            spotlight.setup_long_range_spotlights(midi_path=MIDI_FILE, fps=FPS, clear_first=False)
        else:
            print(f"  [BASE-MIDI] skip (not found): {BASE_MIDI}")
            spotlight.setup_long_range_spotlights(midi_path=MIDI_FILE, fps=FPS)
        # Verify keyframe count
        light_kf_count = 0
        for obj in bpy.data.objects:
            if obj.type != 'LIGHT' or not obj.data.animation_data:
                continue
            act = obj.data.animation_data.action
            if not act:
                continue
            # Try old API first, then new API (Blender 5.0)
            try:
                light_kf_count += len(act.fcurves)
            except (AttributeError, TypeError):
                try:
                    for layer in act.layers:
                        for strip in layer.strips:
                            for cb in strip.channelbags:
                                light_kf_count += len(cb.fcurves)
                except (AttributeError, TypeError):
                    pass
        print(f"  [SPOTLIGHT] {len(spotlight.ALL_LIGHT_NAMES)} lights, "
              f"{light_kf_count} total fcurves")
    except Exception as e:
        import traceback
        print(f"  [SPOTLIGHT] *** setup FAILED: {type(e).__name__}: {e} ***")
        traceback.print_exc()

    # [6.8a] [CAM-REBUILD] シーンプロパティにカメラ再構築用データを保存
    # rebuild_cameras_from_json.py が .blend を開いた後でこれを使用する
    bpy.context.scene["drum_events_json"] = json.dumps(drum_events)
    bpy.context.scene["midi_bpm"] = float(midi_bpm)
    bpy.context.scene["cam_scene_end"] = int(scene_end)
    # [小節数] rebuild_cameras_from_json.py がMidi小節数でカメラ切替制御するための全曲小節数
    bpy.context.scene["midi_total_measures"] = int(midi_total_measures)
    bpy.context.scene["midi_beats_per_measure"] = 4  # 4/4拍
    bpy.context.scene["midi_ref"] = MIDI_FILE  # 参照Midiパス (フォールバック用)
    print(f"  [CAM-REBUILD] Saved {len(drum_events)} drum_events + bpm={midi_bpm} "
          f"+ total_measures={midi_total_measures} to scene props")

    # [6.8] Camera system (multi | beat-reactive | off)
    cam_mode = str(CFG.get('camera', 'multi')).lower()
    if cam_mode == 'multi':
        print("\n[6.8] Building 5-camera multi-camera system...")
        shots_json = str(CFG.get('shots-json', ''))
        if shots_json and not os.path.isabs(shots_json):
            shots_json = os.path.abspath(shots_json)
        try:
            build_multi_camera_system(
                drum_events, scene_end,
                midi_bpm=midi_bpm,
                center=_camera_drummer_center(),
                shots_json_path=shots_json if shots_json else None,
            )
        except Exception as e:
            import traceback
            print(f"  [MULTI-CAM] *** build FAILED: {type(e).__name__}: {e} ***")
            traceback.print_exc()
    elif cam_mode == 'beat-reactive':
        print("\n[6.8] Building beat-reactive camera...")
        try:
            build_beat_reactive_camera(drum_events, scene_end, midi_bpm=midi_bpm)
        except Exception as e:
            import traceback
            print(f"  [CAM] *** build FAILED: {type(e).__name__}: {e} ***")
            traceback.print_exc()
    else:
        print("\n[6.8] Camera: disabled (camera=off)")

    # [6.9] Unlock all objects (Blender 5.0 lock_* are 3-value sequences)
    print("\n[6.9] Unlocking all objects + ensuring viewport visibility...")
    unlocked = 0
    for obj in bpy.data.objects:
        try:
            obj.lock_location = (False, False, False)
            obj.lock_rotation = (False, False, False)
            obj.lock_scale = (False, False, False)
            unlocked += 1
        except (TypeError, ValueError):
            try:
                obj.lock_location = False
                obj.lock_rotation = False
                obj.lock_scale = False
                unlocked += 1
            except Exception:
                pass
        if obj.hide_viewport:
            obj.hide_viewport = False
    # Also fix collection-level flags
    for coll in bpy.data.collections:
        if coll.hide_viewport:
            coll.hide_viewport = False
    # Fix view layer exclude
    def _fix_vl(lc):
        if lc.exclude:
            lc.exclude = False
        if lc.hide_viewport:
            lc.hide_viewport = False
        for c in lc.children:
            _fix_vl(c)
    _fix_vl(bpy.context.view_layer.layer_collection)
    print(f"  [UNLOCK] {unlocked} objects unlocked")

    # [7] Save
    print(f"\n[7] Saving -> {OUTPUT}")
    # [PORTABILITY] 保存前に全外部リソースパスを相対パスに強制
    # (Linux移植時、.blend同梱のPNGが絶対パスだと破断するため)
    bpy.ops.file.make_paths_relative()
    bpy.ops.wm.save_mainfile(filepath=OUTPUT)
    print(f"[DONE] -> {OUTPUT}")


if __name__ == "__main__":
    main()