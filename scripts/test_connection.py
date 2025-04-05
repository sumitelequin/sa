import asyncio
import logging
import os
import sys

from actp import connection
from actp import session
from actp.util import logutil
from actp.util import util

logger = logging.getLogger(__name__)
script_name = os.path.basename(sys.argv[0])

SAMPLE_USAGE = {
    r'Check connection to Actant configured with non-standard port':
        [
            f"{script_name}  --user SUMIT --password xxxxxx --ip 10.16.6.165 --port 4723",
        ]
}


async def run(ip: str, port: int, user: str, password: str):
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(handler=util.handle_asyncio_exceptions)

    act_connection = connection.ActConnection(ip=ip, port=port, loop=loop)
    try:
        def on_act_connection_status_change(ac: connection.ActConnection, new_state: connection.ActConnectionState, err_msg: str, old_state: connection.ActConnectionState):
            if new_state == connection.ActConnectionState.Disconnected:
                logger.error(f'Disconnected. msg: "{err_msg}"')
            if new_state == connection.ActConnectionState.Connected:
                logger.info(f'Connected')

        act_connection.add_state_change_handler(state_change_handler=on_act_connection_status_change)
        await act_connection.connect()
        if not act_connection.is_connected():
            return

        act_session = session.ActSession(act_connection=act_connection, user=user, password=password, appname=script_name)
        on_logon: session.LogonResponse = await act_session.logon()
        if on_logon.Success:
            logger.info(f'Successfully logged in')
        else:
            logger.info(f'Failed to log in. msg:"{on_logon.ErrorMsg}"')
        act_session.logout()
    finally:
        if act_connection is not None:
            act_connection.disconnect()
        await util.cancel_pending_asyncio_tasks()


def main():
    parser = util.get_arg_parser(desc="Test act connection", examples=SAMPLE_USAGE)
    util.add_act_connection_args(parser=parser)
    parser.add_argument('-ll', '--loglevel', help='Level at which to log (DEBUG, INFO, WARNING, ERROR, CRITICAL)', required=False, default='INFO')
    print('4')
    args = parser.parse_args()
    print('5')
    print(args)
    logutil.configure_simple_console_logging(log_level=args.loglevel)
    try:
        asyncio.run(run(ip=args.ip, port=args.port, user=args.user, password=args.password))
    except KeyboardInterrupt:
        logger.info(f'Exiting on Ctrl-C')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        logger.exception('Caught exception in main()')
