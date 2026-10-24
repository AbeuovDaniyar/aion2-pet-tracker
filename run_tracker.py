"""Entry point for the packaged app (PyInstaller) and a simple way to start it from source."""
import sys

from app.main import main

if __name__ == "__main__":
    sys.exit(main())
