import asyncio
import contextlib
import logging
import os
import sys
import typing as ty

from actp import connection, session
from actp.util import logutil, util

logger = logging.getLogger(__name__)
script_name = os.path.basename(sys.argv[0])


async def run(
    ip: str,
    port: int,
    user: str,
    password: str,
    da_data: session.DirectActionData
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
            appname=script_name,
        )

        logon_result: session.LogonResponse = await act_session.logon()
        if logon_result.Success:
            logger.info("✅ Logged in successfully.")
        else:
            logger.error(f"❌ Logon failed: {logon_result.ErrorMsg}")
            return

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
            act_connection.disconnect()

        logger.info("🚀 Sending Direct Action request...")
        act_session.algo_sub_session.create_direct_action(
            direct_action=da_data,
            callback=on_create_da_callback
        )

        await act_connection.wait_on_disconnect()

    finally:
        if act_connection:
            act_connection.disconnect()
        # Clean up remaining async tasks
        pending = asyncio.all_tasks()
        for task in pending:
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task


def main():
    # ✅ Configuration - Replace these with args or config if needed
    ip = "10.16.6.165"
    port = 4724
    user = "SUMIT"
    password = "Iamnotmymind@123#"
    daname = "sm__da__bestbid"
    baseinstrument = "XCME.CB.F.F.MAY25.JUN25.0"
    params = {"BS": "-10", "BC": "-6", "BWQ": "1"}
    additional_instruments = []  # Add NamedInstrument instances if needed
    action_status = "Disabled"

    # 🛠️ Setup logging
    logutil.configure_simple_console_logging()
    logging.getLogger().setLevel(logging.INFO)

    with util.LogCompletionTiming(logger_func=logger.info):
        input_parameters = [
            session.StrProperty(name=k, value=v) for k, v in params.items()
        ]

        da_data = session.DirectActionData(
            name=daname,
            base_instrument=baseinstrument,
            additional_instruments=additional_instruments,
            input_parameters=input_parameters,
            action_status=action_status,
        )

        asyncio.run(run(ip=ip, port=port, user=user, password=password, da_data=da_data))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Caught exception in main()")
