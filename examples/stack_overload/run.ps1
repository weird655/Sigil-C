Set-Location $PSScriptRoot
python ..\..\sigilc.py real.sigil -o real.c --no-bounds-check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
gcc -std=c99 -O0 -g -fsanitize=address -fno-omit-frame-pointer real.c -o real.exe
if ($LASTEXITCODE -ne 0) {
    Write-Host "ASan is not available in this toolchain; use WSL/Linux/macOS."
    exit 1
}
.\real.exe
