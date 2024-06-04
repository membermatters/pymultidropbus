from dataclasses import dataclass, field
from enum import Enum
import logging

from pymultidropbus import helpers

logging.basicConfig()
logger = logging.getLogger("pymultidropbus")


class BindCmdBuilder:
    # thanks https://stackoverflow.com/questions/73103155/in-python-how-do-i-give-each-member-of-an-enum-its-own-implementation-of-an-enu
    bound_methods = {}

    def __init__(self, name=None):
        self.name = name

    def __call__(self, func):
        def wrapper(wrapped_self, *args, **kwargs):
            # try and lookup the bound method, if it doesn't exist, use the original function
            bound_method = self.bound_methods.get((func.__qualname__, wrapped_self.name))
            if bound_method:
                return bound_method(wrapped_self, *args, **kwargs)
            else:
                if kwargs:
                    raise ValueError(f"The default {func.__qualname__} implementation does not accept keyword arguments.")
                if args:
                    raise ValueError(f"The default {func.__qualname__} implementation does not accept positional arguments.")
                return func(wrapped_self, *args, **kwargs)

        if self.name:
            self.bound_methods[(func.__qualname__, self.name)] = func
        return wrapper


class MdbCommand(str, Enum):
    def __str__(self):
        return str(self.value)

    def __add__(self, other):
        return self.value + other

    def build(self) -> str:
        """Builds a command string with the given command and data."""
        return self.value

    UNKNOWN = "-1"
    ACK = "00"
    NAK = "FF"
    RET = "AA"


UNKNOWN_ITEM_NUMBER = 0xFFFF
UNKNOWN_MONEY_VALUE = 2 ** 16
MAX_MONEY_VALUE = 2 ** 16 - 1
MIN_MONEY_VALUE = 0


@dataclass(frozen=True)
class Money:
    cents: int
    vmc_cents: int = field(init=False)
    vmc_hex: str = field(init=False)
    dollars: float = field(init=False)
    formatted_dollars: str = field(init=False)
    scaling_factor: int = 1

    def __str__(self):
        return self.formatted_dollars

    def __post_init__(self):
        object.__setattr__(self, 'vmc_cents', int(self.cents/self.scaling_factor))
        if self.vmc_cents > MAX_MONEY_VALUE:
            logger.error(f"Money value of {self.vmc_cents} cents exceeds maximum value of {MAX_MONEY_VALUE}. This value"
                         f" is being automatically set to 'unknown' when sending to the VMC but the cents and dollars"
                         f"properties will store the original amount.")
            object.__setattr__(self, 'vmc_cents', MAX_MONEY_VALUE)

        hex_value = helpers.cents_to_hex(self.vmc_cents)
        object.__setattr__(self, 'vmc_hex', hex_value)
        object.__setattr__(self, 'dollars', self.cents / 100)
        object.__setattr__(self, 'formatted_dollars', f"${round(self.dollars, 2)}")

    @classmethod
    def from_vmc_hex(cls, hex_value: str, scaling_factor: int = 1):
        int_value = helpers.hex_to_int(hex_value) * scaling_factor
        return Money(int_value, scaling_factor=scaling_factor)


@dataclass
class MdbCommandEvent:
    command: MdbCommand


@dataclass
class UnknownCommandEvent(MdbCommandEvent):
    raw_cmd: str

    command: MdbCommand = field(default=MdbCommand.UNKNOWN, init=False)

@dataclass
class AckCommandEvent(MdbCommandEvent):
    command: MdbCommand = field(default=MdbCommand.ACK)


@dataclass
class NakCommandEvent(MdbCommandEvent):
    command: MdbCommand = field(default=MdbCommand.NAK)


@dataclass
class RetCommandEvent(MdbCommandEvent):
    command: MdbCommand = field(default=MdbCommand.RET)
