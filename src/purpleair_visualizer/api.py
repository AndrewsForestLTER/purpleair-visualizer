"""Download sensor history from the PurpleAir API.

The API limits how much history one request can return, so longer date ranges
are split into several requests, spaced out to stay under its rate limit.
See https://community.purpleair.com/t/loop-api-calls-for-historical-data/4623.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event
from typing import Any, NamedTuple

import pandas as pd

from purpleair_visualizer import __version__
from purpleair_visualizer.data import parse_times

logger = logging.getLogger(__name__)

API_ROOT = "https://api.purpleair.com/v1"
TIME_COLUMN = "time_stamp"
REQUEST_TIMEOUT_SECONDS = 120
REQUEST_SPACING_SECONDS = 1.0
RETRY_DELAYS_SECONDS = (2.0, 5.0, 15.0)
_TRANSIENT_STATUS = {429, 500, 502, 503, 504}

DEFAULT_FIELDS = ("humidity", "temperature", "pressure", "pm2.5_cf_1")
OPTIONAL_FIELDS = ("pm2.5_atm", "pm2.5_alt", "pm2.5_cf_1_a", "pm2.5_cf_1_b")

RequestJson = Callable[[str, str], dict[str, Any]]
Progress = Callable[[int, int], None]


class Average(NamedTuple):
    """An averaging period and the longest span one request may cover."""

    minutes: int
    max_days: int


AVERAGES: dict[str, Average] = {
    "Real-time": Average(0, 30),
    "10 minutes": Average(10, 60),
    "30 minutes": Average(30, 90),
    "1 hour": Average(60, 180),
    "6 hours": Average(360, 365),
    "1 day": Average(1440, 730),
    "1 week": Average(10080, 1825),
    "1 month": Average(43200, 7300),
    "1 year": Average(525600, 36500),
}


class PurpleAirError(Exception):
    """The API could not be reached or refused a request."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class DownloadCancelled(Exception):
    """The user stopped a download."""


@dataclass(frozen=True)
class HistoryRequest:
    """What to download.

    Attributes:
        sensor_index: PurpleAir sensor index.
        api_key: API read key.
        start: First moment to include, UTC.
        end: End of the range, UTC. This moment itself is excluded.
        average: A key of ``AVERAGES``.
        fields: Sensor fields to download.
        read_key: Read key for a private sensor, if any.
    """

    sensor_index: int
    api_key: str
    start: pd.Timestamp
    end: pd.Timestamp
    average: str
    fields: tuple[str, ...]
    read_key: str = ""


def split_range(start: pd.Timestamp, end: pd.Timestamp, average: str) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Split a date range into spans short enough for one request each.

    Args:
        start: First moment to include.
        end: End of the range, excluded.
        average: A key of ``AVERAGES``.

    Returns:
        Consecutive (start, end) spans covering the range.

    Raises:
        ValueError: If the range is empty.
    """
    if end <= start:
        raise ValueError("The end date must be after the start date.")
    limit = pd.Timedelta(days=AVERAGES[average].max_days)
    spans: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    cursor = start
    while cursor < end:
        stop = min(cursor + limit, end)
        spans.append((cursor, stop))
        cursor = stop
    return spans


def _describe_error(body: bytes, status: int) -> str:
    """Turn an API error response into a message for the user."""
    try:
        payload = json.loads(body)
        detail = payload.get("description") or payload.get("error") or ""
    except (ValueError, AttributeError):
        detail = ""
    if status in (401, 403):
        return f"PurpleAir rejected the API key or does not allow this request. {detail}".strip()
    if status == 402:
        return f"Your PurpleAir account may be out of API points. {detail}".strip()
    if status == 404:
        return f"PurpleAir could not find that sensor. {detail}".strip()
    return f"PurpleAir returned error {status}. {detail}".strip()


def request_json(url: str, api_key: str) -> dict[str, Any]:
    """Send one GET request to the API.

    Args:
        url: The full request URL.
        api_key: Sent in the ``X-API-Key`` header.

    Returns:
        The decoded JSON response.

    Raises:
        PurpleAirError: If the request fails.
    """
    request = urllib.request.Request(
        url, headers={"X-API-Key": api_key, "User-Agent": f"purpleair-visualizer/{__version__}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise PurpleAirError(_describe_error(error.read(), error.code), status=error.code) from None
    except (urllib.error.URLError, TimeoutError) as error:
        raise PurpleAirError(f"Could not reach PurpleAir. Check your connection. ({error})") from None
    except ValueError:
        raise PurpleAirError("PurpleAir sent a response that could not be read.") from None


def check_key(api_key: str, request: RequestJson = request_json) -> str:
    """Confirm an API key works.

    Args:
        api_key: The key to test.
        request: Function that performs the HTTP call.

    Returns:
        The key type PurpleAir reports, or ``unknown``.

    Raises:
        PurpleAirError: If the key is rejected.
    """
    return str(request(f"{API_ROOT}/keys", api_key).get("api_key_type", "unknown"))


def _history_url(job: HistoryRequest, start: pd.Timestamp, end: pd.Timestamp) -> str:
    """Build the URL for one span of history."""
    params = {
        "start_timestamp": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_timestamp": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "average": AVERAGES[job.average].minutes,
        "fields": ",".join(job.fields),
    }
    if job.read_key:
        params["read_key"] = job.read_key
    return f"{API_ROOT}/sensors/{job.sensor_index}/history?{urllib.parse.urlencode(params, safe=',:')}"


def _request_with_retry(
    url: str, api_key: str, request: RequestJson, sleep: Callable[[float], None], cancel: Event | None
) -> dict[str, Any]:
    """Send a request, waiting and retrying when the API is briefly unavailable."""
    for delay in (*RETRY_DELAYS_SECONDS, None):
        if cancel is not None and cancel.is_set():
            raise DownloadCancelled
        try:
            return request(url, api_key)
        except PurpleAirError as error:
            if delay is None or error.status not in _TRANSIENT_STATUS:
                raise
            logger.warning("Retrying after error %s", error.status)
            sleep(delay)
    raise AssertionError("unreachable")


def _to_frame(payload: dict[str, Any]) -> pd.DataFrame:
    """Convert one API response to a data frame."""
    if not isinstance(payload.get("fields"), list) or not isinstance(payload.get("data"), list):
        raise PurpleAirError("PurpleAir sent a response in an unexpected format.")
    if TIME_COLUMN not in payload["fields"]:
        raise PurpleAirError(f"PurpleAir's response has no '{TIME_COLUMN}' column.")
    return pd.DataFrame(payload["data"], columns=payload["fields"])


def download_history(
    job: HistoryRequest,
    progress: Progress | None = None,
    cancel: Event | None = None,
    request: RequestJson = request_json,
    sleep: Callable[[float], None] = time.sleep,
) -> pd.DataFrame:
    """Download a sensor's history as one table sorted by time.

    Args:
        job: What to download.
        progress: Called with (requests finished, total requests).
        cancel: Set this event to stop the download.
        request: Function that performs the HTTP call.
        sleep: Function used to wait between requests.

    Returns:
        One row per timestamp, with UTC times in PurpleAir's export format.

    Raises:
        DownloadCancelled: If ``cancel`` was set.
        PurpleAirError: If a request fails or there is no data in the range.
        ValueError: If the date range is empty.
    """
    spans = split_range(job.start, job.end, job.average)
    frames: list[pd.DataFrame] = []
    for number, (start, end) in enumerate(spans, start=1):
        if number > 1:
            sleep(REQUEST_SPACING_SECONDS)
        payload = _request_with_retry(_history_url(job, start, end), job.api_key, request, sleep, cancel)
        frames.append(_to_frame(payload))
        if progress is not None:
            progress(number, len(spans))

    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        raise PurpleAirError("PurpleAir has no data for this sensor in that date range.")
    combined = pd.concat(frames, ignore_index=True)
    combined[TIME_COLUMN] = parse_times(combined[TIME_COLUMN])
    combined = (
        combined.dropna(subset=[TIME_COLUMN])
        .drop_duplicates(subset=[TIME_COLUMN])
        .sort_values(TIME_COLUMN, kind="stable")
        .reset_index(drop=True)
    )
    combined[TIME_COLUMN] = combined[TIME_COLUMN].dt.strftime("%Y-%m-%d %H:%M:%S+00:00")
    ordered = [TIME_COLUMN, *[column for column in combined.columns if column != TIME_COLUMN]]
    return combined[ordered]
