from scripts.run_v18_proposition_campaign import run


def test_v18_proposition_campaign_has_no_false_pass_or_false_block():
    result = run(20)
    assert result["verdict"] == "PASS"
    assert result["total_cases"] == result["correct"] == 100
    assert result["false_pass"] == result["false_block"] == 0
