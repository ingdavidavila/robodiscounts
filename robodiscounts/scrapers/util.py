import re
from typing import Optional


def parse_money(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    m = re.search(r"(\d[\d,]*\.?\d*)", text.replace("\xa0", " "))
    return float(m.group(1).replace(",", "")) if m else None
