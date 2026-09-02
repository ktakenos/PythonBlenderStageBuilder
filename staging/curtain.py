# -*- coding: utf-8 -*-
"""curtain.py - Stage curtain modeling module.

Supports both individual curtain creation and bulk side-curtain setup.
"""
import bpy
import math


# ---------------------------------------------------------------------------
#  Internal helpers
# ---------------------------------------------------------------------------

def _clear_curtain_meshes():
    """Remove existing curtain objects."""
    to_delete = [
        o for o in bpy.context.scene.objects
        if o.type == 'MESH' and 'curtain' in o.name.lower()
    ]
    if to_delete:
        bpy.ops.object.select_all(action='DESELECT')
        for o in to_delete:
            o.select_set(True)
        bpy.context.view_layer.objects.active = to_delete[0]
        bpy.ops.object.delete(use_global=False)


def _create_curtain_material():
    """Create a dark curtain fabric material."""
    name = "Curtain_Mat"
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

    # Deep black fabric tone
    bsdf.inputs['Base Color'].default_value = (0.04, 0.035, 0.04, 1.0)
    bsdf.inputs['Roughness'].default_value = 0.9
    bsdf.inputs['Metallic'].default_value = 0.0

    links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    return mat


def _add_folds(curtain, width, height, depth, folds, fold_depth):
    """Subdivide mesh and displace vertices to simulate curtain pleats."""
    segments_x = folds * 2 + 1
    segments_z = max(8, int(height / 0.5))

    bpy.context.view_layer.objects.active = curtain
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.subdivide(number_cuts=segments_x - 1)
    bpy.ops.mesh.subdivide(number_cuts=segments_z - 1)
    bpy.ops.object.mode_set(mode='OBJECT')

    mesh = curtain.data
    # Base mesh is a unit cube (local coords in [-0.5, 0.5]) that is scaled by
    # object.scale = (thickness, width, height).  Two corrections vs the old
    # (flat) implementation:
    #   1. normalise local Y from its unit range [-0.5, 0.5] to [0, 1]
    #      (the old code assumed [-width/2, width/2], so only a fraction of the
    #      intended wave cycles appeared), and
    #   2. treat ``fold_depth`` as a WORLD-metre amplitude: compensate for
    #      object.scale.x (= ``depth``) so the ripple is not silently shrunk by
    #      the small thickness scale (the old world amplitude was
    #      ``fold_depth * depth``, which is why the curtain looked flat).
    local_amp = fold_depth / depth if depth > 0 else 0.0

    for vert in mesh.vertices:
        co = vert.co
        local_x = co.x
        norm_y = co.y + 0.5  # unit-cube local Y [-0.5, 0.5] -> [0, 1]
        displacement = math.sin(norm_y * folds * 2 * math.pi) * local_amp
        co.x = local_x + displacement


# ---------------------------------------------------------------------------
#  Public API
# ---------------------------------------------------------------------------

def create_curtain(
    location=(0.0, 0.0, 0.0),
    width=1.5,
    height=5.0,
    thickness=0.15,
    folds=5,
    fold_depth=0.025,
    rotation=(0.0, 0.0, 0.0),
    name=None,
):
    """
    Create a single curtain at the specified position.

    Args:
        location: (x, y, z) of the curtain bottom-center. z is the base Z.
        width: Width along Y axis (in local space before rotation).
        height: Height along Z axis.
        thickness: Base slab thickness along X axis in WORLD metres (the thin
            box before the wave is added; object.scale.x == thickness).
        folds: Number of pleat (wave) cycles across the width.
        fold_depth: Peak ripple depth in WORLD metres. It is applied in local
            space divided by ``thickness`` so the true world-space amplitude
            equals ``fold_depth`` (NOT ``fold_depth * thickness`` as before).
        rotation: Euler rotation (rx, ry, rz) in radians, applied after scaling.
            Default (0,0,0) means the curtain face is perpendicular to Y axis.
            Use (0, pi/2, 0) to make the face perpendicular to X axis instead.
        name: Optional object name. If None, auto-generated.

    Returns:
        The created curtain object.
    """
    mat = _create_curtain_material()

    center_x = location[0]
    center_y = location[1]
    center_z = location[2] + height / 2

    bpy.ops.mesh.primitive_cube_add(
        size=1,
        location=(center_x, center_y, center_z)
    )
    curtain = bpy.context.active_object
    curtain.name = name or "Curtain"
    # size=1 means 1m cube, scale directly to desired dimensions
    curtain.scale = (thickness, width, height)

    # Apply rotation after scaling
    curtain.rotation_euler = (rotation[0], rotation[1], rotation[2])

    if len(curtain.data.materials) == 0:
        curtain.data.materials.append(mat)
    else:
        curtain.data.materials[0] = mat

    _add_folds(curtain, width, height, thickness, folds, fold_depth)

    return curtain


def create_stage_curtains(stage_width=9.0, stage_depth=6.0, curtain_height=5.0):
    """
    Create left and right side curtains for a stage area.

    This is a convenience wrapper around create_curtain().

    Args:
        stage_width: Full width of the stage platform (X axis).
        stage_depth: Depth of the stage platform (Y axis).
        curtain_height: Curtain height.

    Returns:
        Tuple of (left_curtain, right_curtain) objects.
    """
    _clear_curtain_meshes()

    half_w = stage_width / 2
    curtain_width = stage_depth * 0.18
    curtain_depth = 0.3
    margin = 0.15

    left_loc = (-half_w + margin, stage_depth / 2 - curtain_width / 2, 0)
    right_loc = (half_w - margin, stage_depth / 2 - curtain_width / 2, 0)

    left_curtain = create_curtain(
        location=left_loc,
        width=curtain_width,
        height=curtain_height,
        thickness=curtain_depth,
        name="Left_Curtain",
    )
    right_curtain = create_curtain(
        location=right_loc,
        width=curtain_width,
        height=curtain_height,
        thickness=curtain_depth,
        name="Right_Curtain",
    )

    return left_curtain, right_curtain


def clear_curtain_objects():
    """Remove all curtain objects from the scene."""
    _clear_curtain_meshes()