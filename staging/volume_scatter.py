# -*- coding: utf-8 -*-
"""volume_scatter.py - 舞台空間にVolume Scatterを適用して照明ビームを実現"""
import bpy


def create_stage_volume(scene: bpy.types.Scene,
                        width: float = 12.0,
                        depth: float = 14.0,
                        height: float = 6.0,
                        location: tuple = (0.0, -3.0, 3.0),
                        density: float = 0.15,
                        color: tuple = (1.0, 1.0, 1.0),
                        mean_free_path: float = 0.1,
                        anisotropy: float = 0.8):
    """
    舞台空間全体を覆うVolume Scatterボックスを作成。

    Args:
        scene: Blenderシーン
        width: ボックス幅 (X軸)
        depth: ボックス奥行 (Y軸)
        height: ボックス高さ (Z軸)
        location: ボックス中心位置
        density: 散乱密度（低すぎるとビームが見えない、高すぎてもやもやはいる）
        color: 散乱色（白光なら白、温かい光なら少し黄色めなど）
        mean_free_path: 平均自由行程（小さいほど散乱が強い。0.1=霧状、1.0=薄い空気）
        anisotropy: 前方散乱の偏り (-1後方〜1前方)。0.8=光筋がはっきり見える

    Returns:
        VolumeボックスのObject
    """
    # --- ボックスメッシュ作成 ---
    bpy.ops.mesh.primitive_cube_add(
        size=1,
        location=location
    )
    box_obj = bpy.context.active_object
    box_obj.name = "Stage_Volume_Box"
    box_obj.scale = (width, depth, height)

    # --- デフォルトマテリアルを全削除（Blenderが自動割り当てするMaterial.001などをクリア）---
    while box_obj.data.materials:
        box_obj.data.materials.pop(index=0)

    # --- Material: Volume Scatter（SurfaceなしでVolumeのみ）---
    mat = bpy.data.materials.new(name="Stage_Volume_Scatter")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    node_pv = nodes.new('ShaderNodeVolumePrincipled')
    node_output = nodes.new('ShaderNodeOutputMaterial')

    node_pv.location = (-300, 0)
    node_pv.name = "Principled Volume"
    node_output.location = (200, 0)

    # Principled Volumeパラメータ設定（Blender 5.0 入力名）
    node_pv.inputs['Color'].default_value = (*color, 1.0)
    node_pv.inputs['Density'].default_value = density
    node_pv.inputs['Anisotropy'].default_value = anisotropy
    node_pv.inputs['Absorption Color'].default_value = (1.0, 1.0, 1.0, 1.0)

    # Volume出力をVolume入力に接続（Surfaceは空のまま＝透明）
    links.new(node_pv.outputs['Volume'], node_output.inputs['Volume'])

    # --- Shadow ModeをNONEに設定（ボックス表面をレンダリングしない）---
    try:
        mat.shadow_method = 'NONE'
    except Exception:
        pass  # Blenderバージョンによっては属性が存在しない場合がある

    # --- Materialをボックスに適用 ---
    box_obj.data.materials.append(mat)

    # --- Worldも少しScatter（舞台外の空気感）---
    world = scene.world
    if world is None:
        world = bpy.data.worlds.new("World")
        scene.world = world
    world.use_nodes = True
    wnodes = world.node_tree.nodes
    wlinks = world.node_tree.links
    wnodes.clear()

    node_bg = wnodes.new('ShaderNodeBackground')
    node_vol = wnodes.new('ShaderNodeVolumeScatter')
    node_output_w = wnodes.new('ShaderNodeOutputWorld')

    node_bg.location = (-400, 100)
    node_vol.location = (-400, -100)
    node_output_w.location = (0, 0)

    node_bg.inputs['Color'].default_value = (0.02, 0.02, 0.03, 1.0)  # ダーク
    node_bg.inputs['Strength'].default_value = 0.5
    node_vol.inputs['Density'].default_value = 0.02  # 世界全体のScatterはごく薄く
    node_vol.inputs['Color'].default_value = (1.0, 1.0, 1.0, 1.0)

    wlinks.new(node_bg.outputs['Background'], node_output_w.inputs['Surface'])
    wlinks.new(node_vol.outputs['Volume'], node_output_w.inputs['Volume'])

    return box_obj


def set_cycles_render(scene: bpy.types.Scene,
                      device: str = 'CPU',
                      samples: int = 128,
                      bounces: int = 12):
    """
    レンダリングエンジンをCyclesに設定。

    Args:
        scene: Blenderシーン
        device: 'CPU' or 'GPU'
        samples: レンダリングサンプル数（Volumeは多めがよい）
        bounces: 最大反射回数（Volume内での光の散乱回数を考慮）
    """
    render = scene.render
    render.engine = 'CYCLES'

    cycles = scene.cycles
    cycles.device = device
    cycles.samples = samples
    cycles.max_bounces = bounces


def set_eevee_render(scene: bpy.types.Scene,
                     samples: int = 64):
    """
    レンダリングエンジンをEeveeに設定し、Volumetricsを有効化。

    Blender 5.0 では Eevee Next が標準であり、属性名が変更されている可能性があるため、
    各属性設定を try/except で囲む。

    Args:
        scene: Blenderシーン
        samples: レンダリングサンプル数（Eeveeのdenoise用など、デフォルト64）
    """
    # NOTE: In Blender 4.2+/5.0, 'BLENDER_EEVEE' IS Eevee Next.
    # There is no separate 'BLENDER_EEVEE_NEXT' engine ID.
    # Old properties (use_volumetrics, use_bloom, use_gtao) are removed.
    render = scene.render
    render.engine = 'BLENDER_EEVEE'

    eevee = scene.eevee

    # Eevee Next volumetric settings
    eevee.volumetric_tile_size = "8"       # string enum: "1","2","4","8","16"
    eevee.volumetric_samples = 64          # volume ray march samples
    eevee.volumetric_start = 0.1           # near clip
    eevee.volumetric_end = 100.0           # far clip
    eevee.taa_render_samples = 64          # render TAA samples


def remove_beam_cones(scene: bpy.types.Scene):
    """
    既存のbeamコーンメッシュを全削除。
    Volume Scatter方式に切り替えた場合に残ったコーンを掃除する。
    """
    to_delete = [
        o for o in scene.objects
        if o.type == 'MESH' and 'Beam' in o.name
    ]
    if to_delete:
        bpy.ops.object.select_all(action='DESELECT')
        for o in to_delete:
            o.select_set(True)
        scene.objects.active = to_delete[0]
        bpy.ops.object.delete(use_global=False)
        for o in to_delete:
            if o.data and o.data.users == 0:
                bpy.data.meshes.remove(o.data)