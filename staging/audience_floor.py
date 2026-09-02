# -*- coding: utf-8 -*-
"""audience_floor.py - Audience floor (F-floor) modeling module."""
import bpy


def _clear_floor_meshes():
    """Remove existing audience floor objects."""
    to_delete = [
        o for o in bpy.context.scene.objects
        if o.type == 'MESH' and 'audience_floor' in o.name.lower()
    ]
    if to_delete:
        bpy.ops.object.select_all(action='DESELECT')
        for o in to_delete:
            o.select_set(True)
        bpy.context.view_layer.objects.active = to_delete[0]
        bpy.ops.object.delete(use_global=False)


def _create_audience_floor_material():
    """Create a dark wooden floor material for the audience area."""
    name = "AudienceFloor_Mat"
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

    # Dark wood tone floor
    bsdf.inputs['Base Color'].default_value = (0.12, 0.10, 0.08, 1.0)
    bsdf.inputs['Roughness'].default_value = 0.7
    bsdf.inputs['Metallic'].default_value = 0.0

    links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    return mat


def create_audience_floor(
    width=14.0, depth=8.0, thickness=0.2,
    stage_front_y=-3.0
):
    """
    Create the audience floor in front of the stage.

    Args:
        width: Total width of the audience floor area.
        depth: Depth (Y-axis extent) of the audience floor area.
        thickness: Thickness of the floor slab.
        stage_front_y: Y position of the stage F-face (front edge).
            The audience floor starts just before this and extends forward.

    Returns:
        The created floor object.
    """
    _clear_floor_meshes()

    mat = _create_audience_floor_material()

    # Position: centered on X, extending from stage front towards negative Y
    center_y = stage_front_y - depth / 2
    center_z = thickness / 2

    bpy.ops.mesh.primitive_cube_add(
        size=1,
        location=(0.0, center_y, center_z)
    )
    floor = bpy.context.active_object
    floor.name = "Audience_Floor"
    floor.scale = (width, depth, thickness)

    # Apply material
    if len(floor.data.materials) == 0:
        floor.data.materials.append(mat)
    else:
        floor.data.materials[0] = mat

    return floor


def clear_audience_floor_objects():
    """Remove all audience floor objects from the scene."""
    _clear_floor_meshes()