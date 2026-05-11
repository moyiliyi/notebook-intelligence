"""Verify the redirect-guard handlers on remote skill fetches.

Pre-fix: stock urllib follows any 30x to anywhere, so a hijacked DNS
entry, a typo'd manifest URL, or a malicious repo URL could silently
redirect a fetch to an attacker host that captures the bearer token
or serves a tarball that bypasses our extraction guards.

This module pokes the handlers directly — synthesizing a redirect
response without an HTTP server — so the tests are deterministic.
"""

import io
import urllib.error

import pytest

from notebook_intelligence import skill_github_import, skill_manifest


def _fake_redirect_inputs(orig_url: str, headers: dict):
    """Build the (req, fp, code, msg, headers, newurl)-shaped args that
    HTTPRedirectHandler.redirect_request expects."""
    import urllib.request

    req = urllib.request.Request(orig_url, headers=headers)
    fp = io.BytesIO(b"")
    return req, fp, 302, "Found", {}


class TestGitHubOnlyRedirect:
    def setup_method(self):
        self.handler = skill_github_import._GitHubOnlyRedirectHandler()

    def test_blocks_redirect_to_attacker_host(self):
        req, fp, code, msg, hdrs = _fake_redirect_inputs(
            "https://api.github.com/repos/o/r/tarball/HEAD",
            {"Authorization": "Bearer secret"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            self.handler.redirect_request(
                req, fp, code, msg, hdrs, "https://evil.example.com/loot"
            )
        assert "non-GitHub host" in str(exc.value)

    def test_allows_redirect_to_codeload(self):
        # api.github.com → codeload.github.com is the legitimate tarball flow.
        req, fp, code, msg, hdrs = _fake_redirect_inputs(
            "https://api.github.com/repos/o/r/tarball/HEAD",
            {"Authorization": "Bearer secret", "Accept": "application/vnd.github+json"},
        )
        new_req = self.handler.redirect_request(
            req, fp, code, msg, hdrs,
            "https://codeload.github.com/o/r/legacy.tar.gz/HEAD",
        )
        assert new_req is not None
        assert new_req.full_url.startswith("https://codeload.github.com/")

    def test_strips_authorization_on_cross_host_redirect(self):
        req, fp, code, msg, hdrs = _fake_redirect_inputs(
            "https://api.github.com/repos/o/r/tarball/HEAD",
            {"Authorization": "Bearer secret", "Accept": "application/vnd.github+json"},
        )
        new_req = self.handler.redirect_request(
            req, fp, code, msg, hdrs,
            "https://codeload.github.com/o/r/legacy.tar.gz/HEAD",
        )
        # No Authorization header on the cross-host hop — the bearer never
        # reaches a host that doesn't need it.
        items = {k.lower(): v for k, v in new_req.header_items()}
        assert "authorization" not in items
        # Other headers (Accept) are preserved.
        assert items.get("accept") == "application/vnd.github+json"

    def test_keeps_authorization_on_same_host_redirect(self):
        # 301 from api.github.com → api.github.com (path normalization, etc.)
        # should keep the auth header so the retry succeeds.
        req, fp, code, msg, hdrs = _fake_redirect_inputs(
            "https://api.github.com/repos/o/r",
            {"Authorization": "Bearer secret"},
        )
        new_req = self.handler.redirect_request(
            req, fp, code, msg, hdrs,
            "https://api.github.com/repositories/12345",
        )
        items = {k.lower(): v for k, v in new_req.header_items()}
        assert items.get("authorization") == "Bearer secret"

    def test_blocks_redirect_to_subdomain_typo(self):
        # `github.com.evil.com` is a classic phishing pattern — must not match.
        req, fp, code, msg, hdrs = _fake_redirect_inputs(
            "https://api.github.com/repos/o/r/tarball/HEAD",
            {},
        )
        with pytest.raises(urllib.error.HTTPError):
            self.handler.redirect_request(
                req, fp, code, msg, hdrs,
                "https://github.com.evil.com/loot",
            )

    def test_blocks_https_to_http_downgrade(self):
        # An on-path attacker who can spoof a 302 could chain
        # ``https://api.github.com`` → ``http://api.github.com`` and capture
        # the bearer in cleartext. Even though the host is allowlisted, the
        # scheme downgrade has to be refused.
        req, fp, code, msg, hdrs = _fake_redirect_inputs(
            "https://api.github.com/repos/o/r/tarball/HEAD",
            {"Authorization": "Bearer secret"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            self.handler.redirect_request(
                req, fp, code, msg, hdrs,
                "http://api.github.com/repos/o/r/tarball/HEAD",
            )
        assert "non-HTTPS" in str(exc.value)


class TestManifestNoRedirect:
    def setup_method(self):
        self.handler = skill_manifest._NoRedirectHandler()

    def test_blocks_any_redirect(self):
        req, fp, code, msg, hdrs = _fake_redirect_inputs(
            "https://manifests.example.com/skills.yaml",
            {"Authorization": "Bearer secret"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            self.handler.redirect_request(
                req, fp, code, msg, hdrs,
                "https://manifests.example.com/skills.v2.yaml",
            )
        assert "manifest" in str(exc.value).lower()

    def test_blocks_even_same_host_redirect(self):
        # The manifest URL is supposed to be stable. A redirect signals an
        # operator URL drift; failing loud is the right call.
        req, fp, code, msg, hdrs = _fake_redirect_inputs(
            "https://example.com/skills.yaml", {}
        )
        with pytest.raises(urllib.error.HTTPError):
            self.handler.redirect_request(
                req, fp, code, msg, hdrs,
                "https://example.com/skills.yaml/",
            )
