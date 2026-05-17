import contextlib
import importlib
import io
from unittest.mock import patch


def import_app():
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return importlib.import_module("reminders_app_v3")


def reset_session_state(app, **values):
    state = app.st.session_state
    for key in list(state.keys()):
        del state[key]
    state.update(values)
    return state


def sample_reminder_row(**overrides):
    row = {
        "Client Name": "Client A",
        "Animal Name": "Pet A",
        "Plan Item": "Rabies",
        "Reminder Date": "01 Jun 2026",
        "Due Date": "01 Jun 2026",
        "Charge Date": "01 Jun 2025",
        "Qty": "1",
        "Days": "365",
    }
    row.update(overrides)
    return row


@contextlib.contextmanager
def quiet_busy_overlay(*_args, **_kwargs):
    yield


class TrackerCapture:
    def __init__(self, app):
        self.app = app
        self.calls = []

    def append_row(self, title, headers, values):
        self.calls.append({
            "title": title,
            "headers": headers,
            "values": values,
        })
        return True

    def patch_append_row(self):
        return patch.object(self.app, "append_tracker_row", side_effect=self.append_row)

    def action_records(self):
        records = []
        for call in self.calls:
            if call["title"] != self.app.ACTION_TRACKER_WORKSHEET:
                continue
            record = self.app.action_tracker_values_to_record(call["headers"], call["values"])
            if record:
                records.append(record)
        return records
