import asyncio
import contextlib
import enum
import logging
import struct
import typing as ty

import google.protobuf.message

from .proto import Act_pb2 as act_pb

ResponseHandler = ty.Callable[[act_pb.Response], None]

ActConnectionToStrFunc = ty.Callable[['ActConnection'], str]


class ActConnectionState(str, enum.Enum):
    Unknown = "Unknown",
    Connecting = "Connecting",
    Connected = "Connected",
    Disconnected = "Disconnected"


ErrMsg = str
NewState = ActConnectionState
OldState = ActConnectionState
StateChangeHandler = ty.Callable[['ActConnection', NewState, ErrMsg, OldState], None]

IncomingDataInspector = ty.Callable[[bytes], None]
OutgoingDataInspector = ty.Callable[[bytes], None]


class ActConnection(asyncio.Protocol):
    def __init__(self, ip: str, port: int, loop: asyncio.AbstractEventLoop):
        self.ip = ip
        self.port = port
        self.loop = loop
        self.on_response: ty.Optional[ResponseHandler] = None
        self.on_connected: asyncio.Future = loop.create_future()
        self.on_connection_lost: asyncio.Future = loop.create_future()
        self.transport: ty.Optional[asyncio.Transport] = None
        self._logger = logging.getLogger(__name__)
        self.received_data: bytearray = bytearray()
        self.state = ActConnectionState.Unknown
        self.err_msg: ty.Optional[str] = None
        self._state_change_handlers: ty.List[StateChangeHandler] = []
        self.to_str_func: ty.Optional[ActConnectionToStrFunc] = None
        self._pending_futures: ty.Optional[ty.Set[asyncio.Future]] = None
        self._outgoing_data_inspectors: ty.List[OutgoingDataInspector] = []
        self._incoming_data_inspectors: ty.List[IncomingDataInspector] = []

    def set_to_str_func(self, to_str_func: ty.Optional[ActConnectionToStrFunc] = None):
        self.to_str_func = to_str_func

    def __str__(self):
        if self.to_str_func is not None:
            return self.to_str_func(self)
        return f'{self.ip}:{self.port}'

    def is_connected(self) -> bool:
        return self.state == ActConnectionState.Connected

    def add_state_change_handler(self, state_change_handler: StateChangeHandler):
        self._state_change_handlers.append(state_change_handler)

    async def connect(self):
        self._set_state(new_state=ActConnectionState.Connecting)
        try:
            self._logger.info(f'Connecting to {self}')
            self.transport, protocol = await self.loop.create_connection(protocol_factory=lambda: self, host=self.ip, port=self.port)
            done, self._pending_futures = await asyncio.wait(fs=(self.on_connected, self.on_connection_lost), return_when=asyncio.FIRST_COMPLETED)
        except OSError as err:
            self._logger.error(f'Failed to connect: {err}')
            self.on_connection_lost.set_result(False)

    async def wait_on_disconnect(self):
        with contextlib.suppress(asyncio.exceptions.CancelledError):
            await self.on_connection_lost

    def disconnect(self):
        self._set_state(new_state=ActConnectionState.Disconnected)
        if self.transport is not None:
            self._logger.info(f'Disconnecting from {self}')
            self.transport.close()
            self.transport = None
        if self.on_connection_lost.cancelled():
            return
        with contextlib.suppress(asyncio.exceptions.CancelledError):
            self.on_connection_lost.cancel()

    def set_response_handler(self, on_response: ResponseHandler):
        self.on_response = on_response

    def connection_made(self, transport: asyncio.Transport):
        self._logger.info(f'Connected to {self}')
        self.transport = transport
        self._set_state(new_state=ActConnectionState.Connected)
        self.on_connected.set_result(True)

    def connection_lost(self, exc):
        self._logger.info(f'Disconnected from {self}')
        self._set_state(new_state=ActConnectionState.Disconnected)
        self.on_connection_lost.set_result(True)

    def send_request(self, request: act_pb.Request) -> bool:
        if self.transport is None:
            logging.warning(f'Not connected, no transport')
            return False
        if self.on_response is None:
            logging.warning(f'No response handler set, ignoring send request')
            return False
        msg_data = request.SerializeToString()
        packed_len = struct.pack('<L', len(msg_data))  # little-endian, long
        data = packed_len + msg_data
        for outgoing_data_inspector in self._outgoing_data_inspectors:
            outgoing_data_inspector(data)
        self.transport.write(data)
        return True

    def data_received(self, data: bytes):
        for incoming_data_inspector in self._incoming_data_inspectors:
            incoming_data_inspector(data)
        self.received_data += bytearray(data)
        while True:
            received_len = len(self.received_data)
            if received_len < 4:
                return
            msg_len: int = struct.unpack('<L', self.received_data[0:4])[0]
            if received_len < msg_len + 4:
                return
            try:
                response = act_pb.Response()
                msg_data = bytes(self.received_data[4:msg_len + 4])
                response.ParseFromString(msg_data)
                self.received_data = self.received_data[msg_len + 4:]
                self.on_response(response)
            except google.protobuf.message.DecodeError:
                logging.exception(f'exception decoding message')

    def add_inspectors(self, incoming_data_inspector: ty.Optional[IncomingDataInspector], outgoing_data_inspector: ty.Optional[OutgoingDataInspector]):
        """ Functions to call on incoming data or outgoing data """
        if incoming_data_inspector is not None:
            self._incoming_data_inspectors.append(incoming_data_inspector)
        if outgoing_data_inspector is not None:
            self._outgoing_data_inspectors.append(outgoing_data_inspector)

    def remove_inspectors(self, incoming_data_inspector: ty.Optional[IncomingDataInspector], outgoing_data_inspector: ty.Optional[OutgoingDataInspector]):
        if incoming_data_inspector in self._incoming_data_inspectors:
            self._incoming_data_inspectors.remove(incoming_data_inspector)
        if outgoing_data_inspector in self._outgoing_data_inspectors:
            self._outgoing_data_inspectors.remove(outgoing_data_inspector)

    def _set_state(self, new_state: ActConnectionState, err_msg: ty.Optional[str] = None):
        if new_state == self.state:
            return
        old_state = self.state
        self.state = new_state
        self.err_msg = err_msg
        for state_handler in self._state_change_handlers:
            state_handler(self, self.state, self.err_msg, old_state)
