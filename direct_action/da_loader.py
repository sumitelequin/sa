import pandas as pd
from actp import session


# Grain symbols that use fractional pricing
GRAIN_SYMBOLS = [".ZC.", ".ZS.", ".ZW.", ".KE."]
 
def is_grain_future(instr: str) -> bool:
    return any(symbol in instr for symbol in GRAIN_SYMBOLS)
 
def convert_fractional_price(value: str) -> str:
    try:
        fval = float(value)
        whole = int(fval)
        frac = round((fval - whole) * 8)  # Convert to 1/8ths
        return f"{whole}" if frac == 0 else f"{whole}-{frac}"
    except ValueError:
        return value  # Return original if not convertible to float
 
def load_direct_actions_from_csv(filepath: str) -> list[session.DirectActionData]:
    df = pd.read_csv(filepath)
    # Filter rows where 'to_trade_today' is true/yes/1
    df = df[df['to_trade_global'].astype(str).str.lower().isin(['true', '1', 'yes'])]
    df = df[df['to_trade_today'].astype(str).str.lower().isin(['true', '1', 'yes'])]
 
    # Drop 'comments' column if it exists
    df = df.drop(columns=['comments'], errors='ignore')

    da_list = []
 
    for _, row in df.iterrows():
        name = row["name"]
        base_instrument = row["base_instrument"]
        action_status = row.get("status", "Disabled")
 
        is_grain = is_grain_future(base_instrument)
        reserved = {"name", "base_instrument", "status", "to_trade_today"}
 
        params = {}
        for col in df.columns:
            if col not in reserved:
                val = row[col]
                if pd.isna(val):
                    params[col] = ""
                else:
                    val_str = str(val)
                    if is_grain:
                        val_str = convert_fractional_price(val_str)
                    params[col] = val_str
 
        input_parameters = [
            session.StrProperty(name=k, value=v) for k, v in params.items()
        ]
 
        da_data = session.DirectActionData(
            name=name,
            base_instrument=base_instrument,
            additional_instruments=[],
            input_parameters=input_parameters,
            action_status=action_status,
        )
 
        da_list.append(da_data)

    return da_list