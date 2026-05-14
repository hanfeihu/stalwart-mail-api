# Stalwart Mail API

给 [Stalwart Mail Server](https://stalw.art/) 封装一层简单、可部署、可二次开发的 REST API。

Stalwart 本身很强，但它面向的是完整邮件服务器和 JMAP/管理接口。很多业务系统只需要几个直接的 HTTP 能力：创建邮箱、分页读取邮件、转发邮件。这个项目就是把这些常用能力整理成一套轻量接口，方便接到自己的 SaaS、CRM、自动化系统、注册收信系统或内部工具里。

## 适合谁用

- 已经部署了 Stalwart，但希望用 REST API 管理邮箱账号。
- 业务系统需要自动创建 `user@example.com` 这类邮箱。
- 需要通过接口读取某个邮箱收到的邮件，并支持分页。
- 需要通过接口把指定邮件转发给其他邮箱。
- 想基于 Stalwart 做一套自己的邮件平台或邮件中台。

## 功能

- 创建邮箱账号。
- 分页查询邮件列表。
- 转发指定邮件。
- 内置健康检查。
- 内置简洁 API 文档页面。
- 不依赖第三方 Python 包，方便在服务器上直接运行。
- 支持通过 Nginx 挂到 `/mail-api/` 子路径。

## 工作方式

```text
Your App
   |
   | REST API + Bearer Token
   v
Stalwart Mail API
   |
   | Stalwart OAuth/JMAP/Admin API
   v
Stalwart Mail Server
```

这个服务不会替代 Stalwart，它只是站在 Stalwart 前面，把常见动作包装成更容易接入的 HTTP 接口。

## 快速开始

准备 Python 3.6+：

```bash
git clone https://github.com/hanfeihu/stalwart-mail-api.git
cd stalwart-mail-api
cp .env.example .env
```

编辑 `.env`：

```bash
STALWART_BASE_URL=https://mail.example.com
STALWART_ADMIN_EMAIL=admin@example.com
STALWART_ADMIN_PASSWORD=change-me
MAIL_DOMAIN=example.com
MAIL_API_KEY=change-this-to-a-long-random-secret
MAIL_API_HOST=127.0.0.1
MAIL_API_PORT=8765
```

本地启动：

```bash
set -a
. ./.env
set +a
python3 mail_api.py
```

访问：

```text
http://127.0.0.1:8765/mail-api/docs
```

## API 示例

所有写接口都需要：

```http
Authorization: Bearer <MAIL_API_KEY>
Content-Type: application/json
```

### 创建邮箱

```bash
curl -X POST http://127.0.0.1:8765/mail-api/v1/accounts \
  -H "Authorization: Bearer $MAIL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "River-Cedar-Quartz-7291!",
    "name": "Test User"
  }'
```

### 获取邮件列表

```bash
curl -X POST http://127.0.0.1:8765/mail-api/v1/messages/search \
  -H "Authorization: Bearer $MAIL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "River-Cedar-Quartz-7291!",
    "page": 1,
    "pageSize": 20
  }'
```

### 转发邮件

```bash
curl -X POST http://127.0.0.1:8765/mail-api/v1/messages/forward \
  -H "Authorization: Bearer $MAIL_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "River-Cedar-Quartz-7291!",
    "messageId": "message-id-from-list",
    "to": "target@example.com",
    "comment": "Please check this email."
  }'
```

## 部署

推荐部署方式：

1. Stalwart 负责邮件服务。
2. 本项目监听 `127.0.0.1:8765`。
3. Nginx 把公网的 `/mail-api/` 反向代理到本服务。
4. 使用 systemd 保持服务常驻。

详细步骤见 [部署文档](docs/deployment.md)。

## 安全建议

- 不要把 `.env`、管理员密码、API Key 提交到仓库。
- `MAIL_API_KEY` 请使用足够长的随机字符串。
- 只通过 HTTPS 暴露接口。
- 如果接口面向公网，建议在 Nginx 层增加 IP 白名单、访问频率限制或网关鉴权。
- 创建邮箱接口需要 Stalwart 管理员权限，务必保护好部署机器。

## 路线图

- 删除邮箱账号。
- 修改邮箱密码。
- 获取邮件正文详情。
- 附件下载。
- Webhook 收信通知。
- OpenAPI JSON 输出。

## License

MIT

如果这个项目帮你少踩一点邮件系统集成的坑，欢迎点一个 Star。
