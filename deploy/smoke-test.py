"""Check a running SelfX instance with small, generated files and no model downloads."""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4


API = "/api/v1"
SUBTITLE = b"1\n00:00:01,000 --> 00:00:02,000\nSelfX is ready.\n\n"
SHIFTED_SUBTITLE = SUBTITLE.replace(b"01,000", b"01,500").replace(b"02,000", b"02,500")


class SmokeError(Exception):
    pass


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SelfX:
    def __init__(self, url):
        self.url = url.rstrip("/")
        self.token = None
        self.opener = build_opener(NoRedirects())

    def request(self, path, *, data=None, content_type=None, headers=None):
        request_headers = dict(headers or {})
        if self.token:
            request_headers["Authorization"] = f"Bearer {self.token}"
        if content_type:
            request_headers["Content-Type"] = content_type
        req = Request(self.url + path, data=data, headers=request_headers)
        try:
            with self.opener.open(req, timeout=8) as response:
                return response.read()
        except HTTPError as exc:
            exc.close()
            raise SmokeError(f"{req.get_method()} {path} returned HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError) as exc:
            raise SmokeError(f"{req.get_method()} {path} failed to connect ({type(exc).__name__})") from None

    def api(self, path, payload=None, *, headers=None):
        data = json.dumps(payload).encode() if payload is not None else None
        return json.loads(self.request(API + path, data=data, content_type="application/json", headers=headers))

    def upload_subtitle(self):
        boundary = uuid4().hex
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="selfx-smoke.srt"\r\n'
            "Content-Type: application/x-subrip\r\n\r\n"
        ).encode() + SUBTITLE + f"\r\n--{boundary}--\r\n".encode()
        return json.loads(self.request(API + "/files", data=body, content_type=f"multipart/form-data; boundary={boundary}"))


def wait_for_health(client, timeout):
    deadline = time.monotonic() + timeout
    last_error = "health endpoint returned an unexpected status"
    while time.monotonic() < deadline:
        try:
            health = client.api("/healthz")
            if health.get("status") == "ok" and health.get("service") == "selfx":
                return
        except (SmokeError, json.JSONDecodeError) as exc:
            last_error = str(exc)
        time.sleep(1)
    raise SmokeError(f"Service did not become healthy within {timeout}s ({last_error})")


def wait_for_output(client, job_path, timeout):
    deadline = time.monotonic() + timeout
    state = "queued"
    while time.monotonic() < deadline:
        job = client.api(job_path)
        state = job["status"]
        if state == "done":
            outputs = job["output_files"]
            if len(outputs) != 1:
                raise SmokeError(f"Expected a single output from {job_path}, received {len(outputs)}")
            return client.request(f"{API}/files/{outputs[0]['id']}/download")
        if state in {"error", "canceled", "cancelled"}:
            raise SmokeError(f"{job_path} finished in state {state}. Check the worker logs.")
        time.sleep(1)
    raise SmokeError(f"{job_path} stayed {state} after {timeout}s. Check the worker logs.")


def run(args):
    username = os.environ.get("SELFX_ADMIN_USER", "")
    password = os.environ.get("SELFX_ADMIN_PASSWORD", "")
    if not username or not password:
        raise SmokeError("Set SELFX_ADMIN_USER and SELFX_ADMIN_PASSWORD for the test account.")

    client = SelfX(args.base_url)
    wait_for_health(client, args.timeout)
    page = client.request("/")
    asset = re.search(rb'src="(/assets/[^"/]+\.js)"', page)
    if b'id="root"' not in page or asset is None or len(client.request(asset[1].decode())) < 100:
        raise SmokeError("The built web application or its JavaScript bundle is missing.")
    print("Web application, PostgreSQL and Redis responded.", flush=True)

    client.token = client.api("/auth/login", {"username": username, "password": password})["access_token"]
    if args.expect_planner_disabled:
        planner = client.api("/workflow-runs/planner")
        if planner != {"available": False, "model": None}:
            raise SmokeError("The local planner should be disabled for this install.")
    source = client.upload_subtitle()["id"]
    checksum_job = client.api("/jobs", {
        "tool": "hash-checksum", "file_ids": [source], "params": {"algorithm": "sha256"},
    })
    checksum = wait_for_output(client, f"/jobs/{checksum_job['id']}", args.timeout)
    if checksum.splitlines() != [f"sha256: {hashlib.sha256(SUBTITLE).hexdigest()}".encode()]:
        raise SmokeError("The quick worker returned an incorrect checksum.")
    print("The quick worker processed an authenticated upload and returned the expected checksum.", flush=True)

    workflow = {
        "file_id": source,
        "plan": {"steps": [{
            "id": "shift", "action": "subtitle-cleanup", "input": "source", "params": {"offset_ms": 500},
        }]},
    }
    headers = {"Idempotency-Key": uuid4().hex}
    created = client.api("/workflow-runs/execute", workflow, headers=headers)
    repeated = client.api("/workflow-runs/execute", workflow, headers=headers)
    if repeated["id"] != created["id"]:
        raise SmokeError("Replaying a workflow submission created a duplicate run.")
    shifted = wait_for_output(client, f"/workflow-runs/{created['id']}", args.timeout)
    if shifted != SHIFTED_SUBTITLE:
        raise SmokeError("The workflow worker returned incorrect subtitle timing.")
    print("The workflow worker applied the requested edit and returned the same run on replay.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="Origin serving SelfX, such as http://127.0.0.1:8800")
    parser.add_argument("--timeout", type=int, default=90, help="Seconds to wait for startup and for each job")
    parser.add_argument("--expect-planner-disabled", action="store_true", help="Require a model-free setup")
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    try:
        run(args)
    except (SmokeError, KeyError, TypeError, ValueError) as exc:
        sys.exit(f"SelfX smoke test failed: {exc}")


if __name__ == "__main__":
    main()
