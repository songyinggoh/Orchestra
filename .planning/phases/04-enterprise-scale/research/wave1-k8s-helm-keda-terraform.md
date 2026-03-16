# Wave 1 Research: Kubernetes, Helm, KEDA & Terraform

**Task:** T-4.2 (Kubernetes + gVisor/Kata + KEDA)
**Sources:** Helm docs (helm.sh), KEDA docs (keda.sh), Terraform Registry (EKS/GKE modules), Phase 4 research (01, 13, 15)
**Date:** 2026-03-12

---

## 1. Helm Chart Architecture

### Directory Structure for Orchestra
```
deploy/helm/orchestra/
├── Chart.yaml              # Chart metadata (apiVersion: v2)
├── values.yaml             # Default configuration
├── values-dev.yaml         # Dev overrides
├── values-prod.yaml        # Production overrides
├── templates/
│   ├── _helpers.tpl        # Named templates (labels, names, selectors)
│   ├── deployment.yaml     # Worker deployment
│   ├── service.yaml        # ClusterIP service
│   ├── serviceaccount.yaml # RBAC service account
│   ├── configmap.yaml      # Orchestra config
│   ├── secret.yaml         # NATS credentials, DID keys
│   ├── hpa.yaml            # HPA for CPU/memory (fallback)
│   ├── keda-scaledobject.yaml  # KEDA autoscaler
│   ├── pdb.yaml            # PodDisruptionBudget
│   └── NOTES.txt           # Post-install instructions
└── charts/                 # Subcharts (NATS, OTel Collector)
```

### Chart.yaml
```yaml
apiVersion: v2
name: orchestra
description: Multi-agent orchestration framework
type: application
version: 0.1.0        # Chart version
appVersion: "4.0.0"   # Orchestra version
dependencies:
  - name: nats
    version: "1.2.x"
    repository: https://nats-io.github.io/k8s/helm/charts/
    condition: nats.enabled
  - name: keda
    version: "2.16.x"
    repository: https://kedacore.github.io/charts
    condition: keda.enabled
```

### values.yaml (Key Sections)
```yaml
replicaCount: 2

image:
  repository: ghcr.io/songyinggoh/orchestra
  tag: ""  # Defaults to Chart.appVersion
  pullPolicy: IfNotPresent

runtime:
  className: ""  # Set to "gvisor" or "kata" for sandboxed pods

resources:
  requests:
    cpu: 250m
    memory: 512Mi
  limits:
    cpu: "2"
    memory: 2Gi

nats:
  enabled: true
  url: "nats://orchestra-nats:4222"
  jetstream:
    enabled: true
    fileStorage:
      size: 10Gi

keda:
  enabled: true
  minReplicaCount: 1
  maxReplicaCount: 20
  lagThreshold: "100"
  activationLagThreshold: "10"

probes:
  liveness:
    path: /health
    initialDelaySeconds: 10
    periodSeconds: 15
  readiness:
    path: /ready
    initialDelaySeconds: 5
    periodSeconds: 10
  startup:
    path: /health
    failureThreshold: 30
    periodSeconds: 5

strategy:
  type: RollingUpdate
  rollingUpdate:
    maxSurge: 1
    maxUnavailable: 0  # Zero-downtime deploys
```

---

## 2. Helm Best Practices

### `_helpers.tpl` Named Templates
```yaml
{{- define "orchestra.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "orchestra.labels" -}}
helm.sh/chart: {{ include "orchestra.chart" . }}
app.kubernetes.io/name: {{ include "orchestra.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "orchestra.selectorLabels" -}}
app.kubernetes.io/name: {{ include "orchestra.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
```

### Deployment Template with Conditional RuntimeClass
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "orchestra.fullname" . }}
  labels: {{- include "orchestra.labels" . | nindent 4 }}
spec:
  replicas: {{ .Values.replicaCount }}
  strategy: {{- toYaml .Values.strategy | nindent 4 }}
  selector:
    matchLabels: {{- include "orchestra.selectorLabels" . | nindent 6 }}
  template:
    metadata:
      labels: {{- include "orchestra.selectorLabels" . | nindent 8 }}
    spec:
      {{- with .Values.runtime.className }}
      runtimeClassName: {{ . }}
      {{- end }}
      serviceAccountName: {{ include "orchestra.serviceAccountName" . }}
      terminationGracePeriodSeconds: 30
      containers:
        - name: orchestra
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
          ports:
            - containerPort: 8000
              name: http
          livenessProbe:
            httpGet:
              path: {{ .Values.probes.liveness.path }}
              port: http
            initialDelaySeconds: {{ .Values.probes.liveness.initialDelaySeconds }}
            periodSeconds: {{ .Values.probes.liveness.periodSeconds }}
          readinessProbe:
            httpGet:
              path: {{ .Values.probes.readiness.path }}
              port: http
            initialDelaySeconds: {{ .Values.probes.readiness.initialDelaySeconds }}
            periodSeconds: {{ .Values.probes.readiness.periodSeconds }}
          startupProbe:
            httpGet:
              path: {{ .Values.probes.startup.path }}
              port: http
            failureThreshold: {{ .Values.probes.startup.failureThreshold }}
            periodSeconds: {{ .Values.probes.startup.periodSeconds }}
          resources: {{- toYaml .Values.resources | nindent 12 }}
          env:
            - name: NATS_URL
              value: {{ .Values.nats.url }}
            - name: ORCHESTRA_ENV
              valueFrom:
                configMapKeyRef:
                  name: {{ include "orchestra.fullname" . }}-config
                  key: environment
```

---

## 3. KEDA NATS JetStream Scaler

### ScaledObject Configuration
```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: {{ include "orchestra.fullname" . }}-scaler
  labels: {{- include "orchestra.labels" . | nindent 4 }}
spec:
  scaleTargetRef:
    name: {{ include "orchestra.fullname" . }}
  minReplicaCount: {{ .Values.keda.minReplicaCount }}
  maxReplicaCount: {{ .Values.keda.maxReplicaCount }}
  pollingInterval: 15
  cooldownPeriod: 60
  fallback:
    failureThreshold: 3
    replicas: {{ .Values.replicaCount }}
  advanced:
    horizontalPodAutoscalerConfig:
      behavior:
        scaleUp:
          stabilizationWindowSeconds: 30
          policies:
            - type: Pods
              value: 4
              periodSeconds: 60
        scaleDown:
          stabilizationWindowSeconds: 300
          policies:
            - type: Percent
              value: 25
              periodSeconds: 60
  triggers:
    - type: nats-jetstream
      metadata:
        natsServerMonitoringEndpoint: "orchestra-nats:8222"
        account: "$G"
        stream: "TASKS"
        consumer: "orchestra-workers"
        lagThreshold: {{ .Values.keda.lagThreshold | quote }}
        activationLagThreshold: {{ .Values.keda.activationLagThreshold | quote }}
        useHttps: "false"
      authenticationRef:
        name: {{ include "orchestra.fullname" . }}-nats-auth
```

### Key KEDA Parameters

| Parameter | Description | Recommended |
|-----------|-------------|-------------|
| `lagThreshold` | Messages behind = 1 replica per N messages | "100" |
| `activationLagThreshold` | Messages to wake from 0→1 | "10" |
| `pollingInterval` | Seconds between metric checks | 15 |
| `cooldownPeriod` | Seconds after last trigger before scale-down | 60 |
| `stream` | JetStream stream name | "TASKS" |
| `consumer` | Consumer name to monitor | "orchestra-workers" |

### How Scaling Works
1. KEDA polls NATS monitoring endpoint every 15s
2. Reads consumer lag (pending messages not yet acked)
3. If lag > `activationLagThreshold` and currently at 0 → scale to 1
4. Desired replicas = ceil(lag / lagThreshold)
5. Scale-up: max 4 pods per 60s (burst protection)
6. Scale-down: max 25% per 60s (stability)
7. If lag = 0 for `cooldownPeriod` → scale to `minReplicaCount`

### TriggerAuthentication (if NATS requires auth)
```yaml
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: {{ include "orchestra.fullname" . }}-nats-auth
spec:
  secretTargetRef:
    - parameter: natsServerMonitoringEndpoint
      name: orchestra-nats-creds
      key: monitoring-url
```

---

## 4. Terraform: AWS EKS Module

### Module: `terraform-aws-modules/eks/aws` v20+

```hcl
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = "orchestra-${var.environment}"
  cluster_version = "1.31"

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  cluster_endpoint_public_access = true  # Set false for prod

  cluster_addons = {
    coredns    = { most_recent = true }
    kube-proxy = { most_recent = true }
    vpc-cni    = { most_recent = true }
  }

  eks_managed_node_groups = {
    # System workloads (no gVisor needed)
    system = {
      instance_types = ["t3.medium"]
      min_size       = 2
      max_size       = 4
      desired_size   = 2
      labels = { "orchestra.dev/role" = "system" }
    }

    # Agent workers (standard runtime)
    agent-workers = {
      instance_types = ["c5.xlarge"]
      min_size       = 1
      max_size       = 20
      desired_size   = 2
      labels = { "orchestra.dev/role" = "agent" }
      taints = [{
        key    = "orchestra.dev/agent-only"
        value  = "true"
        effect = "NO_SCHEDULE"
      }]
    }

    # Secure workers (gVisor sandbox)
    secure-workers = {
      instance_types = ["c5.xlarge"]
      min_size       = 0
      max_size       = 10
      desired_size   = 1
      labels = {
        "orchestra.dev/role"    = "secure-agent"
        "orchestra.dev/sandbox" = "gvisor"
      }
      # gVisor installed via DaemonSet post-provisioning
    }
  }

  # Enable IRSA for KEDA, OTel, etc.
  enable_irsa = true
}
```

### gVisor on EKS (DaemonSet Installer)
EKS doesn't natively support gVisor. Install via DaemonSet:
```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: gvisor-installer
  namespace: kube-system
spec:
  selector:
    matchLabels:
      app: gvisor-installer
  template:
    spec:
      nodeSelector:
        orchestra.dev/sandbox: "gvisor"
      hostPID: true
      initContainers:
        - name: install-runsc
          image: gvisor.dev/gvisor/installer:latest
          securityContext:
            privileged: true
          volumeMounts:
            - name: host
              mountPath: /host
      containers:
        - name: pause
          image: k8s.gcr.io/pause:3.9
      volumes:
        - name: host
          hostPath:
            path: /
```

### RuntimeClass for gVisor
```yaml
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: gvisor
handler: runsc
overhead:
  podFixed:
    memory: "64Mi"
    cpu: "50m"
```

---

## 5. Terraform: GCP GKE Module

### Module: `terraform-google-modules/kubernetes-engine/google` v35+

```hcl
module "gke" {
  source  = "terraform-google-modules/kubernetes-engine/google"
  version = "~> 35.0"

  project_id = var.project_id
  name       = "orchestra-${var.environment}"
  region     = var.region

  kubernetes_version    = "1.31"
  release_channel       = "REGULAR"
  network               = module.vpc.network_name
  subnetwork            = module.vpc.subnets_names[0]
  ip_range_pods         = "pods"
  ip_range_services     = "services"

  # Workload Identity (replaces node SA)
  identity_namespace = "${var.project_id}.svc.id.goog"

  node_pools = [
    {
      name         = "system"
      machine_type = "e2-standard-2"
      min_count    = 2
      max_count    = 4
      auto_upgrade = true
    },
    {
      name           = "agent-workers"
      machine_type   = "c2-standard-4"
      min_count      = 1
      max_count      = 20
      auto_upgrade   = true
      # Native gVisor support on GKE!
      sandbox_config = [{ sandbox_type = "gvisor" }]
    }
  ]

  node_pools_labels = {
    agent-workers = { "orchestra.dev/role" = "agent" }
  }

  node_pools_taints = {
    agent-workers = [{
      key    = "orchestra.dev/agent-only"
      value  = "true"
      effect = "NO_SCHEDULE"
    }]
  }
}
```

### GKE vs EKS: gVisor Support

| Feature | GKE | EKS |
|---------|-----|-----|
| gVisor support | **Native** (`sandbox_config`) | DaemonSet installer needed |
| Setup complexity | One field | ~100 lines of DaemonSet YAML |
| Maintenance | Google-managed updates | Self-managed runsc updates |
| Kata support | No | Via custom AMI |

**Recommendation:** GKE is strongly preferred for gVisor workloads. EKS requires significant additional operational overhead.

---

## 6. Rolling Deployment & Health Probes

### Strategy
```yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxSurge: 1        # One extra pod during rollout
    maxUnavailable: 0  # Zero-downtime: never remove before new is ready
```

### Probe Design for Orchestra Agents

| Probe | Purpose | Endpoint | Timing |
|-------|---------|----------|--------|
| **Startup** | Wait for model loading | `/health` | failureThreshold=30, period=5s (up to 150s) |
| **Liveness** | Detect deadlocks | `/health` | initialDelay=10s, period=15s |
| **Readiness** | Traffic routing | `/ready` | initialDelay=5s, period=10s |

### `/ready` vs `/health`
- `/health` → Process is alive (not deadlocked). Returns 200 if event loop responds.
- `/ready` → Can accept work. Returns 200 only when NATS connected + model loaded + not draining.

### Graceful Shutdown
```python
import signal, asyncio

async def graceful_shutdown(sig):
    """Handle SIGTERM from Kubernetes."""
    # 1. Mark not ready (fail readiness probe)
    app.state.draining = True
    # 2. Finish in-flight tasks (terminationGracePeriodSeconds = 30)
    await drain_current_tasks(timeout=25)
    # 3. Close NATS connection (stops pulling new messages)
    await nats_client.close()
    # 4. Exit
    sys.exit(0)
```

### PodDisruptionBudget
```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: {{ include "orchestra.fullname" . }}-pdb
spec:
  minAvailable: 1
  selector:
    matchLabels: {{- include "orchestra.selectorLabels" . | nindent 6 }}
```

---

## 7. Implementation Recommendations

### Directory Structure
```
deploy/
├── helm/
│   └── orchestra/          # Helm chart (see Section 1)
├── terraform/
│   ├── modules/
│   │   ├── eks/            # AWS EKS config
│   │   └── gke/            # GCP GKE config
│   ├── environments/
│   │   ├── dev/
│   │   └── prod/
│   ├── main.tf
│   ├── variables.tf
│   └── outputs.tf
├── nats-values.yaml        # NATS Helm overrides
└── otel-collector.yaml     # OTel Collector config (see wave1-otel-collector.md)
```

### Cloud Target (Gap 5 — RESOLVED)
**Decision: GKE primary, EKS secondary.**
- GKE has native gVisor support (one field vs ~100 lines DaemonSet on EKS)
- Helm chart stays cloud-agnostic via `runtimeClassName` value override
- GKE is default in `deploy/terraform/environments/`; EKS config provided for multi-cloud
- Kata deferred to Phase 5 (GKE doesn't support it; gVisor sufficient for I/O-bound agents)

### EKS vs GKE Decision Matrix

| Factor | EKS | GKE |
|--------|-----|-----|
| gVisor | DaemonSet (manual) | **Native** (one field) |
| Kata | Custom AMI | Not available |
| KEDA | Helm install | Helm install |
| Workload Identity | IRSA | Native WI |
| Cost (estimate) | ~$73/mo control plane | ~$73/mo control plane |
| Terraform maturity | Very mature module | Very mature module |
| **Verdict** | Secondary | **Primary** |

### Validation Checklist
1. `helm template` renders without errors
2. `helm lint` passes
3. `helm install --dry-run` succeeds against cluster
4. KEDA ScaledObject creates valid HPA
5. RuntimeClass exists before pods reference it
6. gVisor DaemonSet running on target nodes (EKS)
7. Probes respond correctly during startup/drain
8. PDB prevents full outage during node upgrades
9. NATS monitoring endpoint accessible from KEDA
10. Terraform plan shows expected resources

### Common Pitfalls

| Pitfall | Mitigation |
|---------|------------|
| gVisor not installed before deploy | Node selector + init container check |
| KEDA can't reach NATS monitoring | Ensure port 8222 exposed, network policy allows |
| Scale-down too aggressive | 300s stabilization window + 25% max |
| Readiness probe too fast | Startup probe guards initial load |
| PDB blocks node drain | Set `minAvailable` not `maxUnavailable` |
| Helm dependency version drift | Pin minor versions in Chart.yaml |
| Terraform state conflicts | Remote state in S3/GCS with locking |
| Secret rotation breaks pods | External Secrets Operator + auto-restart |

---

## 8. Cross-References

- **NATS cluster config:** See `wave1-nats-jetstream.md` for JetStream stream/consumer setup
- **OTel Collector deploy:** See `wave1-otel-collector.md` for DaemonSet/Deployment YAML
- **gVisor details:** See `wave1-sandboxing-wasm.md` for syscall filtering and performance
- **Existing research:** `01-infrastructure-scalability.md`, `13-iac-drift-management.md`, `15-unified-devops-strategy.md`
