# Phase 4 Research: IaC & Drift Management

**Researched:** 2026-03-11
**Domain:** Infrastructure-as-Code (IaC), GitOps, Drift Management, Kubernetes, Ray, KEDA
**Status:** DRAFT

---

## 1. The Challenge: Configuration Drift at Scale

Phase 4 introduces distributed execution (Ray) and event-driven autoscaling (KEDA). Managing these across **Dev, Staging, and Production** manually is prone to "Configuration Drift" — where the live cluster state diverges from the intended design in Git.

### Risks in Phase 4
*   **Ray Inconsistency:** A worker group replica count change in Dev (for cost saving) accidentally leaking into Prod (causing performance degradation).
*   **KEDA Flapping:** GitOps tools attempting to "fix" the replica count that KEDA is actively scaling, leading to infinite reconciliation loops.
*   **Secret Mismatch:** Different API keys or NATS credentials across environments being manually patched and forgotten.

---

## 2. Strategic Solution: Hybrid IaC + GitOps

The industry-standard "Hybrid" approach is recommended for Orchestra:

| Layer | Tool | Responsibility |
|-------|------|----------------|
| **Infrastructure** | **Terraform** | Provisioning EKS/GKE clusters, VPCs, IAM roles, RDS/Postgres, and NATS infra. |
| **Application & Ops** | **ArgoCD** | Managing RayClusters, KEDA ScaledObjects, Deployments, and ConfigMaps inside the cluster. |

### Why ArgoCD for Drift Management?
*   **Continuous Reconciliation:** Unlike Terraform (which only checks for drift during a `plan`), ArgoCD runs *inside* the cluster and detects drift in real-time.
*   **Self-Healing:** Can be configured to automatically revert manual `kubectl edit` changes.
*   **Visual Diff:** Provides a clear UI showing exactly which resource is "Out of Sync" and why.

---

## 3. Implementation Patterns for Orchestra

### Pattern A: Handling Autoscaling (KEDA/Ray)
To prevent "flapping," ArgoCD must be instructed to ignore the `replicas` field for resources managed by autoscalers.

```yaml
# ArgoCD Application snippet
spec:
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/replicas
    - group: ray.io
      kind: RayCluster
      jsonPointers:
        - /spec/workerGroupSpecs/0/replicas
```

### Pattern B: Multi-Environment via ApplicationSets
Use the **ArgoCD ApplicationSet** controller to automatically generate environment-specific applications based on the `deploy/overlays/` directory.

### Pattern C: Secret Management (Sealed Secrets)
To keep the "Truth" entirely in Git without leaking credentials, use **Bitnami Sealed Secrets**.
*   **Dev:** Encrypt `SECRET_KEY` with Dev Public Key → Push to `deploy/overlays/dev/`.
*   **Prod:** Encrypt `SECRET_KEY` with Prod Public Key → Push to `deploy/overlays/prod/`.
*   The cluster-side controller decrypts them at runtime.

---

## 4. Recommended Directory Structure

```text
deploy/
├── base/                # Common manifests (KEDA, RayCluster templates)
│   ├── kustomization.yaml
│   └── orchestra-agent.yaml
└── overlays/
    ├── dev/             # Small instances, 1-2 workers, minReplicas=0
    │   ├── kustomization.yaml
    │   └── patches.yaml
    ├── staging/         # Mirror of prod, but smaller limits
    └── prod/            # High availability, gVisor runtime, minReplicas=1
        ├── kustomization.yaml
        └── patches.yaml
```

---

## 5. Drift Remediation Workflow

1.  **Detection:** ArgoCD UI flags a resource as "Out of Sync."
2.  **Inspection:** Engineer uses `argocd app diff` to see the manual change.
3.  **Decision:**
    *   *If intentional:* Update the manifest in Git, push, and ArgoCD will sync (and the drift is gone).
    *   *If accidental:* Click "Sync" in ArgoCD (or wait for Auto-Sync) to revert the cluster to the Git state.
4.  **Verification:** ArgoCD status returns to "Healthy" and "Synced."
