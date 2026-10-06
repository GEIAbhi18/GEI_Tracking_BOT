"""
Tests for Factech complaint creation flow.

Verifies:
- Correct payload format sent to Factech API
- Success only when Factech confirms with a real complaint ID
- Failure returned on API errors, timeouts, and unexpected responses
- Structured logging with request IDs
- No false success messages to users
- Security: API keys masked in logs
"""
from __future__ import annotations
import json
import pytest
from unittest.mock import MagicMock, patch, call
from clients.factech_client import create_complaint, _mask_sensitive_headers, _generate_request_id


# ── Test Fixtures ──────────────────────────────────────────────────────────

SAMPLE_CLIENT_CONTEXT = {
    "building": "GEBB2",
    "company_name": "Good Earth Infra",
    "floor": "Ground Floor",
    "unit_number": "1",
    "admin_name": "Normal Tenant",
    "mobile_number": "919876543210",
    "email": "test@gei.com",
}

SAMPLE_COMPLAINT_DATA = {
    "nature": "Electrical",
    "sub_nature": "Power Failure",
    "description": "test-new55",
}


@pytest.fixture(autouse=True)
def mock_supabase_for_factech(mocker):
    """Prevent real Supabase calls during complaint tests."""
    mock_db = MagicMock()
    mock_db.insert.return_value.execute.return_value = MagicMock()
    mocker.patch("db.supabase.table", return_value=mock_db)
    yield mock_db


# ── Test: Correct Payload Format ──────────────────────────────────────────

class TestPayloadFormat:
    """Verifies the payload sent to Factech matches the expected API spec."""

    def test_payload_has_correct_fields(self, mocker):
        """Payload must contain exactly: complaint_no, unit_no, category, sub_category, description, created_at."""
        mock_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "success": True,
            "complaintId": "0451",
            "message": "Complaint created",
        }
        mock_resp.headers = {}
        mock_post.return_value = mock_resp

        create_complaint(SAMPLE_CLIENT_CONTEXT, SAMPLE_COMPLAINT_DATA)

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        payload = call_kwargs["json"]

        # Must have these fields
        assert "complaint_no" in payload
        assert "unit_no" in payload
        assert "category" in payload
        assert "sub_category" in payload
        assert "description" in payload
        assert "created_at" in payload

        # Must NOT have these old extra fields
        assert "name" not in payload
        assert "mobile" not in payload
        assert "email" not in payload
        assert "building" not in payload
        assert "floor" not in payload
        assert "company" not in payload
        assert "comments" not in payload

    def test_payload_values_match_input(self, mocker):
        """Verify payload values are derived correctly from inputs."""
        mock_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "success": True,
            "complaintId": "test44",
            "message": "OK",
        }
        mock_resp.headers = {}
        mock_post.return_value = mock_resp

        create_complaint(SAMPLE_CLIENT_CONTEXT, SAMPLE_COMPLAINT_DATA)

        payload = mock_post.call_args[1]["json"]
        assert payload["complaint_no"] == ""
        assert payload["unit_no"] == "001"  # unit "1" -> "001" (zero-padded)
        assert payload["category"] == "Electrical"
        assert payload["sub_category"] == "Power Failure"
        assert payload["description"] == "test-new55"
        # created_at should be a datetime string
        assert len(payload["created_at"]) == 19  # "YYYY-MM-DD HH:MM:SS"

    def test_unit_no_formatting_short_digit(self, mocker):
        """Single digit unit numbers get zero-padded to 3 chars."""
        mock_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": True, "complaintId": "C1"}
        mock_resp.headers = {}
        mock_post.return_value = mock_resp

        ctx = {**SAMPLE_CLIENT_CONTEXT, "unit_number": "5"}
        create_complaint(ctx, SAMPLE_COMPLAINT_DATA)

        payload = mock_post.call_args[1]["json"]
        assert payload["unit_no"] == "005"

    def test_unit_no_formatting_long_string(self, mocker):
        """Unit numbers >= 3 chars are left as-is."""
        mock_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": True, "complaintId": "C2"}
        mock_resp.headers = {}
        mock_post.return_value = mock_resp

        ctx = {**SAMPLE_CLIENT_CONTEXT, "unit_number": "GEEBTWOTest"}
        create_complaint(ctx, SAMPLE_COMPLAINT_DATA)

        payload = mock_post.call_args[1]["json"]
        assert payload["unit_no"] == "GEEBTWOTest"

    def test_url_uses_correct_site_id(self, mocker):
        """URL must use site_id 593 for GEBB2 building."""
        mock_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": True, "complaintId": "C3"}
        mock_resp.headers = {}
        mock_post.return_value = mock_resp

        create_complaint(SAMPLE_CLIENT_CONTEXT, SAMPLE_COMPLAINT_DATA)

        called_url = mock_post.call_args[0][0]
        assert "/v1/thirdparty/site/593/complaint" in called_url


# ── Test: Success Conditions ──────────────────────────────────────────────

class TestSuccessConditions:
    """Verifies success is only returned when Factech actually confirms complaint creation."""

    def test_success_with_complaint_id_in_response(self, mocker):
        """Success when HTTP 200 + complaintId in response."""
        mock_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "success": True,
            "complaintId": "0451",
            "message": "Complaint created successfully",
        }
        mock_resp.headers = {}
        mock_post.return_value = mock_resp

        result = create_complaint(SAMPLE_CLIENT_CONTEXT, SAMPLE_COMPLAINT_DATA)

        assert result["success"] is True
        assert result["complaint_id"] == "0451"
        assert result["fallback"] is False

    def test_success_with_com_no_in_response(self, mocker):
        """Success when response has com_no field."""
        mock_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {
            "com_no": "test44",
            "message": "OK",
        }
        mock_resp.headers = {}
        mock_post.return_value = mock_resp

        result = create_complaint(SAMPLE_CLIENT_CONTEXT, SAMPLE_COMPLAINT_DATA)

        assert result["success"] is True
        assert result["complaint_id"] == "test44"

    def test_success_with_nested_data_complaint_id(self, mocker):
        """Success when complaint ID is in data.complaintId."""
        mock_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {"complaintId": "NESTED-123"},
            "message": "Created",
        }
        mock_resp.headers = {}
        mock_post.return_value = mock_resp

        result = create_complaint(SAMPLE_CLIENT_CONTEXT, SAMPLE_COMPLAINT_DATA)

        assert result["success"] is True
        assert result["complaint_id"] == "NESTED-123"


# ── Test: Failure Conditions ──────────────────────────────────────────────

class TestFailureConditions:
    """Verifies failure is returned correctly and no false success is reported."""

    def test_failure_on_http_400(self, mocker):
        """HTTP 400 = failure, even if response body looks OK."""
        mock_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"message": "Bad Request"}
        mock_resp.text = "Bad Request"
        mock_resp.headers = {}
        mock_post.return_value = mock_resp

        result = create_complaint(SAMPLE_CLIENT_CONTEXT, SAMPLE_COMPLAINT_DATA)

        assert result["success"] is False
        assert result["complaint_id"] is None

    def test_failure_on_http_500(self, mocker):
        """HTTP 500 = failure."""
        mock_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.return_value = {"message": "Internal Server Error"}
        mock_resp.text = "Internal Server Error"
        mock_resp.headers = {}
        mock_post.return_value = mock_resp

        result = create_complaint(SAMPLE_CLIENT_CONTEXT, SAMPLE_COMPLAINT_DATA)

        assert result["success"] is False

    def test_failure_on_error_status_in_response(self, mocker):
        """HTTP 200 but status=error and no success flag = failure."""
        mock_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "error",
            "message": "Invalid unit_no",
        }
        mock_resp.text = "error"
        mock_resp.headers = {}
        mock_post.return_value = mock_resp

        result = create_complaint(SAMPLE_CLIENT_CONTEXT, SAMPLE_COMPLAINT_DATA)

        assert result["success"] is False

    def test_failure_when_no_complaint_id_in_response(self, mocker):
        """HTTP 200 but no complaint ID = failure (complaint likely not created)."""
        mock_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": "Some message but no ID",
        }
        mock_resp.text = "Some message but no ID"
        mock_resp.headers = {}
        mock_post.return_value = mock_resp

        result = create_complaint(SAMPLE_CLIENT_CONTEXT, SAMPLE_COMPLAINT_DATA)

        assert result["success"] is False
        assert result["complaint_id"] is None

    def test_failure_on_timeout(self, mocker):
        """Timeout = failure, NOT success with fallback."""
        import requests as req_lib
        mock_post = mocker.patch("requests.post", side_effect=req_lib.Timeout("timed out"))

        result = create_complaint(SAMPLE_CLIENT_CONTEXT, SAMPLE_COMPLAINT_DATA)

        assert result["success"] is False
        assert result["complaint_id"] is None
        assert "timed out" in result["message"].lower()

    def test_failure_on_connection_error(self, mocker):
        """Connection error = failure, NOT success with fallback."""
        import requests as req_lib
        mock_post = mocker.patch("requests.post", side_effect=req_lib.ConnectionError("DNS resolution failed"))

        result = create_complaint(SAMPLE_CLIENT_CONTEXT, SAMPLE_COMPLAINT_DATA)

        assert result["success"] is False
        assert result["complaint_id"] is None

    def test_no_fallback_complaint_id_generated(self, mocker):
        """
        CRITICAL: On failure, the code must NOT generate a fake complaint ID
        (GEI-xxxxx or FT-xxxxx) and return it as a real ID.
        """
        mock_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.return_value = {"message": "Server Error"}
        mock_resp.text = "Server Error"
        mock_resp.headers = {}
        mock_post.return_value = mock_resp

        result = create_complaint(SAMPLE_CLIENT_CONTEXT, SAMPLE_COMPLAINT_DATA)

        assert result["success"] is False
        assert result["complaint_id"] is None
        # Ensure no GEI- or FT- prefixed ID is generated
        assert result.get("fallback") is False


# ── Test: Logging ──────────────────────────────────────────────────────────

class TestLogging:
    """Verifies structured logging output for Render."""

    def test_logs_contain_request_id(self, mocker, caplog):
        """Every log line for a complaint must contain the same request_id."""
        mock_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": True, "complaintId": "LOG-1"}
        mock_resp.headers = {}
        mock_post.return_value = mock_resp

        with caplog.at_level("INFO"):
            create_complaint(SAMPLE_CLIENT_CONTEXT, SAMPLE_COMPLAINT_DATA)

        factech_logs = [r.message for r in caplog.records if "[FACTECH_COMPLAINT]" in r.message]
        assert len(factech_logs) > 0

        # Extract request_id from first log
        import re
        match = re.search(r'request_id=([a-f0-9]+)', factech_logs[0])
        assert match is not None
        req_id = match.group(1)

        # All FACTECH_COMPLAINT logs must share the same request_id
        for log_msg in factech_logs:
            assert f"request_id={req_id}" in log_msg

    def test_logs_show_payload(self, mocker, caplog):
        """Logs must show the exact payload sent to Factech."""
        mock_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": True, "complaintId": "LOG-2"}
        mock_resp.headers = {}
        mock_post.return_value = mock_resp

        with caplog.at_level("INFO"):
            create_complaint(SAMPLE_CLIENT_CONTEXT, SAMPLE_COMPLAINT_DATA)

        log_text = " ".join(r.message for r in caplog.records)
        assert "Payload:" in log_text
        assert "test-new55" in log_text
        assert "Electrical" in log_text

    def test_logs_show_http_status(self, mocker, caplog):
        """Logs must show the HTTP status code."""
        mock_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": True, "complaintId": "LOG-3"}
        mock_resp.headers = {}
        mock_post.return_value = mock_resp

        with caplog.at_level("INFO"):
            create_complaint(SAMPLE_CLIENT_CONTEXT, SAMPLE_COMPLAINT_DATA)

        log_text = " ".join(r.message for r in caplog.records)
        assert "HTTP Status: 200" in log_text

    def test_logs_show_success_result(self, mocker, caplog):
        """Logs must clearly indicate SUCCESS."""
        mock_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": True, "complaintId": "LOG-4"}
        mock_resp.headers = {}
        mock_post.return_value = mock_resp

        with caplog.at_level("INFO"):
            create_complaint(SAMPLE_CLIENT_CONTEXT, SAMPLE_COMPLAINT_DATA)

        log_text = " ".join(r.message for r in caplog.records)
        assert "Complaint Creation Result: SUCCESS" in log_text

    def test_logs_show_failure_result(self, mocker, caplog):
        """Logs must clearly indicate FAILED."""
        mock_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"message": "Bad request"}
        mock_resp.text = "Bad request"
        mock_resp.headers = {}
        mock_post.return_value = mock_resp

        with caplog.at_level("INFO"):
            create_complaint(SAMPLE_CLIENT_CONTEXT, SAMPLE_COMPLAINT_DATA)

        log_text = " ".join(r.message for r in caplog.records)
        assert "FAILED" in log_text


# ── Test: Security (Masked Headers) ──────────────────────────────────────

class TestSecurity:
    """Verifies sensitive values are never logged."""

    def test_mask_sensitive_headers(self):
        """API keys and auth headers must be masked."""
        headers = {
            "Content-Type": "application/json",
            "apiKey": "84kRVwKiBZrjJL2loRWXlhh_u6AJp_b6Wq_OKsbm250",
            "x-api-key": "84kRVwKiBZrjJL2loRWXlhh_u6AJp_b6Wq_OKsbm250",
            "Authorization": "Bearer secret-token",
        }
        masked = _mask_sensitive_headers(headers)

        assert masked["Content-Type"] == "application/json"
        assert masked["apiKey"] == "***MASKED***"
        assert masked["x-api-key"] == "***MASKED***"
        assert masked["Authorization"] == "***MASKED***"

    def test_logs_do_not_contain_api_key(self, mocker, caplog):
        """Logs must NOT contain the actual API key value."""
        mock_post = mocker.patch("requests.post")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"success": True, "complaintId": "SEC-1"}
        mock_resp.headers = {}
        mock_post.return_value = mock_resp

        with caplog.at_level("INFO"):
            create_complaint(SAMPLE_CLIENT_CONTEXT, SAMPLE_COMPLAINT_DATA)

        log_text = " ".join(r.message for r in caplog.records)
        # The actual API key must not appear
        assert "84kRVwKiBZrjJL2loRWXlhh" not in log_text


# ── Test: Request ID Generation ───────────────────────────────────────────

class TestRequestId:

    def test_request_id_is_unique(self):
        """Each request should get a unique ID."""
        ids = {_generate_request_id() for _ in range(100)}
        assert len(ids) == 100

    def test_request_id_is_hex(self):
        """Request ID should be a 12-char hex string."""
        rid = _generate_request_id()
        assert len(rid) == 12
        int(rid, 16)  # Should not raise ValueError


# ── Test: WhatsApp User Messaging ─────────────────────────────────────────

class TestWhatsAppMessaging:
    """Verifies the user sees correct messages based on Factech response."""

    def test_success_message_only_on_real_success(self, mocker):
        """User should see success message ONLY when Factech confirms."""
        from clients.flows import handle_client_text

        mock_send_text = mocker.patch("clients.flows.send_text")
        mock_post_opts = mocker.patch("clients.flows.send_post_complaint_options")

        mocker.patch("clients.flows.create_complaint", return_value={
            "success": True,
            "complaint_id": "0451",
            "message": "Complaint created",
        })

        mock_state_res = MagicMock()
        mock_state_res.data = [{
            "action": "AWAITING_CLIENT_COMPLAINT_DESC",
            "metadata": {"client_context": SAMPLE_CLIENT_CONTEXT},
        }]
        mock_db = MagicMock()
        mock_db.select.return_value.eq.return_value.execute.return_value = mock_state_res
        mock_db.delete.return_value.eq.return_value.execute.return_value = MagicMock()
        mocker.patch("clients.flows.supabase.table", return_value=mock_db)

        handle_client_text(SAMPLE_CLIENT_CONTEXT["mobile_number"], "test-new55")

        # Find the success message call
        sent_msgs = [c[0][1] for c in mock_send_text.call_args_list]
        success_msgs = [m for m in sent_msgs if "Complaint Logged Successfully" in m]
        assert len(success_msgs) == 1
        assert "#0451" in success_msgs[0]

    def test_failure_message_when_api_fails(self, mocker):
        """User should see failure message when Factech rejects the complaint."""
        from clients.flows import handle_client_text

        mock_send_text = mocker.patch("clients.flows.send_text")
        mock_post_opts = mocker.patch("clients.flows.send_post_complaint_options")

        mocker.patch("clients.flows.create_complaint", return_value={
            "success": False,
            "complaint_id": None,
            "message": "Factech API error: Invalid unit_no",
            "raw": {"status": "error", "message": "Invalid unit_no"},
        })

        mock_state_res = MagicMock()
        mock_state_res.data = [{
            "action": "AWAITING_CLIENT_COMPLAINT_DESC",
            "metadata": {"client_context": SAMPLE_CLIENT_CONTEXT},
        }]
        mock_db = MagicMock()
        mock_db.select.return_value.eq.return_value.execute.return_value = mock_state_res
        mock_db.delete.return_value.eq.return_value.execute.return_value = MagicMock()
        mocker.patch("clients.flows.supabase.table", return_value=mock_db)

        handle_client_text(SAMPLE_CLIENT_CONTEXT["mobile_number"], "test-new55")

        sent_msgs = [c[0][1] for c in mock_send_text.call_args_list]
        # Must NOT contain success message
        success_msgs = [m for m in sent_msgs if "Complaint Logged Successfully" in m]
        assert len(success_msgs) == 0

        # Must contain failure message
        failure_msgs = [m for m in sent_msgs if "Unable to register" in m]
        assert len(failure_msgs) == 1

    def test_no_fake_complaint_id_shown_to_user(self, mocker):
        """When API fails, user should NOT see a fake GEI-xxxxx or FT-xxxxx ID."""
        from clients.flows import handle_client_text

        mock_send_text = mocker.patch("clients.flows.send_text")
        mocker.patch("clients.flows.send_post_complaint_options")

        mocker.patch("clients.flows.create_complaint", return_value={
            "success": False,
            "complaint_id": None,
            "message": "Factech API timeout",
            "raw": {},
        })

        mock_state_res = MagicMock()
        mock_state_res.data = [{
            "action": "AWAITING_CLIENT_COMPLAINT_DESC",
            "metadata": {"client_context": SAMPLE_CLIENT_CONTEXT},
        }]
        mock_db = MagicMock()
        mock_db.select.return_value.eq.return_value.execute.return_value = mock_state_res
        mock_db.delete.return_value.eq.return_value.execute.return_value = MagicMock()
        mocker.patch("clients.flows.supabase.table", return_value=mock_db)

        handle_client_text(SAMPLE_CLIENT_CONTEXT["mobile_number"], "test-new55")

        sent_msgs = [c[0][1] for c in mock_send_text.call_args_list]
        all_text = " ".join(sent_msgs)
        # No fake GEI- or FT- IDs should appear
        import re
        fake_ids = re.findall(r'#(GEI-\d+|FT-\d+)', all_text)
        assert len(fake_ids) == 0
