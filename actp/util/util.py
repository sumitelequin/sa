import argparse
import asyncio
import contextlib
import logging
import sys
import time
import typing as ty
# DO NOT IMPORT from ..act, it prevents future usage of util inside that act.* file

from ..proto import Act_pb2 as act_pb


class ClassHasEquality(object):
    """ Implement equality as dictionary check """

    # https://stackoverflow.com/a/25176504/31130

    def __eq__(self, other: ty.Any) -> bool:
        """ Check dictionary to implement equality """
        if other is self:
            return True
        if type(other) is type(self):
            return self.__dict__ == other.__dict__
        return False

    def __hash__(self) -> int:
        """ Needed for sets """
        return hash(tuple(sorted(self.__dict__.items())))


def print_invocation(logseverity: int = logging.INFO) -> None:
    """ Print command-line arguments """
    logger = logging.getLogger(__name__)
    logger.log(logseverity, 'Invocation:')
    logger.log(logseverity, '    %s', ' '.join([x for x in sys.argv]))


def print_args(args: argparse.Namespace, logseverity: int = logging.INFO) -> None:
    """ Print arguments returned by ArgumentParser """
    assert isinstance(args, argparse.Namespace)
    logger = logging.getLogger(__name__)
    logger.log(logseverity, 'Args:')
    for key, val in sorted(vars(args).items()):
        logger.log(logseverity, '    %s: %s', key, val)


def get_hrsminssecs(secs_str: str) -> str:
    ''' Takes time interval in seconds and returns 'hrs:mins:secs' string '''
    try:
        secs = int(secs_str)
    except ValueError as val_err:
        raise Exception(f'Cannot convert from secs to hrs:mins:secs string. Invalid secs. Secs:{secs_str}') from val_err
    hrs = int(int(secs) / (60 * 60))
    secs -= hrs * 60 * 60
    mins = int(int(secs) / 60)
    secs -= mins * 60
    return '{:02d}:{:02d}:{:02d}'.format(hrs, mins, secs)


class CustomFormatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
    """" Combine the two formatters so we can have both defaults and formatted epilog for examples """
    pass


def get_arg_parser(desc: str, examples: ty.Any = None) -> argparse.ArgumentParser:
    """ Return ArgumentParser with custom formatter and epilog constructed from examples """
    assert isinstance(desc, str)

    # assert isinstance(examples, dict)

    def _get_epilog_text():
        nonlocal examples
        if not examples:
            return ''
        examples_str = 'Examples:\n'
        if isinstance(examples, str):
            examples_str += examples
        elif isinstance(examples, dict):
            for explanation, usage in examples.items():
                if isinstance(usage, str):
                    usage_str = usage
                elif isinstance(usage, list):
                    usage_str = '\n'.join(['  ' + ue for ue in usage])
                else:
                    raise Exception('Unhandled usage type')
                examples_str += explanation + ':\n' + usage_str + '\n\n'
        return examples_str

    return argparse.ArgumentParser(description=desc, epilog=_get_epilog_text(), formatter_class=CustomFormatter)


LoggerFuncType = ty.Callable[[str], None]


class LogCompletionTiming(object):
    """Context manager for logging the start and end times"""

    def __init__(self, logger_func: ty.Optional[LoggerFuncType] = None, msg: ty.Optional[str] = None, datetime_format: str = "%y/%m/%d %H:%M:%S") -> None:
        assert logger_func is None or callable(logger_func)
        self.logger_func = logger_func
        self.msg = msg
        self.datetime_format = datetime_format
        self.start = None
        self.start_ts = None

    def __enter__(self) -> None:
        self.start = time.strftime(self.datetime_format)
        self.start_ts = time.perf_counter()

    def __exit__(self, exc_type, exc_value, traceback):
        end = time.strftime(self.datetime_format)
        end_ts = time.perf_counter()
        interval_secs = end_ts - self.start_ts
        if self.logger_func:
            msg = f'{self.msg}. ' if self.msg else ''
            self.logger_func(f'{msg}Completed at {end} in {get_hrsminssecs(interval_secs)}')


def handle_asyncio_exceptions(l: asyncio.AbstractEventLoop, context: ty.Dict[str, str]):
    logger = logging.getLogger(__name__)
    message = context['message']
    exc = context['exception']
    handle = context['handle']

    if isinstance(exc, asyncio.InvalidStateError):
        # error when Ctrl-C is pressed, ignore
        return

    if isinstance(exc, KeyError):
        if '_ProactorReadPipeTransport._loop_reading' in message:
            # ignore, don't know what causes this but happens occasionally on exit and seems harmless
            # investigate later if can find the time
            return

    logger.info(f'asyncio exception: {context}')
    pass


async def cancel_pending_asyncio_tasks():
    pending = asyncio.all_tasks()
    for task in pending:
        if task.cancelled():
            continue
        task.cancel()
        with contextlib.suppress(asyncio.exceptions.CancelledError):
            await task


def add_act_connection_args(parser: argparse.ArgumentParser):
    parser.add_argument('-user', '--user', help='The user', required=True)
    parser.add_argument('-pass', '--password', help='The password', required=True)
    parser.add_argument('-ip', '--ip', help='The Act address', default='127.0.0.1')
    parser.add_argument('-p', '--port', help='The Act port', default=4722, type=int)


def log_requests(request: act_pb.Request):
    logger = logging.getLogger(__name__)
    logger.info(f'[Request]:\n[\n{request}]')


def log_responses(response: act_pb.Response):
    logger = logging.getLogger(__name__)
    logger.info(f'[Response]:\n[\n{response}]')


def log_incoming_data(data: bytes):
    logger = logging.getLogger(__name__)
    logger.info(f'[Received]: {len(data)}')


def log_outgoing_data(data: bytes):
    logger = logging.getLogger(__name__)
    logger.info(f'[Sent]: {len(data)}')
