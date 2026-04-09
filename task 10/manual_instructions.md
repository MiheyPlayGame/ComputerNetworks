# Task 10 — ручной DNS и traceroute (Windows)

**Требования:** PowerShell, встроенная команда `tracert`.

Перейти в каталог задания:

```powershell
Set-Location "c:\Users\Mihey\Desktop\CompNet\ComputerNetworks\task 10"
```

---

## 1. DNS: список доменов → IP-адреса

Запрос A-записей для каждой непустой строки в `domains.txt` и запись в `dns_ips_manual.txt`:

```powershell
Get-Content domains.txt | ForEach-Object {
    $d = $_.Trim()
    if ($d) {
        "`n=== $d ==="
        Resolve-DnsName -Name $d -Type A -ErrorAction SilentlyContinue |
            Where-Object { $_.Type -eq 'A' } |
            ForEach-Object { $_.IPAddress }
    }
} | Out-File -FilePath manual_dns_ips.txt -Encoding utf8
```

Откройте `dns_ips_manual.txt` и скопируйте IP для шага 2 (или подставьте свой массив).

---

## 2. Traceroute: каждый IP → текстовый лог

На Windows используется `**tracert**`, не `traceroute`.


| Параметр | Смысл                                                   |
| -------- | ------------------------------------------------------- |
| `-d`     | не делать обратный DNS по промежуточным узлам (быстрее) |
| `-h 12`  | не больше 12 хопов                                      |
| `-w 800` | таймаут ответа одного зонда, мс                         |


Пример: список IP вручную (замените на адреса из вашего `manual_dns_ips.txt`).

**Важно:** каждый адрес в **кавычках** (`'…'`). Без кавычек PowerShell воспринимает `64.233.164.139` как выражение, массив `$ips` оказывается пустым, `tracert` вызывается без цели.

```powershell
$ips = @(
    '64.233.164.139'
    '140.82.121.4'
    '77.88.55.88'
    '84.237.49.123'
    '104.16.133.229'
)

Remove-Item -ErrorAction SilentlyContinue manual_tracert.txt
foreach ($ip in $ips) {
    "`n===== TRACERT $ip =====`n" | Out-File -Append manual_tracert.txt -Encoding utf8
    tracert -d -h 12 -w 800 $ip 2>&1 | Out-File -Append manual_tracert.txt -Encoding utf8
}
```

Проверка: `$ips` должно вывести пять строк; если пусто — снова задайте массив с кавычками.

Результат — файл **`manual_tracert.txt`**.

---

## 3. Сводка в CSV (скрипт)

Те же шаги для **всех** IPv4 из DNS и разбор хопов в таблицу:

```powershell
python dns_traceroute.py
```

