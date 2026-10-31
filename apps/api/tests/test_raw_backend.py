import json
from collections import Counter

from canonguard.plot.aliases import parse_alias_table
from canonguard.plot.raw_retrieval import (
    build_scene_query,
    candidate_pool,
    genre_affinity,
    mmr_select,
    rerank,
    retrieve_scenes,
)
from canonguard.plot.raw_suggest import (
    SuggestionDraft,
    bind_raw_suggestions,
    build_raw_suggestion_messages,
)
from canonguard.plot.scene_index import SceneHit, SceneIndex, SceneUnit
from canonguard.plot.schemas import StuckCharacter, StuckPoint


def _scene(
    scene_id: str,
    text: str,
    genre: str = "Drama",
    characters: tuple[str, ...] = (),
    heading: str = "SC 1",
    work_id: str = "w",
) -> SceneUnit:
    return SceneUnit(
        scene_id=scene_id,
        work_id=work_id,
        work_title=f"Work {scene_id}",
        language="zh",
        genre=genre,
        scene_no=1,
        heading=heading,
        text=text,
        characters=characters,
    )


def _hit(scene: SceneUnit, score: float = 0.5, vector: tuple[float, ...] = (1.0, 0.0)) -> SceneHit:
    return SceneHit(scene=scene, score=score, dense=score, lexical=0.0, vector=vector)


def _stuck(characters: list[StuckCharacter], genre: str = "Drama") -> StuckPoint:
    return StuckPoint(
        story_state="草稿",
        stuck_question="他们接下来该怎么走？",
        genre=genre,
        current_node="两人刚吵完",
        desired_effect="关系前进一步",
        characters=characters,
        constraints=["不能靠巧合"],
        narrative_functions=["relationship_turn"],
    )


def test_query_expands_aliases_and_keeps_structure_hints() -> None:
    aliases = parse_alias_table({"characters": [{"canonical": "Baoyu", "aliases": ["宝玉"]}]})
    stuck = _stuck([StuckCharacter(name="宝玉", function="protagonist")])

    query = build_scene_query(stuck, aliases)

    assert "Baoyu" in query and "宝玉" in query
    assert "protagonist" in query
    assert "relationship_turn" in query
    assert "不能靠巧合" in query


def test_rerank_boosts_genre_and_character_presence() -> None:
    stuck = _stuck([StuckCharacter(name="宝玉", function="protagonist")])
    plain = _hit(_scene("a", "a street at night", genre="Sci-Fi"))
    matching = _hit(_scene("b", "宝玉站在灯下", genre="Drama", characters=("宝玉",)), score=0.4)

    ranked = rerank([plain, matching], stuck)

    assert ranked[0].scene.scene_id == "b"
    assert "genre match" in ranked[0].reasons
    assert any("characters" in reason for reason in ranked[0].reasons)


def test_character_overlap_compares_normalized_canonical_names() -> None:
    # both sides are canonicalised upstream (parse + index build); compare after normalise
    stuck = _stuck([StuckCharacter(name="Baoyu", function="protagonist")])
    hit = _hit(_scene("a", "灯下", characters=("baoyu",)))

    ranked = rerank([hit], stuck)

    assert any("characters" in reason for reason in ranked[0].reasons)


def test_mmr_prefers_a_different_scene_when_scores_are_close() -> None:
    near_duplicate = _hit(_scene("near", "same"), score=0.50, vector=(1.0, 0.0))
    duplicate = _hit(_scene("dup", "same"), score=0.49, vector=(0.99, 0.01))
    different = _hit(_scene("diff", "other"), score=0.45, vector=(0.0, 1.0))

    selected = mmr_select([near_duplicate, duplicate, different], top_k=2, mmr_lambda=0.7)

    assert [item.scene.scene_id for item in selected] == ["near", "diff"]


def test_retrieve_scenes_returns_requested_size() -> None:
    units = [_scene(f"s{index}", f"text {index}", work_id=f"w{index}") for index in range(5)]
    index = SceneIndex(units, [[1.0, float(index % 2)] for index in range(5)])
    stuck = _stuck([StuckCharacter(name="宝玉", function="protagonist")])

    hits = retrieve_scenes(
        index,
        stuck,
        [1.0, 0.0],
        parse_alias_table({}),
        top_k=3,
        candidate_k=5,
    )

    assert len(hits) == 3


def test_mmr_work_cap_trims_repeated_works_and_fills_from_others() -> None:
    hits = [_hit(_scene(f"a{index}", f"a{index}", work_id="a")) for index in range(4)]
    hits += [_hit(_scene(f"b{index}", f"b{index}", work_id="b")) for index in range(3)]
    hits += [_hit(_scene("c0", "c0", work_id="c"))]

    picked = mmr_select(hits, top_k=5, mmr_lambda=1.0, work_cap=2)

    assert [hit.scene.scene_id for hit in picked] == ["a0", "a1", "b0", "b1", "c0"]


def test_mmr_work_cap_can_be_disabled() -> None:
    hits = [_hit(_scene(f"a{index}", f"a{index}", work_id="a")) for index in range(4)]

    picked = mmr_select(hits, top_k=3, mmr_lambda=1.0, work_cap=None)

    assert [hit.scene.scene_id for hit in picked] == ["a0", "a1", "a2"]


def test_mmr_work_cap_equals_ordering_everything_then_trimming() -> None:
    hits = [
        _hit(_scene("a1", "a1", work_id="a"), score=0.9, vector=(1.0, 0.0)),
        _hit(_scene("a2", "a2", work_id="a"), score=0.88, vector=(1.0, 0.02)),
        _hit(_scene("b1", "b1", work_id="b"), score=0.85, vector=(0.2, 1.0)),
        _hit(_scene("b2", "b2", work_id="b"), score=0.8, vector=(0.21, 1.0)),
        _hit(_scene("c1", "c1", work_id="c"), score=0.75, vector=(1.0, 1.0)),
    ]

    ordered = mmr_select(hits, top_k=len(hits), mmr_lambda=0.7)
    counts: Counter[str] = Counter()
    trimmed: list[SceneHit] = []
    for hit in ordered:
        work = hit.scene.work_id
        if counts[work] >= 1:
            continue
        counts[work] += 1
        trimmed.append(hit)
        if len(trimmed) >= 2:
            break

    assert [hit.scene.scene_id for hit in mmr_select(hits, 2, 0.7, work_cap=1)] == [
        hit.scene.scene_id for hit in trimmed
    ]


def test_retrieve_scenes_caps_slots_per_work() -> None:
    units: list[SceneUnit] = []
    vectors: list[list[float]] = []
    for work in ("a", "b", "c"):
        for index in range(3):
            units.append(_scene(f"{work}{index}", f"{work} text {index}", work_id=work))
            vectors.append([1.0, float(index)])
    index = SceneIndex(units, vectors)
    stuck = _stuck([StuckCharacter(name="宝玉", function="protagonist")])

    hits = retrieve_scenes(
        index,
        stuck,
        [1.0, 0.0],
        parse_alias_table({}),
        top_k=5,
        candidate_k=9,
        work_cap=2,
    )

    assert len(hits) == 5
    counts = Counter(hit.scene.work_id for hit in hits)
    assert max(counts.values()) <= 2


def test_retrieve_scenes_without_cap_lets_one_work_fill_the_list() -> None:
    units = [_scene(f"s{index}", f"text {index}", work_id="w") for index in range(6)]
    index = SceneIndex(units, [[1.0, float(index)] for index in range(6)])
    stuck = _stuck([StuckCharacter(name="宝玉", function="protagonist")])

    hits = retrieve_scenes(
        index,
        stuck,
        [1.0, 0.0],
        parse_alias_table({}),
        top_k=4,
        candidate_k=6,
        work_cap=None,
    )

    assert len(hits) == 4


def test_raw_suggestion_prompt_numbers_each_scene() -> None:
    stuck = _stuck([StuckCharacter(name="宝玉", function="protagonist")])
    scenes = [
        _hit(_scene("a", "第一场原文", heading="第1场"), 0.5),
        _hit(_scene("b", "第二场原文")),
    ]

    messages = build_raw_suggestion_messages(stuck, scenes)
    user = messages[1]["content"]

    assert "[1] Work a | 第1场" in user
    assert "[2] Work b | SC 1" in user
    assert "第一场原文" in user


def test_binding_keeps_only_quotes_found_in_the_scene() -> None:
    scenes = [_hit(_scene("a", "宝玉把帕子塞进袖子里。"), 0.5)]
    drafts = [
        SuggestionDraft(
            precedent_index=1,
            next_node="他把帕子收起来。",
            character_behavior_logic="不解释。",
            emotional_tone="克制",
            transfer_rationale="同样的动作替代对白。",
            reference_quote="宝玉把帕子塞进袖子里。",
        ),
        SuggestionDraft(
            precedent_index=1,
            next_node="他转身离开。",
            character_behavior_logic="回避。",
            emotional_tone="冷",
            transfer_rationale="同样的退场。",
            reference_quote="这句原文根本不存在。",
        ),
        SuggestionDraft(
            precedent_index=9,
            next_node="无效先例。",
            character_behavior_logic="-",
            emotional_tone="-",
            transfer_rationale="-",
        ),
    ]

    bound = bind_raw_suggestions(drafts, scenes)

    assert len(bound) == 2
    assert bound[0].reference_quote == "宝玉把帕子塞进袖子里。"
    assert bound[0].corpus_reference == "Work a · SC 1"
    assert bound[1].reference_quote is None


def test_excerpt_windows_around_the_cited_quote() -> None:
    from canonguard.plot.scene_index import SceneUnit, scene_excerpt_around

    scene = SceneUnit(
        scene_id="x",
        work_id="w",
        work_title="W",
        language="zh",
        genre="Drama",
        scene_no=1,
        heading="SC",
        text="前情铺垫。" * 80 + "宝玉把帕子塞进袖子里，没有说话。" + "后文补充。" * 80,
    )

    excerpt, highlight = scene_excerpt_around(scene, "宝玉把帕子塞进袖子里，没有说话。", 500)

    assert highlight == "宝玉把帕子塞进袖子里，没有说话。"
    assert highlight in excerpt
    assert len(excerpt) <= 502  # window plus the two ellipses


def test_quote_lookup_tolerates_spacing_and_punctuation() -> None:
    from canonguard.plot.scene_index import locate_quote

    text = "宝玉 把帕子塞进袖子里， 没有说话。"
    span = locate_quote(text, "宝玉把帕子塞进袖子里没有说话")

    assert span is not None
    start, end = span
    assert text[start:end].startswith("宝玉")
    assert text[start:end].endswith("说话")


def test_missing_quote_falls_back_to_a_plain_excerpt() -> None:
    from canonguard.plot.scene_index import SceneUnit, scene_excerpt_around

    scene = SceneUnit(
        scene_id="x",
        work_id="w",
        work_title="W",
        language="zh",
        genre="Drama",
        scene_no=1,
        heading="SC",
        text="只有一段原文。",
    )

    excerpt, highlight = scene_excerpt_around(scene, "不存在的引文", 500)

    assert excerpt == "只有一段原文。"
    assert highlight is None


def test_genre_affinity_uses_primary_and_specific_tags() -> None:
    stuck = _stuck([], genre="Drama")

    assert genre_affinity(stuck, "Drama, Adventure")[0] == 0
    assert genre_affinity(stuck, "Crime, Thriller, Drama")[0] == 2
    assert genre_affinity(stuck, "Science Fiction, Action")[0] == 3


def test_genre_affinity_finds_specific_overlap_before_ubiquitous() -> None:
    stuck = _stuck([], genre="Comedy, Family, Drama")

    assert genre_affinity(stuck, "Comedy, Drama")[0] == 0
    assert genre_affinity(stuck, "Family, Adventure")[0] == 1
    assert genre_affinity(stuck, "Crime, Thriller, Drama")[0] == 2


def test_rerank_specificity_promotes_primary_genre() -> None:
    stuck = _stuck([], genre="Drama")
    hits = [
        _hit(_scene("a", "a", genre="Science Fiction, Action")),
        _hit(_scene("b", "b", genre="Drama, Adventure")),
    ]

    ranked = rerank(hits, stuck, genre_prior="specificity")

    assert ranked[0].scene.scene_id == "b"


def test_default_primary_bonus_balances_genre_against_relevance() -> None:
    """Candidate scores now share one fused scale, so the genre prior is the only lever.

    The RRF values are real magnitudes: 0.0164 is a pool peak (rank 1), 0.0100 a
    global rank ~40, and a quota pick lands near 0.0067 (rank ~90).
    """
    stuck = _stuck([], genre="Crime")
    weak_match = _hit(_scene("weak", "w", genre="Crime, Thriller"), score=0.0067)
    mid_mismatch = _hit(_scene("mid", "m", genre="Drama"), score=0.0100)
    top_mismatch = _hit(_scene("top", "t", genre="Drama"), score=0.0164)

    promoted = rerank([mid_mismatch, weak_match], stuck, genre_prior="specificity")
    assert promoted[0].scene.scene_id == "weak"

    # ... but the prior stays soft: the best-matched scene in the corpus still loses
    held = rerank([top_mismatch, weak_match], stuck, genre_prior="specificity")
    assert held[0].scene.scene_id == "top"


def test_genre_quota_appends_same_genre_scenes_missed_globally() -> None:
    units = [_scene(f"c{index}", "crime", genre="Crime, Thriller") for index in range(3)]
    units.append(_scene("d0", "crime drama", genre="Drama, Adventure"))
    index = SceneIndex(units, [[1.0, 0.0]] * 4)

    hits = index.search("crime", [1.0, 0.0], top_k=2, genre_quota=("drama", 5))

    assert [hit.scene.scene_id for hit in hits] == ["c0", "c1", "d0"]
    # one ranking, two slices: the appended scene cannot outscore a global pick
    assert hits[2].score <= hits[1].score


def test_genre_quota_does_not_repeat_a_global_pick() -> None:
    units = [_scene(f"c{index}", "crime", genre="Crime, Thriller") for index in range(3)]
    units.append(_scene("d0", "crime drama", genre="Drama, Adventure"))
    index = SceneIndex(units, [[1.0, 0.0]] * 4)

    hits = index.search("crime", [1.0, 0.0], top_k=4, genre_quota=("drama", 5))

    assert len({hit.scene.scene_id for hit in hits}) == len(hits) == 4


def test_candidate_pool_genre_recall_pulls_in_filtered_scenes() -> None:
    units = [_scene(f"c{index}", "crime", genre="Crime, Thriller") for index in range(3)]
    units.append(_scene("d0", "zzz", genre="Drama, Adventure"))
    index = SceneIndex(units, [[1.0, 0.0], [1.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    stuck = _stuck([], genre="Drama")

    pool = candidate_pool(
        index,
        "crime",
        [1.0, 0.0],
        stuck,
        candidate_k=2,
        genre_extra=5,
        genre_recall=True,
    )

    assert "d0" in {hit.scene.scene_id for hit in pool}


def test_scene_index_roundtrips_with_split_vectors(tmp_path) -> None:
    units = [_scene(f"s{index}", f"text {index}", work_id=f"w{index}") for index in range(3)]
    index = SceneIndex(units, [[float(index), 0.0, 1.0] for index in range(3)])
    path = tmp_path / "index.json"

    index.save(path)

    assert (tmp_path / "index.vectors.f32").exists()
    loaded = SceneIndex.load(path)
    assert loaded.dim == 3
    assert [unit.scene_id for unit in loaded.units] == ["s0", "s1", "s2"]
    assert loaded.get("s1").text == "text 1"


def test_scene_index_loads_legacy_inline_vectors(tmp_path) -> None:
    payload = {
        "units": [
            {
                "scene_id": "s0",
                "work_id": "w",
                "work_title": "W",
                "language": "zh",
                "genre": "Drama",
                "scene_no": 1,
                "heading": "SC",
                "text": "旧格式",
                "characters": [],
            }
        ],
        "vectors": [[1.0, 2.0, 3.0]],
    }
    path = tmp_path / "index.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = SceneIndex.load(path)

    assert loaded.dim == 3
    assert loaded.get("s0").text == "旧格式"
