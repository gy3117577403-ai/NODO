<#
NODO 开发环境脚本。只操作 Compose 项目 nodo-dev，不碰预览环境和其他项目。

用法（在仓库根目录）：
  powershell -ExecutionPolicy Bypass -File scripts\nodo.ps1 <命令> [参数]

命令：
  init            生成 .env 和 config/odoo.conf（已存在则不覆盖）
  build           构建 NODO 镜像
  up              启动开发环境
  stop            停止开发环境（保留数据）
  logs            查看 Odoo 日志（最近 200 行）
  init-db         创建开发库 nodo_dev 并安装标准应用（库已存在则拒绝）
  check           只读核对开发库状态
  install <模块>  在 nodo_dev 中安装模块
  update <模块>   在 nodo_dev 中升级模块
  seed-users      为每个角色各建一个测试用户（只建缺少的），密码写入本地账号文件
  draw-start [refresh] 启动本机 CAD 计算进程；refresh 在空闲时重载工作进程
  seed-draw       在开发库准备 AE 单门、双门基础柜
  seed-draw-catalog 在开发库登记待核对附件及预览
  seed-supply-pilot  准备采购协作验收账号和采购资料
  init-staff-pilot  创建独立人员试点库 nodo_staff_pilot
  check-staff-pilot 核对试点库的人员来源、档案关系和界面版本
  update-staff-pilot 在人员试点库升级员工模块
  preview-staff-pilot <HTML>  核对架构图导入结果，回滚本次写入
  import-staff-pilot <HTML>  将架构图档案写入人员试点库
  test <模块>     在一次性测试库中安装模块并运行测试，结束后删除该测试库
  test nodo_draw -DrawBrowser  附加独立夹具公司的附件库浏览器和出图验收
  test nodo_draw -DrawLayout <before|after>  附加附件库界面截图与选型验收
  shell           进入 nodo_dev 的 odoo shell
#>
param(
    [Parameter(Position = 0)][string]$Command = 'help',
    [Parameter(Position = 1)][string]$Module,
    [switch]$DrawBrowser,
    [ValidateSet('before', 'after')][string]$DrawLayout
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$ComposeFile = Join-Path $Root 'docker-compose.yml'
$EnvFile = Join-Path $Root '.env'
$ConfFile = Join-Path $Root 'config\odoo.conf'
$ConfTemplate = Join-Path $Root 'config\odoo.conf.example'
$AccountsFile = Join-Path $Root 'config\dev-accounts.local.md'
$DevDb = 'nodo_dev'
$StaffPilotDb = 'nodo_staff_pilot'
$StaffPilotAccountsFile = Join-Path $Root 'config\staff-pilot-accounts.local.md'
$OdooConf = '/etc/odoo/odoo.conf'
$StandardApps = @('contacts', 'crm', 'sale_management', 'purchase', 'stock', 'mrp', 'mail')
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = $Utf8NoBom

function New-Secret([int]$Bytes = 24) {
    $buf = New-Object byte[] $Bytes
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($buf)
    $rng.Dispose()
    return -join ($buf | ForEach-Object { $_.ToString('x2') })
}

function Invoke-Compose {
    & docker compose --project-directory $Root -f $ComposeFile @args
    if ($LASTEXITCODE -ne 0) { throw "docker compose $($args -join ' ') 失败（退出码 $LASTEXITCODE）" }
}

function Assert-Initialized {
    if (-not (Test-Path -LiteralPath $EnvFile) -or -not (Test-Path -LiteralPath $ConfFile)) {
        throw '还没有生成 .env 或 config/odoo.conf，请先运行 init'
    }
}

function Test-DbExists([string]$Name) {
    $out = & docker compose --project-directory $Root -f $ComposeFile exec -T db psql -U odoo -d postgres -tAc "select 1 from pg_database where datname = '$Name'"
    if ($LASTEXITCODE -ne 0) { throw '无法查询数据库列表' }
    return (($out | Out-String).Trim() -eq '1')
}

function Assert-ModuleName([string]$Name) {
    if (-not $Name -or $Name -notmatch '^[a-z][a-z0-9_]*$') { throw "请提供模块技术名称，例如 nodo_base（收到：'$Name'）" }
}

function Invoke-OdooRun([string[]]$OdooArgs, [hashtable]$EnvVars = @{}, [string[]]$ContainerArgs = @()) {
    $envArgs = @()
    foreach ($k in $EnvVars.Keys) { $envArgs += @('-e', $k) }
    $old = @{}
    try {
        foreach ($k in $EnvVars.Keys) { $old[$k] = [Environment]::GetEnvironmentVariable($k); [Environment]::SetEnvironmentVariable($k, $EnvVars[$k]) }
        Invoke-Compose run --rm --no-deps @envArgs @ContainerArgs odoo @OdooArgs
    }
    finally {
        foreach ($k in $EnvVars.Keys) { [Environment]::SetEnvironmentVariable($k, $old[$k]) }
    }
}

function Invoke-OdooShellScript(
    [string]$ScriptName, [hashtable]$EnvVars = @{}, [string]$Database = $DevDb, [string[]]$ContainerArgs = @()
) {
    Invoke-OdooRun -EnvVars $EnvVars -ContainerArgs $ContainerArgs -OdooArgs @(
        'sh', '-c', "odoo shell -c $OdooConf -d $Database --log-level=warn < /mnt/nodo-scripts/$ScriptName"
    )
}

function Assert-StaffPilotExists {
    Assert-Initialized
    if (-not (Test-DbExists $StaffPilotDb)) { throw '请先运行 init-staff-pilot 准备独立试点库' }
}

function Invoke-ModuleUpgrade([string]$Database, [string]$Name) {
    Assert-ModuleName $Name
    Assert-Initialized
    Invoke-Compose stop odoo
    try {
        Invoke-Compose run --rm --no-deps odoo odoo module upgrade -c $OdooConf -d $Database $Name
    }
    finally {
        Invoke-Compose up -d --wait --wait-timeout 120 odoo
    }
}

function Invoke-StaffPilotRoster([string]$Path, [bool]$Commit) {
    Assert-Initialized
    if (-not $Path) { throw '请提供组织架构图 HTML 文件的路径' }
    $sourceFile = Get-Item -LiteralPath $Path
    if ($sourceFile.PSIsContainer -or $sourceFile.Extension -ne '.html') { throw '请选择架构图 HTML 文件' }
    if (-not (Test-DbExists $StaffPilotDb)) { throw '请先运行 init-staff-pilot 准备独立试点库' }
    $commitMode = if ($Commit) { '1' } else { '0' }
    Invoke-OdooShellScript 'import_staff_pilot.py' @{ NODO_STAFF_PILOT_COMMIT = $commitMode } $StaffPilotDb @(
        '--volume', "$($sourceFile.FullName):/mnt/nodo-roster.html:ro"
    )
}

switch ($Command) {
    'init' {
        if (Test-Path -LiteralPath $EnvFile) {
            Write-Host '.env 已存在，不覆盖'
        }
        else {
            $dbPassword = New-Secret
            $envText = "NODO_DB_PASSWORD=$dbPassword`nNODO_HTTP_PORT=8079`n"
            [IO.File]::WriteAllText($EnvFile, $envText, $Utf8NoBom)
            Write-Host '已生成 .env'
        }
        if (Test-Path -LiteralPath $ConfFile) {
            Write-Host 'config/odoo.conf 已存在，不覆盖'
        }
        else {
            $dbPassword = ((Get-Content -LiteralPath $EnvFile) | Where-Object { $_ -like 'NODO_DB_PASSWORD=*' }) -replace '^NODO_DB_PASSWORD=', ''
            if (-not $dbPassword) { throw '.env 里没有 NODO_DB_PASSWORD' }
            $conf = [IO.File]::ReadAllText($ConfTemplate, $Utf8NoBom)
            $conf = $conf.Replace('__MASTER_PASSWORD__', (New-Secret)).Replace('__DB_PASSWORD__', $dbPassword)
            [IO.File]::WriteAllText($ConfFile, $conf, $Utf8NoBom)
            Write-Host '已生成 config/odoo.conf'
        }
    }
    'build' { Assert-Initialized; Invoke-Compose build odoo }
    'up' {
        Assert-Initialized
        Invoke-Compose up -d --wait --wait-timeout 120
        $port = ((Get-Content -LiteralPath $EnvFile) | Where-Object { $_ -like 'NODO_HTTP_PORT=*' }) -replace '^NODO_HTTP_PORT=', ''
        Write-Host "NODO 开发环境已启动：http://127.0.0.1:$port"
    }
    'stop' { Invoke-Compose stop }
    'logs' { Invoke-Compose logs --tail 200 odoo }
    'init-db' {
        Assert-Initialized
        Invoke-Compose up -d --wait db
        if (Test-DbExists $DevDb) { throw "数据库 $DevDb 已存在。本命令不会覆盖或删除它。" }
        Invoke-Compose stop odoo
        Write-Host "创建 $DevDb（简体中文，国家中国，不加载演示数据）..."
        Invoke-Compose run --rm --no-deps odoo odoo db -c $OdooConf init $DevDb --language zh_CN --country CN --username admin@nodo.test
        $adminPassword = 'Nodo-' + (New-Secret 12)
        Write-Host '设置公司、语言、时区和管理员密码...'
        Invoke-OdooShellScript 'setup_dev_db.py' @{ NODO_ADMIN_PASSWORD = $adminPassword }
        $accounts = @"
# NODO 开发环境测试账号（本地文件，已被 git 忽略，不要提交或外发）

生成时间：$(Get-Date -Format 'yyyy-MM-dd HH:mm')

| 用途 | 数据库 | 账号 | 密码 |
|---|---|---|---|
| 管理员 | $DevDb | admin@nodo.test | $adminPassword |

"@
        [IO.File]::WriteAllText($AccountsFile, $accounts, $Utf8NoBom)
        Write-Host '管理员账号已写入 config/dev-accounts.local.md'
        Write-Host "安装标准应用：$($StandardApps -join ', ') ..."
        Invoke-Compose run --rm --no-deps odoo odoo module install -c $OdooConf -d $DevDb @StandardApps
        Invoke-Compose up -d --wait --wait-timeout 120 odoo
        Write-Host "开发库 $DevDb 已就绪"
    }
    'check' { Assert-Initialized; Invoke-OdooShellScript 'check_dev_db.py' }
    'install' {
        Assert-ModuleName $Module
        Assert-Initialized
        Invoke-Compose stop odoo
        Invoke-Compose run --rm --no-deps odoo odoo module install -c $OdooConf -d $DevDb $Module
        Invoke-Compose up -d --wait --wait-timeout 120 odoo
    }
    'draw-start' {
        $worker = Join-Path $Root 'scripts\draw\worker.py'
        $cadRoot = Join-Path $Root '.nodo-draw'
        if (-not (Test-Path -LiteralPath (Join-Path $cadRoot 'engine-manifest.json'))) {
            throw '先用 scripts/draw/prepare.py 准备本机私有工程资源'
        }
        $heartbeat = Join-Path $cadRoot 'exchange\worker.json'
        $workerArg = '"' + $worker + '"'
        $running = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object { $_.CommandLine -and $_.CommandLine.EndsWith($workerArg, [StringComparison]::OrdinalIgnoreCase) })
        if ($Module -eq 'refresh' -and $running.Count) {
            $pending = Get-ChildItem -LiteralPath (Join-Path $cadRoot 'exchange') -Directory | Where-Object {
                $request = Join-Path $_.FullName 'request.json'
                $stateFile = Join-Path $_.FullName 'status.json'
                (Test-Path -LiteralPath $request) -and ((-not (Test-Path -LiteralPath $stateFile)) -or
                    ((Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json).state -notin @('done','failed')))
            }
            if ($pending) { throw '仍有 CAD 任务在排队或计算，请在队列空闲后重载。' }
            $running | ForEach-Object { Stop-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
            $running | ForEach-Object { Wait-Process -Id $_.ProcessId -ErrorAction SilentlyContinue }
            $running = @()
        }
        if ($running -and (Test-Path -LiteralPath $heartbeat) -and ((Get-Date).ToUniversalTime() - (Get-Item -LiteralPath $heartbeat).LastWriteTimeUtc).TotalSeconds -lt 20) {
            Write-Host 'CAD 服务已运行'
            break
        }
        $python = (Get-Command python -CommandType Application | Select-Object -First 1).Source
        Start-Process -FilePath $python -ArgumentList @('-u', ('"' + $worker + '"')) -WorkingDirectory $Root -WindowStyle Hidden -RedirectStandardError (Join-Path $cadRoot 'worker-error.log') -RedirectStandardOutput (Join-Path $cadRoot 'worker.log')
        Write-Host '已请求启动 CAD 服务'
    }
    'seed-draw' { Assert-Initialized; Invoke-OdooShellScript 'seed_draw_boms.py' }
    'seed-draw-catalog' { Assert-Initialized; Invoke-OdooShellScript 'seed_draw_catalog.py' }
    'seed-users' {
        Assert-Initialized
        $out = Invoke-OdooShellScript 'seed_role_users.py'
        $created = @($out | Where-Object { $_ -like 'NODO_USER_CREATED *' })
        $out | Where-Object { $_ -like 'NODO_USER_EXISTS *' } | ForEach-Object { Write-Host ('已存在，未改动：' + ($_ -split ' ')[1]) }
        if ($created.Count -gt 0) {
            if (-not (Test-Path -LiteralPath $AccountsFile)) { throw '找不到 config/dev-accounts.local.md，请先运行 init-db' }
            $rows = $created | ForEach-Object {
                $p = $_ -split ' '
                "| 角色：$($p[1]) | $DevDb | $($p[2]) | $($p[3]) |"
            }
            [IO.File]::AppendAllText($AccountsFile, (($rows -join "`n") + "`n"), $Utf8NoBom)
            $created | ForEach-Object { Write-Host ('已创建：' + ($_ -split ' ')[2]) }
            Write-Host '密码已写入 config/dev-accounts.local.md'
        }
    }
    'seed-supply-pilot' {
        Assert-Initialized
        if (-not (Test-Path -LiteralPath $AccountsFile)) { throw '找不到 config/dev-accounts.local.md，请先运行 init-db' }
        $pilotRoles = @('assistant', 'engineer', 'buyer', 'manager')
        $pilotPasswords = @{}
        foreach ($role in $pilotRoles) {
            $pilotPasswords["NODO_SUPPLY_$($role.ToUpperInvariant())_PASSWORD"] = 'Nodo-' + (New-Secret 12)
        }
        $out = Invoke-OdooShellScript 'seed_supply_pilot.py' $pilotPasswords
        foreach ($line in $out) {
            if ($line -like 'NODO_SUPPLY_USER_CREATED *') {
                $parts = $line -split ' ', 4
                $passwordKey = "NODO_SUPPLY_$($parts[1].ToUpperInvariant())_PASSWORD"
                $row = "| 采购协作：$($parts[3]) | $DevDb | $($parts[2]) | $($pilotPasswords[$passwordKey]) |"
                [IO.File]::AppendAllText($AccountsFile, "$row`n", $Utf8NoBom)
                Write-Host ('已创建：' + $parts[2])
            }
            else { Write-Host $line }
        }
        Write-Host '采购协作账号存放在 config/dev-accounts.local.md'
    }
    'init-staff-pilot' {
        Assert-Initialized
        if ((Test-DbExists $StaffPilotDb) -or (Test-Path -LiteralPath $StaffPilotAccountsFile)) {
            throw '人员试点库或本地凭据文件已存在，请先核对已有状态'
        }
        $staffPilotPassword = 'Nodo-' + (New-Secret 18)
        $initCommand = 'odoo db -c {0} init {1} --language zh_CN --country CN --username admin@nodo.test --password "$NODO_ADMIN_PASSWORD"' -f $OdooConf, $StaffPilotDb
        Invoke-OdooRun @('sh', '-c', $initCommand) @{ NODO_ADMIN_PASSWORD = $staffPilotPassword }
        $staffPilotAccounts = @"
# NODO 人员试点库账号

| 用途 | 数据库 | 账号 | 密码 |
|---|---|---|---|
| 管理员 | $StaffPilotDb | admin@nodo.test | $staffPilotPassword |

"@
        [IO.File]::WriteAllText($StaffPilotAccountsFile, $staffPilotAccounts, $Utf8NoBom)
        Invoke-OdooShellScript 'setup_dev_db.py' @{ NODO_ADMIN_PASSWORD = $staffPilotPassword } $StaffPilotDb
        Invoke-Compose run --rm --no-deps odoo odoo module install -c $OdooConf -d $StaffPilotDb nodo_staff_import nodo_supply
        Write-Host '人员试点库已就绪，凭据写入 config/staff-pilot-accounts.local.md'
    }
    'check-staff-pilot' {
        Assert-StaffPilotExists
        Invoke-OdooShellScript 'check_staff_pilot.py' @{} $StaffPilotDb
    }
    'update-staff-pilot' {
        Assert-StaffPilotExists
        Invoke-ModuleUpgrade $StaffPilotDb 'nodo_staff_import'
    }
    'preview-staff-pilot' { Invoke-StaffPilotRoster $Module $false }
    'import-staff-pilot' { Invoke-StaffPilotRoster $Module $true }
    'update' {
        Invoke-ModuleUpgrade $DevDb $Module
    }
    'test' {
        Assert-ModuleName $Module
        Assert-Initialized
        if (($DrawBrowser -or $DrawLayout) -and $Module -ne 'nodo_draw') { throw '附件库浏览器验收仅适用于 nodo_draw。' }
        Invoke-Compose up -d --wait db
        $testDb = 'nodo_test_' + (Get-Date -Format 'yyyyMMddHHmmss')
        Write-Host "在一次性测试库 $testDb 中测试 $Module ..."
        $code = 0
        try {
            & docker compose --project-directory $Root -f $ComposeFile run --rm --no-deps odoo odoo db -c $OdooConf init $testDb --language zh_CN --country CN
            if ($LASTEXITCODE -ne 0) { throw "创建测试库 $testDb 失败" }
            & docker compose --project-directory $Root -f $ComposeFile run --rm --no-deps odoo odoo -c $OdooConf -d $testDb -i $Module --test-tags "/$Module" --stop-after-init --log-level=test
            $code = $LASTEXITCODE
            if (($DrawBrowser -or $DrawLayout) -and $code -eq 0) {
                $browserPassword = New-Secret
                Invoke-OdooShellScript 'seed_draw_browser.py' @{NODO_DRAW_BROWSER_PASSWORD = $browserPassword} $testDb
                try {
                    $env:NODO_DRAW_BROWSER_DB = $testDb
                    $env:NODO_DRAW_BROWSER_PASSWORD = $browserPassword
                    & node (Join-Path $Root 'scripts/draw/verify_accessory_library.cjs') $DrawLayout
                    $code = $LASTEXITCODE
                }
                finally {
                    [Environment]::SetEnvironmentVariable('NODO_DRAW_BROWSER_DB', $null)
                    [Environment]::SetEnvironmentVariable('NODO_DRAW_BROWSER_PASSWORD', $null)
                }
            }
        }
        finally {
            Write-Host "删除一次性测试库 $testDb ..."
            & docker compose --project-directory $Root -f $ComposeFile run --rm --no-deps odoo odoo db -c $OdooConf drop $testDb
        }
        if ($code -ne 0) { throw "测试失败（退出码 $code）" }
        Write-Host '测试通过'
    }
    'shell' { Assert-Initialized; Invoke-Compose exec odoo odoo shell -c $OdooConf -d $DevDb }
    default {
        Get-Content -LiteralPath $PSCommandPath -Encoding UTF8 | Select-Object -Skip 1 -First 25
    }
}
