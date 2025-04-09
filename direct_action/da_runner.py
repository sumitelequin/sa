import asyncio
import contextlib
import logging
import typing as ty
from actp import connection, session
from actp.util import util

logger = logging.getLogger(__name__)

async def run_all_direct_actions(
    ip: str,
    port: int,
    user: str,
    password: str,
    da_list: list[session.DirectActionData]
):
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(handler=util.handle_asyncio_exceptions)

    act_connection = connection.ActConnection(ip=ip, port=port, loop=loop)

    try:
        await act_connection.connect()
        if not act_connection.is_connected():
            logger.error("❌ Could not connect to server.")
            return

        act_session = session.ActSession(
            act_connection=act_connection,
            user=user,
            password=password,
            appname="DA Runner",
        )

        logon_result: session.LogonResponse = await act_session.logon()
        if not logon_result.Success:
            logger.error(f"❌ Logon failed: {logon_result.ErrorMsg}")
            return

        logger.info("✅ Logged in successfully.")

        for da_data in da_list:
            logger.info(f"🚀 Sending Direct Action request for: {da_data.base_instrument}")
            done_event = asyncio.Event()

            def on_create_da_callback(
                client_id: session.ClientId,
                err_msg: session.ErrMsg,
                name: ty.Optional[session.DirectActionName],
                status: ty.Optional[session.AutomationStatus]
            ):
                if err_msg:
                    logger.error(f"❌ Failed to create direct action: {err_msg}")
                else:
                    logger.info(f"✅ Created Direct Action '{name}' with status '{status}'")
                done_event.set()

            act_session.algo_sub_session.create_direct_action(
                direct_action=da_data,
                callback=on_create_da_callback
            )

            await done_event.wait()

        act_connection.disconnect()
        await act_connection.wait_on_disconnect()

    finally:
        if act_connection:
            act_connection.disconnect()
        pending = asyncio.all_tasks()
        for task in pending:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
