$ErrorActionPreference = "Stop"

$BundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (Test-Path $BundledPython) {
  $Python = $BundledPython
} else {
  $PythonCommand = Get-Command python -ErrorAction SilentlyContinue
  if (-not $PythonCommand) {
    throw "Python was not found. Install Python 3.11+ or run inside the Codex workspace runtime."
  }
  $Python = $PythonCommand.Source
}

Set-Location $PSScriptRoot
& $Python -m app.server --host 127.0.0.1 --port 8080

