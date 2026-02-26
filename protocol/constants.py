"""Sony headphone protocol constants — XM6 verified via live testing."""

from enum import IntEnum

# --- Framing bytes ---
START_MARKER = 0x3E  # '>'
END_MARKER = 0x3C    # '<'
ESCAPE_BYTE = 0x3D   # '='

# Escape map: byte -> (ESCAPE_BYTE, replacement)
ESCAPE_MAP = {
    0x3C: 0x2C,  # END_MARKER   -> (0x3D, 0x2C)
    0x3D: 0x2D,  # ESCAPE_BYTE  -> (0x3D, 0x2D)
    0x3E: 0x2E,  # START_MARKER -> (0x3D, 0x2E)
}

# Reverse map for unescaping
UNESCAPE_MAP = {v: k for k, v in ESCAPE_MAP.items()}


class DataType(IntEnum):
    """Packet data types."""
    DATA = 0x00
    ACK = 0x01
    DATA_MDR = 0x0C      # Used by XM6 for commands and notifications
    DATA_COMMON = 0x0D
    DATA_MDR_NO2 = 0x0E  # Used by XM5


class CommandType(IntEnum):
    """Command opcodes sent in payload."""
    # Battery
    BATTERY_GET_LEVEL = 0x12   # XM6: inquiry_type=0x01 for single battery
    BATTERY_NOTIFY = 0x13
    BATTERY_GET = 0x22         # XM6: returns level + charging as bytes
    BATTERY_RET = 0x23

    # NC / Ambient Sound
    NC_ASM_GET = 0x66
    NC_ASM_RET = 0x67
    NC_ASM_SET = 0x68
    NC_ASM_NOTIFY = 0x69

    # EQ
    EQ_GET = 0x56
    EQ_RET = 0x57
    EQ_SET = 0x58
    EQ_NOTIFY = 0x59

    # Playback
    PLAY_GET_STATUS = 0xA2
    PLAY_RET_STATUS = 0xA3
    PLAY_SET_STATUS = 0xA4
    PLAY_GET_PARAM = 0xA6     # Volume GET
    PLAY_RET_PARAM = 0xA7     # Volume response
    PLAY_SET_PARAM = 0xA8     # Volume SET

    # DSEE
    DSEE_GET = 0xE6
    DSEE_RET = 0xE7
    DSEE_SET = 0xE8
    DSEE_NOTIFY = 0xE9

    # Speak-to-Chat
    SPEAK_TO_CHAT_GET = 0xF6
    SPEAK_TO_CHAT_RET = 0xF7
    SPEAK_TO_CHAT_SET = 0xF8
    SPEAK_TO_CHAT_NOTIFY = 0xF9


class NcAsmInquiredType(IntEnum):
    """Device-specific NC/ASM identifier."""
    V1_V2 = 0x02
    XM5 = 0x17
    XM6 = 0x19


class EqPreset(IntEnum):
    """Equalizer preset IDs."""
    OFF = 0x00
    ROCK = 0x01
    POP = 0x02
    JAZZ = 0x03
    DANCE = 0x04
    EDM = 0x05
    R_AND_B = 0x06
    HIP_HOP = 0x07
    ACOUSTIC = 0x08
    BRIGHT = 0x10
    EXCITED = 0x11
    MELLOW = 0x12
    RELAXED = 0x13
    VOCAL = 0x14
    TREBLE = 0x15
    BASS = 0x16
    SPEECH = 0x17


class AncMode(IntEnum):
    """High-level ANC mode."""
    OFF = 0
    NOISE_CANCELLING = 1
    AMBIENT_SOUND = 2


class PlaybackControl(IntEnum):
    """Playback control actions."""
    PAUSE = 0x01
    TRACK_UP = 0x02
    TRACK_DOWN = 0x03
    PLAY = 0x07


class PlayInquiredType(IntEnum):
    """Playback sub-types."""
    PLAYBACK_CONTROL = 0x01
    MUSIC_VOLUME = 0x20


# Human-readable maps for API
EQ_PRESET_NAMES = {
    "off": EqPreset.OFF,
    "rock": EqPreset.ROCK,
    "pop": EqPreset.POP,
    "jazz": EqPreset.JAZZ,
    "dance": EqPreset.DANCE,
    "edm": EqPreset.EDM,
    "r_and_b": EqPreset.R_AND_B,
    "hip_hop": EqPreset.HIP_HOP,
    "acoustic": EqPreset.ACOUSTIC,
    "bright": EqPreset.BRIGHT,
    "excited": EqPreset.EXCITED,
    "mellow": EqPreset.MELLOW,
    "relaxed": EqPreset.RELAXED,
    "vocal": EqPreset.VOCAL,
    "treble": EqPreset.TREBLE,
    "bass": EqPreset.BASS,
    "speech": EqPreset.SPEECH,
}

ANC_MODE_NAMES = {
    "off": AncMode.OFF,
    "nc": AncMode.NOISE_CANCELLING,
    "ambient": AncMode.AMBIENT_SOUND,
}
