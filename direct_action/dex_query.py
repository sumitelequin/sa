import asyncio
import logging
import os
import sys
import typing as ty
 
from config import IP, PORT, USER, PASSWORD
from actp import connection, dex, session
from actp.util import logutil, util
 
logger = logging.getLogger(__name__)
script_name = os.path.basename(sys.argv[0])
 
async def run_dex_query(
    scope_keys: ty.List[str],
    fields: ty.List[str],
    frequency: int = 1000,
    is_snapshot: bool = True,
    no_triggers: ty.Optional[ty.List[str]] = None,
    contexts: ty.Optional[ty.List[str]] = None,
    output_csv_path: ty.Optional[str] = None,
):
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(handler=util.handle_asyncio_exceptions)
 
    act_connection = connection.ActConnection(ip=IP, port=PORT, loop=loop)
 
    try:
        await act_connection.connect()
        if not act_connection.is_connected():
            logger.error("❌ Could not connect to server.")
            return
 
        act_session = session.ActSession(
            act_connection=act_connection,
            user=USER,
            password=PASSWORD,
            appname=script_name,
        )
 
        logon_result = await act_session.logon()
        if not logon_result.Success:
            logger.error(f"❌ Logon failed: {logon_result.ErrorMsg}")
            return
 
        logger.info("✅ Logged in to DEX")
 
        def on_state_change(dq, new_status, err_msg, old_status):
            logger.info(f'DEX state: {old_status} ➡ {new_status} | {err_msg or "OK"}')
 
        def on_columns(dq, columns):
            logger.info(f'Columns received: {len(columns)}')
 
        def on_update(dq, update_count, num_rows, new_rows, updated_rows):
            logger.info(f'Rows updated: {len(updated_rows)}')
            for row in updated_rows:
                values = [f'{cell.column.name}:{cell.value_str()}' for cell in row.get_updated_cells(update_count)]
                logger.info(f'[{row}]: {", ".join(values)}')
 
            if output_csv_path:
                with open(output_csv_path, "w", encoding="utf-8", newline="") as f:
                    f.write(dq.as_csv())
 
            if is_snapshot:
                dq.stop()
                act_session.logout()
 
        query_data = dex.DexQueryData(
            scope_keys=scope_keys,
            fields=fields,
            frequency=frequency,
            is_snapshot=is_snapshot,
            no_triggers=no_triggers,
            contexts=contexts,
        )
 
        dq = dex.DexQuery(act_session=act_session, query_data=query_data)
        dq.add_handlers(
            state_change_handler=on_state_change,
            columns_received_handler=on_columns,
            update_handler=on_update
        )
        dq.start()
 
        await act_connection.wait_on_disconnect()
 
    finally:
        if act_connection:
            act_connection.disconnect()
        await util.cancel_pending_asyncio_tasks()