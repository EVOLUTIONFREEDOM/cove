param(
  [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"
$tools = Join-Path $Root "tools"
$jdkZip = Join-Path $tools "jdk17.zip"
$sdkZip = Join-Path $tools "cmdline-tools.zip"
$sdkRoot = Join-Path $tools "android-sdk"

if (-not (Test-Path $jdkZip)) { throw "Missing $jdkZip — download JDK 17 zip first." }
if (-not (Test-Path $sdkZip)) { throw "Missing $sdkZip — download Android cmdline-tools zip first." }

$jdkDir = Get-ChildItem $tools -Directory | Where-Object { $_.Name -like "jdk-*" -or $_.Name -like "microsoft-jdk*" } | Select-Object -First 1
if (-not $jdkDir) {
  Expand-Archive $jdkZip -DestinationPath $tools -Force
  $jdkDir = Get-ChildItem $tools -Directory | Where-Object { $_.Name -like "jdk*" -or $_.Name -like "*jdk*" } | Select-Object -First 1
}

$cmdLatest = Join-Path $sdkRoot "cmdline-tools\latest"
if (-not (Test-Path (Join-Path $cmdLatest "bin\sdkmanager.bat"))) {
  $tmp = Join-Path $tools "cmdline-tmp"
  if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
  Expand-Archive $sdkZip -DestinationPath $tmp -Force
  New-Item -ItemType Directory -Force -Path $cmdLatest | Out-Null
  $inner = Get-ChildItem $tmp -Directory | Select-Object -First 1
  Copy-Item (Join-Path $inner.FullName "*") $cmdLatest -Recurse -Force
}

$env:JAVA_HOME = $jdkDir.FullName
$env:ANDROID_HOME = $sdkRoot
$sdkmanager = Join-Path $cmdLatest "bin\sdkmanager.bat"

"y","y","y","y","y","y","y" | & $sdkmanager --sdk_root=$sdkRoot --licenses
& $sdkmanager --sdk_root=$sdkRoot "platform-tools" "platforms;android-36" "build-tools;36.0.0"

Write-Output "JAVA_HOME=$env:JAVA_HOME"
Write-Output "ANDROID_HOME=$env:ANDROID_HOME"
