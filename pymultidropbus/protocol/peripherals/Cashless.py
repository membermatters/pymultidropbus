from dataclasses import dataclass, field
from enum import Enum

import pymultidropbus.protocol as protocol
import pymultidropbus.protocol.Vmc as Vmc


class CashlessDeviceAddress(Enum):
    UNKNOWN = 0
    PRIMARY = 1
    SECONDARY = 2


class MdbResponse(Enum):
    @protocol.BindCmdBuilder("BEGIN_SESSION")
    def build(self, available_balance: "protocol.Money") -> str:
        return self.value + available_balance.vmc_hex

    @protocol.BindCmdBuilder("APPROVE_VEND")
    def build(self, amount_charged: "protocol.Money") -> str:
        return self.value + amount_charged.vmc_hex

    # handle a default case (no arguments supported)
    @protocol.BindCmdBuilder()
    def build(self) -> str:
        return self.value

    JUST_RESET = "00"
    READER_CONFIG_DATA = "01"
    DISPLAY_REQUEST = "02"
    BEGIN_SESSION = "03"
    SESSION_CANCEL_REQUEST = "04"
    APPROVE_VEND = "05"
    DENY_VEND = "06"
    END_SESSION = "07"
    CANCELLED = "08"
    PERIPHERAL_ID = "09"
    MALFUNCTION_ERROR = "0A"
    COMMAND_OUT_OF_SEQUENCE = "0B"
    REVALUE_APPROVED = "0D"
    REVALUE_DENIED = "0E"
    REVALUE_LIMIT_AMOUNT = "0F"
    USER_FILE_DATA = "10"
    TIME_DATE_REQUEST = "11"
    DATA_ENTRY_REQUEST = "12"
    DATA_ENTRY_CANCEL = "13"
    REQ_TO_RECV = "1B"
    RETRY_DENY = "1C"
    SEND_BLOCK = "1D"
    OK_TO_SEND = "1E"
    REQ_TO_SEND = "1F"
    DIAGNOSTIC_RESPONSE = "FF"


class MdbCommand(Enum):
    RESET = 0
    SETUP_CONFIG_DATA = 1
    SETUP_PRICE_DATA = 2
    POLL = 3

    VEND_REQUEST = 4
    VEND_CANCEL = 5
    VEND_SUCCESS = 6
    VEND_FAILURE = 7
    VEND_SESSION_COMPLETE = 8
    VEND_CASH_SALE = 8
    VEND_NEGATIVE_VEND_REQUEST = 9

    READER_DISABLE = 10
    READER_ENABLE = 11
    READER_CANCEL = 12
    DATA_ENTRY_RESPONSE = 13

    REVALUE_REQUEST = 14
    REVALUE_LIMIT_REQUEST = 15

    EXPANSION_REQUEST_ID = 16
    EXPANSION_READ_USER_FILE = 17
    EXPANSION_WRITE_USER_FILE = 18
    EXPANSION_WRITE_TIME_DATE = 19
    EXPANSION_OPTIONAL_FEATURE_ENABLED = 20
    EXPANSION_REQ_TO_RCV = 21
    EXPANSION_RETRY_DENY = 22
    EXPANSION_SEND_BLOCK = 23
    EXPANSION_OK_TO_SEND = 24
    EXPANSION_REQ_TO_SEND = 25
    EXPANSION_DIAGNOSTICS = 26


class AddressedMdbCommand:
    # MDB supports two cashless devices, labelled primary and secondary by the library
    def __init__(self, key):
        # loop through all the enum values and compare with a startswith()
        for enum in PrimaryAddressMdbCommand:
            if key.startswith(enum.value):
                self.MdbCommand = MdbCommand[enum.name]
                self.DeviceAddress = CashlessDeviceAddress.PRIMARY
                self.EnumClass = PrimaryAddressMdbCommand
                self.EnumInstance = enum
                return

        for enum in SecondaryAddressMdbCommand:
            if key.startswith(enum.value):
                self.MdbCommand = MdbCommand[enum.name]
                self.DeviceAddress = CashlessDeviceAddress.SECONDARY
                self.EnumClass = SecondaryAddressMdbCommand
                self.EnumInstance = enum
                return

        # if we couldn't find a match then throw
        raise ValueError(f"Could not find a match for {key}")


class PrimaryAddressMdbCommand(Enum):
    RESET = "10"
    SETUP_CONFIG_DATA = "1100"
    SETUP_PRICE_DATA = "1101"
    POLL = "12"

    VEND_REQUEST = "1300"
    VEND_CANCEL = "1301"
    VEND_SUCCESS = "1302"
    VEND_FAILURE = "1303"
    VEND_SESSION_COMPLETE = "1304"
    VEND_CASH_SALE = "1305"
    VEND_NEGATIVE_VEND_REQUEST = "1306"

    READER_DISABLE = "1400"
    READER_ENABLE = "1401"
    READER_CANCEL = "1402"
    DATA_ENTRY_RESPONSE = "1403"

    REVALUE_REQUEST = "1500"
    REVALUE_LIMIT_REQUEST = "1501"

    EXPANSION_REQUEST_ID = "1700"
    EXPANSION_READ_USER_FILE = "1701"
    EXPANSION_WRITE_USER_FILE = "1702"
    EXPANSION_WRITE_TIME_DATE = "1703"
    EXPANSION_OPTIONAL_FEATURE_ENABLED = "1704"
    EXPANSION_REQ_TO_RCV = "17FA"
    EXPANSION_RETRY_DENY = "17FB"
    EXPANSION_SEND_BLOCK = "17FC"
    EXPANSION_OK_TO_SEND = "17FD"
    EXPANSION_REQ_TO_SEND = "17FE"
    EXPANSION_DIAGNOSTICS = "17FF"


class SecondaryAddressMdbCommand(Enum):
    RESET = "60"
    SETUP_CONFIG_DATA = "6100"
    SETUP_PRICE_DATA = "6101"
    POLL = "62"

    VEND_REQUEST = "6300"
    VEND_CANCEL = "6301"
    VEND_SUCCESS = "6302"
    VEND_FAILURE = "6303"
    VEND_SESSION_COMPLETE = "6304"
    VEND_CASH_SALE = "6305"
    VEND_NEGATIVE_VEND_REQUEST = "6306"

    READER_DISABLE = "6400"
    READER_ENABLE = "6401"
    READER_CANCEL = "6402"
    DATA_ENTRY_RESPONSE = "6403"

    REVALUE_REQUEST = "6500"
    REVALUE_LIMIT_REQUEST = "6501"

    EXPANSION_REQUEST_ID = "6700"
    EXPANSION_READ_USER_FILE = "6701"
    EXPANSION_WRITE_USER_FILE = "6702"
    EXPANSION_WRITE_TIME_DATE = "6703"
    EXPANSION_OPTIONAL_FEATURE_ENABLED = "6704"
    EXPANSION_REQ_TO_RCV = "67FA"
    EXPANSION_RETRY_DENY = "67FB"
    EXPANSION_SEND_BLOCK = "67FC"
    EXPANSION_OK_TO_SEND = "67FD"
    EXPANSION_REQ_TO_SEND = "67FE"
    EXPANSION_DIAGNOSTICS = "67FF"


class State(Enum):
    INACTIVE = "CSH_INACTIVE"
    DISABLED = "CSH_DISABLED"
    ENABLED = "CSH_ENABLED"
    IDLE = "CSH_IDLE"
    VEND = "CSH_VEND"
    REVALUE = "CSH_REVALUE"
    NEGATIVE_VEND = "CSH_NEGATIVE_VEND"


class VmcDisplayType(Enum):
    Limited = 0b000
    Ascii = 0b001


@dataclass
class VmcDisplay:
    rows: int
    columns: int
    type: VmcDisplayType


@dataclass
class SetupConfigDataCommandEvent(protocol.MdbCommandEvent):
    feature_level: Vmc.FeatureLevel
    display: VmcDisplay

    command: MdbCommand = field(default=MdbCommand.SETUP_CONFIG_DATA, init=False)


@dataclass
class SetupPriceCommandEvent(protocol.MdbCommandEvent):
    min_price: protocol.Money
    max_price: protocol.Money

    command: MdbCommand = field(default=MdbCommand.SETUP_PRICE_DATA, init=False)


@dataclass
class ExpansionRequestIdCommandEvent(protocol.MdbCommandEvent):
    manufacturer_code: str
    serial_number: str
    model_number: str
    software_version: str

    command: MdbCommand = field(default=MdbCommand.EXPANSION_REQUEST_ID, init=False)


@dataclass
class VendRequestCommandEvent(protocol.MdbCommandEvent):
    item_price: protocol.Money
    item_number: int

    command: MdbCommand = field(default=MdbCommand.VEND_REQUEST, init=False)


@dataclass
class VendSuccessCommandEvent(protocol.MdbCommandEvent):
    item_number: int

    command: MdbCommand = field(default=MdbCommand.VEND_SUCCESS, init=False)
