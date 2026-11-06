"""Offline memory_events transfer using the selected storage plugin."""
from .storage_transfer import main as _main

def main() -> None:
    _main("memory_events")

if __name__ == "__main__":
    main()
