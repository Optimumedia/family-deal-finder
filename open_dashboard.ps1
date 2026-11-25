# Opens the dashboard at http://localhost:8810 (the page needs a local web server to read data.json).
Set-Location $PSScriptRoot
Start-Process "http://localhost:8810"
python -m http.server 8810 -d docs
