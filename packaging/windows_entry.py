"""PyInstaller entry point; desktop remains independently importable in tests."""
import sys

from desktop.main import main


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--smoke-test":
        from desktop.bundle_check import check_bundle
        raise SystemExit(check_bundle(sys.argv[2]))
    raise SystemExit(main())
