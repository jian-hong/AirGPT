"""A forwarded header must never buy you the host's identity.

The host-only gate asked `not _is_local_host(ip)`, where ip came from
`_client_ip()` -> `_forwarded_client_ip()`, which returned CF-Connecting-IP or
X-Forwarded-For verbatim. Both are client-supplied. Only a provider that
overwrites them makes them trustworthy, and the four providers in the sweep do
not agree: cloudflared sets CF-Connecting-IP, localtunnel sets X-Forwarded-For
and has no reason to touch anything Cloudflare-shaped, and serveo/localhost.run
are raw ssh forwards that set neither.

So `CF-Connecting-IP: 127.0.0.1` made a remote caller the host. Verified live
against a loca.lt tunnel before the fix: GET /api/audit returned 403 bare and
200 with that single header, serving the real audit trail. The same bypass
opened all 17 _HOST_ONLY_PREFIXES, /api/terminal/ and /api/fs/ among them.

And with no headers at all - a raw ssh forward - `_forwarded_client_ip` returned
None, `_client_ip()` fell back to the loopback address the forward arrives on,
and every remote visitor was the host without trying anything.

Root cause class (R-0004): the gate trusted an identity the caller could author.
It now asks the question directly - a request carrying a tunnel Host header came
from outside this machine, whatever any header claims.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("AIRGPT_NO_BROWSER", "1")

import clipdrop  # noqa: E402

LOOPBACK = "127.0.0.1"
TUNNEL_HOSTS = ("abc.loca.lt", "abc.serveo.net", "abc.lhr.life",
                "abc.trycloudflare.com", "abc.localhost.run")


class _Headers(dict):
    def get(self, key, default=None):
        return dict.get(self, key, default)


def _headers(host, **extra):
    h = _Headers({"Host": host})
    h.update({k.replace("_", "-"): v for k, v in extra.items()})
    return h


class HostGateSpoofTest(unittest.TestCase):
    def test_forwarded_header_cannot_claim_loopback(self):
        for host in TUNNEL_HOSTS:
            for header in ("CF-Connecting-IP", "X-Forwarded-For"):
                h = _headers(host, **{header.replace("-", "_"): LOOPBACK})
                self.assertFalse(
                    clipdrop._is_host_request(h, LOOPBACK),
                    f"{header}: {LOOPBACK} over {host} was treated as the host",
                )

    def test_forwarded_header_cannot_claim_the_hosts_lan_ip(self):
        """_is_local_host also passes the host's own LAN address."""
        try:
            lan = [x for x in clipdrop.local_ips() if x not in ("127.0.0.1", "::1")]
        except Exception:
            lan = []
        if not lan:
            self.skipTest("no non-loopback local ip on this machine to impersonate")
        for host in TUNNEL_HOSTS:
            h = _headers(host, CF_Connecting_IP=lan[0])
            self.assertFalse(
                clipdrop._is_host_request(h, LOOPBACK),
                f"a header claiming the host LAN ip {lan[0]} passed over {host}",
            )

    def test_raw_ssh_forward_with_no_headers_is_not_the_host(self):
        """serveo and localhost.run add nothing; the fallback used to be loopback."""
        for host in ("abc.serveo.net", "abc.lhr.life"):
            self.assertFalse(
                clipdrop._is_host_request(_headers(host), LOOPBACK),
                f"a header-less tunnel request over {host} was treated as the host",
            )

    def test_unidentified_tunnel_peer_is_not_address_shaped(self):
        ip = clipdrop._forwarded_client_ip(_headers("abc.serveo.net"), LOOPBACK)
        self.assertEqual(ip, clipdrop.TUNNEL_PEER)
        self.assertFalse(clipdrop._is_local_host(ip))

    def test_a_real_remote_ip_is_still_reported(self):
        """The gate must not blind the audit trail: name the peer when we know it."""
        h = _headers("abc.trycloudflare.com", CF_Connecting_IP="203.0.113.9")
        self.assertEqual(clipdrop._forwarded_client_ip(h, LOOPBACK), "203.0.113.9")

    # R-0005: a control that refuses legitimate work is a failure. The host must
    # keep full access on the paths it actually uses.
    def test_host_on_loopback_still_passes(self):
        for host in ("127.0.0.1:8765", "localhost:8765", "airgpt.local:8765"):
            self.assertTrue(
                clipdrop._is_host_request(_headers(host), LOOPBACK),
                f"host was locked out of its own machine via {host}",
            )

    def test_host_on_its_own_lan_ip_still_passes(self):
        try:
            lan = [x for x in clipdrop.local_ips() if x not in ("127.0.0.1", "::1")]
        except Exception:
            lan = []
        if not lan:
            self.skipTest("no non-loopback local ip on this machine to test with")
        self.assertTrue(
            clipdrop._is_host_request(_headers(f"{lan[0]}:8765"), lan[0]),
            "host was locked out when browsing its own LAN address",
        )

    def test_lan_peer_is_not_the_host(self):
        self.assertFalse(
            clipdrop._is_host_request(_headers("192.168.1.50:8765"), "192.168.1.50"),
            "a LAN peer was treated as the host",
        )


if __name__ == "__main__":
    unittest.main()
