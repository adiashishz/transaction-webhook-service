import re

from rest_framework.test import APIClient


def test_health_check_reports_healthy_with_utc_timestamp():
    response = APIClient().get("/")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "HEALTHY"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", body["current_time"])
