from __future__ import annotations

import asyncio
import collections
import dataclasses
import enum
import logging
import typing as ty

from . import connection
from .proto import ActAlgo_pb2 as algo_pb
from .proto import ActAutoControl_pb2 as autocontrol_pb
from .proto import ActTypes_pb2 as act_types_pb
from .proto import Act_pb2 as act_pb
from .proto import DataExchangeAPI_pb2 as dex_pb
from .util import util


def has_error(op_status: act_types_pb.OperationStatus) -> bool:
    return op_status.errorMessage is not None and len(op_status.errorMessage) > 0


def _get_error(op_status: act_types_pb.OperationStatus) -> ty.Optional[str]:
    """ Turn empty string error message into None """
    if has_error(op_status):
        return op_status.errorMessage
    return None


def log_any_error(msg: str, op_status: act_types_pb.OperationStatus) -> bool:
    if not has_error(op_status=op_status):
        return False
    logger = logging.getLogger(__name__)
    logger.error(f'Error response. {msg}, Msg:"{op_status.errorMessage}"')
    return True


@dataclasses.dataclass(unsafe_hash=True)
class StrProperty:
    name: str
    value: str

    def to_proto(self) -> act_types_pb.Property:
        property = act_types_pb.Property()
        property.name = self.name
        property.value = self.value
        return property


@dataclasses.dataclass(unsafe_hash=True)
class ServerConnection:
    name: str
    status: act_pb.ConnectionStatus


LogonResponse = collections.namedtuple('LogonResponse', 'Success ErrorMsg ActLoginResponse')

ActSessionToStrFunc = ty.Callable[['ActSession'], str]

RequestInspector = ty.Callable[[act_pb.Request], None]
ResponseInspector = ty.Callable[[act_pb.Response], None]


class ActSession(object):
    def __init__(self, act_connection: connection.ActConnection, user: str, password: str, appname: str,
                 failure_actions: ty.Optional[ty.List[act_pb.FailureAction]] = None,
                 session_options: ty.Optional[ty.List[act_pb.SessionOption]] = None,
                 client_properties: ty.Optional[ty.List[StrProperty]] = None,
                 ):
        self.act_connection: connection.ActConnection = act_connection
        self._logger = logging.getLogger(__name__)
        self.user = user
        self.password = password
        self.appname = appname
        self.failure_actions = failure_actions
        self.session_options = session_options
        self.client_properties = client_properties
        self._handlers: ty.Dict[act_pb.SubProtocolType, connection.ResponseHandler] = dict()
        self.session_id: int = 0
        self.to_str_func: ty.Optional[ActSessionToStrFunc] = None
        self.session_properties: ty.List[StrProperty] = []
        self.server_connections: ty.List[ServerConnection] = []
        self._request_inspectors: ty.List[RequestInspector] = []
        self._response_inspectors: ty.List[ResponseInspector] = []
        self.act_connection.set_response_handler(on_response=self.on_response)
        self.act_sub_session = ActSubSession(act_session=self)
        self.dex_sub_session = DexSubSession(act_session=self)
        self.autocontrol_sub_session = AutoControlSubSession(act_session=self)
        self.algo_sub_session = AlgoSubSession(act_session=self)

    def set_to_str_func(self, to_str_func: ty.Optional[ActSessionToStrFunc] = None):
        self.to_str_func = to_str_func

    def __str__(self):
        if self.to_str_func is not None:
            return self.to_str_func(self)
        return f'({self.act_connection}:{self.session_id}:{self.user})'

    async def logon(self) -> LogonResponse:
        return await self.act_sub_session.logon(user=self.user, password=self.password, appname=self.appname)

    def logout(self):
        self.act_sub_session.logout()
        self.act_connection.disconnect()

    def add_sub_session_handler(self, sub_protocol_type: act_pb.SubProtocolType, handler: connection.ResponseHandler) -> None:
        # self._logger.info(f'adding handler for sub-protocol {sub_protocol_type}')
        self._handlers[sub_protocol_type] = handler

    def add_inspectors(self, request_inspector: ty.Optional[RequestInspector], response_inspector: ty.Optional[ResponseInspector]):
        """ Functions to call on every request or response """
        if request_inspector is not None:
            self._request_inspectors.append(request_inspector)
        if response_inspector is not None:
            self._response_inspectors.append(response_inspector)

    def remove_inspectors(self, request_inspector: ty.Optional[RequestInspector], response_inspector: ty.Optional[ResponseInspector]):
        if request_inspector in self._request_inspectors:
            self._request_inspectors.remove(request_inspector)
        if response_inspector is self._response_inspectors:
            self._response_inspectors.remove(response_inspector)

    def send_request(self, request: act_pb.Request) -> None:
        # self._logger.info(f'sending sub-protocol {request.subProtocolType} request')
        for request_inspector in self._request_inspectors:
            request_inspector(request)
        self.act_connection.send_request(request=request)

    def on_response(self, response: act_pb.Response):
        for response_inspector in self._response_inspectors:
            response_inspector(response)
        sub_protocol_type = response.subProtocolType
        # self._logger.info(f'received sub-protocol {sub_protocol_type} response')
        if sub_protocol_type in self._handlers:
            self._handlers[sub_protocol_type](response)
        else:
            self._logger.warning(f'sub protocol type {sub_protocol_type} responses not handled')


class InspectorHelper(object):
    """ Helper class for adding & removing request/response inspectors on the session and incoming data/outgoing data inspectors on the connection """

    def __init__(self, act_session: ActSession) -> None:
        self.act_session = act_session
        self._logger = logging.getLogger(__name__)
        self._started = False
        self.request_inspector: ty.Optional[RequestInspector] = None
        self.response_inspector: ty.Optional[ResponseInspector] = None
        self.incoming_data_inspector: ty.Optional[connection.IncomingDataInspector] = None
        self.outgoing_data_inspector: ty.Optional[connection.OutgoingDataInspector] = None

    def start(self, inspect_requests=False, inspect_responses=False, inspect_incoming_data=False, inspect_outgoing_data=False):
        if self._started:
            self.stop()
        self.request_inspector = util.log_requests if inspect_requests else None
        self.response_inspector = util.log_responses if inspect_responses else None
        self.incoming_data_inspector = util.log_incoming_data if inspect_incoming_data else None
        self.outgoing_data_inspector = util.log_outgoing_data if inspect_outgoing_data else None
        self._started = True
        self._logger.info(f'Starting inspection. Requests:{inspect_requests}, Responses:{inspect_responses}, Incoming Data:{inspect_incoming_data}, Outgoing Data:{inspect_outgoing_data}')
        self.act_session.add_inspectors(request_inspector=self.request_inspector, response_inspector=self.response_inspector)
        self.act_session.act_connection.add_inspectors(outgoing_data_inspector=self.outgoing_data_inspector, incoming_data_inspector=self.incoming_data_inspector)

    def stop(self):
        self._started = False
        self._logger.info(f'Stopping inspection')
        self.act_session.remove_inspectors(request_inspector=self.request_inspector, response_inspector=self.response_inspector)
        self.act_session.act_connection.remove_inspectors(outgoing_data_inspector=self.outgoing_data_inspector, incoming_data_inspector=self.incoming_data_inspector)
        self.request_inspector = None
        self.response_inspector = None
        self.incoming_data_inspector = None
        self.outgoing_data_inspector = None


# Act sub-session
class ActSubSession(object):
    def __init__(self, act_session: ActSession):
        self.session: ActSession = act_session
        self._logger = logging.getLogger(__name__)
        self._sub_proto_type = act_pb.SUB_PROTO_ACT
        self.on_logon_response: ty.Optional[asyncio.Future] = None
        self.on_logon_error: ty.Optional[str] = None
        self.on_logon_data: ty.Optional[act_pb.ActLoginResponse] = None
        self.session.add_sub_session_handler(sub_protocol_type=self._sub_proto_type, handler=self.on_act_response)

    async def logon(self, user: str, password: str, appname: str,
                    failure_actions: ty.Optional[ty.List[act_pb.FailureAction]] = None,
                    session_options: ty.Optional[ty.List[act_pb.SessionOption]] = None,
                    client_properties: ty.Optional[ty.List[StrProperty]] = None,
                    ) -> LogonResponse:
        login_request = act_pb.ActLoginRequest()
        login_request.username = user
        login_request.password = password
        login_request.appname = appname

        if failure_actions is not None:
            login_request.failureActions.extend(failure_actions)

        if session_options is not None:
            login_request.sessionOptions.extend(session_options)

        if client_properties is not None:
            for client_property in client_properties:
                login_request.clientProperties.append(client_property.to_proto())

        act_request = act_pb.ActRequest()
        act_request.requestType = act_pb.REQ_LOGIN
        act_request.clientId = 0
        act_request.loginRequest.CopyFrom(login_request)

        self._logger.info(f'Logging in as user "{user}" and app "{appname}"')
        self._send_request(act_request=act_request)
        self.on_logon_response = asyncio.get_running_loop().create_future()
        await self.on_logon_response
        return LogonResponse(self.on_logon_error is None, self.on_logon_error, self.on_logon_data)

    def logout(self):
        act_request = act_pb.ActRequest()
        act_request.requestType = act_pb.REQ_LOGOUT
        act_request.clientId = 0

        self._logger.info(f'Logging off')
        self._send_request(act_request=act_request)

    def _send_request(self, act_request: act_pb.Request):
        request = act_pb.Request()
        request.subProtocolType = self._sub_proto_type
        request.actRequest.CopyFrom(act_request)
        self.session.send_request(request=request)

    def on_act_response(self, response: act_pb.Response):
        act_response = response.actResponse
        if act_response is None:
            self._logger.error(f'Got empty act sub-protocol response')
            return

        response_type = act_response.responseType
        if response_type == act_pb.RESP_LOGIN:
            if log_any_error("login response", act_response.operationStatus):
                self.on_logon_error = act_response.operationStatus.errorMessage
                self.on_logon_response.set_result(True)
                return
            login_response = act_response.loginResponse
            if login_response is None:
                self.on_logon_error = f'No logon response'
                self.on_logon_response.set_result(True)
                return
            self.session.session_id = act_response.sessionId
            self._logger.info(f'Logged in on {self.session.act_connection} as {login_response.User}, session id {self.session.session_id}')
            self._logger.info(f'Actant version: {login_response.Version}')
            self._logger.info(f'Link time: {login_response.LinkTime}')
            has_allocations = False
            if login_response.HasField('hasAllocations'):
                has_allocations = login_response.hasAllocations
            self._logger.info(f'Node: {login_response.Node}, user:{login_response.User}, allocations: {has_allocations}')
            if login_response.HasField('actProtocolVersion'):
                self._logger.info(f'Act Version: {login_response.actProtocolVersion}')
            for prop in login_response.properties:
                self.session.session_properties.append(StrProperty(prop.name, prop.value))
            for server_connection in act_response.connections:
                self.session.server_connections.append(ServerConnection(server_connection.name, server_connection.status))
            self.on_logon_data = login_response
            self.on_logon_response.set_result(True)
        else:
            self._logger.info(f'Unhandled act sub-protocol response type')


# ActAutoControl sub-session

@dataclasses.dataclass(unsafe_hash=True)
class AutomationUpdate:
    auto_control_type: str
    automation_status: str


@dataclasses.dataclass(unsafe_hash=True)
class ProductAutomationUpdate:
    product: str
    iid: str
    automation_updates: ty.List[AutomationUpdate]


ClientId = int
ErrMsg = str
AckResponseHandler = ty.Callable[[ClientId, ErrMsg], None]


class AutoControlSubSession(object):
    def __init__(self, act_session: ActSession):
        self.session: ActSession = act_session
        self._logger = logging.getLogger(__name__)
        self._sub_proto_type = act_pb.SUB_PROTO_AUTOCONTROL
        self._request_id = 0  # interactive id
        self._client_id: ClientId = 0
        self._automation_request_handlers: ty.Dict[ClientId, AckResponseHandler] = dict()
        self.session.add_sub_session_handler(sub_protocol_type=self._sub_proto_type, handler=self.on_autocontrol_response)

    def _send_request(self, autocontrol_request: autocontrol_pb.Request):
        request = act_pb.Request()
        request.subProtocolType = self._sub_proto_type
        request.autoControlRequest.CopyFrom(autocontrol_request)
        self.session.send_request(request=request)

    def send_automation_updates(self, product_updates: ty.List[ProductAutomationUpdate], callback: AckResponseHandler) -> ClientId:
        client_id = ++self._client_id
        self._automation_request_handlers[client_id] = callback

        autocontrol_request = autocontrol_pb.Request()
        autocontrol_request.requestType = autocontrol_pb.RequestType.REQ_AUTOCONTROL_UPDATE
        autocontrol_request.clientId = client_id

        for product_update in product_updates:
            proto_product_update = autocontrol_request.automationUpdates.add()
            proto_product_update.product = product_update.product
            proto_product_update.oldIId = product_update.iid
            proto_product_update.newIId = self._get_next_iid()
            for automation_update in product_update.automation_updates:
                proto_update = proto_product_update.statusChanges.add()
                proto_update.autoControlType = automation_update.auto_control_type
                proto_update.automationStatus = automation_update.automation_status

        # self._logger.info(f'Sending automation update request')
        self._send_request(autocontrol_request=autocontrol_request)
        return client_id

    def on_autocontrol_response(self, response: act_pb.Response):
        autocontrol_response = response.autoControlResponse
        if autocontrol_response is None:
            self._logger.error(f'Got empty autocontrol sub-protocol response')
            return

        response_type = autocontrol_response.responseType
        if response_type == autocontrol_pb.RESP_AUTOCONTROL_UPDATE:
            if has_error(autocontrol_response.operationStatus):
                if autocontrol_response.clientId in self._automation_request_handlers:
                    self._automation_request_handlers[autocontrol_response.clientId](autocontrol_response.clientId, _get_error(autocontrol_response.operationStatus))
                    del self._automation_request_handlers[autocontrol_response.clientId]
        elif response_type == autocontrol_pb.RESP_PRODUCT_AUTOMATION:
            self._automation_request_handlers[autocontrol_response.clientId](autocontrol_response.clientId, _get_error(autocontrol_response.operationStatus))
            del self._automation_request_handlers[autocontrol_response.clientId]
            # if log_any_error("product automation response", autocontrol_response.operationStatus):
            #     return
        else:
            self._logger.info(f'Unhandled autocontrol sub-protocol response type')
        pass

    def _get_next_iid(self) -> str:
        return f'{self.session.session_id}:{++self._request_id}'


# Dex sub-session


DexQueryTableUpdateHandler = ty.Callable[[ClientId, ErrMsg, dex_pb.TableUpdate], None]


@dataclasses.dataclass(unsafe_hash=True)
class _DexQueryHandlerData:
    is_snapshot: bool
    ack_handler: AckResponseHandler
    table_update_handler: DexQueryTableUpdateHandler


class DexSubSession(object):
    def __init__(self, act_session: ActSession):
        self.session: ActSession = act_session
        self._logger = logging.getLogger(__name__)
        self._sub_proto_type = act_pb.SUB_PROTO_DEX
        self._client_id: ClientId = 0
        self._query_handler_data: ty.Dict[ClientId, _DexQueryHandlerData] = dict()
        self._table_update_resp_handlers: ty.Dict[ClientId, AckResponseHandler] = dict()
        self._stop_query_resp_handlers: ty.Dict[ClientId, AckResponseHandler] = dict()
        self.session.add_sub_session_handler(sub_protocol_type=self._sub_proto_type, handler=self.on_dex_response)

    def _send_request(self, dex_request: dex_pb.Request):
        request = act_pb.Request()
        request.subProtocolType = self._sub_proto_type
        request.dexRequest.CopyFrom(dex_request)
        self.session.send_request(request=request)

    def start_query(self, scope_keys: ty.List[str], fields: ty.List[str], frequency: int, is_snapshot: bool,
                    ack_handler: AckResponseHandler, table_update_handler: DexQueryTableUpdateHandler,
                    no_triggers: ty.Optional[ty.List[str]] = None, contexts: ty.Optional[ty.List[str]] = None) -> ClientId:
        client_id = ++self._client_id
        self._query_handler_data[client_id] = _DexQueryHandlerData(is_snapshot=is_snapshot, ack_handler=ack_handler, table_update_handler=table_update_handler)

        proto_start_query = dex_pb.StartQuery()
        proto_start_query.scopeKey.extend(scope_keys)
        proto_start_query.field.extend(fields)
        proto_start_query.frequency = frequency
        proto_start_query.oneTime = is_snapshot
        if no_triggers is not None:
            proto_start_query.noTrigger.extend(no_triggers)
        if contexts is not None:
            proto_start_query.context.extend(contexts)

        dex_request = dex_pb.Request()
        dex_request.requestType = dex_pb.RequestType.REQ_START_QUERY
        dex_request.clientId = client_id
        dex_request.startQuery.CopyFrom(proto_start_query)

        self._send_request(dex_request=dex_request)
        return client_id

    def stop_query(self, client_id: ClientId, ack_handler: AckResponseHandler):
        self._stop_query_resp_handlers[client_id] = ack_handler
        dex_request = dex_pb.Request()
        dex_request.requestType = dex_pb.RequestType.REQ_STOP_QUERY
        dex_request.clientId = client_id

        self._send_request(dex_request=dex_request)

    def update_table(self, table_update: dex_pb.TableUpdate, ack_handler: AckResponseHandler):
        client_id = ++self._client_id
        self._table_update_resp_handlers[client_id] = ack_handler
        dex_request = dex_pb.Request()
        dex_request.requestType = dex_pb.RequestType.REQ_TABLE_UPDATE
        dex_request.clientId = client_id
        dex_request.tableUpdate.CopyFrom(table_update)

        self._send_request(dex_request=dex_request)
        return client_id

    def on_dex_response(self, response: act_pb.Response):
        dex_response = response.dexResponse
        if dex_response is None:
            self._logger.error(f'Got empty dex sub-protocol response')
            return

        response_type = dex_response.responseType
        if response_type == dex_pb.RESP_START_QUERY:
            if dex_response.clientId not in self._query_handler_data:
                self._logger.error(f'No start query response handler for query id {dex_response.clientId}')
                return
            query_handler_data = self._query_handler_data[dex_response.clientId]
            query_handler_data.ack_handler(dex_response.clientId, _get_error(dex_response.operationStatus))
            return
        elif response_type == dex_pb.UPDATE_TABLE:
            if dex_response.clientId not in self._query_handler_data:
                self._logger.error(f'No query table update handler for query id {dex_response.clientId}')
                return
            query_handler_data = self._query_handler_data[dex_response.clientId]
            query_handler_data.table_update_handler(dex_response.clientId, _get_error(dex_response.operationStatus), dex_response.tableUpdate)
            if query_handler_data.is_snapshot:
                del self._query_handler_data[dex_response.clientId]
            return
        elif response_type == dex_pb.RESP_STOP_QUERY:
            if dex_response.clientId not in self._stop_query_resp_handlers:
                # self._logger.error(f'No stop query response handler for query id {dex_response.clientId}')
                return
            stop_query_ack_handler = self._stop_query_resp_handlers[dex_response.clientId]
            stop_query_ack_handler(dex_response.clientId, _get_error(dex_response.operationStatus))
            del self._stop_query_resp_handlers[dex_response.clientId]
            del self._query_handler_data[dex_response.clientId]
        elif response_type == dex_pb.RESP_TABLE_UPDATE:
            if dex_response.clientId not in self._table_update_resp_handlers:
                self._logger.error(f'No stop query response handler for query id {dex_response.clientId}')
                return
            table_update_ack_handler = self._table_update_resp_handlers[dex_response.clientId]
            table_update_ack_handler(dex_response.clientId, _get_error(dex_response.operationStatus))
            del self._table_update_resp_handlers[dex_response.clientId]


@dataclasses.dataclass(unsafe_hash=True)
class NamedInstrument:
    name: str
    instrument: str

    def to_proto(self) -> algo_pb.NamedInstrument:
        named_instrument = algo_pb.NamedInstrument()
        named_instrument.name = self.name
        named_instrument.instrument = self.instrument
        return named_instrument


DirectActionAdditionalInstruments = ty.List[NamedInstrument]
InputParameters = ty.List[StrProperty]

DirectActionName = str
AutomationStatus = str
AlgoName = str
CreateDirectActionResponseHandler = ty.Callable[[ClientId, ErrMsg, ty.Optional[DirectActionName], ty.Optional[AutomationStatus]], None]
SetAlgoStatusResponseHandler = ty.Callable[[ClientId, ErrMsg, ty.Optional[AlgoName]], None]
TerminateAlgoResponseHandler = ty.Callable[[ClientId, ErrMsg, ty.Optional[AlgoName]], None]


class AlgoControlStatus(str, enum.Enum):
    Unknown = "Unknown",
    Off = "Off",
    Manual = "Manual",
    Auto = "Auto",

    def to_proto(self) -> algo_pb.AlgoControlStatus:
        if self.value == AlgoControlStatus.Off:
            return algo_pb.AlgoControlStatus.ACS_Off
        if self.value == AlgoControlStatus.Manual:
            return algo_pb.AlgoControlStatus.ACS_Manual
        if self.value == AlgoControlStatus.Auto:
            return algo_pb.AlgoControlStatus.ACS_Auto
        return algo_pb.AlgoControlStatus.ACS_Unknown

    @classmethod
    def from_proto(cls, inp: algo_pb.AlgoControlStatus) -> AlgoControlStatus:
        if inp == algo_pb.AlgoControlStatus.ACS_Off:
            return AlgoControlStatus.Off
        if inp == algo_pb.AlgoControlStatus.ACS_Manual:
            return AlgoControlStatus.Manual
        if inp == algo_pb.AlgoControlStatus.ACS_Auto:
            return AlgoControlStatus.Auto
        return algo_pb.AlgoControlStatus.ACS_Unknown


@dataclasses.dataclass(unsafe_hash=True)
class DirectActionData:
    name: str
    base_instrument: str
    additional_instruments: ty.Optional[DirectActionAdditionalInstruments] = None
    input_parameters: ty.Optional[InputParameters] = None
    action_status: ty.Optional[str] = None

    def to_proto(self) -> algo_pb.CreateDirectActionRequest:
        create_direct_action_request = algo_pb.CreateDirectActionRequest()
        create_direct_action_request.directActionName = self.name
        create_direct_action_request.baseInstrument = self.base_instrument
        if self.additional_instruments is not None:
            for additional_instrument in self.additional_instruments:
                create_direct_action_request.additionalInstruments.append(additional_instrument.to_proto())
        if self.input_parameters is not None:
            for input_parameter in self.input_parameters:
                create_direct_action_request.inputParameters.append(input_parameter.to_proto())
        if self.action_status is not None:
            create_direct_action_request.actionStatus = self.action_status
        return create_direct_action_request


# algo sub-session

class AlgoSubSession(object):
    def __init__(self, act_session: ActSession):
        self.session: ActSession = act_session
        self._logger = logging.getLogger(__name__)
        self._sub_proto_type = act_pb.SUB_PROTO_ALGO
        self._client_id: ClientId = 0
        self._create_da_request_handlers: ty.Dict[ClientId, CreateDirectActionResponseHandler] = dict()
        self._set_algo_status_request_handlers: ty.Dict[ClientId, SetAlgoStatusResponseHandler] = dict()
        self._terminate_algo_request_handlers: ty.Dict[ClientId, TerminateAlgoResponseHandler] = dict()
        self.session.add_sub_session_handler(sub_protocol_type=self._sub_proto_type, handler=self.on_algo_response)

    def _send_request(self, algo_request: algo_pb.Request):
        request = act_pb.Request()
        request.subProtocolType = self._sub_proto_type
        request.algoRequest.CopyFrom(algo_request)
        self.session.send_request(request=request)

    def create_direct_action(self, direct_action: DirectActionData, callback: CreateDirectActionResponseHandler) -> ClientId:
        client_id = ++self._client_id
        self._create_da_request_handlers[client_id] = callback

        create_direct_action_request = direct_action.to_proto()

        algo_request = algo_pb.Request()
        algo_request.requestType = algo_pb.RequestType.REQ_CREATE_DIRECT_ACTION
        algo_request.clientId = client_id
        algo_request.createDirectActionRequest.CopyFrom(create_direct_action_request)

        self._logger.info(f'Sending create direct action request')
        self._send_request(algo_request=algo_request)
        return client_id

    def set_algo_status(self, algo_name: str, status: AlgoControlStatus, callback: SetAlgoStatusResponseHandler) -> ClientId:
        client_id = ++self._client_id
        self._set_algo_status_request_handlers[client_id] = callback

        algo_request = algo_pb.Request()
        algo_request.requestType = algo_pb.RequestType.REQ_SET_ALGO_STATUS
        algo_request.clientId = client_id
        algo_request.algoName = algo_name
        algo_request.controlStatus = status.to_proto()

        self._logger.info(f'Sending set algo status request')
        self._send_request(algo_request=algo_request)
        return client_id

    def terminate_algo(self, algo_name: str, callback: TerminateAlgoResponseHandler) -> ClientId:
        client_id = ++self._client_id
        self._terminate_algo_request_handlers[client_id] = callback

        algo_request = algo_pb.Request()
        algo_request.requestType = algo_pb.RequestType.REQ_TERMINATE_ALGO
        algo_request.clientId = client_id
        algo_request.algoName = algo_name

        self._logger.info(f'Sending terminate algo request')
        self._send_request(algo_request=algo_request)
        return client_id

    def on_algo_response(self, response: act_pb.Response):
        algo_response = response.algoResponse
        if algo_response is None:
            self._logger.error(f'Got empty algo sub-protocol response')
            return

        response_type = algo_response.responseType
        # self._logger.info(f'Got algo response: {response_type}')
        if response_type == algo_pb.RESP_CREATE_DIRECT_ACTION:
            if algo_response.clientId in self._create_da_request_handlers:
                create_da_response = algo_response.createDirectActionResponse
                action_name = None
                automation_status = None
                if create_da_response is not None:
                    action_name = create_da_response.actionName
                    automation_status = create_da_response.automationStatus
                self._create_da_request_handlers[algo_response.clientId](algo_response.clientId, _get_error(algo_response.operationStatus), action_name, automation_status)
                del self._create_da_request_handlers[algo_response.clientId]
            else:
                self._logger.error(f'No handler for create direct action response')
        elif response_type == algo_pb.RESP_SET_ALGO_STATUS:
            if algo_response.clientId in self._set_algo_status_request_handlers:
                self._set_algo_status_request_handlers[algo_response.clientId](algo_response.clientId, _get_error(algo_response.operationStatus), algo_response.algoName)
                del self._set_algo_status_request_handlers[algo_response.clientId]
            else:
                self._logger.error(f'No handler for set algo status response')
        elif response_type == algo_pb.RESP_TERMINATE_ALGO:
            if algo_response.clientId in self._terminate_algo_request_handlers:
                self._terminate_algo_request_handlers[algo_response.clientId](algo_response.clientId, _get_error(algo_response.operationStatus), algo_response.algoName)
                del self._terminate_algo_request_handlers[algo_response.clientId]
            else:
                self._logger.error(f'No handler for terminate algo response')
        else:
            self._logger.info(f'Unhandled algo sub-protocol response type')
        pass
