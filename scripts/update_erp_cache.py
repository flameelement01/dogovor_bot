#!/usr/bin/env python3
"""
Update erp_students_cache.json with fresh data from api.aiplus.school.
Usage:
  python3 update_erp_cache.py
  python3 update_erp_cache.py --username 950713301438 --password Aa12345678%
"""

import argparse
import getpass
import json
import sys
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).parent
ERP_CACHE = SCRIPT_DIR / "erp_students_cache.json"
API_BASE = "https://api.aiplus.school"

ERP_SHYM_BRANCHES = {
    "61a32b8f-8049-4d3c-b363-7d3e9d703f86": "Дулати",
    "fd41bf42-f34c-4c58-a85c-55e5d1611873": "Желтоксан",
    "3c45dc5c-1b45-4959-a463-d6fad455235a": "Шаяхметова",
}
ERP_ACTIVE = ["active", "new", "not_started", "frozen"]


def login(username: str, password: str) -> str:
    resp = requests.post(
        f"{API_BASE}/crm-login",
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    d = resp.json()
    if d.get("status") != "success":
        print(f"Login failed: {d.get('error')}")
        sys.exit(1)
    token = d["data"]["accessToken"]
    print(f"Logged in OK (token: {token[:20]}...)")
    return token


def fetch_branch(branch_id: str, branch_name: str, token: str) -> list:
    headers = {"Authorization": f"Bearer {token}", "Lang": "ru"}
    rows_per_page = 200
    students = []
    page = 1

    while True:
        body = {
            "page": page,
            "rowsPerPage": rows_per_page,
            "branches": [branch_id],
            "statuses": ERP_ACTIVE,
        }
        resp = requests.post(
            f"{API_BASE}/q/get-students",
            headers=headers,
            json=body,
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"  Error {resp.status_code}: {resp.text[:200]}")
            break

        data = resp.json().get("data", {})
        batch = data.get("students", [])
        total = data.get("total", 0)

        if not batch:
            break

        students.extend(batch)
        print(f"  {branch_name} page {page}: {len(students)}/{total}", flush=True)

        if len(students) >= total or len(batch) < rows_per_page:
            break
        page += 1

    return students


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", "-u")
    parser.add_argument("--password", "-p")
    args = parser.parse_args()

    username = args.username or input("ERP username (IIN/phone): ").strip()
    password = args.password or getpass.getpass("ERP password: ")

    token = login(username, password)

    all_new = []
    for branch_id, branch_name in ERP_SHYM_BRANCHES.items():
        print(f"\nFetching {branch_name}...")
        students = fetch_branch(branch_id, branch_name, token)
        print(f"  → {len(students)} active students from {branch_name}")
        all_new.extend(students)

    # Keep non-Shymkent from old cache, replace Shymkent with fresh data
    old_others = []
    if ERP_CACHE.exists():
        with open(ERP_CACHE) as f:
            old = json.load(f)
        old_others = [s for s in old if s.get("branch", {}).get("id") not in ERP_SHYM_BRANCHES]
        print(f"\nKept {len(old_others)} non-Shymkent records from old cache")

    merged = old_others + all_new
    with open(ERP_CACHE, "w") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"\nDone: {len(all_new)} Shymkent + {len(old_others)} other = {len(merged)} total")
    print(f"Cache saved to {ERP_CACHE}")


if __name__ == "__main__":
    main()
