"""Tests for the Slack sync-report block builder.

The previous version computed coverage gap counts by raw source membership:

    no_edr = [d for d in devices if "crowdstrike" not in d.sources]
    no_mdm = [d for d in devices if "jumpcloud" not in d.sources]

That conflated:
- "Without EDR" with IDP_ONLY devices (mobile / shadow IT that never need
  EDR by design).
- "Without MDM" with SERVER devices (no MDM is the correct posture).

These tests pin the new behaviour: gap counts come from `device.status`,
and IDP_ONLY / SERVER are surfaced separately as context.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.alerts import build_sync_blocks


def _block_text(blocks: list[dict], block_idx: int) -> str:
    """Helper: extract the markdown text from a section block."""
    b = blocks[block_idx]
    return b.get("text", {}).get("text", "")


def _full_text(blocks: list[dict]) -> str:
    """Concat every section's text — convenient for substring asserts."""
    out: list[str] = []
    for b in blocks:
        if b.get("type") == "section":
            t = b.get("text", {}).get("text")
            if t:
                out.append(t)
            for f in b.get("fields") or []:
                out.append(f.get("text", ""))
    return "\n".join(out)


class TestGapHonesty:
    """Counts in the report should reflect *real* coverage gaps, not the
    raw-source filter that mistakes IDP_ONLY for missing EDR or SERVER
    for missing MDM."""

    def test_no_edr_excludes_idp_only(self) -> None:
        # 5 NO_EDR (real gap) + 12 IDP_ONLY (NOT a gap) + 3 MANAGED
        status_counts = {"NO_EDR": 5, "IDP_ONLY": 12, "MANAGED": 3}
        blocks = build_sync_blocks(
            status_counts=status_counts, total=20, managed=3,
            sources_ok=["crowdstrike", "okta", "jumpcloud"], sources_failed=[],
            sync_status="success",
            no_edr_count=5, no_mdm_count=0,
            idp_only_count=12, server_count=0,
        )
        text = _full_text(blocks)
        assert "5` endpoints need CrowdStrike" in text
        # Context line surfaces the IDP-only carve-out so reader knows
        # what was *excluded* from the gap number.
        assert "12 IDP-only" in text

    def test_no_mdm_excludes_servers(self) -> None:
        status_counts = {"NO_MDM": 4, "SERVER": 25, "MANAGED": 10}
        blocks = build_sync_blocks(
            status_counts=status_counts, total=39, managed=10,
            sources_ok=["crowdstrike", "okta", "jumpcloud"], sources_failed=[],
            sync_status="success",
            no_edr_count=0, no_mdm_count=4,
            idp_only_count=0, server_count=25,
        )
        text = _full_text(blocks)
        assert "4` endpoints need JumpCloud" in text
        assert "25 servers/VMs" in text

    def test_no_context_lines_when_zero(self) -> None:
        """When there's no IDP_ONLY or SERVER, don't add empty context."""
        blocks = build_sync_blocks(
            status_counts={"FULLY_MANAGED": 100}, total=100, managed=100,
            sources_ok=["crowdstrike", "okta", "jumpcloud"], sources_failed=[],
            sync_status="success",
            no_edr_count=0, no_mdm_count=0,
            idp_only_count=0, server_count=0,
        )
        text = _full_text(blocks)
        assert "IDP-only" not in text
        assert "servers/VMs" not in text

    def test_real_world_klar_numbers(self) -> None:
        """Sanity: the example numbers from the user — 17 NO_EDR, 7 NO_MDM,
        39 IDP_ONLY, 51 SERVER — all surface cleanly without overlap."""
        blocks = build_sync_blocks(
            status_counts={
                "FULLY_MANAGED": 206, "MANAGED": 110,
                "NO_EDR": 17, "NO_MDM": 7,
                "IDP_ONLY": 39, "SERVER": 51, "STALE": 6,
            },
            total=436, managed=316,
            sources_ok=["crowdstrike", "okta", "jumpcloud"], sources_failed=[],
            sync_status="success",
            no_edr_count=17, no_mdm_count=7,
            idp_only_count=39, server_count=51,
        )
        text = _full_text(blocks)
        assert "17` endpoints need CrowdStrike" in text
        assert "39 IDP-only" in text
        assert "7` endpoints need JumpCloud" in text
        assert "51 servers/VMs" in text


class TestBackwardCompat:
    """Old call sites without the new keyword args still work — the
    context lines just don't appear."""

    def test_old_signature_still_renders(self) -> None:
        blocks = build_sync_blocks(
            status_counts={"NO_EDR": 5, "MANAGED": 100}, total=105, managed=100,
            sources_ok=["crowdstrike", "okta", "jumpcloud"], sources_failed=[],
            sync_status="success",
            no_edr_count=5, no_mdm_count=0,
        )
        text = _full_text(blocks)
        # Number still rendered, no context line because zero IDP/SERVER.
        assert "5` endpoints need CrowdStrike" in text
        assert "IDP-only" not in text
        assert "servers/VMs" not in text
