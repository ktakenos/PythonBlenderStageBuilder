import bpy
import os
import mido

# ==========================================
# 設定パラメータ
# ==========================================
MIDI_FILE_PATH = "drum_pattern.mid"             # サンプルMIDI (BPM=120, GM ch10)
BASE_MIDI_FILE = "bass_pattern.mid"             # ベースパート MIDI (melodic, ch0, BPM=120)
DRUM_CHANNEL = 9                                 # ドラムチャンネル (0-indexed: Channel 10 = 9)

# ライトグループ (12本: Front5 + Back5 + Side_L/R)
LIGHTS = {
    'FRONT':  ["SP_Front_1", "SP_Front_2", "SP_Front_3", "SP_Front_4", "SP_Front_5"],
    'BACK':   ["SP_Back_1", "SP_Back_2", "SP_Back_3", "SP_Back_4", "SP_Back_5"],
    'LONG_RANGE_L': ["SP_Side_L"], # 客席後方 左
    'LONG_RANGE_R': ["SP_Side_R"]  # 客席後方 右
}

ALL_LIGHT_NAMES = LIGHTS['FRONT'] + LIGHTS['BACK'] + LIGHTS['LONG_RANGE_L'] + LIGHTS['LONG_RANGE_R']

def set_light_keyframe(light_name, frame, energy, color=None):
    """指定したライトの輝度と色にキーフレームを打つヘルパー関数"""
    obj = bpy.data.objects.get(light_name)
    if not obj or obj.type != 'LIGHT':
        return
    
    light = obj.data
    light.energy = energy
    light.keyframe_insert(data_path="energy", frame=frame)
    
    if color:
        light.color = color
        light.keyframe_insert(data_path="color", frame=frame)

def setup_long_range_spotlights(midi_path=None, fps=30.0, clear_first=True):
    """MIDIドラムパートからスポットライトキーフレームを生成。
    
    Args:
        midi_path: MIDIファイルパス（Noneなら MIDI_FILE_PATH を使用）
        fps: フレームレート（デフォルト30）
        clear_first: True で既存の全キーフレームをクリアしてから打つ。
                     False で既存（=ベース呼吸レイヤー）の上に追加打鍵する。
    """
    path = midi_path or MIDI_FILE_PATH
    mid = mido.MidiFile(path)
    current_tempo = 500000  # 初期値 120BPM → MIDIのset_tempoで上書き
    
    # 1. 全ライトのビーム角を最適化（ステージ全体を照らす前提で輪郭を明確化）
    import math
    _SPOT_SIZE_MAP = {
        'FRONT':  math.radians(35),   # 20°半角: 幅を絞って輪郭を明確化
        'BACK':   math.radians(25),   # 12°半角: 後方照射の輪郭
        'LONG_RANGE_L': math.radians(20),
        'LONG_RANGE_R': math.radians(20),
    }
    for group, size in _SPOT_SIZE_MAP.items():
        for name in LIGHTS[group]:
            obj = bpy.data.objects.get(name)
            if obj and obj.type == 'LIGHT':
                obj.data.spot_size = size
                obj.data.spot_blend = 0.15  # 適度なエッジ柔らかさ

    # 2. アニメーション初期化 (1フレーム目を消灯)
    #    clear_first=True : 既存キーフレームを全消ししてドラム演出だけで再構築
    #    clear_first=False: 既存（ベース呼吸レイヤー）を残したまま追加打鍵（=ピーク重ね）
    if clear_first:
        for name in ALL_LIGHT_NAMES:
            obj = bpy.data.objects.get(name)
            if obj and obj.type == 'LIGHT':
                if obj.data.animation_data:
                    obj.data.animation_data_clear()
                set_light_keyframe(name, 1, 0.0)

    lr_toggle = False  # 左右交互フラグ

    # 3. MIDIの解析とライティング割り当て
    for track in mid.tracks:
        current_time_sec = 0.0
        
        for msg in track:
            current_time_sec += mido.tick2second(msg.time, mid.ticks_per_beat, current_tempo)
            
            if msg.type == 'set_tempo':
                current_tempo = msg.tempo
                
            if hasattr(msg, 'channel') and msg.channel == DRUM_CHANNEL and msg.type == 'note_on' and msg.velocity > 0:
                frame = int(current_time_sec * fps) + 1
                vel_ratio = msg.velocity / 127.0
                note = msg.note
                
                # --- A. バスドラム (Kick) -> 前面4個 (ローエンドのドカンとした発光) ---
                if note in [35, 36]:
                    for name in LIGHTS['FRONT']:
                        set_light_keyframe(name, frame, 3000.0 * vel_ratio, (1.0, 0.9, 0.8))
                        set_light_keyframe(name, frame + 3, 0.0) # パッと消える

                # --- B. スネアドラム (Snare) -> 客席後方からのロングピンスポット（左右交互照射） ---
                # 距離が遠いため輝度（MAX 15000W等）を強めに設定
                elif note in [38, 40]:
                    target = LIGHTS['LONG_RANGE_L'][0] if lr_toggle else LIGHTS['LONG_RANGE_R'][0]
                    lr_toggle = not lr_toggle
                    
                    # 蒼白い強烈なビームを中央へ投射
                    set_light_keyframe(target, frame, 12000.0 * vel_ratio, (0.8, 0.9, 1.0))
                    set_light_keyframe(target, frame + 6, 0.0) # 余韻を持たせて衰退

                # --- C. タム類 (Toms) -> 背後5個 (音高で左から右へチェイス) ---
                elif note in [41, 43, 45, 47, 48, 50]:
                    if note == 41:       tom_index = 4  # Low Floor Tom -> 右端
                    elif note == 43:     tom_index = 3  # Low Tom
                    elif note == 45:     tom_index = 2  # High Tom -> 中央
                    elif note == 47:     tom_index = 1  # Hi-Mid Tom
                    elif note == 48:     tom_index = 0  # Lo-Mid Tom -> 左端
                    else:               tom_index = 2  # 50: 中央共有
                    target_back = LIGHTS['BACK'][tom_index]
                    set_light_keyframe(target_back, frame, 2500.0 * vel_ratio, (0.1, 0.5, 1.0))
                    set_light_keyframe(target_back, frame + 4, 0.0)

                # --- D. クラッシュ/キメ (Crash) -> 全12灯一斉全灯（劇的なクロス） ---
                elif note in [49, 51, 57]:
                    # 全ライトを金色に発光
                    for name in ALL_LIGHT_NAMES:
                        # 客席後方ライトは距離があるため輝度倍増
                        power = 20000.0 if "Side" in name else 4000.0
                        set_light_keyframe(name, frame, power * vel_ratio, (1.0, 0.85, 0.4))
                        set_light_keyframe(name, frame + 12, 0.0) # スローフェードアウト

    print("[6] Spotlight: ライティング自動化完了 (12灯)")


def setup_base_midi_spotlights(base_midi_path=None, fps=30.0):
    """§11-4 ベースMIDI演出: メロディック/ローパートを「アンビエント呼吸レイヤー」に変換。

    - ベース音高(40-71) → FRONT 5灯のピッチチェイス（低音=左、高音=右）
    - velocity → 控えめな暖色エネルギー（MAX ~1500W）でフロアー発光
    - 長いフェード(~20f) で「呼吸感」を作り、ドラムピーク(§11-4/既存)がアクセントに
    - 呼び出し順序: ドラム演出【前】に呼ぶ（ドラムが上書き=ピーク、ベースは間を埋める床）
    """
    path = base_midi_path or BASE_MIDI_FILE
    if not os.path.exists(path):
        print("[6b] BaseMIDI Spotlight: スキップ (ファイル不存在) ->", path)
        return

    mid = mido.MidiFile(path)
    current_tempo = 500000
    NOTE_MIN, NOTE_MAX = 29, 48          # サンプルbass_pattern.midの音域 (F1〜C3)
    span = max(1, NOTE_MAX - NOTE_MIN)
    front_n = len(LIGHTS['FRONT'])
    base_count = 0

    # 初期化（呼吸レイヤーは土台レイヤーなので、既存をクリアして1フレーム目を消灯）
    for name in ALL_LIGHT_NAMES:
        obj = bpy.data.objects.get(name)
        if obj and obj.type == 'LIGHT':
            if obj.data.animation_data:
                obj.data.animation_data_clear()
            set_light_keyframe(name, 1, 0.0)

    for track in mid.tracks:
        current_time_sec = 0.0
        for msg in track:
            current_time_sec += mido.tick2second(msg.time, mid.ticks_per_beat, current_tempo)
            if msg.type == 'set_tempo':
                current_tempo = msg.tempo
            if (hasattr(msg, 'channel') and msg.type == 'note_on' and msg.velocity > 0
                    and hasattr(msg, 'note')):
                note = msg.note
                if not (NOTE_MIN <= note <= NOTE_MAX):
                    continue
                frame = int(current_time_sec * fps) + 1
                vel_ratio = msg.velocity / 127.0
                # 音高 → 前面ライトの位置 (低音=0/左 … 高音=末端/右)
                pitch_ratio = (note - NOTE_MIN) / span
                idx = min(front_n - 1, int(pitch_ratio * front_n))
                name = LIGHTS['FRONT'][idx]
                # 音高で色温度を微変化: 低音=暖(橙), 高音=やや冷(白青) → 音楽的グラデーション
                warm = (1.0, 0.82, 0.62)
                cool = (0.72, 0.84, 1.0)
                color = tuple(warm[i] + (cool[i] - warm[i]) * pitch_ratio for i in range(3))
                energy = 1500.0 * vel_ratio     # 控えめ: 床レイヤー (ドラムピークより下)
                set_light_keyframe(name, frame, energy, color)
                set_light_keyframe(name, frame + 20, 0.0)  # 長いフェード=呼吸
                base_count += 1

    print(f"[6b] BaseMIDI Spotlight: 完了 (notes={base_count}, フロア=FRANT, 呼吸レイヤー)")
# 注意: 統合スクリプトから setup_long_range_spotlights() を呼ぶ。単体実行時は以下をコメント解除
# setup_long_range_spotlights()
