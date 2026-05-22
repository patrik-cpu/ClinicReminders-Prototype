# Performance Upload Pass

Date: 2026-05-19

## Executive Summary

The upload pipeline is safer than the earlier `PERFORMANCE_REPORT.md` baseline in several ways: file count/size/row/column limits now exist, upload summary caching is module-level only, existing datasets are passed into publish when already loaded, tracker rows for saved upload summaries are batched, and Drive uploads use resumable `MediaIoBaseUpload`.

The remaining upload performance and memory risks are still meaningful for large clinics. The highest-cost path is a successful upload save: uploaded file bytes are materialized, parsed DataFrames are cached, concatenated into a working DataFrame, copied/sanitized several times, possibly combined with a fully downloaded existing Drive dataset, serialized as one full CSV byte string, wrapped in another `BytesIO`, uploaded synchronously, then saved again into `st.session_state["working_df"]`.

The safest next fixes are small memory-lifetime reductions and duplicate parse/copy reductions, not a storage redesign.

## 1. Upload Parse Flow From File Input To Parsed DataFrame

Current flow:

1. `st.file_uploader(...)` accepts `csv`, `xls`, and `xlsx` files in the Upload Data section at `reminders_app_v3.py:10921`.
2. `_to_blob(uploaded)` at `reminders_app_v3.py:8397` checks declared size, calls `uploaded.getvalue()`, validates byte length, and returns `{"name": uploaded.name, "bytes": b}`.
3. `upload_fingerprint(file_blobs)` at `reminders_app_v3.py:8409` hashes every file name and full byte payload.
4. `summarize_uploads(file_blobs, UPLOAD_SUMMARY_SCHEMA_VERSION)` at `reminders_app_v3.py:8463` validates the collection, calls `process_file()` per blob, validates the DataFrame again, computes date bounds, and returns `(datasets, summary_rows)`.
5. `process_file(file_bytes, filename)` at `reminders_app_v3.py:6384` validates file size, wraps bytes in `BytesIO`, reads CSV via `pd.read_csv(... dtype=str ...)` or Excel via `pd.read_excel(... dtype=str)`, validates row/column limits, strips empty rows/headers, drops duplicate columns, applies aliases/PMS normalization, parses `ChargeDate`, and finalizes through `finalize_processed_upload_df()`.
6. Upload UI concatenates parsed DataFrames with `pd.concat(...)` at `reminders_app_v3.py:11088` or `reminders_app_v3.py:11095`, then stores a sanitized copy in `st.session_state["working_df"]`.

## 2. Cache Usage And Cache Keys

- `process_file(file_bytes, filename)` is `@st.cache_data(show_spinner=False)` at `reminders_app_v3.py:6384`.
  - Cache key is Streamlit's hash of full `file_bytes` plus `filename`.
  - Cost: the full file bytes participate in hashing and the parsed DataFrame result can remain in the data cache.

- `summarize_uploads(file_blobs, cache_version)` is `@st.cache_data(show_spinner=False)` at `reminders_app_v3.py:8463`.
  - Cache key is Streamlit's hash of the tuple of blob dicts, including every full byte payload, plus `UPLOAD_SUMMARY_SCHEMA_VERSION`.
  - Return value includes parsed DataFrames in `datasets`, so successful uploads can be cached both at per-file parse level and at multi-file summary level.

- `prepare_session_bundle(df, cache_key)` is `@st.cache_data(show_spinner=False)` at `reminders_app_v3.py:8484`, but `PRECOMPUTE_ANALYTICS_BUNDLE = False`, so the heavy bundle is not normally stored in session.

- `get_drive_service()` is `@st.cache_resource(show_spinner=False)` at `reminders_app_v3.py:3100`.
  - Good reuse: avoids rebuilding the Drive client every upload/download.

- `reset_uploaded_data_state(clear_cache=True)` can call `st.cache_data.clear()` at `reminders_app_v3.py:572`, but Upload Data file-change handling calls it with `clear_cache=False` at `reminders_app_v3.py:10946`.

## 3. Where File Bytes Are Stored

- Streamlit owns uploaded-file objects from `st.file_uploader`.
- `_to_blob()` materializes each file into Python bytes via `uploaded.getvalue()` at `reminders_app_v3.py:8405`.
- `file_blobs = tuple(_to_blob(f) for f in files)` holds all selected file bytes in local render scope at `reminders_app_v3.py:10958`.
- `upload_fingerprint()` hashes full bytes at `reminders_app_v3.py:8415`.
- `process_file()` wraps each byte payload in `BytesIO` at `reminders_app_v3.py:6395`.
- `summarize_uploads()` cache keys include the blob tuple, so the full bytes are used for cache hashing.
- `drive_download_bytes()` downloads Drive files into `BytesIO` and returns `fh.getvalue()` at `reminders_app_v3.py:3130-3138`.
- `publish_dataset_for_clinic()` creates full `out_bytes` with `merged_df.to_csv(...).encode("utf-8")` at `reminders_app_v3.py:4077`.
- `drive_upsert_csv_bytes()` wraps those bytes in another `BytesIO` for `MediaIoBaseUpload` at `reminders_app_v3.py:3479`.

## 4. Where DataFrames Are Stored In Session State Or Cache

Session state:

- `st.session_state["working_df"]` stores the loaded/saved clinic dataset after Drive load at `reminders_app_v3.py:3372`, after upload parse at `reminders_app_v3.py:11089` and `reminders_app_v3.py:11100`, after publish at `reminders_app_v3.py:11180`, and after removing a saved upload at `reminders_app_v3.py:9456`.
- `st.session_state["prepared_df"]` stores prepared reminder rows via `get_prepared_df()` at `reminders_app_v3.py:10256`.
- `st.session_state["bundle"]` can store analytics bundle output at `reminders_app_v3.py:9194`, but the guard currently disables precompute.
- `st.session_state["_active_reminder_window_cache"]` and `_stats_export_csv_cache` hold smaller derived DataFrame/CSV artifacts from prior performance passes.

Cache:

- `process_file()` caches normalized DataFrames.
- `summarize_uploads()` caches `(pms_name, df)` tuples and summary rows.
- `ensure_reminder_columns()` at `reminders_app_v3.py:10003`, statistics generated rows at `reminders_app_v3.py:12911`, and outcomes at `reminders_app_v3.py:13850` can cache DataFrames derived from `working_df`.

## 5. Upload Save And Publish Flow

Current save flow:

1. After parsing, upload UI creates `new_df = st.session_state["working_df"].copy()` at `reminders_app_v3.py:11110`.
2. It computes upload date bounds with `dataset_date_bounds(new_df)` at `reminders_app_v3.py:11113`.
3. It reads the existing dataset pointer via `get_existing_dataset_pointer()` at `reminders_app_v3.py:11119`.
4. If a pointer exists, it downloads and parses the existing Drive dataset before save confirmation using `load_existing_shared_df()` at `reminders_app_v3.py:11123`.
5. `save_uploaded_dataset()` calls `publish_dataset_for_clinic(... existing_df=existing_df)` at `reminders_app_v3.py:11147`, so publish does not repeat that download when `existing_df` is available.
6. `publish_dataset_for_clinic()` merges with `merge_dataset_update()` at `reminders_app_v3.py:4069`, serializes the full merged DataFrame at `reminders_app_v3.py:4077`, uploads to Drive at `reminders_app_v3.py:4097`, then updates the settings pointer at `reminders_app_v3.py:4107`.
7. After publish, `save_uploaded_dataset()` sanitizes and stores the merged DataFrame in `working_df`, updates upload history, batches `upload_saved` tracker rows through `record_dataset_tracker_events()`, records performance, updates uploader reset state, adds automatic patient exclusions, saves settings, and reruns.

Related remove flow:

- `remove_dataset_upload_at_index()` filters the current full `working_df`, serializes the remaining full DataFrame to CSV at `reminders_app_v3.py:9447`, uploads it, updates the pointer, and stores `working_df` again.

## 6. Google Drive Download And Upload Calls

- `drive_download_bytes(file_id, ...)` at `reminders_app_v3.py:3119`.
  - Uses `service.files().get_media(... supportsAllDrives=True)`.
  - Downloads chunks into `BytesIO` using `MediaIoBaseDownload`.
  - Enforces `DRIVE_TRANSFER_TIMEOUT_SECONDS` through elapsed wall-clock checks.

- `drive_find_file_id_by_name(filename, folder_id)` at `reminders_app_v3.py:3162`.
  - Uses `files().list(... pageSize=1 ...)` for pointer recovery.

- `drive_upsert_csv_bytes(file_bytes, filename, folder_id, existing_file_id, ...)` at `reminders_app_v3.py:3460`.
  - Uses `MediaIoBaseUpload(BytesIO(file_bytes), mimetype="text/csv", resumable=True)`.
  - Calls `files().update(...)` when `existing_file_id` exists, otherwise `files().create(...)`.
  - Upload is synchronous inside the Streamlit run.

- `load_shared_dataset_for_clinic()` downloads the saved dataset on login/load at `reminders_app_v3.py:3365`.
- `load_existing_shared_df()` downloads the saved dataset for publish/merge at `reminders_app_v3.py:3692`.
- `publish_dataset_for_clinic()` uploads the merged dataset at `reminders_app_v3.py:4097`.
- `remove_dataset_upload_at_index()` uploads the remaining dataset at `reminders_app_v3.py:9448`.

## 7. CSV Serialization Points

Upload/publish:

- `publish_dataset_for_clinic()`: `merged_df.to_csv(index=False).encode("utf-8")` at `reminders_app_v3.py:4077`.
- `remove_dataset_upload_at_index()`: `remaining_df.drop(...).to_csv(index=False).encode("utf-8")` at `reminders_app_v3.py:9447`.

Other app exports:

- `stats_export_csv_bytes(frame)` at `reminders_app_v3.py:14844`.
- `stats_export_frame_fingerprint()` can fall back to `frame.to_csv(index=True)` for hashing at `reminders_app_v3.py:14932`.
- Debug export uses `debug_out.to_csv(index=False).encode("utf-8")` at `reminders_app_v3.py:17759`.

## 8. Existing Upload Size And Row Limits

Configured limits at `reminders_app_v3.py:6237-6241`:

- Required columns: `ChargeDate`, `Client Name`, `Animal Name`, `Item Name`.
- Max files per upload: `5`.
- Max file bytes per file: `50 MB`.
- Max rows per parsed file: `250,000`.
- Max columns per parsed file: `200`.

Validation points:

- `_to_blob()` rejects declared oversized files before `getvalue()` when Streamlit exposes `.size`, then validates actual bytes after `getvalue()`.
- `validate_upload_file_collection()` checks file count and per-file byte size.
- `process_file()` validates file size before parser calls and DataFrame row/column limits immediately after parsing.
- `finalize_processed_upload_df()` validates row/column limits again after sanitization.

Existing tests:

- Oversized upload rejected before parser in `tests/test_ci_audit_characterization.py`.
- Row/column and file-count limits in `tests/test_ci_audit_characterization.py`.
- Publish and Drive upload behavior in `tests/test_ci_dataset_update.py`.

## 9. Repeated Parsing Or Unnecessary Copies

### Finding P1: Upload bytes are duplicated through blob hashing and cached parse results

- Hot path: `_to_blob()` -> `upload_fingerprint()` -> `summarize_uploads()` -> `process_file()`.
- Expected memory/API cost: up to 5 files x 50 MB can be materialized as Python bytes, hashed in full, passed into two `@st.cache_data` layers, and parsed into DataFrames. Cache keys and cached return values can keep memory pressure high across reruns.
- Safest fix: keep behavior but replace `file_blobs` with lightweight metadata plus a content digest where possible; use digest/name/size as explicit cache key and avoid caching both the raw byte-containing summary and per-file parse results. A first safe patch is a helper that builds `{"name", "size", "sha256", "bytes"}` once and passes only digest metadata into skip/cache decisions.
- Behavior risk exists: medium. Cache-key changes can create stale parse results if digest/name/version handling is wrong.
- Tests needed: same bytes parse once for same digest/schema version; same name with changed bytes reparses; different names with same bytes do not collide unexpectedly; oversized file still rejected before parser.
- Validation commands: `python -m py_compile reminders_app_v3.py`; `python -m unittest tests.test_ci_audit_characterization tests.test_ci_dataset_update`; `python -m unittest discover -s tests -p "test_ci_*.py"`.

### Finding P1: Successful publish holds multiple full dataset copies plus full CSV bytes

- Hot path: `save_uploaded_dataset()` and `publish_dataset_for_clinic()`.
- Expected memory/API cost: current upload can exist as cached parsed DataFrames, concatenated `working_df`, `new_df` copy, existing Drive bytes, existing parsed DataFrame, `existing.copy()`, `new.copy()`, `merged_df`, `out_bytes`, and `BytesIO(out_bytes)`. API cost is one Drive download when an existing dataset exists, one resumable Drive upload, pointer update, and tracker/settings writes.
- Safest fix: reduce local copies first. Pass a sanitized `new_df` directly rather than copying `working_df` again, and avoid copying `new_df` in `merge_dataset_update()` unless mutation is needed. Later, consider streaming CSV serialization to a temp file or `BytesIO` directly, but only after tests cover Drive upload payloads.
- Behavior risk exists: low for removing provably unnecessary copies; medium for streaming/upload refactor.
- Tests needed: publish with no existing dataset; publish with existing dataset append; replace-overlapping dates; duplicate billed-item dedupe order; Drive payload CSV contents unchanged.
- Validation commands: `python -m py_compile reminders_app_v3.py`; `python -m unittest tests.test_ci_dataset_update`; `bash scripts/pre_merge_check.sh`.

### Finding P1: Existing dataset can be downloaded/parsed before every save attempt

- Hot path: Upload Data section reads existing pointer and calls `load_existing_shared_df()` at `reminders_app_v3.py:11119-11123` before entering `save_uploaded_dataset()`.
- Expected memory/API cost: one full Drive download plus full parse/sanitize of existing clinic data during upload save. This is necessary for overlap decisions and merge correctness, but it happens even before the publish function starts.
- Safest fix: cache the existing dataset loaded for the current pointer during one upload flow in session state or pass-through local scope, with an explicit key of `(clinic_id, existing_file_id, existing_name, dataset_updated_at/data_version)`. Current code already passes `existing_df` into publish, so the next safe step is avoiding repeated load across reruns when the selected upload has not changed.
- Behavior risk exists: medium. Stale existing data would be serious if another user updated the shared dataset between reruns.
- Tests needed: existing dataset is not re-downloaded for the same pointer/upload key in one flow; pointer change invalidates cache; failed load does not poison cache; multi-user stale pointer path remains fail-closed.
- Validation commands: `python -m unittest tests.test_ci_dataset_update tests.test_ci_error_handling`; `bash scripts/pre_merge_check.sh`.

### Finding P2: Charge dates are parsed repeatedly during upload summary and publish

- Hot path: `process_file()` parses `ChargeDate`; `finalize_processed_upload_df()` sanitizes and validates; `summarize_uploads()` reparses `df["ChargeDate"]` for from/to; `dataset_date_bounds()` reparses `new_df["ChargeDate"]`; `merge_dataset_update()` reparses dates for overlap and sort.
- Expected memory/API cost: repeated Series allocations and date parsing over up to hundreds of thousands of rows. No extra external API cost.
- Safest fix: add a datetime-aware fast path to `dataset_date_bounds()` and similar helpers, or preserve a normalized datetime `ChargeDate` guarantee from `sanitize_working_df()` and avoid calling custom `parse_dates()` when dtype is already datetime64.
- Behavior risk exists: low if implemented as dtype fast path with string fallback.
- Tests needed: date bounds for datetime64, strings, invalid dates, empty DataFrames; upload summary from canonical CSV and PMS-specific inputs.
- Validation commands: `python -m unittest tests.test_ci_dataset_update tests.test_ci_logic_edge_cases`; `python -m unittest discover -s tests -p "test_ci_*.py"`.

### Finding P2: Sanitization and duplicate-column cleanup copy DataFrames repeatedly

- Hot path: `process_file()` calls `drop_duplicate_columns()`, alias helpers copy frames, `finalize_processed_upload_df()` calls `sanitize_working_df()`, upload UI calls `sanitize_working_df()` after concat, and publish stores `sanitize_working_df(merged_df)`.
- Expected memory/API cost: extra DataFrame-sized allocations during parse/save, especially with wide exports near the 200-column limit.
- Safest fix: measure first, then remove redundant sanitization only where an upstream helper already guarantees canonical schema. A low-risk start is documenting/centralizing which functions return sanitized frames, then adding tests before deleting any copy.
- Behavior risk exists: medium. Upload normalization is PMS-sensitive and brittle; dropping a defensive sanitizer can expose malformed columns.
- Tests needed: canonical CSV, VETport alias columns, ezyVet names, Xpress, duplicate columns, blank rows, invalid dates, and row dedupe behavior.
- Validation commands: `python -m unittest tests.test_ci_dataset_update tests.test_ci_audit_characterization`; `bash scripts/pre_merge_check.sh`.

### Finding P2: Full CSV serialization is eager and synchronous

- Hot path: `publish_dataset_for_clinic()` serializes `merged_df` before Drive upload; remove flow serializes `remaining_df`.
- Expected memory/API cost: full CSV string/bytes allocation proportional to merged dataset size, then another wrapper in `BytesIO`; synchronous Drive upload blocks the user until complete.
- Safest fix: first record CSV byte length in existing performance tracker to understand cost. Next, stream to a temporary file or a single `BytesIO` without the intermediate encoded bytes if Google client usage supports it cleanly.
- Behavior risk exists: medium. Upload retries, error reporting, and tests currently expect byte payloads.
- Tests needed: Drive upload receives identical CSV bytes; timeout/error handling unchanged; publish pointer updates only after upload success.
- Validation commands: `python -m unittest tests.test_ci_dataset_update tests.test_ci_error_handling`; live/staging smoke for Drive upload.

### Finding P2: Upload parse success records performance but not memory/byte size

- Hot path: `record_performance_tracker_event("upload_parse", ...)` at `reminders_app_v3.py:11076` and `record_performance_tracker_event("dataset_publish", ...)` at `reminders_app_v3.py:11210`.
- Expected memory/API cost: no direct memory cost, but missing observability makes it hard to choose between byte cache, copy, and CSV streaming fixes. Each tracker event is also a Sheets append.
- Safest fix: include total uploaded bytes, CSV output bytes, and `df.memory_usage(deep=True).sum()` in sanitized message fields or add columns in a separate tracker schema pass. Keep under `TRACKER_CELL_TEXT_LIMIT`.
- Behavior risk exists: low for message-only metrics, medium if changing tracker headers.
- Tests needed: tracker message sanitization/length; performance tracker row contents with fake sheet.
- Validation commands: `python -m unittest tests.test_ci_audit_characterization tests.test_ci_dataset_update`.

### Finding P3: Dataset summary repair can trigger Drive load during Upload Data render

- Hot path: `get_saved_dataset_summary_rows()` calls `load_shared_dataset_for_clinic()` when history has missing row counts and no `working_df` at `reminders_app_v3.py:9332-9344`.
- Expected memory/API cost: a render-time Drive download and parse just to repair display metadata. It is guarded by `_row_count_repair_load_attempted_for`, but still heavy when it happens.
- Safest fix: prefer showing unknown row counts and defer repair to an explicit maintenance/save path. Alternatively cache repaired row counts in settings once loaded.
- Behavior risk exists: low-medium. UI metadata may remain less precise until data is loaded.
- Tests needed: missing history row counts do not repeatedly load Drive; display still renders; repair still happens when full dataset is intentionally loaded.
- Validation commands: `python -m unittest tests.test_ci_dataset_update tests.test_ci_streamlit_startup`.

## 10. Low-Risk Memory Reductions

1. Add datetime dtype fast paths in `dataset_date_bounds()` and upload summary date-bound code.
   - Low behavior risk because string fallback can remain unchanged.

2. Reuse one upload digest computed in `_to_blob()` or a new blob builder instead of hashing full bytes again in every upload cache/skip helper.
   - Medium behavior risk unless cache invalidation tests are strong.

3. Avoid `new_df = st.session_state["working_df"].copy()` when no mutation follows that cannot be done on a narrow/drop-column view.
   - Low behavior risk if tests prove publish payload unchanged.

4. In `merge_dataset_update()`, avoid copying `new_df` when it is only read.
   - Low behavior risk for append mode; replace-overlap mode needs care for existing frame filtering.

5. Add explicit `max_entries` to upload-related `@st.cache_data` functions.
   - Low behavior risk; possible UX cost if users switch repeatedly between many large uploads.

6. Clear only upload parse caches after successful save/reset if Streamlit can target those functions, instead of global `st.cache_data.clear()`.
   - Medium behavior risk because other caches rely on broad invalidation today.

7. Record upload bytes, parsed DataFrame memory, merged DataFrame memory, and output CSV bytes before changing architecture.
   - Low behavior risk and helps rank future fixes.

## Recommended Patch Order

1. Add memory/byte metrics to existing upload parse and publish performance tracker messages.
2. Add datetime fast paths for upload date bounds and publish date bounds.
3. Remove one proven redundant copy from the publish path with regression tests.
4. Add `max_entries` to upload parse/summary caches.
5. Rework upload cache keys to digest metadata instead of full byte-containing blob tuples.
6. Investigate streaming Drive upload only after payload tests and staging measurements.

## Validation Commands For Future Fixes

```bash
python -m py_compile reminders_app_v3.py settings_pointer_utils.py
python -m unittest tests.test_ci_audit_characterization
python -m unittest tests.test_ci_dataset_update
python -m unittest tests.test_ci_error_handling
python -m unittest tests.test_ci_streamlit_startup
python -m unittest discover -s tests -p "test_ci_*.py"
bash scripts/pre_merge_check.sh
python -m pip check
```

For Drive behavior changes, also run the live/staging Google smoke check with credentials:

```bash
python scripts/live_google_smoke_check.py
```

## Stop Point

This pass is report-only. No upload parsing, memory, cache, or publish-flow fixes were implemented.
