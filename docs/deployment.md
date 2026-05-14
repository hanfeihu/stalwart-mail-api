# 部署文档

这里以 Linux + systemd + Nginx 为例。

## 1. 准备目录

```bash
sudo mkdir -p /opt/stalwart-mail-api
sudo cp mail_api.py /opt/stalwart-mail-api/
sudo chmod 755 /opt/stalwart-mail-api/mail_api.py
```

## 2. 配置环境变量

创建 `/opt/stalwart-mail-api/.env`：

```bash
STALWART_BASE_URL=https://mail.example.com
STALWART_ADMIN_EMAIL=admin@example.com
STALWART_ADMIN_PASSWORD=change-me
MAIL_DOMAIN=example.com
MAIL_API_KEY=replace-with-a-long-random-key
MAIL_API_HOST=127.0.0.1
MAIL_API_PORT=8765
```

生成随机 API Key：

```bash
openssl rand -hex 32
```

## 3. systemd

复制服务文件：

```bash
sudo cp systemd/stalwart-mail-api.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now stalwart-mail-api
sudo systemctl status stalwart-mail-api
```

## 4. Nginx 反向代理

把下面配置放到对应站点的 `server` 块中：

```nginx
location ^~ /mail-api/ {
    proxy_pass http://127.0.0.1:8765/mail-api/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_connect_timeout 60s;
    proxy_send_timeout 600s;
    proxy_read_timeout 600s;
}
```

检查并重载：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 5. 验证

```bash
curl https://your-domain.com/mail-api/health
```

打开文档页面：

```text
https://your-domain.com/mail-api/docs
```

## 常见问题

### 401 Unauthorized

请求头里的 `Authorization: Bearer <MAIL_API_KEY>` 不正确。

### Password is too weak

Stalwart 有自己的密码强度策略，请换一个更强的密码。

### Upstream request failed

通常是本服务无法访问 Stalwart，或 Stalwart 管理员账号密码不正确。检查：

- `STALWART_BASE_URL`
- `STALWART_ADMIN_EMAIL`
- `STALWART_ADMIN_PASSWORD`
- 服务器到 Stalwart 的网络连通性

### 只能访问健康检查，创建账号失败

健康检查不需要连接 Stalwart，创建账号需要连接 Stalwart 并使用管理员权限。
