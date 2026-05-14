# API 文档

默认路径前缀为 `/mail-api`。

## 鉴权

除健康检查和文档页面外，接口都需要 Bearer Token：

```http
Authorization: Bearer <MAIL_API_KEY>
```

`MAIL_API_KEY` 在服务端环境变量中配置。

## GET /mail-api/health

健康检查。

响应：

```json
{
  "success": true,
  "service": "stalwart-mail-api",
  "domain": "example.com"
}
```

## POST /mail-api/v1/accounts

创建邮箱账号。

请求：

```json
{
  "email": "test@example.com",
  "password": "River-Cedar-Quartz-7291!",
  "name": "Test User",
  "locale": "en_US",
  "timeZone": "Asia/Shanghai"
}
```

响应：

```json
{
  "success": true,
  "email": "test@example.com",
  "id": "account-id"
}
```

说明：

- `email` 必须属于 `MAIL_DOMAIN`。
- `password` 至少 12 位，且还会经过 Stalwart 自身密码策略检查。
- `name`、`locale`、`timeZone` 可选。

## POST /mail-api/v1/messages/search

分页获取邮件列表。

请求：

```json
{
  "email": "test@example.com",
  "password": "River-Cedar-Quartz-7291!",
  "page": 1,
  "pageSize": 20
}
```

响应：

```json
{
  "success": true,
  "email": "test@example.com",
  "page": 1,
  "pageSize": 20,
  "total": 3,
  "position": 0,
  "messages": [
    {
      "id": "message-id",
      "subject": "Hello",
      "from": [{"email": "sender@example.net"}],
      "to": [{"email": "test@example.com"}],
      "receivedAt": "2026-05-14T00:00:00Z",
      "preview": "Message preview"
    }
  ]
}
```

说明：

- `pageSize` 最大为 100。
- 当前接口返回邮件摘要和预览，不返回完整附件。

## POST /mail-api/v1/messages/forward

转发指定邮件。

请求：

```json
{
  "email": "test@example.com",
  "password": "River-Cedar-Quartz-7291!",
  "messageId": "message-id-from-list",
  "to": "target@example.com",
  "comment": "Please check this email."
}
```

`to` 也可以是数组：

```json
{
  "to": ["a@example.com", "b@example.com"]
}
```

响应：

```json
{
  "success": true,
  "email": "test@example.com",
  "messageId": "message-id-from-list",
  "forwardedTo": ["target@example.com"]
}
```

## 错误格式

```json
{
  "success": false,
  "error": "Unauthorized",
  "detail": {}
}
```
