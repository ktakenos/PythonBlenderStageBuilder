# -*- coding: utf-8 -*-
"""stage_platform.py - Stage platform modeling module (from stage_model.py)"""
import bpy
import math
import mathutils

STAGE_W, STAGE_D, STAGE_H = 6.0, 4.0, 1.0
STAIR_STEP_COUNT, STAIR_X_TOTAL, STAIR_Y_PER_STEP = 3, 1.0, 1.0
STEP_THICKNESS, RAILING_HEIGHT = 0.05, 0.9


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


def _clear_stage_meshes():
    to_delete = [o for o in bpy.context.scene.objects if o.type == 'MESH' and any(k in o.name.lower() for k in ['stage', 'stair', 'railing'])]
    if to_delete:
        bpy.ops.object.select_all(action='DESELECT')
        for o in to_delete: o.select_set(True)
        bpy.context.view_layer.objects.active = to_delete[0]
        bpy.ops.object.delete(use_global=False)


def _get_or_create_material(name, color, roughness=0.5, metallic=0.8):
    if name in bpy.data.materials: return bpy.data.materials[name]
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new(type='ShaderNodeOutputMaterial'); out.location = (200, 0)
    bsdf = nodes.new(type='ShaderNodeBsdfPrincipled'); bsdf.location = (0, 0)
    links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    bsdf.inputs['Base Color'].default_value = color
    bsdf.inputs['Roughness'].default_value = roughness
    bsdf.inputs['Metallic'].default_value = metallic
    return mat


def _create_black_tile_material():
    """Create a dark anodized aluminum style material for the stage platform (solid color, no texture)."""
    mat = bpy.data.materials.new(name="BlackTile_Mat")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out_node = nodes.new(type='ShaderNodeOutputMaterial')
    out_node.location = (300, 0)
    bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    bsdf.location = (0, 0)
    # Dark anodized aluminum: solid black-gray color, no texture stripes
    bsdf.inputs['Base Color'].default_value = (0.08, 0.08, 0.09, 1.0)
    bsdf.inputs['Roughness'].default_value = 0.5
    bsdf.inputs['Metallic'].default_value = 0.6
    links.new(bsdf.outputs['BSDF'], out_node.inputs['Surface'])
    return mat


def _create_metal_material():
    """Create dark anodized aluminum material for railings."""
    mat = bpy.data.materials.new(name="Metal_Railing")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new(type='ShaderNodeOutputMaterial'); out.location = (600, 0)
    bsdf = nodes.new(type='ShaderNodeBsdfPrincipled'); bsdf.location = (300, 0)
    # Dark anodized aluminum - same as stage platform
    bsdf.inputs['Base Color'].default_value = (0.08, 0.08, 0.09, 1.0)
    bsdf.inputs['Roughness'].default_value = 0.5; bsdf.inputs['Metallic'].default_value = 0.6
    links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    return mat


class StagePlatform:
    def __init__(self, width=6.0, depth=4.0, height=1.0):
        self.width, self.depth, self.height = width, depth, height
        self.objects = []

    def build(self):
        platform_objs = self._platform()
        left_stair_objs = self._side_stair('left')
        right_stair_objs = self._side_stair('right')
        left_railing_objs = self._railing('left')
        right_railing_objs = self._railing('right')
        
        # Join platform into single object
        plat_joined = _join_objects(platform_objs)
        if plat_joined:
            plat_joined.name = "Stage_Platform"
        
        # Join left stair into single object
        ls_joined = _join_objects(left_stair_objs)
        if ls_joined:
            ls_joined.name = "Stage_LeftStair"
        
        # Join right stair into single object
        rs_joined = _join_objects(right_stair_objs)
        if rs_joined:
            rs_joined.name = "Stage_RightStair"
        
        # Join left railing into single object
        lr_joined = _join_objects(left_railing_objs)
        if lr_joined:
            lr_joined.name = "Stage_LeftRailing"
        
        # Join right railing into single object
        rr_joined = _join_objects(right_railing_objs)
        if rr_joined:
            rr_joined.name = "Stage_RightRailing"
        
        self.objects = []
        if plat_joined: self.objects.append(plat_joined)
        if ls_joined: self.objects.append(ls_joined)
        if rs_joined: self.objects.append(rs_joined)
        if lr_joined: self.objects.append(lr_joined)
        if rr_joined: self.objects.append(rr_joined)
        
        return self.objects

    def _platform(self):
        bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, self.height / 2))
        obj = bpy.context.active_object; obj.name = "StagePlatform"
        obj.scale = (self.width / 2, self.depth / 2, self.height / 2)
        return [obj]

    def _side_stair(self, side):
        step_h = self.height / STAIR_STEP_COUNT
        x_sign = -1 if side == 'left' else 1
        step_x = STAIR_X_TOTAL / STAIR_STEP_COUNT
        objs = []
        for i in range(STAIR_STEP_COUNT):
            z_loc = step_h * i + STEP_THICKNESS / 2
            x_loc = x_sign * self.width / 2 + x_sign * (step_x * (STAIR_STEP_COUNT - i) - step_x / 2)
            bpy.ops.mesh.primitive_cube_add(size=1, location=(x_loc, 0.0, z_loc))
            obj = bpy.context.active_object; obj.name = f"Stair_{side}_Step{i+1}"
            obj.scale = (step_x, STAIR_Y_PER_STEP, STEP_THICKNESS); objs.append(obj)
            for y_sign in [-1, 1]:
                support_z = step_h * i
                if support_z > 0.01:
                    bpy.ops.mesh.primitive_cube_add(size=1, location=(x_loc, y_sign * (STAIR_Y_PER_STEP / 2 - 0.05), support_z + STEP_THICKNESS / 2))
                    beam = bpy.context.active_object; beam.name = f"Stair_{side}_Beam{i+1}_{y_sign}"
                    beam.scale = (step_x * 0.9, 0.05, step_h - STEP_THICKNESS); objs.append(beam)
        return objs

    def _railing(self, side):
        step_h = self.height / STAIR_STEP_COUNT; x_sign = -1 if side == 'left' else 1
        step_x = STAIR_X_TOTAL / STAIR_STEP_COUNT
        stage_edge_x = x_sign * self.width / 2
        pipe_radius = 0.03
        x_bottom = stage_edge_x + x_sign * (STAIR_X_TOTAL - step_x / 2); z_bottom = RAILING_HEIGHT
        x_top = stage_edge_x + x_sign * (step_x / 2)
        z_top = self.height + STEP_THICKNESS + RAILING_HEIGHT
        bar_length = math.sqrt((x_top - x_bottom)**2 + (z_top - z_bottom)**2)
        center_x = (x_bottom + x_top) / 2.0; center_z = (z_bottom + z_top) / 2.0
        objs = []
        for y_sign in [-1, 1]:
            y_pos = y_sign * STAIR_Y_PER_STEP / 2
            bpy.ops.mesh.primitive_cylinder_add(radius=pipe_radius, depth=bar_length, location=(center_x, y_pos, center_z))
            bar = bpy.context.active_object; bar.name = f"Railing_{side}_Slope_{y_sign}"
            default_dir = mathutils.Vector((0, 0, 1)); target_dir = mathutils.Vector((x_top - x_bottom, 0, z_top - z_bottom)).normalized()
            bar.rotation_euler = default_dir.rotation_difference(target_dir).to_euler(); objs.append(bar)
            pole_b_h = z_bottom
            if pole_b_h > pipe_radius * 2:
                bpy.ops.mesh.primitive_cylinder_add(radius=pipe_radius, depth=pole_b_h, location=(x_bottom, y_pos, pole_b_h / 2.0))
                pole = bpy.context.active_object; pole.name = f"Railing_{side}_PoleB_{y_sign}"
                objs.append(pole)
            pole_t_h = z_top
            if pole_t_h > pipe_radius * 2:
                bpy.ops.mesh.primitive_cylinder_add(radius=pipe_radius, depth=pole_t_h, location=(x_top, y_pos, pole_t_h / 2.0))
                pole = bpy.context.active_object; pole.name = f"Railing_{side}_PoleT_{y_sign}"
                objs.append(pole)
            sphere_r = pipe_radius * 2.0
            for sz in [z_bottom, z_top]:
                bpy.ops.mesh.primitive_ico_sphere_add(radius=sphere_r, location=(x_bottom if sz == z_bottom else x_top, y_pos, sz), subdivisions=3)
                sph = bpy.context.active_object; sph.name = f"Railing_{side}_Sphere_{('B' if sz == z_bottom else 'T')}{y_sign}"
                objs.append(sph)
        return objs

    def apply_materials(self):
        """Apply materials only to self.objects (platform, stairs, railings)."""
        tile_mat = _create_black_tile_material()
        metal_mat = _create_metal_material()
        for obj in self.objects:
            if obj is not None and obj.type == 'MESH':
                if 'railing' in obj.name.lower():
                    if len(obj.data.materials) == 0:
                        obj.data.materials.append(metal_mat)
                    else:
                        obj.data.materials[0] = metal_mat
                else:
                    if len(obj.data.materials) == 0:
                        obj.data.materials.append(tile_mat)
                    else:
                        obj.data.materials[0] = tile_mat


# =============================================================================
# Standalone API functions (for __init__.py imports)
# =============================================================================

def create_stage_platform(width=9.0, depth=6.0, height=1.0):
    """Create a stage platform with stairs and railings."""
    platform = StagePlatform(width=width, depth=depth, height=height)
    objs = platform.build()
    platform.apply_materials()
    return objs


def apply_materials_to_stage():
    """Apply materials to all stage objects in the scene."""
    platform = StagePlatform()
    platform.apply_materials()


def clear_stage_objects():
    """Remove all stage-related objects from the scene."""
    _clear_stage_meshes()
