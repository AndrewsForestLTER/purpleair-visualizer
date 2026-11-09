"""Tests for the PurpleAir API client, using a simulated server."""

import io
import json
import urllib.error
import urllib.parse
from pathlib import Path
from threading import Event
from typing import Any
from unittest import mock

import pandas as pd
import pytest

from purpleair_visualizer import api
from purpleair_visualizer.api import (
    AVERAGES,
    DownloadCancelled,
    HistoryRequest,
    PurpleAirError,
    check_key,
    download_history,
    request_json,
    split_range,
)
from purpleair_visualizer.data import PST
from purpleair_visualizer.settings import initial_api_key, load_settings, save_settings

EPOCH_2025 = int(pd.Timestamp("2025-01-01", tz="UTC").timestamp())


def job(days: int = 1, average: str = "1 hour", read_key: str = "") -> HistoryRequest:
    start = pd.Timestamp("2025-01-01", tz="UTC")
    return HistoryRequest(115739, "secret", start, start + pd.Timedelta(days=days), average, ("humidity", "pm2.5_cf_1"), read_key)


def query(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).items()}


class Server:
    """Answers history requests with one row per span, newest first."""

    def __init__(self, failures: list[PurpleAirError] | None = None) -> None:
        self.urls: list[str] = []
        self.keys: list[str] = []
        self.failures = failures or []

    def __call__(self, url: str, key: str) -> dict[str, Any]:
        self.urls.append(url)
        self.keys.append(key)
        if self.failures:
            raise self.failures.pop(0)
        start = int(pd.Timestamp(query(url)["start_timestamp"]).timestamp())
        return {"fields": ["time_stamp", "humidity", "pm2.5_cf_1"], "data": [[start + 3600, 41, 2.5], [start, 40, None]]}


def test_splits_at_published_limits() -> None:
    start = pd.Timestamp("2025-01-01", tz="UTC")
    spans = split_range(start, start + pd.Timedelta(days=400), "1 hour")
    assert len(spans) == 3
    assert spans[0][1] == spans[1][0]
    assert spans[-1][1] == start + pd.Timedelta(days=400)
    assert all(stop - begin <= pd.Timedelta(days=180) for begin, stop in spans)


def test_exactly_one_limit_is_one_request() -> None:
    start = pd.Timestamp("2025-01-01", tz="UTC")
    assert len(split_range(start, start + pd.Timedelta(days=AVERAGES["Real-time"].max_days), "Real-time")) == 1


def test_empty_range_is_rejected() -> None:
    start = pd.Timestamp("2025-01-01", tz="UTC")
    with pytest.raises(ValueError, match="after the start"):
        split_range(start, start, "1 hour")


def test_request_url_and_key_header_use() -> None:
    server = Server()
    download_history(job(read_key="private"), request=server, sleep=lambda _: None)
    assert server.urls[0].startswith("https://api.purpleair.com/v1/sensors/115739/history?")
    assert query(server.urls[0]) == {
        "start_timestamp": "2025-01-01T00:00:00Z",
        "end_timestamp": "2025-01-02T00:00:00Z",
        "average": "60",
        "fields": "humidity,pm2.5_cf_1",
        "read_key": "private",
    }
    assert server.keys == ["secret"]
    assert "secret" not in server.urls[0]


def test_results_are_sorted_in_export_format() -> None:
    data = download_history(job(), request=Server(), sleep=lambda _: None)
    assert data["time_stamp"].tolist() == ["2025-01-01 00:00:00+00:00", "2025-01-01 01:00:00+00:00"]
    assert list(data.columns) == ["time_stamp", "humidity", "pm2.5_cf_1"]
    assert pd.isna(data["pm2.5_cf_1"].iloc[0])


def test_pst_output_and_requested_column_order() -> None:
    swapped = lambda url, key: {"fields": ["pm2.5_cf_1", "time_stamp", "humidity"], "data": [[2.5, EPOCH_2025, 40]]}
    data = download_history(job(), request=swapped, sleep=lambda _: None, time_zone=PST)
    assert list(data.columns) == ["time_stamp", "humidity", "pm2.5_cf_1"]
    assert data["time_stamp"].iloc[0] == "2024-12-31 16:00:00-08:00"


def test_long_range_is_combined_and_spaced() -> None:
    server = Server()
    waits: list[float] = []
    progress: list[tuple[int, int]] = []
    data = download_history(
        job(days=400), lambda done, total: progress.append((done, total)), request=server, sleep=waits.append
    )
    assert len(server.urls) == 3
    assert len(data) == 6
    assert data["time_stamp"].is_monotonic_increasing
    assert waits == [1.0, 1.0]
    assert progress[-1] == (3, 3)


def test_duplicate_timestamps_are_removed() -> None:
    fixed = lambda url, key: {"fields": ["time_stamp", "h"], "data": [[EPOCH_2025, 1], [EPOCH_2025, 1]]}
    assert len(download_history(job(), request=fixed, sleep=lambda _: None)) == 1


def test_transient_error_is_retried() -> None:
    server = Server([PurpleAirError("busy", status=429)])
    waits: list[float] = []
    assert len(download_history(job(), request=server, sleep=waits.append)) == 2
    assert waits == [2.0]


def test_gives_up_after_retries() -> None:
    server = Server([PurpleAirError("down", status=503) for _ in range(4)])
    with pytest.raises(PurpleAirError, match="down"):
        download_history(job(), request=server, sleep=lambda _: None)
    assert len(server.urls) == 4


def test_rejected_key_is_not_retried() -> None:
    server = Server([PurpleAirError("bad key", status=403)])
    with pytest.raises(PurpleAirError, match="bad key"):
        download_history(job(), request=server, sleep=lambda _: None)
    assert len(server.urls) == 1


def test_cancel_stops_before_next_request() -> None:
    cancel = Event()
    cancel.set()
    server = Server()
    with pytest.raises(DownloadCancelled):
        download_history(job(), cancel=cancel, request=server, sleep=lambda _: None)
    assert server.urls == []


def test_no_data_is_reported() -> None:
    empty = lambda url, key: {"fields": ["time_stamp", "h"], "data": []}
    with pytest.raises(PurpleAirError, match="no data"):
        download_history(job(), request=empty, sleep=lambda _: None)


def test_unexpected_response_is_reported() -> None:
    with pytest.raises(PurpleAirError, match="unexpected format"):
        download_history(job(), request=lambda url, key: {"oops": 1}, sleep=lambda _: None)


def test_check_key_reports_type() -> None:
    assert check_key("k", request=lambda url, key: {"api_key_type": "READ"}) == "READ"


def http_error(status: int, body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://api.purpleair.com", status, "x", None, io.BytesIO(body))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("status", "text"), [(403, "rejected the API key"), (402, "out of API points"), (404, "could not find"), (500, "error 500")]
)
def test_http_errors_become_clear_messages(status: int, text: str) -> None:
    body = json.dumps({"error": "E", "description": "Detail."}).encode()
    with mock.patch.object(api.urllib.request, "urlopen", side_effect=http_error(status, body)):
        with pytest.raises(PurpleAirError, match=text) as caught:
            request_json("https://api.purpleair.com/v1/keys", "secret")
    assert caught.value.status == status
    assert "Detail." in str(caught.value)
    assert "secret" not in str(caught.value)


def test_network_failure_becomes_clear_message() -> None:
    with mock.patch.object(api.urllib.request, "urlopen", side_effect=urllib.error.URLError("offline")):
        with pytest.raises(PurpleAirError, match="Could not reach"):
            request_json("https://api.purpleair.com/v1/keys", "secret")


def test_key_is_sent_as_header() -> None:
    response = mock.MagicMock()
    response.__enter__.return_value.read.return_value = b"{}"
    with mock.patch.object(api.urllib.request, "urlopen", return_value=response) as opener:
        request_json("https://api.purpleair.com/v1/keys", "secret")
    assert opener.call_args.args[0].get_header("X-api-key") == "secret"


def test_settings_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "settings.json"
    save_settings({"sensor_index": "1"}, path)
    assert load_settings(path) == {"sensor_index": "1"}


@pytest.mark.parametrize("content", ["not json", "[1, 2]"])
def test_bad_settings_are_ignored(tmp_path: Path, content: str) -> None:
    path = tmp_path / "settings.json"
    path.write_text(content)
    assert load_settings(path) == {}


def test_missing_settings_are_empty(tmp_path: Path) -> None:
    assert load_settings(tmp_path / "absent.json") == {}


def test_api_key_falls_back_to_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PURPLEAIR_API_KEY", "from-env")
    assert initial_api_key({}) == "from-env"
    assert initial_api_key({"api_key": "saved"}) == "saved"
