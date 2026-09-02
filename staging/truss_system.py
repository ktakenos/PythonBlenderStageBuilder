# -*- coding: utf-8 -*-
"""
truss_system.py - トラスケージモデリングモジュール
================================================
元の truss_modeling_new_v2.py からクラスを抽出・再定義したモジュール。

Blender座標系: X=左右, Y=奥行き, Z=上
"""

import bpy
import math


# =============================================================================
# ユーティリティ関数
# =============================================================================

def _clear_scene():
    """シーン内のメッシュオブジェクトのみを削除"""
    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH':
            bpy.data.objects.remove(obj, do_unlink=True)


def _get_or_create_material(name: str, color: tuple, roughness: float = 0.5, metallic: float = 0.8):
    """既存のマテリアルを取得するか、新規作成して返す"""
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    nodes.clear()

    output_node = nodes.new(type='ShaderNodeOutputMaterial')
    output_node.location = (200, 0)

    principled_node = nodes.new(type='ShaderNodeBsdfPrincipled')
    principled_node.location = (0, 0)

    links.new(principled_node.outputs['BSDF'], output_node.inputs['Surface'])
    principled_node.inputs['Base Color'].default_value = color
    principled_node.inputs['Roughness'].default_value = roughness
    principled_node.inputs['Metallic'].default_value = metallic

    return mat


def _create_pipe(radius: float, depth: float, location: tuple, rotation_x: float,
                 material_name: str = None, color: tuple = None, roughness: float = None, metallic: float = None):
    """パイプ（円柱）を作成し、オブジェクトを返す。
    マテリアルパラメータがNoneの場合はマテリアルを割り当てない（後で一括適用するため）。"""
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=depth, location=location)

    obj = bpy.context.active_object
    obj.name = f"Pipe_r{radius:.2f}_d{depth:.2f}"

    obj.rotation_euler[0] = rotation_x

    if material_name is not None and color is not None:
        mat = _get_or_create_material(material_name, color, roughness=roughness or 0.5, metallic=metallic or 0.8)
        if not obj.data.materials:
            obj.data.materials.append(mat)

    return obj


def _create_bar(length: float, width: float, depth: float, location: tuple,
               rotation: tuple = (0.0, 0.0, 0.0),
               material_name: str = None, color: tuple = None,
               roughness: float = None, metallic: float = None):
    """直方体の棒を作成し、オブジェクトを返す。
    マテリアルパラメータがNoneの場合はマテリアルを割り当てない（後で一括適用するため）。"""
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0))

    obj = bpy.context.active_object
    obj.name = f"Bar_l{length:.2f}_w{width:.2f}_d{depth:.2f}"

    obj.scale[0] = length
    obj.scale[1] = width
    obj.scale[2] = depth

    obj.location = location

    obj.rotation_euler[0] = rotation[0]
    obj.rotation_euler[1] = rotation[1]
    obj.rotation_euler[2] = rotation[2]

    if material_name is not None and color is not None:
        mat = _get_or_create_material(material_name, color, roughness=roughness or 0.5, metallic=metallic or 0.8)
        if not obj.data.materials:
            obj.data.materials.append(mat)

    return obj


def _join_objects(obj_list: list):
    """オブジェクトリストを1つのメッシュに結合して返す"""
    if not obj_list:
        return None

    if len(obj_list) == 1:
        bpy.ops.object.select_all(action='DESELECT')
        obj_list[0].select_set(True)
        bpy.context.view_layer.objects.active = obj_list[0]
        return obj_list[0]

    bpy.ops.object.select_all(action='DESELECT')
    for obj in obj_list:
        obj.select_set(True)

    bpy.context.view_layer.objects.active = obj_list[0]
    bpy.ops.object.join()

    return bpy.context.active_object


# =============================================================================
# TrussFrame: 単一トラスフレーム
# =============================================================================

class TrussFrame:
    """単一トラスフレームのパイプ群を作成・結合する"""

    def __init__(self, length: float = 1.5, thickness: float = 0.1,
                 rotation_angle_deg: float = 30.0,
                 center_x: float = 0.0, center_y: float = 0.0, center_z: float = 1.0,
                 color: tuple = None, material: str = None,
                 roughness: float = None, metallic: float = None):
        self.length = length
        self.thickness = thickness
        self.rotation_angle_deg = rotation_angle_deg
        self.center_x = center_x
        self.center_y = center_y
        self.center_z = center_z
        # マテリアルは最終的にTrussSystem.apply_materials()で一括適用するためNone
        self.color = color
        self.material = material
        self.roughness = roughness
        self.metallic = metallic

    def create_frame(self):
        pipes = []

        pipe1 = _create_pipe(
            radius=self.thickness * 0.5,
            depth=1.0,
            location=(self.center_x, self.center_y, self.center_z),
            rotation_x=math.radians(0.0),
        )
        pipes.append(pipe1)

        pipe2 = _create_pipe(
            radius=0.015,
            depth=0.5,
            location=(self.center_x, self.center_y + 0.25, self.center_z - 0.45),
            rotation_x=math.radians(-90.0),
        )
        pipes.append(pipe2)

        pipe3 = _create_pipe(
            radius=0.025,
            depth=0.875,
            location=(self.center_x, self.center_y + 0.25, self.center_z),
            rotation_x=math.radians(-30.0),
        )
        pipes.append(pipe3)

        unit_obj = _join_objects(pipes)
        if unit_obj is None:
            return None

        positions = [(0.5, 0, 0), (0, 0.5, 0), (-0.5, 0, 0)]
        frame_parts = [unit_obj]

        bpy.ops.object.select_all(action='DESELECT')
        unit_obj.select_set(True)
        bpy.context.view_layer.objects.active = unit_obj

        for pos in positions:
            bpy.ops.object.duplicate_move(
                OBJECT_OT_duplicate={"linked": False, "mode": 'TRANSLATION'},
                TRANSFORM_OT_translate={"value": pos}
            )
            new_obj = bpy.context.active_object
            new_obj.rotation_euler[2] += math.radians(90)
            frame_parts.append(new_obj)

        final_obj = _join_objects(frame_parts)

        if final_obj is not None:
            final_obj.name = "TrussFrame"

        return final_obj


# =============================================================================
# JointCube: 立方体ジョイント形状
# =============================================================================

class JointCube:
    """トラスの幅を1辺とした立方体のジョイント形状。
    マテリアルは最終的にTrussSystem.apply_materials()で一括適用するため、作成時は割り当てない。"""

    def __init__(self, size: float = 1.5, bar_width: float = None):
        self.size = size
        if bar_width is None:
            self.bar_width = 0.05 * 2.2
        else:
            self.bar_width = bar_width

    def create_joint(self, location: tuple = (0.0, 0.0, 0.0)) -> bpy.types.Object:
        bars = []
        half = self.size / 2.0
        bar_len = self.size
        bar_w = self.bar_width

        # X軸方向の4本
        for y_off in [half, -half]:
            for z_off in [half, -half]:
                bar = _create_bar(
                    length=bar_len, width=bar_w, depth=bar_w,
                    location=(location[0], location[1] + y_off, location[2] + z_off),
                )
                bars.append(bar)

        # Y軸方向の4本
        for x_off in [half, -half]:
            for z_off in [half, -half]:
                bar = _create_bar(
                    length=bar_w, width=bar_len, depth=bar_w,
                    location=(location[0] + x_off, location[1], location[2] + z_off),
                )
                bars.append(bar)

        # Z軸方向の4本
        for x_off in [half, -half]:
            for y_off in [half, -half]:
                bar = _create_bar(
                    length=bar_w, width=bar_w, depth=bar_len,
                    location=(location[0] + x_off, location[1] + y_off, location[2]),
                )
                bars.append(bar)

        final_obj = _join_objects(bars)

        if final_obj is not None:
            final_obj.name = f"JointCube_s{self.size:.2f}"

        return final_obj


# =============================================================================
# Beam: Z軸方向に複数層を積んだビーム（柱）
# =============================================================================

class Beam:
    """Z軸方向に複数層を積んだビーム（柱）"""

    def __init__(self, num_layers: int = 3, z_spacing: float = 1.0,
                 position: tuple = (0, 0, 0), rotation_deg: float = 0.0,
                 frame_kwargs: dict = None):
        self.num_layers = num_layers
        self.z_spacing = z_spacing
        self.position = position
        self.rotation_deg = rotation_deg
        self.frame_kwargs = frame_kwargs or {}

    def create_beam(self) -> bpy.types.Object:
        frame = TrussFrame(**self.frame_kwargs)
        base_obj = frame.create_frame()

        if base_obj is None:
            return None

        beam_objs = [base_obj]

        if self.num_layers > 1:
            bpy.ops.object.select_all(action='DESELECT')
            base_obj.select_set(True)
            bpy.context.view_layer.objects.active = base_obj

            for _ in range(self.num_layers - 1):
                bpy.ops.object.duplicate_move(
                    OBJECT_OT_duplicate={"linked": False, "mode": 'TRANSLATION'},
                    TRANSFORM_OT_translate={"value": (0, 0, self.z_spacing)}
                )
                beam_objs.append(bpy.context.active_object)

        final_obj = _join_objects(beam_objs)

        if final_obj is not None:
            final_obj.location = self.position
            final_obj.rotation_euler[2] = math.radians(self.rotation_deg)

        return final_obj


# =============================================================================
# TrussSystem: 柱配置 + 水平梁配置を統括するクラス
# =============================================================================

class TrussSystem:
    """柱と水平梁の全体的な配置を管理"""

    def __init__(self):
        self.columns = []
        self.beams_h = []
        self.joints = []

    def reset_scene(self):
        _clear_scene()
        self.columns = []
        self.beams_h = []
        self.joints = []

    def create_horizontal_beams(self, positions: list,
                                  start_z: float = 2.5,
                                  frames_per_edge: list = None,
                                  frame_kwargs: dict = None):
        kwargs = frame_kwargs or {}

        if frames_per_edge is None:
            frames_per_edge = [3, 3, 3, 3]

        edges = [(0, 1), (1, 2), (2, 3), (3, 0)]
        edge_offsets = [(0, 0), (0.5, 0), (0.5, 0.5), (0, 0.5)]

        for edge_idx, (from_idx, to_idx) in enumerate(edges):
            edge_offset_x, edge_offset_y = edge_offsets[edge_idx]
            from_pos = positions[from_idx]
            to_pos = positions[to_idx]
            dx = to_pos[0] - from_pos[0]
            dy = to_pos[1] - from_pos[1]

            edge_length = math.sqrt(dx**2 + dy**2)
            if edge_length == 0:
                continue

            angle_rad = math.atan2(dy, dx)
            num_frames = frames_per_edge[edge_idx]
            half_frame_width = 0.5

            total_span = edge_length - (half_frame_width * 2)

            if num_frames > 1:
                step = total_span / (num_frames - 1)
            else:
                step = 0

            frame = TrussFrame(**kwargs)
            first_frame_obj = frame.create_frame()

            if first_frame_obj is None:
                continue

            edge_objs = [first_frame_obj]

            t_first = half_frame_width / edge_length
            first_x = from_pos[0] + dx * t_first + edge_offset_x
            first_y = from_pos[1] + dy * t_first + edge_offset_y
            first_frame_obj.location = (first_x, first_y, start_z)
            first_frame_obj.rotation_euler[0] = math.radians(90)
            first_frame_obj.rotation_euler[2] = angle_rad + math.radians(90)

            for i in range(1, num_frames):
                bpy.ops.object.select_all(action='DESELECT')
                prev_obj = edge_objs[-1]
                prev_obj.select_set(True)
                bpy.context.view_layer.objects.active = prev_obj

                t_current = (half_frame_width + step * i) / edge_length
                current_x = from_pos[0] + dx * t_current + edge_offset_x
                current_y = from_pos[1] + dy * t_current + edge_offset_y

                move_x = current_x - prev_obj.location[0]
                move_y = current_y - prev_obj.location[1]
                move_z = start_z - prev_obj.location[2]

                bpy.ops.object.duplicate_move(
                    OBJECT_OT_duplicate={"linked": False, "mode": 'TRANSLATION'},
                    TRANSFORM_OT_translate={"value": (move_x, move_y, move_z)}
                )

                new_obj = bpy.context.active_object
                new_obj.rotation_euler[0] = math.radians(90)
                new_obj.rotation_euler[2] = angle_rad + math.radians(90)
                edge_objs.append(new_obj)

            joined = _join_objects(edge_objs)
            if joined is not None:
                joined.name = f"HBeam_Edge{edge_idx}"
                self.beams_h.append(joined)

    def create_corner_joints(self, positions: list, top_z: float, size: float = 0.5):
        offset_x = 0.25
        offset_y = 0.25
        offset_z_bottom = -0.25
        offset_z_top = 0.25

        for pos in positions:
            joint = JointCube(size=size)
            joint_obj = joint.create_joint(location=(pos[0] + offset_x, pos[1] + offset_y, pos[2] + offset_z_bottom))
            if joint_obj is not None:
                self.joints.append(joint_obj)

        for pos in positions:
            joint = JointCube(size=size)
            joint_obj = joint.create_joint(location=(pos[0] + offset_x, pos[1] + offset_y, top_z + offset_z_top))
            if joint_obj is not None:
                self.joints.append(joint_obj)

    def build_cage(self, width: float, depth: float, height: float,
                   num_layers: int = None, frame_interval: float = 1.0,
                   location: tuple = (0.0, 0.0, 0.0)):
        """トラスケージを構築。locationは基点(x,y,z)を指定可能。"""
        if num_layers is None:
            num_layers = max(1, int(round(height / frame_interval)))

        loc_x, loc_y, loc_z = location

        corner_positions = [
            (loc_x, loc_y, loc_z),
            (loc_x + width, loc_y, loc_z),
            (loc_x + width, loc_y + depth, loc_z),
            (loc_x, loc_y + depth, loc_z),
        ]

        for pos in corner_positions:
            beam = Beam(
                num_layers=num_layers,
                z_spacing=frame_interval,
                position=pos,
            )
            col_obj = beam.create_beam()
            if col_obj is not None:
                self.columns.append(col_obj)

        top_z = (num_layers - 1) * frame_interval + 0.5

        frames_x = max(1, int(round(width / frame_interval)))
        frames_y = max(1, int(round(depth / frame_interval)))

        frames_per_edge = [frames_x, frames_y, frames_x, frames_y]

        self.create_horizontal_beams(
            corner_positions,
            start_z=top_z,
            frames_per_edge=frames_per_edge,
        )

        self.create_corner_joints(corner_positions, top_z=top_z, size=0.5)

    def apply_materials(self):
        """Apply dark metal material to all truss objects."""
        mat_name = "Truss_Anodized"
        base_color = (0.08, 0.08, 0.09, 1.0)
        mat = _get_or_create_material(mat_name, base_color, roughness=0.5, metallic=0.6)
        
        for obj_list in [self.columns, self.beams_h, self.joints]:
            for obj in obj_list:
                if obj is not None and obj.type == 'MESH':
                    if len(obj.data.materials) == 0:
                        obj.data.materials.append(mat)
                    else:
                        obj.data.materials[0] = mat


# =============================================================================
# Standalone API functions (for __init__.py imports)
# =============================================================================

def create_truss_frame(width: float, depth: float, height: float, num_layers: int = None, frame_interval: float = 1.0):
    """Create a single truss frame."""
    system = TrussSystem()
    system.build_cage(width, depth, height, num_layers=num_layers, frame_interval=frame_interval)
    return system


def create_full_stage_truss(width: float = 10.0, depth: float = 6.0, height: float = 5.0,
                            frame_interval: float = 1.0, location: tuple = (-5.25, -3.5, 0.5)):
    """Create a full stage truss system. location=(x,y,z) specifies the base corner.
    All truss parts are joined into a single object."""
    system = TrussSystem()
    num_layers = max(1, int(round(height / frame_interval)))
    system.build_cage(width, depth, height, num_layers=num_layers, frame_interval=frame_interval, location=location)
    system.apply_materials()
    
    # Join all truss objects into a single object
    all_objs = system.columns + system.beams_h + system.joints
    if all_objs:
        joined = _join_objects(all_objs)
        if joined is not None:
            joined.name = "Truss_System"
    
    return system


def apply_materials_to_truss():
    """Apply materials to all truss objects in the scene."""
    mat_name = "Truss_Anodized"
    base_color = (0.08, 0.08, 0.09, 1.0)
    mat = _get_or_create_material(mat_name, base_color, roughness=0.5, metallic=0.6)
    
    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH' and ('Beam' in obj.name or 'Column' in obj.name or 'Joint' in obj.name):
            if len(obj.data.materials) == 0:
                obj.data.materials.append(mat)
            else:
                obj.data.materials[0] = mat


def clear_truss_objects():
    """Remove all truss-related objects from the scene."""
    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH' and ('Beam' in obj.name or 'Column' in obj.name or 'Joint' in obj.name):
            bpy.data.objects.remove(obj, do_unlink=True)
    
    if "Truss_Anodized" in bpy.data.materials:
        bpy.data.materials.remove(bpy.data.materials["Truss_Anodized"])
