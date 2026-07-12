"""Entry-Point: ``python -m mailer``."""

from .send import main

if __name__ == "__main__":
    raise SystemExit(main())
