from __future__ import annotations

from app.config import load_config
from app.services.descriptor import build_descriptor_xml


def main() -> None:
    print(build_descriptor_xml(load_config()))


if __name__ == "__main__":
    main()
