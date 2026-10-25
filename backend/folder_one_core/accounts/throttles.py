from rest_framework.throttling import SimpleRateThrottle


class LoginThrottle(SimpleRateThrottle):
    """Limits login attempts per (client IP, email)."""

    scope = "login"

    def get_cache_key(self, request, view):
        email = str(request.data.get("email", "")).lower() if hasattr(request, "data") else ""
        return self.cache_format % {"scope": self.scope, "ident": f"{self.get_ident(request)}:{email}"}


class RegisterThrottle(SimpleRateThrottle):
    scope = "register"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
