# Публикация на GitHub

Рекомендуемое имя: `linklane`.

Описание: `Self-hosted Python link shortener with custom aliases, QR codes, a private dashboard and privacy-conscious analytics.`

Темы: `python`, `fastapi`, `url-shortener`, `sqlite`, `qrcode`, `self-hosted`, `portfolio`.

1. Распакуйте архив исходников в отдельную папку вне учебного Git-репозитория.
2. Создайте пустой GitHub-репозиторий без автоматически созданного README.
3. Из новой папки выполните:

```powershell
git init
git add .
git commit -m "Initial release: Linklane"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/linklane.git
git push -u origin main
```

Замените `YOUR_USERNAME` на свой логин. Агент эти команды не выполнял.
Перед загрузкой проверьте отсутствие `data`, `.demo`, `.session-key`, `.env`, `.venv`
и личных экспортов. В подготовленном архиве их нет.

Изображения в README используют вымышленные демонстрационные данные.
После публикации проверьте изображения и результаты GitHub Actions.
Сам сервер GitHub не запускает: для рабочей публичной ссылки нужно самостоятельное размещение.
