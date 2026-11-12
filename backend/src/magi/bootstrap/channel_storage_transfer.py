"""Offline channels transfer using the selected storage plugin."""
from .storage_transfer import main as _main

def main() -> None:
    _main("channels")

if __name__ == "__main__":
    main()
