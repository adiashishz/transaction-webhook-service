"""End-to-end check of the assessment's success criteria against a running deployment.

Usage: python scripts/smoke_test.py --base-url http://localhost:8000

Standard library only, so it runs anywhere with Python 3.10+.
"""

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor

RESULTS = []


def request(base_url, method, path, body=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(f"{base_url}{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status, text = resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        status, text = exc.code, exc.read().decode()
    elapsed_ms = (time.perf_counter() - started) * 1000
    try:
        payload = json.loads(text) if text else None
    except json.JSONDecodeError:
        payload = text
    return status, payload, elapsed_ms


def payload(txn_id, **overrides):
    body = {
        "transaction_id": txn_id,
        "source_account": "acc_user_789",
        "destination_account": "acc_merchant_456",
        "amount": 1500,
        "currency": "INR",
    }
    return {**body, **overrides}


def check(name, ok, detail=""):
    RESULTS.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{f' - {detail}' if detail else ''}")
    return ok


def post_webhook(base_url, body):
    return request(base_url, "POST", "/v1/webhooks/transactions", body)


def get_transaction(base_url, txn_id):
    return request(base_url, "GET", f"/v1/transactions/{txn_id}")


def wait_until_processed(base_url, txn_id, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, body, _ = get_transaction(base_url, txn_id)
        if status == 200 and body[0]["status"] == "PROCESSED":
            return body
        time.sleep(2)
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--load", type=int, default=50, help="concurrent webhooks for the performance check")
    parser.add_argument("--timeout", type=int, default=120, help="seconds to wait for background processing")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    run = uuid.uuid4().hex[:8]

    print(f"Smoke testing {base}\n\nHealth")
    status, body, ms = request(base, "GET", "/")
    check("GET / returns HEALTHY", status == 200 and body.get("status") == "HEALTHY", f"{status} in {ms:.0f}ms")

    print("\n1. Single transaction")
    single_id = f"txn_smoke_{run}_single"
    started = time.monotonic()
    status, body, ms = post_webhook(base, payload(single_id))
    check("webhook returns 202", status == 202, f"{ms:.0f}ms")
    check("webhook responds within 500ms", ms < 500, f"{ms:.0f}ms")
    status, body, _ = get_transaction(base, single_id)
    check(
        "transaction is PROCESSING with processed_at null",
        status == 200 and body[0]["status"] == "PROCESSING" and body[0]["processed_at"] is None,
        json.dumps(body),
    )

    print("\n2. Duplicate prevention")
    dup_id = f"txn_smoke_{run}_duplicate"
    with ThreadPoolExecutor(max_workers=5) as pool:
        responses = list(pool.map(lambda _: post_webhook(base, payload(dup_id)), range(5)))
    responses += [post_webhook(base, payload(dup_id, amount=9999)) for _ in range(2)]
    check("all 7 deliveries return 202", all(r[0] == 202 for r in responses), str([r[0] for r in responses]))
    firsts = [r for r in responses if r[1] and r[1].get("duplicate") is False]
    check("exactly one delivery was accepted as new", len(firsts) == 1, f"{len(firsts)} accepted as new")
    status, body, _ = get_transaction(base, dup_id)
    check(
        "one record stored, original amount kept",
        status == 200 and len(body) == 1 and body[0]["amount"] == 1500,
        json.dumps(body),
    )

    print(f"\n3. Performance ({args.load} concurrent webhooks while processing is under way)")
    with ThreadPoolExecutor(max_workers=min(args.load, 25)) as pool:
        load = list(pool.map(lambda i: post_webhook(base, payload(f"txn_smoke_{run}_load_{i}")), range(args.load)))
    latencies = sorted(r[2] for r in load)
    p95 = latencies[max(0, int(len(latencies) * 0.95) - 1)]
    check("all load webhooks return 202", all(r[0] == 202 for r in load), str({r[0] for r in load}))
    check(
        "p95 latency under 500ms",
        p95 < 500,
        f"p50 {statistics.median(latencies):.0f}ms, p95 {p95:.0f}ms, max {latencies[-1]:.0f}ms",
    )

    print("\n4. Reliability (bad input handled gracefully, service stays up)")
    status, _, _ = request(base, "POST", "/v1/webhooks/transactions", raw=b"{not json")
    check("malformed JSON returns 400", status == 400, str(status))
    status, _, _ = post_webhook(base, payload(f"txn_smoke_{run}_bad", amount=-5))
    check("invalid amount returns 400", status == 400, str(status))
    status, _, _ = get_transaction(base, f"txn_smoke_{run}_missing")
    check("unknown transaction returns 404", status == 404, str(status))
    status, body, _ = request(base, "GET", "/")
    check("service still HEALTHY after load", status == 200 and body.get("status") == "HEALTHY")

    print(f"\nWaiting for background processing (up to {args.timeout}s)...")
    single = wait_until_processed(base, single_id, args.timeout)
    elapsed = time.monotonic() - started
    check("single transaction PROCESSED", single is not None, f"after ~{elapsed:.0f}s")
    if single:
        check("processed after the ~30s simulated delay", elapsed >= 28, f"processed_at {single[0]['processed_at']}")
    dup = wait_until_processed(base, dup_id, args.timeout)
    check("duplicate transaction PROCESSED once", dup is not None and len(dup) == 1)
    last_load = wait_until_processed(base, f"txn_smoke_{run}_load_{args.load - 1}", args.timeout)
    check("load transactions PROCESSED", last_load is not None)

    passed = sum(RESULTS)
    print(f"\n{passed}/{len(RESULTS)} checks passed")
    sys.exit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
