from config import IP, PORT, USER, PASSWORD
from da_loader import load_direct_actions_from_csv
from da_runner import run_all_direct_actions
import asyncio
import logging
from actp.util import logutil, util

def main():
    logutil.configure_simple_console_logging()
    logging.getLogger().setLevel(logging.INFO)

    da_list = load_direct_actions_from_csv("orders__da__bestbid_n_bestask.csv")

    with util.LogCompletionTiming(logger_func=logging.info):
        try:
            asyncio.run(run_all_direct_actions(IP, PORT, USER, PASSWORD, da_list))
        except Exception:
            logging.exception("❌ Error sending Direct Actions")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("Caught exception in main()")
