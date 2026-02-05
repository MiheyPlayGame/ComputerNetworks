import subprocess
import re
import csv

def ping_host(host):
    command = ['ping', '-n', '2', host]
    
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError:
        print(f"{host} недоступен")
        return 0

hosts = ["google.com", "youtube.com", "gmail.com", "table.nsu.ru", "kaggle.com", "github.com", "tbank.ru", "jackboxgames.ru", "ozon.ru", "steamcommunity.com"]

ping_data = []

for host in hosts:
    out = ping_host(host)

    try:
        time_match = re.search(r'time[=<](\d+)ms', out)
        min_match = re.search(r'Minimum\s*=\s*(\d+)ms', out)
        max_match = re.search(r'Maximum\s*=\s*(\d+)ms', out)
        avg_match = re.search(r'Average\s*=\s*(\d+)ms', out)

        time = int(time_match.group(1))
        minimum = int(min_match.group(1))
        maximum = int(max_match.group(1))
        average = int(avg_match.group(1))

        ping_data.append({
            'host': host,
            'time': time,
            'minimum': minimum,
            'maximum': maximum,
            'average': average
        })
    except:
        ping_data.append({
            'host': host,
            'time': None,
            'minimum': None,
            'maximum': None,
            'average': None
        })

with open('ping_results.csv', 'w', newline='', encoding='utf-8') as csvfile:
    fieldnames = ['host', 'time', 'minimum', 'maximum', 'average']
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    
    writer.writeheader()
    for row in ping_data:
        writer.writerow(row)

