#!/bin/bash
set -euo pipefail
project_dir="$(cd "$(dirname "$0")" && pwd)"
cd "$project_dir"
if command -v dotnet >/dev/null 2>&1; then
  task_dotnet_bin="$(command -v dotnet)"
elif [[ -f "$project_dir/.local-runtime" ]]; then
  {
    IFS= read -r task_dotnet_dir
    IFS= read -r task_package_dir
    IFS= read -r task_cli_dir
  } < "$project_dir/.local-runtime"
  export DOTNET_ROOT="$task_dotnet_dir"
  export NUGET_PACKAGES="$task_package_dir"
  export DOTNET_CLI_HOME="$task_cli_dir"
  task_dotnet_bin="$task_dotnet_dir/dotnet"
else
  echo '.NET 8 SDK bulunamadı. README.md dosyasındaki kurulum adımlarını izleyin.'
  exit 1
fi
if [[ ! -x "$task_dotnet_bin" ]]; then
  echo 'Yerel .NET SDK taşınmış veya silinmiş. .NET 8 SDK kurup tekrar çalıştırın.'
  exit 1
fi
echo 'Power BI → SSAS Converter: http://localhost:5200'
echo 'Durdurmak için Ctrl+C kullanın. Port kullanımda ise açık converter oturumunu kapatın.'
exec "$task_dotnet_bin" run --project src/PbitToSsasConverter.Web -c Release --no-launch-profile --urls http://localhost:5200
