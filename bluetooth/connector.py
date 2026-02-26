"""macOS IOBluetooth RFCOMM connector for Sony WH-1000XM6.

All IOBluetooth operations MUST run on the main thread with an active NSRunLoop.
Protocol details verified via live Bluetooth testing:
  - XM6 uses DataMdr (0x0C) for commands
  - ACK type is always 0x01
  - Sequence numbers alternate 0↔1
  - Bidirectional ACK handshake required
"""

import logging
import re
import time

import objc

# Fix PyObjC metadata BEFORE importing IOBluetooth classes
objc.registerMetaDataForSelector(
    b"IOBluetoothSDPServiceRecord",
    b"getRFCOMMChannelID:",
    {
        "retval": {"type": b"i"},
        "arguments": {2: {"type": b"o^C", "type_modifier": b"o"}},
    },
)
objc.registerMetaDataForSelector(
    b"IOBluetoothDevice",
    b"openRFCOMMChannelAsync:withChannelID:delegate:",
    {
        "retval": {"type": b"i"},
        "arguments": {
            2: {"type": b"o^@", "type_modifier": b"o"},
            3: {"type": b"C"},
            4: {"type": b"@"},
        },
    },
)

from Foundation import NSObject, NSRunLoop, NSDate  # noqa: E402
from IOBluetooth import (  # noqa: E402
    IOBluetoothDevice,
    IOBluetoothRFCOMMChannel,
    IOBluetoothSDPUUID,
)

from protocol.codec import (  # noqa: E402
    Message,
    extract_message,
    pack,
)
from protocol.constants import DataType, CommandType  # noqa: E402

log = logging.getLogger(__name__)

# V2 UUID — works with XM4+, XM5, XM6
SERVICE_UUID_V2 = bytes([
    0x95, 0x6C, 0x7B, 0x26, 0xD4, 0x9A, 0x4B, 0xA8,
    0xB0, 0x3F, 0xB1, 0x7D, 0x39, 0x3C, 0xB6, 0xE2,
])
# V1 UUID — older devices (XM3, early XM4)
SERVICE_UUID_V1 = bytes([
    0x96, 0xCC, 0x20, 0x3E, 0x50, 0x68, 0x46, 0xAD,
    0xB3, 0x2D, 0xE3, 0x16, 0xF5, 0xE0, 0x69, 0xBA,
])

FALLBACK_RFCOMM_CHANNEL = 9


def _build_ack_packet(seq: int) -> bytes:
    """Build a raw ACK packet (type=0x01, no payload)."""
    inner = bytes([DataType.ACK, seq, 0, 0, 0, 0])
    chk = sum(inner) & 0xFF
    return bytes([0x3E]) + inner + bytes([chk]) + bytes([0x3C])


class RFCOMMDelegate(NSObject):
    """Objective-C delegate for IOBluetoothRFCOMMChannel callbacks."""

    def initWithConnector_(self, connector):
        self = objc.super(RFCOMMDelegate, self).init()
        if self is None:
            return None
        self.connector = connector
        return self

    def rfcommChannelData_data_length_(self, channel, data, length):
        raw = bytes(data[:length])
        self.connector._on_data_received(raw)

    def rfcommChannelClosed_(self, channel):
        log.warning("RFCOMM channel closed by remote device")
        self.connector._on_disconnected()

    def rfcommChannelOpenComplete_status_(self, channel, status):
        log.info("RFCOMM channel open complete, status: %d", status)


class SonyBluetoothConnector:
    """Manages Bluetooth RFCOMM connection to Sony headphones.

    ALL public methods must be called from the main thread (via run_on_main).
    """

    def __init__(self):
        self.seq_number: int = 0
        self.device: IOBluetoothDevice | None = None
        self.channel: IOBluetoothRFCOMMChannel | None = None
        self.delegate: RFCOMMDelegate | None = None
        self._recv_buffer = bytearray()
        self._pending_responses: list[Message] = []
        self._connected = False

        # Cached state
        self.battery_level: int = -1
        self.battery_charging: bool = False
        self.anc_mode: str = "unknown"
        self.volume_level: int = -1
        self.dsee_enabled: bool = False
        self.speak_to_chat_enabled: bool = False

    @property
    def connected(self) -> bool:
        return self._connected

    def discover_sony_devices(self) -> list[dict]:
        devices = IOBluetoothDevice.pairedDevices()
        if not devices:
            return []
        results = []
        for dev in devices:
            name = dev.name()
            if name and "WH-1000XM" in name:
                results.append({
                    "name": str(name),
                    "address": str(dev.addressString()),
                })
        return results

    def _find_rfcomm_channel(self) -> int | None:
        for uuid_bytes in (SERVICE_UUID_V2, SERVICE_UUID_V1):
            uuid_obj = IOBluetoothSDPUUID.uuidWithBytes_length_(uuid_bytes, 16)
            record = self.device.getServiceRecordForUUID_(uuid_obj)
            if record is not None:
                io_ret, channel_id = record.getRFCOMMChannelID_(None)
                if io_ret == 0:
                    log.info("Found RFCOMM channel %d via UUID", channel_id)
                    return channel_id

        log.warning("UUID lookup failed, scanning SDP records")
        records = self.device.services()
        if records:
            for rec in records:
                proto = rec.getAttributeDataElement_(0x0004)
                svc_class = rec.getAttributeDataElement_(0x0001)
                if proto is None or svc_class is None:
                    continue
                proto_str = str(proto)
                svc_str = str(svc_class)
                if "uuid128" in svc_str and "uuid32(00 00 00 03)" in proto_str:
                    m = re.search(
                        r"uuid32\(00 00 00 03\),\s*uint32\((\d+)\)", proto_str
                    )
                    if m:
                        channel_id = int(m.group(1))
                        log.info("Found RFCOMM channel %d via SDP scan", channel_id)
                        return channel_id

        log.warning("Using fallback RFCOMM channel %d", FALLBACK_RFCOMM_CHANNEL)
        return FALLBACK_RFCOMM_CHANNEL

    def connect(self, address: str) -> bool:
        if self._connected:
            return True

        # Clean up any leftover state from previous connection
        if self.channel:
            try:
                self.channel.closeChannel()
            except Exception:
                pass
            self.channel = None
        if self.device:
            try:
                self.device.closeConnection()
            except Exception:
                pass
            self.device = None
        self.delegate = None

        log.info("Connecting to %s ...", address)
        self.device = IOBluetoothDevice.deviceWithAddressString_(address)
        if self.device is None:
            log.error("Device not found: %s", address)
            return False

        result = self.device.performSDPQuery_(None)
        if result != 0:
            log.error("SDP query failed: %d", result)
            return False

        for _ in range(30):
            NSRunLoop.currentRunLoop().runUntilDate_(
                NSDate.dateWithTimeIntervalSinceNow_(0.1)
            )

        channel_id = self._find_rfcomm_channel()
        if channel_id is None:
            log.error("Could not determine RFCOMM channel")
            return False

        self.delegate = RFCOMMDelegate.alloc().initWithConnector_(self)
        result, self.channel = self.device.openRFCOMMChannelAsync_withChannelID_delegate_(
            None, channel_id, self.delegate
        )
        if result != 0:
            log.error("Failed to open RFCOMM channel %d: %d", channel_id, result)
            return False

        for _ in range(50):
            NSRunLoop.currentRunLoop().runUntilDate_(
                NSDate.dateWithTimeIntervalSinceNow_(0.1)
            )
            if self.channel and self.channel.isOpen():
                break

        if not self.channel or not self.channel.isOpen():
            log.error("RFCOMM channel did not open in time")
            return False

        self._connected = True
        self.seq_number = 0
        self._recv_buffer.clear()
        self._pending_responses.clear()

        # Drain initial notifications
        for _ in range(20):
            NSRunLoop.currentRunLoop().runUntilDate_(
                NSDate.dateWithTimeIntervalSinceNow_(0.05)
            )
        self._pending_responses.clear()

        # Protocol initialization handshake
        log.info("Sending init handshake...")
        init1 = self.send_command(bytes([0x00, 0x00]), timeout=2.0)
        if init1:
            log.info("Init1 (ProtocolInfo): cmd=0x%02X", init1.payload[0] if init1.payload else 0)
        init2 = self.send_command(bytes([0x06, 0x00]), timeout=2.0)
        if init2:
            log.info("Init2 (SupportFunc): cmd=0x%02X", init2.payload[0] if init2.payload else 0)

        log.info("Connected to %s on RFCOMM channel %d", address, channel_id)
        return True

    def disconnect(self):
        if self.channel:
            self.channel.closeChannel()
            self.channel = None
        if self.device:
            self.device.closeConnection()
            self.device = None
        self._connected = False
        self.delegate = None
        self._recv_buffer.clear()
        self._pending_responses.clear()
        log.info("Disconnected")

    def send_command(self, payload: bytes, timeout: float = 3.0) -> Message | None:
        """Send a command and wait for the matching response.

        Uses DataMdr (0x0C) for XM6. Polls NSRunLoop for delegate callbacks.
        Filters responses by expected command byte.
        """
        if not self._connected or not self.channel:
            return None

        seq = self.seq_number
        packet = pack(DataType.DATA_MDR, seq, payload)

        self._pending_responses.clear()

        request_cmd = payload[0]
        expected_cmds = {request_cmd, (request_cmd + 1) & 0xFF}

        log.info("TX [seq=%d cmd=0x%02X]", seq, request_cmd)
        result = self.channel.writeSync_length_(packet, len(packet))
        if result != 0:
            log.error("RFCOMM write failed: %d", result)
            return None

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            NSRunLoop.currentRunLoop().runUntilDate_(
                NSDate.dateWithTimeIntervalSinceNow_(0.05)
            )
            for i, resp in enumerate(self._pending_responses):
                if resp.payload and resp.payload[0] in expected_cmds:
                    self._pending_responses.pop(i)
                    log.info(
                        "RX [cmd=0x%02X]: %s",
                        resp.payload[0], resp.payload.hex(),
                    )
                    return resp

        log.warning("Response timeout [seq=%d cmd=0x%02X]", seq, request_cmd)
        return None

    def _on_data_received(self, data: bytes):
        self._recv_buffer.extend(data)

        while True:
            msg, remaining = extract_message(bytes(self._recv_buffer))
            self._recv_buffer = bytearray(remaining)
            if msg is None:
                break

            if msg.data_type == DataType.ACK:
                # ACK from device — send bidirectional ACK back and update seq
                next_seq = 1 - msg.seq if msg.seq <= 1 else 0
                ack = _build_ack_packet(next_seq)
                if self.channel:
                    self.channel.writeSync_length_(ack, len(ack))
                self.seq_number = msg.seq
                log.debug("ACK seq=%d, next_cmd_seq=%d", msg.seq, msg.seq)
            else:
                # Data packet — ACK it and queue for processing
                next_seq = 1 - msg.seq if msg.seq <= 1 else 0
                ack = _build_ack_packet(next_seq)
                if self.channel:
                    self.channel.writeSync_length_(ack, len(ack))

                self._process_notification(msg)
                self._pending_responses.append(msg)

    def _process_notification(self, msg: Message):
        if not msg.payload:
            return

        cmd = msg.payload[0]

        if cmd in (CommandType.BATTERY_RET,):
            # 0x23: payload[2]=level, payload[3]=charging
            if len(msg.payload) >= 4:
                self.battery_level = msg.payload[2]
                self.battery_charging = bool(msg.payload[3])
                log.info("Battery: %d%%, charging=%s", self.battery_level, self.battery_charging)

        elif cmd in (CommandType.NC_ASM_RET, CommandType.NC_ASM_NOTIFY):
            # 0x67/0x69: XM6 response format verified from HCI:
            #   NC ON:  69 19 01 [01] [00] [00] 14 00 00  (enable=1, asm=0)
            #   ASM ON: 69 19 01 [01] [01] [00] 0f 00 00  (enable=1, asm=1)
            #   OFF:    69 19 01 [00] [00] [00] 14 00 00  (enable=0)
            # NC is inferred: enable=1 and asm=0 means NC mode
            if len(msg.payload) >= 5:
                enable = bool(msg.payload[3])
                asm_on = bool(msg.payload[4])
                if enable and not asm_on:
                    self.anc_mode = "nc"
                elif enable and asm_on:
                    self.anc_mode = "ambient"
                else:
                    self.anc_mode = "off"
                log.info("ANC: %s", self.anc_mode)

        elif cmd in (CommandType.PLAY_RET_PARAM, 0xA9):
            # 0xA7/0xA9: payload[2]=volume
            if len(msg.payload) >= 3:
                self.volume_level = msg.payload[2]
                log.info("Volume: %d", self.volume_level)

        elif cmd in (CommandType.DSEE_RET, CommandType.DSEE_NOTIFY):
            # 0xE7/0xE9: payload[2]=enabled
            if len(msg.payload) >= 3:
                self.dsee_enabled = bool(msg.payload[2])
                log.info("DSEE: %s", self.dsee_enabled)

        elif cmd in (CommandType.SPEAK_TO_CHAT_RET, CommandType.SPEAK_TO_CHAT_NOTIFY):
            # 0xF7/0xF9: payload[2]=enabled
            if len(msg.payload) >= 3:
                self.speak_to_chat_enabled = bool(msg.payload[2])
                log.info("Speak-to-Chat: %s", self.speak_to_chat_enabled)

    def _on_disconnected(self):
        self._connected = False
        self.channel = None
        self.device = None
        self.delegate = None
        self._recv_buffer.clear()
        self._pending_responses.clear()
