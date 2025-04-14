import asyncio
import logging
from dex_query import run_dex_query
from actp.util import logutil
from datetime import datetime
import os

def main():
    logutil.configure_simple_console_logging()
    logging.getLogger().setLevel(logging.INFO)
    csv_folder="C:\\Users\\s.mishra\\OneDrive - QEC Capital\\Position Analysis\\"
    csv_file="{} snapshot.csv".format((datetime.now()).strftime('%Y%m%d'))

    asyncio.run(run_dex_query(
        scope_keys=["XCME.ZS.NOV26", 
                    "XCME.ZC.DEC26", 
                    "XCME.HE.F.F.FEB26.APR26.0", 
                    "XCME.HE.F.F.APR26.JUN26.0", 
                    "XCME.ZC.F.F.DEC25.MAR26.0",
                    "XCME.ZC.F.F.MAR26.MAY26.0",
                    "XCME.ZC.F.F.DEC26.MAR27.0",
                    "XCME.ZC.F.F.MAR27.MAY27.0"
                    ],  
        fields=["bid", "ask"],     
        is_snapshot=True,
        output_csv_path=os.path.join(csv_folder,csv_file)
    ))
 
if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("❌ Error running DEX query")