"""投递记录测试：快照、去重、状态机、停滞标记、统计与用户隔离。

不涉及 LLM，全部走同步接口。
"""

from datetime import datetime, timedelta, timezone

from app import applications as core
from app.models import (
    Application,
    ApplicationEvent,
    Company,
    JobPosting,
    MatchResult,
    Resume,
    UserManualJob,
)


def make_resume(db, user, **kwargs) -> Resume:
    resume = Resume(
        user_id=user.id,
        name=kwargs.pop("name", "resume.md"),
        file_path=kwargs.pop("file_path", f"data/uploads/{user.id}/resume.md"),
        file_format="md",
        original_encrypted="",
        parsed_profile_json=kwargs.pop("profile", {"skills": ["Python"]}),
        version=kwargs.pop("version", 1),
        is_master=kwargs.pop("is_master", True),
        parse_status="done",
        **kwargs,
    )
    db.add(resume)
    db.commit()
    return resume


def make_job(db, company_name="米哈游", **kwargs) -> JobPosting:
    company = Company(name=company_name)
    db.add(company)
    db.commit()
    job = JobPosting(
        company_id=company.id,
        title=kwargs.pop("title", "后端开发工程师"),
        location=kwargs.pop("location", "上海"),
        employment_type="全职",
        experience_required="3-5年",
        skills=["Python"],
        responsibilities=[],
        requirements=[],
        nice_to_have=[],
        description_raw="负责订单系统开发。",
        source_url="https://jobs.mihoyo.com/#/position/7001",
        source_type="manual",
        content_hash="a" * 64,
        is_active=True,
        **kwargs,
    )
    db.add(job)
    db.commit()
    return job


def make_manual_job(db, user, **kwargs) -> UserManualJob:
    job = UserManualJob(
        user_id=user.id,
        company_name=kwargs.pop("company_name", "小公司"),
        title=kwargs.pop("title", "Python 工程师"),
        location="北京",
        skills=[],
        responsibilities=[],
        requirements=[],
        nice_to_have=[],
        description_raw="写 Python。",
        source_type="manual",
        content_hash="c" * 64,
    )
    db.add(job)
    db.commit()
    return job


def apply(client, headers, ref_type: str, ref_id: int, **body) -> dict:
    resp = client.post(
        "/api/applications",
        headers=headers,
        json={"job_ref_type": ref_type, "job_ref_id": ref_id, **body},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------- 创建与快照


def test_create_application_snapshots_shared_job(client, user_headers, db, normal_user):
    make_resume(db, normal_user)
    job = make_job(db)

    data = apply(client, user_headers, "job_posting", job.id)

    assert data["status"] == "applied"
    assert data["company_name"] == "米哈游"
    assert data["title"] == "后端开发工程师"
    assert data["location"] == "上海"
    assert data["source_url"] == "https://jobs.mihoyo.com/#/position/7001"
    assert data["resume_id"] is not None
    assert data["match_score"] is None  # 未打分也能投
    assert data["days_since_update"] == 0
    assert data["is_stale"] is False
    assert data["next_status"] == "written_test"


def test_snapshot_survives_job_change(client, user_headers, db, normal_user):
    make_resume(db, normal_user)
    job = make_job(db)
    data = apply(client, user_headers, "job_posting", job.id)

    job.title = "改过的标题"
    db.add(job)
    db.commit()

    detail = client.get(f"/api/applications/{data['id']}", headers=user_headers).json()
    assert detail["title"] == "后端开发工程师"


def test_create_from_manual_job_and_explicit_resume(client, user_headers, db, normal_user):
    first = make_resume(db, normal_user, name="master.md", is_master=True)
    second = make_resume(db, normal_user, name="v2.md", is_master=False, version=2)
    job = make_manual_job(db, normal_user)

    data = apply(client, user_headers, "user_manual_job", job.id, resume_id=second.id)

    assert data["company_name"] == "小公司"
    assert data["resume_id"] == second.id
    assert data["resume_id"] != first.id


def test_match_score_and_result_are_snapshotted(client, user_headers, db, normal_user):
    resume = make_resume(db, normal_user)
    job = make_job(db)
    match = MatchResult(
        user_id=normal_user.id,
        resume_id=resume.id,
        resume_version=resume.version,
        job_ref_type="job_posting",
        job_ref_id=job.id,
        score=88,
        payload_json={},
    )
    db.add(match)
    db.commit()

    data = apply(client, user_headers, "job_posting", job.id)

    assert data["match_score"] == 88
    assert data["match_result_id"] == match.id


def test_duplicate_application_returns_conflict(client, user_headers, db, normal_user):
    make_resume(db, normal_user)
    job = make_job(db)
    first = apply(client, user_headers, "job_posting", job.id)

    resp = client.post(
        "/api/applications",
        headers=user_headers,
        json={"job_ref_type": "job_posting", "job_ref_id": job.id},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["application_id"] == first["id"]


def test_unknown_job_returns_400(client, user_headers, db, normal_user):
    make_resume(db, normal_user)
    resp = client.post(
        "/api/applications",
        headers=user_headers,
        json={"job_ref_type": "job_posting", "job_ref_id": 9999},
    )
    assert resp.status_code == 400


def test_cannot_apply_to_other_users_manual_job(client, user_headers, db, normal_user, other_user):
    make_resume(db, normal_user)
    job = make_manual_job(db, other_user)

    resp = client.post(
        "/api/applications",
        headers=user_headers,
        json={"job_ref_type": "user_manual_job", "job_ref_id": job.id},
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------- 状态机


def test_transition_allows_skip_and_records_timeline(client, user_headers, db, normal_user):
    make_resume(db, normal_user)
    job = make_job(db)
    data = apply(client, user_headers, "job_posting", job.id)

    resp = client.patch(
        f"/api/applications/{data['id']}", headers=user_headers, json={"status": "interview", "note": "约了下周三"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "interview"

    detail = client.get(f"/api/applications/{data['id']}", headers=user_headers).json()
    assert [e["to_status"] for e in detail["events"]] == ["applied", "interview"]
    assert detail["events"][1]["from_status"] == "applied"
    assert detail["events"][1]["note"] == "约了下周三"


def test_terminal_status_is_final(client, user_headers, db, normal_user):
    make_resume(db, normal_user)
    job = make_job(db)
    data = apply(client, user_headers, "job_posting", job.id)

    ok = client.patch(f"/api/applications/{data['id']}", headers=user_headers, json={"status": "rejected"})
    assert ok.status_code == 200
    assert ok.json()["is_stale"] is False  # 终止态不再算停滞

    blocked = client.patch(f"/api/applications/{data['id']}", headers=user_headers, json={"status": "offer"})
    assert blocked.status_code == 400
    assert "已结束" in blocked.json()["detail"]


def test_unknown_status_rejected(client, user_headers, db, normal_user):
    make_resume(db, normal_user)
    job = make_job(db)
    data = apply(client, user_headers, "job_posting", job.id)

    resp = client.patch(f"/api/applications/{data['id']}", headers=user_headers, json={"status": "ghosted"})
    assert resp.status_code == 400
    assert "未知状态" in resp.json()["detail"]


def test_same_status_is_idempotent(client, user_headers, db, normal_user):
    make_resume(db, normal_user)
    job = make_job(db)
    data = apply(client, user_headers, "job_posting", job.id)

    resp = client.patch(f"/api/applications/{data['id']}", headers=user_headers, json={"status": "applied"})
    assert resp.status_code == 200
    detail = client.get(f"/api/applications/{data['id']}", headers=user_headers).json()
    assert len(detail["events"]) == 1


def test_note_update_refreshes_activity(client, user_headers, db, normal_user):
    make_resume(db, normal_user)
    job = make_job(db)
    data = apply(client, user_headers, "job_posting", job.id)

    application = db.get(Application, data["id"])
    old = datetime.now(timezone.utc) - timedelta(days=10)
    application.last_activity_at = old
    db.commit()

    before = client.get(f"/api/applications/{data['id']}", headers=user_headers).json()
    assert before["days_since_update"] >= 10 and before["is_stale"] is True

    resp = client.patch(f"/api/applications/{data['id']}", headers=user_headers, json={"note": "发了催问邮件"})
    assert resp.status_code == 200
    assert resp.json()["note"] == "发了催问邮件"
    assert resp.json()["days_since_update"] == 0
    assert resp.json()["is_stale"] is False


# ---------------------------------------------------------------- 列表与统计


def test_list_filters_sorts_and_marks_stale(client, user_headers, db, normal_user):
    make_resume(db, normal_user)
    first = apply(client, user_headers, "job_posting", make_job(db, company_name="A", title="岗位A").id)
    second = apply(client, user_headers, "job_posting", make_job(db, company_name="B", title="岗位B").id)
    client.patch(f"/api/applications/{second['id']}", headers=user_headers, json={"status": "offer"})

    stale_row = db.get(Application, first["id"])
    stale_row.last_activity_at = datetime.now(timezone.utc) - timedelta(days=9)
    db.commit()

    rows = client.get("/api/applications", headers=user_headers).json()
    assert len(rows) == 2
    stale = next(r for r in rows if r["id"] == first["id"])
    assert stale["is_stale"] is True and stale["days_since_update"] == 9

    offers = client.get("/api/applications?status=offer", headers=user_headers).json()
    assert [r["id"] for r in offers] == [second["id"]]

    by_stale = client.get("/api/applications?sort=stale", headers=user_headers).json()
    assert by_stale[0]["id"] == first["id"]


def test_stats_counts_by_status_and_stale(client, user_headers, db, normal_user):
    make_resume(db, normal_user)
    one = apply(client, user_headers, "job_posting", make_job(db, company_name="A").id)
    two = apply(client, user_headers, "job_posting", make_job(db, company_name="B").id)
    apply(client, user_headers, "job_posting", make_job(db, company_name="C").id)
    client.patch(f"/api/applications/{two['id']}", headers=user_headers, json={"status": "rejected"})

    row = db.get(Application, one["id"])
    row.last_activity_at = datetime.now(timezone.utc) - timedelta(days=8)
    db.commit()

    stats = client.get("/api/applications/stats", headers=user_headers).json()
    assert stats["total"] == 3
    assert stats["by_status"]["applied"] == 2
    assert stats["by_status"]["rejected"] == 1
    assert stats["stale"] == 1
    assert stats["active"] == 2


# ---------------------------------------------------------------- 隔离


def test_other_user_cannot_see_or_modify(client, user_headers, other_headers, db, normal_user):
    make_resume(db, normal_user)
    job = make_job(db)
    data = apply(client, user_headers, "job_posting", job.id)

    assert client.get(f"/api/applications/{data['id']}", headers=other_headers).status_code == 404
    assert (
        client.patch(
            f"/api/applications/{data['id']}", headers=other_headers, json={"status": "offer"}
        ).status_code
        == 404
    )
    assert client.get("/api/applications", headers=other_headers).json() == []
    assert client.get("/api/applications/stats", headers=other_headers).json()["total"] == 0


# ---------------------------------------------------------------- 纯逻辑


def test_days_since_update_handles_naive_datetime():
    application = Application(
        user_id=1,
        job_ref_type="job_posting",
        job_ref_id=1,
        company_name="X",
        title="Y",
        status="applied",
        applied_at=datetime.now(timezone.utc),
        last_activity_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=3),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    assert core.days_since_update(application) == 3
    payload = core.serialize(application)
    assert payload["is_stale"] is False
    assert payload["status_label"] == "已投递"


def test_events_cascade_on_delete(client, user_headers, db, normal_user):
    make_resume(db, normal_user)
    job = make_job(db)
    data = apply(client, user_headers, "job_posting", job.id)
    client.patch(f"/api/applications/{data['id']}", headers=user_headers, json={"status": "interview"})

    db.delete(db.get(Application, data["id"]))
    db.commit()

    assert db.query(ApplicationEvent).count() == 0
