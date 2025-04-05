import csv
import dataclasses
import enum
import io
import logging
import sys
import typing as ty

from . import session
from .proto import DataExchangeAPI_pb2 as dex_pb
from .util import util


class DexQueryData(util.ClassHasEquality):
    def __init__(self, scope_keys: ty.List[str], fields: ty.List[str], is_snapshot: bool,
                 frequency: int = 1000,
                 no_triggers: ty.Optional[ty.List[str]] = None,
                 contexts: ty.Optional[ty.List[str]] = None):
        self.scope_keys = scope_keys
        self.fields = [field.upper() for field in fields]
        self.frequency = frequency
        self.is_snapshot = is_snapshot
        self.no_triggers = no_triggers
        self.contexts = contexts


VariantVectorValue = ty.List[dex_pb.VariantValue]
VariantValueToStrFunc = ty.Callable[[dex_pb.VariantValue, VariantVectorValue], str]

DexColumnToStrFunc = ty.Callable[['DexColumn'], str]


class DexQuantity(util.ClassHasEquality):
    ScalingFactor: int = 100000000
    Precision: int = 8
    _INVALID = -sys.maxsize - 1
    _Divisors = [100000000, 10000000, 1000000, 100000, 10000, 1000, 100, 10, 1]
    _Padding = ["", "0", "00", "000", "0000", "00000", "000000", "0000000", "00000000", "000000000"]

    def __init__(self):
        self._value: int = 0

    def __str__(self):
        return self.to_str(num_decimals=self.get_decimals())

    def to_float(self) -> float:
        return self._value / self.ScalingFactor

    def to_dex(self) -> int:
        return self._value

    def get_decimals(self) -> int:
        if self._value < 0:
            return -self._value % self.ScalingFactor
        return self._value % self.ScalingFactor

    def to_str(self, num_decimals: int) -> str:
        no_trailing_zeros = num_decimals < 0
        num_decimals = self.Precision if no_trailing_zeros else int(max(min(num_decimals, self.Precision), 0))
        value = -self._value if self._value < 0 else self._value
        fraction = value % self.ScalingFactor
        int_part = int((value - fraction) / self.ScalingFactor)
        res = ''
        if self._value < 0:
            res += '-'
        if num_decimals > 0:
            if int_part > 0:
                res += str(int_part)
            res += '.'
            temp = str(fraction / self._Divisors[num_decimals])
            padding = num_decimals - len(temp)
            if padding > 0:
                res += self._Padding[padding]
            res += temp
        elif int_part > 0:
            res += str(int_part)
        elif int_part == 0:
            return '0'
        if no_trailing_zeros:
            if self._value == 0:
                return '0'
            return res.rstrip('0')
        return res

    @classmethod
    def get_zero(cls) -> 'DexQuantity':
        return DexQuantity()

    @classmethod
    def from_float(cls, value: float) -> 'DexQuantity':
        dex_quantity = DexQuantity()
        dex_quantity._value = value * cls.ScalingFactor
        return dex_quantity

    @classmethod
    def from_dex(cls, value: int) -> 'DexQuantity':
        return cls.from_value_and_precision(value=value, precision=cls.Precision)

    @classmethod
    def from_value_and_precision(cls, value: int, precision: int) -> 'DexQuantity':
        dex_quantity = DexQuantity()
        if precision == cls.Precision:
            dex_quantity._value = value
        else:
            if precision < 0 or precision > cls.Precision:
                dex_quantity._value = 0
            else:
                dex_quantity._value = value * cls._Divisors[precision]
        return dex_quantity


class DexPrice(util.ClassHasEquality):
    ScalingFactor: int = 10000000
    Precision: int = 7
    _INVALID = -sys.maxsize - 1
    _Divisors = [10000000, 1000000, 100000, 10000, 1000, 100, 10, 1]
    _Rounding = [5000000, 500000, 50000, 5000, 500, 50, 5, 0]
    _RoundUp = [1, 10, 100, 1000, 10000, 100000, 1000000, 10000000]
    _Padding = ["", "0", "00", "000", "0000", "00000", "000000", "0000000", "00000000"]

    def __init__(self):
        self._value: int = self._INVALID

    def __str__(self):
        return self.to_str(num_decimals=self.get_decimals())

    def is_valid(self) -> bool:
        return self._value != self._INVALID

    def to_float(self) -> float:
        if not self.is_valid():
            return 0
        return self._value / self.ScalingFactor

    def to_dex(self) -> int:
        return self._value

    def get_decimals(self) -> int:
        if self._value < 0:
            return -self._value % self.ScalingFactor
        return self._value % self.ScalingFactor

    def to_str(self, num_decimals: int) -> str:
        if not self.is_valid():
            return "INVALID"
        num_decimals = int(max(min(num_decimals, self.Precision), 0))
        value = -self._value if self._value < 0 else self._value
        fraction = value % self.ScalingFactor
        int_part = int((value - fraction) / self.ScalingFactor)
        res = ''
        if self._value < 0:
            res += '-'
        if num_decimals > 0:
            rounded = int((fraction + self._Rounding[num_decimals]) / self._Divisors[num_decimals])
            round_up = self._RoundUp[num_decimals]
            if rounded > round_up:
                rounded -= round_up
                int_part += 1
            temp = str(rounded)
            padding = num_decimals - len(temp)
            if int_part > 0:
                res += str(int_part)
            res += '.'
            if padding > 0:
                res += self._Padding[padding]
            res += temp
        elif int_part > 0:
            res += str(int_part)
        elif int_part == 0:
            return '0'
        return res

    @classmethod
    def get_invalid(cls) -> 'DexPrice':
        return DexPrice()

    @classmethod
    def from_float(cls, value: float) -> 'DexPrice':
        dex_price = DexPrice()
        dex_price._value = value * cls.ScalingFactor
        return dex_price

    @classmethod
    def from_dex(cls, value: int) -> 'DexPrice':
        return cls.from_value_and_precision(value=value, precision=cls.Precision)

    @classmethod
    def from_value_and_precision(cls, value: int, precision: int) -> 'DexPrice':
        dex_price = DexPrice()
        if precision == cls.Precision:
            dex_price._value = value
        else:
            if precision < 0 or precision > cls.Precision:
                dex_price._value = cls._INVALID
            else:
                dex_price._value = value * cls._Divisors[precision]
        return dex_price

    @classmethod
    def from_str(cls, value: str) -> ty.Optional['DexPrice']:
        price: int = 0
        decimals: int = 0
        negative = False
        decimal_mode = False
        for c in value:
            if c == '-':
                negative = True
            elif c.isnumeric():
                price = 10 * price + (ord(c) - ord('0'))
                if decimal_mode:
                    decimals += 1
            elif c == '.':
                decimal_mode = True
            else:
                return DexPrice.get_invalid()

        if negative:
            price = -price
        return DexPrice.from_value_and_precision(value=price, precision=decimals)


def str_to_variant_value(inp: str, type: dex_pb.VariantType) -> dex_pb.VariantValue:
    value = dex_pb.VariantValue()
    if type == dex_pb.VariantType.VAR_UNKNOWN:
        pass
    elif type == dex_pb.VariantType.VAR_DOUBLE:
        try:
            value.varDouble = float(inp)
        except ValueError:
            value.varDouble = float('nan')
    elif type == dex_pb.VariantType.VAR_INT32:
        try:
            value.varInt = int(inp)
        except ValueError:
            value.varInt = 0
    elif type == dex_pb.VariantType.VAR_PRICE:
        dex_price = DexPrice.from_str(inp)
        if dex_price:
            value.varPrice = dex_price.to_dex()
    elif type == dex_pb.VariantType.VAR_STRING:
        value.varString = inp

    return value


def variant_value_to_dex_price(value: dex_pb.VariantValue) -> DexPrice:
    if value is None:
        return DexPrice.get_invalid()
    if value.HasField("varPrice"):
        return DexPrice.from_dex(value=value.varPrice)
    if value.HasField("varDouble"):
        return DexPrice.from_float(value=value.varDouble)
    if value.HasField("varQuantity"):
        return DexPrice.from_float(value=DexQuantity.from_dex(value=value.varQuantity).to_float())
    if value.HasField("varInt"):
        return DexPrice.from_float(value=value.varInt)
    return DexPrice.get_invalid()


def variant_value_to_dex_quantity(value: dex_pb.VariantValue) -> DexQuantity:
    if value is None:
        return DexQuantity.get_zero()
    if value.HasField("varQuantity"):
        return DexQuantity.from_dex(value=value.varQuantity)
    if value.HasField("varDouble"):
        return DexQuantity.from_float(value=value.varDouble)
    if value.HasField("varInt"):
        return DexQuantity.from_float(value=value.varInt)
    return DexQuantity.get_zero()


def variant_value_to_int(value: dex_pb.VariantValue) -> int:
    if value is None:
        return 0
    if value.HasField("varQuantity"):
        return int(DexQuantity.from_dex(value=value.varQuantity).to_float())
    if value.HasField("varInt"):
        return value.varInt
    if value.HasField("varDouble"):
        return int(value.varDouble)
    if value.HasField("varPrice"):
        return int(DexPrice.from_dex(value=value.varPrice).to_float())
    return 0


class DexColumn(util.ClassHasEquality):
    def __init__(self, col_index: int, name: str, col_type: dex_pb.VariantType, is_vector: bool, can_write: bool, value_to_str_func: VariantValueToStrFunc):
        self.col_index = col_index
        self.name = name
        self.col_type = col_type
        self.is_vector = is_vector
        self.can_write = can_write
        self.value_to_str_func = value_to_str_func
        self.to_str_func: ty.Optional[DexColumnToStrFunc] = None

    def set_to_str_func(self, to_str_func: ty.Optional[DexColumnToStrFunc] = None):
        self.to_str_func = to_str_func

    def __str__(self):
        if self.to_str_func is not None:
            return self.to_str_func(self)
        return f'{self.name}'

    def col_type_str(self) -> str:
        return dex_pb.VariantType.Name(self.col_type)

    @classmethod
    def from_minimum_data(cls, col_index: int, name: str, col_type: dex_pb.VariantType) -> 'DexColumn':
        return DexColumn(col_index=col_index, name=name, col_type=col_type, is_vector=False, can_write=False, value_to_str_func=get_variant_value_to_str_func(variant_type=col_type, is_vector=False))


DexCellToStrFunc = ty.Callable[['DexCell'], str]


class DexCell(util.ClassHasEquality):
    def __init__(self, column: DexColumn, value_to_str_func: VariantValueToStrFunc):
        self.column = column
        self.value_to_str_func = value_to_str_func
        self.value: ty.Optional[dex_pb.VariantValue] = None
        self.vector: ty.Optional[VariantVectorValue] = None
        self.row: ty.Optional[DexRow] = None
        self.guessed_value: ty.Optional[str] = None
        self.update_count: int = 0
        self.to_str_func: ty.Optional[DexCellToStrFunc] = None

    def set_to_str_func(self, to_str_func: ty.Optional[DexCellToStrFunc] = None):
        self.to_str_func = to_str_func

    def __str__(self):
        if self.to_str_func is not None:
            return self.to_str_func(self)
        return f'({self.row},{self.column}):{self.guessed_value}'

    def value_str(self) -> str:
        return self.value_to_str_func(self.value, self.vector)


DexRowKeyToStrFunc = ty.Callable[['DexRowKey'], str]


class DexRowKey(util.ClassHasEquality):
    def __init__(self, key: str, contexts: str):
        self.key = key
        self.contexts = contexts
        self.to_str_func: ty.Optional[DexRowKeyToStrFunc] = None

    def set_to_str_func(self, to_str_func: ty.Optional[DexRowKeyToStrFunc] = None):
        self.to_str_func = to_str_func

    def __str__(self):
        if self.to_str_func is not None:
            return self.to_str_func(self)
        if self.contexts is None or len(self.contexts) == 0:
            return f'{self.key}'
        return f'{self.key}:{self.contexts}'

    @classmethod
    def from_row(cls, row: dex_pb.Row) -> 'DexRowKey':
        return DexRowKey(key=row.key, contexts=row.contexts)

    @classmethod
    def without_contexts(cls, key: str) -> 'DexRowKey':
        return DexRowKey(key=key, contexts='')


DexRowToStrFunc = ty.Callable[['DexRow'], str]
DexCells = ty.List[DexCell]
DexColumns = ty.List[DexColumn]


class DexRow(util.ClassHasEquality):
    def __init__(self, row_index: int, row_key: DexRowKey, cells: DexCells):
        self.row_index = row_index
        self.row_key: DexRowKey = row_key
        self.cells = cells
        for cell in self.cells:
            cell.row = self
        self.to_str_func: ty.Optional[DexRowToStrFunc] = None

    def set_to_str_func(self, to_str_func: ty.Optional[DexRowToStrFunc] = None):
        self.to_str_func = to_str_func

    def __str__(self):
        if self.to_str_func is not None:
            return self.to_str_func(self)
        return f'{self.row_key}'

    def update_cell(self, update_count: int, cell: dex_pb.Cell):
        if cell.columnNumber >= len(self.cells):
            return
        dex_cell = self.cells[cell.columnNumber]
        dex_cell.update_count = update_count
        if cell.HasField("value"):
            dex_cell.value = cell.value
        else:
            if cell.valueVector is not None:
                dex_cell.vector = []
                for value in cell.valueVector:
                    dex_cell.vector.append(value)
            else:
                dex_cell.vector = None

    def get_cells(self, selector: ty.Callable[[DexCell], bool]) -> DexCells:
        return [cell for cell in self.cells if selector(cell)]

    def get_updated_cells(self, update_count: int) -> DexCells:
        return self.get_cells(selector=lambda cell: cell.update_count >= update_count)

    def get_cell_by_name(self, column_name: str) -> ty.Optional[DexCell]:
        return next((cell for cell in self.cells if cell.column.name == column_name), None)

    def to_dex_row(self) -> dex_pb.Row:
        dex_cells: ty.List[dex_pb.Cell] = []
        for cell in self.cells:
            dex_cell = dex_pb.Cell()
            dex_cell.columnNumber = cell.column.col_index
            dex_cell.value.CopyFrom(cell.value)
            dex_cells.append(dex_cell)
        dex_row = dex_pb.Row()
        dex_row.key = self.row_key.key
        dex_row.cell.extend(dex_cells)
        return dex_row


def get_variant_value_to_str_func(variant_type: dex_pb.VariantType, is_vector: bool) -> VariantValueToStrFunc:
    def get_variant_value_str(variant_value: dex_pb.VariantValue, variant_vector_value: VariantVectorValue) -> str:
        if variant_value.HasField('varString'):
            return variant_value.varString
        return ''

    def get_variant_value_double(variant_value: dex_pb.VariantValue, variant_vector_value: VariantVectorValue) -> str:
        if variant_value.HasField('varDouble'):
            return str(DexPrice.from_float(variant_value.varDouble))
        return ''

    def get_variant_value_int32(variant_value: dex_pb.VariantValue, variant_vector_value: VariantVectorValue) -> str:
        if variant_value.HasField('varQuantity'):
            return str(DexQuantity.from_dex(variant_value.varQuantity))
        if variant_value.HasField('varInt'):
            return str(variant_value.varInt)
        return ''

    def get_variant_value_price(variant_value: dex_pb.VariantValue, variant_vector_value: VariantVectorValue) -> str:
        dex_price = variant_value_to_dex_price(value=variant_value)
        return str(dex_price)

    def get_variant_value_unknown(variant_value: dex_pb.VariantValue, variant_vector_value: VariantVectorValue) -> str:
        return ''

    if variant_type == dex_pb.VariantType.VAR_STRING:
        return get_variant_value_str
    elif variant_type == dex_pb.VariantType.VAR_DOUBLE:
        return get_variant_value_double
    elif variant_type == dex_pb.VariantType.VAR_INT32:
        return get_variant_value_int32
    elif variant_type == dex_pb.VariantType.VAR_PRICE:
        return get_variant_value_price
    return get_variant_value_unknown


DexRows = ty.List[DexRow]


@dataclasses.dataclass(unsafe_hash=True)
class DexTableUpdate(object):
    columns: DexColumns
    rows: DexRows

    def to_table_update(self) -> dex_pb.TableUpdate:
        column_descriptors: ty.List[dex_pb.ColumnDescriptor] = []
        for column in self.columns:
            column_descriptor = dex_pb.ColumnDescriptor()
            column_descriptor.name = column.name
            column_descriptors.append(column_descriptor)

        rows: ty.List[dex_pb.Row] = []
        for row in self.rows:
            rows.append(row.to_dex_row())

        table_update = dex_pb.TableUpdate()
        table_update.columnDescriptor.extend(column_descriptors)
        table_update.row.extend(rows)
        return table_update


def to_csv(columns: DexColumns, rows: DexRows, writer: ty.Optional[csv.writer] = None, with_type_row: ty.Optional[bool] = None) -> str:
    output = io.StringIO()
    if writer is None:
        writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
    column_names = [column.name for column in columns]
    header_row = ['Key', *column_names]
    writer.writerow(header_row)
    if with_type_row is None or with_type_row:
        column_types = [column.col_type_str() for column in columns]
        type_row = ['Type', *column_types]
        writer.writerow(type_row)
    for row in rows:
        row_values = [cell.value_str() for cell in row.cells]
        writer.writerow([row.row_key.key, *row_values])
    return output.getvalue()


def from_csv(csv_str: str, reader: ty.Optional[csv.reader] = None) -> ty.Optional[DexTableUpdate]:
    logger = logging.getLogger(__name__)
    input = io.StringIO(csv_str)
    if reader is None:
        reader = csv.reader(input, delimiter=',')
    input_rows = list(reader)
    if len(input_rows) < 2:
        logger.error(f'Need at least two input_rows in csv: Header, Type')
        return None
    header_row = input_rows[0]
    type_row = input_rows[1]
    columns: DexColumns = []
    for i, column_name in enumerate(header_row):
        if i == 0:  # RowKey
            continue
        column_type_str = type_row[i]
        column_type = dex_pb.VariantType.Value(column_type_str)
        column = DexColumn.from_minimum_data(col_index=i - 1, name=column_name, col_type=column_type)
        columns.append(column)

    rows: DexRows = []
    data_rows = input_rows[2:]
    for row_index, data_row in enumerate(data_rows):
        row_key = DexRowKey.without_contexts(key=data_row[0])
        cells = []
        for column_index, cell_value in enumerate(data_row[1:]):
            column = columns[column_index]
            cell = DexCell(column=column, value_to_str_func=column.value_to_str_func)
            cell.value = str_to_variant_value(inp=cell_value, type=column.col_type)
            cells.append(cell)
        row = DexRow(row_index=row_index, row_key=row_key, cells=cells)
        rows.append(row)

    return DexTableUpdate(columns=columns, rows=rows)


class DexQueryState(str, enum.Enum):
    Unknown = "Unknown",
    Starting = "Starting",
    Started = "Started",
    StartError = "StartError",
    ColumnsReceived = "ColumnsReceived",
    UpdateError = "UpdateError",
    Stopping = "Stopping",
    Stopped = "Stopped",
    Disconnected = "Disconnected",
    StopError = "StopError",


ErrMsg = str
NewState = DexQueryState
OldState = DexQueryState
StateChangeHandler = ty.Callable[['DexQuery', NewState, ErrMsg, OldState], None]

ColumnsReceivedHandler = ty.Callable[['DexQuery', ty.List[DexColumn]], None]

UpdateCount = int
NumRows = int
NewRows = ty.List[DexRow]
NewUpdatedRows = ty.List[DexRow]
UpdateHandler = ty.Callable[['DexQuery', UpdateCount, NumRows, NewRows, NewUpdatedRows], None]

DeletedRows = ty.List[DexRow]
ResetHandler = ty.Callable[['DexQuery', UpdateCount, DeletedRows], None]

DexQueryToStrFunc = ty.Callable[['DexQuery'], str]


class DexQuery(object):

    def __init__(self, query_data: DexQueryData, act_session: session.ActSession):
        self.query_data = query_data
        self.act_session = act_session
        self.logger = logging.getLogger(__name__)
        self.state = DexQueryState.Unknown
        self.err_msg: ty.Optional[str] = None
        self.client_id: ty.Optional[int] = None
        self.update_count: int = 0
        self.columns: DexColumns = []
        self.rows: DexRows = []
        self._row_keys: ty.Dict[DexRowKey, int] = dict()
        self._row_number_keys: ty.Dict[int, DexRowKey] = dict()
        self._state_change_handlers: ty.List[StateChangeHandler] = []
        self._columns_received_handlers: ty.List[ColumnsReceivedHandler] = []
        self._update_handlers: ty.List[UpdateHandler] = []
        self._reset_handlers: ty.List[ResetHandler] = []

        self.to_str_func: ty.Optional[DexQueryToStrFunc] = None

    def set_to_str_func(self, to_str_func: ty.Optional[DexQueryToStrFunc] = None):
        self.to_str_func = to_str_func

    def __str__(self):
        if self.to_str_func is not None:
            return self.to_str_func(self)
        return f'({self.act_session}:{self.client_id})'

    def add_handlers(self,
                     state_change_handler: ty.Optional[StateChangeHandler] = None,
                     columns_received_handler: ty.Optional[ColumnsReceivedHandler] = None,
                     update_handler: ty.Optional[UpdateHandler] = None,
                     reset_handler: ty.Optional[ResetHandler] = None,
                     ):
        if state_change_handler is not None:
            self._state_change_handlers.append(state_change_handler)
        if columns_received_handler is not None:
            self._columns_received_handlers.append(columns_received_handler)
        if update_handler is not None:
            self._update_handlers.append(update_handler)
        if reset_handler is not None:
            self._reset_handlers.append(reset_handler)

    def start(self):
        self._change_state(new_state=DexQueryState.Starting)
        self.client_id = self.act_session.dex_sub_session.start_query(scope_keys=self.query_data.scope_keys,
                                                                      fields=self.query_data.fields,
                                                                      frequency=self.query_data.frequency,
                                                                      is_snapshot=self.query_data.is_snapshot,
                                                                      no_triggers=self.query_data.no_triggers,
                                                                      contexts=self.query_data.contexts,
                                                                      ack_handler=self.on_start_query,
                                                                      table_update_handler=self.on_table_update)

    def stop(self):
        self._change_state(new_state=DexQueryState.Stopping)
        self.act_session.dex_sub_session.stop_query(client_id=self.client_id, ack_handler=self.on_stop_query)

    def on_start_query(self, client_id: int, err_msg: str):
        if err_msg is not None and len(err_msg) > 0:
            self._change_state(new_state=DexQueryState.StartError, err_msg=err_msg)
        else:
            self._change_state(new_state=DexQueryState.Started)

    def on_stop_query(self, client_id: int, err_msg: str):
        if err_msg is not None and len(err_msg) > 0:
            self._change_state(new_state=DexQueryState.StopError, err_msg=err_msg)
        else:
            self._change_state(new_state=DexQueryState.Stopped)

    def on_table_update(self, client_id: int, err_msg: str, update: dex_pb.TableUpdate):
        self.update_count += 1
        if len(update.columnDescriptor) > 0:
            self._reset()
            for i, column_descriptor_x in enumerate(update.columnDescriptor):
                column_descriptor: dex_pb.ColumnDescriptor = column_descriptor_x
                dex_column = DexColumn(col_index=i,
                                       name=column_descriptor.name,
                                       col_type=column_descriptor.type,
                                       is_vector=column_descriptor.isVector,
                                       can_write=column_descriptor.canWrite,
                                       value_to_str_func=get_variant_value_to_str_func(column_descriptor.type, is_vector=column_descriptor.isVector))
                self.columns.append(dex_column)
            self._change_state(new_state=DexQueryState.ColumnsReceived)
            for columns_received_handler in self._columns_received_handlers:
                columns_received_handler(self, self.columns)

        current_rows = self.rows
        new_rows: ty.List[DexRow] = []
        new_updated_rows: ty.List[DexRow] = []
        for row_x in update.row:
            row: dex_pb.Row = row_x
            row_key = self._get_row_key(row=row)
            if row_key not in self._row_keys:
                self._row_keys[row_key] = len(current_rows)
                cells: ty.List[DexCell] = []
                for column in self.columns:
                    cells.append(DexCell(column=column, value_to_str_func=column.value_to_str_func))
                dex_row = DexRow(row_index=len(current_rows), row_key=row_key, cells=cells)
                current_rows.append(dex_row)
                new_rows.append(dex_row)
            row_index = self._row_keys[row_key]
            dex_row = current_rows[row_index]
            for cell in row.cell:
                dex_row.update_cell(cell=cell, update_count=self.update_count)
            new_updated_rows.append(dex_row)
        self.rows = current_rows
        for update_handler in self._update_handlers:
            update_handler(self, self.update_count, len(self.rows), new_rows, new_updated_rows)

    def get_rows(self, selector: ty.Callable[[DexRow], bool]) -> DexRows:
        return [row for row in self.rows if selector(row)]

    def get_updated_rows(self, update_count: int) -> DexRows:
        return self.get_rows(selector=lambda row: row.update_count >= update_count)

    def get_row_by_key(self, key: str) -> ty.Optional[DexRow]:
        return next((row for row in self.rows if row.row_key.key == key), None)

    def as_csv(self, csv_writer: ty.Optional[csv.writer] = None, with_type_row: ty.Optional[bool] = None) -> str:
        return to_csv(columns=self.columns, rows=self.rows, writer=csv_writer, with_type_row=with_type_row)

    def _get_row_key(self, row: dex_pb.Row) -> DexRowKey:
        row_number = None
        try:
            if row.HasField('rowNumber'):
                row_number = row.rowNumber
        except ValueError:
            pass

        if row_number is not None and row_number in self._row_number_keys:
            return self._row_number_keys[row_number]
        row_key = DexRowKey.from_row(row=row)
        if row_number is not None:
            self._row_number_keys[row_number] = row_key
        return row_key

    def _reset(self):
        for reset_handler in self._reset_handlers:
            reset_handler(self, len(self.rows), self.rows)
        self.columns = []
        self.rows = []
        self._row_keys.clear()
        self._row_number_keys.clear()

    def _change_state(self, new_state: DexQueryState, err_msg: str = None):
        old_state = self.state
        self.state = new_state
        self.err_msg = err_msg
        for state_change_handler in self._state_change_handlers:
            state_change_handler(self, self.state, self.err_msg, old_state)
