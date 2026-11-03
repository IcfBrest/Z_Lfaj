"""打分纯逻辑单元测试：不触网、不建库，只验证规则与加权。"""

from types import SimpleNamespace

from app.scoring import (
    DEFAULT_WEIGHTS,
    DIMENSIONS,
    EXPERIENCE_GAP_YEARS,
    JobView,
    combine,
    degree_rank,
    filter_jobs,
    parse_min_years,
    profile_degree,
    profile_years,
    rank_candidates,
    relevance,
    resolve_weights,
)

PROFILE = {
    "basic_info": {"location": "上海", "years_of_experience": 3},
    "education": [{"school": "某大学", "degree": "本科", "major": "计算机"}],
    "work": [{"company": "某公司", "title": "后端开发工程师", "period": "2021-2024"}],
    "projects": [{"name": "订单系统", "role": "后端", "tech_stack": ["Go"]}],
    "skills": ["Python", "MySQL", "Redis"],
}


def job(**kwargs) -> JobView:
    data = dict(ref_type="job_posting", ref_id=1, title="后端开发工程师", company="某公司", location="上海")
    data.update(kwargs)
    return JobView(**data)


# ---------------------------------------------------------------- 硬规则解析


def test_parse_min_years_variants():
    assert parse_min_years("3-5年") == 3.0
    assert parse_min_years("10年以上") == 10.0
    assert parse_min_years("1年以内") == 1.0
    assert parse_min_years("经验不限") is None
    assert parse_min_years("应届毕业生") is None
    assert parse_min_years(None) is None
    assert parse_min_years("面议") is None


def test_degree_rank_order():
    assert degree_rank("大专") == 1
    assert degree_rank("本科及以上") == 2
    assert degree_rank("硕士") == 3
    assert degree_rank("博士") == 4
    assert degree_rank("Master degree") == 3
    assert degree_rank("学历不限") is None
    assert degree_rank(None) is None


def test_profile_helpers():
    assert profile_years(PROFILE) == 3.0
    assert profile_degree(PROFILE) == 2
    assert profile_years({}) is None
    assert profile_degree({"education": [{"degree": "博士"}, {"degree": "本科"}]}) == 4


def test_filter_jobs_excludes_experience_gap_and_degree():
    kept, excluded = filter_jobs(
        PROFILE,
        [
            job(ref_id=1, experience_required="3-5年"),  # 保留
            job(ref_id=2, experience_required="10年以上"),  # 经验差 7 年 → 排除
            job(ref_id=3, education_required="硕士及以上"),  # 学历不足 → 排除
            job(ref_id=4, experience_required=None, education_required=None),  # 解析不出 → 放行
        ],
    )
    assert [j.ref_id for j in kept] == [1, 4]
    assert {e["job_ref_id"] for e in excluded} == {2, 3}
    assert all(e["reason"] for e in excluded)
    assert EXPERIENCE_GAP_YEARS == 2.0


def test_filter_jobs_passes_unknown_profile():
    kept, excluded = filter_jobs({}, [job(experience_required="10年以上", education_required="博士")])
    assert len(kept) == 1 and excluded == []


# ---------------------------------------------------------------- 粗排


def test_relevance_prefers_skill_and_location_hit():
    hit = relevance(PROFILE, job(skills=["Python", "MySQL"], location="上海市"))
    miss = relevance(PROFILE, job(skills=["Rust", "Kubernetes"], location="北京", title="视觉设计师"))
    assert hit > miss
    assert 0.0 <= miss <= 1.0 and 0.0 <= hit <= 1.0


def test_rank_candidates_keeps_limit_and_order():
    jobs = [
        job(ref_id=1, skills=["Rust"]),
        job(ref_id=2, skills=["Python", "MySQL"], location="上海"),
        job(ref_id=3, skills=["Python"]),
    ]
    ranked = rank_candidates(PROFILE, jobs, limit=2)
    assert [j.ref_id for j in ranked] == [2, 3]
    assert rank_candidates(PROFILE, jobs, limit=0) == []


# ---------------------------------------------------------------- 加权总分


def test_combine_equal_weights():
    total, missing, scores = combine(
        {"技能匹配": 80, "经验相关度": 70, "职级与薪资匹配": 60, "行业/业务匹配": 50}, DEFAULT_WEIGHTS
    )
    assert total == 65
    assert missing == []
    assert scores["技能匹配"] == 80


def test_combine_respects_weights():
    weights = {"技能匹配": 100.0, "经验相关度": 0.0, "职级与薪资匹配": 0.0, "行业/业务匹配": 0.0}
    total, _, _ = combine(
        {"技能匹配": 80, "经验相关度": 10, "职级与薪资匹配": 10, "行业/业务匹配": 10}, weights
    )
    assert total == 80


def test_combine_missing_and_out_of_range_dimensions():
    total, missing, scores = combine({"技能匹配": 120, "经验相关度": -5}, DEFAULT_WEIGHTS)
    assert missing == ["职级与薪资匹配", "行业/业务匹配"]
    assert scores["技能匹配"] == 100 and scores["经验相关度"] == 0
    assert total == (100 + 0 + 0 + 0) // 4


def test_resolve_weights_defaults_and_override():
    assert resolve_weights(None) == DEFAULT_WEIGHTS
    assert resolve_weights(SimpleNamespace(score_weights=None)) == DEFAULT_WEIGHTS
    custom = resolve_weights(SimpleNamespace(score_weights={"技能匹配": 70, "经验相关度": 10}))
    assert custom["技能匹配"] == 70.0 and custom["行业/业务匹配"] == 25.0
    # 全 0 时回落到均等，避免除零
    assert resolve_weights(SimpleNamespace(score_weights={name: 0 for name in DIMENSIONS})) == DEFAULT_WEIGHTS
