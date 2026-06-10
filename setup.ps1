# GFP 蛋白质设计项目 — 环境激活脚本
# 用法: . .\setup.ps1    (PowerShell 中 dot-source 运行)

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Get-Item $ProjectRoot).FullName

# 激活 Conda 环境
conda activate gfp_design 2>$null
if ($LASTEXITCODE -eq 0 -or $?) {
    Write-Host "[OK] Conda 环境 'gfp_design' 已激活" -ForegroundColor Green
} else {
    Write-Host "[WARN] 无法激活 conda，请先运行 conda init powershell" -ForegroundColor Yellow
}

# 所有缓存/模型存入 D 盘 (不写 C 盘)
$env:TORCH_HOME    = Join-Path $ProjectRoot "cache\torch"
$env:HF_HOME       = Join-Path $ProjectRoot "cache\huggingface"
$env:PIP_CACHE_DIR = Join-Path $ProjectRoot "cache\pip"

Write-Host "[OK] TORCH_HOME    = $env:TORCH_HOME"    -ForegroundColor Green
Write-Host "[OK] HF_HOME       = $env:HF_HOME"       -ForegroundColor Green
Write-Host "[OK] PIP_CACHE_DIR = $env:PIP_CACHE_DIR" -ForegroundColor Green
Write-Host "[OK] 环境就绪，可以运行 Pipeline"         -ForegroundColor Cyan
