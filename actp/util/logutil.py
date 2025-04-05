"""
Help mainly with logging to console
"""
import contextlib
import logging
import sys
import typing as ty

# globals

MESSAGE_FORMAT = '%(message)s'
SEVERITY_FORMAT = '%(levelname)6s'
TIME_FORMAT = '%(asctime)s'
NAME_FORMAT = '%(name-20s)s'
THREAD_FORMAT = '%(thread)4s'

DEFAULT_CONSOLE_FORMAT = ' '.join([SEVERITY_FORMAT, NAME_FORMAT, MESSAGE_FORMAT])
DEFAULT_LOG_FORMAT = ' '.join([TIME_FORMAT, THREAD_FORMAT, SEVERITY_FORMAT, NAME_FORMAT, MESSAGE_FORMAT])

DEFAULT_DATE_FORMAT = '%y%m%d %H%M%S'
SIMPLE_DATE_FORMAT = '%H:%M:%S'


# pylint: disable-msg=too-few-public-methods
class SingleLevelFilter(logging.Filter):
    """ Filters in or out all messages at given LEVEL """

    # https://stackoverflow.com/a/1383365

    def __init__(self, passlevel: int, reject: bool) -> None:
        self.passlevel = passlevel
        self.reject = reject
        super().__init__()

    def filter(self, record: logging.LogRecord) -> bool:
        if self.reject:
            return record.levelno != self.passlevel
        return record.levelno == self.passlevel


# pylint: disable-msg=too-few-public-methods
class MaxLevelFilter(logging.Filter):
    """ Filters (lets through) all messages with level < LEVEL """

    # https://stackoverflow.com/a/24956305

    def __init__(self, level: int) -> None:
        self.level = level
        super().__init__()

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno < self.level  # "<" instead of "<=": since logger.setLevel is inclusive, this should be exclusive


def reset_logger_config() -> None:
    """ Remove all handlers on the root logger logger """
    # Reconfigure logger config
    # https://stackoverflow.com/a/14602233
    root_logger = logging.getLogger()
    while root_logger.handlers:
        root_logger.removeHandler(root_logger.handlers[-1])


def configure_console_logging(log_level: ty.Optional[str] = None, console_fmt: str = None, date_fmt: str = None) -> None:
    """ Configure console logging """
    assert log_level is None or isinstance(log_level, str)  # 'DEBUG' not logging.DEBUG
    reset_logger_config()
    new_lvl = None
    if log_level is not None:
        with contextlib.suppress(AttributeError):
            new_lvl = getattr(logging, log_level)
    if new_lvl is None:
        new_lvl = logging.INFO

    if console_fmt is None:
        console_fmt = DEFAULT_CONSOLE_FORMAT
    if date_fmt is None:
        date_fmt = ''

    # logging.basicConfig(stream=sys.stdout, level=new_lvl, format=console_fmt, datefmt=date_fmt)

    formatter = logging.Formatter(fmt=console_fmt, datefmt=date_fmt)

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    stdout_handler.setLevel(new_lvl)
    stdout_handler.addFilter(MaxLevelFilter(logging.WARNING))

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    stderr_handler.setLevel(max(new_lvl, logging.WARNING))

    root_logger = logging.getLogger()
    root_logger.setLevel(new_lvl)
    root_logger.addHandler(stdout_handler)
    root_logger.addHandler(stderr_handler)


# pylint: disable-msg=invalid-name
def configure_simple_console_logging(log_level: ty.Optional[str] = None, timed: bool = False, log_severity: bool = True) -> None:
    """ Wrapper to configure console logging to a simpler format """
    components = []
    date_fmt = None
    if timed:
        components.append(TIME_FORMAT)
        date_fmt = SIMPLE_DATE_FORMAT
    if log_severity:
        components.append(SEVERITY_FORMAT)
    components.append(MESSAGE_FORMAT)
    console_fmt = ' '.join(components)
    configure_console_logging(log_level=log_level, console_fmt=console_fmt, date_fmt=date_fmt)


def get_file_logger(logfile_path: str, log_fmt: ty.Optional[str] = None, date_fmt: ty.Optional[str] = None, log_level: int = logging.INFO) -> logging.FileHandler:
    """ Wrapper to get a configured file logger """
    if log_fmt is None:
        log_fmt = DEFAULT_LOG_FORMAT
    if date_fmt is None:
        date_fmt = DEFAULT_DATE_FORMAT

    filehandler = logging.FileHandler(logfile_path)
    filehandler.setFormatter(logging.Formatter(fmt=log_fmt, datefmt=date_fmt))
    filehandler.setLevel(log_level)
    return filehandler


def add_file_logger(logfile_path: str, log_fmt: ty.Optional[str] = None, date_fmt: ty.Optional[str] = None, log_level: int = logging.INFO) -> logging.FileHandler:
    """ Add a file logger """
    filelogger = get_file_logger(logfile_path=logfile_path, log_fmt=log_fmt, date_fmt=date_fmt, log_level=log_level)
    rootlogger = logging.getLogger()
    rootlogger.addHandler(filelogger)
    return filelogger


class AddOptionalFileLogger(object):
    """Context manager for optionally adding and removing a file logger """

    def __init__(self, logfile_path: ty.Optional[str], log_fmt: ty.Optional[str] = None, date_fmt: ty.Optional[str] = None, log_level: int = logging.INFO) -> None:
        self.handler = None if not logfile_path else get_file_logger(logfile_path=logfile_path, log_fmt=log_fmt, date_fmt=date_fmt, log_level=log_level)
        self.root_logger = logging.getLogger()

    def __enter__(self) -> None:
        if self.handler:
            self.root_logger.addHandler(self.handler)

    def __exit__(self, exc_type: ty.Any, exc_value: ty.Any, traceback: ty.Any):
        if self.handler:
            self.root_logger.removeHandler(self.handler)
