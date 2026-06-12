from pathlib import Path

from garmin_export.cli import ExportConfig, export_activities, iter_activities


class FakeClient:
    def __init__(self):
        self.detail_calls = []

    def get_activities(self, start=0, limit=20, activitytype=None):
        activities = [
            {"activityId": 101, "activityName": "One", "activityType": activitytype},
            {"activityId": 102, "activityName": "Two", "activityType": activitytype},
            {"activityId": 103, "activityName": "Three", "activityType": activitytype},
        ]
        return activities[start : start + limit]

    def get_activity(self, activity_id):
        self.detail_calls.append(("summary", activity_id))
        return {"activityId": activity_id, "full": True}

    def get_activity_details(self, activity_id):
        self.detail_calls.append(("details", activity_id))
        return {"activityId": activity_id, "metrics": []}


def test_iter_activities_reads_until_empty_page():
    client = FakeClient()

    activities = iter_activities(client, page_size=2, activity_type="running")

    assert [activity["activityId"] for activity in activities] == [101, 102, 103]
    assert {activity["activityType"] for activity in activities} == {"running"}


def test_export_activities_writes_manifest_and_activity_files(tmp_path: Path):
    client = FakeClient()
    config = ExportConfig(
        output_dir=tmp_path,
        page_size=2,
        include_details=True,
        activity_type=None,
        tokenstore=None,
    )

    result = export_activities(client, config)

    assert result.activity_count == 3
    assert (tmp_path / "manifest.json").exists()
    assert (tmp_path / "activities" / "101.json").exists()
    assert ("details", "101") in client.detail_calls
