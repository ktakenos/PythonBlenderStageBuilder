# -*- coding: utf-8 -*-
"""back_wall.py - Wall (cyclorama) modeling module for stage."""
import bpy
import math
import mathutils


def _clear_wall_meshes():
    """Remove existing wall objects."""
    to_delete = [
        o for o in bpy.context.scene.objects
        if o.type == 'MESH' and (o.name.startswith('Wall_') or o.name.startswith('Ceiling_'))
    ]
    if to_delete:
        bpy.ops.object.select_all(action='DESELECT')
        for o in to_delete:
            o.select_set(True)
        bpy.context.view_layer.objects.active = to_delete[0]
        bpy.ops.object.delete(use_global=False)


def _create_cyclorama_material():
    """Create a dark cyclorama material (near-black matte fabric)."""
    name = "Cyclorama_Mat"
    if name in bpy.data.materials:
        return bpy.data.materials[name]

    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()

    out = nodes.new(type='ShaderNodeOutputMaterial')
    out.location = (300, 0)
    bsdf = nodes.new(type='ShaderNodeBsdfPrincipled')
    bsdf.location = (0, 0)

    # Very dark gray, almost black, non-reflective fabric
    bsdf.inputs['Base Color'].default_value = (0.05, 0.05, 0.06, 1.0)
    bsdf.inputs['Roughness'].default_value = 0.95
    bsdf.inputs['Metallic'].default_value = 0.0

    links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    return mat


def create_wall(name, width=9.0, height=5.0, location=(0.0, 3.0, 0.0), rotation=(0, 0, 0)):
    """
    Create a wall panel (back wall or side wall).

    Args:
        name: Object name (e.g. "Wall_Back", "Wall_Side_L", "Wall_Side_R").
        width: Width of the wall in meters.
        height: Height of the wall in meters.
        location: Base position (center bottom edge of the wall).
        rotation: Euler rotation (x, y, z) in radians.
    """
    mat = _create_cyclorama_material()

    # Wall panel: width x height x thin depth
    thickness = 0.1
    bpy.ops.mesh.primitive_cube_add(
        size=1,
        location=(location[0], location[1], location[2] + height / 2)
    )
    wall = bpy.context.active_object
    wall.name = name
    wall.scale = (width, thickness, height)
    wall.rotation_euler = mathutils.Euler(rotation)

    # Apply material
    if len(wall.data.materials) == 0:
        wall.data.materials.append(mat)
    else:
        wall.data.materials[0] = mat

    return wall


def create_back_wall(width=9.0, height=5.0, location=(0.0, 3.0, 0.0)):
    """
    Create a back wall (cyclorama) at the rear of the stage.

    Args:
        width: Width of the wall in meters (default 9m, matching stage width).
        height: Height of the wall in meters (default 5m).
        location: Base position (center bottom edge of the wall).
    """
    _clear_wall_meshes()
    return create_wall("Wall_Back", width=width, height=height, location=location)


def create_ceiling(width=9.0, depth=7.0, location=(0.0, 3.0, 5.0), thickness=0.1):
    """
    Create a ceiling panel above the stage.

    Args:
        width:   X方向のサイズ（デフォルト9m）.
        depth:   Y方向のサイズ（デフォルト7m）.
        location: 天井パネルの中心位置 (x, y, z). デフォルト(0.0, 3.0, 5.0).
        thickness: 厚み（Z方向、デフォルト0.1m）.
    """
    mat = _create_cyclorama_material()

    bpy.ops.mesh.primitive_cube_add(
        size=1,
        location=location
    )
    ceiling = bpy.context.active_object
    ceiling.name = "Ceiling_Top"
    ceiling.scale = (width, depth, thickness)

    if len(ceiling.data.materials) == 0:
        ceiling.data.materials.append(mat)
    else:
        ceiling.data.materials[0] = mat

    return ceiling


def clear_back_wall_objects():
    """Remove all wall and ceiling objects from the scene."""
    _clear_wall_meshes()
