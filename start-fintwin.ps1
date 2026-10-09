$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$backend = Join-Path $root 'backend'
$python = $null
$venvPython = Join-Path $backend '.venv\Scripts\python.exe'
if (Test-Path $venvPython) { $python = $venvPython }
if (-not $python) {
  $bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
  if (Test-Path $bundledPython) { $python = $bundledPython }
}
if (-not $python) { $cmd = Get-Command python -ErrorAction SilentlyContinue; if ($cmd -and $cmd.Source -notmatch 'WindowsApps') { $python = $cmd.Source } }
if (-not $python) { throw 'Install Python 3.11 or newer, then run this launcher again.' }
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodeCmd) { throw 'Install Node.js 20 or newer, then run this launcher again.' }
$sitePackages = Join-Path $backend '.site-packages'
$env:PYTHONPATH = "$sitePackages;$backend"
$importCheck = & $python -c "import fastapi, sqlalchemy, pandas, sklearn" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host 'Installing FinTwin API dependencies for first launch…'
  New-Item -ItemType Directory -Force -Path $sitePackages | Out-Null
  & $python -m pip install --disable-pip-version-check --target $sitePackages -r (Join-Path $backend 'requirements.txt')
  if ($LASTEXITCODE -ne 0) { throw 'Could not install API dependencies. Check your internet connection and Python installation.' }
}
$env:PYTHONPATH = "$sitePackages;$backend"
$envFile = Join-Path $backend '.env'
if (-not (Test-Path $envFile)) {
  $secret = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(48))
  @("DATABASE_URL=sqlite:///./fintwin.db", "JWT_SECRET=$secret", "ACCESS_TOKEN_MINUTES=30", "UPLOAD_DIR=./uploads", "MODEL_DIR=./artifacts", "FRONTEND_ORIGINS=http://localhost:5173") | Set-Content -Encoding ascii $envFile
}
$apiReady = $false
try { $null = Invoke-RestMethod 'http://127.0.0.1:8000/health' -TimeoutSec 2; $apiReady = $true } catch {}
if (-not $apiReady) {
  Write-Host 'Preparing your private local database…'
  Push-Location $backend
  try { & $python -m alembic upgrade head; if ($LASTEXITCODE -ne 0) { throw 'Database setup failed. Check the backend configuration.' } } finally { Pop-Location }
  $logDir = Join-Path $backend 'logs'
  New-Item -ItemType Directory -Force -Path $logDir | Out-Null
  Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000') -WorkingDirectory $backend -RedirectStandardOutput (Join-Path $logDir 'api.log') -RedirectStandardError (Join-Path $logDir 'api-error.log') -WindowStyle Hidden
  for ($i=0; $i -lt 40; $i++) { Start-Sleep -Milliseconds 500; try { $null = Invoke-RestMethod 'http://127.0.0.1:8000/health' -TimeoutSec 2; $apiReady = $true; break } catch {} }
  if (-not $apiReady) { throw 'The API did not start. Check Python dependencies and port 8000.' }
}
$webReady = $false
try { $null = Invoke-WebRequest 'http://127.0.0.1:5173/' -TimeoutSec 2; $webReady = $true } catch {}
if (-not $webReady) {
  New-Item -ItemType Directory -Force -Path (Join-Path $root 'logs') | Out-Null
  Start-Process -FilePath $nodeCmd.Source -ArgumentList @('server.mjs') -WorkingDirectory $root -RedirectStandardOutput (Join-Path $root 'logs\web.log') -RedirectStandardError (Join-Path $root 'logs\web-error.log') -WindowStyle Hidden
  for ($i=0; $i -lt 20; $i++) { Start-Sleep -Milliseconds 300; try { $null = Invoke-WebRequest 'http://127.0.0.1:5173/' -TimeoutSec 2; $webReady = $true; break } catch {} }
  if (-not $webReady) { throw 'The FinTwin website did not start. Check port 5173.' }
}
Start-Process 'http://localhost:5173/'
Write-Host 'FinTwin AI is ready at http://localhost:5173/'
