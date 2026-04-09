import csv
import re
import socket
import subprocess
import sys
from pathlib import Path

DOMAINS_FILE = Path(__file__).with_name("domains.txt")
OUTPUT_CSV = Path(__file__).with_name("dns_traceroute_results.csv")
DNS_CACHE_TXT = Path(__file__).with_name("dns_resolved_ips.txt")

# Windows tracert: hop, three RTT fields, then hostname/IP or message
HOP_LINE = re.compile(
    r"^\s*(\d+)\s+"
    r"(\*|(?:<\d+|\d+)\s*ms)\s+"
    r"(\*|(?:<\d+|\d+)\s*ms)\s+"
    r"(\*|(?:<\d+|\d+)\s*ms)\s+"
    r"(.+?)\s*$"
)


def load_domains(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def resolve_ipv4(domain: str) -> list[str]:
    ips: list[str] = []
    try:
        infos = socket.getaddrinfo(domain, None, socket.AF_INET, socket.SOCK_STREAM)
    except socket.gaierror as e:
        print(f"DNS error {domain}: {e}", file=sys.stderr)
        return ips
    seen: set[str] = set()
    for item in infos:
        addr = item[4][0]
        if addr not in seen:
            seen.add(addr)
            ips.append(addr)
    return ips


def run_tracert(ip: str, max_hops: int = 30, timeout_ms: int = 800) -> str:
    cmd = ["tracert", "-d", "-h", str(max_hops), "-w", str(timeout_ms), ip]
    r = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    return r.stdout or r.stderr or ""


def parse_tracert_output(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        m = HOP_LINE.match(line)
        if not m:
            continue
        hop, p1, p2, p3, host = m.groups()
        rows.append(
            {
                "hop": hop,
                "rtt1_ms": p1.strip(),
                "rtt2_ms": p2.strip(),
                "rtt3_ms": p3.strip(),
                "hop_host": host.strip(),
            }
        )
    return rows


def main() -> None:
    if not DOMAINS_FILE.is_file():
        print(f"Нет файла {DOMAINS_FILE}", file=sys.stderr)
        sys.exit(1)

    domains = load_domains(DOMAINS_FILE)
    domain_to_ips: dict[str, list[str]] = {}
    all_lines: list[str] = []

    for d in domains:
        ips = resolve_ipv4(d)
        domain_to_ips[d] = ips
        all_lines.append(f"=== {d} ===")
        all_lines.extend(ips if ips else ["(no A record)"])
        all_lines.append("")

    DNS_CACHE_TXT.write_text("\n".join(all_lines), encoding="utf-8")

    csv_rows: list[dict[str, str]] = []
    for domain, ips in domain_to_ips.items():
        for ip in ips:
            print(f"tracert {domain} -> {ip} ...")
            out = run_tracert(ip)
            hops = parse_tracert_output(out)
            if not hops:
                csv_rows.append(
                    {
                        "domain": domain,
                        "target_ip": ip,
                        "hop": "",
                        "rtt1_ms": "",
                        "rtt2_ms": "",
                        "rtt3_ms": "",
                        "hop_host": "",
                        "raw_tracert_excerpt": out[:2000].replace("\r\n", "\n"),
                    }
                )
                continue
            for h in hops:
                csv_rows.append(
                    {
                        "domain": domain,
                        "target_ip": ip,
                        "hop": h["hop"],
                        "rtt1_ms": h["rtt1_ms"],
                        "rtt2_ms": h["rtt2_ms"],
                        "rtt3_ms": h["rtt3_ms"],
                        "hop_host": h["hop_host"],
                        "raw_tracert_excerpt": "",
                    }
                )

    fieldnames = [
        "domain",
        "target_ip",
        "hop",
        "rtt1_ms",
        "rtt2_ms",
        "rtt3_ms",
        "hop_host",
        "raw_tracert_excerpt",
    ]
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(csv_rows)

    print(f"Written {OUTPUT_CSV} ({len(csv_rows)} rows)")


if __name__ == "__main__":
    main()
