"""Shared constants for the Cambrian sports calendar project."""

# Cities considered part of the South Bay for home-game filtering.
# Defined once here to ensure consistency across build_calendar.py,
# schedule_fetcher.py, and scripts/repopulate_schedules.py.
SOUTH_BAY_CITIES: frozenset[str] = frozenset({
    "Campbell",
    "Cupertino",
    "Los Gatos",
    "Morgan Hill",
    "Mountain View",
    "San Jose",
    "Santa Clara",
    "Saratoga",
    "Stanford",
})
