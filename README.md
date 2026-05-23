# DealNest AstrBot QQ 群通知插件

这个插件采用拉取模式：AstrBot 定时访问 DealNest 的通知队列 API，广播到已绑定的 QQ 群，再回写发送结果。DealNest 不需要访问 AstrBot 或 NapCat。

## DealNest 环境变量

```env
QQBOT_ENABLED=true
BOT_NOTIFICATION_TOKEN=换成至少32位的随机字符串
QQBOT_NOTIFY_NEW_PROJECTS=true
QQBOT_NOTIFY_GROUP_SUCCESS=true
QQBOT_NOTIFY_PAYMENT_PERIOD=true
QQBOT_NOTIFY_DELIVERY_READY=true
BOT_NOTIFICATION_POLL_IDLE_SECONDS=30
BOT_NOTIFICATION_POLL_ACTIVE_SECONDS=5
BOT_NOTIFICATION_FAILURE_BACKOFF_SECONDS=60
```

部署后执行数据库迁移并重启 DealNest：

```powershell
npm.cmd run prisma:migrate:deploy
npm.cmd run prisma:generate
```

## AstrBot 配置

1. 在 AstrBot WebUI 的插件安装地址中填写：

```text
https://github.com/Cyrker/astrbot_plugin_dealnest_notifier
```

也可以把本目录放到 AstrBot 的插件目录后作为本地插件加载。
2. 在插件配置里填写：
   - `dealnest_base_url`：公网或内网可访问的 DealNest 地址，例如 `https://dealnest.example.com`
   - `token`：与 DealNest `BOT_NOTIFICATION_TOKEN` 相同
   - `dealnest_proxy_url`：可选，AstrBot 访问 DealNest 时使用的代理；留空直连，支持 `http://127.0.0.1:7890`、`s5://127.0.0.1:1080`、`socks5://user:pass@host:1080`
   - `admin_qqs`：允许执行 `/dn_bind_group`、`/dn_unbind_group`、`/dn_notify_status`、`/dn_poll_now` 的 QQ 号，每行或逗号分隔一个
3. 在每个要接收通知的 QQ 群里发送：

```text
/dn_bind_group
```

插件会保存当前群的 `unified_msg_origin` 到 `target_umos`，后续通知会广播到所有已绑定群。

如需移除某个群，在该群内发送：

```text
/dn_unbind_group
```

## 调试命令

```text
/dn_notify_status
/dn_poll_now
```

以上命令仅允许 `admin_qqs` 中的 QQ 或 AstrBot 全局管理员执行。

## 网络要求

只要求 AstrBot 所在内网能访问 DealNest 的 HTTP(S) 地址。可以通过 Tailscale、VPN、反向代理、内网域名或 `dealnest_proxy_url` 代理解决；不要求 DealNest 主动访问 AstrBot 或 NapCat。
