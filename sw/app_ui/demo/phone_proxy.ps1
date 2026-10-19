<#
Let a phone on the same Wi-Fi reach the demo server that runs inside WSL (NAT mode). Run in an ADMIN PowerShell:

    powershell -ExecutionPolicy Bypass -File phone_proxy.ps1          # open  http://<PC Wi-Fi IP>:8000/mockup/?live=1
    powershell -ExecutionPolicy Bypass -File phone_proxy.ps1 -Remove  # close it again

It forwards Windows port 8000 to the WSL address and opens the firewall for that port for the local subnet only.
The WSL address changes after `wsl --shutdown` or a reboot: run it again then. The page can move the cell and write
corrections without a login, so open it only on a network you trust, and run -Remove when you are done.
#>
param([switch]$Remove, [int]$Port = 8000, [string]$Distro = "Ubuntu-24.04")
$rule = "PolaGrid demo $Port"
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "Run this in an Administrator PowerShell."; exit 1
}
if ($Remove) {
    netsh interface portproxy delete v4tov4 listenport=$Port listenaddress=0.0.0.0 | Out-Null
    Remove-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue
    Write-Host "Removed the port $Port forward and the firewall rule."; exit 0
}
$wsl = ((wsl -d $Distro -- hostname -I) -split "\s+" | Where-Object { $_ -match "^\d+\.\d+\.\d+\.\d+$" } | Select-Object -First 1)
if (-not $wsl) { Write-Error "Could not read the WSL address (is $Distro running?)"; exit 1 }
netsh interface portproxy add v4tov4 listenport=$Port listenaddress=0.0.0.0 connectport=$Port connectaddress=$wsl | Out-Null
Remove-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName $rule -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -RemoteAddress LocalSubnet -Profile Any | Out-Null
$ip = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias "Wi-Fi" -ErrorAction SilentlyContinue | Select-Object -First 1).IPAddress
Write-Host "Forwarding 0.0.0.0:$Port -> ${wsl}:$Port (WSL)."
Write-Host "Phone (same Wi-Fi): http://${ip}:$Port/mockup/?live=1&token=<the token that demo_up.sh printed>"
