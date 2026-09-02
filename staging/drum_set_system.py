# -*- coding: utf-8 -*-
"""Drum set system module - Creates a full drum kit with stands and cymbals."""

import bpy
import math
import mathutils

INCH = 0.0254

# =============================================================================
# Material Cache
# =============================================================================

_mat_cache = {}


def _get_mat(name: str) -> bpy.types.Material:
    if name in _mat_cache:
        mat = _mat_cache[name]
        try:
            _ = mat.name  # 参照が有効か確認
            return mat
        except (ReferenceError, RuntimeError):
            print(f"[drum_set_system] Stale mat ref for '{name}', recreating...")
            del _mat_cache[name]

    mats = {
        "Drum_Shell_BlackPearl": ((0.10, 0.01, 0.01, 1.0), 0.0, 0.1),
        "Drum_Head_Coated": ((0.92, 0.9, 0.87, 1.0), 0.0, 0.6),
        "Hardware_Chrome": ((0.75, 0.76, 0.78, 1.0), 0.95, 0.15),
        "Cymbal_Brass": ((0.75, 0.62, 0.30, 1.0), 0.9, 0.2),
        "Pedal_BlackSteel": ((0.12, 0.12, 0.13, 1.0), 0.85, 0.4),
    }

    if name not in mats:
        return None

    base_color, metallic, roughness = mats[name]
    mat = _create_principled_material(name, base_color, metallic, roughness)
    _mat_cache[name] = mat
    return mat


def _create_principled_material(name: str, base_color: tuple, metallic: float, roughness: float):
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    node_bsdf = nodes.new('ShaderNodeBsdfPrincipled')
    node_output = nodes.new('ShaderNodeOutputMaterial')
    node_bsdf.location = (-300, 0)
    node_output.location = (200, 0)

    node_bsdf.inputs['Base Color'].default_value = base_color
    node_bsdf.inputs['Metallic'].default_value = metallic
    node_bsdf.inputs['Roughness'].default_value = roughness

    links.new(node_bsdf.outputs['BSDF'], node_output.inputs['Surface'])
    return mat


def _assign_material(obj: bpy.types.Object, material: bpy.types.Material):
    if material is None:
        return
    try:
        _ = material.name
    except (ReferenceError, RuntimeError):
        print(f"[drum_set_system] WARNING: material already removed, skipping assignment to {obj.name}")
        return
    if len(obj.data.materials) == 0:
        obj.data.materials.append(material)
    else:
        obj.data.materials[0] = material


def _create_head_logo_material() -> bpy.types.Material:
    """バスドラ前方ヘッド用：同心円+放射線+中心ドットのプロシージャル・マテリアル。

    白背景（0.92, 0.9, 0.87）にグレー（0.35）の線 pattern。
    Object座標（local x,y = 円盤面）を radial/angle に変換して描画。
    """
    name = "Drum_Head_Coated_Logo"
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    # --- Output & BSDF ---
    n_output = nt.nodes.new('ShaderNodeOutputMaterial')
    n_output.location = (1200, 0)
    n_bsdf = nt.nodes.new('ShaderNodeBsdfPrincipled')
    n_bsdf.location = (900, 0)
    n_bsdf.inputs['Roughness'].default_value = 0.6
    nt.links.new(n_bsdf.outputs['BSDF'], n_output.inputs['Surface'])

    # --- Texture Coordinate (Object) → Separate XYZ ---
    n_texco = nt.nodes.new('ShaderNodeTexCoord')
    n_texco.location = (-1200, 0)
    n_sep = nt.nodes.new('ShaderNodeSeparateXYZ')
    n_sep.location = (-1000, 0)
    nt.links.new(n_texco.outputs['Object'], n_sep.inputs['Vector'])

    # --- rho = sqrt(x^2 + y^2) ---
    n_x2 = nt.nodes.new('ShaderNodeMath')
    n_x2.operation = 'MULTIPLY'
    n_x2.location = (-800, 200)
    nt.links.new(n_sep.outputs['X'], n_x2.inputs[0])
    nt.links.new(n_sep.outputs['X'], n_x2.inputs[1])

    n_y2 = nt.nodes.new('ShaderNodeMath')
    n_y2.operation = 'MULTIPLY'
    n_y2.location = (-800, 0)
    nt.links.new(n_sep.outputs['Y'], n_y2.inputs[0])
    nt.links.new(n_sep.outputs['Y'], n_y2.inputs[1])

    n_add_xy = nt.nodes.new('ShaderNodeMath')
    n_add_xy.operation = 'ADD'
    n_add_xy.location = (-600, 100)
    nt.links.new(n_x2.outputs[0], n_add_xy.inputs[0])
    nt.links.new(n_y2.outputs[0], n_add_xy.inputs[1])

    n_sqrt = nt.nodes.new('ShaderNodeMath')
    n_sqrt.operation = 'SQRT'
    n_sqrt.location = (-450, 100)
    nt.links.new(n_add_xy.outputs[0], n_sqrt.inputs[0])

    # --- Helper: ring_mask(rho, radius, width) = 1 - clamp(|rho-r|/w, 0, 1) ---
    def _ring_node(radius: float, width: float, y_offset: float) -> 'ShaderNodeMath':
        """Returns the output node of the ring mask (0..1)."""
        # abs(rho - radius)
        n_sub = nt.nodes.new('ShaderNodeMath')
        n_sub.operation = 'SUBTRACT'
        n_sub.inputs[1].default_value = radius
        n_sub.location = (-250, y_offset)
        nt.links.new(n_sqrt.outputs[0], n_sub.inputs[0])

        n_abs = nt.nodes.new('ShaderNodeMath')
        n_abs.operation = 'ABSOLUTE'
        n_abs.location = (-100, y_offset)
        nt.links.new(n_sub.outputs[0], n_abs.inputs[0])

        # divide by width
        n_div = nt.nodes.new('ShaderNodeMath')
        n_div.operation = 'DIVIDE'
        n_div.inputs[1].default_value = width
        n_div.location = (50, y_offset)
        nt.links.new(n_abs.outputs[0], n_div.inputs[0])

        # clamp to 0..1
        n_clamp = nt.nodes.new('ShaderNodeClamp')
        n_clamp.location = (200, y_offset)
        nt.links.new(n_div.outputs[0], n_clamp.inputs['Value'])

        # 1 - clamped
        n_inv = nt.nodes.new('ShaderNodeMath')
        n_inv.operation = 'SUBTRACT'
        n_inv.inputs[0].default_value = 1.0
        n_inv.location = (350, y_offset)
        nt.links.new(n_clamp.outputs[0], n_inv.inputs[1])
        return n_inv

    # Three concentric rings
    ring1 = _ring_node(0.08, 0.005, 400)
    ring2 = _ring_node(0.15, 0.005, 200)
    ring3 = _ring_node(0.23, 0.005, 0)

    # Combine rings: max
    n_r12 = nt.nodes.new('ShaderNodeMath')
    n_r12.operation = 'MAXIMUM'
    n_r12.location = (500, 300)
    nt.links.new(ring1.outputs[0], n_r12.inputs[0])
    nt.links.new(ring2.outputs[0], n_r12.inputs[1])

    n_rings = nt.nodes.new('ShaderNodeMath')
    n_rings.operation = 'MAXIMUM'
    n_rings.location = (650, 200)
    nt.links.new(n_r12.outputs[0], n_rings.inputs[0])
    nt.links.new(ring3.outputs[0], n_rings.inputs[1])

    # --- Radial lines: 6 lines → abs(sin(atan2(y,x)*3)) < 0.04 ---
    n_atan = nt.nodes.new('ShaderNodeMath')
    n_atan.operation = 'ARCTAN2'
    n_atan.location = (-250, -200)
    nt.links.new(n_sep.outputs['Y'], n_atan.inputs[0])
    nt.links.new(n_sep.outputs['X'], n_atan.inputs[1])

    n_angle3 = nt.nodes.new('ShaderNodeMath')
    n_angle3.operation = 'MULTIPLY'
    n_angle3.inputs[1].default_value = 3.0
    n_angle3.location = (-100, -200)
    nt.links.new(n_atan.outputs[0], n_angle3.inputs[0])

    n_sin = nt.nodes.new('ShaderNodeMath')
    n_sin.operation = 'SINE'
    n_sin.location = (50, -200)
    nt.links.new(n_angle3.outputs[0], n_sin.inputs[0])

    n_sin_abs = nt.nodes.new('ShaderNodeMath')
    n_sin_abs.operation = 'ABSOLUTE'
    n_sin_abs.location = (200, -200)
    nt.links.new(n_sin.outputs[0], n_sin_abs.inputs[0])

    # thin line: 1 - clamp(sin_abs / 0.04)
    n_sin_div = nt.nodes.new('ShaderNodeMath')
    n_sin_div.operation = 'DIVIDE'
    n_sin_div.inputs[1].default_value = 0.04
    n_sin_div.location = (350, -200)
    nt.links.new(n_sin_abs.outputs[0], n_sin_div.inputs[0])

    n_sin_clamp = nt.nodes.new('ShaderNodeClamp')
    n_sin_clamp.location = (500, -200)
    nt.links.new(n_sin_div.outputs[0], n_sin_clamp.inputs['Value'])

    n_radial_raw = nt.nodes.new('ShaderNodeMath')
    n_radial_raw.operation = 'SUBTRACT'
    n_radial_raw.inputs[0].default_value = 1.0
    n_radial_raw.location = (650, -200)
    nt.links.new(n_sin_clamp.outputs[0], n_radial_raw.inputs[1])

    # Radial lines only outside center dot (rho > 0.04) and inside disc (rho < 0.27)
    n_r_gt = nt.nodes.new('ShaderNodeMath')
    n_r_gt.operation = 'GREATER_THAN'
    n_r_gt.inputs[1].default_value = 0.04
    n_r_gt.location = (500, -400)
    nt.links.new(n_sqrt.outputs[0], n_r_gt.inputs[0])

    n_r_lt = nt.nodes.new('ShaderNodeMath')
    n_r_lt.operation = 'LESS_THAN'
    n_r_lt.inputs[1].default_value = 0.27
    n_r_lt.location = (500, -550)
    nt.links.new(n_sqrt.outputs[0], n_r_lt.inputs[0])

    n_r_mask = nt.nodes.new('ShaderNodeMath')
    n_r_mask.operation = 'MULTIPLY'
    n_r_mask.location = (700, -450)
    nt.links.new(n_r_gt.outputs[0], n_r_mask.inputs[0])
    nt.links.new(n_r_lt.outputs[0], n_r_mask.inputs[1])

    n_radial = nt.nodes.new('ShaderNodeMath')
    n_radial.operation = 'MULTIPLY'
    n_radial.location = (800, -300)
    nt.links.new(n_radial_raw.outputs[0], n_radial.inputs[0])
    nt.links.new(n_r_mask.outputs[0], n_radial.inputs[1])

    # --- Center dot: rho < 0.035 ---
    n_dot = nt.nodes.new('ShaderNodeMath')
    n_dot.operation = 'LESS_THAN'
    n_dot.inputs[1].default_value = 0.035
    n_dot.location = (500, -700)
    nt.links.new(n_sqrt.outputs[0], n_dot.inputs[0])

    # --- Combine all masks: max(rings, max(radial, dot)) ---
    n_max1 = nt.nodes.new('ShaderNodeMath')
    n_max1.operation = 'MAXIMUM'
    n_max1.location = (900, -100)
    nt.links.new(n_radial.outputs[0], n_max1.inputs[0])
    nt.links.new(n_dot.outputs[0], n_max1.inputs[1])

    n_total = nt.nodes.new('ShaderNodeMath')
    n_total.operation = 'MAXIMUM'
    n_total.location = (1000, 0)
    nt.links.new(n_rings.outputs[0], n_total.inputs[0])
    nt.links.new(n_max1.outputs[0], n_total.inputs[1])

    # --- Color: white(0.92,0.9,0.87) ↔ gray(0.35,0.35,0.35) ---
    n_mix = nt.nodes.new('ShaderNodeMixRGB')
    n_mix.location = (1050, -200)
    n_mix.inputs['Color1'].default_value = (0.92, 0.9, 0.87, 1.0)  # white
    n_mix.inputs['Color2'].default_value = (0.35, 0.35, 0.35, 1.0)  # gray
    nt.links.new(n_total.outputs[0], n_mix.inputs['Fac'])
    nt.links.new(n_mix.outputs['Color'], n_bsdf.inputs['Base Color'])

    return mat


def _rotate_vec(v: tuple, rot: mathutils.Euler) -> mathutils.Vector:
    return rot.to_matrix() @ mathutils.Vector(v)


def _join_objects(obj_list: list):
    """オブジェクトリストを1つのメッシュに結合して返す"""
    if not obj_list:
        return None
    if len(obj_list) == 1:
        return obj_list[0]
    bpy.ops.object.select_all(action='DESELECT')
    for obj in obj_list:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = obj_list[0]
    bpy.ops.object.join()
    return bpy.context.view_layer.objects.active


# =============================================================================
# Drum Shell Helper
# =============================================================================

def _create_flat_dome_head(head_radius: float, thickness: float,
                           loc: tuple, rotation: mathutils.Euler,
                           dome_amp: float = 0.008,
                           n_rings: int = 12) -> bpy.types.Object:
    """平坦円盤ヘッド + 凸/凹ドーム Shape Key（定在波用）を生成する。

    ベースメッシュは完全に平面（テンションで張られた状態）。
    Shape Key "Dome" は local z 方向に
        dz = dome_amp * (1 - (rho/r)^2)
    のプロファイルで頂点をオフセットし、value=+1 なら凸ドーム、
    value=-1 なら凹ドーム（中心が沈む）、value=0 で平面に戻る。

    打撃時に Shape Key value を
        value(t) = e^(-lambda*t) * sin(omega*t)
    のカーブでキーフレーム化すると、凸→凹→減衰の定在波振動になる。

    Parameters
    ----------
    head_radius : 円形リムの半径 (m)
    thickness   : ヘッド厚み (m)
    loc         : リム面の中心位置（世界座標）
    rotation    : ドラムの回転
    dome_amp    : ドーム振幅 (m) — value=±1 時の中心の最大変位
    n_rings     : 径方向の同心円リング数（既定 12）
    """
    import bmesh

    r = head_radius
    n_segs = 64

    bm = bmesh.new()

    # 中心頂点（local z = 0）
    center = bm.verts.new((0.0, 0.0, 0.0))

    # 同心円リング n_rings 本（径方向分割、local z = 0 で平面）
    rings = []
    for i in range(1, n_rings + 1):
        rho = r * i / n_rings
        ring = []
        for j in range(n_segs):
            a = 2.0 * math.pi * j / n_segs
            ring.append(bm.verts.new((rho * math.cos(a),
                                      rho * math.sin(a),
                                      0.0)))
        rings.append(ring)

    # 中心ファン
    for j in range(n_segs):
        nj = (j + 1) % n_segs
        bm.faces.new((center, rings[0][j], rings[0][nj]))

    # リング間クアド面
    for i in range(len(rings) - 1):
        for j in range(n_segs):
            nj = (j + 1) % n_segs
            bm.faces.new((rings[i][j], rings[i + 1][j],
                          rings[i + 1][nj], rings[i][nj]))

    mesh = bpy.data.meshes.new("FlatDomeHeadMesh")
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new("Drum_FlatDomeHead", mesh)
    bpy.context.collection.objects.link(obj)

    # Shape Key "Dome": local z 方向にプロファイルオフセット
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.ops.object.shape_key_add()          # Basis（自動名）
    bpy.ops.object.shape_key_add(from_mix=True)  # Basis のコピー
    dome = obj.data.shape_keys.key_blocks[-1]
    dome.name = "Dome"                      # 後続スクリプトで名前で参照するため
    for i in range(len(dome.data)):
        v = dome.data[i]
        rho = math.sqrt(v.co.x * v.co.x + v.co.y * v.co.y)
        if rho <= r:
            profile = 1.0 - (rho / r) ** 2
        else:
            profile = 0.0
        v.co.z = v.co.z + dome_amp * profile
    obj.data.shape_keys.key_blocks[-1].value = 0.0  # 静止時=平面

    # Solidify で厚み付与
    sol = obj.modifiers.new(name="Solidify", type='SOLIDIFY')
    sol.thickness = thickness
    sol.offset = 0.0

    # 位置・回転を設定（ベース形状=平面なので、loc がそのまま中心）
    obj.location = mathutils.Vector(loc)
    obj.rotation_euler = rotation

    _assign_material(obj, _create_head_logo_material())
    return obj


def _create_drum_shell(radius: float, height: float, location: tuple,
                       rotation: mathutils.Euler,
                       front_dome_amp: float = 0.0,
                       back_dome_amp: float = 0.0) -> list:
    loc = mathutils.Vector(location)
    objs = []

    shell_mat = _get_mat("Drum_Shell_BlackPearl")
    head_mat = _get_mat("Drum_Head_Coated")
    chrome_mat = _get_mat("Hardware_Chrome")

    # Shell body (hollow cylinder)
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=height, location=loc, end_fill_type='NOTHING')
    shell = bpy.context.view_layer.objects.active
    shell.name = "Drum_ShellBody"
    shell.rotation_euler = rotation
    _assign_material(shell, shell_mat)
    objs.append(shell)

    # Drum heads (top/bottom) — flat plane (+ optional dome shape key) or flat cylinder
    head_thickness = 0.003
    for sign in [-1, 1]:
        head_z_offset = sign * (height / 2 + head_thickness / 2)
        head_loc = loc + _rotate_vec((0, 0, head_z_offset), rotation)

        dome_amp = front_dome_amp if sign == 1 else back_dome_amp
        if dome_amp > 0:
            head_radius = radius + 0.001  # シェルに1mmオーバーラップ（隙間・z-fight防止）
            head = _create_flat_dome_head(
                head_radius=head_radius,
                thickness=head_thickness,
                loc=head_loc,
                rotation=rotation,
                dome_amp=dome_amp,
            )
        else:
            head_radius = radius - 0.005  # 従来どおり
            bpy.ops.mesh.primitive_cylinder_add(radius=head_radius, depth=head_thickness, location=head_loc)
            head = bpy.context.view_layer.objects.active
            head.rotation_euler = rotation
            _assign_material(head, head_mat)

        head.name = "Drum_Head" + ("_Bottom" if sign == -1 else "_Top")
        objs.append(head)

    # Hoop rings
    ring_radius = radius + 0.003
    ring_thick = 0.008
    ring_offset = height / 2 - ring_thick / 2

    for sign in [-1, 1]:
        r_loc = loc + _rotate_vec((0, 0, sign * ring_offset), rotation)
        bpy.ops.mesh.primitive_torus_add(
            major_radius=ring_radius, minor_radius=ring_thick,
            major_segments=32, minor_segments=8, location=r_loc
        )
        ring = bpy.context.view_layer.objects.active
        ring.name = "Drum_HoopRing"
        ring.rotation_euler = rotation
        _assign_material(ring, chrome_mat)
        objs.append(ring)

    # Tension rods (12)
    rod_count = 12
    rod_radius = 0.003
    for i in range(rod_count):
        angle = 2 * math.pi / rod_count * i
        r_off_x = math.cos(angle) * (ring_radius - rod_radius)
        r_off_y = math.sin(angle) * (ring_radius - rod_radius)
        rod_loc = loc + _rotate_vec((r_off_x, r_off_y, 0), rotation)
        bpy.ops.mesh.primitive_cylinder_add(radius=rod_radius, depth=height * 0.35, location=rod_loc)
        rod = bpy.context.view_layer.objects.active
        rod.name = f"Drum_TensionRod_{i}"
        rod.rotation_euler = rotation
        _assign_material(rod, chrome_mat)
        objs.append(rod)

    return objs


# =============================================================================
# Bass Drum
# =============================================================================

def create_bass_drum(location: tuple = (0, 0, 0), rotation: tuple = (0, 0, 0)) -> list:
    rot = mathutils.Euler(rotation)
    radius = 22 * INCH / 2
    height = 18 * INCH

    drum_rot = mathutils.Euler((math.radians(90), rot[1], rot[2]))
    loc = mathutils.Vector(location)

    # 前方ヘッド: 平坦 + Shape Key "Dome"（打撃時に定在波振動でたわみ表現）
    # dome_amp=0.008 m (8mm) — 中心の最大変位（value=±1 時）
    objs = _create_drum_shell(radius, height, loc, drum_rot, front_dome_amp=0.008)
    for obj in objs:
        obj.name = "Bass_" + obj.name

    return objs


# =============================================================================
# Tom-Tom
# =============================================================================

def create_tom_tom(radius_inch: float, height_inch: float, location: tuple, rotation: tuple = (0, 0, 0), mount_angle: float = 0.0) -> list:
    rot = mathutils.Euler(rotation)
    radius = radius_inch * INCH / 2
    height = height_inch * INCH

    tilt_rot = mathutils.Euler((rot[0] + math.radians(mount_angle), rot[1], rot[2]))
    objs = _create_drum_shell(radius, height, mathutils.Vector(location), tilt_rot)

    label = f"Tom_{int(radius_inch)}x{int(height_inch)}"
    for obj in objs:
        obj.name = label + "_" + obj.name

    return objs


# =============================================================================
# Tom Mount Only (vertical pole on bass drum top)
# =============================================================================

def create_tom_mount_only(tom_radius_inch: float, location: tuple, side: str = "right", pole_length: float = 0.3) -> list:
    """
    タムドラムのマウント支柱のみを作成（バスドラム上面に垂直に設置）
    内側垂直ポールのみ(X=±0.05)
    """
    objs = []
    loc = mathutils.Vector(location)
    pole_radius = 0.012
    chrome_mat = _get_mat("Hardware_Chrome")

    if side == "right":
        inner_x = 0.05
    else:
        inner_x = -0.05

    bpy.ops.mesh.primitive_cylinder_add(
        radius=pole_radius, depth=pole_length,
        location=(loc.x + inner_x, loc.y, loc.z)
    )
    inner_pole = bpy.context.view_layer.objects.active
    inner_pole.name = f"TomMount_InnerPole_{side}"
    _assign_material(inner_pole, chrome_mat)
    objs.append(inner_pole)

    return objs


# =============================================================================
# H-Bar (tom-to-tom horizontal connector)
# =============================================================================

def create_tom_hbar(location: tuple = (0, 0, 0), rotation: tuple = (0, 0, 0), bar_length: float = 0.16) -> list:
    """
    タム2個の支柱上部を横に連結するHバー（棒状）
    """
    loc = mathutils.Vector(location)
    rot = mathutils.Euler(rotation)
    objs = []

    hbar_radius = 0.008
    chrome_mat = _get_mat("Hardware_Chrome")

    hbar_loc = loc + _rotate_vec((0, 0, -0.01), rot)

    bpy.ops.mesh.primitive_cylinder_add(radius=hbar_radius, depth=bar_length, location=hbar_loc)
    hbar = bpy.context.view_layer.objects.active
    hbar.name = "Tom_HBar"
    hbar.rotation_euler = (rot[0], rot[1] + math.radians(90), rot[2])
    _assign_material(hbar, chrome_mat)
    objs.append(hbar)

    return objs


# =============================================================================
# Floor Tom
# =============================================================================

def create_floor_tom(radius_inch: float = 16, height_inch: float = 14, location: tuple = (0, 0, 0), rotation: tuple = (0, 0, 0), ground_z: float = 0.0) -> list:
    """Create a floor tom with legs that extend from shell bottom to ground_z.
    
    ground_z: The Z-coordinate where the leg bottoms should reach (default 0.0).
              This allows alignment with snare/cymbal stand bases.
    """
    rot = mathutils.Euler(rotation)
    shell_objs = create_tom_tom(radius_inch, height_inch, location, rotation, mount_angle=0.0)

    label = f"FloorTom_{int(radius_inch)}x{int(height_inch)}"
    for obj in shell_objs:
        if not obj.name.startswith(label):
            obj.name = label + "_" + obj.name

    radius = radius_inch * INCH / 2
    height = height_inch * INCH

    shell_bottom_z = location[2] - height / 2
    leg_length = max(shell_bottom_z - ground_z, 0.15)

    for i in range(3):
        angle = 2 * math.pi / 3 * i
        lx = math.cos(angle) * (radius - 0.01)
        ly = math.sin(angle) * (radius - 0.01)
        foot_center_z = ground_z + leg_length / 2
        foot_loc = mathutils.Vector((location[0] + lx, location[1] + ly, foot_center_z))

        bpy.ops.mesh.primitive_cylinder_add(radius=0.008, depth=leg_length, location=foot_loc)
        leg = bpy.context.view_layer.objects.active
        leg.name = f"{label}_Leg_{i}"
        leg.rotation_euler = rot
        shell_objs.append(leg)

    return shell_objs


# =============================================================================
# Snare Drum
# =============================================================================

def create_snare_drum(radius_inch: int = 14, depth_inch: int = 6, location: tuple = (0, 0, 0), rotation: tuple = (0, 0, 0)) -> list:
    loc = mathutils.Vector(location)
    rot = mathutils.Euler(rotation)
    objs = []

    R = radius_inch * INCH / 2
    D = depth_inch * INCH

    objs.extend(_create_drum_shell(R, D, loc, rot))
    for obj in objs:
        if not obj.name.startswith("Snare"):
            obj.name = "Snare_" + obj.name

    wire_radius = R * 0.85
    wire_z = loc.z - D / 2 - 0.005
    bpy.ops.mesh.primitive_torus_add(
        major_radius=wire_radius, minor_radius=0.003,
        major_segments=24, minor_segments=6, location=(loc.x, loc.y, wire_z)
    )
    wire = bpy.context.view_layer.objects.active
    wire.name = "Snare_Wires"
    wire.rotation_euler = rot
    objs.append(wire)

    return objs


# =============================================================================
# Snare Stand (tripod CD-base type)
# =============================================================================

def create_snare_stand(location: tuple = (0, 0, 0), rotation: tuple = (0, 0, 0)) -> list:
    """
    スネアスタンド作成（三脚CDベース型）
    - メインポール（Z軸垂直支柱、上面にスネートレー）
    - CDベース: ポール下部から3本の足が放射状に広がる三脚型
    """
    loc = mathutils.Vector(location)
    rot = mathutils.Euler(rotation)
    objs = []

    chrome_mat = _get_mat("Hardware_Chrome")

    stand_height = 0.30
    pole_radius = 0.008
    cd_base_radius = 0.15
    leg_radius = 0.005
    spread_height = 0.12

    # Main pole
    pole_loc = loc + _rotate_vec((0, 0, -stand_height / 2), rot)
    bpy.ops.mesh.primitive_cylinder_add(radius=pole_radius, depth=stand_height, location=pole_loc)
    pole = bpy.context.view_layer.objects.active
    pole.name = "Stand_SnarePole"
    pole.rotation_euler = rot
    _assign_material(pole, chrome_mat)
    objs.append(pole)

    # Snare tray (ring on top)
    tray_radius = 0.08
    tray_thickness = 0.005
    tray_loc = loc + _rotate_vec((0, 0, 0.0), rot)
    bpy.ops.mesh.primitive_torus_add(
        major_radius=tray_radius, minor_radius=tray_thickness,
        major_segments=24, minor_segments=8, location=tray_loc
    )
    tray = bpy.context.view_layer.objects.active
    tray.name = "Stand_SnareTray"
    tray.rotation_euler = rot
    _assign_material(tray, chrome_mat)
    objs.append(tray)

    # Tripod CD base (3 legs)
    base_z = loc.z - spread_height
    ground_z = loc.z - stand_height + 0.02

    for i in range(3):
        angle = 2 * math.pi / 3 * i + math.radians(30)

        foot_x = loc.x + math.cos(angle) * cd_base_radius
        foot_y = loc.y + math.sin(angle) * cd_base_radius

        dx = foot_x - loc.x
        dy = foot_y - loc.y
        dz = ground_z - base_z
        leg_len = math.sqrt(dx*dx + dy*dy + dz*dz)

        if leg_len < 0.01:
            continue

        mid_x = (loc.x + foot_x) / 2
        mid_y = (loc.y + foot_y) / 2
        mid_z = (base_z + ground_z) / 2

        bpy.ops.mesh.primitive_cylinder_add(radius=leg_radius, depth=leg_len,
                                           location=(mid_x, mid_y, mid_z))
        leg = bpy.context.view_layer.objects.active
        leg.name = f"Stand_SnareLeg_{i}"

        default_dir = mathutils.Vector((0, 0, 1))
        target_dir = mathutils.Vector((dx, dy, dz)).normalized()
        leg.rotation_euler = default_dir.rotation_difference(target_dir).to_euler()

        _assign_material(leg, chrome_mat)
        objs.append(leg)

    return objs


# =============================================================================
# Cymbal Helper
# =============================================================================

def _create_cymbal(radius: float, thickness: float, location: tuple, rotation: mathutils.Euler, boss_radius: float = 0.03) -> list:
    loc = mathutils.Vector(location)

    brass_mat = _get_mat("Cymbal_Brass")

    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=thickness, location=loc)
    cymbal = bpy.context.view_layer.objects.active
    cymbal.name = "Cymbal_Body"
    cymbal.rotation_euler = rotation
    _assign_material(cymbal, brass_mat)

    boss_loc = loc + _rotate_vec((0, 0, thickness / 2 + 0.005), rotation)
    bpy.ops.mesh.primitive_cylinder_add(radius=boss_radius, depth=0.015, location=boss_loc)
    boss = bpy.context.view_layer.objects.active
    boss.name = "Cymbal_Boss"
    boss.rotation_euler = rotation
    _assign_material(boss, brass_mat)

    return [cymbal, boss]


# =============================================================================
# Hi-Hat (with tripod CD base + pedal plate)
# =============================================================================

def create_hihat(location: tuple = (0, 0, 0), rotation: tuple = (0, 0, 0), pedal_angle_deg: float = 60) -> list:
    """
    ハイハットシンバル + 三脚CDベーススタンド（φ14インチ）
    - メインポール（Z軸垂直支柱、上面に上下2枚のシンバル）
    - CDベース: ポール下部から3本の足が放射状に広がる三脚型
    - ペダル板（Y+側に取り付け）
    
    Args:
        pedal_angle_deg: ペダル板のZ軸回転角度（度）
            - Z軸正方向への右ねじ回転を正とする
            - 0 = Y軸正方向
            - 60 = Y+からX-側へ60度（初期値）
    """
    objs = []
    rot = mathutils.Euler(rotation)
    loc = mathutils.Vector(location)

    cymbal_radius = 14 * INCH / 2
    cymbal_thick = 0.004

    stand_height = 0.65
    pole_radius = 0.008
    cd_base_radius = 0.15
    leg_radius = 0.005
    spread_height = 0.49

    chrome_mat = _get_mat("Hardware_Chrome")
    pedal_mat = _get_mat("Pedal_BlackSteel")

    # Bottom cymbal
    bottom_objs = _create_cymbal(cymbal_radius, cymbal_thick, loc, rot, boss_radius=0.025)
    for o in bottom_objs:
        o.name = "HihatBottom_" + o.name.replace("Cymbal_", "")
    objs.extend(bottom_objs)

    # Top cymbal (closed position - nearly touching bottom)
    top_loc = loc + _rotate_vec((0, 0, 0.002), rot)
    top_objs = _create_cymbal(cymbal_radius, cymbal_thick, top_loc, rot, boss_radius=0.025)
    for o in top_objs:
        o.name = "HihatTop_" + o.name.replace("Cymbal_", "")
    objs.extend(top_objs)

    # Main pole
    pole_center_z = loc.z - stand_height / 2
    pole_loc = mathutils.Vector((loc.x, loc.y, pole_center_z))
    bpy.ops.mesh.primitive_cylinder_add(radius=pole_radius, depth=stand_height, location=pole_loc)
    pole = bpy.context.view_layer.objects.active
    pole.name = "Stand_HihatPole"
    pole.rotation_euler = rot
    _assign_material(pole, chrome_mat)
    objs.append(pole)

    # Tripod CD base (3 legs) - rotated by pedal_angle_deg so one leg faces pedal side
    base_z = loc.z - spread_height
    ground_z = loc.z - stand_height + 0.02

    for i in range(3):
        angle = 2 * math.pi / 3 * i + math.radians(30) - math.radians(pedal_angle_deg)

        foot_x = loc.x + math.cos(angle) * cd_base_radius
        foot_y = loc.y + math.sin(angle) * cd_base_radius

        dx = foot_x - loc.x
        dy = foot_y - loc.y
        dz = ground_z - base_z
        leg_len = math.sqrt(dx*dx + dy*dy + dz*dz)

        if leg_len < 0.01:
            continue

        mid_x = (loc.x + foot_x) / 2
        mid_y = (loc.y + foot_y) / 2
        mid_z = (base_z + ground_z) / 2

        bpy.ops.mesh.primitive_cylinder_add(radius=leg_radius, depth=leg_len,
                                           location=(mid_x, mid_y, mid_z))
        leg = bpy.context.view_layer.objects.active
        leg.name = f"Stand_HihatLeg_{i}"

        default_dir = mathutils.Vector((0, 0, 1))
        target_dir = mathutils.Vector((dx, dy, dz)).normalized()
        leg.rotation_euler = default_dir.rotation_difference(target_dir).to_euler()

        _assign_material(leg, chrome_mat)
        objs.append(leg)

    # Pedal plate - positioned at pole center, rotated, then offset along rotated Y+ direction
    pedal_z = loc.z - stand_height + 0.03

    plate_width_front = 0.12 * (2/3)
    plate_width_rear = 0.12
    plate_length = 0.10 * 2
    plate_thickness = 0.012

    # Create cube at pole center
    bpy.ops.mesh.primitive_cube_add(size=1, location=(loc.x, loc.y, pedal_z))
    pedal = bpy.context.view_layer.objects.active
    pedal.name = "Stand_HihatPedal"
    pedal.scale = (plate_width_rear / 2, plate_length / 2, plate_thickness)

    # Calculate final position: offset by plate_length/2 so pedal rear edge aligns with pole (pole is rotation center)
    angle_rad = math.radians(pedal_angle_deg)
    offset_dist = plate_length / 2  # 0.10m — distance from pole to pedal center
    # Y+からX-側へθ回転 → X成分は負、Y成分は正（右ねじ定理）
    offset_x = -math.sin(angle_rad) * offset_dist
    offset_y = math.cos(angle_rad) * offset_dist
    pedal.location = mathutils.Vector((loc.x + offset_x, loc.y + offset_y, pedal_z))

    # Set rotation: rotate so local Y+ points toward pole (same direction as offset: Y+→X-)
    pedal.rotation_euler = rot.copy()
    pedal.rotation_euler.z += angle_rad

    # Make trapezoid by narrowing front (Y+) vertices
    me = pedal.data
    front_narrow_ratio = plate_width_front / plate_width_rear
    for v in me.vertices:
        if v.co.y > 0.5:
            v.co.x = v.co.x * front_narrow_ratio
    me.update()
    _assign_material(pedal, pedal_mat)
    objs.append(pedal)

    return objs


# =============================================================================
# Cymbal with Stand (Ride/Crash) - with tripod CD base
# =============================================================================

def create_cymbal_with_stand(cymbal_name: str, radius_inch: float, thickness: float,
                             stand_base_xy: tuple, cymbal_location: tuple, rotation: tuple = (0, 0, 0),
                             stand_height: float = 1.0, tilt_angle: float = -15) -> list:
    """
    シンバル + スタンドの共通作成
    - 垂直ポール1本
    - 斜めビーム1本（垂直ポールの途中からシンバル下方へ）
    - CDベース三脚3本
    - シンバル保持リング
    """
    objs = []
    rot = mathutils.Euler(rotation)
    cymbal_loc = mathutils.Vector(cymbal_location)
    stand_x, stand_y = stand_base_xy

    cymbal_radius = radius_inch * INCH / 2
    tilt_rot = mathutils.Euler((rot[0] + math.radians(tilt_angle), rot[1], rot[2]))

    brass_mat = _get_mat("Cymbal_Brass")
    chrome_mat = _get_mat("Hardware_Chrome")

    # Cymbal body
    cymbal_objs = _create_cymbal(cymbal_radius, thickness, cymbal_loc, tilt_rot, boss_radius=0.03)
    for o in cymbal_objs:
        o.name = f"{cymbal_name}_{o.name.replace('Cymbal_', '')}"
    objs.extend(cymbal_objs)

    pole_radius = 0.008
    cd_base_radius = 0.15
    leg_radius = 0.005
    spread_height = stand_height * 0.2

    cymbal_bottom_z = cymbal_loc.z - thickness / 2
    ground_z_base = cymbal_loc.z - stand_height + 0.02

    # Joint sphere height
    joint_z = ground_z_base + stand_height * 0.4
    joint_top_z = joint_z + 0.05

    # Vertical pole
    pole_top_z = joint_top_z
    pole_height = pole_top_z - ground_z_base
    pole_center_z = ground_z_base + pole_height / 2

    pole_loc = mathutils.Vector((stand_x, stand_y, pole_center_z))
    bpy.ops.mesh.primitive_cylinder_add(radius=pole_radius, depth=pole_height, location=pole_loc)
    pole = bpy.context.view_layer.objects.active
    pole.name = f"Stand_{cymbal_name}Pole"
    pole.rotation_euler = rot
    _assign_material(pole, chrome_mat)
    objs.append(pole)

    # Joint sphere
    sphere_loc = mathutils.Vector((stand_x, stand_y, joint_top_z))
    bpy.ops.mesh.primitive_ico_sphere_add(radius=0.012, subdivisions=2, location=sphere_loc)
    sphere = bpy.context.view_layer.objects.active
    sphere.name = f"Stand_{cymbal_name}JointSphere"
    _assign_material(sphere, chrome_mat)
    objs.append(sphere)

    # Diagonal beam
    beam_start = mathutils.Vector((stand_x + 0.02, stand_y, joint_top_z))
    beam_end = mathutils.Vector((cymbal_loc.x, cymbal_loc.y, cymbal_bottom_z + 0.01))

    dx = beam_end.x - beam_start.x
    dy = beam_end.y - beam_start.y
    dz = beam_end.z - beam_start.z
    beam_len = math.sqrt(dx*dx + dy*dy + dz*dz)

    if beam_len > 0.01:
        mid_x = (beam_start.x + beam_end.x) / 2
        mid_y = (beam_start.y + beam_end.y) / 2
        mid_z = (beam_start.z + beam_end.z) / 2

        bpy.ops.mesh.primitive_cylinder_add(radius=0.006, depth=beam_len, location=(mid_x, mid_y, mid_z))
        beam = bpy.context.view_layer.objects.active
        beam.name = f"Stand_{cymbal_name}Beam"

        default_dir = mathutils.Vector((0, 0, 1))
        target_dir = mathutils.Vector((dx, dy, dz)).normalized()
        beam.rotation_euler = default_dir.rotation_difference(target_dir).to_euler()

        _assign_material(beam, chrome_mat)
        objs.append(beam)

    # Cymbal holder ring
    holder_z = cymbal_bottom_z + 0.01
    bpy.ops.mesh.primitive_torus_add(
        major_radius=0.04, minor_radius=0.003,
        major_segments=16, minor_segments=6, location=(cymbal_loc.x, cymbal_loc.y, holder_z)
    )
    holder = bpy.context.view_layer.objects.active
    holder.name = f"Stand_{cymbal_name}Holder"
    holder.rotation_euler = tilt_rot
    _assign_material(holder, chrome_mat)
    objs.append(holder)

    # Tripod CD base (3 legs)
    base_z = ground_z_base + spread_height
    for i in range(3):
        angle = 2 * math.pi / 3 * i + math.radians(30)

        foot_x = stand_x + math.cos(angle) * cd_base_radius
        foot_y = stand_y + math.sin(angle) * cd_base_radius

        dx = foot_x - stand_x
        dy = foot_y - stand_y
        dz = ground_z_base - base_z
        leg_len = math.sqrt(dx*dx + dy*dy + dz*dz)

        if leg_len < 0.01:
            continue

        mid_x = (stand_x + foot_x) / 2
        mid_y = (stand_y + foot_y) / 2
        mid_z = (base_z + ground_z_base) / 2

        bpy.ops.mesh.primitive_cylinder_add(radius=leg_radius, depth=leg_len,
                                           location=(mid_x, mid_y, mid_z))
        leg = bpy.context.view_layer.objects.active
        leg.name = f"Stand_{cymbal_name}Leg_{i}"

        default_dir = mathutils.Vector((0, 0, 1))
        target_dir = mathutils.Vector((dx, dy, dz)).normalized()
        leg.rotation_euler = default_dir.rotation_difference(target_dir).to_euler()

        _assign_material(leg, chrome_mat)
        objs.append(leg)

    return objs


# =============================================================================
# Kick Pedal (detailed: trapezoid plate + rods + arm + beater)
# =============================================================================

def create_kick_pedal(location: tuple = (0, 0, 0), rotation: tuple = (0, 0, 0)) -> list:
    """
    キックペダル作成
    - ベースプレート: ドラム側幅の2/3程度のかかと側の台形
    - 左右垂直ロッド×2本
    - 上部水平ロッド×1本
    - アーム + ビーターブロック
    """
    loc = mathutils.Vector(location)
    rot = mathutils.Euler(rotation)
    objs = []

    pedal_mat = _get_mat("Pedal_BlackSteel")

    # Trapezoid base plate
    plate_width_front = 0.15 * (2/3)
    plate_width_rear = 0.15
    plate_length = 0.12 * 4
    plate_thickness = 0.015

    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    plate = bpy.context.view_layer.objects.active
    plate.name = "Pedal_BasePlate"
    plate.scale = (plate_width_rear / 2, plate_length / 2, plate_thickness)
    plate.rotation_euler = rot

    me = plate.data
    front_narrow_ratio = plate_width_front / plate_width_rear
    for v in me.vertices:
        if v.co.y > 0.5:
            v.co.x = v.co.x * front_narrow_ratio
    me.update()
    _assign_material(plate, pedal_mat)
    objs.append(plate)

    # Vertical rods x2
    vertical_rod_length = 0.12
    vertical_rod_radius = 0.006

    for x_sign in [-1, 1]:
        v_x = x_sign * (plate_width_rear / 2 - 0.01)
        v_y = -(plate_length / 2 - 0.02) + 0.1
        v_z = plate_thickness / 2 + vertical_rod_length / 2

        rod_loc = loc + _rotate_vec((v_x, v_y, v_z), rot)
        bpy.ops.mesh.primitive_cylinder_add(radius=vertical_rod_radius, depth=vertical_rod_length, location=rod_loc)
        v_rod = bpy.context.view_layer.objects.active
        v_rod.name = f"Pedal_VerticalRod_{x_sign}"
        v_rod.rotation_euler = rot
        _assign_material(v_rod, pedal_mat)
        objs.append(v_rod)

    # Horizontal rod x1 (左右X方向に走り、垂直支柱±0.065に接続)
    h_rod_length = 2 * (plate_width_rear / 2 - 0.01)
    h_rod_radius = 0.005
    h_rod_z = plate_thickness / 2 + vertical_rod_length
    h_rod_y = -(plate_length / 2 - 0.02) + 0.1

    h_rod_loc = loc + _rotate_vec((0, h_rod_y, h_rod_z), rot)
    bpy.ops.mesh.primitive_cylinder_add(radius=h_rod_radius, depth=h_rod_length, location=h_rod_loc)
    h_rod = bpy.context.view_layer.objects.active
    h_rod.name = "Pedal_HorizontalRod"
    h_rod.rotation_euler = (rot[0], rot[1] + math.radians(90), rot[2])
    _assign_material(h_rod, pedal_mat)
    objs.append(h_rod)

    # Arm — 支点(Pedal_HorizontalRod)から垂直上方向(Z+)に伸びる
    # アーム長は支点からビーター上部までの距離
    arm_length = 0.18
    arm_thickness = 0.01
    arm_center_z = h_rod_z + arm_length / 2
    arm_y = h_rod_y  # 支点と同じY位置

    arm_loc = loc + _rotate_vec((0, arm_y, arm_center_z), rot)
    bpy.ops.mesh.primitive_cylinder_add(radius=arm_thickness, depth=arm_length, location=arm_loc)
    arm = bpy.context.view_layer.objects.active
    arm.name = "Pedal_Arm"
    arm.rotation_euler = rot  # Z方向に沿うので回転はrotをそのまま
    _assign_material(arm, pedal_mat)
    objs.append(arm)

    # Beater block — アーム上部から前方(Y-方向、バスドラヘッド側)にオフセット配置
    # ビーターはY軸方向に倒れたシリンダー（面がバスドラを向く）
    beater_radius = 0.02
    beater_height = 0.03
    beater_z = h_rod_z + arm_length   # アーム上部Z
    # アームは h_rod_y 位置のZ円柱。ビーター(Y円柱)の中心線がアーム先端(支点y)に
    # かかり、後端がアーム先端に接して前方(バスドラ側Y-)に伸びるように配置する。
    # (コードは h_rod_y を足していないため、ここに明示的に h_rod_y を含める)
    beater_y_offset = h_rod_y - beater_height / 2

    beater_loc = loc + _rotate_vec((0, beater_y_offset, beater_z), rot)
    bpy.ops.mesh.primitive_cylinder_add(radius=beater_radius, depth=beater_height, location=beater_loc)
    beater = bpy.context.view_layer.objects.active
    beater.name = "Pedal_BeaterBlock"
    beater.rotation_euler = (rot[0] + math.radians(90), rot[1], rot[2])  # Y方向に倒す（面が前方を向く）
    _assign_material(beater, pedal_mat)
    objs.append(beater)

    return objs


# =============================================================================
# Full Drum Set Assembly
# =============================================================================

def create_full_drum_set(stage_width: float = 10.0, stage_depth: float = 8.0,
                         location_offset: tuple = (0.0, 0.0, 0.0),
                         hihat_pedal_angle_deg: float = 60) -> list:
    """ドラムセットをステージ奥に配置。location_offset=(x,y,z)で基点をオフセット可能。
    drum_set_model.pyのmain()と同等の座標・構成を使用する。
    
    Args:
        hihat_pedal_angle_deg: ハイハットペダルのZ軸回転角度（度）
            - Z軸正方向への右ねじ回転を正とする
            - 0 = Y軸正方向
            - 60 = Y+からX-側へ60度（初期値）
    """
    all_objs = []
    offset_x, offset_y, offset_z = location_offset

    center_x = offset_x
    center_y = offset_y - stage_depth * 0.3
    base_z = offset_z

    # Bass drum dimensions
    bass_radius_m = 22 * INCH / 2  # 0.2794m
    bass_top_z = bass_radius_m * 2 + base_z  # 0.5588m

    # --- Bass Drum ---
    all_objs.extend(create_bass_drum(location=(center_x, center_y + 0.2, bass_radius_m + base_z)))

    # --- Kick Pedal ---
    all_objs.extend(create_kick_pedal(location=(center_x, center_y + 0.60, 0.015 + base_z)))

    # --- Tom Mount Poles ---
    pole_length = 0.3
    mount_z = bass_top_z + pole_length / 2

    all_objs.extend(create_tom_mount_only(
        tom_radius_inch=10,
        location=(center_x, center_y + 0.2, mount_z),
        side="right",
        pole_length=pole_length
    ))

    all_objs.extend(create_tom_mount_only(
        tom_radius_inch=12,
        location=(center_x, center_y + 0.2, mount_z),
        side="left",
        pole_length=pole_length
    ))

    # Pole top Z
    pole_top_z = mount_z + pole_length / 2  # bass_top_z + pole_length

    # --- 10" Tom (right) ---
    tom10_height = 8 * INCH
    tom10_center_z = pole_top_z - tom10_height / 2
    all_objs.extend(create_tom_tom(
        radius_inch=10, height_inch=8,
        location=(center_x + 0.2, center_y + 0.27, tom10_center_z),
        rotation=(math.radians(-15), 0, 0),
        mount_angle=0
    ))

    # --- 12" Tom (left) ---
    tom12_height = 10 * INCH
    tom12_center_z = pole_top_z - tom12_height / 2
    all_objs.extend(create_tom_tom(
        radius_inch=12, height_inch=10,
        location=(center_x - 0.25, center_y + 0.3, tom12_center_z),
        rotation=(math.radians(-15), 0, 0),
        mount_angle=0
    ))

    # --- H-bars ---
    all_objs.extend(create_tom_hbar(
        location=(center_x + 0.125, center_y + 0.2, pole_top_z),
        rotation=(0, 0, 0),
        bar_length=0.18
    ))

    all_objs.extend(create_tom_hbar(
        location=(center_x - 0.15, center_y + 0.2, pole_top_z),
        rotation=(0, 0, 0),
        bar_length=0.20
    ))

    # --- Snare Stand + Snare Drum ---
    snare_stand_pos = (center_x + 0.25, center_y + 0.65, 0.30 + base_z)
    all_objs.extend(create_snare_stand(location=snare_stand_pos))
    all_objs.extend(create_snare_drum(
        radius_inch=14, depth_inch=6,
        location=(snare_stand_pos[0], snare_stand_pos[1], 0.376 + base_z)
    ))

    # --- Floor Tom ---
    all_objs.extend(create_floor_tom(16, 14, location=(center_x - 0.3, center_y + 0.65, 0.3 + base_z), ground_z=base_z))

    # --- Hi-Hat ---
    all_objs.extend(create_hihat(
        location=(center_x + 0.45, center_y + 0.8, 0.65 + base_z),
        pedal_angle_deg=hihat_pedal_angle_deg
    ))

    # --- Ride Cymbal ---
    all_objs.extend(create_cymbal_with_stand(
        "Ride", 20, 0.005,
        stand_base_xy=(center_x - 0.6, center_y + 0.1),
        cymbal_location=(center_x - 0.5, center_y + 0.4, 1.1 + base_z),
        rotation=(0, 0, 0),
        stand_height=1.1, tilt_angle=-15
    ))

    # --- Crash Cymbal ---
    all_objs.extend(create_cymbal_with_stand(
        "Crash", 16, 0.004,
        stand_base_xy=(center_x + 0.6, center_y + 0.1),
        cymbal_location=(center_x + 0.4, center_y + 0.5, 1.1 + base_z),
        rotation=(0, 0, 0),
        stand_height=1.2, tilt_angle=-20
    ))

    # Join all drum set parts into a single object
    joined = _join_objects(all_objs)
    if joined is not None:
        joined.name = "Drum_Set"
        return [joined]

    return all_objs


# =============================================================================
# Material Application
# =============================================================================

def apply_materials_to_drum_set():
    shell_mat = _get_mat("Drum_Shell_BlackPearl")
    head_mat = _get_mat("Drum_Head_Coated")
    chrome_mat = _get_mat("Hardware_Chrome")
    brass_mat = _get_mat("Cymbal_Brass")
    pedal_mat = _get_mat("Pedal_BlackSteel")

    for obj in bpy.context.scene.objects:
        if obj.type != 'MESH':
            continue

        name_lower = obj.name.lower()

        if 'cymbal' in name_lower or 'hihat' in name_lower or 'crash_body' in name_lower or 'ride_body' in name_lower:
            _assign_material(obj, brass_mat)
        elif 'pedal' in name_lower or 'plate' in name_lower or 'beater' in name_lower or 'arm' in name_lower:
            _assign_material(obj, pedal_mat)
        elif 'head' in name_lower:
            _assign_material(obj, head_mat)
        elif 'stand_' in name_lower or 'mount' in name_lower or 'hoop' in name_lower or 'rod' in name_lower or 'hbar' in name_lower or 'tray' in name_lower or 'holder' in name_lower or 'sphere' in name_lower or 'beam' in name_lower:
            _assign_material(obj, chrome_mat)
        elif 'shell' in name_lower or 'bass_' in name_lower or 'tom_' in name_lower or 'floor_tom' in name_lower or 'snare_' in name_lower:
            _assign_material(obj, shell_mat)
        else:
            _assign_material(obj, chrome_mat)


def clear_drum_set_objects():
    prefixes = ['Bass_', 'Snare_', 'Tom_', 'FloorTom_', 'Hihat', 'Crash', 'Ride', 'Pedal_', 'Stand_']
    scene = bpy.context.scene

    to_delete = []
    for obj in scene.objects:
        if obj.type == 'MESH' and any(obj.name.startswith(p) for p in prefixes):
            to_delete.append(obj)

    if to_delete:
        bpy.ops.object.select_all(action='DESELECT')
        for obj in to_delete:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = to_delete[0]
        bpy.ops.object.delete(use_global=False)

    mat_names = ["Drum_Shell_BlackPearl", "Drum_Head_Coated", "Hardware_Chrome", "Cymbal_Brass", "Pedal_BlackSteel"]
    for mat_name in mat_names:
        if mat_name in bpy.data.materials:
            bpy.data.materials.remove(bpy.data.materials[mat_name])


# =============================================================================
# Drummer Chair (round seat, no backrest, central column + 5 casters)
# =============================================================================

def create_drummer_chair(location: tuple = (0, 0, 0), seat_height: float = 0.55, seat_radius: float = 0.18) -> list:
    """
    ドラム椅子作成（背もたれ無しの円形シート）
    - シート面（円形ディスク、上面に縁取りリング）
    - センター支柱（气柱）
    - ガスレフトシリンダ
    - ベースディスク
    - キャスター脚5本
    
    Args:
        location: 椅子の中心位置(x, y, z) — zは床面
        seat_height: シート上面の高さ（床からの距離）
        seat_radius: シートの半径
    """
    objs = []
    loc = mathutils.Vector(location)
    
    chrome_mat = _get_mat("Hardware_Chrome")
    pedal_mat = _get_mat("Pedal_BlackSteel")
    
    # --- Seat disk (cylinder, very thin) ---
    seat_thickness = 0.04
    seat_z = loc.z + seat_height
    bpy.ops.mesh.primitive_cylinder_add(radius=seat_radius, depth=seat_thickness, location=(loc.x, loc.y, seat_z))
    seat = bpy.context.view_layer.objects.active
    seat.name = "Chair_Seat"
    _assign_material(seat, pedal_mat)
    objs.append(seat)
    
    # --- Seat edge ring (torus on top of seat) ---
    ring_radius = seat_radius
    ring_thick = 0.012
    ring_z = seat_z + seat_thickness / 2 + ring_thick / 2
    bpy.ops.mesh.primitive_torus_add(
        major_radius=ring_radius, minor_radius=ring_thick,
        major_segments=32, minor_segments=8, location=(loc.x, loc.y, ring_z)
    )
    seat_ring = bpy.context.view_layer.objects.active
    seat_ring.name = "Chair_SeatRing"
    _assign_material(seat_ring, pedal_mat)
    objs.append(seat_ring)
    
    # --- Base disk (bottom plate) — define first so column can reference it ---
    base_disk_radius = 0.25
    base_disk_thickness = 0.015
    base_disk_z = loc.z + base_disk_thickness / 2

    # --- Center column (main post) ---
    column_radius = 0.02
    column_top_z = seat_z - seat_thickness / 2
    column_bottom_z = base_disk_z + base_disk_thickness / 2  # column sits on top of base disk
    column_height = column_top_z - column_bottom_z
    column_center_z = (column_top_z + column_bottom_z) / 2

    bpy.ops.mesh.primitive_cylinder_add(radius=column_radius, depth=column_height, location=(loc.x, loc.y, column_center_z))
    column = bpy.context.view_layer.objects.active
    column.name = "Chair_Column"
    _assign_material(column, chrome_mat)
    objs.append(column)
    
    # --- Gas lift cylinder (slightly thicker, below seat) ---
    gaslift_height = 0.15
    gaslift_radius = 0.028
    gaslift_z = seat_z - seat_thickness / 2 - gaslift_height / 2
    bpy.ops.mesh.primitive_cylinder_add(radius=gaslift_radius, depth=gaslift_height, location=(loc.x, loc.y, gaslift_z))
    gaslift = bpy.context.view_layer.objects.active
    gaslift.name = "Chair_GasLift"
    _assign_material(gaslift, chrome_mat)
    objs.append(gaslift)
    
    # Base disk mesh creation (variables defined above for column calculation)
    bpy.ops.mesh.primitive_cylinder_add(radius=base_disk_radius, depth=base_disk_thickness, location=(loc.x, loc.y, base_disk_z))
    base_disk = bpy.context.view_layer.objects.active
    base_disk.name = "Chair_BaseDisk"
    _assign_material(base_disk, chrome_mat)
    objs.append(base_disk)
    
    # --- 5 caster legs + wheels ---
    caster_count = 5
    caster_leg_length = 0.06
    caster_wheel_radius = 0.018
    
    for i in range(caster_count):
        angle = 2 * math.pi / caster_count * i
        
        foot_x = loc.x + math.cos(angle) * (base_disk_radius - 0.02)
        foot_y = loc.y + math.sin(angle) * (base_disk_radius - 0.02)
        
        # Caster leg (cylinder from base disk to wheel center)
        leg_z = base_disk_z - caster_leg_length / 2
        bpy.ops.mesh.primitive_cylinder_add(radius=0.006, depth=caster_leg_length, location=(foot_x, foot_y, leg_z))
        cleg = bpy.context.view_layer.objects.active
        cleg.name = f"Chair_CasterLeg_{i}"
        _assign_material(cleg, chrome_mat)
        objs.append(cleg)
        
        # Caster wheel (sphere)
        wheel_z = base_disk_z - caster_leg_length - caster_wheel_radius / 2
        bpy.ops.mesh.primitive_uv_sphere_add(radius=caster_wheel_radius, segments=12, location=(foot_x, foot_y, wheel_z))
        wheel = bpy.context.view_layer.objects.active
        wheel.name = f"Chair_CasterWheel_{i}"
        _assign_material(wheel, pedal_mat)
        objs.append(wheel)
    
    # Join all chair parts into a single object
    joined = _join_objects(objs)
    if joined is not None:
        joined.name = "Drummer_Chair"
        return [joined]
    
    return objs
