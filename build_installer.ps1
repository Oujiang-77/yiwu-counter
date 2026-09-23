$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw '缺少 Python 虚拟环境' }
$version = (& $python -c 'from storage import VERSION; print(VERSION)').Trim()
if ($LASTEXITCODE -ne 0 -or $version -notmatch '^\d+\.\d+\.\d+$') { throw '程序版本号无效' }
$bundle = Join-Path $PSScriptRoot 'dist/档口开单系统/档口开单系统.exe'
if (-not (Test-Path -LiteralPath $bundle)) { throw '请先运行 build.ps1 构建程序目录' }
$compiler = Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6/ISCC.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw '缺少 Inno Setup 6 的 ISCC.exe' }
& $compiler "/DMyAppVersion=$version" 'installer.iss'
if ($LASTEXITCODE -ne 0) { throw '安装程序构建失败' }
$installer = Join-Path (Split-Path $PSScriptRoot -Parent) "outputs/HuoYouShu-Setup-$version-Windows-x64.exe"
if (-not (Test-Path -LiteralPath $installer)) { throw '安装程序输出文件不存在' }
$digest = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
[System.IO.File]::WriteAllText("$installer.sha256.txt", "$digest  $(Split-Path $installer -Leaf)`n", [System.Text.UTF8Encoding]::new($false))
Write-Output "Installer: $installer"
Write-Output "SHA256: $digest"
