from flask import Flask, jsonify, request, Response
from flask_cors import CORS
import psutil
import requests
import sqlite3
import time
from datetime import datetime, timezone, timedelta
import os

import db
import metrics

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")


def github_headers():
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


app = Flask(__name__)
CORS(app)


# Seed services — copied to the database on first startup if the DB is empty.
SEED_SERVICES = [
    {"name": "Google", "url": "https://www.google.com"},
    {"name": "GitHub", "url": "https://github.com"},
    {"name": "Gitea", "url": "https://gitea.dev.bodnarescu.ro"},
]


def seed_services_if_empty():
    """If the database has no services, populate it with the defaults."""
    existing = db.list_monitored_services()
    if existing:
        return
    for service in SEED_SERVICES:
        db.add_monitored_service(service["name"], service["url"])


@app.route('/health')
@metrics.track_request('health')
def health():
    return jsonify({"status": "ok", "service": "pulse-backend"})


@app.route('/')
@metrics.track_request('index')
def index():
    return jsonify({"message": "Pulse API is running"})


@app.route('/metrics')
@metrics.track_request('metrics')
def system_metrics():
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('/')

    # Update gauges so Prometheus sees the latest values
    metrics.cpu_percent.set(cpu)
    metrics.memory_percent.set(mem.percent)
    metrics.disk_percent.set(disk.percent)

    return jsonify({
        "cpu": {"percent": cpu},
        "memory": {
            "total": mem.total,
            "used": mem.used,
            "percent": mem.percent
        },
        "disk": {
            "total": disk.total,
            "used": disk.used,
            "percent": disk.percent
        }
    })


@app.route('/uptime')
@metrics.track_request('uptime')
def uptime():
    seed_services_if_empty()
    services = db.list_monitored_services()

    # Update the gauge for "services count"
    metrics.monitored_services_count.set(len(services))

    results = []
    for service in services:
        try:
            start = time.time()
            response = requests.get(service["url"], timeout=5)
            latency = round((time.time() - start) * 1000, 2)
            results.append({
                "name": service["name"],
                "url": service["url"],
                "status": "up" if response.status_code == 200 else "degraded",
                "status_code": response.status_code,
                "latency_ms": latency
            })
        except Exception as e:
            results.append({
                "name": service["name"],
                "url": service["url"],
                "status": "down",
                "error": str(e)
            })
    return jsonify({"services": results})


@app.route('/dora')
@metrics.track_request('dora')
def dora():
    headers = github_headers()
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    commits_url = "https://api.github.com/repos/Bragashh/pulse/commits?sha=main&per_page=100"
    commits_resp = requests.get(commits_url, headers=headers)
    commits_data = commits_resp.json()

    if isinstance(commits_data, list):
        recent_commits = [
            c for c in commits_data
            if datetime.fromisoformat(c["commit"]["author"]["date"].replace("Z", "+00:00")) > week_ago
        ]
        commits_count = len(recent_commits)
    else:
        commits_count = 0

    runs_url = "https://api.github.com/repos/Bragashh/pulse/actions/runs?per_page=20"
    runs_resp = requests.get(runs_url, headers=headers)
    runs_data = runs_resp.json()
    runs = runs_data.get("workflow_runs", []) if isinstance(runs_data, dict) else []

    total_runs = len(runs)
    failed_runs = len([r for r in runs if r["conclusion"] == "failure"])
    failure_rate = round((failed_runs / total_runs) * 100, 1) if total_runs > 0 else 0

    return jsonify({
        "deployment_frequency": {
            "commits_last_7_days": commits_count,
            "per_day": round(commits_count / 7, 1)
        },
        "change_failure_rate": {
            "total_runs": total_runs,
            "failed_runs": failed_runs,
            "failure_rate_percent": failure_rate
        }
    })


@app.route('/score')
@metrics.track_request('score')
def score():
    total = 100

    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory().percent
    disk = psutil.disk_usage('/').percent

    if cpu > 80: total -= 20
    elif cpu > 60: total -= 10

    if mem > 80: total -= 20
    elif mem > 60: total -= 10

    if disk > 80: total -= 20
    elif disk > 60: total -= 10

    for service in db.list_monitored_services():
        try:
            r = requests.get(service["url"], timeout=5)
            if r.status_code != 200:
                total -= 15
        except:
            total -= 15

    runs_url = "https://api.github.com/repos/Bragashh/pulse/actions/runs?per_page=20"
    runs_resp = requests.get(runs_url, headers=github_headers())
    runs_data = runs_resp.json()
    runs = runs_data.get("workflow_runs", []) if isinstance(runs_data, dict) else []
    total_runs = len(runs)
    failed_runs = len([r for r in runs if r["conclusion"] == "failure"])
    if total_runs > 0:
        failure_rate = (failed_runs / total_runs) * 100
        if failure_rate > 20: total -= 20
        elif failure_rate > 10: total -= 10

    return jsonify({
        "score": max(0, total),
        "max": 100,
        "status": "healthy" if total >= 80 else "degraded" if total >= 50 else "critical"
    })


# --- Service management endpoints (self-service Phase 1) ---

@app.route('/services', methods=['GET'])
@metrics.track_request('services_list')
def list_services():
    """Return all currently monitored services."""
    services = db.list_monitored_services()
    return jsonify({"services": services})


@app.route('/services', methods=['POST'])
@metrics.track_request('services_create')
def create_service():
    """Add a new monitored service."""
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip()
    url = data.get('url', '').strip()

    if not name:
        return jsonify({"error": "name is required"}), 400
    if not url:
        return jsonify({"error": "url is required"}), 400

    if not (url.startswith('http://') or url.startswith('https://')):
        return jsonify({"error": "url must start with http:// or https://"}), 400

    try:
        service_id = db.add_monitored_service(name, url)
    except sqlite3.IntegrityError:
        return jsonify({"error": f"a service named '{name}' already exists"}), 409

    return jsonify({
        "id": service_id,
        "name": name,
        "url": url,
    }), 201


@app.route('/services/<int:service_id>', methods=['DELETE'])
@metrics.track_request('services_delete')
def delete_service(service_id):
    """Soft-delete a monitored service."""
    deleted = db.soft_delete_monitored_service(service_id)
    if not deleted:
        return jsonify({"error": "service not found or already deleted"}), 404
    return jsonify({"id": service_id, "deleted": True})


@app.route('/services/<int:service_id>/restore', methods=['POST'])
@metrics.track_request('services_restore')
def restore_service(service_id):
    """Restore a soft-deleted service."""
    restored = db.restore_monitored_service(service_id)
    if not restored:
        return jsonify({"error": "service not found or not deleted"}), 404
    return jsonify({"id": service_id, "restored": True})


# --- Prometheus scrape endpoint ---

@app.route('/prometheus-metrics')
def prometheus_metrics():
    """Endpoint Prometheus scrapes to collect all defined metrics."""
    body, content_type = metrics.metrics_response()
    return Response(body, mimetype=content_type)

# --- Deployment endpoints (self-service Phase 3) ---

import threading
import deployer


def _async_poll_status(deployment_id: int, service_name: str, max_attempts: int = 30):
    """
    Poll the deployment status in a background thread and update the DB row
    as the status changes. Stops on healthy, failed, or after max_attempts.
    """
    for _ in range(max_attempts):
        time.sleep(2)  # poll every 2 seconds
        try:
            status = deployer.deployment_status(service_name)
            db_status = status["status"]
            if db_status in ("healthy", "failed", "not_found"):
                final_status = db_status if db_status != "not_found" else "failed"
                db.update_deployment_status(deployment_id, final_status)
                return
            # Otherwise it's "pending" — keep polling
        except Exception:
            db.update_deployment_status(deployment_id, "failed")
            return

    # Timed out
    db.update_deployment_status(deployment_id, "failed")


@app.route('/services/deploy', methods=['POST'])
@metrics.track_request('services_deploy')
def deploy_service_endpoint():
    """
    Deploy a new service to Kubernetes.

    Body: { name, image, port, replicas, environment }

    Returns 202 (Accepted) immediately; deployment continues in the background.
    Caller polls GET /api/deployments to see status updates.
    """
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip()
    image = data.get('image', '').strip()
    port = data.get('port')
    replicas = data.get('replicas', 1)
    environment = data.get('environment', 'staging').strip()

    # Validate
    if not name:
        return jsonify({"error": "name is required"}), 400
    if not image:
        return jsonify({"error": "image is required"}), 400
    if not isinstance(port, int) or port < 1 or port > 65535:
        return jsonify({"error": "port must be an integer between 1 and 65535"}), 400
    if not isinstance(replicas, int) or replicas < 1 or replicas > 10:
        return jsonify({"error": "replicas must be an integer between 1 and 10"}), 400
    if environment not in ("staging", "production"):
        return jsonify({"error": "environment must be 'staging' or 'production'"}), 400

    # Avoid name collisions per environment
    existing = db.get_deployed_service_by_name(name, environment)
    if existing:
        return jsonify({
            "error": f"a service named '{name}' already exists in {environment}"
        }), 409

    # Record the service in the DB
    service_id = db.add_deployed_service(name, environment, image, port, replicas)
    deployment_id = db.add_deployment(service_id, image, environment, status="deploying")

    # Trigger the actual Kubernetes deploy
    try:
        result = deployer.deploy_service(name=name, image=image, port=port, replicas=replicas)
    except Exception as e:
        db.update_deployment_status(deployment_id, "failed")
        return jsonify({"error": f"deployment failed: {str(e)}"}), 500

    # Start background polling for health
    thread = threading.Thread(
        target=_async_poll_status,
        args=(deployment_id, name),
        daemon=True,
    )
    thread.start()

    return jsonify({
        "service_id": service_id,
        "deployment_id": deployment_id,
        "name": name,
        "environment": environment,
        "node_port": result["node_port"],
        "status": "deploying",
    }), 202


@app.route('/deployments', methods=['GET'])
@metrics.track_request('deployments_list')
def list_deployments():
    """List all deployed services with their current deployment status."""
    services = db.list_deployed_services()
    result = []
    for svc in services:
        # Get the most recent deployment for this service
        deployments = db.list_deployments_for_service(svc["id"], limit=1)
        latest = deployments[0] if deployments else None
        result.append({
            **svc,
            "latest_status": latest["status"] if latest else "unknown",
            "latest_deployed_at": latest["deployed_at"] if latest else None,
        })
    return jsonify({"deployed_services": result})


@app.route('/deployments/<name>', methods=['DELETE'])
@metrics.track_request('deployments_delete')
def remove_deployed_service(name):
    """Delete a deployed service from both Kubernetes and the database."""
    environment = request.args.get('environment', 'staging')

    svc = db.get_deployed_service_by_name(name, environment)
    if not svc:
        return jsonify({"error": "service not found"}), 404

    # Production deployments are suffixed with -prod in Kubernetes
    deployment_name = name if environment == "staging" else f"{name}-prod"

    try:
        deployer.delete_deployment(deployment_name)
    except Exception as e:
        return jsonify({"error": f"kubernetes delete failed: {str(e)}"}), 500

    db.soft_delete_deployed_service(svc["id"])

    return jsonify({"name": name, "environment": environment, "deleted": True})

    
@app.route('/deployments/<name>/promote', methods=['POST'])
@metrics.track_request('deployments_promote')
def promote_deployment(name):
    """
    Promote a service from staging to production.

    Reads the staging deployment's image/port/replicas, then deploys the same
    parameters under the 'production' environment. Both environments run in parallel.
    """
    # Find the staging service
    staging_svc = db.get_deployed_service_by_name(name, "staging")
    if not staging_svc:
        return jsonify({"error": f"no staging deployment named '{name}' found"}), 404

    # Check if production already exists for this name
    prod_svc = db.get_deployed_service_by_name(name, "production")
    if prod_svc:
        return jsonify({
            "error": f"a production deployment named '{name}' already exists; "
                     "delete it first or use a different name"
        }), 409

    # Use the staging service's image/port/replicas as the production source of truth
    image = staging_svc["image"]
    port = staging_svc["port"]
    replicas = staging_svc["replicas"]

    # Record in DB
    prod_service_id = db.add_deployed_service(
        name=name,
        environment="production",
        image=image,
        port=port,
        replicas=replicas,
    )
    deployment_id = db.add_deployment(
        prod_service_id, image, "production", status="deploying"
    )

    # The deployer doesn't currently namespace by environment — it uses pulse-deployed
    # for everything. To keep staging and production separated, we suffix the production
    # deployment name. This way both can coexist in the same namespace.
    prod_deployment_name = f"{name}-prod"

    try:
        result = deployer.deploy_service(
            name=prod_deployment_name,
            image=image,
            port=port,
            replicas=replicas,
        )
    except Exception as e:
        db.update_deployment_status(deployment_id, "failed")
        return jsonify({"error": f"promotion failed: {str(e)}"}), 500

    # Background poll for health
    thread = threading.Thread(
        target=_async_poll_status,
        args=(deployment_id, prod_deployment_name),
        daemon=True,
    )
    thread.start()

    return jsonify({
        "service_id": prod_service_id,
        "deployment_id": deployment_id,
        "name": name,
        "deployment_name": prod_deployment_name,
        "environment": "production",
        "image": image,
        "node_port": result["node_port"],
        "status": "deploying",
    }), 202

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)