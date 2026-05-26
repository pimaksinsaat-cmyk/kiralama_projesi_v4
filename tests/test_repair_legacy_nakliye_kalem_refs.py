from scripts.repair_legacy_nakliye_kalem_refs import (
    DONUS,
    GIDIS,
    STATUS_AMBIGUOUS,
    STATUS_CONFLICT,
    STATUS_UNMATCHED,
    STATUS_UPDATE,
    KalemInfo,
    LegacyNakliyeInfo,
    decide_group_repairs,
)
from decimal import Decimal


def kalem(kalem_id, *tokens, gidis_satis="0.00", donus_satis="0.00"):
    return KalemInfo(
        kalem_id,
        tuple(("equipment_code", token) for token in tokens),
        Decimal(gidis_satis),
        Decimal(donus_satis),
    )


def nakliye(nakliye_id, guzergah, direction=GIDIS, tutar="0.00"):
    return LegacyNakliyeInfo(
        id=nakliye_id,
        kiralama_id=10,
        form_no="PF-TEST",
        direction=direction,
        old_aciklama=f"{direction}: PF-TEST",
        guzergah=guzergah,
        tutar=Decimal(tutar),
    )


def test_single_legacy_single_kalem_uses_single_kalem_fallback():
    decisions = decide_group_repairs([nakliye(1, "kod gecmeyen rota")], [kalem(101, "PM01")])

    assert len(decisions) == 1
    assert decisions[0].status == STATUS_UPDATE
    assert decisions[0].matched_kalem_id == 101
    assert decisions[0].match_reason == "single_kalem"
    assert decisions[0].new_aciklama == "Gidiş: PF-TEST #101"


def test_two_legacy_two_kalem_uses_greedy_unique_assignments():
    decisions = decide_group_repairs(
        [
            nakliye(1, "PM11 Ikitelli subesinden musterisine goturuldu"),
            nakliye(2, "PM21 Ikitelli subesinden musterisine goturuldu"),
        ],
        [kalem(101, "PM11"), kalem(102, "PM21")],
    )

    assert [d.status for d in decisions] == [STATUS_UPDATE, STATUS_UPDATE]
    assert {d.matched_kalem_id for d in decisions} == {101, 102}
    assert {d.new_aciklama for d in decisions} == {
        "Gidiş: PF-TEST #101",
        "Gidiş: PF-TEST #102",
    }


def test_two_legacy_same_kalem_blocks_second_as_unmatched():
    decisions = decide_group_repairs(
        [
            nakliye(1, "PM11 Ikitelli subesinden musterisine goturuldu"),
            nakliye(2, "PM11 Ikitelli subesinden musterisine goturuldu"),
        ],
        [kalem(101, "PM11"), kalem(102, "PM21")],
    )

    assert decisions[0].status == STATUS_UPDATE
    assert decisions[1].status == STATUS_UNMATCHED


def test_multi_kalem_without_route_signal_is_unmatched():
    decisions = decide_group_repairs(
        [nakliye(1, "kod gecmeyen rota")],
        [kalem(101, "PM11"), kalem(102, "PM21")],
    )

    assert decisions[0].status == STATUS_UNMATCHED


def test_multi_kalem_without_route_signal_can_use_unique_amount_match():
    decisions = decide_group_repairs(
        [nakliye(1, "Dis Ekipman musterisine goturuldu", tutar="2500.00")],
        [
            kalem(101, gidis_satis="2500.00"),
            kalem(102, "PM21", gidis_satis="0.00"),
        ],
    )

    assert decisions[0].status == STATUS_UPDATE
    assert decisions[0].matched_kalem_id == 101
    assert decisions[0].match_reason == "amount_match"


def test_same_signal_for_multiple_kalem_is_ambiguous():
    decisions = decide_group_repairs(
        [nakliye(1, "PM11 Ikitelli subesinden musterisine goturuldu")],
        [kalem(101, "PM11"), kalem(102, "PM11")],
    )

    assert decisions[0].status == STATUS_AMBIGUOUS


def test_short_token_does_not_match_by_itself():
    decisions = decide_group_repairs(
        [nakliye(1, "AB musterisine goturuldu")],
        [kalem(101, "AB"), kalem(102, "PM21")],
    )

    assert decisions[0].status == STATUS_UNMATCHED


def test_donus_uses_same_matching_rules():
    decisions = decide_group_repairs(
        [nakliye(1, "PM11 musteriden subeye getirildi", direction=DONUS)],
        [kalem(101, "PM11"), kalem(102, "PM21")],
    )

    assert decisions[0].status == STATUS_UPDATE
    assert decisions[0].new_aciklama == "Dönüş: PF-TEST #101"


def test_existing_new_description_conflict_blocks_apply():
    decisions = decide_group_repairs(
        [nakliye(1, "PM11 Ikitelli subesinden musterisine goturuldu")],
        [kalem(101, "PM11")],
        existing_descriptions={(10, "Gidiş: PF-TEST #101"): {99}},
    )

    assert decisions[0].status == STATUS_CONFLICT
