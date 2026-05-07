from __future__ import annotations

from app.config import load_config
from app.security.jwt_tools import build_vendor_api_jwt


def main() -> None:
    print(build_vendor_api_jwt(load_config()))


if __name__ == "__main__":
    main()
