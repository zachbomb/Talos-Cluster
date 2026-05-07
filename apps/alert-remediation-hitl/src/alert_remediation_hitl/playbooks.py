"""Playbook registry + Kubernetes Job dispatcher.

Playbooks are YAML manifests under
clusters/main/kubernetes/system/alert-remediation/app/playbook-*.yaml.
They register themselves via a `remediation: <name>` label match. Receivers
load the playbook-registry ConfigMap at startup and dispatch by name.
"""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from kubernetes import client as k8s_client  # type: ignore[import-untyped]
from kubernetes import config as k8s_config  # type: ignore[import-untyped]

_LOGGER = logging.getLogger(__name__)


@dataclass
class Playbook:
    name: str
    matches: dict[str, str]
    service_account_name: str
    rate_limit_seconds: int
    job_spec: dict[str, Any] = field(default_factory=dict)


class PlaybookRegistry:
    """Loads playbook manifests at startup. Hot-reload deferred to follow-up
    (a ConfigMap update + receiver restart is acceptable for v1)."""

    def __init__(self, registry_path: str | Path):
        self._registry_path = Path(registry_path)
        self._playbooks: dict[str, Playbook] = {}

    def load(self) -> None:
        if not self._registry_path.exists():
            _LOGGER.warning("Playbook registry not found at %s — no playbooks loaded.", self._registry_path)
            return
        with self._registry_path.open() as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            return
        for entry in data.get("playbooks", []):
            pb = Playbook(
                name=entry["name"],
                matches=dict(entry.get("matches", {})),
                service_account_name=entry["serviceAccountName"],
                rate_limit_seconds=entry.get("rateLimitSeconds", 300),
                job_spec=copy.deepcopy(entry.get("jobSpec", {})),
            )
            self._playbooks[pb.name] = pb
        _LOGGER.info("Loaded %d playbooks: %s", len(self._playbooks), list(self._playbooks))

    def get(self, name: str) -> Playbook | None:
        return self._playbooks.get(name)


class JobDispatcher:
    """Materializes a playbook's jobSpec into a real Kubernetes Job."""

    def __init__(self, namespace: str):
        self._namespace = namespace
        try:
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            try:
                k8s_config.load_kube_config()
            except Exception:  # pragma: no cover - tests stub this client
                _LOGGER.debug("No kube config available; JobDispatcher will fail at runtime if used.")
        self._batch = k8s_client.BatchV1Api()

    @staticmethod
    def _job_name(fingerprint: str, playbook: str) -> str:
        """Build a DNS-1123-compliant Job name.

        K8s names: max 63 chars, lowercase alphanumerics + `-`, must start/end
        with alphanumeric. Sanitize the playbook name (which can come from
        user-authored YAML and may contain underscores or capitals) so we
        don't fail Job creation with an invalid-name error.
        """
        import re

        short_fp = re.sub(r"[^a-z0-9]", "", fingerprint.lower())[:16]
        sanitized_pb = re.sub(r"[^a-z0-9-]", "-", playbook.lower()).strip("-")
        return f"hitl-{sanitized_pb}-{short_fp}"[:63]

    def find_existing_jobs(self, fingerprint: str) -> list[k8s_client.V1Job]:
        """Used by reconciler to adopt running Jobs after pod restart."""
        label_selector = f"alerting.local/fingerprint={fingerprint}"
        resp = self._batch.list_namespaced_job(
            namespace=self._namespace, label_selector=label_selector
        )
        return list(resp.items)

    def create_job(self, *, playbook: Playbook, fingerprint: str) -> str:
        """Materialize and create the Job. Returns the Job name."""
        job_name = self._job_name(fingerprint, playbook.name)
        spec = copy.deepcopy(playbook.job_spec)
        # Stamp identifying labels onto the Job + its Pods so the reconciler
        # can find them by fingerprint after a restart.
        labels = {
            "alerting.local/fingerprint": fingerprint,
            "alerting.local/playbook": playbook.name,
        }
        # Ensure activeDeadlineSeconds + backoffLimit + restartPolicy are set
        # to the safe defaults if the playbook didn't specify them.
        spec.setdefault("activeDeadlineSeconds", 240)
        spec.setdefault("backoffLimit", 0)
        template = spec.setdefault("template", {})
        template_metadata = template.setdefault("metadata", {})
        existing_labels = template_metadata.setdefault("labels", {})
        existing_labels.update(labels)
        pod_spec = template.setdefault("spec", {})
        pod_spec.setdefault("restartPolicy", "Never")
        pod_spec.setdefault("serviceAccountName", playbook.service_account_name)
        body = k8s_client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=k8s_client.V1ObjectMeta(
                name=job_name, namespace=self._namespace, labels=labels
            ),
            spec=spec,
        )
        self._batch.create_namespaced_job(namespace=self._namespace, body=body)
        return job_name

    def get_job(self, job_name: str) -> k8s_client.V1Job | None:
        try:
            return self._batch.read_namespaced_job(name=job_name, namespace=self._namespace)
        except k8s_client.exceptions.ApiException as exc:
            if exc.status == 404:
                return None
            raise
