import csv
import re
import sys
from pathlib import Path

from dns_traceroute import parse_tracert_output

MANUAL_DNS = Path(__file__).with_name("manual_dns_ips.txt")
MANUAL_TRACERT = Path(__file__).with_name("manual_tracert.txt")
OUTPUT_CSV = Path(__file__).with_name("manual_traceroutes_results.csv")

SECTION_HEADER = re.compile(r"^===\s*(.+?)\s*===\s*$")
IP_LINE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
TRACERT_HEADER = re.compile(r"^===== TRACERT ([\d.]+) =====\s*$")

FIELDNAMES = [
    "domain",
    "target_ip",
    "hop",
    "rtt1_ms",
    "rtt2_ms",
    "rtt3_ms",
    "hop_host",
    "raw_tracert_excerpt",
]


def parse_manual_dns(path: Path) -> dict[str, str]:
    """domain -> listed IPv4; reverse map ip -> domain (last section wins if IP repeats)."""
    ip_to_domain: dict[str, str] = {}
    current_domain: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        m = SECTION_HEADER.match(line)
        if m:
            current_domain = m.group(1).strip()
            continue
        if not line or current_domain is None:
            continue
        if IP_LINE.match(line):
            ip_to_domain[line] = current_domain
    return ip_to_domain


def split_tracert_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_ip: str | None = None
    buf: list[str] = []
    for raw in text.splitlines():
        m = TRACERT_HEADER.match(raw.strip())
        if m:
            if current_ip is not None:
                sections.append((current_ip, "\n".join(buf)))
            current_ip = m.group(1)
            buf = []
        elif current_ip is not None:
            buf.append(raw)
    if current_ip is not None:
        sections.append((current_ip, "\n".join(buf)))
    return sections


def main() -> None:
    if not MANUAL_DNS.is_file():
        print(f"Missing {MANUAL_DNS}", file=sys.stderr)
        sys.exit(1)
    if not MANUAL_TRACERT.is_file():
        print(f"Missing {MANUAL_TRACERT}", file=sys.stderr)
        sys.exit(1)

    ip_to_domain = parse_manual_dns(MANUAL_DNS)
    body = MANUAL_TRACERT.read_text(encoding="utf-8")
    sections = split_tracert_sections(body)

    rows: list[dict[str, str]] = []
    for target_ip, chunk in sections:
        domain = ip_to_domain.get(target_ip, "")
        hops = parse_tracert_output(chunk)
        if not hops:
            rows.append(
                {
                    "domain": domain,
                    "target_ip": target_ip,
                    "hop": "",
                    "rtt1_ms": "",
                    "rtt2_ms": "",
                    "rtt3_ms": "",
                    "hop_host": "",
                    "raw_tracert_excerpt": chunk[:2000].replace("\r\n", "\n"),
                }
            )
            continue
        for h in hops:
            rows.append(
                {
                    "domain": domain,
                    "target_ip": target_ip,
                    "hop": h["hop"],
                    "rtt1_ms": h["rtt1_ms"],
                    "rtt2_ms": h["rtt2_ms"],
                    "rtt3_ms": h["rtt3_ms"],
                    "hop_host": h["hop_host"],
                    "raw_tracert_excerpt": "",
                }
            )

    with OUTPUT_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    print(f"Written {OUTPUT_CSV} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
