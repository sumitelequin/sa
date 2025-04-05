import pandas as pd
from actp import session

def load_direct_actions_from_csv(filepath: str) -> list[session.DirectActionData]:
    df = pd.read_csv(filepath)
    da_list = []

    for _, row in df.iterrows():
        name = row["name"]
        base_instrument = row["base_instrument"]
        action_status = row.get("status", "Disabled")

        reserved = {"name", "base_instrument", "status"}
        params = {
            col: str(row[col]) for col in df.columns if col not in reserved and pd.notna(row[col])
        }

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
