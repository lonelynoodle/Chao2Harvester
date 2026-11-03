param([switch]$Smoke, [string]$OutputDirectory = 'bin', [switch]$SelfContained)
$ErrorActionPreference = 'Stop'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$buildRoot = $PSScriptRoot
$sdk = Join-Path $buildRoot 'tools\dotnet\dotnet.exe'
$python = Join-Path $buildRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = Join-Path $buildRoot 'runtime\python\python.exe'
}
$publishPath = Join-Path $buildRoot $OutputDirectory
if (-not (Test-Path -LiteralPath $sdk)) {
    $sdk = (Get-Command dotnet -ErrorAction Stop).Source
}
if (-not (Test-Path -LiteralPath $python)) { throw '请先创建 .venv 并安装 requirements.lock，或使用含 runtime 的完整发布包。' }
Push-Location -LiteralPath $buildRoot
try {
    & $python -c "import json; from chao2.workflows import TASKS,ORDER; from chao2.configuration import SPECS; from pathlib import Path; Path('frontend/tasks.json').write_text(json.dumps([{'key':k,'name':TASKS[k][0],'description':TASKS[k][1],'settings':SPECS[k]} for k in ORDER],ensure_ascii=False,indent=2),encoding='utf-8')"
    if ($LASTEXITCODE) { throw '任务清单生成失败' }
    & $python -c "import json; from chao2.tool_settings import PUZZLE_SPEC,TOUR_SPEC,ABYSS_SPEC; from chao2.wild_settings import WILD_SPEC; from chao2.merchant_settings import MERCHANT_SPEC; from chao2.trigger_events import TRIGGER_EVENT_SPEC; from pathlib import Path; Path('frontend/tools.json').write_text(json.dumps([PUZZLE_SPEC,TOUR_SPEC,WILD_SPEC,ABYSS_SPEC,MERCHANT_SPEC,TRIGGER_EVENT_SPEC],ensure_ascii=False,indent=2),encoding='utf-8')"
    if ($LASTEXITCODE) { throw '小工具设置生成失败' }
    $runtimeArgs = @()
    if ($SelfContained) { $runtimeArgs = @('-r', 'win-x64', '-p:SelfContained=true') }
    & $sdk restore frontend\Chao2Harvester.csproj --locked-mode @runtimeArgs
    if ($LASTEXITCODE) { throw '前端依赖还原失败' }
    if ($SelfContained) {
        & $sdk publish frontend\Chao2Harvester.csproj -c Release -o $publishPath -r win-x64 --self-contained true --no-restore -p:DebugType=None -p:DebugSymbols=false
    } else {
        & $sdk publish frontend\Chao2Harvester.csproj -c Release -o $publishPath --no-self-contained --no-restore -p:DebugType=None -p:DebugSymbols=false
    }
    if ($LASTEXITCODE) { throw '前端构建失败' }
    if ($Smoke) {
        $smokeResult = Join-Path $buildRoot 'dev\diagnostics\smoke\wpf-smoke.json'
        if (Test-Path -LiteralPath $smokeResult) { Remove-Item -LiteralPath $smokeResult }
        $check = Start-Process -FilePath (Join-Path $publishPath 'Chao2Harvester.exe') -ArgumentList '--smoke' -WindowStyle Hidden -PassThru
        if (-not $check.WaitForExit(60000)) { throw '前端离线检查超时' }
        if (-not (Test-Path -LiteralPath $smokeResult)) { throw '前端未产生检查结果，请先关闭其他超二收菜窗口' }
        $result = Get-Content -LiteralPath $smokeResult -Raw | ConvertFrom-Json
        if ($result.status -ne 'passed') { throw $result.reason }
        Get-Content -LiteralPath $smokeResult
    }
} finally { Pop-Location }
