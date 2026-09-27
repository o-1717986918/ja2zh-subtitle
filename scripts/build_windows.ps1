param(
    [string]$Version = "1.0.0",
    [switch]$CpuOnly,
    [switch]$SkipPortableBuild,
    [switch]$SkipInstaller,
    [switch]$SkipWebView2Download
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$Python = "D:\miniconda\envs\ja2zh-subtitle\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = (Get-Command python -ErrorAction Stop).Source
}

$SnapshotRoot = Join-Path $ProjectRoot "models\whisper\models--Systran--faster-whisper-medium\snapshots"
$ModelDir = Get-ChildItem -LiteralPath $SnapshotRoot -Directory |
    Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName "model.bin") } |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1 -ExpandProperty FullName
if (-not $ModelDir) {
    throw "未找到 Whisper-medium 本地模型，请先运行 scripts\download_models.py --preset balanced。"
}

function Find-MediaBinary([string]$Name) {
    $environmentName = "JA2ZH_" + $Name.ToUpperInvariant()
    $configured = [Environment]::GetEnvironmentVariable($environmentName)
    if ($configured -and (Test-Path -LiteralPath $configured)) {
        return (Resolve-Path -LiteralPath $configured).Path
    }
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $pattern = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages\Gyan.FFmpeg_*\ffmpeg-*\bin\$Name.exe"
    $candidate = Get-ChildItem -Path $pattern -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1 -ExpandProperty FullName
    if ($candidate) { return $candidate }
    throw "找不到 $Name.exe，构建机需要可用的 FFmpeg。"
}

$Ffmpeg = Find-MediaBinary "ffmpeg"
$Ffprobe = Find-MediaBinary "ffprobe"

if (-not $SkipPortableBuild) {
    & $Python (Join-Path $ProjectRoot "scripts\make_app_icon.py")
    if ($LASTEXITCODE -ne 0) { throw "应用图标生成失败。" }

    $env:JA2ZH_PROJECT_ROOT = $ProjectRoot
    $env:JA2ZH_WHISPER_MODEL_DIR = $ModelDir
    $env:JA2ZH_FFMPEG_PATH = $Ffmpeg
    $env:JA2ZH_FFPROBE_PATH = $Ffprobe
    $env:JA2ZH_BUILD_WITH_CUDA = if ($CpuOnly) { "0" } else { "1" }

    Push-Location $ProjectRoot
    try {
        & $Python -m PyInstaller --noconfirm --clean --distpath dist --workpath build "packaging\JA2ZH-Subtitle.spec"
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败。" }
    } finally {
        Pop-Location
    }
}

$Portable = Join-Path $ProjectRoot "dist\JA2ZH Subtitle"
if (-not (Test-Path -LiteralPath (Join-Path $Portable "JA2ZH Subtitle.exe"))) {
    throw "便携目录不存在，不能跳过桌面程序构建：$Portable"
}
$PortableSize = (Get-ChildItem -LiteralPath $Portable -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host ("桌面程序构建完成：{0}（{1:N2} GB）" -f $Portable, ($PortableSize / 1GB))

if ($SkipInstaller) { exit 0 }

$VendorDir = Join-Path $ProjectRoot "packaging\vendor"
$WebViewInstaller = Join-Path $VendorDir "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
if (-not (Test-Path -LiteralPath $WebViewInstaller)) {
    if ($SkipWebView2Download) {
        throw "缺少 WebView2 离线安装程序：$WebViewInstaller"
    }
    New-Item -ItemType Directory -Path $VendorDir -Force | Out-Null
    Write-Host "正在下载 Microsoft WebView2 x64 离线运行时…"
    Invoke-WebRequest -Uri "https://go.microsoft.com/fwlink/p/?LinkId=2124703" -OutFile $WebViewInstaller
}

$IsccCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$Iscc = $IsccCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $Iscc) { throw "未找到 Inno Setup 6，请先安装 JRSoftware.InnoSetup。" }

$ReleaseDir = Join-Path $ProjectRoot "release"
New-Item -ItemType Directory -Path $ReleaseDir -Force | Out-Null
$Definitions = @(
    "/DAppVersion=$Version",
    "/DSourceDir=$Portable",
    "/DOutputDir=$ReleaseDir",
    (Join-Path $ProjectRoot "packaging\installer.iss")
)
& $Iscc $Definitions
if ($LASTEXITCODE -ne 0) { throw "安装包编译失败。" }

$Installer = Get-ChildItem -LiteralPath $ReleaseDir -Filter "JA2ZH-Subtitle-Setup-$Version-win-x64.exe" |
    Select-Object -First 1
if (-not $Installer) { throw "安装包输出不存在。" }
Write-Host ("安装包构建完成：{0}（{1:N2} GB）" -f $Installer.FullName, ($Installer.Length / 1GB))
