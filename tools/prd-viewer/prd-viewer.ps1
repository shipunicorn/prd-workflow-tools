param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Args
)

$ErrorActionPreference = "Stop"
$script = Join-Path $PSScriptRoot "prd_viewer.py"
python $script @Args
