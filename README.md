# SharingFace

一个以双图投票为核心的 Python 网站，支持中英文切换。

- 游客直接投票或跳过，注册登录后可上传、删除自己的照片。
- 随机展示两位不同用户的照片，排除自己的照片；同一身份不会再次遇到已经投过或跳过的照片对。
- 记录选择、左右展示顺序与时间；投票以事务更新 Elo 分数和排行榜，重复提交不会重复计分。
- 默认中文，也会读取浏览器语言；页面右上角可以切换中文或英文，选择保存在 Cookie 中。

技术栈：Django 5.2 LTS、SQLite、Django 模板、原生 CSS / JavaScript。无需 Node 构建或外部 API。

## 本地运行

需要 Python 3.12 或更新版本。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python manage.py migrate
python manage.py runserver
```

默认监听 `[::]:8000`，同时接受 IPv4 和 IPv6 连接。可在本机访问 <http://127.0.0.1:8000/> 或 <http://[::1]:8000/>，也可以使用本机的其他 IP 地址访问；系统需支持 IPv6 和 IPv4 映射。默认接受任意 Host，可通过 `DJANGO_ALLOWED_HOSTS` 限制。

首次打开会显示空状态。注册至少两个账号，各上传一张照片，再使用未登录的浏览器窗口即可投票。登录用户要遇到两位**其他用户**的照片才会出现对局。

照片保存在 `media/`，数据库是 `db.sqlite3`。这两处均不纳入版本控制；没有自动生成的参赛照片或虚构票数。

```bash
python manage.py test
python manage.py createsuperuser
```

后台地址：`/admin/`。

## 核心代码

| 文件 | 职责 |
| --- | --- |
| `arena/models.py` | 照片、投票身份、对局及约束 |
| `arena/services.py` | 配对、跳过、投票、Elo 更新 |
| `arena/forms.py` | 上传图片解码、压缩和去除元数据 |
| `arena/views.py` | 页面、账号衔接和照片管理 |
| `templates/`、`static/` | 页面与渐进增强交互，禁用 JavaScript 仍可投票 |
| `locale/zh_Hans/LC_MESSAGES/django.po` | 中文翻译 |

上传支持 JPEG、PNG、WebP，最大 10 MB / 2500 万像素；校正方向、缩小到最长边 1600 像素，转存 JPEG 并移除原始元数据。用户删除照片时会同时删除图片文件和包含该照片的对局；其他照片已经获得的历史 Elo 分数保留。

Elo 初始分数为 1000，K=32；至少参与一次有效投票后进入榜单。分数表示本站参与者的相对偏好。随机配对不承诺每张照片曝光完全相等。

游客身份保存在浏览器会话中，清除 Cookie 后会成为新游客。注册时保留当前游客的投票记录；已有账号登录后使用该账号的身份。当前没有跨设备游客识别、刷票风控或账号找回服务。

AI 评分和审美画像暂未实现；当前保留的是后续分析可用的原始选择记录，尚未加入模型训练流程。

## 修改翻译

运行不依赖 gettext 工具，已包含编译后的 `.mo` 文件。修改翻译时安装 GNU gettext（Ubuntu：`apt install gettext`），然后运行：

```bash
python manage.py makemessages -l zh_Hans --ignore=.venv
# 编辑 locale/zh_Hans/LC_MESSAGES/django.po
python manage.py compilemessages -l zh_Hans --ignore=.venv
```

英文使用代码和模板中的原始文案，新增语言时增加 `settings.LANGUAGES` 和对应的翻译文件。

## 部署配置

开发服务器仅供开发使用。部署时可安装 `pip install -e '.[production]'`，运行 `python manage.py collectstatic --noinput`，并使用 `gunicorn --bind '[::]:8000' sharingface.wsgi:application`。Gunicorn 的 IPv4 兼容性取决于系统的 IPv6 socket 设置（Linux 需要 `net.ipv6.bindv6only=0`）。反向代理负责 HTTPS、`/static/` 和 `/media/` 文件服务。

| 环境变量 | 用途 |
| --- | --- |
| `DJANGO_DEBUG=0` | 关闭调试；同时启用安全 Cookie |
| `DJANGO_SECRET_KEY` | 部署时必须设置为独立随机密钥 |
| `DJANGO_ALLOWED_HOSTS` | 允许访问的域名或 IP，逗号分隔；默认为 `*` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | 可信 HTTPS 来源，逗号分隔 |

SQLite 使用 IMMEDIATE 事务保证并发投票不会覆盖计分，适合初期小规模运行；扩大写入负载时可迁移到 PostgreSQL，并移除 SQLite 专属连接选项。
