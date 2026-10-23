"""Small text helpers shared by the agent nodes and tools."""
import re
from typing import Optional


def short_branch_name(name: Optional[str], default: str = "clinic") -> str:
    """'T. Nagar Branch' -> 'T. Nagar'. Returns `default` when no name is given."""
    if not name:
        return default
    return re.sub(r"\s+branch\b", "", name, flags=re.IGNORECASE).strip() or default
