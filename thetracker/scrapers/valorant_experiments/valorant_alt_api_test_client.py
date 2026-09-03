"""
Small test client for the Valorant stats Flask API.
Sends HTTP requests and prints JSON responses in the terminal.
"""

import json

import requests

BASE_URL = "http://127.0.0.1:5000"


def test_endpoint(label: str, url: str) -> None:
    """GET an endpoint and print the response."""
    print(f"\n{'=' * 50}")
    print(f"  {label}")
    print(f"  GET {url}")
    print("=" * 50)

    try:
        response = requests.get(url, timeout=5)
        print(f"Status: {response.status_code}")
        print(json.dumps(response.json(), indent=2))
    except requests.exceptions.ConnectionError:
        print("ERROR: Could not connect to the API.")
        print("Make sure valapi.py is running:  py valapi.py")
    except Exception as e:
        print(f"ERROR: {e}")


def main():
    endpoints = [
        ("Home", f"{BASE_URL}/"),
        ("All matches", f"{BASE_URL}/matches"),
        ("Single match", f"{BASE_URL}/matches/match_001"),
        ("All players", f"{BASE_URL}/players"),
        ("TenZ stats", f"{BASE_URL}/player/TenZ/stats"),
        ("ScreaM stats", f"{BASE_URL}/player/ScreaM/stats"),
        ("Demo stats", f"{BASE_URL}/stats/demo"),
    ]

    print("Valorant API Test Client")
    print(f"Target: {BASE_URL}")

    for label, url in endpoints:
        test_endpoint(label, url)

    print(f"\n{'=' * 50}")
    print("  Done!")
    print("=" * 50)


if __name__ == "__main__":
    main()
