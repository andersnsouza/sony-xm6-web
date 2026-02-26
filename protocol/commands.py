"""Sony WH-1000XM6 command builders — verified via live Bluetooth testing.

Each function returns a payload (bytes) to be wrapped with codec.pack().
"""

from .constants import (
    AncMode,
    CommandType,
    EqPreset,
    NcAsmInquiredType,
    PlaybackControl,
    PlayInquiredType,
)


# --- ANC / Ambient Sound ---

def build_nc_asm_xm6(
    nc_on: bool,
    asm_on: bool,
    asm_level: int = 0x14,
    focus_voice: bool = False,
) -> bytes:
    """Build NC/ASM command for XM6.

    Verified payload from HCI traffic capture:
      NC ON:  68:19:01:01:00:01:14:00:00
      ASM ON: 68:19:01:01:01:00:0A:00:00
      OFF:    68:19:01:00:00:00:14:00:00
    """
    enable = 0x01 if (nc_on or asm_on) else 0x00
    level = max(0, min(20, asm_level))
    return bytes([
        CommandType.NC_ASM_SET,         # 0x68
        NcAsmInquiredType.XM6,          # 0x19
        0x01,                           # sub-command
        enable,
        0x01 if asm_on else 0x00,       # ASM mode
        0x01 if nc_on else 0x00,        # NC mode
        level,
        0x01 if focus_voice else 0x00,
        0x00,                           # reserved
    ])


def build_anc_command_xm6(
    mode: AncMode,
    asm_level: int = 10,
    focus_voice: bool = False,
) -> bytes:
    """High-level ANC mode setter for XM6."""
    if mode == AncMode.NOISE_CANCELLING:
        return build_nc_asm_xm6(nc_on=True, asm_on=False)
    elif mode == AncMode.AMBIENT_SOUND:
        return build_nc_asm_xm6(
            nc_on=False, asm_on=True,
            asm_level=asm_level, focus_voice=focus_voice,
        )
    else:
        return build_nc_asm_xm6(nc_on=False, asm_on=False)


def build_nc_asm_get() -> bytes:
    """Request current NC/ASM status. Response: cmd=0x67."""
    return bytes([CommandType.NC_ASM_GET, NcAsmInquiredType.XM6])


# --- Battery ---

def build_battery_inquiry() -> bytes:
    """Request battery level. Response: cmd=0x23, payload[2]=level, payload[3]=charging."""
    return bytes([CommandType.BATTERY_GET, 0x00])


# --- Equalizer ---

def build_eq_preset(preset: EqPreset) -> bytes:
    """Set EQ to a built-in preset."""
    return bytes([CommandType.EQ_SET, 0x01, int(preset)])


# --- Volume ---

def build_volume_set(level: int) -> bytes:
    """Set volume level (0-30)."""
    return bytes([
        CommandType.PLAY_SET_PARAM,
        PlayInquiredType.MUSIC_VOLUME,
        max(0, min(30, level)),
    ])


def build_volume_get() -> bytes:
    """Request current volume. Response: cmd=0xA7, payload[2]=level."""
    return bytes([CommandType.PLAY_GET_PARAM, PlayInquiredType.MUSIC_VOLUME])


# --- DSEE (upscaling) ---

def build_dsee_set(enabled: bool) -> bytes:
    """Enable/disable DSEE HX audio upscaling."""
    return bytes([CommandType.DSEE_SET, 0x01, int(enabled)])


def build_dsee_get() -> bytes:
    """Request current DSEE state. Response: cmd=0xE7, payload[2]=enabled."""
    return bytes([CommandType.DSEE_GET, 0x01])


# --- Speak-to-Chat ---

def build_speak_to_chat_set(enabled: bool) -> bytes:
    """Enable/disable Speak-to-Chat feature."""
    return bytes([
        CommandType.SPEAK_TO_CHAT_SET,
        0x02,
        int(enabled),
        0x01,  # sensitivity (HIGH)
        0x01,  # timeout (MID ~15s)
    ])


def build_speak_to_chat_get() -> bytes:
    """Request Speak-to-Chat state. Response: cmd=0xF7."""
    return bytes([CommandType.SPEAK_TO_CHAT_GET, 0x02])


# --- Playback ---

def build_playback_control(control: PlaybackControl) -> bytes:
    """Send a playback control command."""
    return bytes([
        CommandType.PLAY_SET_STATUS,
        PlayInquiredType.PLAYBACK_CONTROL,
        int(control),
    ])


def build_play() -> bytes:
    return build_playback_control(PlaybackControl.PLAY)


def build_pause() -> bytes:
    return build_playback_control(PlaybackControl.PAUSE)


def build_next() -> bytes:
    return build_playback_control(PlaybackControl.TRACK_UP)


def build_prev() -> bytes:
    return build_playback_control(PlaybackControl.TRACK_DOWN)
