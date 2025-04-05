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
    r'Get BID,ASK snapshot on XCME.ES.F':
        [
            f"{script_name}  --scope_keys XCME.ES.F --fields bid,ask --snapshot --ip 192.168.45.117 --user Shared --password ' ",
        ],
    r'Get XBIT.BTC.O PEs into a csv file (to update and write back using dex_table_update.py)':
        [
            f"{script_name} --scope_keys XBIT.BTC.O --fields pe1,pe2,pe3 --snapshot --output_csv_path C:\dev\BTC_PEs.csv --user Shared --password ' --ip 192.168.45.117 --port 4724",
        ],
    r'Get running algos':
        [
            f"{script_name} --scope_keys GLOBAL --fields action.name,action.instrument,action.status,action.side,action.origin,action.numorders,action.quantity,action.price,action.scripterror --snapshot --ip 192.168.45.117 --user Shared --password ' ",
        ],
    r'Get some automation details':
        [
            f"{script_name} --scope_keys \"GLOBAL>FILTER.PRODUCTTYPES(OFKT)\" --fields auto.quotes,auto.iid,auto.quotesscript,auto.hitlift,auto.autohedge,auto.autohedgealgo,auto.scanner1,auto.scanner1algo --snapshot --ip 192.168.45.117 --user Shared --password ' ",
        ],
    r'Get OTC strategy details':
        [
            f"{script_name} --scope_keys GLOBAL --fields otcstrat.instrument,otcstrat.multilinename,otcstrat.ownnbid,otcstrat.product,otcstrat.ownbid,nbid,bid,ownorderbid,otcstrat.marketnbid,otcstrat.marketbid,otcstrat.theor,otcstrat.brokerid,ask,ownorderask,otcstrat.marketask,nask,otcstrat.marketnask,otcstrat.ownask,otcstrat.ownnask,otcstrat.uprice,otcstrat.uuid,otcstrat.retired,otcstrat.foreign --snapshot --ip 192.168.45.117 --user Shared --password ' ",
        ],
}


async def run(
        ip: str,
        port: int,
        user: str,
        password: str,
        scope_keys: ty.List[str],
        fields: ty.List[str],
        frequency: int,
        is_snapshot: bool,
        no_triggers: ty.Optional[ty.List[str]] = None,
        contexts: ty.Optional[ty.List[str]] = None,
        output_csv_path: ty.Optional[str] = None,
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

        def on_columns_received(dq: dex.DexQuery, columns: ty.List[dex.DexColumn]):
            logger.info(f'Columns received. NumColumns:{len(columns)}')

        def on_update(dq: dex.DexQuery, update_count: int, num_rows: int, new_rows: ty.List[dex.DexRow], new_updated_rows: ty.List[dex.DexRow]):
            logger.info(f'Query update. UpdateCount:{update_count}, NumRows:{num_rows}, NumNewRows:{len(new_rows)}, NumNewUpdatedRows: {len(new_updated_rows)}')

            for row in new_updated_rows:
                updated_values = [f'{cell.column.name}:{cell.value_str()}' for cell in row.get_updated_cells(update_count=update_count)]
                update_str = ', '.join(updated_values)
                logger.info(f'[{row}]: {update_str}')

            if output_csv_path is not None:
                csv = dq.as_csv()
                # https://stackoverflow.com/a/3191811
                with open(file=output_csv_path, mode='w', newline='', encoding='utf-8') as out_csv_file:
                    out_csv_file.write(csv)
                    out_csv_file.flush()

            if is_snapshot:
                dq.stop()
                act_session.logout()

        query_data = dex.DexQueryData(scope_keys=scope_keys, fields=fields, frequency=frequency, is_snapshot=is_snapshot, no_triggers=no_triggers, contexts=contexts)
        dex_query = dex.DexQuery(act_session=act_session, query_data=query_data)
        dex_query.add_handlers(state_change_handler=on_query_state_change, columns_received_handler=on_columns_received, update_handler=on_update)
        dex_query.start()

        await act_connection.wait_on_disconnect()
    finally:
        if act_connection is not None:
            act_connection.disconnect()
        await util.cancel_pending_asyncio_tasks()


def main():
    parser = util.get_arg_parser(desc="Run a DEX query", examples=SAMPLE_USAGE)
    util.add_act_connection_args(parser=parser)
    parser.add_argument('-s', '--scope_keys', help='The DEX scope keys', required=True)
    parser.add_argument('-f', '--fields', help='The DEX fields', required=True)
    parser.add_argument('-ntf', '--non_triggering_fields', help='The non-triggering fields')
    parser.add_argument('-c', '--context', help='Context for the query')
    parser.add_argument('-sn', '--snapshot', help='Is snapshot query', action='store_true')
    parser.add_argument('-fr', '--frequency', help='Frequency for non-snapshot queries', default=1000, type=int)
    parser.add_argument('-out_csv', '--output_csv_path', help='Path to csv file to create or overwrite with dex query output')
    parser.add_argument('-ll', '--loglevel', help='Level at which to log (DEBUG, INFO, WARNING, ERROR, CRITICAL)', required=False, default='INFO')
    parser.set_defaults(snapshot=False)
    args = parser.parse_args()
    logutil.configure_simple_console_logging(log_level=args.loglevel, timed=True)

    scope_keys = args.scope_keys.split(',')
    fields = args.fields.split(',')

    non_triggering_fields = None
    if args.non_triggering_fields is not None:
        non_triggering_fields = args.non_triggering_fields.split(',')
    context = None
    if args.context is not None:
        context = args.context.split(',')
    try:
        asyncio.run(run(
            ip=args.ip, port=args.port,
            user=args.user, password=args.password,
            scope_keys=scope_keys, fields=fields,
            frequency=args.frequency, is_snapshot=args.snapshot,
            no_triggers=non_triggering_fields, contexts=context,
            output_csv_path=args.output_csv_path
        ))
    except KeyboardInterrupt:
        logger.info(f'Exiting on Ctrl-C')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        logger.exception('Caught exception in main()')
