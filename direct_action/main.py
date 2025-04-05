from config import IP, PORT, USER, PASSWORD
from da_loader import load_direct_actions_from_csv
from da_runner import run_direct_action
import asyncio
import logging
from actp.util import logutil, util

def main():
    logutil.configure_simple_console_logging()
    logging.getLogger().setLevel(logging.INFO)

    da_list = load_direct_actions_from_csv("orders__da__bestbid_n_bestask.csv")

    with util.LogCompletionTiming(logger_func=logging.info):
        for da_data in da_list:
            try:
                asyncio.run(run_direct_action(IP, PORT, USER, PASSWORD, da_data))
            except Exception:
                logging.exception(f"❌ Error sending Direct Action for: {da_data.base_instrument}")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Caught exception in main()")
