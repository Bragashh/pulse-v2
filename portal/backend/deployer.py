"""
Kubernetes deployment module for Pulse.

Renders manifest templates with user-supplied parameters and applies
them to the cluster via the Kubernetes Python client.

Status of an in-progress deployment is checked by querying the
Kubernetes API for the Deployment object's readiness.
"""

import os
import time
from kubernetes import client, config
from kubernetes.client.rest import ApiException


PULSE_NAMESPACE = "pulse-deployed"  # Where Pulse-deployed services live


def _load_kube_config():
    """
    Load Kubernetes credentials.

    Tries in-cluster config first (for when Pulse runs as a pod itself),
    falls back to kubeconfig file (for local development).
    """
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


def _ensure_namespace_exists():
    """Create the pulse-deployed namespace if it doesn't already exist."""
    _load_kube_config()
    v1 = client.CoreV1Api()
    try:
        v1.read_namespace(name=PULSE_NAMESPACE)
    except ApiException as e:
        if e.status == 404:
            ns = client.V1Namespace(metadata=client.V1ObjectMeta(name=PULSE_NAMESPACE))
            v1.create_namespace(body=ns)
        else:
            raise


def deploy_service(name: str, image: str, port: int, replicas: int = 1) -> dict:
    """
    Deploy a service to the cluster.

    Creates (or updates) a Deployment and a Service for the given parameters.
    Returns immediately after applying — caller polls deployment_status() for readiness.

    Args:
        name: service name (e.g. "url-shortener")
        image: full container image (e.g. "url-shortener:dev")
        port: container port the app listens on
        replicas: number of pod replicas

    Returns:
        dict with applied manifest names and the assigned NodePort
    """
    _load_kube_config()
    _ensure_namespace_exists()

    apps = client.AppsV1Api()
    core = client.CoreV1Api()

    # --- Deployment ---
    deployment = client.V1Deployment(
        metadata=client.V1ObjectMeta(
            name=name,
            namespace=PULSE_NAMESPACE,
            labels={"app": name, "managed-by": "pulse"},
        ),
        spec=client.V1DeploymentSpec(
            replicas=replicas,
            selector=client.V1LabelSelector(match_labels={"app": name}),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels={"app": name}),
                spec=client.V1PodSpec(
                    containers=[
                        client.V1Container(
                            name=name,
                            image=image,
                            image_pull_policy="Never",  # local images only for now
                            ports=[client.V1ContainerPort(container_port=port)],
                            resources=client.V1ResourceRequirements(
                                requests={"memory": "64Mi", "cpu": "50m"},
                                limits={"memory": "256Mi", "cpu": "500m"},
                            ),
                        )
                    ]
                ),
            ),
        ),
    )

    # Apply (create or update)
    try:
        apps.read_namespaced_deployment(name=name, namespace=PULSE_NAMESPACE)
        apps.replace_namespaced_deployment(
            name=name, namespace=PULSE_NAMESPACE, body=deployment
        )
    except ApiException as e:
        if e.status == 404:
            apps.create_namespaced_deployment(namespace=PULSE_NAMESPACE, body=deployment)
        else:
            raise

    # --- Service ---
    service = client.V1Service(
        metadata=client.V1ObjectMeta(
            name=name,
            namespace=PULSE_NAMESPACE,
            labels={"app": name, "managed-by": "pulse"},
        ),
        spec=client.V1ServiceSpec(
            selector={"app": name},
            ports=[client.V1ServicePort(port=port, target_port=port)],
            type="NodePort",
        ),
    )

    try:
        existing = core.read_namespaced_service(name=name, namespace=PULSE_NAMESPACE)
        # Preserve existing NodePort assignment on update
        service.spec.ports[0].node_port = existing.spec.ports[0].node_port
        core.replace_namespaced_service(
            name=name, namespace=PULSE_NAMESPACE, body=service
        )
    except ApiException as e:
        if e.status == 404:
            core.create_namespaced_service(namespace=PULSE_NAMESPACE, body=service)
        else:
            raise

    # Read the service back to get the assigned NodePort
    created_service = core.read_namespaced_service(name=name, namespace=PULSE_NAMESPACE)
    node_port = created_service.spec.ports[0].node_port

    return {
        "deployment": name,
        "service": name,
        "namespace": PULSE_NAMESPACE,
        "node_port": node_port,
    }


def deployment_status(name: str) -> dict:
    """
    Check the readiness status of a deployed service.

    Returns:
        dict with status ("pending" | "healthy" | "failed"), pod counts, and any failure reason.
    """
    _load_kube_config()
    apps = client.AppsV1Api()

    try:
        dep = apps.read_namespaced_deployment_status(
            name=name, namespace=PULSE_NAMESPACE
        )
    except ApiException as e:
        if e.status == 404:
            return {"status": "not_found", "ready": 0, "desired": 0}
        raise

    desired = dep.spec.replicas or 0
    ready = dep.status.ready_replicas or 0
    available = dep.status.available_replicas or 0

    if ready == desired and desired > 0:
        return {
            "status": "healthy",
            "ready": ready,
            "desired": desired,
            "available": available,
        }

    # Check if any conditions indicate failure
    conditions = dep.status.conditions or []
    for c in conditions:
        if c.type == "Progressing" and c.status == "False":
            return {
                "status": "failed",
                "ready": ready,
                "desired": desired,
                "reason": c.reason or "Unknown",
                "message": c.message or "",
            }

    return {
        "status": "pending",
        "ready": ready,
        "desired": desired,
    }


def delete_deployment(name: str) -> bool:
    """Remove a deployed service entirely (Deployment + Service)."""
    _load_kube_config()
    apps = client.AppsV1Api()
    core = client.CoreV1Api()

    deleted_anything = False

    try:
        apps.delete_namespaced_deployment(name=name, namespace=PULSE_NAMESPACE)
        deleted_anything = True
    except ApiException as e:
        if e.status != 404:
            raise

    try:
        core.delete_namespaced_service(name=name, namespace=PULSE_NAMESPACE)
        deleted_anything = True
    except ApiException as e:
        if e.status != 404:
            raise

    return deleted_anything