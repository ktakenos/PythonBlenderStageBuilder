# -*- coding: utf-8 -*-
"""mic_stand_system.py - Microphone stand modeling module

スタンドの種類:
  - straight: 垂直ポールタイプ（ボーカル用など）
  - boom: ブースム腕付きタイプ（ギターアンプピックアップ、ドラム用など）

基本構成:
  Base(円盤) -> Pole(円柱) -> [Boom(円柱)] -> Clip(Y型ホルダー + マイク筒)
"""
import bpy
import bmesh
import math
import mathutils


# =============================================================================
# Material Cache
# =============================================================================

_mat_cache_mic = {}


def _get_mic_mat(name: str):
    if name in _mat_cache_mic:
        return _mat_cache_mic[name]

    mats = {
        "MicStand_Chrome": ((0.75, 0.75, 0.78, 1.0), 0.95, 0.15),
        "MicStand_Black": ((0.08, 0.08, 0.08, 1.0), 0.8, 0.3),
        "Mic_Body": ((0.15, 0.15, 0.16, 1.0), 0.7, 0.4),
        "Mic_Grille": ((0.55, 0.55, 0.58, 1.0), 0.9, 0.2),
    }

    if name not in mats:
        return None

    base_color, metallic, roughness = mats[name]
    mat = _create_mic_principled_material(name, base_color, metallic, roughness)
    _mat_cache_mic[name] = mat
    return mat


def _create_mic_principled_material(name, base_color, metallic, roughness):
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


def _assign_material(obj, material):
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


# =============================================================================
# Primitive builders
# =============================================================================

def _create_base(location, radius=0.15, thickness=0.01):
    """円盤型ベース"""
    bpy.ops.mesh.primitive_cylinder_add(
        radius=radius, depth=thickness,
        location=location
    )
    return bpy.context.active_object


def _create_pole(base_location, height, diameter=0.02, tilt_x_deg=0):
    """垂直ポール（base_locationが中心、Z方向に伸びる）"""
    pole_center = (base_location[0], base_location[1], base_location[2] + height / 2)
    bpy.ops.mesh.primitive_cylinder_add(
        radius=diameter / 2, depth=height,
        location=pole_center
    )
    pole = bpy.context.active_object
    if tilt_x_deg != 0:
        pole.rotation_euler.x = math.radians(tilt_x_deg)
    return pole


def _boom_direction_world(angle_deg):
    """X回転(90-a)後のローカルZ軸のワールド方向を返す。

    X回転θ=(90-a°) applied to (0,0,1):
      y' =  cos(θ) = sin(a)
      z' = -sin(θ) = -cos(a)
    → (0, sin(a), -cos(a))   ← Y+, Z-方向（右下がり）

    ブースムが「Y負(手前)へ下げる」にはこの逆ベクトルを使う:
      dir = (0, -sin(a), cos(a))
    """
    a = math.radians(angle_deg)
    return mathutils.Vector((0.0, -math.sin(a), math.cos(a)))


def _create_boom(base_location, length=0.4, angle_deg=30, diameter=0.02):
    """ブースム腕（ポール上部からY負方向に水平、Z正方向に上向きに傾く）

    Blenderの圆柱は中心を基点に depth ぶん両側へ伸びる。
    base_location を基部一端にくるので depth/2 だけローカルZ+方向へシフトする。
    """
    angle_rad = math.radians(angle_deg)
    theta = math.radians(90) - angle_rad  # X rotation

    bpy.ops.mesh.primitive_cylinder_add(
        radius=diameter / 2, depth=length,
        location=base_location
    )
    boom = bpy.context.active_object
    boom.rotation_euler.x = theta

    # ローカルZ軸をワールド変換して基部一端にオフセット
    rot_mat = mathutils.Euler((theta, 0.0, 0.0), 'XYZ').to_matrix()
    local_z = mathutils.Vector((0, 0, 1))
    world_dir = rot_mat @ local_z          # (0, sin(a), -cos(a))
    boom.location += world_dir * (length / 2)

    return boom


def _calculate_boom_tip_from_object(boom_obj, base_location):
    """ブースムメッシュのバウンディングボックスから実際の先端位置を取得。

    base_location (基部/pole_top) から最も遠いbbox頂点を先端として返す。
    これにより _create_boom と完全同期（回転行列の不一致を回避）。
    """
    base_vec = mathutils.Vector(base_location)

    # ワールド座標のbbox頂点リストを取得
    bbox_corners = [boom_obj.matrix_world @ mathutils.Vector(corner)
                    for corner in boom_obj.bound_box]

    # 基部から最も遠い頂点を先端とする
    tip = max(bbox_corners, key=lambda p: (p - base_vec).length)
    return tuple(tip)


def _create_vocal_clip(location, rotation):
    """Uボウル型クリップ + マイク胴体"""
    mesh_objs = []
    loc = mathutils.Vector(location)
    rot = mathutils.Euler(rotation)
    rot_mat = rot.to_matrix().to_4x4()

    # Uボウル: 2本の短いアーム
    arm_length = 0.04
    for side in [-1, 1]:
        offset = mathutils.Vector((side * 0.015, -0.02, 0))
        arm_loc = loc + offset
        bpy.ops.mesh.primitive_cylinder_add(
            radius=0.003, depth=arm_length,
            location=arm_loc
        )
        arm = bpy.context.active_object
        arm.rotation_euler = (rot[0] + math.radians(90), rot[1], rot[2])
        mesh_objs.append(arm)

    # マイク筒
    mic_length = 0.12
    mic_radius = 0.015
    bpy.ops.mesh.primitive_cylinder_add(
        radius=mic_radius, depth=mic_length,
        location=loc
    )
    mic_body = bpy.context.active_object
    mic_body.rotation_euler = rot
    mesh_objs.append(mic_body)

    # マイクヘッド（グリル部分、球形）
    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=0.025, segments=16, ring_count=8,
        location=loc + mathutils.Vector((0, 0, mic_length / 2))
    )
    mic_head = bpy.context.active_object
    mesh_objs.append(mic_head)

    return mesh_objs


def _create_guitar_clip(location, rotation):
    """カラビナフック型クリップ + マイク胴体（アンプ前面へ向ける）"""
    mesh_objs = []
    loc = mathutils.Vector(location)
    rot = mathutils.Euler(rotation)

    # フック環（小さいトーラス）
    bpy.ops.mesh.primitive_torus_add(
        major_radius=0.02, minor_radius=0.004,
        major_segments=16, minor_segments=8,
        location=loc
    )
    hook = bpy.context.active_object
    hook.rotation_euler = rot
    mesh_objs.append(hook)

    # マイク筒（より短め）
    mic_length = 0.10
    mic_radius = 0.015
    mic_loc = (loc[0], loc[1], loc[2] - mic_length / 2 - 0.01)
    bpy.ops.mesh.primitive_cylinder_add(
        radius=mic_radius, depth=mic_length,
        location=mic_loc
    )
    mic_body = bpy.context.active_object
    mic_body.rotation_euler = rot
    mesh_objs.append(mic_body)

    # マイクヘッド
    head_loc = (loc[0], loc[1], loc[2] - mic_length - 0.01)
    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=0.02, segments=16, ring_count=8,
        location=head_loc
    )
    mic_head = bpy.context.active_object
    mesh_objs.append(mic_head)

    return mesh_objs


def _create_drum_clip(location, rotation):
    """ドラムマイク用クリップ（短いアーム + クランプ型）"""
    mesh_objs = []
    loc = mathutils.Vector(location)
    rot = mathutils.Euler(rotation)

    # クランプ環
    bpy.ops.mesh.primitive_torus_add(
        major_radius=0.025, minor_radius=0.005,
        major_segments=16, minor_segments=8,
        location=loc
    )
    clamp = bpy.context.active_object
    clamp.rotation_euler = rot
    mesh_objs.append(clamp)

    # アーム（短い）
    arm_len = 0.06
    arm_loc = (loc[0], loc[1], loc[2] + arm_len / 2)
    bpy.ops.mesh.primitive_cylinder_add(
        radius=0.004, depth=arm_len,
        location=arm_loc
    )
    arm = bpy.context.active_object
    arm.rotation_euler = rot
    mesh_objs.append(arm)

    # マイク筒（小型コンデンスマイク風）
    mic_length = 0.08
    mic_radius = 0.012
    mic_loc = (loc[0], loc[1], loc[2] + arm_len + mic_length / 2)
    bpy.ops.mesh.primitive_cylinder_add(
        radius=mic_radius, depth=mic_length,
        location=mic_loc
    )
    mic_body = bpy.context.active_object
    mic_body.rotation_euler = rot
    mesh_objs.append(mic_body)

    # ヘッド
    head_loc = (loc[0], loc[1], loc[2] + arm_len + mic_length + 0.015)
    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=0.015, segments=12, ring_count=6,
        location=head_loc
    )
    mic_head = bpy.context.active_object
    mesh_objs.append(mic_head)

    return mesh_objs


# =============================================================================
# Main API
# =============================================================================

def create_mic_stand(
    location,
    stand_type="straight",
    height=1.5,
    base_radius=0.15,
    pole_diameter=0.02,
    boom_length=0.4,
    boom_angle_deg=30,
    tilt_x_deg=0,
    rotation_z_deg=0,
    clip_type="vocal",
    material="chrome",
):
    """Create a single microphone stand.

    Args:
        location:     (x, y, z) 設置位置（ベース中心）
        stand_type:   "straight"（垂直ポール）または "boom"（ブースム腕付き）
        height:       ポールの高さ(m)、デフォルト1.5
        base_radius:  ベースの半径(m)、デフォルト0.15
        pole_diameter: ポールの太さ(m)、デフォルト0.02
        boom_length:  ブースム腕の長さ(m)、デフォルト0.4（boomタイプのみ有効）
        boom_angle_deg: ブースムの角度（水平から上向き）、デフォルト30度
        tilt_x_deg:   ポール全体のX軸傾斜角（度）、デフォルト0
        rotation_z_deg: Z軸周りの回転角（度）、デフォルト0。
            水平方向の向きを変更できる（時計回り）。
        clip_type:    "vocal", "guitar_pickup", "drum_snare", "drum_tom"
        material:     "chrome"または"black"

    Returns:
        Created objects list (base, pole, [boom], clip parts)
    """
    loc = mathutils.Vector(location)

    # Material selection
    if material == "black":
        stand_mat = _get_mic_mat("MicStand_Black")
    else:
        stand_mat = _get_mic_mat("MicStand_Chrome")

    mic_body_mat = _get_mic_mat("Mic_Body")
    mic_grille_mat = _get_mic_mat("Mic_Grille")

    mesh_objs = []

    # 1. Base
    base = _create_base(loc, radius=base_radius)
    base.name = "MicStand_Base"
    _assign_material(base, stand_mat)
    mesh_objs.append(base)

    # 2. Pole
    pole = _create_pole(loc, height, diameter=pole_diameter, tilt_x_deg=tilt_x_deg)
    pole.name = "MicStand_Pole"
    _assign_material(pole, stand_mat)
    mesh_objs.append(pole)

    # Calculate the top of the pole for boom/clip attachment
    # Pole center is at loc + (0, 0, height/2), so top edge is at loc + (0, 0, height)
    pole_top = (loc[0], loc[1], loc[2] + height)

    # Clip rotation: point slightly downward toward the target
    clip_rotation = (math.radians(-15), 0, 0)

    if stand_type == "boom":
        # 3. Boom arm
        boom = _create_boom(
            pole_top,
            length=boom_length,
            angle_deg=boom_angle_deg,
            diameter=pole_diameter
        )
        boom.name = "MicStand_Boom"
        _assign_material(boom, stand_mat)
        mesh_objs.append(boom)

        # Get the actual boom tip from the created boom object's bounding box
        # This ensures perfect synchronization with the visual geometry
        bpy.context.view_layer.update()
        clip_loc = _calculate_boom_tip_from_object(boom, pole_top)
    else:
        # Straight stand: clip at the top of the pole
        clip_loc = pole_top
        clip_rotation = (math.radians(-10), 0, 0)

    # 4. Clip (microphone holder)
    if clip_type == "guitar_pickup":
        clip_objs = _create_guitar_clip(clip_loc, clip_rotation)
    elif clip_type in ("drum_snare", "drum_tom"):
        clip_objs = _create_drum_clip(clip_loc, clip_rotation)
    else:
        # Default: vocal clip
        clip_objs = _create_vocal_clip(clip_loc, clip_rotation)

    for obj in clip_objs:
        _assign_material(obj, mic_body_mat)
    # Make the last object (sphere/grille) use grille material
    if clip_objs:
        _assign_material(clip_objs[-1], mic_grille_mat)

    mesh_objs.extend(clip_objs)

    # Apply Z-axis rotation around the base location (pole bottom center).
    # Use direct matrix multiplication to avoid parent-unparent issues.
    if rotation_z_deg != 0:
        rot_z = math.radians(rotation_z_deg)
        loc_vec = mathutils.Vector(loc)

        # Build rotation matrix around Z axis, centered at base location
        T_in = mathutils.Matrix.Translation(-loc_vec)
        T_out = mathutils.Matrix.Translation(loc_vec)
        Rz = mathutils.Euler((0, 0, rot_z)).to_matrix().to_4x4()
        M = T_out @ Rz @ T_in

        for obj in mesh_objs:
            obj.matrix_world = M @ obj.matrix_world

    # Join all parts into a single mesh object
    if len(mesh_objs) > 1:
        # Set the first object as active and select all
        bpy.context.view_layer.objects.active = mesh_objs[0]
        for obj in mesh_objs:
            obj.select_set(True)
        # Join all selected objects into the active object
        bpy.ops.object.join()
        # The result is the active object (mesh_objs[0])
        return [mesh_objs[0]]
    else:
        return mesh_objs


def create_mic_stands(count, location_func, **kwargs):
    """Create multiple microphone stands.

    Args:
        count:         設置数
        location_func: イndex (0..count-1) を受け取って (x,y,z) を返す callable
                       または単一のタプル（その位置にcount本設置）
        **kwargs:      create_mic_stand() のキーワード引数

    Returns:
        List of all created objects
    """
    all_objs = []
    for i in range(count):
        if callable(location_func):
            loc = location_func(i)
        else:
            loc = location_func
        objs = create_mic_stand(location=loc, **kwargs)
        prefix = f"MS{i+1}"
        for obj in objs:
            obj.name = f"{prefix}_{obj.name}"
        all_objs.extend(objs)
    return all_objs


def clear_mic_stand_objects():
    """Remove all mic-stand related objects from the scene."""
    to_delete = [
        o for o in bpy.context.scene.objects
        if o.type == 'MESH' and 'MicStand' in o.name
    ]
    if not to_delete:
        # Fallback: name prefix MS
        to_delete = [
            o for o in bpy.context.scene.objects
            if o.type == 'MESH' and o.name.startswith('MS')
        ]
    if to_delete:
        bpy.ops.object.select_all(action='DESELECT')
        for o in to_delete:
            o.select_set(True)
        bpy.context.view_layer.objects.active = to_delete[0]
        bpy.ops.object.delete(use_global=False)


# =============================================================================
# Convenience presets
# =============================================================================

def create_vocal_mic(location, height=1.5, rotation_z_deg=0):
    """ボーカル用マイクスタンド（ストレートポール + ボーカルクリップ）

    Args:
        location:     設置位置
        height:       ポール高さ(m)
        rotation_z_deg: Z軸周りの回転角（度）、デフォルト0
    """
    return create_mic_stand(
        location=location,
        stand_type="straight",
        height=height,
        rotation_z_deg=rotation_z_deg,
        clip_type="vocal",
        material="chrome",
    )


def create_guitar_pickup_mic(location, boom_length=0.35, boom_angle_deg=20, rotation_z_deg=0):
    """ギターアンプピックアップ用マイクスタンド（ブースム + カラビナフック）

    Args:
        location:     設置位置
        boom_length:  ブースム腕の長さ(m)
        boom_angle_deg: ブースム角度（度）
        rotation_z_deg: Z軸周りの回転角（度）、デフォルト0
    """
    return create_mic_stand(
        location=location,
        stand_type="boom",
        height=1.0,
        base_radius=0.12,
        boom_length=boom_length,
        boom_angle_deg=boom_angle_deg,
        rotation_z_deg=rotation_z_deg,
        clip_type="guitar_pickup",
        material="chrome",
    )


def create_drum_mic(location, drum_type="snare", boom_length=0.3, boom_angle_deg=45, rotation_z_deg=0):
    """ドラム用マイクスタンド（ブースム + ドラムクリップ）

    Args:
        location:     設置位置
        drum_type:    "snare"または"tom"
        boom_length:  ブースム腕の長さ(m)
        boom_angle_deg: ブースム角度（度）
        rotation_z_deg: Z軸周りの回転角（度）、デフォルト0
    """
    clip = "drum_snare" if drum_type == "snare" else "drum_tom"
    return create_mic_stand(
        location=location,
        stand_type="boom",
        height=0.6,
        base_radius=0.12,
        boom_length=boom_length,
        boom_angle_deg=boom_angle_deg,
        rotation_z_deg=rotation_z_deg,
        clip_type=clip,
        material="chrome",
    )
