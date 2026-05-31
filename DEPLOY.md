# 🐧 狗三云部署指南

> 把狗三从本地搬到云端 24 小时运行，不再占用自己电脑。

---

## 架构概览

```
┌──────────────────────────────────────────┐
│              云服务器 (VPS)                │
│                                          │
│  ┌──────────────────┐  反向WS   ┌──────┐ │
│  │  dog3-bot        │◄─────────│NapCat│ │
│  │  (NoneBot2)      │  :3001   │(协议)│ │
│  │  Python 3.11     │          └──────┘ │
│  │  端口 8080       │             │      │
│  └──────────────────┘          QQ 服务器  │
│                                          │
│  ┌──────────────────┐                    │
│  │  NapCat WebUI    │ ← 浏览器扫码登录    │
│  │  端口 6099       │                    │
│  └──────────────────┘                    │
└──────────────────────────────────────────┘
```

**连接方式**：反向 WebSocket。NapCat 开放端口 3001，Bot 主动连接 `ws://napcat:3001` 获取 QQ 消息。

---

## 方案选择

| 方案 | 适合人群 | 月费 |
|------|---------|------|
| **A. Docker 部署**（推荐）| 会用命令行的 | 服务器费用 |
| **B. 传统部署** | 想一步步手动的 | 同上 |
| **C. 本地继续跑** | 不想花钱 | 0（但费电） |

---

## 前置准备

### 1. 买一台云服务器

最低配置：**1 核 2G 内存**，Linux（Ubuntu 22.04 / Debian 12）。

推荐（国内访问快）：
- 阿里云 ECS（99 元/年 的活动机就够）
- 腾讯云轻量应用服务器

### 2. 连接服务器

```bash
ssh root@你的服务器IP
```

### 3. 安装 Docker

```bash
# 一键安装
curl -fsSL https://get.docker.com | sh

# 启动 Docker
systemctl enable docker
systemctl start docker

# 安装 Docker Compose 插件
apt install docker-compose-plugin -y
```

验证：

```bash
docker --version
docker compose version
```

---

## 方案 A：Docker 一键部署（推荐）

### 1. 克隆项目

```bash
cd /opt
git clone https://github.com/FBIMAYO1/qq-group-guard.git
cd qq-group-guard
```

### 2. 配置 .env

```bash
cp .env.example .env
nano .env
```

关键修改：

```env
# 改为 Docker 容器间通信地址
ONEBOT_WS_URLS=["ws://napcat:3001"]

# 换成你的 QQ 号
SUPERUSERS=["你的QQ号"]

# 换成你的 DeepSeek API Key
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
```

其他保持默认即可。

### 3. 启动

```bash
docker compose up -d
```

### 4. 扫码登录 QQ

第一次启动需要扫码登录：

1. 浏览器打开 `http://你的服务器IP:6099`
2. 进入 NapCat WebUI → 网络配置
3. 点击「添加 QQ 账号」→ 扫码登录

扫码成功后，查看 bot 是否连接成功：

```bash
docker compose logs -f bot
```

看到类似输出说明成功：

```
[INFO] nonebot | OneBot V11 反向 WebSocket 连接到 ws://napcat:3001
[INFO] nonebot | Running NoneBot...
```

### 5. 日常管理

```bash
# 查看日志
docker compose logs -f bot

# 重启
docker compose restart

# 停止
docker compose down

# 更新代码后重新部署
git pull
docker compose up -d --build
```

---

## 方案 B：传统部署（不用 Docker）

### 1. 服务器环境

```bash
# 安装 Python 3.11
apt update
apt install python3.11 python3.11-venv python3-pip -y

# 安装 NapCat（使用 Docker，因为 NapCat 在 Linux 上推荐 Docker 跑）
# 或者使用 lagrange.onebot 等替代协议端
```

> **注意**：NapCat 在 Linux 上推荐 Docker 运行。如果不想用 Docker 跑 bot，至少 NapCat 建议用 Docker。可以参考方案 A 的 docker-compose，只跑 napcat 服务。

### 2. 部署 Bot

```bash
cd /opt
git clone https://github.com/FBIMAYO1/qq-group-guard.git
cd qq-group-guard

# 创建虚拟环境
python3.11 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 配置 .env（同方案 A 第 2 步）
cp .env.example .env
nano .env
```

### 3. 使用 systemd 守护

```bash
nano /etc/systemd/system/dog3-bot.service
```

写入：

```ini
[Unit]
Description=狗三 QQ 机器人
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/qq-group-guard
ExecStart=/opt/qq-group-guard/venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动：

```bash
systemctl daemon-reload
systemctl enable dog3-bot
systemctl start dog3-bot

# 查看状态
systemctl status dog3-bot
# 查看日志
journalctl -u dog3-bot -f
```

---

## 方案 C：本地继续跑 + 远程访问（零成本）

如果你暂时不想买服务器，可以让 bot 继续在本地跑，配合：

- **远程控制**：用 RustDesk / AnyDesk 远程桌面
- **自动重启**：把 `start.bat` 加入 Windows 任务计划，设置开机自启
- **断电保护**：配合 UPS 或者智能插座定时重启电脑

---

## 数据持久化

以下数据保存在服务器上，容器重启不丢失：

| 数据 | Docker 路径 | 说明 |
|------|-----------|------|
| 签到记录 | `./data/checkin.json` | 群友签到 streak |
| 违规记录 | `./data/violations.json` | AI 检测违规历史 |
| 群配置 | `./data/group_config.json` | 每群独立开关状态 |
| 活跃统计 | `./data/activity.json` | 发言数统计 |
| QQ 登录态 | `./napcat-data/qq/` | 扫码后持久化，不用反复扫 |

备份建议：

```bash
# 定时备份到其他位置
tar -czf backup-$(date +%Y%m%d).tar.gz data/ napcat-data/qq/
```

---

## 安全注意事项

1. **`.env` 绝对不能泄露**（含 DeepSeek API Key），`.gitignore` 已排除
2. **NapCat WebUI 端口 6099** 建议用防火墙限制访问：
   ```bash
   # 只允许你的 IP 访问 WebUI
   ufw allow from 你的IP to any port 6099
   ```
   或者用 SSH 隧道访问：
   ```bash
   ssh -L 6099:localhost:6099 root@你的服务器IP
   # 然后浏览器打开 http://localhost:6099
   ```
3. **Bot 端口 8080** 不需要对外开放（NapCat 在容器内连接）

---

## 常见问题

### Q: QQ 掉线了怎么办？

重新扫码登录：打开 `http://服务器IP:6099` → 网络配置 → 重新登录。

### Q: 怎么更新 bot？

```bash
cd /opt/qq-group-guard
git pull
docker compose up -d --build    # Docker 方案
# 或
systemctl restart dog3-bot      # systemd 方案
```

### Q: 日志太多占磁盘？

Docker 日志已限制 10MB/文件 × 3 个。也可以手动清理：

```bash
docker compose down
docker system prune -a
```

### Q: 扫码后一直连不上？

检查 NapCat 的 WebSocket 配置：
1. 打开 `http://服务器IP:6099`
2. 进入「网络配置」→ 确保「反向 WebSocket」已启用，端口 3001
3. 查看 bot 日志：`docker compose logs bot`

---

*部署完成后，在群里发 `/群管状态` 确认狗三正在运行 🐧*
