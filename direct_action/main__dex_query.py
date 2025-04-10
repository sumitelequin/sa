import asyncio
import logging
from dex_query import run_dex_query
from actp.util import logutil
 
def main():
    logutil.configure_simple_console_logging()
    logging.getLogger().setLevel(logging.INFO)
 
    asyncio.run(run_dex_query(
        scope_keys=["XCME.ZS.NOV26", "XCME.ZC.DEC26", "XCME.F.F."],  # ✅ update this as needed
        fields=["bid", "ask"],     # ✅ customize fields
        is_snapshot=True,
        output_csv_path="zc_snapshot.csv"
    ))
 
if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("❌ Error running DEX query")