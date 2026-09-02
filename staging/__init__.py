# -*- coding: utf-8 -*-
"""staging - Stage modeling package
Integrates truss, stage platform, spotlight, speaker, drum set, and mic stand systems.
"""

from .truss_system import (
    create_truss_frame,
    create_full_stage_truss,
    apply_materials_to_truss,
    clear_truss_objects
)

from .stage_platform import (
    create_stage_platform,
    apply_materials_to_stage,
    clear_stage_objects
)

from .spotlight_system import (
    create_spotlight,
    create_full_lighting_rig,
    apply_materials_to_spotlights,
    clear_spotlight_objects
)

from .speaker_system import (
    create_speaker,
    apply_materials_to_speakers,
    clear_speaker_objects
)

from .drum_set_system import (
    create_full_drum_set,
    apply_materials_to_drum_set,
    clear_drum_set_objects
)

from .mic_stand_system import (
    create_mic_stand,
    create_mic_stands,
    create_vocal_mic,
    create_guitar_pickup_mic,
    create_drum_mic,
    clear_mic_stand_objects
)

from .back_wall import (
    create_back_wall,
    clear_back_wall_objects
)

from .curtain import (
    create_curtain,
    create_stage_curtains,
    clear_curtain_objects
)

from .audience_floor import (
    create_audience_floor,
    clear_audience_floor_objects
)

__all__ = [
    # Truss
    'create_truss_frame',
    'create_full_stage_truss',
    'apply_materials_to_truss',
    'clear_truss_objects',
    # Stage Platform
    'create_stage_platform',
    'apply_materials_to_stage',
    'clear_stage_objects',
    # Spotlight
    'create_spotlight',
    'create_full_lighting_rig',
    'apply_materials_to_spotlights',
    'clear_spotlight_objects',
    # Speaker
    'create_speaker',
    'apply_materials_to_speakers',
    'clear_speaker_objects',
    # Drum Set
    'create_full_drum_set',
    'apply_materials_to_drum_set',
    'clear_drum_set_objects',
    # Mic Stand
    'create_mic_stand',
    'create_mic_stands',
    'create_vocal_mic',
    'create_guitar_pickup_mic',
    'create_drum_mic',
    'clear_mic_stand_objects',
    # Back Wall
    'create_back_wall',
    'clear_back_wall_objects',
    # Curtains
    'create_curtain',
    'create_stage_curtains',
    'clear_curtain_objects',
    # Audience Floor
    'create_audience_floor',
    'clear_audience_floor_objects',
]
