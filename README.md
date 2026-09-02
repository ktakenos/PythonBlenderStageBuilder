# Drummer Lipsync Unified Pipeline (Blender 5.x)

An integrated animation pipeline for Blender 5.x. In a single run it fully combines:
the drummer figure (Armature NLA), drum-kit physics animation (MIDI-triggered),
vocal lip-sync (MusicXML), a bass-MIDI ambient "breathing" layer, Roughness sync,
and MIDI-driven spotlights — and outputs `final_output.blend`.

## Authorship

This repository was created with the assistance of **local LLMs**.
The models used during development were:

| Model | Note |
|---|---|
| `Qwen3.8:27b` | main model |
| `qwen2.5-coder:30b` | used at the start |
| `qwen3.6:27b` | also used |
| `gemma4:31b` | also used |


## Requirements

- **Windows / Linux** / Blender **5.0** (5.x series; assumes `bpy.ops.object.shade_smooth_by_angle`, etc.)
- Python 3 (the one bundled with Blender). Install `mido` into the **Blender-bundled Python**:
  - Windows:
    ```
    "C:\Program Files\Blender Foundation\Blender 5.0\python.exe" -m pip install mido
    ```
  - Linux:
    ```
    /path/to/blender/5.0/python/bin/python -m pip install mido
    ```

## File Structure

| File | Role |
|---|---|
| `run_stage.py` | **Step 1** — builds the whole stage (from the `staging/` package) and saves `stage_output.blend` |
| `staging/` | Stage modeling package (each module described below) |
| `staging/stage_platform.py` | Stage platform (floor + stairs + railings) |
| `staging/truss_system.py` | Truss structure (overhead metal frames) |
| `staging/spotlight_system.py` | Spotlights (housing mesh + light), full lighting rig |
| `staging/speaker_system.py` | PA / guitar & bass amps / floor monitors |
| `staging/drum_set_system.py` | Full drum kit + drummer chair |
| `staging/mic_stand_system.py` | Mic stands (straight / boom) |
| `staging/back_wall.py` | Back & side walls + ceiling (cyclorama) |
| `staging/curtain.py` | Stage curtains |
| `staging/audience_floor.py` | Audience (F) floor |
| `staging/volume_scatter.py` | Volume-scatter box for visible light beams |
| `drummer_lipsync_unified.py` | **Step 2** — applies all animation subsystems in sequence |
| `drum_set_animator.py` | Drum-part MIDI-triggered physics (OHH / cymbals / bass head / kick) |
| `Midi2BlenderSpotlight.py` | MIDI-driven spotlights |
| `multi_camera_system.py` | Multi-camera switching system (JSON-driven) |
| `rebuild_cameras_from_json.py` | **Step 3** — rebuilds cameras from `shots_sample.json` (run in Blender GUI) |
| `register_multicam_handler.py` | **Step 3** — re-registers the camera-switch handler + test-render setup (run in Blender GUI) |
| `run_stage.bat` | **Step 1** runner (Windows) — runs `run_stage.py` with defaults |
| `run_stage.sh` | **Step 1** runner (Linux / macOS) — runs `run_stage.py` with defaults |
| `run_final_output.bat` | **Step 2** runner (Windows) — runs `drummer_lipsync_unified.py` with defaults |
| `run_final_output.sh` | **Step 2** runner (Linux / macOS) — runs `drummer_lipsync_unified.py` with defaults |
| `Drummer_Home-Position_Face.blend` | Base figure (armature + face textures + Idle Action) |
| `stage_output.blend` | Stage setup (lights / meshes) — produced by `run_stage.py` |
| `drum_pattern.mid` | Drum MIDI — short sample (playing timing) |
| `bass_pattern.mid` | Bass MIDI — short sample (ambient breathing layer) |
| `vocal_melody.musicxml` | Lip-sync MusicXML — short sample (lyric timing) |
| `ZundamonMiniMouth*.png` / `ZundamonMiniEyes*.png` | Mouth / eye textures (Albedo + Roughness) |
| `shots_sample.json` | Camera definitions + shot list (measure-based) |

## How to Run (Procedure)

> **FPS is unified at 60.** Use `--fps 60` everywhere (it is the default in
> `drummer_lipsync_unified.py`, in the runner scripts, and in the direct command).

The workflow has **3 steps**. Steps 1 and 2 run headless (command line).
**Step 3 (camera work) is run inside the Blender GUI *after* the stage and the figure
have been generated** — you open the finished `.blend` and load + run the camera script.

### Step 1 — Generate the stage (`run_stage.py`)

Build the full stage set from the `staging/` package and save `stage_output.blend`.
This is the **starting point** of the whole workflow.

```bash
blender -b -P run_stage.py
# To change the output path:
blender -b -P run_stage.py -- --output /path/to/stage_output.blend
```

> **Convenience runners** (run `run_stage.py` with defaults and save `stage_output.blend`):
> - Windows: double-click `run_stage.bat`
> - Linux / macOS: `./run_stage.sh`
>
> Both set the working directory to the repo root and locate Blender via `BLENDER_EXE`
> (the `.bat` uses a hardcoded path; the `.sh` honors the `BLENDER_EXE` environment variable).

What `run_stage.py` builds (in order, from the `staging/` package):

1. **Stage platform** (`staging/stage_platform.py`) — floor, stairs, railings
2. **Truss system** (`staging/truss_system.py`) — overhead metal frames
3. **Speakers** (`staging/speaker_system.py`) — PA x2, guitar/bass amps, floor monitors x5
4. **Spotlights** (`staging/spotlight_system.py`) — front 5 + back 5 + side 2, with housing mesh
5. **Drum set + drummer chair** (`staging/drum_set_system.py`)
6. **Mic stands** (`staging/mic_stand_system.py`) — vocal x6, drum x2
7. **Walls + ceiling** (`staging/back_wall.py`) — back/side cyclorama + ceiling
8. **Curtains x6** (`staging/curtain.py`)
9. **Audience floor** (`staging/audience_floor.py`)
10. **Volume-scatter box** (`staging/volume_scatter.py`) — makes the light beams visible
11. **Default camera + ceiling area light**

The result `stage_output.blend` is fed into Step 2 via `--stage`.

### Step 2 — Generate the figure + animation

Combine the stage with the drummer figure and apply all animation (drum physics,
lip-sync, bass ambient layer, spotlights, roughness). Uses the **short sample**
MIDI/MusicXML files bundled in the repo.

**Windows:**
```bat
run_final_output.bat
```

**Linux / macOS:**
```bash
chmod +x run_final_output.sh
./run_final_output.sh
```

- Before running, set `BLENDER_EXE` in the script to your Blender executable path
  (on Linux you can also override it: `BLENDER_EXE=/path/to/blender ./run_final_output.sh`).
- The log goes to `unified_test_log.txt`; `=== EXIT CODE: 0 ===` means success.
- The output `final_output.blend` is created in the same directory.
- The runner scripts pass `--camera off`, so the camera is **not** built here — see Step 3.

### Step 3 — Camera work (in Blender, after Step 1 + Step 2)

> **The camera is not produced by the headless run.** After the stage and figure are
> generated, open the finished `.blend` in the Blender GUI and load + run the camera
> script to build the cameras and register the frame-by-frame switching handler.

1. Open `final_output.blend` in Blender.
2. **Scripting** workspace → **Open** → `rebuild_cameras_from_json.py` → **Run Script**.
   - Reads `shots_sample.json` and rebuilds the cameras using the drum events / BPM /
     measure count that Step 2 saved into the scene
     (`drum_events_json` / `midi_bpm` / `cam_scene_end` / `midi_total_measures`).
   - To test a different camera layout, change the `SHOTS_JSON` variable at the top of the script.
3. **Scripting** → **Open** → `register_multicam_handler.py` → **Run Script**.
   - Re-registers the `frame_change_post` handler that swaps `scene.camera` per shot,
     and sets a low-res test render configuration.
4. In **Output Properties**, set the output (Video → MP4 + folder), then press **Ctrl+F12** to render.

## What the unified pipeline (Step 2) does

1. **Bass MIDI (§11-4)** — applies the notes of `bass_pattern.mid` as an ambient
   "breathing" layer on the FRONT 5 lights (coexists with the drum-peak fcurves via the
   override structure)
2. **Roughness sync (§11-5)** — keyframes the 9 `_Roughness.png` maps (Mouth 6 + Eyes 3)
   as a Roughness chain (MixRGB) running in parallel to the Albedo chain
3. **Unlock (§6.9)** — resets `lock_location/rotation/scale` on all objects and clears
   collection / view-layer `hide_viewport` / `exclude` (so locks don't reappear on re-runs)

## Camera system (Step 3 detail)

The multi-camera system (`multi_camera_system.py`) generates 5 default cameras
(Wide / Medium / Close / OverShoulder / Top) and switches `scene.camera` automatically
via a `bpy.app.handlers.frame_change_post` handler. Each camera orbits the drummer's
center, with a subtle sine micro-swing + MIDI punch kept in sync.

| Camera | Angle center | Radius | Lens | Use |
|---|---|---|---|---|
| Cam_Wide | -90° (front) | 12m | 24mm | Whole stage |
| Cam_Medium | -45° (left diagonal) | 8m | 35mm | Upper body / stick work |
| Cam_Close | -90° (front) | 4m | 65mm | Lip-sync / face close-up |
| Cam_OverShoulder | -135° (back-right) | 6m | 45mm | Over-the-shoulder angle |
| Cam_Top | -90° (top-down) | 7m / h+3m | 30mm | Bird's-eye / stage layout |

> `shots_sample.json` also defines a 6th camera (`Cam_Low`) on top of these defaults.

**Camera modes (in-run options for Step 2, if you skip Step 3):**
- `--camera multi` — build the multi-camera system during the pipeline run
- `--camera beat-reactive` — a single camera swings around the drummer and punches outward on drum velocity
- `--camera off` — disabled (this is what the runner scripts use; do Step 3 instead)

### Custom shot list (JSON)

Control camera definitions and shot layout with `--shots-json <file.json>` (Step 2)
or the `SHOTS_JSON` variable (Step 3). Sample: `shots_sample.json`.

**2-layer format (cameras + shots), measure-based:**

```json
{
  "cameras": {
    "Cam_Wide": {
      "angle_center_deg": -90.0,
      "swing_half_deg": 10.0,
      "height_offset": -1.2,
      "radius": 12.0,
      "lens_mm": 24.0,
      "punch_scale": 0.0
    }
  },
  "shots": [
    { "cam": "Cam_Wide",   "measure": 1 },
    { "cam": "Cam_Medium", "measure": 3 }
  ]
}
```

**`cameras` section — camera definitions:**

| Field | Type | Description |
|---|---|---|
| `angle_center_deg` | float | Center angle (deg); -90°=front, -45°=left diagonal |
| `swing_half_deg` | float | Half-opening of the micro-swing (deg) |
| `height_offset` | float | Height offset from the drummer center (m) |
| `radius` | float | Orbit radius (m) |
| `lens_mm` | float | Focal length (mm) |
| `punch_scale` | float | Drum punch intensity (0.0-1.0) |

**`shots` section — shot list (measure-based):**

| Field | Type | Description |
|---|---|---|
| `cam` | string | A key from the `cameras` definitions |
| `measure` | int | Measure (1-indexed) at which this shot **starts**; it runs until the next shot's measure (or to the end of the song for the last one) |

> **Legacy frame-based format is still supported** for backward compatibility:
> `{ "cam": "Cam_Wide", "start": 1, "end": 960 }` (and the plain-array form
> `[ { "cam": ..., "start": ..., "end": ... } ]`). When cameras are not defined in the
> JSON, `DEFAULT_CAMERAS` in `multi_camera_system.py` are used.

**Measure → frame calculation** (BPM=120, FPS=60):
- 1 beat = 0.5 s = 30 frames
- 1 measure (4 beats) = 120 frames
- So `measure: 1` starts at frame 1, `measure: 3` starts at frame 241 — the first shot
  (measure 1) covers frames 1–240 (measures 1–2).

When no shot list is given, the cameras are auto-cycled **4 measures at a time** in the
order they are defined. Start from `shots_sample.json` and adjust each `measure` to match
your song's structure.

## Direct command (Step 2, manual)

```bash
blender --background --python drummer_lipsync_unified.py -- \
  --midi drum_pattern.mid \
  --base-midi bass_pattern.mid \
  --musicxml vocal_melody.musicxml \
  --base Drummer_Home-Position_Face.blend \
  --output final_output.blend \
  --fps 60 \
  --stage stage_output.blend \
  --camera off
```

> **Convenience runners** (run Step 2 with the defaults shown above):
> - Windows: double-click `run_final_output.bat`
> - Linux / macOS: `./run_final_output.sh`

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: mido` | Run `pip install mido` with the Blender-bundled Python |
| `ModuleNotFoundError: drum_set_system` | Ensure `staging/` is at the same level as `drum_set_animator.py` |
| `bpy.ops.object.shade_smooth_by_angle` undefined | You must be using Blender 5.x |
| `[ERROR] Blender not found` | Fix `BLENDER_EXE` in `run_final_output.bat` / `run_final_output.sh` |
| `./run_final_output.sh: Permission denied` (Linux) | Run `chmod +x run_final_output.sh` |