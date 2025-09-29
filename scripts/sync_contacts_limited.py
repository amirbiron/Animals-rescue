"""
One-off script: sync limited number of organizations' contact details and alert channels.

Actions per organization (up to --limit):
- If google_place_id exists: fetch Google Place Details, update name/phone/website/address/types.
- Normalize primary_phone to E.164.
- Derive specialties from Google 'types'.
- If phone still missing: try SerpAPI enrichment by name+city (if configured).
- Recompute alert_channels for the org only (whatsapp/sms if phone, email if exists, telegram if chat id).

Usage:
  python /workspace/scripts/sync_contacts_limited.py --limit 10
"""

from __future__ import annotations

import argparse
import asyncio
from typing import List

import structlog

from sqlalchemy import select, and_, or_

from app.models.database import async_session_maker, Organization
from app.services.google import GoogleService
from app.services.serpapi import SerpAPIService
from app.services.sms import _normalize_e164 as _normalize_phone_e164


logger = structlog.get_logger(__name__).bind(component="sync_contacts_limited")


def _derive_specialties_from_types(types: List[str]) -> List[str]:
    specialties: List[str] = []
    for t in types or []:
        t_low = (t or "").lower()
        if any(k in t_low for k in [
            "dog", "cat", "bird", "wild", "reptile",
            "vet", "veterinary", "shelter", "rescue", "hospital"
        ]):
            specialties.append(t_low)
    # unique, sorted
    return sorted(list(set(specialties)))


async def _process(limit: int) -> dict:
    results = {"selected": 0, "updated": 0, "skipped": 0, "errors": 0}
    google = GoogleService()
    serp = SerpAPIService()

    async with async_session_maker() as session:
        # Pick candidates: missing phone/email/specialties, recent first where possible
        q = (
            select(Organization)
            .where(
                and_(
                    Organization.is_active == True,
                    or_(
                        Organization.primary_phone.is_(None),
                        Organization.email.is_(None),
                        Organization.specialties == []  # may not be supported by all DBs
                    )
                )
            )
            .limit(limit)
        )
        orgs = (await session.execute(q)).scalars().all()
        results["selected"] = len(orgs)

        for org in orgs:
            try:
                updated = False
                # 1) Google Place Details when available
                if org.google_place_id:
                    try:
                        details = await google.get_place_details(org.google_place_id)
                    except Exception:
                        details = None
                    if details:
                        org.name = details.get("name", org.name)
                        phone_raw = details.get("phone") or org.primary_phone
                        if phone_raw:
                            org.primary_phone = _normalize_phone_e164(phone_raw)
                        org.website = details.get("website", org.website)
                        org.address = details.get("address", org.address)
                        # specialties
                        types = list(details.get("types", []) or [])
                        specs = _derive_specialties_from_types(types)
                        if specs:
                            merged = sorted(list(set((org.specialties or []) + specs)))
                            org.specialties = merged
                        # coords if missing
                        if not (org.latitude and org.longitude) and details.get("latitude"):
                            org.latitude = details.get("latitude")
                            org.longitude = details.get("longitude")
                        updated = True

                # 2) SerpAPI enrichment if phone still missing
                if not org.primary_phone and org.name:
                    try:
                        contact = serp.get_contact_by_name_city(org.name, org.city)
                    except Exception:
                        contact = None
                    if contact:
                        if contact.get("phone") and not org.primary_phone:
                            org.primary_phone = _normalize_phone_e164(contact["phone"])  # type: ignore[arg-type]
                            updated = True
                        if contact.get("website") and not org.website:
                            org.website = contact["website"]
                            updated = True
                        if contact.get("place_id") and not org.google_place_id:
                            org.google_place_id = contact["place_id"]
                            updated = True

                # 3) Recompute alert channels for this org
                desired: List[str] = []
                if org.primary_phone:
                    desired.extend(["whatsapp", "sms"])
                if org.email:
                    desired.append("email")
                if org.telegram_chat_id:
                    desired.append("telegram")
                # Prefer mobile-only channels
                if desired:
                    seen = set()
                    org.alert_channels = [c for c in desired if not (c in seen or seen.add(c))]
                    updated = True

                if updated:
                    results["updated"] += 1
                else:
                    results["skipped"] += 1

            except Exception as e:  # noqa: BLE001
                logger.warning("org_update_failed", org_id=str(org.id), error=str(e))
                results["errors"] += 1

        await session.commit()

    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    results = asyncio.run(_process(args.limit))
    print(results)


if __name__ == "__main__":
    main()

