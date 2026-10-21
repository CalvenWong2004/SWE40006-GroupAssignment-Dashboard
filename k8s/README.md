# SWE40006 Kubernetes technical handoff

Technical implementation notes and commands only. This is not report or presentation text. Commands below are for PowerShell, run from the folder containing these four files.

## Files and boundaries

| File | Purpose |
| --- | --- |
| dummy-app.yaml | Deployment with two public `traefik/whoami:v1.11.0` replicas and a ClusterIP Service. Responses include the serving Pod hostname. |
| postgres.yaml | One PostgreSQL 17 Pod, a 2 GiB PVC and internal port 5432 Service. Database/user/password come from an externally created Secret. |
| monitoring-values.yaml | Helm overrides for kube-prometheus-stack 92.10.1: Prometheus Operator, Prometheus, Grafana, node-exporter, kube-state-metrics and kubelet/cAdvisor scraping. |

No Namespace objects or namespace overrides are supplied. The integration owner creates/selects namespaces and supplies them at execution time. The dummy workload is independent of FastAPI. No FastAPI image, routes, credentials, database name, migrations or connection-variable names are assumed.

## Prerequisites

- Teammate's working Kubernetes cluster with Linux nodes, working DNS/Service networking and registry access; kubectl configured for that cluster. Docker is not needed to edit these files.
- A default dynamic StorageClass, or an integration-selected class/PV satisfying the PostgreSQL PVC. Check `kubectl get storageclass`. A PVC remaining Pending requires storage investigation, not a database password change.
- Helm 3 and privileges for the monitoring chart's cluster-scoped CRDs, RBAC and node-exporter host access. Check compatibility with the pinned chart (declares Kubernetes >=1.25); review existing operators/releases before installing a second stack. Local cluster security policies may need integration changes.
- Sufficient cluster resources: monitoring requests here only bound Prometheus; Grafana, exporters, operator and cluster components need additional capacity.
- Existing namespaces and two Secrets, described below. Use actual team-agreed database/user values; never commit credential files, generated Secret YAML, decoded Secrets or passwords. Kubernetes Secrets are base64-encoded, not inherently encrypted.

```powershell
$AppNs = Read-Host 'Existing application namespace from integration owner'
$MonitorNs = Read-Host 'Existing monitoring namespace from integration owner'
if (!$AppNs -or !$MonitorNs) { throw 'Both namespace values are required' }
kubectl config current-context
kubectl get namespace $AppNs $MonitorNs
kubectl get nodes
kubectl get storageclass
```

## Supply credentials outside Git

Prefer the team's secret-management mechanism. Alternatively, prepare two temporary UTF-8 env files OUTSIDE the repository using a local editor. Enter actual values privately; do not paste them into shell history. Remove the files securely according to your team's process after creation.

PostgreSQL file contains keys `POSTGRES_USER`, `POSTGRES_DB`, `POSTGRES_PASSWORD`, each as `KEY=value` on a separate line. Grafana file contains `admin-user` and `admin-password` in the same format. No example password is supplied.

```powershell
$PgSecretFile = Read-Host 'Absolute path to private PostgreSQL env file outside repo'
$GrafanaSecretFile = Read-Host 'Absolute path to private Grafana env file outside repo'
kubectl -n $AppNs create secret generic postgres-credentials --from-env-file="$PgSecretFile"
kubectl -n $MonitorNs create secret generic grafana-admin --from-env-file="$GrafanaSecretFile"
```

These creation commands expect absent Secrets. Coordinate existing credentials rather than overwriting them. PostgreSQL initialization variables only initialize an EMPTY data directory; changing the Secret does not rename an existing database or rotate an existing user's database password.

## Validate against teammate's API server, then deploy

```powershell
kubectl -n $AppNs apply --dry-run=server --validate=strict -f dummy-app.yaml -f postgres.yaml
kubectl -n $AppNs apply -f dummy-app.yaml -f postgres.yaml
kubectl -n $AppNs rollout status deployment/dummy-app --timeout=180s
kubectl -n $AppNs wait --for=condition=Ready pod/postgres --timeout=300s
kubectl -n $AppNs get pods,services,pvc
```

Server dry-run checks admission/schema acceptance; it does not pull images, bind storage or prove runtime behavior. For failures inspect `kubectl -n $AppNs describe pod postgres`, `describe pvc postgres-data`, `get events --sort-by=.metadata.creationTimestamp`, and `logs postgres`. PostgreSQL's official image initially uses root to prepare volume ownership; restricted Pod Security or unusual volume permissions may require integration-specific changes.

## Verify two replicas and Service distribution

```powershell
kubectl -n $AppNs get pods -l app=dummy-app -o wide
kubectl -n $AppNs get endpointslices -l kubernetes.io/service-name=dummy-app -o yaml
kubectl -n $AppNs run dummy-lb-check --image=busybox:1.37.0 --restart=Never --command -- sh -c 'set -eu; for i in $(seq 1 40); do wget -T 5 -qO- http://dummy-app/; done'
kubectl -n $AppNs wait --for=jsonpath='{.status.phase}'=Succeeded pod/dummy-lb-check --timeout=180s
kubectl -n $AppNs logs dummy-lb-check
kubectl -n $AppNs delete pod dummy-lb-check
```

Expect two Ready replicas, two ready EndpointSlice addresses and both Pod hostnames in the request output. Each wget makes a new connection. Kubernetes distributes connections, so exact alternation or a 50/50 split is not guaranteed. If only one hostname appears, inspect endpoint readiness and rerun a larger sample. Capture actual output; do not claim success until observed. `kubectl port-forward service/dummy-app 8080:80` is useful for browsing, but forwards to one selected Pod and cannot demonstrate Service load balancing. ClusterIP provides internal balancing; public access/Ingress is an integration decision.

## Verify PostgreSQL, Service authentication and persistence

This test uses a disposable table in the configured database. Confirm that this is a test database before executing the SQL.

```powershell
# Local socket: create a persistent marker (not a network/authentication test).
kubectl -n $AppNs exec postgres -- sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE TABLE IF NOT EXISTS swe40006_persistence_check (id integer PRIMARY KEY, marker text NOT NULL); INSERT INTO swe40006_persistence_check VALUES (1, ''survives-pod-recreation'') ON CONFLICT (id) DO NOTHING;"'
# TCP via Service DNS, with password authentication from the existing Secret env.
kubectl -n $AppNs exec postgres -- sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -w -h postgres -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "SELECT * FROM swe40006_persistence_check;"'
# Delete only the Pod; keep its PVC and reapply the standalone Pod.
kubectl -n $AppNs delete pod postgres --wait=true
kubectl -n $AppNs apply -f postgres.yaml
kubectl -n $AppNs wait --for=condition=Ready pod/postgres --timeout=300s
kubectl -n $AppNs exec postgres -- sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -w -h postgres -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "SELECT * FROM swe40006_persistence_check;"'
```

The marker must still exist after Pod recreation. This tests Service DNS/TCP/password and Pod-replacement persistence, not FastAPI connectivity, backups or node-loss recovery. A standalone Pod restarts failed containers but has no controller to recreate a deleted/lost Pod; reapply it manually. Do not scale this database or share its data directory between servers. PostgreSQL 17 data is mounted under `/var/lib/postgresql/data/pgdata`; do not switch major versions on this PVC without a database migration plan. Image tags are not immutable digests; integration should record/pin tested image digests.

FastAPI in the same namespace can use Service host `postgres` and port `5432`; across namespaces the integration owner supplies its qualified DNS name. They must map the real application's existing configuration and run its actual database/migration tests. The initialization account is a privileged database account; provision a least-privilege application role during integration.

## Render, install and verify monitoring

Do not run `kubectl apply` on monitoring-values.yaml. It is input to Helm. The reference chart version is pinned to avoid silently changing templates; teammates should review chart upgrades and CRD upgrade instructions deliberately.

```powershell
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm show chart prometheus-community/kube-prometheus-stack --version 92.10.1
helm template monitoring prometheus-community/kube-prometheus-stack --version 92.10.1 --namespace $MonitorNs -f monitoring-values.yaml --include-crds > monitoring-rendered.yaml
# Review rendered manifests before installing; don't commit generated credentials.
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack --version 92.10.1 --namespace $MonitorNs -f monitoring-values.yaml --wait --timeout 10m
helm status monitoring -n $MonitorNs
kubectl -n $MonitorNs get pods,services,servicemonitors
kubectl -n $MonitorNs get prometheus
kubectl -n $MonitorNs port-forward service/monitoring-kube-prometheus-prometheus 9090:9090
```

Keep port-forward running. Open http://localhost:9090 and inspect Status > Targets. Verify node-exporter, kube-state-metrics and kubelet/cAdvisor targets are UP, then run these PromQL queries after a few scrape intervals:

```promql
up
100 * (1 - avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])))
100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)
rate(node_disk_read_bytes_total[5m])
rate(node_network_receive_bytes_total{device!="lo"}[5m])
container_memory_working_set_bytes{container!="",container!="POD"}
kube_pod_status_phase{phase="Running"}
```

In another terminal, set `$MonitorNs` again and run:

```powershell
kubectl -n $MonitorNs port-forward service/monitoring-grafana 3000:80
```

Open http://localhost:3000, use the privately supplied Grafana login, and inspect Kubernetes/node dashboards and their Prometheus data source. Service names assume release `monitoring` and no name overrides; confirm with `get services` if integrating differently. Metrics on Docker Desktop/minikube/kind describe Linux cluster nodes/VMs, not necessarily all Windows host activity. Some local/managed control-plane targets (scheduler, controller-manager, etcd, proxy) may be unreachable; document the actual target failures and adapt only the relevant monitors with the integration owner.

Prometheus history and Grafana changes are ephemeral in this demo configuration. Add appropriate persistent storage before relying on retained monitoring history. Alertmanager is disabled; no external notifications are configured. These values do not add FastAPI `/metrics`, HTTP latency metrics or a PostgreSQL exporter. System metrics alone cannot prove the assignment's application latency example or real application/database integration.

## Cleanup and evidence

Keep actual kubectl output, two distinct responder hostnames, persistence query results, monitoring targets and metric screenshots from the teammate's run. Record context, versions, chart version and tested image digests without credentials. These files do not establish completion of the wider CI/CD pipeline or its separate environments.

For dummy cleanup: `kubectl -n $AppNs delete -f dummy-app.yaml`. To stop PostgreSQL while preserving data: delete only `pod/postgres` and `service/postgres`. **Do not run `kubectl delete -f postgres.yaml` unless database data may be destroyed:** that includes the PVC, and the storage reclaim policy can delete the backing volume. `helm uninstall monitoring -n $MonitorNs` removes the monitoring release; chart CRDs may remain and can be shared. Coordinate cluster-scoped cleanup rather than deleting CRDs blindly.

## Validation status on the authoring laptop

Validation performed on 19 October 2026 without Docker or a Kubernetes cluster:

- PyYAML 6.0.3 parsed all three YAML files (six YAML documents).
- jsonschema 4.25.1 validated all five Kubernetes resources against Kubernetes 1.31.0 standalone strict schemas from [kubernetes-json-schema](https://github.com/yannh/kubernetes-json-schema). This is schema validation, not API-server admission validation.
- Static checks passed for two replicas, matching Service selectors, PVC references, external database Secret references and absence of manifest namespaces or Secret objects.
- Helm 3.19.0 was downloaded into the scratch workspace. Helm lint passed for packaged chart 92.10.1 with these values; Helm template with CRDs and Kubernetes version 1.31.0 succeeded using a throwaway render namespace.
- Render inspection confirmed Prometheus retention, node-exporter, kube-state-metrics, kubelet/cAdvisor and the external Grafana Secret reference. PyYAML required treating the chart CRDs' bare equals-sign enum value as a string.

No kubectl executable was found on PATH. API validation, image pulls/startup, probes, Service balancing, storage binding/persistence, SQL commands and metric collection remain UNTESTED. Helm rendering does not run the Operator or prove live discovery. All deployment/test commands above still require execution in the teammate's environment.

## Upstream references

- [whoami image behavior and port flag](https://github.com/traefik/whoami)
- [Kubernetes Services](https://kubernetes.io/docs/concepts/services-networking/service/)
- [Official PostgreSQL image initialization and storage](https://hub.docker.com/_/postgres)
- [Pinned monitoring chart values](https://github.com/prometheus-community/helm-charts/blob/kube-prometheus-stack-92.10.1/charts/kube-prometheus-stack/values.yaml)
- [Monitoring chart installation and upgrades](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack)
