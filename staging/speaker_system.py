# -*- coding: utf-8 -*-
"""Speaker system module - Creates guitar amp, bass amp, monitor, and PA speakers with detailed grille mesh."""

import bpy
import bmesh
import math
import mathutils


# =============================================================================
# Material Cache
# =============================================================================

_mat_cache = {}


def _get_mat(name: str) -> bpy.types.Material:
    """Get or create a cached material."""
    if name in _mat_cache:
        return _mat_cache[name]

    mats = {
        "Speaker_Cabinet": ((0.1, 0.1, 0.1, 1.0), 0.0, 0.85),
        "Speaker_Grille": ((0.08, 0.08, 0.08, 1.0), 0.85, 0.35),
        "Speaker_Knob": ((0.6, 0.6, 0.65, 1.0), 0.9, 0.3),
        "Speaker_Driver": ((0.05, 0.05, 0.06, 1.0), 0.1, 0.7),
        "Speaker_Frame": ((0.15, 0.15, 0.16, 1.0), 0.3, 0.6),
        "Speaker_Panel": ((0.18, 0.18, 0.20, 1.0), 0.05, 0.75),
        "Speaker_DustCap": ((0.03, 0.03, 0.04, 1.0), 0.2, 0.5),
    }

    if name not in mats:
        return None

    base_color, metallic, roughness = mats[name]
    mat = _create_principled_material(name, base_color, metallic, roughness)
    _mat_cache[name] = mat
    return mat


def _assign_material(obj: bpy.types.Object, material: bpy.types.Material):
    """Assign a material to the first slot of an object's mesh data."""
    if material is None:
        return
    if len(obj.data.materials) == 0:
        obj.data.materials.append(material)
    else:
        obj.data.materials[0] = material


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
    return bpy.context.active_object


def _add_bevel_to_object(obj: bpy.types.Object, width: float = 0.003, segments: int = 2):
    """Add a subtle bevel modifier to an object for realistic edge softening."""
    mod = obj.modifiers.new(name="Bevel", type='BEVEL')
    mod.width = width
    mod.segments = segments
    mod.limit_method = 'ANGLE'
    mod.angle_limit = math.radians(30)
    mod.use_clamp_overlap = True


def _create_wireframe_grille(width: float, height: float, thickness: float, 
                             grid_spacing: float = 0.015, wire_radius: float = 0.002):
    """
    Create a realistic wire mesh grille using Wireframe + Solidify modifiers.
    Returns the grille object.
    """
    # Base plate
    bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 0))
    grille = bpy.context.active_object
    grille.name = "Wireframe_Grille"
    grille.scale = (width / 2, thickness, height / 2)

    # Wireframe modifier: create grid pattern
    wf = grille.modifiers.new(name="Wireframe", type='WIREFRAME')
    wf.thickness = 0.001
    wf.offset = 0
    # Control density via scale in object mode after applying
    # We use the wire count by adjusting the base cube resolution first
    
    # Actually, for proper grid control, let's use a grid primitive instead
    bpy.ops.object.delete()
    
    # Create a dense grid
    bpy.ops.mesh.primitive_grid_add(
        x_subdivisions=int(width / grid_spacing) + 1,
        y_subdivisions=int(thickness * 10) + 1,  # thin in depth
        size=1, 
        location=(0, 0, 0)
    )
    grille = bpy.context.active_object
    grille.name = "Wireframe_Grille"
    
    # Scale to fit: X = width, Y = thickness (very thin), Z = height
    grille.scale = (width, grid_spacing * 0.5, height)
    
    # Edge Split for clean shading
    es = grille.modifiers.new(name="EdgeSplit", type='EDGE_SPLIT')
    es.use_edge_angle = True
    es.angle_threshold = math.radians(30)
    
    # Solidify to give wires thickness
    sf = grille.modifiers.new(name="Solidify", type='SOLIDIFY')
    sf.thickness = wire_radius
    sf.offset = 0.5  # Expand outward
    
    return grille


def _recess_front_face(obj: bpy.types.Object, panel_w: float, panel_h: float, panel_recess: float, is_bass: bool = False):
    """
    Create a true rectangular recess on the front face of a cube object.
    
    Uses BMesh bisect_plane to slice the front face into a grid,
    then pushes the center rectangle vertices inward by panel_recess.
    
    Args:
        obj: The cube object (transform must be applied first)
        panel_w: Width of the recessed area
        panel_h: Height of the recessed area  
        panel_recess: Depth to push inward (positive = toward +Y = inside the object)
        is_bass: If True, use bass amp dimensions for tolerance tuning
    """
    me = obj.data
    
    # Create a BMesh from the mesh data
    bm = bmesh.new()
    bm.from_mesh(me)
    
    # Get the actual dimensions after transform apply
    dims = obj.dimensions
    half_W, half_D, half_H = dims.x / 2, dims.y / 2, dims.z / 2
    
    # Front face is at Y ≈ -half_D
    front_Y = -half_D
    
    # --- Bisect the mesh with vertical planes (X cuts) ---
    # Blender 5.0 API: plane_co (point on plane) + plane_no (plane normal)
    for cut_x in [panel_w / 2, -panel_w / 2]:
        geom = list(bm.verts) + list(bm.edges) + list(bm.faces)
        bmesh.ops.bisect_plane(
            bm,
            geom=geom,
            plane_co=mathutils.Vector((cut_x, 0, 0)),   # point on the cutting plane
            plane_no=mathutils.Vector((1, 0, 0)),       # X-axis normal → vertical plane
        )
    
    # --- Bisect the mesh with horizontal planes (Z cuts) ---
    for cut_z in [panel_h / 2, -panel_h / 2]:
        geom = list(bm.verts) + list(bm.edges) + list(bm.faces)
        bmesh.ops.bisect_plane(
            bm,
            geom=geom,
            plane_co=mathutils.Vector((0, 0, cut_z)),   # point on the cutting plane
            plane_no=mathutils.Vector((0, 0, 1)),       # Z-axis normal → horizontal plane
        )
    
    # --- Push the center-front vertices inward (toward +Y) ---
    # The 4-corner vertices of the front face that are within the recess rectangle:
    #   |x| < panel_w/2 AND |z| < panel_h/2 AND Y close to front_Y
    for v in bm.verts:
        if abs(v.co.y - front_Y) < 0.01 and abs(v.co.x) <= panel_w / 2 + 0.005 and abs(v.co.z) <= panel_h / 2 + 0.005:
            v.co.y += panel_recess
    
    # Write the BMesh back to the mesh data
    bm.to_mesh(me)
    bm.free()
    me.update()


def _create_driver_cone(radius: float, depth: float, location: tuple, rotation: tuple = (0, 0, 0)):
    """Create a speaker driver cone (woofer/tweeter representation)."""
    bpy.ops.mesh.primitive_cylinder_add(
        radius=radius, depth=depth, 
        location=location,
        vertices=int(max(16, int(radius / 0.02)))
    )
    cone = bpy.context.active_object
    cone.name = "Driver_Cone"
    cone.rotation_euler = mathutils.Euler(rotation)
    
    # Taper the bottom to simulate cone shape
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='DESELECT')
    bpy.ops.mesh.select_mode(type='VERT')
    
    # Select bottom face vertices
    bm = bpy.context.evaluated_depsgraph_get().objects[cone.name].data
    bpy.ops.object.mode_set(mode='EDIT')
    
    # Use proportional editing or manual selection to taper
    # Simpler approach: scale bottom ring
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.object.mode_set(mode='OBJECT')
    
    _assign_material(cone, _get_mat("Speaker_Driver"))
    return cone


def create_speaker(speaker_type: str, location: tuple, rotation: tuple = (0, 0, 0)) -> list:
    """
    Create a speaker of the specified type with detailed grille mesh. All parts are joined into one object.
    
    Args:
        speaker_type: "guitar_amp", "bass_amp", "monitor", "pa"
        location: (x, y, z) position
        rotation: (x, y, z) rotation in radians
    
    Returns:
        List with single joined object
    """
    loc = mathutils.Vector(location)
    rot = mathutils.Euler(rotation)
    
    creators = {
        "guitar_amp": _create_guitar_amp,
        "bass_amp": _create_bass_amp,
        "monitor": _create_monitor,
        "pa": _create_pa,
    }
    
    if speaker_type not in creators:
        raise ValueError(f"Unknown speaker type: {speaker_type}")
    
    objs = creators[speaker_type](loc, rot)
    
    joined = _join_objects(objs)
    if joined is not None:
        name_map = {
            "guitar_amp": "Guitar_Amp",
            "bass_amp": "Bass_Amp",
            "monitor": "Floor_Monitor",
            "pa": "PA_Speaker"
        }
        joined.name = name_map.get(speaker_type, speaker_type)
        return [joined]
    
    return objs


# ──────────────────────────────────────────────
# Guitar Amp (with detailed grille mesh + bevel)
# ──────────────────────────────────────────────
def _create_guitar_amp(loc: mathutils.Vector, rot: mathutils.Euler) -> list:
    objs = []
    W, D, H = 0.48, 0.55, 0.90
    
    cab_mat = _get_mat("Speaker_Cabinet")
    grille_mat = _get_mat("Speaker_Grille")
    knob_mat = _get_mat("Speaker_Knob")
    frame_mat = _get_mat("Speaker_Frame")
    panel_mat = _get_mat("Speaker_Panel")
    dustcap_mat = _get_mat("Speaker_DustCap")

    # Cabinet with bevel
    bpy.ops.mesh.primitive_cube_add(size=2, location=loc)
    cab = bpy.context.active_object
    cab.name = "GuitarAmp_Cabinet"
    cab.scale = (W / 2, D / 2, H / 2)
    cab.rotation_euler = rot
    _assign_material(cab, cab_mat)
    _add_bevel_to_object(cab, width=0.003, segments=2)
    objs.append(cab)
    
    # ── Detailed wire mesh grille ──
    front_vec = _rotate_vec((0, -1, 0), rot)
    grille_loc = loc + front_vec * (D / 2 + 0.03)
    grille_w = W - 0.08
    grille_h = H - 0.14

    # Blender 5.0: primitive_grid_add does NOT support size_x/size_y.
    # Grid created at size=1 (X:-0.5~0.5, Y:-0.5~0.5). Scale X->width, Y->height, Z stays thin.
    bpy.ops.mesh.primitive_grid_add(
        x_subdivisions=int(grille_w / 0.012) + 1,
        y_subdivisions=int(grille_h / 0.012) + 1,
        size=1, location=grille_loc
    )
    grille = bpy.context.active_object
    grille.name = "GuitarAmp_Grille_Mesh"
    # Scale: X->width, Y->height (grid is in X-Y plane). Z stays thin → Solidify gives depth.
    grille.scale = (grille_w, grille_h, 0.001)
    # Rotate +90° around local X so the grid face (normal +Z) faces -Y (front of cabinet)
    grille.rotation_euler = mathutils.Euler((rot[0] + math.pi / 2, rot[1], rot[2]))

    sf = grille.modifiers.new(name="Solidify", type='SOLIDIFY')
    sf.thickness = 0.005
    sf.offset = 0

    _assign_material(grille, grille_mat)
    objs.append(grille)
    
    driver_loc = loc + front_vec * (D / 4)
    bpy.ops.mesh.primitive_cylinder_add(
        radius=0.16, depth=0.08, location=driver_loc, vertices=32
    )
    driver = bpy.context.active_object
    driver.name = "GuitarAmp_Driver"
    driver.rotation_euler = mathutils.Euler((math.pi / 2 + rot[0], rot[1], rot[2]))
    _assign_material(driver, _get_mat("Speaker_Driver"))
    objs.append(driver)
    
    # ── Dust cap on driver center ──
    # Driver is oriented along +Y axis (rotated X by pi/2). "Top" of cylinder = front face = -Y direction.
    dustcap_loc = driver_loc + front_vec * 0.035
    bpy.ops.mesh.primitive_cylinder_add(radius=0.04, depth=0.015, location=dustcap_loc, vertices=16)
    dustcap = bpy.context.active_object
    dustcap.name = "GuitarAmp_DustCap"
    dustcap.rotation_euler = mathutils.Euler((math.pi / 2 + rot[0], rot[1], rot[2]))
    _assign_material(dustcap, dustcap_mat)
    objs.append(dustcap)

    # ── Metal trim frame around grille (deeper for visibility) ──
    trim_depth = 0.04
    trim_loc = loc + front_vec * (D / 2 + trim_depth / 2 + 0.005)
    
    # Top trim bar
    bpy.ops.mesh.primitive_cube_add(size=2, location=trim_loc)
    trim_top = bpy.context.active_object
    trim_top.name = "GuitarAmp_Trim_Top"
    trim_top.scale = ((grille_w + 0.02) / 2, trim_depth / 2, 0.01)
    trim_top.rotation_euler = rot
    trim_top.location = trim_loc + _rotate_vec((0, 0, grille_h / 2 + 0.005), rot)
    _assign_material(trim_top, frame_mat)
    objs.append(trim_top)
    
    # Bottom trim bar
    bpy.ops.mesh.primitive_cube_add(size=2, location=trim_loc)
    trim_bot = bpy.context.active_object
    trim_bot.name = "GuitarAmp_Trim_Bot"
    trim_bot.scale = ((grille_w + 0.02) / 2, trim_depth / 2, 0.01)
    trim_bot.rotation_euler = rot
    trim_bot.location = trim_loc + _rotate_vec((0, 0, -grille_h / 2 - 0.005), rot)
    _assign_material(trim_bot, frame_mat)
    objs.append(trim_bot)
    
    # ── Amp head with TRUE RECESSED control panel (BMesh bisect_plane) ──
    head_W, head_D, head_H = 0.48, 0.43, 0.15
    head_offset_z = (H + head_H) / 2
    head_loc = loc + _rotate_vec((0, 0, 1), rot) * head_offset_z
    
    # Panel recess dimensions:
    panel_w = head_W - 0.06    # recess width
    panel_h = head_H * 0.5     # recess height
    panel_recess = 0.030       # 30mm recess depth from front face
    
    bpy.ops.mesh.primitive_cube_add(size=2, location=head_loc)
    head = bpy.context.active_object
    head.name = "GuitarAmp_Head"
    head.scale = (head_W / 2, head_D / 2, head_H / 2)
    head.rotation_euler = rot
    
    # ── Apply transform so BMesh works in actual coordinate space ──
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    
    # ── IMPORTANT: After transform_apply, head.location may differ from head_loc.
    #     Re-read the actual position to ensure knob/inset/vent placement is correct. ──
    head_loc = mathutils.Vector(head.location)
    
    # ── Use BMesh bisect_plane to slice the front face into a grid,
    #     then push the center rectangle inward to create a true recess. ──
    _recess_front_face(head, panel_w, panel_h, panel_recess, is_bass=False)
    
    _assign_material(head, cab_mat)
    objs.append(head)
    
    # ── Control Panel Backing Plate (sits at BACK of the recess) ──
    inset_loc = head_loc + _rotate_vec((0, -1, 0), rot) * (head_D / 2 - panel_recess + 0.002)
    bpy.ops.mesh.primitive_cube_add(size=2, location=inset_loc)
    inset_panel = bpy.context.active_object
    inset_panel.name = "GuitarAmp_PanelInset"
    inset_panel.scale = (panel_w / 2, 0.004 / 2, panel_h / 2)
    inset_panel.rotation_euler = rot
    _assign_material(inset_panel, panel_mat)
    objs.append(inset_panel)
    
    # ── Bevel modifier for head edges ──
    _add_bevel_to_object(head, width=0.003, segments=2)
    
    # ── Vent slots on amp head (top surface grooves) ──
    vent_count = 6
    vent_spacing = (head_W - 0.1) / (vent_count + 1)
    for i in range(vent_count):
        x_off = -(head_W / 2 - 0.05) + vent_spacing * (i + 1)
        vent_loc = head_loc + _rotate_vec((x_off, 0, head_H / 2 + 0.001), rot)
        bpy.ops.mesh.primitive_cube_add(size=2, location=vent_loc)
        vent = bpy.context.active_object
        vent.name = f"GuitarAmp_Vent_{i}"
        vent.scale = (0.01, head_D / 3, 0.003)
        vent.rotation_euler = rot
        _assign_material(vent, _get_mat("Speaker_Grille"))
        objs.append(vent)
    
    # ── Knobs (4) ──
    # Knobs are mounted on the backing plate, protruding toward the recess front edge.
    #   backing plate center Y = -(head_D/2 - panel_recess + 0.002)
    #                          = -(0.215 - 0.030 + 0.002) = -0.187
    #   ring center Y offset  = -(head_D/2 - panel_recess + 0.010)
    #                          = -(0.215 - 0.030 + 0.010) = -0.195
    #   This puts the ring ~8mm past the backing plate (outside of it, visible ✓)
    knob_positions = [-(panel_w - 0.10) / 2 + (panel_w - 0.10) / 3 * i for i in range(4)]
    panel_loc = head_loc + _rotate_vec((0, -1, 0), rot) * (head_D / 2 - panel_recess + 0.010)

    # Random-ish indicator angles for realism (each knob points to a different value)
    # Angles are in the knob's local XZ plane: angle=0 means +X (right), increasing toward +Z (up).
    _knob_angles_guitar = [math.radians(30), math.radians(120), math.radians(270), math.radians(60)]

    for i, x_off in enumerate(knob_positions):
        knob_loc = panel_loc + _rotate_vec((x_off, 0, 0), rot)
        # Knob base ring
        bpy.ops.mesh.primitive_torus_add(
            major_radius=0.025, minor_radius=0.005,
            major_segments=16, minor_segments=8, location=knob_loc
        )
        ring = bpy.context.active_object
        ring.name = f"GuitarAmp_KnobRing_{i}"
        ring.rotation_euler = mathutils.Euler((rot[0] + math.pi / 2, rot[1], rot[2]))
        _assign_material(ring, knob_mat)
        objs.append(ring)

        # Knob cap (extends slightly forward from ring center for grip)
        knob_cap_loc = knob_loc + _rotate_vec((0, -0.015, 0), rot)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.018, depth=0.020, location=knob_cap_loc)
        knob = bpy.context.active_object
        knob.name = f"GuitarAmp_Knob_{i}"
        knob.rotation_euler = mathutils.Euler((rot[0] + math.pi / 2, rot[1], rot[2]))
        _assign_material(knob, knob_mat)
        objs.append(knob)

        # ── Knob indicator dot (on top of cap surface) ──
        angle = _knob_angles_guitar[i]
        indicator_r = 0.010
        local_x = math.cos(angle) * indicator_r
        local_z = math.sin(angle) * indicator_r
        # Place indicator on top face of cap (slightly past cap center toward +Z)
        ind_local = mathutils.Vector((local_x, -0.010, local_z))
        ind_world = knob_loc + _rotate_vec((ind_local.x, ind_local.y, ind_local.z), rot)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.004, depth=0.006, location=ind_world, vertices=6)
        ind_obj = bpy.context.active_object
        ind_obj.name = f"GuitarAmp_Indicator_{i}"
        ind_obj.rotation_euler = mathutils.Euler((rot[0] + math.pi / 2, rot[1], rot[2]))
        _assign_material(ind_obj, knob_mat)
        objs.append(ind_obj)

    return objs


# ──────────────────────────────────────────────
# Bass Amp (with detailed grille mesh + bevel)
# ──────────────────────────────────────────────
def _create_bass_amp(loc: mathutils.Vector, rot: mathutils.Euler) -> list:
    objs = []
    W, D, H = 0.55, 0.60, 0.80
    
    cab_mat = _get_mat("Speaker_Cabinet")
    grille_mat = _get_mat("Speaker_Grille")
    knob_mat = _get_mat("Speaker_Knob")
    frame_mat = _get_mat("Speaker_Frame")
    panel_mat = _get_mat("Speaker_Panel")
    dustcap_mat = _get_mat("Speaker_DustCap")

    # Cabinet with bevel
    bpy.ops.mesh.primitive_cube_add(size=2, location=loc)
    cab = bpy.context.active_object
    cab.name = "BassAmp_Cabinet"
    cab.scale = (W / 2, D / 2, H / 2)
    cab.rotation_euler = rot
    _assign_material(cab, cab_mat)
    _add_bevel_to_object(cab, width=0.003, segments=2)
    objs.append(cab)
    
    # ── Detailed wire mesh grille ──
    front_vec = _rotate_vec((0, -1, 0), rot)
    grille_loc = loc + front_vec * (D / 2 + 0.03)
    grille_w = W - 0.08
    grille_h = H - 0.08

    bpy.ops.mesh.primitive_grid_add(
        x_subdivisions=int(grille_w / 0.018) + 1,  # wider spacing for bass
        y_subdivisions=int(grille_h / 0.018) + 1,
        size=1, location=grille_loc
    )
    grille = bpy.context.active_object
    grille.name = "BassAmp_Grille_Mesh"
    grille.scale = (grille_w, grille_h, 0.001)
    grille.rotation_euler = mathutils.Euler((rot[0] + math.pi / 2, rot[1], rot[2]))

    sf = grille.modifiers.new(name="Solidify", type='SOLIDIFY')
    sf.thickness = 0.005
    sf.offset = 0

    _assign_material(grille, grille_mat)
    objs.append(grille)
    
    # ── Bass driver cone (larger) ──
    driver_loc = loc + front_vec * (D / 4)
    bpy.ops.mesh.primitive_cylinder_add(
        radius=0.20, depth=0.10, location=driver_loc, vertices=32
    )
    driver = bpy.context.active_object
    driver.name = "BassAmp_Driver"
    driver.rotation_euler = mathutils.Euler((math.pi / 2 + rot[0], rot[1], rot[2]))
    _assign_material(driver, _get_mat("Speaker_Driver"))
    objs.append(driver)
    
    # ── Dust cap on bass driver center ──
    bdustcap_loc = driver_loc + front_vec * 0.04
    bpy.ops.mesh.primitive_cylinder_add(radius=0.05, depth=0.018, location=bdustcap_loc, vertices=16)
    bdustcap = bpy.context.active_object
    bdustcap.name = "BassAmp_DustCap"
    bdustcap.rotation_euler = mathutils.Euler((math.pi / 2 + rot[0], rot[1], rot[2]))
    _assign_material(bdustcap, dustcap_mat)
    objs.append(bdustcap)

    # ── Metal trim frame (deeper for visibility) ──
    trim_loc = loc + front_vec * (D / 2 + 0.035)
    for z_sign in [-1, 1]:
        bpy.ops.mesh.primitive_cube_add(size=2, location=trim_loc)
        trim = bpy.context.active_object
        trim.name = f"BassAmp_Trim_{z_sign}"
        trim.scale = ((grille_w + 0.02) / 2, 0.01, 0.008)
        trim.rotation_euler = rot
        trim.location = trim_loc + _rotate_vec((0, 0, z_sign * (grille_h / 2 + 0.004)), rot)
        _assign_material(trim, frame_mat)
        objs.append(trim)
    
    # ── Amp head with TRUE RECESSED control panel (BMesh bisect_plane) ──
    head_W, head_D, head_H = 0.50, 0.48, 0.18
    head_offset_z = (H + head_H) / 2
    head_loc = loc + _rotate_vec((0, 0, 1), rot) * head_offset_z
    
    # Panel recess dimensions for bass amp:
    bpanel_w = head_W - 0.06
    bpanel_h = head_H * 0.5
    bpanel_recess = 0.030  # 30mm recess depth
    
    bpy.ops.mesh.primitive_cube_add(size=2, location=head_loc)
    head = bpy.context.active_object
    head.name = "BassAmp_Head"
    head.scale = (head_W / 2, head_D / 2, head_H / 2)
    head.rotation_euler = rot
    
    # ── Apply transform so BMesh works in actual coordinate space ──
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    
    # ── IMPORTANT: Re-read actual position after transform_apply ──
    head_loc = mathutils.Vector(head.location)
    
    # ── Use BMesh bisect_plane to create true recess ──
    _recess_front_face(head, bpanel_w, bpanel_h, bpanel_recess, is_bass=True)
    
    _assign_material(head, cab_mat)
    objs.append(head)
    
    # ── Control Panel Backing Plate (inside recess) ──
    binset_loc = head_loc + _rotate_vec((0, -1, 0), rot) * (head_D / 2 - bpanel_recess + 0.002)
    bpy.ops.mesh.primitive_cube_add(size=2, location=binset_loc)
    binset_panel = bpy.context.active_object
    binset_panel.name = "BassAmp_PanelInset"
    binset_panel.scale = (bpanel_w / 2, 0.004 / 2, bpanel_h / 2)
    binset_panel.rotation_euler = rot
    _assign_material(binset_panel, panel_mat)
    objs.append(binset_panel)
    
    # ── Vent slots ──
    vent_count = 8
    vent_spacing = (head_W - 0.12) / (vent_count + 1)
    for i in range(vent_count):
        x_off = -(head_W / 2 - 0.06) + vent_spacing * (i + 1)
        vent_loc = head_loc + _rotate_vec((x_off, 0, head_H / 2 + 0.001), rot)
        bpy.ops.mesh.primitive_cube_add(size=2, location=vent_loc)
        vent = bpy.context.active_object
        vent.name = f"BassAmp_Vent_{i}"
        vent.scale = (0.008, head_D / 3, 0.003)
        vent.rotation_euler = rot
        _assign_material(vent, _get_mat("Speaker_Grille"))
        objs.append(vent)
    
    # ── Knobs (6) with rings ──
    # Knobs mounted on backing plate inside the recess.
    #   bass head front face      = -0.24m
    #   recess pushes inward by   = +0.030
    #   recess inner face Y       = -0.210
    #   backing plate center      = -0.212
    #   ring center Y offset      = -(head_D/2 - bpanel_recess + 0.010) = -0.220
    knob_positions = [-(bpanel_w - 0.10) / 2 + (bpanel_w - 0.10) / 5 * i for i in range(6)]
    panel_loc = head_loc + _rotate_vec((0, -1, 0), rot) * (head_D / 2 - bpanel_recess + 0.010)

    # Indicator angles for bass amp knobs (in knob local XZ plane)
    _bass_knob_angles = [math.radians(45), math.radians(90), math.radians(200), math.radians(310), math.radians(15), math.radians(160)]

    for i, x_off in enumerate(knob_positions):
        knob_loc = panel_loc + _rotate_vec((x_off, 0, 0), rot)

        # Knob base ring
        bpy.ops.mesh.primitive_torus_add(
            major_radius=0.030, minor_radius=0.006,
            major_segments=16, minor_segments=8, location=knob_loc
        )
        ring = bpy.context.active_object
        ring.name = f"BassAmp_KnobRing_{i}"
        ring.rotation_euler = mathutils.Euler((rot[0] + math.pi / 2, rot[1], rot[2]))
        _assign_material(ring, knob_mat)
        objs.append(ring)

        # Knob cap (extends slightly forward from ring center for grip)
        knob_cap_loc = knob_loc + _rotate_vec((0, -0.015, 0), rot)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.022, depth=0.030, location=knob_cap_loc)
        knob = bpy.context.active_object
        knob.name = f"BassAmp_Knob_{i}"
        knob.rotation_euler = mathutils.Euler((rot[0] + math.pi / 2, rot[1], rot[2]))
        _assign_material(knob, knob_mat)
        objs.append(knob)

        # ── Knob indicator dot (on top of cap surface) ──
        angle = _bass_knob_angles[i]
        indicator_r = 0.012
        local_x = math.cos(angle) * indicator_r
        local_z = math.sin(angle) * indicator_r
        ind_local = mathutils.Vector((local_x, -0.010, local_z))
        ind_world = knob_loc + _rotate_vec((ind_local.x, ind_local.y, ind_local.z), rot)
        bpy.ops.mesh.primitive_cylinder_add(radius=0.005, depth=0.006, location=ind_world, vertices=6)
        ind_obj_b = bpy.context.active_object
        ind_obj_b.name = f"BassAmp_Indicator_{i}"
        ind_obj_b.rotation_euler = mathutils.Euler((rot[0] + math.pi / 2, rot[1], rot[2]))
        _assign_material(ind_obj_b, knob_mat)
        objs.append(ind_obj_b)

    return objs


# ──────────────────────────────────────────────
# Floor Monitor (wedge with detailed grille + stand base)
# ──────────────────────────────────────────────
def _create_monitor(loc: mathutils.Vector, rot: mathutils.Euler) -> list:
    objs = []
    W, D = 0.60, 0.50
    H_rear, H_front = 0.40, 0.20
    
    cab_mat = _get_mat("Speaker_Cabinet")
    grille_mat = _get_mat("Speaker_Grille")
    frame_mat = _get_mat("Speaker_Frame")
    knob_mat = _get_mat("Speaker_Knob")
    
    # Wedge-shaped enclosure via vertex manipulation
    bpy.ops.mesh.primitive_cube_add(size=2, location=loc)
    monitor = bpy.context.active_object
    monitor.name = "Monitor_Body"
    monitor.scale = (W / 2, D / 2, H_rear / 2)
    monitor.rotation_euler = rot
    _assign_material(monitor, cab_mat)
    _add_bevel_to_object(monitor, width=0.003, segments=2)
    
    me = monitor.data
    for v in me.vertices:
        if v.co.y > 0.5 and v.co.z > 0.5:
            v.co.z = v.co.z * (H_front / H_rear)
    me.update()
    objs.append(monitor)
    
    # ── Wire mesh grille on sloped face ──
    front_vec = _rotate_vec((0, -1, 0), rot)
    grille_loc = loc + front_vec * (D / 2.5)
    
    # The cabinet vertex manipulation scales front-top z from 1 to (H_front/H_rear).
    # After object scale of H_rear/2:
    #   back-top z = +H_rear/2, front-top z = +H_front/2
    # Actual height difference on the slope = (H_rear/2 - H_front/2) = (H_rear - H_front)/2
    wedge_angle = math.atan2((H_rear - H_front) / 2, D)
    slope_len = math.sqrt(D ** 2 + (H_rear - H_front) ** 2)
    grille_w = W - 0.1
    
    # Create a grid for the sloped grille
    bpy.ops.mesh.primitive_grid_add(
        x_subdivisions=int(grille_w / 0.015) + 1,
        y_subdivisions=int(slope_len / 0.015) + 1,
        size=1, location=(0, 0, 0)
    )
    grille = bpy.context.active_object
    grille.name = "Monitor_Grille_Mesh"
    grille.scale = (grille_w, slope_len, 0.002)
    
    # Position on the sloped face
    # The slope goes from back-top (y=-D/2, z=+H_rear/2) to front-top (y=+D/2, z=+H_front/2).
    # Center of slope: y=0, z=(H_rear/2 + H_front/2)/2 = (H_rear+H_front)/4
    grille_center_z = (H_rear + H_front) / 4
    grille.location = loc + _rotate_vec((0, 0, grille_center_z), rot)
    grille.rotation_euler = mathutils.Euler((rot[0] - wedge_angle, rot[1], rot[2]))
    
    sf = grille.modifiers.new(name="Solidify", type='SOLIDIFY')
    sf.thickness = 0.0015
    sf.offset = 0
    
    _assign_material(grille, grille_mat)
    objs.append(grille)
    
    # ── Driver cone behind grille ──
    # primitive_cylinder_add creates a cylinder oriented along Z-axis.
    # Place the driver in the lower-center of the wedge, slightly toward the back.
    # Y=-D/6 keeps it away from the front edge; Z=H_rear/4 places it in the lower half.
    driver_loc = loc + _rotate_vec((0, -D / 6, H_rear / 4), rot)
    bpy.ops.mesh.primitive_cylinder_add(
        radius=0.12, depth=0.08, location=driver_loc, vertices=24
    )
    driver = bpy.context.active_object
    driver.name = "Monitor_Driver"
    driver.rotation_euler = mathutils.Euler((rot[0] - wedge_angle, rot[1], rot[2]))
    _assign_material(driver, _get_mat("Speaker_Driver"))
    objs.append(driver)
    
    # ── Tweeter (smaller cone at top of slope) ──
    # Place tweeter in the upper-back portion of the wedge, separated from driver.
    # Y=-D/5 puts it toward the back side (more negative than driver's -D/6).
    # Z=(H_front+H_rear)/4 + 0.02 places it in the upper half of the slope.
    # Z offset of -0.02 pushes the tweeter inside the slope surface so it doesn't protrude.
    tweeter_loc = loc + _rotate_vec((0, -D / 5, (H_front + H_rear) / 4 - 0.02), rot)
    bpy.ops.mesh.primitive_cylinder_add(
        radius=0.04, depth=0.05, location=tweeter_loc, vertices=16
    )
    tweeter = bpy.context.active_object
    tweeter.name = "Monitor_Tweeter"
    tweeter.rotation_euler = mathutils.Euler((rot[0] - wedge_angle, rot[1], rot[2]))
    _assign_material(tweeter, _get_mat("Speaker_Driver"))
    objs.append(tweeter)
    
    # ── Metal trim frame around grille ──
    trim_loc = loc + _rotate_vec((0, 0, grille_center_z), rot)
    for side_sign in [-1, 1]:
        bpy.ops.mesh.primitive_cube_add(size=2, location=trim_loc)
        trim = bpy.context.active_object
        trim.name = f"Monitor_Trim_X_{side_sign}"
        trim.scale = (0.008, slope_len / 2, 0.015)
        trim.rotation_euler = mathutils.Euler((rot[0] - wedge_angle, rot[1], rot[2]))
        trim.location = trim_loc + _rotate_vec((side_sign * (grille_w / 2 + 0.004), 0, 0), 
                                               mathutils.Euler((rot[0] - wedge_angle, 0, 0)))
        # Offset in local X along the sloped face
        trim_rot = mathutils.Euler((rot[0] - wedge_angle, 0, 0))
        trim.location = trim_loc + _rotate_vec(
            (side_sign * (grille_w / 2 + 0.004), 0, 0), trim_rot
        )
        _assign_material(trim, frame_mat)
        objs.append(trim)
    
    # ── Adjustable stand base (rotation mount) ──
    # Cabinet bottom is at loc.z - H_rear/2 (since scale=H_rear/2 from center).
    # Foot depth=0.04, so foot center Z = floor_z + depth/2 = loc.z - H_rear/2 + 0.02
    # Y=D/2+0.01 puts it just outside the front face.
    foot_loc = loc + _rotate_vec((0, D / 2 + 0.01, -H_rear / 2 + 0.02), rot)
    bpy.ops.mesh.primitive_cylinder_add(
        radius=0.04, depth=0.04, location=foot_loc, vertices=16
    )
    foot = bpy.context.active_object
    foot.name = "Monitor_Foot"
    foot.rotation_euler = rot
    _assign_material(foot, frame_mat)
    objs.append(foot)
    
    # Small adjustment screw/knob on top of the foot
    screw_loc = foot_loc + _rotate_vec((0, 0.04, 0.02), rot)
    bpy.ops.mesh.primitive_cylinder_add(
        radius=0.012, depth=0.02, location=screw_loc, vertices=8
    )
    screw = bpy.context.active_object
    screw.name = "Monitor_Screw"
    screw.rotation_euler = rot
    _assign_material(screw, knob_mat)
    objs.append(screw)
    
    return objs


# ──────────────────────────────────────────────
# PA Speaker (with detailed grille mesh + bevel)
# ──────────────────────────────────────────────
def _create_pa(loc: mathutils.Vector, rot: mathutils.Euler) -> list:
    objs = []
    W, D, H = 0.60, 0.70, 1.00
    
    cab_mat = _get_mat("Speaker_Cabinet")
    grille_mat = _get_mat("Speaker_Grille")
    frame_mat = _get_mat("Speaker_Frame")
    
    # Enclosure body with bevel
    bpy.ops.mesh.primitive_cube_add(size=2, location=loc)
    pa = bpy.context.active_object
    pa.name = "PA_Body"
    pa.scale = (W / 2, D / 2, H / 2)
    pa.rotation_euler = rot
    _assign_material(pa, cab_mat)
    _add_bevel_to_object(pa, width=0.003, segments=2)
    objs.append(pa)
    
    # ── Detailed wire mesh grille (two sections: woofer lower + horn/tweeter upper) ──
    front_vec = _rotate_vec((0, -1, 0), rot)
    
    # Lower section: large woofer grille (70% of height)
    woofer_grille_h = (H - 0.16) * 0.65
    woofer_grille_w = W - 0.06
    woofer_grille_z = loc.z - (H - 0.16) * 0.175
    
    wp_loc_3d = loc + front_vec * (D / 2 + 0.03)
    wp_loc_3d.z = woofer_grille_z

    bpy.ops.mesh.primitive_grid_add(
        x_subdivisions=int(woofer_grille_w / 0.014) + 1,
        y_subdivisions=int(woofer_grille_h / 0.014) + 1,
        size=1, location=wp_loc_3d
    )
    woofer_grille = bpy.context.active_object
    woofer_grille.name = "PA_Woofer_Grille"
    woofer_grille.scale = (woofer_grille_w, woofer_grille_h, 0.001)
    woofer_grille.rotation_euler = mathutils.Euler((rot[0] + math.pi / 2, rot[1], rot[2]))

    sf = woofer_grille.modifiers.new(name="Solidify", type='SOLIDIFY')
    sf.thickness = 0.005
    sf.offset = 0

    _assign_material(woofer_grille, grille_mat)
    objs.append(woofer_grille)

    # Upper section: horn/tweeter grille (smaller, narrower)
    horn_grille_h = (H - 0.16) * 0.25
    horn_grille_w = W - 0.20
    horn_grille_z_offset = (H - 0.16) * 0.325

    hp_loc_3d = loc + front_vec * (D / 2 + 0.03)
    hp_loc_3d.z = loc.z + horn_grille_z_offset

    bpy.ops.mesh.primitive_grid_add(
        x_subdivisions=int(horn_grille_w / 0.014) + 1,
        y_subdivisions=int(horn_grille_h / 0.014) + 1,
        size=1, location=hp_loc_3d
    )
    horn_grille = bpy.context.active_object
    horn_grille.name = "PA_Horn_Grille"
    horn_grille.scale = (horn_grille_w, horn_grille_h, 0.001)
    horn_grille.rotation_euler = mathutils.Euler((rot[0] + math.pi / 2, rot[1], rot[2]))

    sf2 = horn_grille.modifiers.new(name="Solidify", type='SOLIDIFY')
    sf2.thickness = 0.005
    sf2.offset = 0

    _assign_material(horn_grille, grille_mat)
    objs.append(horn_grille)
    
    # ── Driver cones visible behind grille (further inside cab: Y offset smaller than grille) ──
    # Woofer (large)
    woofer_d_loc = loc + front_vec * (D / 3)
    woofer_d_loc.z = loc.z - horn_grille_z_offset * 0.5
    bpy.ops.mesh.primitive_cylinder_add(
        radius=0.16, depth=0.12, location=woofer_d_loc, vertices=32
    )
    woofer_d = bpy.context.active_object
    woofer_d.name = "PA_Woofer_Driver"
    woofer_d.rotation_euler = mathutils.Euler((math.pi / 2 + rot[0], rot[1], rot[2]))
    _assign_material(woofer_d, _get_mat("Speaker_Driver"))
    objs.append(woofer_d)
    
    # Tweeter/Horn (smaller, higher, further inside)
    horn_d_loc = loc + front_vec * (D / 2.8)
    horn_d_loc.z = loc.z + horn_grille_z_offset * 0.5
    bpy.ops.mesh.primitive_cylinder_add(
        radius=0.07, depth=0.08, location=horn_d_loc, vertices=24
    )
    horn_d = bpy.context.active_object
    horn_d.name = "PA_Horn_Driver"
    horn_d.rotation_euler = mathutils.Euler((math.pi / 2 + rot[0], rot[1], rot[2]))
    _assign_material(horn_d, _get_mat("Speaker_Driver"))
    objs.append(horn_d)
    
    # ── Metal frame/divider between grille sections ──
    divider_z = loc.z + (H - 0.16) * 0.12
    div_loc = loc + front_vec * (D / 2 + 0.03)
    div_loc.z = divider_z
    
    bpy.ops.mesh.primitive_cube_add(size=2, location=div_loc)
    divider = bpy.context.active_object
    divider.name = "PA_Divider"
    divider.scale = ((W - 0.04) / 2, 0.006, 0.008)
    divider.rotation_euler = rot
    _assign_material(divider, frame_mat)
    objs.append(divider)
    
    # ── Trim frame around PA grille (top/bottom bars) ──
    pa_trim_depth = 0.04
    pa_trim_loc = loc + front_vec * (D / 2 + pa_trim_depth / 2)
    
    for z_sign in [-1, 1]:
        bpy.ops.mesh.primitive_cube_add(size=2, location=pa_trim_loc)
        pa_trim = bpy.context.active_object
        pa_trim.name = f"PA_Trim_{z_sign}"
        pa_trim.scale = ((woofer_grille_w + 0.02) / 2, pa_trim_depth / 2, 0.012)
        pa_trim.rotation_euler = rot
        # Top trim at woofer top edge, bottom trim at woofer bottom edge
        trim_z_offset = z_sign * (woofer_grille_h / 2 + 0.015)
        pa_trim.location = pa_trim_loc + _rotate_vec((0, 0, woofer_grille_z - loc.z + trim_z_offset), rot)
        _assign_material(pa_trim, frame_mat)
        objs.append(pa_trim)
    
    # ── Corner protectors (rubber bumpers) ──
    bumper_depth = 0.015
    for z_sign in [-1, 1]:
        bumper_z = z_sign * (H / 2 - 0.02)
        b_loc = loc + front_vec * (D / 2 + bumper_depth / 2) + _rotate_vec((0, 0, bumper_z), rot)
        
        # Round rubber cap (use ico sphere for Blender 5.0 compat)
        bpy.ops.mesh.primitive_ico_sphere_add(
            radius=0.015, subdivisions=1, location=b_loc
        )
        bumper = bpy.context.active_object
        bumper.name = f"PA_Bumper_{z_sign}"
        bumper.scale = (1, 0.5, 1)  # Flatten slightly
        _assign_material(bumper, cab_mat)
        objs.append(bumper)
        
    # ── Handle on top ──
    handle_W = W - 0.08
    handle_minor_r = 0.015
    handle_loc = loc + _rotate_vec((0, 0, 1), rot) * (H / 2 + handle_minor_r)
    
    bpy.ops.mesh.primitive_torus_add(
        major_radius=handle_W / 2, minor_radius=handle_minor_r,
        major_segments=32, minor_segments=8, location=handle_loc
    )
    handle = bpy.context.active_object
    handle.name = "PA_Handle_Top"
    handle.rotation_euler = rot
    _assign_material(handle, grille_mat)
    objs.append(handle)
    
    # ── D-rings (2) with mounting blocks ──
    for side in [-1, 1]:
        # Mounting block on side
        block_loc = loc + _rotate_vec((side * (W / 2 + 0.01), 0, H / 3), rot)
        bpy.ops.mesh.primitive_cube_add(size=2, location=block_loc)
        block = bpy.context.active_object
        block.name = f"PA_MountBlock_{side}"
        block.scale = (0.015, D * 0.4, 0.03)
        block.rotation_euler = rot
        _assign_material(block, frame_mat)
        objs.append(block)
        
        # D-ring
        ring_loc = loc + _rotate_vec((side * (W / 2 + 0.02), -D * 0.15, H / 3), rot)
        bpy.ops.mesh.primitive_torus_add(
            major_radius=0.02, minor_radius=0.005,
            major_segments=8, minor_segments=6, location=ring_loc
        )
        ring = bpy.context.active_object
        ring.name = f"PA_DRing_{side}"
        ring.rotation_euler = rot
        _assign_material(ring, grille_mat)
        objs.append(ring)
    
    return objs


# ──────────────────────────────────────────────
# Material helpers
# ──────────────────────────────────────────────
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


def apply_materials_to_speakers():
    """Apply materials to all speaker objects in the scene."""
    cab_mat = _get_mat("Speaker_Cabinet")
    grille_mat = _get_mat("Speaker_Grille")
    knob_mat = _get_mat("Speaker_Knob")
    driver_mat = _get_mat("Speaker_Driver")
    frame_mat = _get_mat("Speaker_Frame")
    
    for obj in bpy.context.scene.objects:
        if obj.type != 'MESH':
            continue
        
        name_lower = obj.name.lower()
        
        if 'driver' in name_lower or 'tweeter' in name_lower or 'woofer' in name_lower or 'horn' in name_lower:
            if len(obj.data.materials) == 0:
                obj.data.materials.append(driver_mat)
            else:
                obj.data.materials[0] = driver_mat
        elif 'trim' in name_lower or 'divider' in name_lower or 'mountblock' in name_lower or 'bumper' in name_lower:
            if len(obj.data.materials) == 0:
                obj.data.materials.append(frame_mat)
            else:
                obj.data.materials[0] = frame_mat
        elif 'grille' in name_lower or 'wire' in name_lower or 'vent' in name_lower:
            if len(obj.data.materials) == 0:
                obj.data.materials.append(grille_mat)
            else:
                obj.data.materials[0] = grille_mat
        elif 'knob' in name_lower:
            if len(obj.data.materials) == 0:
                obj.data.materials.append(knob_mat)
            else:
                obj.data.materials[0] = knob_mat
        else:
            if len(obj.data.materials) == 0:
                obj.data.materials.append(cab_mat)
            else:
                obj.data.materials[0] = cab_mat


def clear_speaker_objects():
    """Remove all speaker-related objects from the scene."""
    scene = bpy.context.scene
    prefixes = ['GuitarAmp', 'BassAmp', 'Monitor_', 'PA_', 'Guitar_Amp', 'Bass_Amp', 'Floor_Monitor', 'PA_Speaker']
    
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
    
    mat_names = ["Speaker_Cabinet", "Speaker_Grille", "Speaker_Knob", "Speaker_Driver", "Speaker_Frame"]
    for mat_name in mat_names:
        if mat_name in bpy.data.materials:
            bpy.data.materials.remove(bpy.data.materials[mat_name])