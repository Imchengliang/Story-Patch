from pathlib import Path

from canonguard.plot.stage_loader import (
    discover_movies,
    load_movie_catalog,
    load_stage_movie,
    normalize_episode,
    probe_movie,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "stage"
REAL_MOVIE = FIXTURE_ROOT / "Chinese" / "realshape_movie"


def test_discover_movies_finds_demo() -> None:
    movies = discover_movies(FIXTURE_ROOT)
    languages = {path.name: language for path, language in movies}
    assert languages.get("demo_movie") == "zh"


def test_load_stage_movie_maps_fields() -> None:
    movie = load_stage_movie(FIXTURE_ROOT / "Chinese" / "demo_movie", "zh")
    assert movie.title == "demo_movie"
    assert len(movie.script_scenes) == 2
    assert len(movie.episodes) == 2

    first = movie.episodes[0]
    assert first.episode_id == "ep1"
    assert first.summary == "宝玉与黛玉因旧帕起争执。"
    assert first.event_texts == ("宝玉赠帕", "黛玉多心")
    assert first.scene_refs == (1,)
    assert first.characters == ("宝玉", "黛玉")
    assert first.narrative_function == "relationship_turn"

    second = movie.episodes[1]
    assert second.episode_id == "ep2"
    assert second.event_texts == ("众人说笑",)
    assert second.scene_refs == (2,)
    assert second.characters == ("宝玉",)
    assert second.narrative_function is None


def test_typo_relation_filename_is_resolved() -> None:
    movie = load_stage_movie(FIXTURE_ROOT / "Chinese" / "demo_movie", "zh")
    assert len(movie.relations) == 1
    relation = movie.relations[0]
    assert (relation.source, relation.target, relation.relation) == (
        "ep1",
        "ep2",
        "causes",
    )
    assert relation.confidence == 0.8
    assert movie.causality is not None


def test_characters_loaded_from_icrp_dir() -> None:
    movie = load_stage_movie(FIXTURE_ROOT / "Chinese" / "demo_movie", "zh")
    by_name = {character.name: character for character in movie.characters}
    assert set(by_name) == {"宝玉", "黛玉"}
    assert by_name["宝玉"].role == "protagonist"
    assert by_name["黛玉"].role == "love_interest"
    assert by_name["黛玉"].relations == ("宝玉",)


def test_probe_reports_resolved_files_and_schema() -> None:
    probe = probe_movie(FIXTURE_ROOT / "Chinese" / "demo_movie")
    assert probe["character_dir"] == "ICRP"
    assert probe["kinds"]["script"]["resolved"] == "script.json"
    assert probe["kinds"]["relations"]["resolved"] == "episde_relations.json"
    assert probe["kinds"]["episodes"]["schema"]["episodes"]["len"] == 2
    assert probe["kinds"]["extraction"]["schema"]["scenes"]["len"] == 0


def test_normalize_episode_defaults_id() -> None:
    episode = normalize_episode({}, 3)
    assert episode.episode_id == "episode_3"
    assert episode.summary == ""
    assert episode.event_texts == ()
    assert episode.scene_refs == ()


def test_real_schema_episode_and_relations() -> None:
    movie = load_stage_movie(REAL_MOVIE, "zh")
    assert len(movie.episodes) == 2

    episode = movie.episodes[0]
    assert episode.episode_id == "ep_a"
    assert episode.summary == "宝玉独坐，心事重重。"
    assert episode.event_texts == ("宝玉独坐",)
    assert episode.document_refs == ("scene_1_part_1",)

    assert len(movie.relations) == 1
    relation = movie.relations[0]
    assert (relation.source, relation.target, relation.relation) == (
        "ep_a",
        "ep_b",
        "precedes",
    )
    assert relation.confidence == 0.9
    assert relation.reason == "先后顺序"
    assert relation.source_documents == ("scene_1_part_1",)


def test_icrp_per_character_dirs() -> None:
    movie = load_stage_movie(REAL_MOVIE, "zh")
    by_name = {character.name: character for character in movie.characters}
    assert set(by_name) == {"宝玉", "黛玉"}
    assert by_name["宝玉"].traits == ("多情", "敏感")
    assert by_name["宝玉"].constraints == ("不可粗鲁",)
    assert by_name["宝玉"].relations == ("黛玉",)


def test_catalog_title_and_genres() -> None:
    catalog = load_movie_catalog(FIXTURE_ROOT)
    assert "realshape_movie" in catalog
    movie = load_stage_movie(REAL_MOVIE, "zh", info=catalog["realshape_movie"])
    assert movie.title == "示例影片"
    assert movie.genres == ("Drama", "Romance")
