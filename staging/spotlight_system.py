# -*- coding: utf-8 -*-
"""spotlight_system.py - Spotlight modeling module (from spotlight_model.py)"""
import bpy
import bmesh
import math
import mathutils


# =============================================================================
# Material Cache
# =============================================================================

_mat_cache = {}


def _get_mat(name: str) -> bpy.types.Material:
    if name in _mat_cache:
        return _mat_cache[name]

    mats = {
        "Spotlight_DarkMetal": ((0.12, 0.12, 0.13, 1.0), 0.9, 0.4),
        "Spotlight_Lens": ((0.7, 0.85, 1.0, 1.0), 0.0, 0.2),
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
    if len(obj.data.materials) == 0:
        obj.data.materials.append(material)
    else:
        obj.data.materials[0] = material


def _join_objects(obj_list):
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
    return bpy.context.active_object


def _create_beam_material(name: str, color: tuple, alpha: float = 0.15, emit_strength: float = None,
                           fade_length: float = 6.0, fade_power: float = 3.0,
                           radial_fade: bool = True, radial_fade_power: float = 4.0, radial_scale: float = 1.0):
    """Create a semi-transparent beam material with distance-based AND radial fade emission.

    オブジェクト座標 Z=0 (光源近傍) で最大の明度/透明度、
    Z=fade_length (ビーム先端) でゼロに減衰する。

    fade_power > 1 に設定すると減衰が急激になる（光源直下のみが明るい）。
      axial_factor = clamp(1 - Z/fade_length, 0, 1) ** fade_power

    radial_fade=True の場合、中心軸(X=Y=0)から外側に向かってGauss的減衰する。
      r² = X² + Y²
      radial_factor = exp( -r² / (2 * sigma²) )
      ここで sigma = radial_scale（ガウス分布の標準偏差）

    final_factor = axial_factor * radial_factor
                      → AlphaとEmission Strengthに乗算

    Args:
        name: Material名
        color: ビーム色 (R, G, B)
        alpha: 最大透明度
        emit_strength: 発光強度（Noneの場合はalphaから自動計算）
        fade_length: 軸方向の減衰長さ
        fade_power: 軸方向の減衰パワー（>1で急減衰）
        radial_fade: Trueなら半径方向のGauss的減衰を有効化
        radial_fade_power: 半径方向の減衰パワー（大きいほど中心軸付近のみが明るい）
        radial_scale: 半径方向減衰のスケール（小さいほど中心軸に集中）
    """
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    mat.blend_method = 'BLEND'

    tree = mat.node_tree
    nodes = tree.nodes
    links = tree.links
    nodes.clear()

    # -- Create base nodes --
    n_bsdf     = nodes.new('ShaderNodeBsdfPrincipled')
    n_output   = nodes.new('ShaderNodeOutputMaterial')
    n_texcoord = nodes.new('ShaderNodeTexCoord')
    n_separate = nodes.new('ShaderNodeSeparateXYZ')

    # -- Axial fade nodes (Z direction) --
    n_z_divide   = nodes.new('ShaderNodeMath')
    n_z_subtract = nodes.new('ShaderNodeMath')
    n_z_min      = nodes.new('ShaderNodeMath')
    n_z_max      = nodes.new('ShaderNodeMath')

    # -- Radial fade nodes: Gaussian exp(-r² / (2 * sigma²)) --
    # r² = X² + Y² は直接計算（sqrt不要）
    n_x_mul  = nodes.new('ShaderNodeMath')   # X * X -> x²
    n_y_mul  = nodes.new('ShaderNodeMath')   # Y * Y -> y²
    n_xy_add = nodes.new('ShaderNodeMath')   # x² + y² = r²
    # -r² / (2 * sigma²) を計算:
    n_sigma_sq = nodes.new('ShaderNodeMath')  # sigma * sigma -> sigma²
    n_two_mul  = nodes.new('ShaderNodeMath')  # 2 * sigma²
    n_neg_r2 = nodes.new('ShaderNodeMath')   # -1 * r² -> -r²
    n_divide = nodes.new('ShaderNodeMath')   # -r² / (2*sigma²)
    # exp(x) = e^x をPOWERノードで実現
    n_exp    = nodes.new('ShaderNodeMath')   # e ^ (-r²/(2σ²))

    # -- Combine axial * radial -> final fade --
    n_combine = nodes.new('ShaderNodeMath')  # axial * radial
    n_mul_alpha = nodes.new('ShaderNodeMath')
    n_mul_emit = nodes.new('ShaderNodeMath')

    # -- Position all nodes --
    n_bsdf.location     = (400, 50)
    n_output.location   = (700, 50)
    n_texcoord.location = (-1200, -300)
    n_separate.location = (-1050, -300)

    # Axial fade chain
    n_z_divide.location   = (-900, -200)
    n_z_subtract.location = (-750, -200)
    n_z_min.location      = (-600, -200)
    n_z_max.location      = (-450, -200)

    # Radial fade chain (Gaussian)
    n_x_mul.location   = (-900, -400)
    n_y_mul.location   = (-900, -500)
    n_xy_add.location  = (-750, -450)
    n_sigma_sq.location = (-600, -550)
    n_two_mul.location = (-450, -550)
    n_neg_r2.location = (-450, -450)
    n_divide.location = (-300, -480)
    n_exp.location    = (-150, -480)

    # Combine & final multipliers
    n_combine.location    = (250, -300)
    n_mul_alpha.location  = (400, -100)
    n_mul_emit.location   = (400, -250)

    # -- Setup axial fade operations --
    n_z_divide.operation = 'DIVIDE'
    n_z_divide.inputs[1].default_value = fade_length

    n_z_subtract.operation = 'SUBTRACT'
    n_z_subtract.inputs[0].default_value = 1.0

    n_z_min.operation = 'MINIMUM'
    n_z_min.inputs[1].default_value = 1.0

    n_z_max.operation = 'MAXIMUM'
    n_z_max.inputs[1].default_value = 0.0

    # -- Setup radial fade operations (Gaussian: exp(-r²/(2σ²))) --
    n_x_mul.operation = 'MULTIPLY'   # X*X -> x²
    n_y_mul.operation = 'MULTIPLY'   # Y*Y -> y²
    n_xy_add.operation = 'ADD'       # x² + y² = r²
    
    # sigma²
    n_sigma_sq.operation = 'MULTIPLY'
    # -r² (multiply by -1)
    n_neg_r2.operation = 'MULTIPLY'
    n_neg_r2.inputs[0].default_value = -1.0
    # 2 * sigma²
    n_two_mul.operation = 'MULTIPLY'
    n_two_mul.inputs[0].default_value = 2.0
    # -r² / (2*sigma²)
    n_divide.operation = 'DIVIDE'
    # exp: e ^ x
    n_exp.operation = 'POWER'

    # -- Setup combine & multipliers --
    n_combine.operation = 'MULTIPLY'
    n_mul_alpha.operation = 'MULTIPLY'
    n_mul_alpha.inputs[0].default_value = alpha
    n_mul_emit.operation = 'MULTIPLY'
    if emit_strength is None:
        emit_strength = max(0.5, 2.0 * alpha)
    n_mul_emit.inputs[0].default_value = emit_strength

    # -- Wire connections --
    # TextureCoord -> SeparateXYZ
    links.new(n_texcoord.outputs['Object'], n_separate.inputs['Vector'])

    # Axial: Z -> divide -> subtract -> clamp
    links.new(n_separate.outputs['Z'],   n_z_divide.inputs[0])
    links.new(n_z_divide.outputs['Value'], n_z_subtract.inputs[1])
    links.new(n_z_subtract.outputs['Value'], n_z_min.inputs[0])
    links.new(n_z_min.outputs['Value'],  n_z_max.inputs[0])

    # Radial (Gaussian): X,Y -> x², y² -> r² -> sigma² -> 2*sigma² -> -r²/(2σ²) -> exp()
    links.new(n_separate.outputs['X'],   n_x_mul.inputs[0])
    links.new(n_separate.outputs['X'],   n_x_mul.inputs[1])
    links.new(n_separate.outputs['Y'],   n_y_mul.inputs[0])
    links.new(n_separate.outputs['Y'],   n_y_mul.inputs[1])
    # x² + y² = r²
    links.new(n_x_mul.outputs['Value'],  n_xy_add.inputs[0])
    links.new(n_y_mul.outputs['Value'],  n_xy_add.inputs[1])
    # sigma * sigma = sigma²
    n_sigma_sq.inputs[0].default_value = radial_scale
    n_sigma_sq.inputs[1].default_value = radial_scale
    # 2 * sigma²
    links.new(n_sigma_sq.outputs['Value'], n_two_mul.inputs[1])
    # -1 * r² = -r²
    links.new(n_xy_add.outputs['Value'], n_neg_r2.inputs[1])
    # -r² / (2*sigma²)
    links.new(n_neg_r2.outputs['Value'], n_divide.inputs[0])
    links.new(n_two_mul.outputs['Value'], n_divide.inputs[1])
    # exp(-r²/(2σ²)) = e ^ (-r²/(2σ²))
    # POWER node: left input is exponent, right input is base (e)
    n_exp.inputs[1].default_value = math.e  # base: e
    links.new(n_divide.outputs['Value'], n_exp.inputs[0])  # exponent: -r²/(2σ²)

    # Combine: axial * radial
    if radial_fade:
        links.new(n_z_max.outputs['Value'], n_combine.inputs[0])
        links.new(n_exp.outputs['Value'], n_combine.inputs[1])
    else:
        # radial_fade無効時はaxialのみ使用（radial=1.0相当）
        links.new(n_z_max.outputs['Value'], n_combine.inputs[0])
        n_combine.inputs[1].default_value = 1.0

    # Final multipliers
    links.new(n_combine.outputs['Value'], n_mul_alpha.inputs[1])
    links.new(n_combine.outputs['Value'], n_mul_emit.inputs[1])

    # BSDF connections
    links.new(n_mul_alpha.outputs['Value'], n_bsdf.inputs['Alpha'])
    links.new(n_mul_emit.outputs['Value'],  n_bsdf.inputs['Emission Strength'])

    n_bsdf.inputs['Base Color'].default_value = (color[0], color[1], color[2], 1.0)
    n_bsdf.inputs['Metallic'].default_value = 0.0
    n_bsdf.inputs['Roughness'].default_value = 1.0
    n_bsdf.inputs['Emission Color'].default_value = (color[0], color[1], color[2], 1.0)

    links.new(n_bsdf.outputs['BSDF'], n_output.inputs['Surface'])
    return mat


def _create_beam_cone(location, rotation, spot_size_rad, beam_length=6.0):
    """Create a cone mesh using bmesh for exact vertex positioning.

    ローカル座標系:
      - Apex (尖端) at origin (0, 0, 0) = 光源位置
      - Base (広い側) at Z=beam_length = ビームの遠方側
    World変換で回転を適用し、apexが location に重なるよう設定。

    Args:
        location: Light source position (tuple or mathutils.Vector)
        rotation: Euler rotation of the spotlight
        spot_size_rad: Half-angle of the beam in radians
        beam_length: Length of the beam cone
    """
    loc = mathutils.Vector(location)
    rot = mathutils.Euler(rotation)

    base_radius = beam_length * math.tan(spot_size_rad)
    segments = 32

    # Create mesh with bmesh for full control over vertex positions
    bm = bmesh.new()

    # Apex vertex at origin
    apex = bm.verts.new((0, 0, 0))

    # Base vertices in a circle at Z=beam_length
    base_verts = []
    for i in range(segments):
        angle = 2 * math.pi / segments * i
        x = base_radius * math.cos(angle)
        y = base_radius * math.sin(angle)
        v = bm.verts.new((x, y, beam_length))
        base_verts.append(v)

    # Side faces: apex + two adjacent base vertices
    for i in range(segments):
        next_i = (i + 1) % segments
        bm.faces.new([apex, base_verts[i], base_verts[next_i]])

    # Base face (circle at the wide end) - closed cone
    bm.faces.new(base_verts)

    bm.normal_update()

    mesh = bpy.data.meshes.new("Spotlight_Beam_Mesh")
    bm.to_mesh(mesh)  # Write bmesh data to mesh
    bm.free()

    cone_obj = bpy.data.objects.new("Spotlight_Beam", mesh)
    bpy.context.collection.objects.link(cone_obj)

    # Compute world matrix: apex at origin, base extending along +Z.
    # We want +Z local axis -> spotlight direction (0,0,-1) rotated by rot.
    # And the up direction should match the scene orientation.
    forward = mathutils.Vector((0, 0, -1))
    forward.rotate(rot)

    # Build a rotation matrix that maps +Z to -forward (since our cone extends +Z but spotlight looks -Z direction... wait no)
    # Actually our cone apex is at origin and base is at +Z. The spotlight emits in the -Z rotated direction.
    # So we want the cone's +Z local axis to map to the spotlight emission direction `forward`.
    up = mathutils.Vector((0, 1, 0))
    up.rotate(rot)
    right = forward.cross(up).normalized()
    up = right.cross(forward).normalized()

    # Rotation matrix where columns are the images of basis vectors:
    rot_matrix = mathutils.Matrix((
        (right.x, up.x, forward.x, 0),
        (right.y, up.y, forward.y, 0),
        (right.z, up.z, forward.z, 0),
        (0, 0, 0, 1)
    ))

    # Translate apex to light location
    trans_matrix = mathutils.Matrix.Translation(loc)
    cone_obj.matrix_world = trans_matrix @ rot_matrix

    return cone_obj


def _create_two_layer_beams(location, rotation, spot_size_rad, beam_length=6.0):
    """Create two-layer beam cones: inner core (bright) + outer halo (dim).

    内側コアは開角を狭く・明るく、外側ハローは広角・薄く設定する。
    これにより「中心軸付近と光源近傍が明るい」という散乱光の雰囲気を模倣する。

    Args:
        location: Light source position
        rotation: Euler rotation
        spot_size_rad: Full spot half-angle in radians
        beam_length: Length of the outer halo beam
    Returns:
        List of cone_object tuples
    """
    beams = []

    # --- Inner core ---
    # 開角: スポットの40%, Emission强度高め, α=0.18
    core_angle = spot_size_rad * 0.4
    core_length = beam_length
    core_cone = _create_beam_cone(location, rotation, core_angle, core_length)
    core_cone.name = "Beam_Core"
    beams.append(core_cone)

    # --- Outer halo ---
    # 開角: フルスポットサイズ, Emission強度低め, α=0.05
    halo_length = beam_length * 1.15  # 少し長く拡散させる
    halo_cone = _create_beam_cone(location, rotation, spot_size_rad, halo_length)
    halo_cone.name = "Beam_Halo"
    beams.append(halo_cone)

    return beams


def _clear_spotlight_meshes():
    to_delete = [o for o in bpy.context.scene.objects if o.type == 'MESH' and ('SP' in o.name or 'Spotlight' in o.name)]
    lights_del = [o for o in bpy.context.scene.objects if o.type == 'LIGHT' and ('SpotLight' in o.name or 'SP' in o.name)]
    if to_delete:
        bpy.ops.object.select_all(action='DESELECT')
        for o in to_delete: o.select_set(True)
        bpy.context.view_layer.objects.active = to_delete[0]
        bpy.ops.object.delete(use_global=False)
    for lt in lights_del: bpy.data.objects.remove(lt, do_unlink=True)


def _create_spotlight(location, rotation, energy=150, color=(1,1,1), spot_size=math.radians(20), spot_blend=0.3,
                       beam=False, beam_length=6.0, core_fade_power=2.0, halo_fade_power=1.0,
                       radial_fade=True, radial_fade_power=2.0, core_radial_scale=None, halo_radial_scale=None):
    """Create a single spotlight with housing parts joined into one mesh object.

    Args:
        location: Position of the spotlight
        rotation: Euler rotation (x, y, z)
        energy: Light energy
        color: Light color (R, G, B)
        spot_size: Spot beam half-angle in radians
        spot_blend: Spot edge softness
        beam: If True, create a visible beam cone mesh
        beam_length: Length of the beam cone
        core_fade_power: Inner coreの軸方向減衰指数（>1で急速減衰、デフォルト2.0）
        halo_fade_power: Outer haloの軸方向減衰指数（=1で線形、デフォルト1.0）
        radial_fade: Trueなら半径方向Gauss的減衰を有効化（境目を滑らかにする）
        radial_fade_power: 半径方向減衰のパワー（大きいほど中心に集中）
        core_radial_scale: Coreの半径減衰スケール（Noneの場合は自動計算）
        halo_radial_scale: Haloの半径減衰スケール（Noneの場合は自動計算）
    """
    loc = mathutils.Vector(location); rot = mathutils.Euler(rotation)
    housing_length, housing_radius = 0.25, 0.1
    lens_radius, lens_thickness = 0.09, 0.03
    mount_height, mount_width, mount_depth = 0.06, 0.12, 0.14
    fin_count, fin_height = 8, 0.03
    dir_vec = mathutils.Vector((0, 0, -1)); dir_vec.rotate(rot)
    rot_mat = rot.to_matrix().to_4x4()
    
    metal_mat = _get_mat("Spotlight_DarkMetal")
    lens_mat = _get_mat("Spotlight_Lens")

    mesh_objs = []
    # Housing
    bpy.ops.mesh.primitive_cylinder_add(radius=housing_radius, depth=housing_length, location=loc)
    housing = bpy.context.active_object; housing.name = "Spotlight_Housing"; housing.rotation_euler = rot
    bm = bmesh.new(); bm.from_mesh(housing.data); half_len = housing_length / 2
    for face in bm.faces:
        if abs(face.calc_center_median().z + half_len) < 0.01: bm.faces.remove(face)
    bm.to_mesh(housing.data); bm.free(); housing.data.update()
    _assign_material(housing, metal_mat)
    mesh_objs.append(housing)
    # Lens
    lens_loc = loc + dir_vec * (housing_length / 2 + lens_thickness / 2)
    bpy.ops.mesh.primitive_torus_add(major_radius=lens_radius, minor_radius=0.015, major_segments=32, minor_segments=16, location=lens_loc)
    lens = bpy.context.active_object; lens.name = "Spotlight_Lens"; lens.rotation_euler = rot
    _assign_material(lens, lens_mat)
    mesh_objs.append(lens)
    # Fins
    for i in range(fin_count):
        angle = 2 * math.pi / fin_count * i
        offset_R = housing_radius + fin_height / 2
        local_offset = mathutils.Vector((math.cos(angle) * offset_R, math.sin(angle) * offset_R, 0))
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0,0,0))
        fin = bpy.context.active_object; fin.name = f"Spotlight_Fin_{i}"
        M_scale = mathutils.Matrix.Diagonal(mathutils.Vector((fin_height, fin_height, housing_length*0.7, 1)))
        fin.matrix_world = mathutils.Matrix.Translation(loc) @ rot_mat @ mathutils.Matrix.Translation(local_offset) @ M_scale
        _assign_material(fin, metal_mat)
        mesh_objs.append(fin)
    # Mount
    mount_dir_vec = mathutils.Vector((0, 0, 1)); mount_dir_vec.rotate(rot)
    mount_loc = loc + mount_dir_vec * (housing_length / 2 + mount_height / 2)
    bpy.ops.mesh.primitive_cube_add(size=1, location=mount_loc)
    mount = bpy.context.active_object; mount.name = "Spotlight_Mount"
    mount.scale = (mount_width / 2, mount_depth / 2, mount_height); mount.rotation_euler = rot
    _assign_material(mount, metal_mat)
    mesh_objs.append(mount)
    
    # Join all mesh parts into a single object
    joined_housing = _join_objects(mesh_objs)
    if joined_housing is not None:
        joined_housing.name = "Spotlight_Housing"
    
    # Light (配置: ハウジング内中央、レンズの手前側に配置)
    light_loc = lens_loc - dir_vec * 0.05
    spot_data = bpy.data.lights.new(name="SpotLight_Data", type='SPOT')
    spot_data.energy = energy; spot_data.color[0] = color[0]; spot_data.color[1] = color[1]; spot_data.color[2] = color[2]
    spot_data.spot_size = spot_size; spot_data.spot_blend = spot_blend
    light_obj = bpy.data.objects.new("SpotLight_Source", spot_data)
    light_obj.location = light_loc; light_obj.rotation_euler = rot
    bpy.context.collection.objects.link(light_obj)
    
    objs = []
    if joined_housing: objs.append(joined_housing)
    objs.append(light_obj)

    # Create visible two-layer beam cones if requested
    if beam:
        beam_cones = _create_two_layer_beams(
            location=light_loc,
            rotation=rotation,
            spot_size_rad=spot_size,
            beam_length=beam_length,
        )

        # 半径減衰スケールを自動計算（ビームの最大半径の一定比率）
        if core_radial_scale is None:
            core_radial_scale = beam_length * math.tan(spot_size * 0.4) * 1.5
        if halo_radial_scale is None:
            halo_radial_scale = beam_length * 1.15 * math.tan(spot_size) * 1.5

        # Inner core material: bright, denser
        core_mat_name = f"Beam_Core_{color[0]:.2f}_{color[1]:.2f}_{color[2]:.2f}"
        core_mat = _create_beam_material(
            core_mat_name, color, alpha=0.18, emit_strength=2.5,
            fade_length=beam_length, fade_power=core_fade_power,
            radial_fade=radial_fade, radial_fade_power=radial_fade_power,
            radial_scale=core_radial_scale
        )
        # Outer halo material: dim, more transparent
        halo_mat_name = f"Beam_Halo_{color[0]:.2f}_{color[1]:.2f}_{color[2]:.2f}"
        halo_mat = _create_beam_material(
            halo_mat_name, color, alpha=0.05, emit_strength=0.4,
            fade_length=beam_length * 1.15, fade_power=halo_fade_power,
            radial_fade=radial_fade, radial_fade_power=radial_fade_power * 0.6,
            radial_scale=halo_radial_scale
        )

        for cone in beam_cones:
            if "Core" in cone.name:
                _assign_material(cone, core_mat)
            else:
                _assign_material(cone, halo_mat)
            objs.append(cone)

    return objs


class SpotlightSystem:
    def __init__(self, count=1, spacing=1.0, start_x=0.0, start_y=0, start_z=4.0, rotation_angle_deg=None,
                 energy=150, color=(1, 1, 1), spot_size=math.radians(20), spot_blend=0.3, beam=False, beam_length=6.0,
                 core_fade_power=1.0, halo_fade_power=1.0, rotation_z_deg=0,
                 radial_fade=True, radial_fade_power=0.5):
        self.count, self.spacing = count, spacing
        self.start_x, self.start_y, self.start_z = start_x, start_y, start_z
        self.objects = []
        # rotation_angle_deg: X軸回転角（度）Noneなら自動計算（設置位置からステージ中央下向き）
        self.rotation_angle_deg = rotation_angle_deg
        # rotation_z_deg: Z軸周りの回転角（度）、デフォルト0
        self.rotation_z_deg = rotation_z_deg
        # ライト設定
        self.energy = energy
        self.color = color
        self.spot_size = spot_size
        self.spot_blend = spot_blend
        # ビーム表示設定
        self.beam = beam
        self.beam_length = beam_length
        self.core_fade_power = core_fade_power
        self.halo_fade_power = halo_fade_power
        # 半径方向減衰設定
        self.radial_fade = radial_fade
        self.radial_fade_power = radial_fade_power

    def _compute_rotation(self, index):
        """スポットライトの向きを計算。
        各スポットライトがステージ面（Z=0付近）の中央方向を照らすように設定。"""
        rot_z = math.radians(self.rotation_z_deg)
        
        if self.rotation_angle_deg is not None:
            return (math.radians(self.rotation_angle_deg), 0, rot_z)
        
        # 自動計算: スポット位置からステージ中心下方向へ向く
        spot_x = self.start_x + self.spacing * index
        spot_z = self.start_z
        stage_center_y = self.start_y + 2.0  # ステージ中央付近を照らすYオフセット
        
        # 垂直方向の角度: スポットZから地面(Z=0)へ向く
        vertical_angle = math.atan2(spot_z, 1.5)  # 少し前方への距離感
        
        return (vertical_angle, 0, rot_z)

    def build(self):
        self.objects = []
        for i in range(self.count):
            spot_x = self.start_x + self.spacing * i
            rotation = self._compute_rotation(i)
            spotlight_objs = _create_spotlight(
                location=(spot_x, self.start_y, self.start_z),
                rotation=rotation,
                energy=self.energy,
                color=self.color,
                spot_size=self.spot_size,
                spot_blend=self.spot_blend,
                beam=self.beam,
                beam_length=self.beam_length,
                core_fade_power=self.core_fade_power,
                halo_fade_power=self.halo_fade_power,
                radial_fade=self.radial_fade,
                radial_fade_power=self.radial_fade_power,
            )
            prefix = f"SP{i+1}"
            for obj in spotlight_objs:
                obj.name = f"{prefix}_{obj.name}"
            self.objects.extend(spotlight_objs)
        return self.objects

    def apply_materials(self):
        dark_metal = _get_mat("Spotlight_DarkMetal")
        lens_mat = _get_mat("Spotlight_Lens")
        for obj in bpy.context.scene.objects:
            if obj.type == 'MESH' and obj.name.startswith('SP'):
                if 'lens' in obj.name.lower():
                    if len(obj.data.materials) == 0: obj.data.materials.append(lens_mat)
                    else: obj.data.materials[0] = lens_mat
                else:
                    if len(obj.data.materials) == 0: obj.data.materials.append(dark_metal)
                    else: obj.data.materials[0] = dark_metal


# =============================================================================
# Standalone API functions (for __init__.py imports)
# =============================================================================

def create_spotlight(location, rotation, energy=150, color=(1, 1, 1), spot_size=math.radians(20), spot_blend=0.3):
    """Create a single spotlight at the given location and rotation."""
    return _create_spotlight(location, rotation, energy, color, spot_size, spot_blend)


def create_full_lighting_rig(count=1, spacing=1.0, start_x=0.0, start_y=0, start_z=4.0, rotation_angle_deg=None,
                               energy=150, color=(1, 1, 1), spot_size=math.radians(20), spot_blend=0.3, beam=False,
                               beam_length=6.0, core_fade_power=3.0, halo_fade_power=1.0, rotation_z_deg=0,
                               radial_fade=True, radial_fade_power=1.0):
    """Create spotlights with housing parts joined into one object per spotlight.

    Args:
        count: スポットライトの数
        spacing: X方向の間隔(m)
        start_x: 最初のスポットライトのX座標
        start_y: Y座標（共通）
        start_z: Z座標（共通、天井側）
        rotation_angle_deg: X軸回転角（度）。指定すると各スポットライトがその角度で向く。
                            None（省略）の場合、自動計算でステージ面へ向下する角度になる。
        energy: 光の強さ（デフォルト150）
        color: 光の色 (R, G, B) 各値0-1、デフォルト白色
        spot_size: ビーム広がり角度（ラジアン、デフォルト20°）
        spot_blend: エッジの柔らかさ（0-1、デフォルト0.3）
        beam: Trueの場合、可視光線コーンを生成（デフォルトFalse）
        beam_length: 光線コーンの長さ(m)、デフォルト6.0
        core_fade_power: Inner coreの軸方向減衰指数（>1で急速減衰、デフォルト2.0）
        halo_fade_power: Outer haloの軸方向減衰指数（=1で線形、デフォルト1.0）
        rotation_z_deg: Z軸周りの回転角（度）、デフォルト0。水平方向の向きを変更できる。
        radial_fade: Trueなら半径方向Gauss的減衰を有効化（コアとハローの境目を滑らかにする）
        radial_fade_power: 半径方向減衰のパワー（大きいほど中心に集中、デフォルト2.0）
    """
    system = SpotlightSystem(
        count=count, spacing=spacing, start_x=start_x, start_y=start_y, start_z=start_z,
        rotation_angle_deg=rotation_angle_deg,
        energy=energy, color=color, spot_size=spot_size, spot_blend=spot_blend,
        beam=beam, beam_length=beam_length,
        core_fade_power=core_fade_power, halo_fade_power=halo_fade_power,
        rotation_z_deg=rotation_z_deg,
        radial_fade=radial_fade, radial_fade_power=radial_fade_power,
    )
    return system.build()


def apply_materials_to_spotlights():
    """Apply materials to all spotlight objects in the scene."""
    system = SpotlightSystem()
    system.apply_materials()


def clear_spotlight_objects():
    """Remove all spotlight-related objects from the scene."""
    _clear_spotlight_meshes()