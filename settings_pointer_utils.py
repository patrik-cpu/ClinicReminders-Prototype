import gspread


def settings_col_index(headers, name: str) -> int:
    return headers.index(name) + 1

def get_settings_row_for_clinic(sheet, clinic_id: str, clinic_id_col: str = "ClinicID"):
    all_vals = sheet.get_all_values()
    headers = all_vals[0]
    clinic_col = settings_col_index(headers, clinic_id_col)
    row_idx = None
    for i, r in enumerate(all_vals[1:], start=2):
        if r[clinic_col - 1].strip().lower() == clinic_id.strip().lower():
            row_idx = i
            break
    if row_idx is None:
        raise ValueError("ClinicID not found in settings sheet")
    return headers, row_idx


def update_dataset_pointer_cells(
    *,
    sheet,
    headers,
    row_idx: int,
    file_id: str,
    filename: str,
    updated_at: str,
    dataset_file_id_col: str,
    dataset_updated_at_col: str,
    retry_fn,
):
    """
    Update the 3 dataset pointer columns in one request to reduce partial-update risk.
    """
    if row_idx < 2:
        raise ValueError("row_idx must be >= 2 (row 1 is headers)")

    values = [[file_id, filename, updated_at]]
    rng = (
        f"{gspread.utils.rowcol_to_a1(row_idx, settings_col_index(headers, dataset_file_id_col))}:"
        f"{gspread.utils.rowcol_to_a1(row_idx, settings_col_index(headers, dataset_updated_at_col))}"
    )
    retry_fn(
        sheet.batch_update,
        [{"range": rng, "values": values}],
        value_input_option="RAW",
    )
