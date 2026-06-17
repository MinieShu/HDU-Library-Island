# HDU Library Island

欢迎登上 HDU Library Island。这里是给杭州电子科技大学图书馆预约准备的程序：白天查座位，晚上守开抢时间，到了点就帮你自动执行任务。登陆使用你自己的学号和数字杭电密码，工具会在本地运行，不会把你的密码放进仓库。

## 能做什么

- 桌面 GUI：使用 PyQt6 启动本地窗口，完成登录、区域加载、座位查询和预约。
- Web UI：使用 React + FastAPI，浏览器里操作座位查询、选座和定时任务。
- CAS 登录：通过杭电统一身份认证获取图书馆预约会话。
- 座位预约：按日期、开始时间和时长查询可用座位，并提交预约。
- 定时抢座：设置开抢时间、候选座位、重试次数和并发请求数。
- 本地配置：账号、偏好和任务配置保存在本机 `hdu_library_autobook/config.json`。

## 行李清单

程序会自动检查本机环境，并在可以的时候自动安装或更新缺少的工具。你不需要先进入终端手动配置。

如果系统没有可用的自动安装工具，脚本会打开官方下载页或提示你手动安装：

- Python 3.10 或更高版本
- Node.js 18 或更高版本
- npm
- Windows PowerShell、macOS 终端或 Linux Shell（双击脚本时系统会自动打开）

Python 依赖在 [hdu_library_autobook/requirements.txt](hdu_library_autobook/requirements.txt) 里；前端依赖在 [hdu_library_autobook/web/package.json](hdu_library_autobook/web/package.json) 里。

## 双击启动

推荐普通用户直接使用项目根目录里的双击脚本：

- Windows：先双击 [setup.bat](setup.bat)，完成后双击 [start.bat](start.bat)。
- macOS：先双击 [setup.command](setup.command)，完成后双击 [start.command](start.command)。
- Linux：运行 [setup.sh](setup.sh)，完成后运行 [start.sh](start.sh)。部分桌面环境允许双击运行，部分会要求右键选择“作为程序运行”。

配置脚本会自动检查 Python、Node.js 和 npm，创建 Python 虚拟环境，并安装前后端依赖。启动脚本会一键启动后端 API 和 Web 前端，浏览器会打开 `http://127.0.0.1:5173`。

如果直接双击启动时发现依赖不完整，`start` 也会自动先运行对应的 `setup`。

配置脚本不会写入学号或密码。账号信息仍然只在 Web 登录页输入；如果勾选“记住密码”，程序会把信息保存到本机 `hdu_library_autobook/config.json`，该文件不会被提交到仓库。

## 终端脚本

如果你正在排查问题，或者更喜欢在终端里看完整输出，也可以直接运行系统脚本。

Windows PowerShell：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup_windows.ps1
.\scripts\start_windows.ps1
```

macOS：

```bash
chmod +x setup.command start.command scripts/setup_macos.sh scripts/start_macos.sh
./setup.command
./start.command
```

Linux：

```bash
chmod +x setup.sh start.sh scripts/setup_linux.sh scripts/start_linux.sh
./setup.sh
./start.sh
```

## 第一次上岛

克隆项目：

```bash
git clone https://github.com/MinieShu/HDU-Library-Island.git
cd HDU-Library-Island
```

然后按上面的“双击启动”操作：Windows 双击 `setup.bat`，macOS 双击 `setup.command`，Linux 运行 `setup.sh`。

下面是手动配置方式，适合脚本自动配置失败时排查问题。

准备 Python 环境：

macOS / Linux：

```bash
cd hdu_library_autobook
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Windows PowerShell：

```powershell
cd hdu_library_autobook
py -3 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

如果 PowerShell 提示不能执行脚本，可以只在当前窗口临时放行后再激活：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
```

Windows CMD：

```bat
cd hdu_library_autobook
py -3 -m venv venv
venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

如果你想预先生成本地配置文件，可以复制示例配置：

macOS / Linux：

```bash
cp config.example.json config.json
```

Windows PowerShell：

```powershell
Copy-Item config.example.json config.json
```

这一步不是必须的。Web 端会在登录页让你输入学号和密码，不需要改代码，也不需要提前把账号写进配置文件。请不要把自己的 `config.json` 提交到 GitHub，它已经被 `.gitignore` 保护起来了。

## 启动 Web UI

推荐直接使用上面的启动脚本。下面是手动启动方式，适合排查问题时使用。

先启动 Python API：

macOS / Linux：

```bash
cd hdu_library_autobook
source venv/bin/activate
python -m web_api
```

Windows PowerShell：

```powershell
cd hdu_library_autobook
.\venv\Scripts\Activate.ps1
python -m web_api
```

再开一个终端启动前端：

macOS / Linux / Windows：

```bash
cd hdu_library_autobook/web
npm install
npm run dev
```

浏览器打开：

```text
http://127.0.0.1:5173
```

如果你在 macOS 上，也可以双击项目根目录的 [start.command](start.command)。旧入口 [hdu_library_autobook/start_web.command](hdu_library_autobook/start_web.command) 仍然可用，它会转调用 [scripts/start_macos.sh](scripts/start_macos.sh)，从项目根目录启动 API，再进入 Web 目录启动 Vite。Windows 上推荐双击 [start.bat](start.bat)。

## Windows 使用教程

Windows 可以使用这个程序，推荐先跑 Web UI，因为浏览器界面最稳定。请按下面的小岛路线走：

1. 打开 PowerShell，进入你想放项目的目录。
2. 克隆仓库并进入项目：

```powershell
git clone https://github.com/MinieShu/HDU-Library-Island.git
cd HDU-Library-Island
```

3. 双击 `setup.bat`，或在 PowerShell 里运行一键配置脚本：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\scripts\setup_windows.ps1
```

4. 双击 `start.bat`，或在 PowerShell 里一键启动后端 API 和 Web 前端：

```powershell
.\scripts\start_windows.ps1
```

5. 浏览器打开 `http://127.0.0.1:5173`，在登录页输入自己的学号和数字杭电密码。
6. 使用时保持启动窗口开着；启动脚本会在另一个 PowerShell 窗口里运行后端 API。

如果需要手动启动，可以开两个 PowerShell 窗口：

```powershell
cd HDU-Library-Island\hdu_library_autobook
.\venv\Scripts\Activate.ps1
python -m web_api
```

```powershell
cd HDU-Library-Island\hdu_library_autobook\web
npm install
npm run dev
```

Windows 桌面 GUI 也可以运行：

```powershell
cd HDU-Library-Island\hdu_library_autobook
.\venv\Scripts\Activate.ps1
python main.py
```

如果桌面 GUI 启动失败，优先确认虚拟环境已激活、`PyQt6` 已安装，并尝试重新执行：

```powershell
python -m pip install --upgrade --force-reinstall PyQt6
```

## Web UI 使用教程

1. 打开页面后，在登录卡片里输入自己的学号和数字杭电密码。
2. 勾选“记住密码”会把密码写入本机 `config.json`，只建议在自己的电脑上使用。
3. 勾选“自动登录”会在本机保存自动登录偏好。
4. 登录成功后，先选择预约区域，例如自习室、阅览室或生活区。
5. 选择日期、开始时间和结束时间。
6. 点击“加载区域”，让系统准备该区域的预约参数。
7. 点击“查询座位”，页面会展示可预约和不可预约的座位。
8. 在“座位预约”页点击一个可用座位，再点击预约按钮。
9. 在“定时抢座”页可以把座位加入主选或备选，设置开抢时间、重试次数、重试间隔和并发请求数。
10. 创建任务后保持 API 服务运行。任务到点后会自动执行，页面会显示成功或失败消息。

## 启动桌面 GUI

macOS / Linux：

```bash
cd hdu_library_autobook
source venv/bin/activate
python main.py
```

Windows PowerShell：

```powershell
cd hdu_library_autobook
.\venv\Scripts\Activate.ps1
python main.py
```

调试模式：

```bash
python main.py --verbose
```

macOS 用户也可以双击 [hdu_library_autobook/start.command](hdu_library_autobook/start.command)，脚本会自动检查虚拟环境和依赖。Windows 用户推荐双击项目根目录的 [start.bat](start.bat) 启动 Web UI；如果要启动桌面 GUI，再使用上面的 PowerShell 命令。

## 桌面 GUI 使用教程

1. 启动后进入登录页，填写自己的学号和数字杭电密码。
2. 登录成功后进入主窗口。
3. 在座位相关页面选择区域、日期和时间。
4. 查询座位后选择目标座位并提交预约。
5. 如果要每日定时预约，在定时任务页面配置开抢时间、候选座位和重试参数。
6. 定时任务执行时请保持程序运行，网络也需要保持可用。

## 配置说明

常用字段在 `config.json` 中：

```json
{
    "auth": {
        "student_id": "",
        "password": "",
        "remember": false,
        "auto_login": false
    },
    "schedule": {
        "daily_open_time": "20:00:00",
        "pre_trigger_seconds": 3,
        "retry_interval_seconds": 1,
        "max_retries": 30
    }
}
```

- `auth.student_id`：登录成功后可由本地程序保存，也可以一直留空。
- `auth.password`：登录成功后可由本地程序保存。留空更安全，登录时手动输入。
- `auth.remember`：是否记住密码。
- `auth.auto_login`：是否尝试自动登录。
- `schedule.daily_open_time`：默认开抢时间。
- `schedule.pre_trigger_seconds`：提前触发秒数。
- `schedule.retry_interval_seconds`：失败后的重试间隔。
- `schedule.max_retries`：最大重试次数。

## 安全提醒

每位岛民的账号都要自己保管：

- 不要提交 `config.json`。
- 不要提交 `logs/`。
- 不要提交截图、调试 HTML 或任何包含 Cookie、学号、密码的文件。
- 如果曾经把密码提交到公开仓库，请立刻修改数字杭电密码并清理 Git 历史。
- 本项目只适合个人本地使用，请遵守学校图书馆预约规则。

## 常见问题

登录失败：

```text
请检查学号、密码、校园统一身份认证状态，以及当前网络能否访问杭电 SSO。
```

查询不到座位：

```text
先点击“加载区域”，再查询；也可能是该区域当天暂未开放预约。
```

定时任务没有执行：

```text
确认 API 服务仍在运行，电脑没有休眠，任务时间和本机时区正确。
```

前端连不上 API：

```text
确认 Python API 正在 http://127.0.0.1:8000 运行。
```

## 项目结构

```text
hdu_library_autobook/
├── api/                 # CAS 登录、区域、座位和房间接口
├── gui/                 # PyQt6 桌面界面
├── scheduler/           # 定时预约任务
├── utils/               # 配置和日志工具
├── web/                 # React 前端
├── main.py              # 桌面 GUI 入口
├── web_api.py           # FastAPI 本地 API
├── config.example.json  # 可提交的示例配置
└── requirements.txt     # Python 依赖
```

## 开发命令

Python 语法检查：

```bash
python -m compileall hdu_library_autobook
```

前端构建：

```bash
cd hdu_library_autobook/web
npm install
npm run build
```

这是个科技平权的时代，理性使用脚本，不要让脚本破坏原有的秩序，希望大家都能选上自己心仪的座位。
