# 将工控机主机名映射到 IP（需管理员 PowerShell 运行一次）
$hosts = "$env:windir\System32\drivers\etc\hosts"
$line = "192.168.1.56 chepai-rk3588"
if (Select-String -Path $hosts -Pattern "chepai-rk3588" -Quiet) {
  Write-Host "hosts 已包含 chepai-rk3588"
} else {
  Add-Content -Path $hosts -Value $line
  Write-Host "已添加: $line"
}
