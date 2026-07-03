"""
interface/auth.py — Grid Master OS Phase 5
Authentication placeholder hook for Phase 6 Security Layer.
All requests are currently allowed through.
"""

def check_auth(request=None) -> bool:
    """
    Phase 6 hook: validate API key, PAT, or session token.
    Currently returns True (open access) — will be replaced in Phase 6.
    """
    return True
