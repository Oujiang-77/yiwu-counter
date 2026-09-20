$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw '请先按 README.md 建立 .venv 并安装 requirements-lock.txt。' }
node build_frontend.cjs
if ($LASTEXITCODE -ne 0) { throw '前端构建失败' }
& $python -m unittest test_local -v
if ($LASTEXITCODE -ne 0) { throw '测试失败，停止打包' }
& $python -m PyInstaller --noconfirm --onedir --windowed --name '档口开单系统' --add-data 'web:web' --collect-all rapidocr_onnxruntime --collect-all onnxruntime --collect-all pyclipper --collect-all shapely --collect-submodules uvicorn app.py
if ($LASTEXITCODE -ne 0) { throw '程序打包失败' }
& $python package_release.py
if ($LASTEXITCODE -ne 0) { throw '压缩包生成失败' }
