# Подключение к VPS

```bash
ssh root@195.133.77.76
```

Пароль или SSH-ключ должен быть уже настроен через панель хостера или ваш ssh agent.

## Проверка окружения

```bash
cat /etc/os-release   # узнать версию Ubuntu
df -h                 # свободное место (нужно ≥ 5 ГБ для моделей)
free -h               # оперативка (medium ≈ 5 ГБ, large-v3 ≈ 10 ГБ)
nproc                 # число CPU cores
ip addr               # узнать сетевые интерфейсы
```

## Одноразовый deploy (Ubuntu 22.04 / 24.04 / 26.04)

### 1. Загрузить скрипт

На **вашей Windows-машине**:
```cmd
cd C:\HTML_Protokol
scp deploy-vps.sh root@195.133.77.76:/root/
```

### 2. Запустить deploy на сервере

```bash
ssh root@195.133.77.76
chmod +x /root/deploy-vps.sh
/root/deploy-vps.sh
```

Скрипт автоматически:
- ✅ обновит систему
- ✅ установит Python 3.12 + PostgreSQL 15 + nginx + ffmpeg + git
- ✅ создаст пользователя `hmp` (безопасность)
- ✅ создаст БД `html_mp` + пользователя `hmp`
- ✅ склонирует проект из GitHub
- ✅ создаст venv + установит deps
- ✅ сгенерирует `.env` с SECRET_KEY
- ✅ применит миграции
- ✅ настроит systemd сервис `hmp-backend.service`
- ✅ настроит nginx (frontend + reverse proxy)
- ✅ откроет порты в firewall

⏱ Время установки: ~5-10 минут (без моделей).

### 3. Скачать модель

После установки:
```bash
# Без SSH, прямо с вашей Windows-машины:
curl -X POST http://195.133.77.76/api/v1/hmp/whisper/download/base

# Или в UI: http://195.133.77.76/ → Settings → Whisper Models
```

Размеры:
- `tiny` — 75 MB
- `base` — 150 MB
- `small` — 500 MB
- `medium` — 1.5 GB ⚠️ нужен 5+ ГБ RAM
- `large-v3` — 3 GB ⚠️ нужен 10+ ГБ RAM

**Для VPS рекомендую начать с `base`** — лучшее соотношение скорости и качества.

## Обновление (после изменений в коде)

### С Windows-машины (без SSH)

```cmd
cd C:\HTML_Protokol
.\deploy-to-vps.bat
```

Этот скрипт:
1. ✅ Создаёт zip-архив проекта
2. ✅ Загружает на VPS через `scp`
3. ✅ Распаковывает на сервере
4. ✅ Запускает `update-vps.sh`:
   - pip install --upgrade
   - применяет новые миграции
   - рестартит hmp-backend

### С Linux-сервера (через git push)

Если вы уже запушили изменения в GitHub:
```bash
ssh root@195.133.77.76
/root/update-vps.sh
```

## Просмотр логов

```bash
# Backend логи:
tail -f /var/log/hmp-backend.log

# systemd логи:
journalctl -u hmp-backend -f

# nginx логи:
tail -f /var/log/nginx/access.log
tail -f /var/log/nginx/error.log
```

## Что работает после deploy

| URL | Что |
|---|---|
| `http://195.133.77.76/` | Frontend (UI) |
| `http://195.133.77.76/api/v1/hmp/docs` | Swagger (API) |
| `http://195.133.77.76/api/v1/hmp/health` | Health check |
| `http://195.133.77.76:5173/` | Frontend напрямую (если открыт порт) |
| `http://195.133.77.76:8000/docs` | Swagger (напрямую) |

## Полезные команды на сервере

```bash
# Статус сервисов
systemctl status hmp-backend
systemctl status nginx
systemctl status postgresql

# Рестарт
systemctl restart hmp-backend
systemctl reload nginx

# Логи
journalctl -u hmp-backend -n 100 --no-pager

# PostgeSQL
sudo -u postgres psql -d html_mp -c "SELECT count(*) FROM protocol;"
```

## Безопасность

После первого deploy **обязательно**:
```bash
# 1. Сменить пароль БД
sudo -u postgres psql -c "ALTER USER hmp WITH PASSWORD 'YOUR_SECURE_PASSWORD';"
sed -i "s|hmp_password|YOUR_SECURE_PASSWORD|" /root/HTML_MeetingProtokol/code/hmp-backend/.env

# 2. Firewall: оставить только 22, 80, 443
ufw default deny incoming
ufw allow 22/tcp     # SSH
ufw allow 80/tcp     # HTTP
ufw allow 443/tcp    # HTTPS (если будете настраивать SSL)
ufw enable
ufw status

# 3. SSL через Let's Encrypt (бесплатно)
apt install -y certbot python3-certbot-nginx
certbot --nginx -d 195.133.77.76 -d yourdomain.com
```

## Если что-то пошло не так

1. **Backend не стартует:**
   ```bash
   journalctl -u hmp-backend -n 50 --no-pager
   cat /var/log/hmp-backend.log
   ```

2. **PostgreSQL не подключается:**
   ```bash
   systemctl status postgresql
   sudo -u postgres psql -d html_mp -c "\dt"
   ```

3. **nginx 502 Bad Gateway:**
   ```bash
   systemctl status hmp-backend
   tail -f /var/log/nginx/error.log
   ```

4. **Полный сброс:**
   ```bash
   systemctl stop hmp-backend
   cd /root/HTML_MeetingProtokol/code/hmp-backend
   sudo -u hmp ./.venv/bin/python -c "from app.db.session import init_db; import asyncio; asyncio.run(init_db())"
   systemctl start hmp-backend
   ```
