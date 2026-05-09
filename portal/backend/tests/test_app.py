import importlib
import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    """
    Provides a test client for the Flask app with an isolated temp database.
    Each test gets a fresh DB file that's cleaned up automatically.
    """
    test_db_path = tmp_path / "test_pulse.db"
    monkeypatch.setenv("PULSE_DB_PATH", str(test_db_path))

    # Reload db module so it picks up the new env var path
    import db
    importlib.reload(db)

    # Reload app so it uses the reloaded db module
    import app
    importlib.reload(app)

    app.app.config["TESTING"] = True
    with app.app.test_client() as client:
        yield client


# --- /health ---

def test_health_endpoint_returns_200(client):
    """The /health endpoint should always return 200 OK."""
    response = client.get("/health")
    assert response.status_code == 200


def test_health_endpoint_returns_expected_json(client):
    """The /health endpoint should return the expected JSON shape."""
    response = client.get("/health")
    data = response.get_json()
    assert data["status"] == "ok"
    assert data["service"] == "pulse-backend"


# --- / (index) ---

def test_index_endpoint_returns_200(client):
    """The root endpoint should return 200 OK."""
    response = client.get("/")
    assert response.status_code == 200


def test_index_endpoint_returns_message(client):
    """The root endpoint should return a message field."""
    response = client.get("/")
    data = response.get_json()
    assert "message" in data


# --- /metrics ---

def test_metrics_endpoint_returns_200(client):
    """The /metrics endpoint should return 200 OK."""
    response = client.get("/metrics")
    assert response.status_code == 200


def test_metrics_endpoint_has_expected_keys(client):
    """The /metrics endpoint should have cpu, memory, and disk sections."""
    response = client.get("/metrics")
    data = response.get_json()
    assert "cpu" in data
    assert "memory" in data
    assert "disk" in data


def test_metrics_cpu_has_percent(client):
    """CPU section should report percent as a number."""
    response = client.get("/metrics")
    data = response.get_json()
    assert "percent" in data["cpu"]
    assert isinstance(data["cpu"]["percent"], (int, float))


def test_metrics_memory_has_required_fields(client):
    """Memory section should include total, used, and percent."""
    response = client.get("/metrics")
    data = response.get_json()
    assert "total" in data["memory"]
    assert "used" in data["memory"]
    assert "percent" in data["memory"]


def test_metrics_disk_has_required_fields(client):
    """Disk section should include total, used, and percent."""
    response = client.get("/metrics")
    data = response.get_json()
    assert "total" in data["disk"]
    assert "used" in data["disk"]
    assert "percent" in data["disk"]


# --- /score ---

def test_score_endpoint_returns_200(client):
    """The /score endpoint should return 200 OK."""
    response = client.get("/score")
    assert response.status_code == 200


def test_score_endpoint_returns_score_in_range(client):
    """The /score endpoint should return a score between 0 and 100."""
    response = client.get("/score")
    data = response.get_json()
    assert "score" in data
    assert 0 <= data["score"] <= 100


def test_score_endpoint_returns_status(client):
    """The /score endpoint should return a status field."""
    response = client.get("/score")
    data = response.get_json()
    assert "status" in data
    assert data["status"] in ("healthy", "degraded", "critical")


# --- /uptime ---

def test_uptime_endpoint_returns_200(client, mocker):
    """The /uptime endpoint should return 200 even if all upstream services are mocked as up."""
    mock_response = mocker.Mock()
    mock_response.status_code = 200
    mocker.patch("app.requests.get", return_value=mock_response)

    response = client.get("/uptime")
    assert response.status_code == 200


def test_uptime_returns_services_list(client, mocker):
    """The /uptime endpoint should return a list of services."""
    mock_response = mocker.Mock()
    mock_response.status_code = 200
    mocker.patch("app.requests.get", return_value=mock_response)

    response = client.get("/uptime")
    data = response.get_json()
    assert "services" in data
    assert isinstance(data["services"], list)
    assert len(data["services"]) == 3  # Google, GitHub, Gitea


def test_uptime_marks_services_up_when_200(client, mocker):
    """All services should be marked 'up' when the mock returns 200."""
    mock_response = mocker.Mock()
    mock_response.status_code = 200
    mocker.patch("app.requests.get", return_value=mock_response)

    response = client.get("/uptime")
    data = response.get_json()
    for service in data["services"]:
        assert service["status"] == "up"


def test_uptime_marks_services_down_on_exception(client, mocker):
    """Services should be marked 'down' when the request raises an exception."""
    mocker.patch("app.requests.get", side_effect=Exception("Connection refused"))

    response = client.get("/uptime")
    data = response.get_json()
    for service in data["services"]:
        assert service["status"] == "down"
        assert "error" in service


# --- /dora ---

def test_dora_endpoint_returns_200(client, mocker):
    """The /dora endpoint should return 200 with mocked GitHub API."""
    mock_response = mocker.Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = []  # Empty list of commits
    mocker.patch("app.requests.get", return_value=mock_response)

    response = client.get("/dora")
    assert response.status_code == 200


def test_dora_handles_empty_commit_list(client, mocker):
    """The /dora endpoint should return zero commits when GitHub returns empty list."""
    mock_response = mocker.Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = []
    mocker.patch("app.requests.get", return_value=mock_response)

    response = client.get("/dora")
    data = response.get_json()
    assert data["deployment_frequency"]["commits_last_7_days"] == 0


def test_dora_handles_rate_limit_response(client, mocker):
    """The /dora endpoint should not crash if GitHub returns a non-list (rate limit) response."""
    mock_response = mocker.Mock()
    mock_response.status_code = 403
    mock_response.json.return_value = {"message": "API rate limit exceeded"}
    mocker.patch("app.requests.get", return_value=mock_response)

    response = client.get("/dora")
    assert response.status_code == 200
    data = response.get_json()
    assert data["deployment_frequency"]["commits_last_7_days"] == 0
    assert data["change_failure_rate"]["total_runs"] == 0


# --- /services CRUD ---

def test_list_services_empty_initially(client):
    """A fresh database returns an empty services list."""
    response = client.get("/services")
    assert response.status_code == 200
    data = response.get_json()
    assert data == {"services": []}


def test_create_service_returns_201(client):
    """Creating a service returns 201 with the new service data."""
    response = client.post("/services", json={
        "name": "Google",
        "url": "https://www.google.com"
    })
    assert response.status_code == 201
    data = response.get_json()
    assert data["name"] == "Google"
    assert data["url"] == "https://www.google.com"
    assert "id" in data


def test_create_service_then_list_includes_it(client):
    """A created service should appear in the list."""
    client.post("/services", json={
        "name": "Google",
        "url": "https://www.google.com"
    })

    response = client.get("/services")
    data = response.get_json()
    assert len(data["services"]) == 1
    assert data["services"][0]["name"] == "Google"


def test_create_service_rejects_missing_name(client):
    """POST without a name should return 400."""
    response = client.post("/services", json={"url": "https://www.google.com"})
    assert response.status_code == 400
    assert "name" in response.get_json()["error"].lower()


def test_create_service_rejects_missing_url(client):
    """POST without a url should return 400."""
    response = client.post("/services", json={"name": "Google"})
    assert response.status_code == 400
    assert "url" in response.get_json()["error"].lower()


def test_create_service_rejects_invalid_url(client):
    """POST with a non-http url should return 400."""
    response = client.post("/services", json={
        "name": "Google",
        "url": "not-a-real-url"
    })
    assert response.status_code == 400


def test_create_service_rejects_duplicate_name(client):
    """Creating two services with the same name should return 409."""
    client.post("/services", json={
        "name": "Google",
        "url": "https://www.google.com"
    })
    response = client.post("/services", json={
        "name": "Google",
        "url": "https://www.google.com.au"
    })
    assert response.status_code == 409


def test_delete_service_returns_200(client):
    """Deleting an existing service returns 200."""
    create_response = client.post("/services", json={
        "name": "Google",
        "url": "https://www.google.com"
    })
    service_id = create_response.get_json()["id"]

    response = client.delete(f"/services/{service_id}")
    assert response.status_code == 200
    assert response.get_json()["deleted"] is True


def test_delete_service_removes_from_list(client):
    """A deleted service no longer appears in the list."""
    create_response = client.post("/services", json={
        "name": "Google",
        "url": "https://www.google.com"
    })
    service_id = create_response.get_json()["id"]

    client.delete(f"/services/{service_id}")

    response = client.get("/services")
    assert response.get_json()["services"] == []


def test_delete_nonexistent_service_returns_404(client):
    """Deleting a non-existent service returns 404."""
    response = client.delete("/services/999")
    assert response.status_code == 404


def test_restore_brings_service_back(client):
    """Restoring a deleted service makes it visible again."""
    create_response = client.post("/services", json={
        "name": "Google",
        "url": "https://www.google.com"
    })
    service_id = create_response.get_json()["id"]
    client.delete(f"/services/{service_id}")

    restore_response = client.post(f"/services/{service_id}/restore")
    assert restore_response.status_code == 200

    list_response = client.get("/services")
    assert len(list_response.get_json()["services"]) == 1


def test_restore_nonexistent_returns_404(client):
    """Restoring a service that doesn't exist returns 404."""
    response = client.post("/services/999/restore")
    assert response.status_code == 404


def test_can_recreate_service_after_delete(client):
    """After soft-deleting a service, you should be able to create one with the same name."""
    create1 = client.post("/services", json={
        "name": "Google",
        "url": "https://www.google.com"
    })
    service_id = create1.get_json()["id"]
    client.delete(f"/services/{service_id}")

    create2 = client.post("/services", json={
        "name": "Google",
        "url": "https://www.google.com.au"
    })
    assert create2.status_code == 201
    assert create2.get_json()["id"] != service_id