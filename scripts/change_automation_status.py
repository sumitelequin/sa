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
    r'Enable quotes on XBIT.BTC.O':
        [
            f'{script_name} --product XBIT.BTC.O --automation_type QUOTES --new_status Enabled',
            f'{script_name} -prod XBIT.BTC.O -auto QUOTES -status Enabled',
        ]
}


async def run(
        ip: str,
        port: int,
        user: str,
        password: str,
        product: str,
        automation_type: str,
        new_status: str
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

        def on_query_state_change(dq: dex.DexQuery, new_status: dex.DexQueryState, err_msg: str, old_status: dex.DexQueryState):
            if err_msg is None or len(err_msg) == 0:
                logger.info(f'Query state changed: {new_status} (from {old_status})')
            else:
                logger.info(f'Query state changed: {new_status} (from {old_status}), msg:{err_msg}')
                act_session.logout()

        def on_query_update(dq: dex.DexQuery, update_count: int, num_rows: int, new_rows: ty.List[dex.DexRow], new_updated_rows: ty.List[dex.DexRow]):
            logger.info(f'Query update. UpdateCount:{update_count}, NumRows:{num_rows}, NumNewRows:{len(new_rows)}, NumNewUpdatedRows: {len(new_updated_rows)}')
            if len(new_rows) != 1:
                logger.error(f'Did not get expected row. NumRows:{len(new_rows)}')
                act_session.logout()
                return
            row = new_rows[0]
            cell = row.get_cell_by_name("AUTO.IID")
            iid = cell.value_str()
            logger.info(f'Product {product} has iid {iid}')

            def on_automation_update_response(client_id: int, err_msg: str):
                if err_msg is None or len(err_msg) == 0:
                    logger.info(f'Successfully applied automation update')
                else:
                    logger.info(f'Error applying automation update: {err_msg}')
                act_session.logout()

            automation_update = session.AutomationUpdate(auto_control_type=automation_type, automation_status=new_status)
            logger.info(f'Sending automation update {automation_update} on product {product} with iid "{iid}"')
            pau = session.ProductAutomationUpdate(product=product, iid=iid, automation_updates=[automation_update])
            act_session.autocontrol_sub_session.send_automation_updates(product_updates=[pau], callback=on_automation_update_response)

        logger.info(f'Getting AUTO.IID')
        query_data = dex.DexQueryData(scope_keys=[product], fields=["AUTO.IID"], is_snapshot=True)
        dex_query = dex.DexQuery(act_session=act_session, query_data=query_data)
        dex_query.add_handlers(state_change_handler=on_query_state_change, update_handler=on_query_update)
        dex_query.start()

        await act_connection.wait_on_disconnect()
    finally:
        if act_connection is not None:
            act_connection.disconnect()
        await util.cancel_pending_asyncio_tasks()


def main():
    parser = util.get_arg_parser(desc="Change a product automation type's automation status", examples=SAMPLE_USAGE)
    util.add_act_connection_args(parser=parser)
    parser.add_argument('-prod', '--product', help='The product to change automation', required=True)
    parser.add_argument('-auto', '--automation_type', help='The automation type to change', required=True)
    parser.add_argument('-status', '--new_status', help='The automation status to set', required=True)
    parser.add_argument('-ll', '--loglevel', help='Level at which to log (DEBUG, INFO, WARNING, ERROR, CRITICAL)', required=False, default='INFO')
    args = parser.parse_args()
    logutil.configure_simple_console_logging(log_level=args.loglevel)

    try:
        with util.LogCompletionTiming(logger_func=logger.info):
            asyncio.run(run(user=args.user, password=args.password, ip=args.ip, port=args.port,
                            product=args.product, automation_type=args.automation_type, new_status=args.new_status))
    except KeyboardInterrupt:
        logger.info(f'Exiting on Ctrl-C')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        logger.exception('Caught exception in main()')
