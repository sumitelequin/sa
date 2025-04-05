import asyncio
import logging
import os
import sys
import typing as ty

from actp import connection
from actp import dex
from actp import session
from actp.util import logutil
from actp.util import util

logger = logging.getLogger(__name__)
script_name = os.path.basename(sys.argv[0])

SAMPLE_USAGE = {
    r'Push updated PEs from csv file into Actant (See dex_query.py help for how to generate the csv file)':
        [
            fr"{script_name}  --user Shared --password ' --input_csv_path C:\dev\BTC_PEs.csv",
        ]
}


async def run(
        ip: str,
        port: int,
        user: str,
        password: str,
        input_csv_path: ty.Optional[str] = None,
):
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(handler=util.handle_asyncio_exceptions)

    act_connection = connection.ActConnection(ip=ip, port=port, loop=loop)
    try:
        await act_connection.connect()
        if not act_connection.is_connected():
            return

        act_session = session.ActSession(act_connection=act_connection, user=user, password=password, appname=script_name)
        on_logon: session.LogonResponse = await act_session.logon()
        if on_logon.Success:
            logger.info(f'Successfully logged in')
        else:
            logger.info(f'Failed to log in. msg:"{on_logon.ErrorMsg}"')
            return

        if input_csv_path is None:
            logger.error(f'Nothing to do, exiting')
            act_session.logout()

        def on_table_update_response(client_id: int, err_msg: str):
            if err_msg is None or len(err_msg) == 0:
                logger.info(f'Table update applied successfully')
            else:
                logger.info(f'Error applying table update: {err_msg}')
            act_session.logout()

        with open(file=input_csv_path, mode='r', newline='', encoding='utf-8') as inp_csv_file:
            input_csv = inp_csv_file.read()
            dex_table_update = dex.from_csv(csv_str=input_csv)
            if dex_table_update is None:
                logger.error(f'Failed to parse "{input_csv_path}" contents into csv')
            logger.info(f'Parsed "{input_csv_path}" contents into csv')
            table_update = dex_table_update.to_table_update()
            act_session.dex_sub_session.update_table(table_update=table_update, ack_handler=on_table_update_response)

        await act_connection.wait_on_disconnect()
    finally:
        if act_connection is not None:
            act_connection.disconnect()
        await util.cancel_pending_asyncio_tasks()


def main():
    parser = util.get_arg_parser(desc="Run a dex tabel update", examples=SAMPLE_USAGE)
    util.add_act_connection_args(parser=parser)
    parser.add_argument('-inp_csv', '--input_csv_path', help='Path to csv file with updates to send to Actant', required=True)
    parser.add_argument('-ll', '--loglevel', help='Level at which to log (DEBUG, INFO, WARNING, ERROR, CRITICAL)', required=False, default='INFO')
    parser.set_defaults(snapshot=False)
    args = parser.parse_args()
    logutil.configure_simple_console_logging(log_level=args.loglevel, timed=True)

    try:
        asyncio.run(run(
            ip=args.ip, port=args.port,
            user=args.user, password=args.password,
            input_csv_path=args.input_csv_path
        ))
    except KeyboardInterrupt:
        logger.info(f'Exiting on Ctrl-C')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        logger.exception('Caught exception in main()')
