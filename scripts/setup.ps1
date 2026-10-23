<#
.SYNOPSIS
  One-time setup of a laptop for the Task Dashboard pipeline (Docker Desktop Kubernetes).

.DESCRIPTION
  Run from anywhere inside a clone of the repository:
      powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1

  What it does:
    1. Checks the prerequisites (Docker, kubectl, Helm, Git, free disk) and the cluster.
    2. Creates the application namespace, the two Secrets and the PostgreSQL pod.
    3. Creates the monitoring namespace and Grafana Secret, then installs Prometheus + Grafana.

  Safe to run again: existing namespaces and Secrets are left unchanged, and Secret values
  are never written into the repository. It does NOT register the GitHub Actions runner;
  that needs a token from the repository owner (see the final instructions it prints).

.PARAMETER AppNamespace
  Namespace for the app and PostgreSQL. Must match APP_NAMESPACE in .github/workflows/ci-cd.yml.

.PARAMETER MonitorNamespace
  Namespace for Prometheus and Grafana.

.PARAMETER SkipMonitoring
  Skip the Prometheus/Grafana install (set up only the app side).
#>
[CmdletBinding()]
param(
    [string]$AppNamespace = 'task-dashboard',
    [string]$MonitorNamespace = 'monitoring',
    [switch]$SkipMonitoring
)

# Native tools (docker, kubectl, helm) write progress to stderr; check exit codes explicitly instead.
$ErrorActionPreference = 'Continue'

$repoRoot = Split-Path -Parent $PSScriptRoot
$k8sDir = Join-Path $repoRoot 'k8s'
$chartVersion = '92.10.1'

function Info([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Warn([string]$Message) { Write-Host "!!  $Message" -ForegroundColor Yellow }
function Ok([string]$Message)   { Write-Host "OK  $Message" -ForegroundColor Green }

function Invoke-Tool {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Exe $($Arguments -join ' ') failed (exit code $LASTEXITCODE)"
    }
}

function Test-Quiet {
    # Runs a command, hides its output, returns $true when it succeeded.
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments 2>&1 | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Read-NewPassword {
    param([string]$Prompt, [int]$MinLength = 8, [switch]$AlphanumericOnly)
    while ($true) {
        $first = Read-PlainText "$Prompt"
        $second = Read-PlainText "$Prompt (again)"
        if ($first -ne $second) { Warn 'The two entries do not match. Try again.'; continue }
        if ($first.Length -lt $MinLength) { Warn "Use at least $MinLength characters."; continue }
        if ($AlphanumericOnly -and ($first -notmatch '^[A-Za-z0-9]+$')) {
            Warn 'Use letters and numbers only (this password is placed in a connection URL).'
            continue
        }
        if ($first -match '[\r\n]') { Warn 'No line breaks allowed.'; continue }
        return $first
    }
}

function Read-PlainText([string]$Prompt) {
    $secure = Read-Host $Prompt -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

function New-RandomKey {
    $bytes = New-Object byte[] 48
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $rng.Dispose()
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Initialize-Namespace([string]$Name) {
    if (Test-Quiet kubectl @('get', 'namespace', $Name)) {
        Ok "Namespace '$Name' already exists"
    } else {
        Invoke-Tool kubectl @('create', 'namespace', $Name)
        Ok "Created namespace '$Name'"
    }
}

function Test-SecretExists([string]$Namespace, [string]$Name) {
    return (Test-Quiet kubectl @('-n', $Namespace, 'get', 'secret', $Name))
}

function New-SecretFromPairs {
    # Uses a temporary env file (not command-line arguments), deleted straight after.
    param([string]$Namespace, [string]$Name, [System.Collections.Specialized.OrderedDictionary]$Pairs)
    $file = Join-Path ([IO.Path]::GetTempPath()) ('k8s-secret-' + [guid]::NewGuid().ToString('N') + '.env')
    try {
        $lines = @()
        foreach ($key in $Pairs.Keys) { $lines += ('{0}={1}' -f $key, $Pairs[$key]) }
        [IO.File]::WriteAllLines($file, [string[]]$lines, (New-Object Text.UTF8Encoding($false)))
        Invoke-Tool kubectl @('-n', $Namespace, 'create', 'secret', 'generic', $Name, "--from-env-file=$file")
        Ok "Created Secret '$Name' in '$Namespace'"
    }
    finally {
        if (Test-Path $file) { Remove-Item $file -Force }
    }
}

try {
    # ------------------------------------------------------------------ prerequisites
    Info 'Checking prerequisites'
    $required = @('docker', 'kubectl', 'git')
    if (-not $SkipMonitoring) { $required += 'helm' }
    $missing = @()
    foreach ($tool in $required) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { $missing += $tool }
    }
    if ($missing.Count -gt 0) {
        throw ("Missing tools: {0}. Install them first (Helm: winget install Helm.Helm), then reopen PowerShell." -f ($missing -join ', '))
    }
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        Warn 'python was not found on PATH. The pipeline runner needs it for the test job.'
    }

    $driveLetter = (Split-Path -Qualifier $repoRoot).TrimEnd(':')
    $freeGb = [math]::Round((Get-PSDrive -Name $driveLetter).Free / 1GB, 1)
    if ($freeGb -lt 15) {
        Warn "Only $freeGb GB free on ${driveLetter}:. Docker images need roughly 15-25 GB. A full disk breaks Docker Desktop."
    } else {
        Ok "$freeGb GB free on ${driveLetter}:"
    }

    if (-not (Test-Quiet docker @('info'))) {
        throw 'The Docker engine is not running. Start Docker Desktop and wait until it is ready.'
    }
    Ok 'Docker engine is running'

    if (-not (Test-Quiet kubectl @('config', 'use-context', 'docker-desktop'))) {
        throw "No 'docker-desktop' kubectl context. In Docker Desktop: Settings -> Kubernetes -> enable, choose Kubeadm."
    }
    $nodes = (& kubectl get nodes --no-headers 2>&1) -join "`n"
    if ($nodes -notmatch '\sReady\s') {
        throw "Kubernetes is not ready yet. 'kubectl get nodes' printed:`n$nodes"
    }
    Ok 'Kubernetes cluster is ready (context: docker-desktop)'

    # ------------------------------------------------------------------ application side
    Info "Setting up the application namespace '$AppNamespace'"
    Initialize-Namespace $AppNamespace

    if (Test-SecretExists $AppNamespace 'postgres-credentials') {
        Ok "Secret 'postgres-credentials' already exists - leaving it unchanged"
    } else {
        Write-Host ''
        Write-Host 'Choose database credentials (used by PostgreSQL and the app).'
        $dbUser = Read-Host 'Database user [taskuser]'
        if (-not $dbUser) { $dbUser = 'taskuser' }
        $dbName = Read-Host 'Database name [taskdb]'
        if (-not $dbName) { $dbName = 'taskdb' }
        $dbPassword = Read-NewPassword 'Database password' -MinLength 8 -AlphanumericOnly
        $pairs = [ordered]@{ POSTGRES_USER = $dbUser; POSTGRES_DB = $dbName; POSTGRES_PASSWORD = $dbPassword }
        New-SecretFromPairs $AppNamespace 'postgres-credentials' $pairs
    }

    if (Test-SecretExists $AppNamespace 'app-secret') {
        Ok "Secret 'app-secret' already exists - leaving it unchanged"
    } else {
        Write-Host ''
        Write-Host 'Choose the password for the demo accounts (Calven, Mahymar, Sothearith).'
        $seedPassword = Read-NewPassword 'Demo login password' -MinLength 8
        $pairs = [ordered]@{ SECRET_KEY = (New-RandomKey); SEED_DEMO_USERS = 'true'; SEED_PASSWORD = $seedPassword }
        New-SecretFromPairs $AppNamespace 'app-secret' $pairs
    }

    Info 'Starting PostgreSQL (the first image download can take a few minutes)'
    Invoke-Tool kubectl @('-n', $AppNamespace, 'apply', '-f', (Join-Path $k8sDir 'postgres.yaml'))
    Invoke-Tool kubectl @('-n', $AppNamespace, 'wait', '--for=condition=Ready', 'pod/postgres', '--timeout=300s')
    Ok 'PostgreSQL is ready'

    # ------------------------------------------------------------------ monitoring
    if ($SkipMonitoring) {
        Warn 'Skipping monitoring (-SkipMonitoring)'
    } else {
        Info "Setting up monitoring in namespace '$MonitorNamespace'"
        Initialize-Namespace $MonitorNamespace

        if (Test-SecretExists $MonitorNamespace 'grafana-admin') {
            Ok "Secret 'grafana-admin' already exists - leaving it unchanged"
        } else {
            Write-Host ''
            Write-Host 'Choose the Grafana admin password (the user name will be "admin").'
            $grafanaPassword = Read-NewPassword 'Grafana admin password' -MinLength 8
            $pairs = [ordered]@{ 'admin-user' = 'admin'; 'admin-password' = $grafanaPassword }
            New-SecretFromPairs $MonitorNamespace 'grafana-admin' $pairs
        }

        Info 'Installing Prometheus and Grafana (several GB of images; this can take 10+ minutes)'
        Invoke-Tool helm @('repo', 'add', 'prometheus-community', 'https://prometheus-community.github.io/helm-charts', '--force-update')
        Invoke-Tool helm @('repo', 'update')
        try {
            # hostRootFsMount=false: Docker Desktop cannot mount the host root as a shared mount,
            # which otherwise leaves the node-exporter pod in CrashLoopBackOff.
            Invoke-Tool helm @(
                'upgrade', '--install', 'monitoring', 'prometheus-community/kube-prometheus-stack',
                '--version', $chartVersion,
                '--namespace', $MonitorNamespace,
                '-f', (Join-Path $k8sDir 'monitoring-values.yaml'),
                '--set', 'prometheus-node-exporter.hostRootFsMount.enabled=false',
                '--wait', '--timeout', '15m'
            )
            Ok 'Monitoring stack installed'
        }
        catch {
            Warn "Helm did not finish cleanly: $($_.Exception.Message)"
            Warn "The pods may still be starting. Check: kubectl -n $MonitorNamespace get pods"
        }
    }

    # ------------------------------------------------------------------ summary
    Write-Host ''
    Info 'Current state'
    & kubectl -n $AppNamespace get pods
    if (-not $SkipMonitoring) { & kubectl -n $MonitorNamespace get pods }

    Write-Host ''
    Write-Host 'Cluster setup is done. Remaining manual steps:' -ForegroundColor Green
    Write-Host '  1. Stop any other runner that has the "docker-desktop" label (another PC), so jobs land here.'
    Write-Host '  2. Register this PC as the runner. The repository owner opens'
    Write-Host '     Settings -> Actions -> Runners -> New self-hosted runner (Windows x64) and gives you the token.'
    Write-Host '     Download and extract it in C:\actions-runner, then run:'
    Write-Host '       .\config.cmd --url <repo URL> --token <TOKEN> --labels docker-desktop'
    Write-Host '       .\run.cmd        (leave this window open; answer N to the service question)'
    Write-Host '  3. Push a new commit to main (not "Re-run": that reuses the run number and the Git tag step fails).'
    Write-Host '  4. Open the app at http://localhost:8000 (published by the LoadBalancer Service once the first'
    Write-Host '     deployment has run; no port-forward needed). For monitoring, one PowerShell window each:'
    if (-not $SkipMonitoring) {
        Write-Host "       kubectl -n $MonitorNamespace port-forward service/monitoring-kube-prometheus-prometheus 9090:9090"
        Write-Host "       kubectl -n $MonitorNamespace port-forward service/monitoring-grafana 3000:80"
    }
}
catch {
    Write-Host ''
    Write-Host "XX  $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
