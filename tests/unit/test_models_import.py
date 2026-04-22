from yas.db.models import (
    Alert,
    AlertRouting,
    CrawlRun,
    Enrollment,
    ExtractionCache,
    HouseholdSettings,
    Kid,
    Location,
    Match,
    Offering,
    Page,
    Site,
    UnavailabilityBlock,
    WatchlistEntry,
    WorkerHeartbeat,
)


def test_all_models_importable():
    # A sanity smoke — they must all be Base subclasses with a __tablename__.
    for cls in [
        Alert,
        AlertRouting,
        CrawlRun,
        Enrollment,
        ExtractionCache,
        HouseholdSettings,
        Kid,
        Location,
        Match,
        Offering,
        Page,
        Site,
        UnavailabilityBlock,
        WatchlistEntry,
        WorkerHeartbeat,
    ]:
        assert hasattr(cls, "__tablename__"), f"{cls.__name__} has no __tablename__"
